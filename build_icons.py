#!/usr/bin/env python3
"""
Vectorize the custom location illustrations into stencil-style icons.

Reads fine-line PNG illustrations from the OneDrive media folder, boils
each down to a small stencil (downsample -> blur -> threshold, which
thickens hairline strokes into readable marks at map scale), traces the
ink with contourpy (a matplotlib dependency), simplifies the polygons,
and writes normalized vector outlines to assets/icons.json:

    { "<key>": {"aspect": w/h, "polys": [[[x, y], ...], ...]}, ... }

Coordinates are y-up, height-normalized to 1.0, x centered on 0, y=0 at
the icon's base — build_print_map.py and map_editor.js render them as
filled even-odd compound paths.

Also writes output/print/icon_contact_sheet.png so every conversion can
be eyeballed at roughly print scale in one image.

Re-run after adding/retuning icons. Per-icon overrides live in ICONS.
"""

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath

import contourpy

SRC_DIR = Path(r"C:\Users\hgste\OneDrive\Documents\Side Projects\Photo Tools"
               r"\2025 Roadtrip Map\media\custom map location icons")
OUT_JSON = Path(__file__).parent / "assets" / "icons.json"
SHEET = Path(__file__).parent / "output" / "print" / "icon_contact_sheet.png"

# key -> source file + optional tuning overrides:
#   grid: max long-side pixels before tracing (smaller = chunkier stencil)
#   blur: gaussian radius applied at grid scale
#   thr:  ink threshold on blurred luminance (higher = more ink kept)
ICONS = {
    "la-house":        dict(f="los angeles empire house.png"),
    "sb-palms":        dict(f="santa barbara palm trees.png"),
    "paso-grapes":     dict(f="paso robles grapes.png"),
    "dv-dunes":        dict(f="death valley dunes.png"),
    "zion-narrows":    dict(f="zion.png"),
    "cedar-breaks":    dict(f="cedar breaks state park.png"),
    "cathedral-gorge": dict(f="cathedral gorge.png"),
    "wendover-will":   dict(f="wendover will.png"),
    "sawtooth-bear":   dict(f="sawtooth bear.png"),
    "missoula-grizzly": dict(f="missoula grizzly.png"),
    "kalispell-glacier": dict(f="kalispell glacier.png"),
    "paradise-tent":   dict(f="paradise valley under canvas tent.png"),
    "wy-arch":         dict(f="west yellowston ewelcome arch.png"),
    "tetons":          dict(f="tetans.png"),
    "old-faithful":    dict(f="yellowstone old faithful.png"),
    "custer-burro":    dict(f="custer state park burro.png"),
    "rushmore":        dict(f="mt rushmore.png"),
    "crazy-horse":     dict(f="crazy horse.png"),
    "badlands-chirps": dict(f="badlands chirps.png"),
    "sioux-sunflower": dict(f="sioux falls sunflower.png"),
    "newulm-beer":     dict(f="new ulm beer.png"),
    "mpls-viking":     dict(f="minneapolis viking.png"),
    "door-cider":      dict(f="door county cider.png"),
    "up-aframe":       dict(f="UP A frame pine trees.png"),
    "tc-cherries":     dict(f="traverse city cherries.png"),
    "sleeping-bear":   dict(f="sleeping bear dunes.png"),
    "indiana-dunes":   dict(f="indiana dunes.png"),
    "nrg-bridge":      dict(f="new river gorge bridge.png"),
}

DEFAULTS = dict(grid=170, blur=1.0, thr=0.62)


def simplify(pts, tol):
    """Douglas-Peucker for a closed ring (first == last point).

    DP anchored on identical endpoints degenerates (every ring collapses
    to 2 points), so drop the closing duplicate and split the ring at the
    vertex farthest from point 0, simplifying each open half.
    """
    P = [tuple(p) for p in pts]
    if len(P) > 1 and P[0] == P[-1]:
        P = P[:-1]
    if len(P) <= 4:
        return P

    def dp(seq):
        if len(seq) <= 2:
            return seq
        (x1, y1), (x2, y2) = seq[0], seq[-1]
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1e-12
        dmax, idx = 0.0, 0
        for i in range(1, len(seq) - 1):
            d = abs(dy * seq[i][0] - dx * seq[i][1] + x2 * y1 - y2 * x1) / norm
            if d > dmax:
                dmax, idx = d, i
        if dmax > tol:
            return dp(seq[:idx + 1])[:-1] + dp(seq[idx:])
        return [seq[0], seq[-1]]

    far = max(range(1, len(P)),
              key=lambda i: (P[i][0] - P[0][0]) ** 2 + (P[i][1] - P[0][1]) ** 2)
    half1 = dp(P[:far + 1])
    half2 = dp(P[far:] + [P[0]])
    return half1[:-1] + half2[:-1]


def ring_area(pts):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        a += x1 * y2 - x2 * y1
    return a / 2


