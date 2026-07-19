#!/usr/bin/env python3
"""
Build a high-resolution, print-ready poster of the 2025 road trip.

Reads output/data.json (road-following route + classified stops) and
assets/us-states-10m.json (US Census state boundaries via us-atlas),
renders a stylized pictorial map with an Albers equal-area projection:

  - cream paper, faint state lines, terracotta route (web-app palette)
  - DM Sans + Pinyon Script (assets/fonts/, OFL) to match the web app
  - hand-placed ink glyphs: mountain ranges, conifer/broadleaf stands,
    notable lakes, and national-park markers along the way

Outputs (output/print/):
    roadtrip_print_24x12.svg      vector master (any print size) — "latest"
    roadtrip_print_24x12.png      7200x3600 @ 300 DPI — "latest"
    preview.png                   small preview for quick checks — "latest"
    versions/vN_<date>_<label>.*  a permanent, never-overwritten copy of
                                   every run, so past renders always survive
                                   future edits to this script

Every run bumps N and writes a new versions/ entry; the unversioned
"latest" files at the top level are the only thing that gets replaced.
Pass --label "some-tag" to name a run something more specific than the
default "pictorial"/"plain".

Pass --plain to omit the pictorial glyphs (mountains/trees/lakes/park
markers) and get the route + state outlines only, written to
roadtrip_print_24x12_plain.{svg,png} / preview_plain.png (+ its own
versions/ entries) instead.

Designed for a 24x12 in two-page spread in a 12x12 photo album.
No network access required. Only stdlib + matplotlib.
"""

import argparse
import datetime
import json
import math
import re
import shutil
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.patches import Circle, PathPatch, Polygon as MplPolygon
from matplotlib.path import Path as MplPath

# ── Paths ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DATA_PATH = ROOT / "output" / "data.json"
STATES_PATH = ROOT / "assets" / "us-states-10m.json"
FONT_DIR = ROOT / "assets" / "fonts"
OUT_DIR = ROOT / "output" / "print"
VERSIONS_DIR = OUT_DIR / "versions"

# ── Canvas ───────────────────────────────────────────────────────────────
PAGE_W_IN, PAGE_H_IN = 24.0, 12.0     # two-page spread of a 12x12 album
PRINT_DPI = 300
PREVIEW_DPI = 90

# ── Palette (echoes the web app: cream text, terracotta accent, gold) ────
C_OCEAN = "#D8D2BA"        # water / out-of-nation wash
C_PAPER = "#F6EFE0"        # land
C_STATE_LINE = "#C3B294"   # interior state borders
C_COAST = "#A5947A"        # nation outline / coastline
C_ROUTE = "#D96F47"        # terracotta route
C_ROUTE_CASING = "#F6EFE0" # cream casing under route
C_DAY_DOT = "#C77B54"      # day-stop stipple
C_GOLD = "#EFBE3F"         # overnight markers
C_INK = "#3A342B"          # text + marker edges
C_INK_SOFT = "#6B5D49"     # secondary text
C_RELIEF = "#8E7E66"       # pictorial glyph ink (mountains, trees)
C_FRAME = "#8A7A62"        # border rules

# ── Fonts: app faces (DM Sans / Pinyon Script), Windows fallbacks ────────
WIN_FONTS = Path("C:/Windows/Fonts")


def _font(candidates, fallback=None):
    for name in candidates:
        for base in (FONT_DIR, WIN_FONTS):
            p = base / name
            if p.exists():
                return fm.FontProperties(fname=str(p))
    return fallback or fm.FontProperties()


F_TITLE = _font(["DMSans-500.ttf", "georgia.ttf"])
F_TITLE_LT = _font(["DMSans-300.ttf", "georgia.ttf"])
F_SCRIPT = _font(["PinyonScript-400.ttf", "Gabriola.ttf"])
F_LABEL = _font(["DMSans-400.ttf", "corbel.ttf", "segoeui.ttf"])
F_LABEL_B = _font(["DMSans-500.ttf", "corbelb.ttf", "segoeuib.ttf"])
F_ITALIC = _font(["DMSans-Italic400.ttf", "corbeli.ttf"])

# ── Trip constants ───────────────────────────────────────────────────────
RALEIGH = (-78.6382, 35.7796)  # final destination; route reaches it via build_final_leg.py
TRIP_TITLE = "THE GREAT AMERICAN ROAD TRIP"
TRIP_SUBTITLE = "LOS ANGELES  TO  RALEIGH"
TRIP_DATES = "JUNE 28 – AUGUST 3, 2025"

