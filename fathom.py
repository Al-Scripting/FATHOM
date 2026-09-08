"""FATHOM: helpful, not omniscient. Telemetry -> situation vector -> persona -> PDA hint -> voice.

Run beside the game:  python fathom.py            (local Ollama model, reads telemetry.json from the UE4SS mod)
                      python fathom.py --offline  (template fallback only)
Opens the live dashboard at http://127.0.0.1:8765 and records every frame to sessions/<start>.jsonl.
"""

from __future__ import annotations

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
OLLAMA_OPTIONS = {"num_predict": 30, "temperature": 0.2, "num_ctx": 1024}  # tiny KV cache, stays on GPU
BUDGET_S = 2.5  # in-game the GPU is shared with the game: 1.0 to 1.6 s per hint, vs 0.25 s in the sim
COOLDOWN_S = 20.0
MAX_WORDS = 18

# Thresholds. Oxygen is a fraction of the largest capacity seen this session (45 s bare, 120 s with a tank), because
# the game's own PDA warns at 25%: FATHOM speaks before it, then again only when it is dire.
LOW_O2_FRAC = 0.50  # early on purpose: the line, the model and the synthesizer all need a head start
CRIT_O2_FRAC = 0.15
O2_MAX_MIN = 45.0
THREAT_M = 100.0  # a leviathan this close is near
CONTACT_M = 30.0
PREDATOR_SCALE = 2.0  # a predator at 50 m reads like a leviathan at 100 m
DEEP_M = 200.0
DARK_M = 250.0  # below this it is dark whatever the hour
LOST_M = 1500.0  # the lifepod sits 2 km from ordinary play in Subnautica 2
AIR_SOURCE_M = 40.0  # an oxygen plant, tank, generator or vehicle this close changes the oxygen advice
NIGHT = (19.5, 6.0)  # game hours
SURVIVAL_PRIORITY = 2.0  # life outranks the way home two to one
ASCENT_MPS = 2.0  # ponytail: swim-up speed without fins; calibrate from a logged ascent
TTC_NEAR_S = 10.0  # a creature this many seconds away is near, whatever the distance
TTC_CONTACT_S = 4.0
PREFETCH_O2_MARGIN = 0.12  # write and synthesize the oxygen line this far above the threshold, so it is ready
PREFETCH_LOST_FRAC = 0.8  # same for the way back, at this fraction of LOST_M
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
TONES = [(0.33, "Tone: routine."), (0.66, "Tone: clipped. Shorter than usual."),
         (9.0, "Tone: a routine report of a reading that should not exist. Same pitch as a low battery.")]

STYLES = {
    "survivor": "One warning and one instruction. Nothing else.",
    "navigator": "One fact about the way back, framed as survival advice. No bearing.",
    "explorer": "One environmental reading, closed with an assessment, or with 'Reason unknown.'",
}
# The register is the Alterra PDA's: a survival instrument rebooted with one directive. It reports readings, issues
# verdicts and files paperwork in the same flat voice whatever the reading is. The humor is never stated; it is the
# gap between the fact and the tone. See docs/pda_register.md for the line set this was built from.
SYSTEM = (
    "You are the PDA of a lone survivor on an alien ocean world: a formal, impersonal survival instrument that "
    "reports readings and delivers verdicts. Its humor is deadpan and never stated. Reply with one line of at most "
    f"{MAX_WORDS} words and nothing else: no quotes, no name, no explanation.\n"
    "Use one of these shapes: 'Warning: <condition>.' / 'Caution: <condition>.' / 'Detecting <condition>.' / "
    "'Scans indicate <fact>.' / '<condition>. Assessment: <verdict>.' / '<fact>. Reason unknown.' / "
    "'Consider <action>.' Conditions are qualitative words: low, critical, reduced, increased, exceeded, unknown. "
    "Never a number, a percentage, a distance or a depth value. Institutional phrasing, present tense, no "
    "exclamation marks, no metaphor, no anatomy, no adjectives about darkness or size. Never give bearings, "
    "coordinates, or species names. Never reassure.\n"
    "Examples of the register:\n"
    "Warning: oxygen critical. Ascend.\n"
    "Caution: passing safe depth.\n"
    "Detecting increased local radiation levels. Continuing to monitor.\n"
    "Detecting multiple leviathan class lifeforms in the region. Are you certain whatever you're doing is worth it?\n"
    "Detecting unusually passive behavioral patterns in nearby predators. Reason unknown.\n"
    "Caution: scans show the digestive tracts of nearby lifeforms contain human tissues.\n"
    "Warning: entering ecological dead zone. Position logged.\n"
    "No known structures within range. Retracing your descent is a proven survival strategy.\n"
    "Persona: {persona}. {style} {tone} Say only what the situation says, in its own words. Do not invent "
    "equipment, places, anatomy or readings. No numbers of any kind."
)
# A model line must open the way the PDA opens. Anything else is not the PDA and falls to the template.
OPENERS = ("warning", "caution", "emergency", "attention", "detecting", "scans", "scan ", "lifeform", "oxygen",
           "vital", "local", "multiple", "no known", "assessment", "adding", "approaching", "depth", "pressure",
           "contact", "proximity", "environmental", "hull", "consider", "structural", "ambient", "biological",
           "acoustic", "unidentified", "large", "surface", "logging", "recording", "continuing", "reason")
