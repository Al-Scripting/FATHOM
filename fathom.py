"""FATHOM: helpful, not omniscient. Telemetry -> situation vector -> persona -> PDA hint -> voice.

Run beside the game:  python fathom.py            (local Ollama model, reads telemetry.json from the UE4SS mod)
                      python fathom.py --claude   (Anthropic API, needs ANTHROPIC_API_KEY)
                      python fathom.py --offline  (template fallback only)
Opens the live dashboard at http://127.0.0.1:8765 and records every frame to sessions/<start>.jsonl.
"""

from __future__ import annotations

import functools
import http.server
import json
import random
import sys
import threading
import time
import urllib.request
import webbrowser
from collections import deque
from pathlib import Path
from typing import Any, Callable

import pda_voice

HERE = Path(__file__).parent
TELEMETRY = HERE / "telemetry.json"
TRACE = HERE / "trace.jsonl"
SESSIONS = HERE / "sessions"
DASHBOARD_PORT = 8765

OLLAMA_MODEL = "gemma3:4b"  # llama3.2:3b measured 0.23 s but invented readings in 30% of lines
OLLAMA_URL = "http://127.0.0.1:11434/api/chat"  # not localhost: the IPv6 attempt costs 2 s on Windows
OLLAMA_OPTIONS = {"num_predict": 30, "temperature": 0.3, "num_ctx": 1024}  # tiny KV cache, stays on GPU
CLAUDE_MODEL = "claude-opus-5"
BUDGET_S = 2.5  # in-game the GPU is shared with the game: 1.0 to 1.6 s per hint, vs 0.25 s in the sim
COOLDOWN_S = 10.0
MAX_WORDS = 18

# Thresholds. Oxygen is a fraction of the largest capacity seen this session (45 s bare, 120 s with a tank), because
# the game's own PDA warns at 25%: FATHOM speaks before it, then again only when it is dire.
LOW_O2_FRAC = 0.40
CRIT_O2_FRAC = 0.12
O2_MAX_MIN = 45.0
THREAT_M = 60.0
CONTACT_M = 20.0
DEEP_M = 200.0
DARK_M = 250.0  # below this it is dark whatever the hour
LOST_M = 1500.0  # the lifepod sits 2 km from ordinary play in Subnautica 2
AIR_SOURCE_M = 40.0  # an oxygen plant, tank, generator or vehicle this close changes the oxygen advice
NIGHT = (19.5, 6.0)  # game hours
SURVIVAL_PRIORITY = 2.0  # life outranks the way home two to one
ASCENT_MPS = 2.0  # ponytail: swim-up speed without fins; calibrate from a logged ascent
TTC_NEAR_S = 6.0  # a creature this many seconds away is near, whatever the distance
TTC_CONTACT_S = 2.0
# Zones of dread: (outer range, name, dread per second). Vague while vagueness costs nothing, concrete at contact.
ZONES = [(CONTACT_M, "contact", 1 / 40), (THREAT_M, "near", 1 / 120), (2 * THREAT_M, "presence", 1 / 300)]
PHANTOM_DREAD = 0.8  # above this the PDA may report a contact that is not there
PHANTOM_P = 0.35  # chance per ambient opportunity
PHANTOM_MAX = 1  # per session: once is a story, twice is a bug

# Dread: 0 to 1, rises the longer the dive goes wrong, only recovers at the surface or by a structure.
DREAD_DEEP_PER_S = 1 / 600  # ten minutes below DEEP_M to max out on depth alone
DREAD_DARK_PER_S = 1 / 900  # night, or below DARK_M
DREAD_PER_HINT = 0.15  # every crisis the PDA had to speak about
DREAD_DECAY_PER_S = 1 / 120  # two minutes at the surface or by a structure to calm down
AMBIENT_S = 180.0  # quiet this long, deep, with dread high: one unprompted line
AMBIENT_DREAD = 0.6
TONES = [(0.33, "Tone: a calm instrument."), (0.66, "Tone: clipped. Shorter than usual."),
         (9.0, "Tone: flat and factual about a reading that should not be there. Report the reading, not a feeling.")]