# ── Layout data (map_layout.json) ────────────────────────────────────────
# All hand-tuned positioning lives in map_layout.json so the drag-and-drop
# editor (map_editor.html, served by serve_editor.py) can adjust it without
# touching this script. Schema notes:
#   display_names / stop_overrides — keyed "name|arrival-date" (JSON has no
#     tuple keys); reconstructed into tuples below.
#   stop_overrides — null removes a stop's marker+label; a dict overrides
#     the display name and/or plotted lat/lon while leaving the GPS route
#     untouched.
#   mountains/conifers/broadleaf — [lon, lat, scale(, big)] entries.
#   lakes — name -> polygon ring of [lon, lat].
#   parks — labeled pictorial features (kind: mountain/tree/bridge/dune/...).
#   waypoints — drive-through cities: small neutral marker + plain label.
LAYOUT_PATH = ROOT / "map_layout.json"


def _tuple_keys(d):
    return {tuple(k.split("|", 1)): v for k, v in d.items()}


_layout = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
DISPLAY_NAMES = _tuple_keys(_layout["display_names"])
STOP_OVERRIDES = _tuple_keys(_layout["stop_overrides"])

WAYPOINTS = _layout["waypoints"]

LABEL_STYLE = _layout["label_style"]
MOUNTAINS = [tuple(e) for e in _layout["mountains"]]
CONIFERS = [tuple(e) for e in _layout["conifers"]]
BROADLEAF = [tuple(e) for e in _layout["broadleaf"]]
LAKES = {k: [tuple(p) for p in v] for k, v in _layout["lakes"].items()}
PARKS = _layout["parks"]

# Custom stencil icons: vector outlines traced from the trip's own
# illustrations by build_icons.py; placements live in the layout.
ICONS_PATH = ROOT / "assets" / "icons.json"
ICON_DEFS = (json.loads(ICONS_PATH.read_text(encoding="utf-8"))
             if ICONS_PATH.exists() else {})
ICON_PLACEMENTS = _layout.get("icons", [])
ICON_BASE_IN = 0.35   # icon height in page inches at scale 1.0


# ── TopoJSON decoding (pure python) ──────────────────────────────────────
def decode_topojson(topo, object_name):
    """Return list of (state_name, [rings]) where each ring is [(lon, lat)]."""
    scale = topo["transform"]["scale"]
    translate = topo["transform"]["translate"]

    def decode_arc(arc):
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * scale[0] + translate[0], y * scale[1] + translate[1]))
        return pts

    arcs = [decode_arc(a) for a in topo["arcs"]]

    def ring_from_arc_ids(arc_ids):
        ring = []
        for aid in arc_ids:
            pts = arcs[~aid][::-1] if aid < 0 else arcs[aid]
            if ring:
                ring.extend(pts[1:])
            else:
                ring.extend(pts)
        return ring

    shapes = []
    for geom in topo["objects"][object_name]["geometries"]:
        name = geom.get("properties", {}).get("name", "")
        rings = []
        if geom["type"] == "Polygon":
            rings = [ring_from_arc_ids(r) for r in geom["arcs"]]
        elif geom["type"] == "MultiPolygon":
            for poly in geom["arcs"]:
                rings.extend(ring_from_arc_ids(r) for r in poly)
        shapes.append((name, rings))
    return shapes


# ── Albers equal-area conic projection ───────────────────────────────────
LAT0, LON0 = 40.0, -99.0        # projection origin (route mid-region)
STD1, STD2 = 36.0, 47.0         # standard parallels bracketing the route


def _albers_setup():
    p1, p2 = math.radians(STD1), math.radians(STD2)
    n = 0.5 * (math.sin(p1) + math.sin(p2))
    C = math.cos(p1) ** 2 + 2 * n * math.sin(p1)
    rho0 = math.sqrt(C - 2 * n * math.sin(math.radians(LAT0))) / n
    return n, C, rho0


_N, _C, _RHO0 = _albers_setup()


def project(lon, lat):
    theta = _N * math.radians(lon - LON0)
    rho = math.sqrt(_C - 2 * _N * math.sin(math.radians(lat))) / _N
    return rho * math.sin(theta), _RHO0 - rho * math.cos(theta)


def project_ring(ring):
    return [project(lon, lat) for lon, lat in ring]


