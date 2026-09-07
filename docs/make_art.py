"""Generate the README art: banner, dread curve from a real dive, zone and ring diagrams. python docs/make_art.py"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFilter, ImageFont

matplotlib.use("Agg")
HERE = Path(__file__).parent
ROOT = HERE.parent
CYAN, CORAL, SAND, SLATE, ICE, DIM = "#3fd7ff", "#ff6a4d", "#f0c987", "#8aa5b8", "#d7ecf5", "#5d8299"
FONT_DIR = Path("C:/Windows/Fonts")


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    for name in (["bahnschrift.ttf", "segoeuib.ttf"] if bold else ["bahnschrift.ttf", "segoeui.ttf"]):
        if (FONT_DIR / name).exists():
            f = ImageFont.truetype(str(FONT_DIR / name), size)
            if name.startswith("bahnschrift"):
                try:
                    f.set_variation_by_name("Bold" if bold else "SemiBold")
                except Exception:  # noqa: BLE001 - variation axes are optional
                    pass
            return f
    return ImageFont.load_default()


def banner(path: Path, w: int = 1600, h: int = 560) -> None:
    rng = random.Random(4)
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):  # murky teal at the top to black at the bottom
        t = y / h
        r, g, b = int(10 * (1 - t) + 1 * t), int(60 * (1 - t) ** 1.6 + 4 * t), int(90 * (1 - t) ** 1.3 + 10 * t)
        for x in range(w):
            v = 1.0 - 0.35 * abs(x / w - 0.5)
            px[x, y] = (int(r * v), int(g * v), int(b * v))
    rays = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    for i in range(9):
        x0 = rng.randint(-100, w)
        rd.polygon([(x0, -20), (x0 + rng.randint(40, 90), -20), (x0 + rng.randint(200, 400), h), (x0 + rng.randint(80, 160), h)],
                   fill=(120, 200, 230, rng.randint(6, 14)))
    rays = rays.filter(ImageFilter.GaussianBlur(24))
    img.paste(rays, (0, 0), rays)
    d = ImageDraw.Draw(img)
    for _ in range(700):  # marine snow
        x, y, s = rng.randint(0, w), rng.randint(0, h), rng.random()
        a = int(30 + 90 * s * (1 - y / h))
        d.ellipse([x, y, x + 1 + s * 2, y + 1 + s * 2], fill=(180, 220, 235, a))
    # a shape in the murk
    sil = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sil)
    cx, cy = int(w * 0.72), int(h * 0.62)
    sd.ellipse([cx - 260, cy - 70, cx + 260, cy + 70], fill=(2, 12, 24, 150))
    for k in range(6):
        ang = -0.4 + k * 0.16
        sd.line([(cx - 230, cy + 10), (cx - 230 - 380 * math.cos(ang), cy + 10 + 380 * math.sin(ang))],
                fill=(2, 12, 24, 120), width=int(26 - k * 3))
    sil = sil.filter(ImageFilter.GaussianBlur(18))
    img.paste(sil, (0, 0), sil)
    # HUD frame + wordmark
    d = ImageDraw.Draw(img, "RGBA")
    m = 36
    for x, y, dx, dy in [(m, m, 1, 1), (w - m, m, -1, 1), (m, h - m, 1, -1), (w - m, h - m, -1, -1)]:
        d.line([(x, y), (x + 26 * dx, y)], fill=CYAN, width=3)
        d.line([(x, y), (x, y + 26 * dy)], fill=CYAN, width=3)
    title = "F A T H O M"
    f1 = font(118, bold=True)
    tw = d.textlength(title, font=f1)
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(glow).text(((w - tw) / 2, h * 0.30), title, font=f1, fill=(63, 215, 255, 140))
    glow = glow.filter(ImageFilter.GaussianBlur(16))
    img.paste(glow, (0, 0), glow)
    d.text(((w - tw) / 2, h * 0.30), title, font=f1, fill=ICE)
    f2 = font(30)
    sub = "H E L P F U L .   N O T   O M N I S C I E N T ."
    sw = d.textlength(sub, font=f2)
    d.text(((w - sw) / 2, h * 0.30 + 150), sub, font=f2, fill=CYAN)
    f3 = font(22)
    line = "An AI companion for the PDA that knows when to stay silent."
    lw = d.textlength(line, font=f3)
    d.text(((w - lw) / 2, h * 0.30 + 205), line, font=f3, fill=SLATE)
    d.text((m + 6, h - m - 30), "403 m", font=font(20), fill=CORAL)
    img.save(path, optimize=True)


def dread_curve(path: Path, session: Path) -> None:
    rows = [json.loads(l) for l in session.read_text(encoding="utf-8").splitlines() if l.strip()]
    t0 = rows[0]["t"]
    t = [r["t"] - t0 for r in rows]
    fig, ax = plt.subplots(figsize=(12, 4.2), dpi=150)
    fig.patch.set_facecolor("#04101c")
    ax.set_facecolor("#04101c")
    ax.fill_between(t, 0, [r["dread"] for r in rows], color=CORAL, alpha=0.18)
    ax.plot(t, [r["dread"] for r in rows], color=CORAL, lw=1.8, label="dread (system escalation)")
    ax2 = ax.twinx()
    ax2.plot(t, [r["threat_dist"] for r in rows], color=CYAN, lw=1.2, alpha=0.9, label="nearest leviathan (m)")
    ax2.plot(t, [r["o2"] for r in rows], color=SAND, lw=1.2, alpha=0.9, label="oxygen (s)")
    ax2.set_yscale("log")
    ax2.set_ylim(3, 3000)
    for r in rows:
        if r.get("hint"):
            ax.axvline(r["t"] - t0, color=ICE, alpha=0.35, lw=0.8)
            ax.text(r["t"] - t0 + 2, 1.01, r["hint"]["topic"], color=ICE, fontsize=7, rotation=90, va="bottom",
                    alpha=0.8, clip_on=False)
    ax.set_ylim(0, 1.0)
    ax.set_xlabel("seconds into the dive", color=DIM)
    ax.set_ylabel("dread", color=CORAL)
    ax2.set_ylabel("metres / seconds", color=DIM)
    for a in (ax, ax2):
        a.tick_params(colors=DIM, labelsize=8)
        for s in a.spines.values():
            s.set_color("#123650")
    ax.grid(color="#123650", lw=0.5, alpha=0.6)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="lower right", fontsize=8, facecolor="#081a2c", edgecolor="#123650", labelcolor=ICE)
    ax.set_title("One real dive: a Collector Leviathan pass at 10 m, oxygen to 6 s, refilled at 459 m", color=ICE,
                 fontsize=10, loc="left", pad=34)
    fig.tight_layout()
    fig.savefig(path, facecolor=fig.get_facecolor())


def zones_svg(path: Path) -> None:
    rings = [(1600, "silence", DIM, "nothing"), (120, "presence", SLATE, "at most an ambient line"),
             (60, "near", SAND, "one line, a posture: stay still, lights off"),
             (20, "contact", CORAL, "instant template, one concrete fact: above, below, behind")]
    R, rmax = 230, 3000
    rad = lambda d: R * math.log10(1 + d) / math.log10(1 + rmax)  # noqa: E731
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 520" font-family="Segoe UI, sans-serif">',
             '<rect width="1000" height="520" fill="#04101c"/>']
    cx, cy = 270, 260
    for d, name, col, desc in rings:
        r = rad(d)
        parts.append(f'<circle cx="{cx}" cy="{cy}" r="{r:.0f}" fill="{col}" fill-opacity="0.07" stroke="{col}" stroke-opacity="0.8" stroke-width="1.5"/>')
        parts.append(f'<text x="{cx + 6}" y="{cy - r + 14}" fill="{col}" font-size="11" letter-spacing="2">{name.upper()} · {d} m</text>')
    parts.append(f'<circle cx="{cx}" cy="{cy}" r="4" fill="{CYAN}"/>')
    parts.append(f'<text x="{cx + 10}" y="{cy + 4}" fill="{CYAN}" font-size="11">diver</text>')
    y = 90
    parts.append(f'<text x="540" y="{y}" fill="{ICE}" font-size="20" font-weight="600" letter-spacing="4">ZONES OF DREAD</text>')
    parts.append(f'<text x="540" y="{y + 26}" fill="{DIM}" font-size="12">vague while vagueness costs nothing, concrete only at contact</text>')
    y += 70
    for d, name, col, desc in rings[1:]:
        rate = {"presence": "1/300", "near": "1/120", "contact": "1/40"}[name]
        parts.append(f'<rect x="540" y="{y - 14}" width="8" height="40" fill="{col}"/>')
        parts.append(f'<text x="560" y="{y}" fill="{col}" font-size="14" font-weight="600" letter-spacing="2">{name.upper()}  <tspan fill="{DIM}" font-weight="400" letter-spacing="0">under {d} m, or by time to contact</tspan></text>')
        parts.append(f'<text x="560" y="{y + 20}" fill="{ICE}" font-size="12">{desc}</text>')
        parts.append(f'<text x="560" y="{y + 36}" fill="{DIM}" font-size="11">dread +{rate} per second</text>')
        y += 78
    parts.append(f'<text x="540" y="{y + 10}" fill="{DIM}" font-size="11">time to contact = range / closing speed. A charge at 16 m/s is near at 90 m, not 60.</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


if __name__ == "__main__":
    out = HERE / "img"
    out.mkdir(exist_ok=True)
    banner(out / "banner.png")
    zones_svg(out / "zones.svg")
    sessions = sorted((ROOT / "sessions").glob("*.jsonl"))
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else next((s for s in sessions if "172108" in s.name), sessions[-1] if sessions else None)
    if src:
        dread_curve(out / "dread_curve.png", src)
    print("wrote", sorted(p.name for p in out.iterdir()))