STYLES = {
    "survivor": "Terse imperative. The single most urgent thing, nothing else.",
    "navigator": "One orientation cue tied to what the diver did: their depth, the way they came, the light. No bearing.",
    "explorer": "One plain observation about the surroundings, stated as a sensor reading.",
}
SYSTEM = (
    "You are the PDA of a lone diver on an alien ocean world: a diagnostic instrument that reports readings and "
    f"gives one instruction. Reply with one line of at most {MAX_WORDS} words and nothing else: no quotes, no name, "
    "no explanation. Plain English. Short declarative sentences. No metaphor, no poetry, no adjectives about "
    "darkness or size. Never give bearings, coordinates, numbers, or species names. Never reassure. Examples of "
    "the register:\n"
    "Oxygen critical. Ascend.\n"
    "Detecting a leviathan class lifeform in the region. Are you certain whatever you're doing is worth it?\n"
    "Acoustic contact. Unclassified.\n"
    "Large biomass reading. Source unresolved.\n"
    "The last known structure is behind you, and above.\n"
    "Persona: {persona}. {style} {tone} Say only what the situation says. Do not invent equipment, places, or "
    "readings. No numbers."
)
# A small model reaches for these when told to be ominous. They are poetry, not readings; the line is discarded.
PURPLE = {"stirs", "stir", "breathes", "breathe", "consumes", "consume", "devours", "devour", "abyss", "void",
          "whisper", "whispers", "lurks", "lurking", "shadow", "shadows", "darkness", "eternal", "ancient",
          "hunger", "hungers", "black", "blackness", "vast", "maw", "dread", "nightmare", "watches", "watching"}
READY = "Companion link established. Monitoring vitals and surroundings."
# Critical topics never wait for the model or the synthesizer: the template plays from the cache at once.
CRITICAL = {"oxygen_critical", "threat_contact", "phantom"}
FALLBACK = {
    "oxygen": "Oxygen low. Plan your ascent.",
    "oxygen_critical": "Oxygen critical. Ascend.",
    "threat": "Something large is close. Stay still, or leave quietly.",
    "threat_contact": "Contact. Do not move.",
    "lost": "No known structures in range. Retrace your descent.",
    "depth": "Depth exceeds suit rating. Watch your oxygen.",
    "ambient": "Acoustic contact. Unclassified.",
    "phantom": "Acoustic contact. Bearing unresolved.",  # the one lie the PDA tells, at high dread, once
    None: "Environmental change detected.",
}
FALLBACK_AIR_NEAR = {  # same topics when a source of air is within AIR_SOURCE_M
    "oxygen": "Oxygen low. A source of air is within reach.",
    "oxygen_critical": "Oxygen critical. Replenish now.",
}
FALLBACK_NO_SURFACE = {  # the surface is further than the air will carry the diver
    "oxygen": "Oxygen low. The surface is beyond your air.",
    "oxygen_critical": "Oxygen critical. The surface is out of reach.",
}
TOPIC = {"oxygen": "the oxygen", "oxygen_critical": "the oxygen", "threat": "the creature",
         "threat_contact": "the creature", "lost": "the way back", "depth": "the depth",
         "ambient": "what it senses in the dark", "phantom": "what it senses in the dark", None: "the situation"}
# Unprompted lines are not generated: a 4B model asked to be unsettling writes poetry, and asked to be plain writes
# nothing. These are plain readouts that unsettle by implication, the original PDA's trick. Rotated without repeats.
POOLED = {"ambient"}
AMBIENT_LINES = [
    "Acoustic contact. Unclassified.",
    "Large biomass reading. Source unresolved.",
    "Motion on the sonar. Nothing on the visual.",
    "Something passed the sonar edge. Contact lost.",
    "Water temperature rising. No known source.",
    "Biological signature matches nothing on record.",
    "Multiple contacts. Range indeterminate.",
    "Ambient light below detection. Switching to sonar.",
    "Vital signs elevated. Cause unknown.",
    "Sensor sweep incomplete. Retrying.",
    "Recording. In case.",
]
# A model line must be about its topic. One of these words, or the template plays.
TOPIC_WORDS = {
    "oxygen": {"oxygen", "air", "ascend", "ascent", "breath", "breathing", "surface", "replenish", "reserve", "tank"},
    "threat": {"contact", "movement", "motion", "lifeform", "biomass", "signature", "creature", "large", "sonar",
               "proximity", "still", "evasive", "predator", "hostile", "approaching"},
    "lost": {"structure", "structures", "descent", "path", "light", "surface", "way", "return", "route", "heading",
             "retrace", "ascend", "back", "lifepod", "shelter"},
    "depth": {"pressure", "depth", "hull", "crush", "ascend", "ascent", "descent", "deep", "suit", "rating"},
}
BEARINGS = {"left", "right", "north", "south", "east", "west", "degrees", "meters", "metres", "percent"}
# Flag -> topic, most urgent first: when several flags rise on the same frame the first wins.
FLAG_TOPIC = {"threat_contact": "threat_contact", "oxygen_critical": "oxygen_critical", "threat_near": "threat",
              "low_oxygen": "oxygen", "player_lost": "lost", "deep_zone": "depth"}