# ── Geometry helpers ─────────────────────────────────────────────────────
def haversine_miles(lat1, lon1, lat2, lon2):
    R = 3958.8
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def point_in_rings(lon, lat, rings):
    """Even-odd rule across all rings (handles holes + multipolygons)."""
    inside = False
    for ring in rings:
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
                inside = not inside
            j = i
    return inside


def states_crossed(route_lonlat, state_shapes):
    """Distinct states touched by the route (bbox prefilter + even-odd test)."""
    bboxes = []
    for name, rings in state_shapes:
        xs = [x for r in rings for x, _ in r]
        ys = [y for r in rings for _, y in r]
        bboxes.append((name, rings, min(xs), max(xs), min(ys), max(ys)))

    hit = set()
    for lon, lat in route_lonlat[::4]:
        for name, rings, x0, x1, y0, y1 in bboxes:
            if name in hit or not (x0 <= lon <= x1 and y0 <= lat <= y1):
                continue
            if point_in_rings(lon, lat, rings):
                hit.add(name)
    return hit


# ── Pictorial glyph drawing ──────────────────────────────────────────────
def draw_mountain(ax, x, y, inch, s, zorder, big=False):
    """Ink peaks with snow chevrons. (x, y) is the base center.

    big=True draws a taller, sharper 3-peak Rockies silhouette; the
    default is the smaller 2-peak Sierra/foothill silhouette.
    """
    w = 0.13 * inch * s   # half-width of the main peak
    h = 0.145 * inch * s  # height of the main peak
    lw = 1.05 * s
    kw = dict(color=C_RELIEF, lw=lw, solid_capstyle="round",
              solid_joinstyle="round", zorder=zorder)

    if big:
        h *= 1.35
        # left peak
        ax.plot([x - 1.15 * w, x - 0.55 * w, x + 0.05 * w],
                [y, y + h * 0.82, y], **kw)
        # center peak (tallest)
        ax.plot([x - 0.35 * w, x + 0.15 * w, x + 0.75 * w],
                [y, y + h, y], **kw)
        # right peak
        ax.plot([x + 0.35 * w, x + 0.95 * w, x + 1.55 * w],
                [y, y + h * 0.70, y], **kw)
        # snow chevrons on the two tallest peaks
        ax.plot([x - 0.05 * w, x + 0.15 * w, x + 0.32 * w],
                [y + h * 0.58, y + h * 0.78, y + h * 0.55],
                color=C_RELIEF, lw=0.75 * s, solid_capstyle="round", zorder=zorder)
        ax.plot([x - 0.75 * w, x - 0.55 * w, x - 0.38 * w],
                [y + h * 0.48, y + h * 0.64, y + h * 0.46],
                color=C_RELIEF, lw=0.65 * s, solid_capstyle="round", zorder=zorder)
        return

    # main peak
    ax.plot([x - w, x - 0.1 * w, x + 0.62 * w],
            [y, y + h, y], **kw)
    # companion peak, lower and to the right
    ax.plot([x + 0.05 * w, x + 0.62 * w, x + 1.25 * w],
            [y + 0.12 * h, y + 0.62 * h, y], **kw)
    # snow chevron under the main apex
    ax.plot([x - 0.38 * w, x - 0.1 * w, x + 0.14 * w],
            [y + 0.55 * h, y + 0.72 * h, y + 0.52 * h],
            color=C_RELIEF, lw=0.7 * s, solid_capstyle="round", zorder=zorder)


def draw_conifer(ax, x, y, inch, s, zorder):
    """Small stand of 2 pines (trunk + chevron tiers)."""
    for ox, os_ in ((0.0, 1.0), (0.085, 0.72)):
        cx = x + ox * inch * s
        h = 0.16 * inch * s * os_
        w = 0.05 * inch * s * os_
        lw = 0.95 * s * os_
        kw = dict(color=C_RELIEF, lw=lw, solid_capstyle="round", zorder=zorder)
        ax.plot([cx, cx], [y, y + 0.22 * h], **kw)
        for frac, wf in ((0.25, 1.0), (0.55, 0.78), (0.82, 0.5)):
            ax.plot([cx - w * wf, cx, cx + w * wf],
                    [y + h * frac, y + h * (frac + 0.34), y + h * frac], **kw)