# A small model reaches for these when told to be ominous. They are poetry, not readings; the line is discarded.
PURPLE = {"stirs", "stir", "breathes", "breathe", "consumes", "consume", "devours", "devour", "abyss", "void",
          "whisper", "whispers", "lurks", "lurking", "shadow", "shadows", "darkness", "eternal", "ancient",
          "hunger", "hungers", "black", "blackness", "vast", "maw", "dread", "nightmare", "watches", "watching",
          "escalation"}  # the last is the label the model is given, and must not read back
READY = "Link established. Emergency companion online. Primary directive: keep you alive on an alien world."
# Critical topics never wait for the model or the synthesizer: the template plays from the cache at once.
CRITICAL = {"oxygen_critical", "threat_contact", "phantom"}
FALLBACK = {
    "oxygen": "Caution: oxygen reserve low. Consider beginning your ascent.",
    "oxygen_critical": "Warning: oxygen critical. Ascend.",
    "threat": "Detecting a large lifeform in the vicinity. Assessment: avoid.",
    "threat_contact": "Warning: proximity contact. Remain still.",
    "lost": "No known structures within range. Retracing your descent is a proven survival strategy.",
    "depth": "Caution: passing safe depth.",
    "ambient": "Local acoustic activity exceeds baseline. Continuing to monitor.",
    "phantom": "Detecting a large lifeform in the vicinity. Bearing unresolved.",  # the one lie, at high dread, once
    None: "Environmental change detected. Explanation unclear at this time.",
}
FALLBACK_AIR_NEAR = {  # same topics when a source of air is within AIR_SOURCE_M
    "oxygen": "Caution: oxygen reserve low. A replenishment source is within reach.",
    "oxygen_critical": "Warning: oxygen critical. Replenish now.",
}
FALLBACK_NO_SURFACE = {  # the surface is further than the air will carry the diver
    "oxygen": "Caution: oxygen reserve low. Surface distance exceeds remaining supply.",
    "oxygen_critical": "Warning: oxygen critical. Surface distance exceeds remaining supply.",
}
NO_SURFACE_AIR_NEAR = "Warning: oxygen critical. Surface distance exceeds remaining supply. Replenish now."
TOPIC = {"oxygen": "the oxygen reserve", "oxygen_critical": "the oxygen reserve", "threat": "the lifeform",
         "threat_contact": "the lifeform", "lost": "the way back", "depth": "the depth",
         "ambient": "the surroundings", "phantom": "the surroundings", None: "the situation"}