SURVIVAL_FLAGS = ("threat_contact", "oxygen_critical", "threat_near", "low_oxygen")


def clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def band(value: float | None, steps: list[tuple[float, str]], above: bool = False) -> str | None:
    """First label whose threshold the value crosses. Withholding numbers happens here, not in the model."""
    if value is None:
        return None
    for limit, label in steps:
        if (value > limit) if above else (value < limit):
            return label
    return None


def is_dark(t: dict[str, Any]) -> bool:
    tod = t.get("time_of_day")
    night = tod is not None and (tod >= NIGHT[0] or tod < NIGHT[1])
    return night or (t.get("depth") or 0.0) > DARK_M


def air_near(t: dict[str, Any]) -> bool:
    d = t.get("air_dist")
    return d is not None and d < AIR_SOURCE_M


def can_surface(t: dict[str, Any]) -> bool | None:
    """Whether the air left carries the diver to the surface at ASCENT_MPS. None without an oxygen reading."""
    if t.get("o2") is None:
        return None
    return t["o2"] * ASCENT_MPS >= max(0.0, t.get("depth") or 0.0)


def time_to_contact(td: float | None, closing: float) -> float | None:
    """Seconds until the nearest threat reaches the diver at the current closing speed, None if not closing."""
    if td is None or closing <= 0.5:
        return None
    return td / closing


def zone(td: float | None, ttc: float | None = None) -> tuple[str | None, float]:
    """(zone name, dread per second) for the nearest threat. Time to contact promotes a fast approach."""
    if td is None:
        return None, 0.0
    if ttc is not None and ttc < TTC_CONTACT_S:
        return ZONES[0][1], ZONES[0][2]
    if ttc is not None and ttc < TTC_NEAR_S:
        return ZONES[1][1], ZONES[1][2]
    for limit, name, rate in ZONES:
        if td < limit:
            return name, rate
    return None, 0.0


def describe(t: dict[str, Any], topic: str | None, o2max: float = O2_MAX_MIN) -> str:
    """Qualitative situation for the model. The model varies the phrasing, it never sees the numbers."""
    o2 = None if t.get("o2") is None else t["o2"] / o2max
    rel = t.get("threat_rel")
    parts = [
        band(o2, [(CRIT_O2_FRAC, "Oxygen is almost gone."), (LOW_O2_FRAC, "Oxygen is running out."), (0.7, "Oxygen is low.")]),
        "The surface is out of reach." if can_surface(t) is False else None,
        "A source of air is within reach." if air_near(t) and o2 is not None and o2 < 0.7 else None,
        band(t.get("threat_dist"), [(CONTACT_M, f"Something large is right beside the diver, {rel}." if rel
                                                else "Something large is right beside the diver."),
                                    (THREAT_M, "Something large is close."), (2 * THREAT_M, "Something large is nearby.")]),
        band(t.get("dist_home"), [(2 * LOST_M, "No known structure anywhere near."), (LOST_M, "Far from any known structure.")],
             above=True),
        band(t.get("depth"), [(400, "Beyond safe depth."), (DEEP_M, "Deep.")], above=True),
        "It is dark." if is_dark(t) else None,
    ]
    return " ".join([p for p in parts if p] + [f"Speak about {TOPIC[topic]}. One short line."])


def tone(dread: float) -> str:
    return next(label for limit, label in TONES if dread < limit)