def draw_broadleaf(ax, x, y, inch, s, zorder):
    """Oak-ish tree: trunk + round canopy outline."""
    h = 0.075 * inch * s
    ax.plot([x, x], [y, y + h], color=C_RELIEF, lw=1.0 * s,
            solid_capstyle="round", zorder=zorder)
    ax.add_patch(Circle((x, y + h + 0.055 * inch * s), 0.062 * inch * s,
                        facecolor=C_PAPER, edgecolor=C_RELIEF,
                        lw=0.95 * s, zorder=zorder))
    # small companion
    x2 = x + 0.1 * inch * s
    ax.plot([x2, x2], [y, y + h * 0.6], color=C_RELIEF, lw=0.8 * s,
            solid_capstyle="round", zorder=zorder)
    ax.add_patch(Circle((x2, y + h * 0.6 + 0.04 * inch * s), 0.042 * inch * s,
                        facecolor=C_PAPER, edgecolor=C_RELIEF,
                        lw=0.8 * s, zorder=zorder))


def draw_bridge(ax, x, y, inch, s, zorder):
    """Shallow steel arch under a flat deck, evoking the New River Gorge Bridge."""
    unit = inch * s
    half_span = 0.22 * unit
    deck_y = y + 0.09 * unit
    arch_depth = 0.085 * unit

    ax.plot([x - half_span, x + half_span], [deck_y, deck_y],
            color=C_RELIEF, lw=1.1 * s, solid_capstyle="round", zorder=zorder)

    steps = 20
    arch_pts = [
        (x - half_span + 2 * half_span * i / steps,
         y + arch_depth * math.sin(math.pi * i / steps))
        for i in range(steps + 1)
    ]
    ax.plot([p[0] for p in arch_pts], [p[1] for p in arch_pts],
            color=C_RELIEF, lw=1.0 * s, solid_capstyle="round", zorder=zorder)

    for t in (0.25, 0.5, 0.75):
        ax_ = x - half_span + 2 * half_span * t
        ay_ = y + arch_depth * math.sin(math.pi * t)
        ax.plot([ax_, ax_], [ay_, deck_y], color=C_RELIEF, lw=0.55 * s, zorder=zorder)


def draw_dune(ax, x, y, inch, s, zorder):
    """Low sand-dune mound with a few tufts of dune grass at the crest."""
    unit = inch * s
    half_w = 0.16 * unit
    h = 0.05 * unit

    steps = 20
    dune_pts = [
        (x - half_w + 2 * half_w * i / steps, y + h * math.sin(math.pi * i / steps))
        for i in range(steps + 1)
    ]
    ax.plot([p[0] for p in dune_pts], [p[1] for p in dune_pts],
            color=C_RELIEF, lw=1.0 * s, solid_capstyle="round", zorder=zorder)

    for frac, gh in ((0.35, 0.55), (0.5, 0.75), (0.65, 0.5)):
        gx = x - half_w + 2 * half_w * frac
        gy = y + h * math.sin(math.pi * frac)
        th = 0.05 * unit * gh
        ax.plot([gx, gx - 0.012 * unit], [gy, gy + th], color=C_RELIEF,
                lw=0.6 * s, solid_capstyle="round", zorder=zorder)
        ax.plot([gx, gx + 0.014 * unit], [gy, gy + th * 0.85], color=C_RELIEF,
                lw=0.55 * s, solid_capstyle="round", zorder=zorder)


def draw_skyline(ax, x, y, inch, s, zorder):
    """Small cluster of towers nodding to IDS Center, Foshay Tower, Wells
    Fargo Center: stepped crown, obelisk spire, angled roofline."""
    unit = inch * s
    towers = [
        (-0.09 * unit, 0.05 * unit, 0.16 * unit, "step"),
        (-0.02 * unit, 0.045 * unit, 0.11 * unit, "flat"),
        (0.035 * unit, 0.035 * unit, 0.20 * unit, "spire"),
        (0.09 * unit, 0.05 * unit, 0.13 * unit, "angled"),
    ]
    for ox, w, h, kind in towers:
        cx = x + ox
        top_y = y + h
        ax.plot([cx - w / 2, cx - w / 2, cx + w / 2, cx + w / 2],
                [y, top_y, top_y, y], color=C_RELIEF, lw=0.85 * s, zorder=zorder)
        if kind == "step":
            ax.plot([cx - w * 0.3, cx - w * 0.3, cx + w * 0.3, cx + w * 0.3],
                    [top_y, top_y + 0.03 * unit, top_y + 0.03 * unit, top_y],
                    color=C_RELIEF, lw=0.75 * s, zorder=zorder)
            ax.plot([cx - w * 0.15, cx - w * 0.15, cx + w * 0.15, cx + w * 0.15],
                    [top_y + 0.03 * unit, top_y + 0.055 * unit,
                     top_y + 0.055 * unit, top_y + 0.03 * unit],
                    color=C_RELIEF, lw=0.7 * s, zorder=zorder)
        elif kind == "spire":
            ax.plot([cx - w / 2, cx, cx + w / 2],
                    [top_y, top_y + 0.045 * unit, top_y],
                    color=C_RELIEF, lw=0.75 * s, zorder=zorder)
        elif kind == "angled":
            ax.plot([cx - w / 2, cx + w / 2],
                    [top_y - 0.015 * unit, top_y + 0.015 * unit],
                    color=C_RELIEF, lw=0.75 * s, zorder=zorder)


