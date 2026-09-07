"""The original Subnautica PDA voice: IVONA Amy through Lee23's filter chain, served by subnauticapdavoice.com.

Every distinct line is cached on disk by its text, so it costs the site one request, ever. About 5 s on a miss.
Falls back to the Windows voice when the site is unreachable, so the PDA never goes silent.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Iterable

SITE = "https://subnauticapdavoice.com"
CACHE = Path(__file__).parent / "voice_cache"
HEADERS = {"User-Agent": "FATHOM research prototype (cached, low volume)", "Content-Type": "application/json"}
WAIT_S = 45.0

_speaking = threading.Lock()  # one line at a time


def generate(text: str) -> Path:
    """Return a WAV of `text` in the PDA voice, fetching it from the site on a cache miss."""
    CACHE.mkdir(exist_ok=True)
    path = CACHE / (hashlib.sha1(text.encode("utf-8")).hexdigest()[:16] + ".wav")
    if path.exists():
        return path
    body = json.dumps({"input": {"message": text, "use_ssml": False, "voice_id": "pda"}}).encode()
    job = json.load(urllib.request.urlopen(urllib.request.Request(f"{SITE}/api/generate", body, HEADERS), timeout=30))
    if "job_id" not in job:
        raise RuntimeError(f"site refused: {job}")
    deadline = time.monotonic() + WAIT_S
    while True:
        req = urllib.request.Request(f"{SITE}/api/status/{job['job_id']}", headers=HEADERS)
        status = json.load(urllib.request.urlopen(req, timeout=30))
        if status.get("status") == "ready":
            break
        if status.get("status") == "error" or time.monotonic() > deadline:
            raise RuntimeError(f"site failed: {status}")
        time.sleep(1.0)
    url = status["url"] if status["url"].startswith("http") else SITE + status["url"]
    data = urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=30).read()
    if data[:4] != b"RIFF":
        raise RuntimeError("site returned something that is not a WAV")
    path.write_bytes(data)
    return path


def play(path: Path) -> None:
    cmd = f"(New-Object Media.SoundPlayer '{path}').PlaySync()"
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=True)


def sapi(text: str) -> None:
    """Windows built-in voice, the offline fallback."""
    p = subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", "[Console]::InputEncoding = [Text.Encoding]::UTF8; "
         "Add-Type -AssemblyName System.Speech; "
         "(New-Object System.Speech.Synthesis.SpeechSynthesizer).Speak([Console]::In.ReadToEnd())"],
        stdin=subprocess.PIPE,
    )
    assert p.stdin is not None
    p.stdin.write(text.encode("utf-8"))
    p.stdin.close()
    p.wait()


GLITCH_DREAD = 0.5  # below this the PDA sounds fine


def glitch(path: Path, dread: float) -> Path:
    """Degrade a cached line in proportion to dread: dropouts, stutters, a crushed patch, and near the top a cut.
    The cache stays clean; the degraded copy is rebuilt every time, so the same line never breaks the same way."""
    import random
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as w:
        rate, ch, width, raw = w.getframerate(), w.getnchannels(), w.getsampwidth(), w.readframes(w.getnframes())
    ms = lambda x: int(rate * x / 1000)  # noqa: E731
    if width != 2 or len(raw) < ms(800) * ch * 2:
        return path
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32).reshape(-1, ch)
    rng = random.Random()
    level = (dread - GLITCH_DREAD) / (1 - GLITCH_DREAD)
    for _ in range(1 + int(level * 5)):  # dropouts
        i = rng.randrange(ms(200), len(a) - ms(120))
        a[i:i + ms(rng.randint(15, 60))] = 0
    for _ in range(int(level * 3 + rng.random())):  # stutters
        n = ms(rng.randint(40, 90))
        i = rng.randrange(ms(100), len(a) - 5 * n)
        chunk = a[i:i + n].copy()
        for k in range(1, rng.randint(2, 4)):
            a[i + k * n:i + (k + 1) * n] = chunk
    if level > 0.5:  # crushed patch
        n = ms(rng.randint(150, 400))
        i = rng.randrange(0, len(a) - n)
        q = 2 ** (16 - rng.randint(5, 7))
        a[i:i + n] = np.round(a[i:i + n] / q) * q
    if level > 0.8 and rng.random() < 0.3:  # the line dies mid-sentence
        a = a[: int(len(a) * rng.uniform(0.55, 0.8))]
    out = CACHE / "glitched.wav"
    with wave.open(str(out), "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(a, -32768, 32767).astype(np.int16).tobytes())
    return out


def say(text: str, dread: float = 0.0) -> None:
    """Speak one line, blocking. PDA voice if the site answers, Windows voice otherwise."""
    with _speaking:
        try:
            path = generate(text)
            play(glitch(path, dread) if dread >= GLITCH_DREAD else path)
        except Exception as e:  # any failure on the network or the site: the line must still be heard
            print(f"[voice] PDA voice failed ({e!r}), using the Windows voice", file=sys.stderr)
            sapi(text)


def prewarm(lines: Iterable[str]) -> None:
    """Fetch fixed lines in the background so template fallbacks play instantly."""

    def run() -> None:
        for line in lines:
            try:
                generate(line)
            except Exception as e:
                print(f"[voice] prewarm failed for {line!r}: {e!r}", file=sys.stderr)

    threading.Thread(target=run, daemon=True).start()


if __name__ == "__main__":  # python pda_voice.py [--dread 0.9] some line
    args = sys.argv[1:]
    dread = float(args.pop(args.index("--dread") + 1)) if "--dread" in args else 0.0
    args = [a for a in args if a != "--dread"]
    say(" ".join(args) or "Oxygen critical. Ascend.", dread)