def situation(t: dict[str, Any], o2max: float = O2_MAX_MIN, closing: float = 0.0) -> dict[str, Any]:
    """Flatten one telemetry frame into flags, persona weights, the winning persona and the dominant signal.
    `closing` is the nearest threat's approach speed in m/s; a fast approach is near before it is close."""
    o2, td, home = t.get("o2"), t.get("threat_dist"), t.get("dist_home")
    depth = t.get("depth") or 0.0
    o2f = None if o2 is None else o2 / o2max
    ttc = time_to_contact(td, closing)
    flags = {
        "threat_contact": td is not None and (td < CONTACT_M or (ttc is not None and ttc < TTC_CONTACT_S)),
        "oxygen_critical": o2f is not None and o2f < CRIT_O2_FRAC,
        "threat_near": td is not None and (td < THREAT_M or (ttc is not None and ttc < TTC_NEAR_S)),
        "low_oxygen": o2f is not None and o2f < LOW_O2_FRAC,
        "deep_zone": depth > DEEP_M,
        "player_lost": home is not None and home > LOST_M,
    }
    # Linear urgencies scaled so each flag threshold sits at 0.5. ponytail: tune against logged sessions
    signals = {
        "oxygen": clamp((2 * LOW_O2_FRAC - o2f) / (2 * LOW_O2_FRAC)) if o2f is not None else 0.0,
        "threat": clamp((2 * THREAT_M - td) / (2 * THREAT_M)) if td is not None else 0.0,
        "lost": clamp((home - LOST_M / 2) / LOST_M) if home is not None else 0.0,
        "depth": clamp((depth - DEEP_M) / DEEP_M),
    }
    survivor = max(signals["oxygen"], signals["threat"]) * SURVIVAL_PRIORITY
    navigator = signals["lost"]
    explorer = 1.0 - min(1.0, max(survivor, navigator))
    total = survivor + navigator + explorer
    weights = {"survivor": survivor / total, "navigator": navigator / total, "explorer": explorer / total}
    dominant = max(signals, key=signals.get)
    return {
        "flags": flags,
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "persona": max(weights, key=weights.get),  # survivor is first, so it wins ties
        "dominant": dominant if signals[dominant] > 0 else None,
    }


def why_speak(prev: dict[str, Any] | None, cur: dict[str, Any], last_spoke: float, now: float) -> str | None:
    """Silence is the default. Returns the topic to speak about: the most urgent flag that just rose, or, outside
    the cooldown, the dominant signal when the persona or the dominant signal changed. None means stay quiet."""
    if not any(cur["flags"].values()):
        return None
    rose = [FLAG_TOPIC[k] for k in FLAG_TOPIC if cur["flags"][k] and not (prev and prev["flags"][k])]
    if rose:
        return rose[0]
    if now - last_spoke >= COOLDOWN_S and (cur["persona"], cur["dominant"]) != (prev["persona"], prev["dominant"]):
        return cur["dominant"]
    return None