def draw_icon(ax, icon_def, x, y, inch, s, zorder):
    """Filled compound path for a traced stencil icon, anchored at its
    bottom-center. Polys are unit-height, y-up (see build_icons.py)."""
    hgt = ICON_BASE_IN * s * inch
    verts, codes = [], []
    for ring in icon_def["polys"]:
        pts = [(x + px * hgt, y + py * hgt) for px, py in ring]
        verts.extend(pts + [pts[0]])
        codes.extend([MplPath.MOVETO] + [MplPath.LINETO] * (len(pts) - 1)
                     + [MplPath.CLOSEPOLY])
    ax.add_patch(PathPatch(MplPath(verts, codes), facecolor=C_RELIEF,
                           edgecolor="none", zorder=zorder))


def draw_pennant(ax, x, y, inch, s, zorder):
    """Small triangular pennant on a mast, lettered IU."""
    unit = inch * s
    mast_h = 0.12 * unit
    ax.plot([x, x], [y, y + mast_h], color=C_RELIEF, lw=0.9 * s,
            solid_capstyle="round", zorder=zorder)
    fw, fh = 0.09 * unit, 0.045 * unit
    flag_pts = [(x, y + mast_h), (x + fw, y + mast_h - fh / 2), (x, y + mast_h - fh)]
    ax.add_patch(MplPolygon(flag_pts, closed=True, facecolor="#8F1A1A",
                            edgecolor=C_RELIEF, lw=0.6 * s, zorder=zorder))
    ax.annotate("IU", (x + fw * 0.32, y + mast_h - fh / 2), ha="center", va="center",
                fontsize=4.6, color="#F6EFE0", fontproperties=F_LABEL_B,
                zorder=zorder + 0.1)


# ── Main render ──────────────────────────────────────────────────────────
def next_version(style_tag):
    """Smallest unused vN for this style (pictorial/plain), scanning
    versions/ so numbering survives across runs and never collides."""
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    pattern = re.compile(rf"^v(\d+)_.*{re.escape(style_tag)}")
    used = [int(m.group(1)) for f in VERSIONS_DIR.iterdir()
            if (m := pattern.match(f.name))]
    return max(used, default=0) + 1