# Pooled topics are not generated. Unprompted lines: a 4B model asked to be unsettling writes poetry, and asked to
# be plain writes nothing. Creature lines: asked about a lifeform it describes anatomy. The PDA's register for both
# is fixed, so these are original lines in that register, rotated without repeats, at zero latency.
POOLED = {"ambient", "threat", "depth"}
DEPTH_LINES = [
    "Caution: passing safe depth. Position logged.",
    "Caution: passing safe depth. Continuing descent is not advised.",
    "Depth exceeds suit rating. Assessment: immediate ascent required.",
    "Warning: approaching crush depth.",
    "Caution: this suit is not rated for further descent. Exploration is conducted at your own risk.",
]
THREAT_LINES = [  # leviathan tier
    "Detecting a large lifeform in the vicinity. Assessment: avoid.",
    "Detecting a leviathan class lifeform in the immediate vicinity. Are you certain whatever you're doing is worth it?",
    "Warning: large lifeform closing on this position. Consider remaining still.",
    "Lifeform behavior in this region is consistent with predation. Continuing to monitor.",
    "Detecting a large lifeform with an interest in this position. Reason unknown.",
    "Caution: proximity to a large lifeform. Exploration is conducted at your own risk.",
]
PREDATOR_LINES = [  # predator tier, the register of the databank's assessments
    "Detecting a hostile lifeform in the vicinity. Assessment: avoid or distract.",
    "Warning: hostile lifeform closing on this position. Consider a flare, or remaining still.",
    "Detecting territorial behavior in a nearby lifeform. Assessment: leave its territory.",
    "Caution: hostile lifeform in the immediate vicinity. Unpredictable attacks are documented.",
    "Detecting a pack lifeform in the vicinity. Assessment: distract, and avoid close contact.",
]
AMBIENT_LINES = [
    "Local acoustic activity exceeds baseline. Continuing to monitor.",
    "Detecting a large lifeform in the region. Reason for its interest: unknown.",
    "Lifeform readings in this region are sparse. Explanation unclear at this time.",
    "Scans show the digestive tracts of nearby lifeforms contain tissue of unknown origin.",
    "Detecting unusually coordinated movement among nearby lifeforms. Reason unknown.",
    "Warning: entering a region with no prior survey data. Exploration is conducted at your own risk.",
    "Multiple lifeform signatures converging on this position. Are you certain whatever you're doing is worth it?",
    "Vital signs elevated. This is considered a normal response.",
    "Environmental scan complete. Results withheld pending your survival.",
    "Logging position. In the event of your disappearance, this data may assist recovery.",
    "Anomalous reading logged. Category: unexplained.",
]
POOLS = {"threat": THREAT_LINES, "predator": PREDATOR_LINES, "ambient": AMBIENT_LINES, "depth": DEPTH_LINES}
MODEL_TOPICS = {"oxygen", "lost"}  # the only lines the model writes; both are slow-moving, so they can be prefetched
ESCALATION = [(0.33, "routine"), (0.66, "elevated"), (0.85, "high"), (9.0, "critical")]
# A model line must be about its topic. One of these words, or the template plays.
TOPIC_WORDS = {
    "oxygen": {"oxygen", "air", "ascend", "ascent", "ascending", "breath", "breathing", "surface", "replenish",
               "replenishment", "reserve", "reserves", "supply", "tank"},
    "threat": {"contact", "movement", "motion", "lifeform", "lifeforms", "biomass", "signature", "creature",
               "predator", "predators", "large", "sonar", "proximity", "vicinity", "still", "evasive", "hostile",
               "approaching", "avoid", "assessment", "aggressive", "territorial"},
    "lost": {"structure", "structures", "descent", "path", "light", "surface", "way", "return", "route", "heading",
             "retrace", "retracing", "ascend", "back", "lifepod", "shelter", "survival", "position", "bearing"},
    "depth": {"pressure", "depth", "hull", "crush", "ascend", "ascent", "descent", "deep", "suit", "rating", "safe"},
}
BEARINGS = {"left", "right", "north", "south", "east", "west", "northern", "southern", "eastern", "western",
            "northeast", "northwest", "southeast", "southwest", "degrees", "meters", "metres", "percent"}
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


def threat_range(t: dict[str, Any]) -> tuple[float | None, bool]:
    """Effective range of the nearest hostile and whether it is a predator rather than a leviathan.
    Predator ranges are scaled by PREDATOR_SCALE so the same zones and lines apply."""
    td, pd = t.get("threat_dist"), t.get("predator_dist")
    cands = ([(td, False)] if td is not None else []) + ([(pd * PREDATOR_SCALE, True)] if pd is not None else [])
    return min(cands) if cands else (None, False)


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


