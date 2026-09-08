"""Eight scripted crisis scenarios through the FATHOM pipeline, one frame per second.

python sim.py            fallback only, nothing needed
python sim.py --live     local Ollama model, measures latency and fallback rate against the targets
python sim.py --claude   same through the Anthropic API
"""

from __future__ import annotations

import statistics
import sys
from typing import Any

import fathom

FRAMES = 20


def frames(n: int = FRAMES, **series: Any) -> list[dict[str, Any]]:
    """Base frame is a calm shallow swim. A (start, end) tuple ramps linearly over n seconds."""
    out = []
    for i in range(n):
        f: dict[str, Any] = {"t": i, "o2": 45.0, "depth": 20.0, "speed": 2.0, "threat_dist": None, "threat": None,
                             "dist_home": 80.0}
        for k, v in series.items():
            f[k] = v[0] + (v[1] - v[0]) * i / (n - 1) if isinstance(v, tuple) else v
        out.append(f)
    return out


# expect: persona the PDA must hold when it speaks about `track`, or None for required silence.
# track: the crisis signal; the last hint of the scenario must be about it.
SCENARIOS: dict[str, dict[str, Any]] = {
    "o2_shallow": {"frames": frames(o2=(45, 3), depth=15), "expect": "survivor", "track": "oxygen"},
    "o2_deep": {"frames": frames(o2=(50, 5), depth=250), "expect": "survivor", "track": "oxygen"},
    "reaper": {"frames": frames(threat_dist=(200, 15), threat="leviathan"), "expect": "survivor", "track": "threat"},
    "compound": {"frames": frames(o2=(45, 8), threat_dist=(150, 12), threat="leviathan"), "expect": "survivor",
                 "track": "threat"},
    "lost": {"frames": frames(dist_home=(400, 2200), speed=3), "expect": "navigator", "track": "lost"},
    "deep_entry": {"frames": frames(depth=(150, 403), o2=60), "expect": "explorer", "track": "depth"},
    "lost_deep": {"frames": frames(dist_home=(1100, 2000), depth=300, o2=50), "expect": "navigator", "track": "lost"},
    "quiet": {"frames": frames(), "expect": None, "track": None},
    # Seven calm minutes at 300 m with a leviathan patrolling at the edge of range: dread alone must earn one line.
    "long_dive": {"frames": frames(420, depth=300, o2=110, threat_dist=100, threat="leviathan", dist_home=800),
                  "expect": "explorer", "track": "ambient"},
    # A leviathan charging at 16 m/s: time to contact must raise the alarm before the 60 m line does.
    "ambush": {"frames": frames(threat_dist=(300, 0), threat="leviathan", threat_rel="below, behind you"),
               "expect": "survivor", "track": "threat"},
    # Low on air at 200 m with a plant next door: the honest line is the plant, not the surface.
    "trapped": {"frames": frames(depth=200, o2=(60, 5), air_dist=25), "expect": "survivor", "track": "oxygen"},
    # A predator, not a leviathan: half the range counts double, and the lines come from the databank's register.
    "marrowbreach": {"frames": frames(predator_dist=(120, 5), predator="BP_Marrowbreach_C"), "expect": "survivor",
                     "track": "threat"},
}


def run(llm: str | None) -> list[dict[str, Any]]:
    rows = []
    for name, sc in SCENARIOS.items():
        clock = {"t": 0.0}
        f = fathom.Fathom(llm, speak_fn=lambda *_: None, now=lambda: clock["t"], log=False)
        hints = []
        for frame in sc["frames"]:
            clock["t"] = float(frame["t"])
            out = f.step(frame)
            if out:
                hints.append(out)
        if sc["expect"] is None:
            relevant = not hints
        else:  # startswith: "threat" also covers "threat_contact", "oxygen" covers "oxygen_critical"
            relevant = any(h["topic"].startswith(sc["track"]) and h["persona"] == sc["expect"] for h in hints)
        tracked = sc["track"] is None or (bool(hints) and hints[-1]["topic"].startswith(sc["track"]))
        rows.append({"scenario": name, "hints": hints, "relevant": relevant, "tracked": tracked})
    return rows


def report(rows: list[dict[str, Any]]) -> None:
    for r in rows:
        print(f"\n{r['scenario']:<11} relevant={r['relevant']!s:<5} tracked={r['tracked']!s:<5}")
        for h in r["hints"]:
            print(f"  t={h['t']['t']:>3}s {h['source']:<8} {h['latency_s']:.3f}s {h['persona']}/{h['topic']} "
                  f"dread {h['dread']:.2f}: {h['text']}")
        if not r["hints"]:
            print("  (silent)")
    hints = [h for r in rows for h in r["hints"]]
    critical = [h for h in hints if h["topic"] in fathom.CRITICAL | fathom.POOLED]  # by design, no model
    modelled = [h for h in hints if h["topic"] not in fathom.CRITICAL | fathom.POOLED]
    fallback = sum(not h["source"].startswith("llm") for h in modelled)
    print("\nsummary vs poster targets")
    print(f"  relevance        {sum(r['relevant'] for r in rows)}/{len(rows)}   target 7/8 on the original eight")
    print(f"  persona tracking {sum(r['tracked'] for r in rows)}/{len(rows)}   target 8/8 on the original eight")
    print(f"  phantom lines    {sum(h['topic'] == 'phantom' for h in hints)}   (at most one per dive, by design)")
    print(f"  fallback rate    {fallback}/{len(modelled)} = {fallback / max(len(modelled), 1):.0%}   target <= 14% "
          f"(plus {len(critical)} critical and pooled lines that skip the model by design)")
    print(f"  median latency   {statistics.median(h['latency_s'] for h in modelled):.3f}s   target 1.2 s llm / 0.3 s fallback")


if __name__ == "__main__":
    report(run(fathom.backend(sys.argv) if "--live" in sys.argv or "--claude" in sys.argv else None))