def trace(cfg):
    img = Image.open(SRC_DIR / cfg["f"]).convert("RGBA")
    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
    lum = np.asarray(Image.alpha_composite(bg, img).convert("L"), dtype=float) / 255.0

    # Crop to ink bounding box with a small pad.
    ink = lum < 0.85
    if not ink.any():
        raise ValueError(f"{cfg['f']}: no ink found")
    ys, xs = np.where(ink)
    pad = int(0.03 * max(img.size))
    y0, y1 = max(0, ys.min() - pad), min(lum.shape[0], ys.max() + pad)
    x0, x1 = max(0, xs.min() - pad), min(lum.shape[1], xs.max() + pad)
    lum = lum[y0:y1, x0:x1]

    # Pre-thicken hairline strokes at source resolution (grayscale erosion
    # = ink dilation) so they survive the heavy downsample, then shrink to
    # `grid` px, blur, and measure inkness.
    h, w = lum.shape
    grid = cfg.get("grid", DEFAULTS["grid"])
    src = Image.fromarray((lum * 255).astype(np.uint8))
    k = round(max(h, w) / grid * cfg.get("thicken", 1.0))
    k = max(3, k | 1)  # odd, >= 3
    src = src.filter(ImageFilter.MinFilter(k))
    scale = grid / max(h, w)
    small = src.resize(
        (max(2, round(w * scale)), max(2, round(h * scale))), Image.LANCZOS)
    small = small.filter(ImageFilter.GaussianBlur(cfg.get("blur", DEFAULTS["blur"])))
    inkness = 1.0 - np.asarray(small, dtype=float) / 255.0

    # Threshold with an adaptive fallback: if the default level keeps too
    # little (very light linework) or too much ink, pick a percentile so
    # every illustration lands in a printable coverage band.
    thr = cfg.get("thr", DEFAULTS["thr"])
    level = 1.0 - thr
    frac = float((inkness > level).mean())
    if frac < 0.04:
        level = float(np.quantile(inkness, 0.96))
    elif frac > 0.50:
        level = float(np.quantile(inkness, 0.55))

    # Trace the threshold contour. contourpy's filled() returns exterior
    # rings and holes wound for correct compound-path rendering.
    gen = contourpy.contour_generator(z=inkness,
                                      fill_type=contourpy.FillType.OuterOffset)
    boundaries, all_offsets = gen.filled(level, 2.0)

    hh = inkness.shape[0]
    polys = []
    for pts_arr, offsets in zip(boundaries, all_offsets):
        for i in range(len(offsets) - 1):
            ring = pts_arr[offsets[i]:offsets[i + 1]]
            ring = simplify(ring, tol=0.55)
            if len(ring) < 3 or abs(ring_area(ring)) < 2.5:
                continue
            # y-flip to y-up
            polys.append([[float(x), float(hh - y)] for x, y in ring])
    if not polys:
        raise ValueError(f"{cfg['f']}: traced to nothing (thr too low?)")

    # Normalize: height 1.0, x centered, y=0 at base.
    all_pts = [p for ring in polys for p in ring]
    xs_ = [p[0] for p in all_pts]
    ys_ = [p[1] for p in all_pts]
    minx, maxx, miny, maxy = min(xs_), max(xs_), min(ys_), max(ys_)
    height = maxy - miny or 1.0
    cx = (minx + maxx) / 2
    norm = [[[round((x - cx) / height, 3), round((y - miny) / height, 3)]
             for x, y in ring] for ring in polys]
    return {"aspect": round((maxx - minx) / height, 3), "polys": norm}


def icon_path(icon, x=0.0, y=0.0, s=1.0):
    """matplotlib Path for an icon placed at (x, y), height s."""
    verts, codes = [], []
    for ring in icon["polys"]:
        pts = [(x + px * s, y + py * s) for px, py in ring]
        verts.extend(pts + [pts[0]])
        codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(pts) - 1)
                     + [MplPath.CLOSEPOLY])
    return MplPath(verts, codes)


def contact_sheet(icons):
    cols = 6
    rows = math.ceil(len(icons) / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(cols * 2.1, rows * 2.4))
    fig.patch.set_facecolor("#F6EFE0")
    for ax, (key, icon) in zip(axes.flat, icons.items()):
        ax.add_patch(PathPatch(icon_path(icon), facecolor="#8E7E66",
                               edgecolor="none"))
        npts = sum(len(r) for r in icon["polys"])
        ax.set_title(f"{key}  ({len(icon['polys'])} rings, {npts} pts)",
                     fontsize=6.5, color="#3A342B")
        half = max(0.75, icon["aspect"] / 2 + 0.1)
        ax.set_xlim(-half, half)
        ax.set_ylim(-0.12, 1.12)
        ax.set_aspect("equal")
        ax.axis("off")
        ax.set_facecolor("#F6EFE0")
    for ax in axes.flat[len(icons):]:
        ax.axis("off")
    SHEET.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(SHEET, dpi=110, facecolor=fig.get_facecolor(),
                bbox_inches="tight")
    plt.close(fig)


def main():
    icons = {}
    total_pts = 0
    for key, cfg in ICONS.items():
        icon = trace(cfg)
        icons[key] = icon
        npts = sum(len(r) for r in icon["polys"])
        total_pts += npts
        print(f"{key:18s} {len(icon['polys']):4d} rings {npts:6d} pts "
              f"aspect {icon['aspect']}")
    OUT_JSON.write_text(json.dumps(icons, ensure_ascii=False),
                        encoding="utf-8")
    print(f"\nWrote {OUT_JSON} ({OUT_JSON.stat().st_size / 1024:.0f} KB, "
          f"{total_pts} pts total)")
    contact_sheet(icons)
    print(f"Wrote {SHEET}")


if __name__ == "__main__":
    main()