def describe(t: dict[str, Any], topic: str | None, o2max: float = O2_MAX_MIN, dread: float = 0.0) -> str:
    """Qualitative situation for the model. The model varies the phrasing, it never sees the numbers."""
    o2 = None if t.get("o2") is None else t["o2"] / o2max
    rel = t.get("threat_rel")
    rng, predator = threat_range(t)
    who = "A hostile lifeform" if predator else "A large lifeform"
    parts = [  # the register's own nouns, so the model reports the lifeform and the reserve, not "pressure"
        band(o2, [(CRIT_O2_FRAC, "Oxygen reserve critical."), (LOW_O2_FRAC, "Oxygen reserve low."),
                  (0.7, "Oxygen reserve reduced.")]),
        "Surface distance exceeds remaining supply." if can_surface(t) is False else None,
        "A replenishment source is within reach." if air_near(t) and o2 is not None and o2 < 0.7 else None,
        band(rng, [(CONTACT_M, f"{who} is in contact range, {rel}." if rel else f"{who} is in contact range."),
                   (THREAT_M, f"{who} is in the immediate vicinity."), (2 * THREAT_M, f"{who} is in the region.")]),
        band(t.get("dist_home"), [(2 * LOST_M, "No known structures within range."), (LOST_M, "Far from any known structure.")],
             above=True),
        band(t.get("depth"), [(400, "Safe depth exceeded by a wide margin."), (DEEP_M, "Safe depth exceeded.")],
             above=True),
        "Light levels below detection." if is_dark(t) else None,
        f"Escalation {next(label for limit, label in ESCALATION if dread < limit)}.",
    ]
    return " ".join([p for p in parts if p] + [f"Report on {TOPIC[topic]}. One line."])


def tone(dread: float) -> str:
    return next(label for limit, label in TONES if dread < limit)


def situation(t: dict[str, Any], o2max: float = O2_MAX_MIN, closing: float = 0.0) -> dict[str, Any]:
    """Flatten one telemetry frame into flags, persona weights, the winning persona and the dominant signal.
    `closing` is the nearest threat's approach speed in m/s; a fast approach is near before it is close."""
    o2, home = t.get("o2"), t.get("dist_home")
    td, _ = threat_range(t)
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
    # Life outranks the way home two to one, but only once life is actually at risk: a leviathan patrolling at
    # the edge of range does not make the PDA a survivalist. Ties go to Explorer, listed first.
    priority = SURVIVAL_PRIORITY if any(flags[k] for k in SURVIVAL_FLAGS) else 1.0
    survivor = max(signals["oxygen"], signals["threat"]) * priority
    navigator = signals["lost"]
    explorer = 1.0 - min(1.0, max(survivor, navigator))
    total = survivor + navigator + explorer
    weights = {"explorer": explorer / total, "survivor": survivor / total, "navigator": navigator / total}
    dominant = max(signals, key=signals.get)
    return {
        "flags": flags,
        "weights": {k: round(v, 3) for k, v in weights.items()},
        "persona": max(weights, key=weights.get),
        "dominant": dominant if signals[dominant] > 0 else None,
    }


def why_speak(prev: dict[str, Any] | None, cur: dict[str, Any], last_spoke: float, now: float) -> str | None:
    """Silence is the default. Returns the topic to speak about: the most urgent flag that just rose, or, outside
    the cooldown, the dominant signal when the persona changed. None means stay quiet."""
    if not any(cur["flags"].values()):
        return None
    rose = [FLAG_TOPIC[k] for k in FLAG_TOPIC if cur["flags"][k] and not (prev and prev["flags"][k])]
    if rose:
        return rose[0]
    if now - last_spoke >= COOLDOWN_S and cur["persona"] != prev["persona"]:
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


def ask(llm: str, system: str, user: str) -> str:
    """One line from the local model. Raises on timeout, transport failure, or a non-text stop."""
    r = ollama({"model": OLLAMA_MODEL, "stream": False, "keep_alive": "30m", "options": OLLAMA_OPTIONS,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}, BUDGET_S)
    if r.get("done_reason") != "stop":
        raise ValueError(f"done_reason={r.get('done_reason')}")
    return r["message"]["content"]


