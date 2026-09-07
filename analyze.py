"""Behavioural proxies from a session log: what the diver did in the seconds after each PDA line.

python analyze.py                      latest file in sessions/
python analyze.py sessions/X.jsonl     that one

Each hint gets a reaction record; the same record is computed at random quiet moments as the baseline, so the
question "did the line change anything" has a control. Writes <session>.reactions.json next to the log.
"""

from __future__ import annotations

import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any

BEFORE_S = 10.0  # behaviour before the line, for comparison
AFTER_S = 20.0  # window in which a reaction counts
STILL = 0.3  # m/s or less counts as stationary
ASCENT_M = 2.0  # metres shallower than at the line counts as ascending
TURN_DEG = 120.0  # heading change between before and after counts as turning back
BASELINE_N = 30

GROUPS = {"oxygen": "ascended", "oxygen_critical": "ascended", "depth": "ascended", "threat": "distanced",
          "threat_contact": "distanced", "lost": "closed_home", "ambient": None}  # the reaction each topic should provoke


def load(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def window(rows: list[dict[str, Any]], i: int, lo: float, hi: float) -> list[dict[str, Any]]:
    t0 = rows[i]["t"]
    return [r for r in rows[max(0, i - 400): i + 400] if t0 + lo <= r["t"] <= t0 + hi]


def heading(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    """Direction of travel from frame a to frame b in degrees, None without positions or without movement."""
    if a.get("x") is None or b.get("x") is None:
        return None
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    return math.degrees(math.atan2(dy, dx)) if math.hypot(dx, dy) > 1.0 else None


def reaction(rows: list[dict[str, Any]], i: int) -> dict[str, Any] | None:
    """What happened in the AFTER_S seconds after frame i, relative to the BEFORE_S seconds before it."""
    h, before, after = rows[i], window(rows, i, -BEFORE_S, 0), window(rows, i, 0, AFTER_S)
    if len(after) < 4 or len(before) < 2:
        return None
    dt = (after[-1]["t"] - after[0]["t"]) / max(len(after) - 1, 1)
    speed_before = statistics.mean(r["speed"] for r in before)
    speed_after = statistics.mean(r["speed"] for r in after)
    ascended = next((r["t"] - h["t"] for r in after if r["depth"] <= h["depth"] - ASCENT_M), None)
    end = after[-1]
    hb, ha = heading(before[0], h), heading(h, end)
    turned = None if hb is None or ha is None else abs((ha - hb + 180) % 360 - 180) > TURN_DEG
    return {
        "t": h["t"],
        "topic": h["hint"]["topic"] if h.get("hint") else None,
        "speed_change": round(speed_after - speed_before, 2),
        "still_s": round(sum(dt for r in after if r["speed"] <= STILL), 1),
        "ascended": ascended is not None,
        "time_to_ascent_s": None if ascended is None else round(ascended, 1),
        "depth_change_m": round(end["depth"] - h["depth"], 1),
        "closed_home": None if h.get("dist_home") is None or end.get("dist_home") is None
        else end["dist_home"] < h["dist_home"] - ASCENT_M,
        "distanced": None if h.get("threat_dist") is None or end.get("threat_dist") is None
        else end["threat_dist"] > h["threat_dist"] + ASCENT_M,
        "turned_back": turned,
    }


def analyze(rows: list[dict[str, Any]], seed: int = 0) -> dict[str, Any]:
    hint_idx = [i for i, r in enumerate(rows) if r.get("hint")]
    reactions = [x for i in hint_idx if (x := reaction(rows, i))]
    quiet = [i for i in range(len(rows)) if all(abs(rows[i]["t"] - rows[j]["t"]) > BEFORE_S + AFTER_S for j in hint_idx)]
    random.Random(seed).shuffle(quiet)
    baseline = [x for i in quiet[:BASELINE_N] if (x := reaction(rows, i))]
    return {"session_s": round(rows[-1]["t"] - rows[0]["t"], 1), "frames": len(rows), "reactions": reactions,
            "baseline": baseline, "summary": {**{g: summarize([r for r in reactions if r["topic"] == g]) for g in GROUPS},
                                              "all_hints": summarize(reactions), "baseline": summarize(baseline)}}


def rate(rs: list[dict[str, Any]], key: str) -> float | None:
    vals = [r[key] for r in rs if r[key] is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def summarize(rs: list[dict[str, Any]]) -> dict[str, Any]:
    if not rs:
        return {"n": 0}
    return {"n": len(rs), "speed_change": round(statistics.mean(r["speed_change"] for r in rs), 2),
            "still_s": round(statistics.mean(r["still_s"] for r in rs), 1), "ascended": rate(rs, "ascended"),
            "closed_home": rate(rs, "closed_home"), "distanced": rate(rs, "distanced"), "turned_back": rate(rs, "turned_back")}


def report(result: dict[str, Any]) -> None:
    cols = ["n", "speed_change", "still_s", "ascended", "closed_home", "distanced", "turned_back"]
    print(f"session {result['session_s']:.0f} s, {result['frames']} frames, {len(result['reactions'])} hints analysed, "
          f"{len(result['baseline'])} baseline windows ({AFTER_S:.0f} s after each line)")
    print(f"{'':<10}" + "".join(f"{c:>13}" for c in cols))
    for name, s in result["summary"].items():
        cells = [s.get(c) for c in cols]
        print(f"{name:<10}" + "".join(f"{'-' if v is None else v:>13}" for v in cells))
    for r in result["reactions"]:
        want = GROUPS.get(r["topic"])
        did = "" if want is None else ("did" if r[want] else "did not")
        print(f"  {r['topic']:<8} speed {r['speed_change']:+.2f}  still {r['still_s']:>4}s  depth {r['depth_change_m']:+.1f}m"
              f"  {did} {want or ''}".rstrip())


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else max(Path("sessions").glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    result = analyze(load(path))
    out = path.with_suffix(".reactions.json")
    out.write_text(json.dumps(result, indent=1), encoding="utf-8")
    report(result)
    print(f"written {out}")


if __name__ == "__main__":
    main()
