"""python test_fathom.py"""

from __future__ import annotations

import fathom
import sim

CALM = {"o2": 45.0, "depth": 20.0, "speed": 2.0, "threat_dist": None, "threat": None, "dist_home": 80.0}
ASK = fathom.ask


def test_situation() -> None:
    s = fathom.situation(CALM)
    assert not any(s["flags"].values()) and s["persona"] == "explorer"
    assert fathom.situation({**CALM, "o2": 60.0})["dominant"] is None
    s = fathom.situation({**CALM, "o2": 10.0})
    assert s["flags"]["low_oxygen"] and s["persona"] == "survivor" and s["dominant"] == "oxygen"
    s = fathom.situation({**CALM, "o2": 10.0, "threat_dist": 10.0})
    assert s["dominant"] == "threat" and s["persona"] == "survivor"
    s = fathom.situation({**CALM, "dist_home": 2000.0})
    assert s["flags"]["player_lost"] and s["persona"] == "navigator"
    assert abs(sum(s["weights"].values()) - 1.0) < 0.01


def test_why_speak() -> None:
    calm, low = fathom.situation(CALM), fathom.situation({**CALM, "o2": 10.0})
    assert fathom.why_speak(None, calm, 0.0, 0.0) is None  # nothing wrong, stay silent
    assert fathom.why_speak(calm, low, 0.0, 1.0) == "oxygen"  # flag rose
    assert fathom.why_speak(low, low, 0.0, 1.0) is None  # same crisis, already said it
    lost = fathom.situation({**CALM, "o2": 10.0, "dist_home": 2200.0})  # dominant signal flips, no new flag
    prev = {**low, "flags": {**low["flags"], "player_lost": True}}
    assert fathom.why_speak(prev, lost, 0.0, 5.0) is None  # inside cooldown
    assert fathom.why_speak(prev, lost, 0.0, 15.0) == "lost"


def test_describe() -> None:
    d = fathom.describe({**CALM, "o2": 12.0, "threat_dist": 50.0, "depth": 250.0}, "threat")
    assert d == ("Oxygen reserve low. Surface distance exceeds remaining supply. A large lifeform is in the immediate "
                 "vicinity. Safe depth exceeded. Report on the lifeform. One line.")  # 12 s of air cannot cover 250 m
    assert fathom.describe({**CALM, "o2": 60.0}, None) == "Report on the situation. One line."
    assert not any(ch.isdigit() for ch in d)
    d = fathom.describe({**CALM, "o2": 4.0, "air_dist": 12.0, "time_of_day": 23.0}, "oxygen_critical")
    assert d.startswith("Oxygen reserve critical. Surface distance exceeds remaining supply. A replenishment source")
    assert "Light levels below detection." in d


def test_critical_and_priority() -> None:
    fathom.ask = lambda *a: (_ for _ in ()).throw(AssertionError("model must not be called"))  # type: ignore
    try:
        t = {**CALM, "threat_dist": 10.0}
        text, source, latency = fathom.hint(t, fathom.situation(t), "threat_contact", "ollama")
        assert (text, source) == (fathom.FALLBACK["threat_contact"], "fallback") and latency < 0.01
        t = {**CALM, "o2": 4.0, "air_dist": 12.0, "depth": 5.0}  # 4 s of air still covers 5 m
        assert fathom.hint(t, fathom.situation(t), "oxygen_critical", "ollama")[0] == fathom.FALLBACK_AIR_NEAR["oxygen_critical"]
        t["depth"] = 20.0  # and does not cover 20 m
        assert fathom.hint(t, fathom.situation(t), "oxygen_critical", "ollama")[0] == fathom.NO_SURFACE_AIR_NEAR
    finally:
        fathom.ask = ASK
    s = fathom.situation({**CALM, "o2": 10.0, "dist_home": 2200.0})  # life outranks the way home
    assert s["persona"] == "survivor" and s["flags"]["player_lost"]
    s = fathom.situation({**CALM, "threat_dist": 10.0})
    assert s["flags"]["threat_contact"] and s["flags"]["threat_near"]
    assert fathom.why_speak(fathom.situation(CALM), s, 0.0, 1.0) == "threat_contact"  # most urgent flag wins


def test_guards() -> None:
    t = {**CALM, "o2": 10.0, "depth": 5.0}
    for bad in ["Oxygen at 20%. Turn left.", "Something vast stirs in the black.", "The abyss breathes.",
                "You should probably get some air soon."]:  # the last one is fine English and not the PDA
        fathom.ask = lambda llm, system, user, bad=bad: bad  # type: ignore[assignment]
        try:
            text, source, _ = fathom.hint(t, fathom.situation(t), "oxygen", "ollama")
        finally:
            fathom.ask = ASK
        assert source == "fallback" and text == fathom.FALLBACK["oxygen"], bad
    fathom.ask = lambda *a: "Caution: oxygen reserve low. Consider ascending."  # type: ignore[assignment]
    try:
        assert fathom.hint(t, fathom.situation(t), "oxygen", "ollama")[1] == "llm"
    finally:
        fathom.ask = ASK


def test_fallback() -> None:
    t = {**CALM, "o2": 10.0}
    text, source, latency = fathom.hint(t, fathom.situation(t), "oxygen", None)
    assert source == "fallback" and 0 < len(text.split()) <= fathom.MAX_WORDS and latency < 0.01