def template(topic: str | None, t: dict[str, Any]) -> str:
    """The fixed line for a topic, made concrete only where it must be: relation at contact, air and surface
    for oxygen. These are the only lines that may point anywhere."""
    if topic == "threat_contact":
        kind = "hostile contact" if threat_range(t)[1] else "proximity contact"
        rel = t.get("threat_rel")
        return f"Warning: {kind}. {rel[0].upper()}{rel[1:]}. Remain still." if rel else f"Warning: {kind}. Remain still."
    if topic in FALLBACK_AIR_NEAR and air_near(t):
        if can_surface(t) is False and topic == "oxygen_critical":
            return NO_SURFACE_AIR_NEAR
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
            text = ask(llm, system, describe(t, topic, o2max, dread)).strip().strip('"')
            if any(c.isdigit() for c in text):  # the model was given no numbers, so any number is invented
                raise ValueError(f"invented a reading: {text!r}")
            words = set(text.lower().replace(",", " ").replace(".", " ").split())
            if BEARINGS & words:
                raise ValueError(f"gave a bearing: {text!r}")
            if PURPLE & words:
                raise ValueError(f"went purple: {text!r}")
            if topic in TOPIC_WORDS and not TOPIC_WORDS[topic] & words:
                raise ValueError(f"off topic for {topic}: {text!r}")
            if not text.lower().startswith(OPENERS):
                raise ValueError(f"not the PDA's register: {text!r}")
            if 0 < len(text.split()) <= MAX_WORDS:
                return text, "llm", time.perf_counter() - start
            print(f"[fathom] {llm} over {MAX_WORDS} words: {text!r}", file=sys.stderr)
        except Exception as e:  # any backend failure falls through to the template; the PDA never goes silent
            print(f"[fathom] {llm} failed: {e!r}", file=sys.stderr)
    return template(topic, t), "fallback", time.perf_counter() - start


def speak(text: str, dread: float = 0.0, urgent: bool = False) -> None:
    """Hand the line to the speaker: latest wins, stale lines are dropped, urgent lines cut in."""
    pda_voice.SPEAKER.say(text, dread, urgent)


def append(path: Path, rec: dict[str, Any]) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")