def main(pictorial=True, label=None):
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    topo = json.loads(STATES_PATH.read_text(encoding="utf-8"))

    route = [(lon, lat) for lon, lat in data["route"]["geometry"]["coordinates"]]
    stops = data["stops"]
    overnights = [s for s in stops if s.get("type") == "overnight"]
    day_stops = [s for s in stops if s.get("type") == "day"]

    state_shapes = decode_topojson(topo, "states")
    nation_shapes = decode_topojson(topo, "nation")

    # Trip stats
    miles = sum(
        haversine_miles(route[i][1], route[i][0], route[i + 1][1], route[i + 1][0])
        for i in range(len(route) - 1)
    )
    crossed = states_crossed(route + [RALEIGH], state_shapes)
    n_photos = 8435
    n_days = 37
    stats = f"{n_days} DAYS   ·   {miles:,.0f} MILES   ·   {len(crossed)} STATES   ·   {n_photos:,} PHOTOGRAPHS"
    print(f"Route: {len(route)} pts, {miles:,.0f} mi, states: {len(crossed)}")

    # ── Projected view window: route bbox + padding, expanded to 2:1 ────
    proj_route = [project(lon, lat) for lon, lat in route]
    pr_x = [p[0] for p in proj_route] + [project(*RALEIGH)[0]]
    pr_y = [p[1] for p in proj_route] + [project(*RALEIGH)[1]]
    x0, x1 = min(pr_x), max(pr_x)
    y0, y1 = min(pr_y), max(pr_y)
    pad_x = (x1 - x0) * 0.055
    pad_y = (y1 - y0) * 0.10
    x0, x1, y0, y1 = x0 - pad_x, x1 + pad_x, y0 - pad_y, y1 + pad_y

    target = PAGE_W_IN / PAGE_H_IN
    w, h = x1 - x0, y1 - y0
    if w / h < target:                      # too tall -> widen
        extra = target * h - w
        x0 -= extra / 2
        x1 += extra / 2
    else:                                   # too wide -> heighten
        extra = w / target - h
        y0 -= extra * 0.62                  # bias extra space to the south
        y1 += extra * 0.38                  # (title block lives down there)

    inch = (x1 - x0) / PAGE_W_IN            # one page-inch in projected units

    # ── Figure ──────────────────────────────────────────────────────────
    fig = plt.figure(figsize=(PAGE_W_IN, PAGE_H_IN))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.set_facecolor(C_OCEAN)
    fig.patch.set_facecolor(C_OCEAN)

    # Nation fill (land)
    nation_polys = [project_ring(r) for _, rings in nation_shapes for r in rings]
    ax.add_collection(
        PolyCollection(nation_polys, facecolors=C_PAPER, edgecolors="none", zorder=1)
    )

    # State borders + coastline
    state_lines = [project_ring(r) for _, rings in state_shapes for r in rings]
    ax.add_collection(
        LineCollection(state_lines, colors=C_STATE_LINE, linewidths=0.7, zorder=2, alpha=0.9)
    )
    ax.add_collection(
        LineCollection(nation_polys, colors=C_COAST, linewidths=1.1, zorder=3)
    )

    # ── Pictorial layer (under the route) ───────────────────────────────
    halo = [pe.withStroke(linewidth=2.6, foreground=C_PAPER)]

    if pictorial:
        for lname, ring in LAKES.items():
            ax.add_patch(MplPolygon(project_ring(ring), closed=True,
                                    facecolor=C_OCEAN, edgecolor=C_COAST,
                                    lw=0.8, joinstyle="round", zorder=3.4))
        for lon, lat, s, big in MOUNTAINS:
            px, py = project(lon, lat)
            draw_mountain(ax, px, py, inch, s, zorder=3.6, big=big)
        for lon, lat, s in CONIFERS:
            px, py = project(lon, lat)
            draw_conifer(ax, px, py, inch, s, zorder=3.6)
        for lon, lat, s in BROADLEAF:
            px, py = project(lon, lat)
            draw_broadleaf(ax, px, py, inch, s, zorder=3.6)

        for park in PARKS:
            px, py = project(park["lon"], park["lat"])
            kind = park["kind"]
            if kind == "mountain":
                draw_mountain(ax, px, py, inch, 0.72, zorder=3.6, big=park.get("big", False))
            elif kind == "tree":
                draw_broadleaf(ax, px, py, inch, 0.85, zorder=3.6)
            elif kind == "bridge":
                draw_bridge(ax, px, py, inch, 0.95, zorder=3.6)
            elif kind == "dune":
                draw_dune(ax, px, py, inch, 0.95, zorder=3.6)
            # kind "none": label only (a custom icon usually sits nearby)
            t = ax.annotate(
                park["name"], (px, py), xytext=(park["dx"], park["dy"]),
                textcoords="offset points", ha=park["ha"], va="center",
                multialignment=park["ha"],  # per-line alignment for "\n" labels
                fontsize=6.8, color=C_INK_SOFT, fontproperties=F_ITALIC, zorder=9,
            )
            t.set_path_effects(halo)

        # Custom stencil icons (traced from the trip's illustrations)
        for e in ICON_PLACEMENTS:
            icon_def = ICON_DEFS.get(e["icon"])
            if not icon_def:
                print(f"  warning: unknown icon {e['icon']!r} skipped")
                continue
            px, py = project(e["lon"], e["lat"])
            draw_icon(ax, icon_def, px, py, inch, e.get("scale", 1.0), zorder=3.7)

    # ── Route ───────────────────────────────────────────────────────────
    rx = [p[0] for p in proj_route]
    ry = [p[1] for p in proj_route]
    ax.plot(rx, ry, color=C_ROUTE_CASING, lw=5.6, solid_capstyle="round", zorder=4)
    ax.plot(
        rx, ry, color=C_ROUTE, lw=3.0, solid_capstyle="round", zorder=5,
        path_effects=[pe.SimpleLineShadow(offset=(1.2, -1.2), shadow_color="#8a6a50", alpha=0.25, rho=1), pe.Normal()],
    )

    # The route now follows real roads all the way to Raleigh (the final
    # leg past the last GPS photo was routed in by build_final_leg.py), so
    # there is no synthetic dashed segment any more — the star sits at the
    # true route end.
    qx, qy = proj_route[-1]

    # ── Stops ───────────────────────────────────────────────────────────
    dx = [project(s["lng"], s["lat"])[0] for s in day_stops]
    dy = [project(s["lng"], s["lat"])[1] for s in day_stops]
    ax.scatter(dx, dy, s=10, c=C_DAY_DOT, alpha=0.6, lw=0, zorder=6)

    labels = []  # (display_name, x, y)
    seen = set()
    for s in overnights:
        key = (s["name"], s["arrival"][:10])
        if key in STOP_OVERRIDES:
            override = STOP_OVERRIDES[key]
            if override is None:
                continue
            name = override.get("name", DISPLAY_NAMES.get(key, s["name"]))
            lat = override.get("lat", s["lat"])
            lng = override.get("lon", s["lng"])
        else:
            name = DISPLAY_NAMES.get(key, s["name"])
            lat, lng = s["lat"], s["lng"]
        px, py = project(lng, lat)
        if name in seen:
            continue
        seen.add(name)
        labels.append((name, px, py))
    ovx = [x for _, x, _ in labels]
    ovy = [y for _, _, y in labels]
    ax.scatter(ovx, ovy, s=52, c=C_GOLD, edgecolors=C_INK, linewidths=1.1, zorder=7)

    if pictorial:
        # Decorative extras anchored to specific overnight markers. (The
        # Minneapolis skyline was superseded by the custom viking icon.)
        extra_glyphs = {
            "Bloomington": ("pennant", 0.15 * inch, 0.02 * inch),
        }
        for nm, px, py in labels:
            if nm in extra_glyphs:
                kind, ox, oy = extra_glyphs[nm]
                if kind == "pennant":
                    draw_pennant(ax, px + ox, py + oy, inch, 1.0, zorder=6.2)

    # Waypoints: cities driven through but not stayed in.
    wpx = [project(w["lon"], w["lat"])[0] for w in WAYPOINTS]
    wpy = [project(w["lon"], w["lat"])[1] for w in WAYPOINTS]
    ax.scatter(wpx, wpy, s=20, c=C_DAY_DOT, edgecolors=C_INK, linewidths=0.6,
               alpha=0.85, zorder=6.5)

    # Start + end markers
    sx, sy = proj_route[0]
    ax.scatter([sx], [sy], s=120, marker="o", facecolors="none",
               edgecolors=C_INK, linewidths=1.6, zorder=8)
    ax.scatter([sx], [sy], s=26, c=C_ROUTE, edgecolors=C_INK, linewidths=0.9, zorder=8)
    ax.scatter([qx], [qy], s=210, marker="*", c=C_GOLD, edgecolors=C_INK,
               linewidths=1.0, zorder=8)

    # ── Labels ──────────────────────────────────────────────────────────
    def put_label(name, px, py, size=8.8, bold=False, color=C_INK, sub=None):
        st = LABEL_STYLE.get(name, dict(dx=9, dy=0, ha="left", va="center"))
        # A "\n" in the name renders as two stacked lines (matplotlib native);
        # multialignment keeps the lines aligned to the label's ha side.
        t = ax.annotate(
            name, (px, py), xytext=(st["dx"], st["dy"]), textcoords="offset points",
            ha=st["ha"], va=st["va"], multialignment=st["ha"], fontsize=size, color=color,
            fontproperties=F_LABEL_B if bold else F_LABEL, zorder=9,
        )
        t.set_path_effects(halo)
        if sub:
            s2 = ax.annotate(
                sub, (px, py), xytext=(st["dx"], st["dy"] - 10.5), textcoords="offset points",
                ha=st["ha"], va=st["va"], fontsize=6.2, color=C_INK_SOFT,
                fontproperties=F_LABEL, zorder=9,
            )
            s2.set_path_effects(halo)

    for name, px, py in labels:
        put_label(name, px, py)

    for w in WAYPOINTS:
        wx, wy = project(w["lon"], w["lat"])
        put_label(w["name"], wx, wy, size=8.0, color=C_INK_SOFT)

    put_label("Los Angeles", sx, sy, size=9.8, bold=True, sub="JUNE 28")
    put_label("Raleigh", qx, qy, size=9.8, bold=True, sub="AUGUST 3")

    # ── Title block (in the open south-central plains) ──────────────────
    tx = x0 + (x1 - x0) * 0.492
    ty = y0 + (y1 - y0) * 0.175
    lh = (y1 - y0)  # for relative offsets

    ax.text(tx, ty + lh * 0.072, "Summer 2025", ha="center", va="center",
            fontsize=46, color=C_ROUTE, fontproperties=F_SCRIPT, zorder=10)
    ax.text(tx, ty, " ".join(TRIP_TITLE).replace("   ", "    "), ha="center",
            va="center", fontsize=21.5, color=C_INK, fontproperties=F_TITLE,
            zorder=10)
    ax.text(tx, ty - lh * 0.054, TRIP_SUBTITLE + "   ·   " + TRIP_DATES,
            ha="center", va="center", fontsize=10, color=C_INK_SOFT,
            fontproperties=F_LABEL, zorder=10)
    ax.plot([tx - (x1 - x0) * 0.10, tx + (x1 - x0) * 0.10],
            [ty - lh * 0.088] * 2, color=C_FRAME, lw=0.8, zorder=10)
    ax.text(tx, ty - lh * 0.121, stats, ha="center", va="center", fontsize=8.4,
            color=C_INK_SOFT, fontproperties=F_TITLE_LT, zorder=10)

    # ── Frame (double rule) ─────────────────────────────────────────────
    def frame(inset_in, lw):
        fx = inset_in / PAGE_W_IN
        fy = inset_in / PAGE_H_IN
        ax.add_patch(plt.Rectangle(
            (x0 + (x1 - x0) * fx, y0 + (y1 - y0) * fy),
            (x1 - x0) * (1 - 2 * fx), (y1 - y0) * (1 - 2 * fy),
            fill=False, edgecolor=C_FRAME, linewidth=lw, zorder=11,
        ))

    frame(0.30, 1.5)
    frame(0.40, 0.6)

    # ── Save ────────────────────────────────────────────────────────────
    # Every run gets a permanent, numbered copy in versions/ (never
    # overwritten); the unversioned "latest" files are the only thing
    # replaced, so past renders always survive future edits to this script.
    suffix = "" if pictorial else "_plain"
    style_tag = "pictorial" if pictorial else "plain"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["svg.fonttype"] = "path"   # embed fonts as outlines

    latest_svg = OUT_DIR / f"roadtrip_print_24x12{suffix}.svg"
    latest_png = OUT_DIR / f"roadtrip_print_24x12{suffix}.png"
    latest_preview = OUT_DIR / f"preview{suffix}.png"
    fig.savefig(latest_svg, format="svg", facecolor=fig.get_facecolor())
    fig.savefig(latest_png, dpi=PRINT_DPI, facecolor=fig.get_facecolor())
    fig.savefig(latest_preview, dpi=PREVIEW_DPI, facecolor=fig.get_facecolor())

    n = next_version(style_tag)
    date_str = datetime.date.today().isoformat()
    stem = f"v{n}_{date_str}_{style_tag}" + (f"-{label}" if label else "")
    shutil.copy2(latest_svg, VERSIONS_DIR / f"{stem}.svg")
    shutil.copy2(latest_png, VERSIONS_DIR / f"{stem}.png")
    shutil.copy2(latest_preview, VERSIONS_DIR / f"{stem}_preview.png")

    print(f"Wrote {latest_svg}, {latest_png} "
          f"({PAGE_W_IN * PRINT_DPI:.0f}x{PAGE_H_IN * PRINT_DPI:.0f}), {latest_preview}")
    print(f"Archived as {VERSIONS_DIR}/{stem}.{{svg,png}}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--plain", action="store_true",
                        help="omit pictorial glyphs; route + state outlines only")
    parser.add_argument("--label", default=None,
                        help="short tag appended to this run's versions/ filename")
    args = parser.parse_args()
    main(pictorial=not args.plain, label=args.label)