def test_silence_compound_and_dread() -> None:
    rows = {r["scenario"]: r for r in sim.run(None)}
    assert rows["quiet"]["hints"] == []
    assert [h["topic"] for h in rows["compound"]["hints"]] == ["threat", "oxygen", "threat_contact"]
    assert all(h["persona"] == "survivor" for h in rows["compound"]["hints"])
    threat = rows["compound"]["hints"][0]
    assert threat["source"] == "pool" and threat["text"] in fathom.THREAT_LINES and threat["latency_s"] == 0
    depth = rows["deep_entry"]["hints"][0]
    assert depth["topic"] == "depth" and depth["source"] == "pool" and depth["text"] in fathom.DEPTH_LINES
    assert all(r["relevant"] and r["tracked"] for r in rows.values())
    long = rows["long_dive"]["hints"]
    assert long[0]["topic"] == "depth" and long[-1]["topic"] == "ambient" and long[-1]["dread"] >= fathom.AMBIENT_DREAD
    assert all(b["dread"] >= a["dread"] for a, b in zip(long, long[1:]))  # dread only climbs down there
    ambient = [h["text"] for h in long if h["topic"] == "ambient"]
    assert len(ambient) == len(set(ambient)) and all(a in fathom.AMBIENT_LINES for a in ambient)  # pooled, no repeats
    assert all(h["source"] == "pool" for h in long if h["topic"] == "ambient")


def test_zones_and_reach() -> None:
    assert fathom.zone(None) == (None, 0.0) and fathom.zone(100)[0] == "presence" and fathom.zone(50)[0] == "near"
    assert fathom.zone(10)[0] == "contact" and fathom.zone(100, ttc=5.0)[0] == "near" and fathom.zone(100, ttc=1.5)[0] == "contact"
    assert fathom.zone(10)[1] > fathom.zone(50)[1] > fathom.zone(100)[1]
    s = fathom.situation({**CALM, "threat_dist": 100.0}, closing=20.0)  # 5 s out: near, not yet contact
    assert s["flags"]["threat_near"] and not s["flags"]["threat_contact"]
    assert not fathom.situation({**CALM, "threat_dist": 100.0})["flags"]["threat_near"]
    assert fathom.can_surface({**CALM, "o2": 10.0, "depth": 100.0}) is False  # 100 m at 2 m/s needs 50 s
    assert fathom.can_surface({**CALM, "o2": 60.0, "depth": 100.0}) is True and fathom.can_surface({"o2": None}) is None
    t = {**CALM, "threat_dist": 10.0, "threat_rel": "below, behind you"}
    assert fathom.template("threat_contact", t) == "Warning: proximity contact. Below, behind you. Remain still."
    assert fathom.template("oxygen_critical", {**CALM, "o2": 4.0, "depth": 100.0}) == fathom.FALLBACK_NO_SURFACE["oxygen_critical"]
    assert fathom.template("oxygen_critical", {**CALM, "o2": 4.0, "depth": 100.0, "air_dist": 10.0}) == fathom.NO_SURFACE_AIR_NEAR
    assert fathom.template("oxygen", {**CALM, "o2": 15.0, "depth": 5.0}) == fathom.FALLBACK["oxygen"]
    assert "Surface distance exceeds remaining supply." in fathom.describe({**CALM, "o2": 4.0, "depth": 100.0}, "oxygen_critical")


def test_phantom() -> None:
    old = fathom.PHANTOM_P
    fathom.PHANTOM_P = 1.0
    try:
        clock = {"t": 0.0}
        f = fathom.Fathom(None, speak_fn=lambda *_: None, now=lambda: clock["t"], log=False)
        topics = []
        for i in range(900):  # fifteen quiet minutes at 300 m, no creature in range
            clock["t"] = float(i)
            out = f.step({**CALM, "depth": 300.0, "o2": 100.0, "dist_home": 800.0, "t": i})
            if out:
                topics.append(out["topic"])
        assert topics.count("phantom") == 1 and "ambient" in topics
        assert topics.index("phantom") > 0 and f.dread >= fathom.PHANTOM_DREAD
    finally:
        fathom.PHANTOM_P = old


def test_tone() -> None:
    assert fathom.tone(0.0).startswith("Tone: routine") and fathom.tone(0.9).startswith("Tone: a routine report")


def test_analyze() -> None:
    import analyze

    rows = []  # 2 Hz for 90 s: swim east at 100 m, oxygen line at t=30, then stop, turn back west and ascend
    for i in range(180):
        t = i / 2
        after = t - 30
        depth = 100.0 if after <= 0 else max(0.0, 100.0 - 2 * after)
        speed = 2.0 if after <= 0 or after > 5 else 0.0
        x = t * 2 if after <= 0 else 60 - max(0.0, after - 5) * 2
        hint = {"topic": "oxygen", "text": "Oxygen critical. Ascend.", "source": "fallback", "latency_s": 0} if i == 60 else None
        rows.append({"t": 1e9 + t, "depth": depth, "o2": 20.0, "speed": speed, "threat_dist": None, "threat": None,
                     "dist_home": 500.0 + x, "x": x, "y": 0.0, "hint": hint})
    r = analyze.analyze(rows)
    hit = r["reactions"][0]
    assert hit["topic"] == "oxygen" and hit["ascended"] and hit["turned_back"] and hit["closed_home"]
    assert hit["still_s"] >= 4.0 and hit["speed_change"] < 0 and hit["time_to_ascent_s"] <= 1.5
    assert r["summary"]["oxygen"]["ascended"] == 1.0 and r["summary"]["baseline"]["n"] > 0
    assert r["summary"]["baseline"]["ascended"] < 1.0  # quiet moments do not look like reactions


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