class Fathom:
    """One instance per session. Feed frames to step(); it returns a hint record when it speaks, else None."""

    def __init__(
        self,
        llm: str | None = "ollama",
        speak_fn: Callable[..., None] = speak,
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
        self.pools: dict[str, list[str]] = {}
        self.prefetched: dict[str, tuple[tuple[Any, ...], str, str, float]] = {}  # topic -> (key, text, source, s)
        self.prefetching: set[str] = set()
        self.frames: deque[dict[str, Any]] = deque(maxlen=600)  # five minutes at 2 Hz, for the dashboard
        self.hints: list[dict[str, Any]] = []
        self.session = SESSIONS / (time.strftime("%Y%m%d-%H%M%S") + ".jsonl")
        if llm == "ollama":
            warm_ollama()

    def next_pooled(self, topic: str, t: dict[str, Any]) -> str:
        """The next line from a topic's pool, every line once before any repeats, in a fresh order each cycle."""
        pool = "predator" if topic == "threat" and threat_range(t)[1] else topic
        if not self.pools.get(pool):
            self.pools[pool] = list(POOLS[pool])
            self.rng.shuffle(self.pools[pool])
        return self.pools[pool].pop()

    @staticmethod
    def prefetch_key(topic: str, t: dict[str, Any]) -> tuple[Any, ...]:
        """What a prefetched line depends on. If this changes before the trigger, the line is written again."""
        return (topic, air_near(t), can_surface(t))

    def maybe_prefetch(self, t: dict[str, Any], sit: dict[str, Any]) -> None:
        """The model is never on the critical path. Oxygen and the way back move slowly, so their lines are
        written and synthesized while the situation is still approaching the threshold; at the trigger the ready
        line plays, or the template does. In the offline sim this runs inline and skips the synthesizer."""
        if not self.llm:
            return
        o2f = None if t.get("o2") is None else t["o2"] / self.o2max
        home = t.get("dist_home")
        due = {"oxygen": o2f is not None and o2f < LOW_O2_FRAC + PREFETCH_O2_MARGIN and not sit["flags"]["low_oxygen"],
               "lost": home is not None and home > LOST_M * PREFETCH_LOST_FRAC and not sit["flags"]["player_lost"]}
        for topic, wanted in due.items():
            key = self.prefetch_key(topic, t)
            if wanted and topic not in self.prefetching and self.prefetched.get(topic, (None,))[0] != key:
                self.prefetching.add(topic)
                if self.log:
                    threading.Thread(target=self.prefetch, args=(topic, key, dict(t), sit), daemon=True).start()
                else:
                    self.prefetch(topic, key, dict(t), sit, synthesize=False)

    def prefetch(self, topic: str, key: tuple[Any, ...], t: dict[str, Any], sit: dict[str, Any],
                 synthesize: bool = True) -> None:
        try:
            text, source, latency = hint(t, sit, topic, self.llm, self.dread, self.o2max)
            if synthesize:
                pda_voice.generate(text)
            self.prefetched[topic] = (key, text, source, latency)
        except Exception as e:  # a failed prefetch only means the template plays
            print(f"[fathom] prefetch of {topic} failed: {e!r}", file=sys.stderr)
        finally:
            self.prefetching.discard(topic)

    def update_dread(self, t: dict[str, Any], now: float, zone_rate: float) -> None:
        dt = max(0.0, now - self.prev_t) if self.prev_t is not None else 0.0
        depth, home = t.get("depth") or 0.0, t.get("dist_home")
        # ponytail: predators raise dread through the zone rate only; a per-species temper needs the object dump
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
        td, _ = threat_range(t)
        dt = now - self.prev_t if self.prev_t is not None else 0.0
        closing = (self.prev_td - td) / dt if td is not None and self.prev_td is not None and dt > 0 else 0.0
        ttc = time_to_contact(td, closing)
        zone_name, zone_rate = zone(td, ttc)
        sit = situation(t, self.o2max, closing)
        self.update_dread(t, now, zone_rate)
        self.maybe_prefetch(t, sit)
        self.prefetched = {k: v for k, v in self.prefetched.items()
                           if v[0] == self.prefetch_key(k, t)}  # a line written for a different situation is stale
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
            ready = self.prefetched.pop(topic, None)
            if topic in POOLED:
                text, source, latency = self.next_pooled(topic, t), "pool", 0.0
            elif ready and ready[0] == self.prefetch_key(topic, t):
                text, source, latency = ready[1], ready[2] + "+prefetch", ready[3]  # the write cost, paid earlier
            elif topic in MODEL_TOPICS:
                text, source, latency = template(topic, t), "fallback", 0.0  # no ready line: the template, now
            else:
                text, source, latency = hint(t, sit, topic, None, self.dread, self.o2max)
            self.last_spoke = now
            if topic not in ("ambient", "phantom"):
                self.dread = clamp(self.dread + DREAD_PER_HINT)
            out = {"t": t, **sit, "dread": round(self.dread, 3), "topic": topic, "text": text, "source": source,
                   "latency_s": round(latency, 3)}
            self.hints.append(out)
            if self.log:
                append(TRACE, out)
            self.speak(text, self.dread, topic in CRITICAL)
        # wall-clock t with sub-second resolution: the mod's own t is whole seconds and analyze.py needs spacing
        frame = {**t, "t": time.time(), "flags": sit["flags"], "weights": sit["weights"], "persona": sit["persona"],
                 "dominant": sit["dominant"], "dread": round(self.dread, 3), "o2max": self.o2max, "dark": is_dark(t),
                 "zone": zone_name, "closing": round(closing, 1), "ttc": None if ttc is None else round(ttc, 1),
                 "can_surface": can_surface(t), "prefetched": sorted(self.prefetched),
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
    return None if "--offline" in argv else "ollama"


def main() -> None:
    fathom = Fathom(backend(sys.argv))
    pda_voice.prewarm([READY, *FALLBACK_AIR_NEAR.values(), *FALLBACK_NO_SURFACE.values(), NO_SURFACE_AIR_NEAR,
                       *(v for k, v in FALLBACK.items() if k), *THREAT_LINES, *PREDATOR_LINES, *AMBIENT_LINES,
                       *DEPTH_LINES, "Warning: hostile contact. Remain still."])
    serve_dashboard(fathom)
    print(f"FATHOM watching {TELEMETRY} ({fathom.llm or 'offline'}), dashboard http://127.0.0.1:{DASHBOARD_PORT}, "
          f"recording {fathom.session.name}. Waiting for the game.")
    mtime, linked = 0.0, False
    while True:
        try:
            m = TELEMETRY.stat().st_mtime
            if m != mtime and time.time() - m < 3:  # only frames the mod wrote just now count as a link
                mtime = m
                if not linked:
                    linked = True
                    print("link live")
                    speak(READY)  # the game is writing telemetry: now the link is real
                out = fathom.step(json.loads(TELEMETRY.read_text()))
                if out:
                    print(f"[{out['source']} {out['latency_s']}s {out['persona']}/{out['topic']} dread {out['dread']}] "
                          f"{out['text']}")
            elif linked and time.time() - m > 10:
                linked = False
                print("link lost")
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        time.sleep(0.25)


if __name__ == "__main__":
    main()