def ollama(body: dict[str, Any], timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(OLLAMA_URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def warm_ollama() -> None:
    """Load the model now so the first hint does not pay the load time. Empty messages = load only.
    Same options as the hint call: a different num_ctx makes Ollama reload the model, which costs seconds."""
    ollama({"model": OLLAMA_MODEL, "messages": [], "keep_alive": "30m", "options": OLLAMA_OPTIONS}, timeout=120)


@functools.cache
def claude() -> Any:
    import anthropic  # only needed with --claude

    return anthropic.Anthropic().with_options(timeout=BUDGET_S, max_retries=0)


def ask(llm: str, system: str, user: str) -> str:
    """One line from the selected backend. Raises on timeout, transport failure, or a non-text stop."""
    if llm == "ollama":
        r = ollama({"model": OLLAMA_MODEL, "stream": False, "keep_alive": "30m", "options": OLLAMA_OPTIONS,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, BUDGET_S)
        if r.get("done_reason") != "stop":
            raise ValueError(f"done_reason={r.get('done_reason')}")
        return r["message"]["content"]
    r = claude().messages.create(
        model=CLAUDE_MODEL,
        max_tokens=64,
        thinking={"type": "disabled"},  # ponytail: a short hint cannot afford thinking tokens
        output_config={"effort": "low"},
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if r.stop_reason != "end_turn":
        raise ValueError(f"stop_reason={r.stop_reason}")
    return " ".join(b.text for b in r.content if b.type == "text")


def template(topic: str | None, t: dict[str, Any]) -> str:
    """The fixed line for a topic, made concrete only where it must be: relation at contact, air and surface
    for oxygen. These are the only lines that may point anywhere."""
    if topic == "threat_contact" and t.get("threat_rel"):
        return f"Contact. {t['threat_rel'][0].upper()}{t['threat_rel'][1:]}. Do not move."
    if topic in FALLBACK_AIR_NEAR and air_near(t):
        if can_surface(t) is False and topic == "oxygen_critical":
            return "Oxygen critical. The surface is out of reach. Replenish now."
        return FALLBACK_AIR_NEAR[topic]
    if topic in FALLBACK_NO_SURFACE and can_surface(t) is False:
        return FALLBACK_NO_SURFACE[topic]
    return FALLBACK[topic]


def hint(
    t: dict[str, Any], sit: dict[str, Any], topic: str | None, llm: str | None, dread: float = 0.0,
    o2max: float = O2_MAX_MIN,
) -> tuple[str, str, float]:
    """Return (text, source, latency_s). Source is 'llm' inside the budget, else 'fallback'.
    Critical topics go straight to the template: those lines must play instantly."""
    start = time.perf_counter()
    if llm and topic not in CRITICAL:
        system = SYSTEM.format(persona=sit["persona"], style=STYLES[sit["persona"]], tone=tone(dread))
        try:
            text = ask(llm, system, describe(t, topic, o2max)).strip().strip('"')
            if any(c.isdigit() for c in text):  # the model was given no numbers, so any number is invented
                raise ValueError(f"invented a reading: {text!r}")
            words = set(text.lower().replace(",", " ").replace(".", " ").split())
            if BEARINGS & words:
                raise ValueError(f"gave a bearing: {text!r}")
            if PURPLE & words:
                raise ValueError(f"went purple: {text!r}")
            if topic in TOPIC_WORDS and not TOPIC_WORDS[topic] & words:
                raise ValueError(f"off topic for {topic}: {text!r}")
            if 0 < len(text.split()) <= MAX_WORDS:
                return text, "llm", time.perf_counter() - start
            print(f"[fathom] {llm} over {MAX_WORDS} words: {text!r}", file=sys.stderr)
        except Exception as e:  # any backend failure falls through to the template; the PDA never goes silent
            print(f"[fathom] {llm} failed: {e!r}", file=sys.stderr)
    return template(topic, t), "fallback", time.perf_counter() - start


def speak(text: str, dread: float = 0.0) -> None:
    """PDA voice in the background so a synthesis never delays the next frame. Dread degrades the audio."""
    threading.Thread(target=pda_voice.say, args=(text, dread), daemon=True).start()


def append(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


class Fathom:
    """One instance per session. Feed frames to step(); it returns a hint record when it speaks, else None."""

    def __init__(
        self,
        llm: str | None = "ollama",
        speak_fn: Callable[[str, float], None] = speak,
        now: Callable[[], float] = time.monotonic,
        log: bool = True,
    ) -> None:
        self.llm, self.speak, self.now, self.log = llm, speak_fn, now, log
        self.prev: dict[str, Any] | None = None
        self.prev_t: float | None = None
        self.prev_td: float | None = None
        self.last_spoke = float("-inf")
        self.dread = 0.0
        self.o2max = O2_MAX_MIN
        self.phantoms = 0
        self.rng = random.Random()
        self.ambient_pool: list[str] = []
        self.frames: deque[dict[str, Any]] = deque(maxlen=600)  # five minutes at 2 Hz, for the dashboard
        self.hints: list[dict[str, Any]] = []
        self.session = SESSIONS / (time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
        if llm == "ollama":
            warm_ollama()

    def next_ambient(self) -> str:
        if not self.ambient_pool:
            self.ambient_pool = list(AMBIENT_LINES)
            self.rng.shuffle(self.ambient_pool)
        return self.ambient_pool.pop()

    def update_dread(self, t: dict[str, Any], now: float, zone_rate: float) -> None:
        dt = max(0.0, now - self.prev_t) if self.prev_t is not None else 0.0
        depth, home = t.get("depth") or 0.0, t.get("dist_home")
        if depth > DEEP_M:
            self.dread += DREAD_DEEP_PER_S * dt
        self.dread += zone_rate * dt
        if is_dark(t):
            self.dread += DREAD_DARK_PER_S * dt
        if depth < 5 or (home is not None and home < 100):
            self.dread -= DREAD_DECAY_PER_S * dt
        self.dread = clamp(self.dread)

    def step(self, t: dict[str, Any]) -> dict[str, Any] | None:
        if t.get("o2") is not None:
            self.o2max = max(self.o2max, t["o2"])
        now = self.now()
        td = t.get("threat_dist")
        dt = now - self.prev_t if self.prev_t is not None else 0.0
        closing = (self.prev_td - td) / dt if td is not None and self.prev_td is not None and dt > 0 else 0.0
        ttc = time_to_contact(td, closing)
        zone_name, zone_rate = zone(td, ttc)
        sit = situation(t, self.o2max, closing)
        self.update_dread(t, now, zone_rate)
        out = None
        topic = why_speak(self.prev, sit, self.last_spoke, now)
        quiet_and_deep = topic is None and (t.get("depth") or 0.0) > DEEP_M and now - self.last_spoke >= AMBIENT_S
        if quiet_and_deep and self.dread >= PHANTOM_DREAD and self.phantoms < PHANTOM_MAX and td is None \
                and self.rng.random() < PHANTOM_P:
            topic = "phantom"
            self.phantoms += 1
        elif quiet_and_deep and self.dread >= AMBIENT_DREAD:
            topic = "ambient"
        if topic:
            if topic in POOLED:
                text, source, latency = self.next_ambient(), "pool", 0.0
            else:
                text, source, latency = hint(t, sit, topic, self.llm, self.dread, self.o2max)
            self.last_spoke = now
            if topic not in ("ambient", "phantom"):
                self.dread = clamp(self.dread + DREAD_PER_HINT)
            out = {"t": t, **sit, "dread": round(self.dread, 3), "topic": topic, "text": text, "source": source,
                   "latency_s": round(latency, 3)}
            self.hints.append(out)
            if self.log:
                append(TRACE, out)
            self.speak(text, self.dread)
        # wall-clock t with sub-second resolution: the mod's own t is whole seconds and analyze.py needs spacing
        frame = {**t, "t": time.time(), "flags": sit["flags"], "weights": sit["weights"], "persona": sit["persona"],
                 "dominant": sit["dominant"], "dread": round(self.dread, 3), "o2max": self.o2max, "dark": is_dark(t),
                 "zone": zone_name, "closing": round(closing, 1), "ttc": None if ttc is None else round(ttc, 1),
                 "can_surface": can_surface(t),
                 "hint": out and {k: out[k] for k in ("topic", "text", "source", "latency_s")}}
        self.frames.append(frame)
        if self.log:
            append(self.session, frame)
        self.prev, self.prev_t, self.prev_td = sit, now, td
        return out


class Dashboard(http.server.BaseHTTPRequestHandler):
    fathom: Fathom

    def do_GET(self) -> None:
        if self.path == "/data":
            body = json.dumps({"frames": list(self.fathom.frames), "hints": self.fathom.hints[-40:]}).encode()
            ctype = "application/json"
        else:
            body = (HERE / "dashboard.html").read_bytes()
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


def serve_dashboard(fathom: Fathom) -> None:
    Dashboard.fathom = fathom
    server = http.server.ThreadingHTTPServer(("127.0.0.1", DASHBOARD_PORT), Dashboard)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webbrowser.open(f"http://127.0.0.1:{DASHBOARD_PORT}")


def backend(argv: list[str]) -> str | None:
    return None if "--offline" in argv else "claude" if "--claude" in argv else "ollama"


def main() -> None:
    fathom = Fathom(backend(sys.argv))
    pda_voice.prewarm([READY, *FALLBACK_AIR_NEAR.values(), *FALLBACK_NO_SURFACE.values(),
                       "Oxygen critical. The surface is out of reach. Replenish now.",
                       *(v for k, v in FALLBACK.items() if k)])
    serve_dashboard(fathom)
    print(f"FATHOM watching {TELEMETRY} ({fathom.llm or 'offline'}), dashboard http://127.0.0.1:{DASHBOARD_PORT}, "
          f"recording {fathom.session.name}")
    speak(READY)  # model warmed, dashboard up, recorder open: say so in the PDA voice
    mtime = 0.0
    while True:
        try:
            m = TELEMETRY.stat().st_mtime
            if m != mtime:
                mtime = m
                out = fathom.step(json.loads(TELEMETRY.read_text()))
                if out:
                    print(f"[{out['source']} {out['latency_s']}s {out['persona']}/{out['topic']} dread {out['dread']}] "
                          f"{out['text']}")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.25)


if __name__ == "__main__":
    main()
