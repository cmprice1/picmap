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
    roadtrip_print_24x12.svg      vector master (any print size)
    roadtrip_print_24x12.png      7200x3600 @ 300 DPI
    preview.png                   small preview for quick checks

Designed for a 24x12 in two-page spread in a 12x12 photo album.
No network access required. Only stdlib + matplotlib.
"""

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.font_manager as fm
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.patches import Circle, Polygon as MplPolygon

# ── Paths ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DATA_PATH = ROOT / "output" / "data.json"
STATES_PATH = ROOT / "assets" / "us-states-10m.json"
FONT_DIR = ROOT / "assets" / "fonts"
OUT_DIR = ROOT / "output" / "print"

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
RALEIGH = (-78.6382, 35.7796)  # trip's stated destination (no GPS photos on final leg)
TRIP_TITLE = "THE GREAT AMERICAN ROAD TRIP"
TRIP_SUBTITLE = "LOS ANGELES  TO  RALEIGH"
TRIP_DATES = "JUNE 28 – AUGUST 3, 2025"

# Display names for overnight stops. Keys are (data.json name, arrival date).
# County-level geocodes are mapped to the actual place per stop coordinates.
DISPLAY_NAMES = {
    ("Inyo County", "2025-07-03"): "Death Valley",
    ("Washington County", "2025-07-05"): "Zion",
    ("Blaine County", "2025-07-10"): "Sawtooth Valley",
    ("Park County", "2025-07-17"): "Paradise Valley",
    ("Teton County", "2025-07-18"): "The Tetons",
    ("Park County", "2025-07-20"): "Yellowstone",
    ("Carbon County", "2025-07-20"): "Red Lodge",
    ("Lawrence County", "2025-07-23"): "Black Hills",
    ("Town of Egg Harbor", "2025-07-27"): "Door County",
    ("Stephenson Township", "2025-07-29"): "Cedar River",
    ("Moran Township", "2025-07-30"): "St. Ignace",
    ("Surry County", "2025-08-03"): "Mount Airy",
}

# Label placement overrides, keyed by display name.
# dx/dy in points relative to the marker; ha/va matplotlib alignment.
LABEL_STYLE = {
    "Los Angeles":     dict(dx=-8, dy=-4, ha="right", va="top"),
    "Santa Barbara":   dict(dx=-9, dy=2, ha="right", va="center"),
    "Paso Robles":     dict(dx=-9, dy=4, ha="right", va="center"),
    "Death Valley":    dict(dx=8, dy=-9, ha="left", va="center"),
    "Las Vegas":       dict(dx=9, dy=-6, ha="left", va="center"),
    "Zion":            dict(dx=9, dy=-3, ha="left", va="center"),
    "Wendover":        dict(dx=-10, dy=0, ha="right", va="center"),
    "Sawtooth Valley": dict(dx=-10, dy=2, ha="right", va="center"),
    "Missoula":        dict(dx=-10, dy=2, ha="right", va="center"),
    "Kalispell":       dict(dx=-10, dy=3, ha="right", va="center"),
    "Paradise Valley": dict(dx=10, dy=6, ha="left", va="center"),
    "The Tetons":      dict(dx=-10, dy=-3, ha="right", va="center"),
    "West Yellowstone": dict(dx=-13, dy=-1, ha="right", va="center"),
    "Yellowstone":     dict(dx=14, dy=-16, ha="left", va="center"),
    "Red Lodge":       dict(dx=9, dy=-9, ha="left", va="center"),
    "Black Hills":     dict(dx=0, dy=11, ha="center", va="bottom"),
    "Sioux Falls":     dict(dx=0, dy=-12, ha="center", va="top"),
    "Minneapolis":     dict(dx=-4, dy=11, ha="center", va="bottom"),
    "Door County":     dict(dx=11, dy=-2, ha="left", va="center"),
    "Cedar River":     dict(dx=-10, dy=5, ha="right", va="center"),
    "St. Ignace":      dict(dx=2, dy=11, ha="center", va="bottom"),
    "Traverse City":   dict(dx=8, dy=-13, ha="left", va="center"),
    "Cincinnati":      dict(dx=-2, dy=-12, ha="center", va="top"),
    "Mount Airy":      dict(dx=-4, dy=11, ha="center", va="bottom"),
    "Raleigh":         dict(dx=10, dy=-4, ha="left", va="center"),
}

# ── Pictorial layer ──────────────────────────────────────────────────────
# All positions are (lon, lat, scale). Only geography the trip actually
# touched: ranges flanking the drive, forests along it, lakes seen from
# the road, and parks evidenced by day-stop clusters in the data.
MOUNTAINS = [
    # Sierra Nevada (west of the Owens Valley leg)
    (-118.60, 36.55, 1.00), (-118.85, 36.95, 1.15), (-119.10, 37.35, 0.95),
    # Great Basin ranges (US-93 crossing, Nevada)
    (-115.85, 38.70, 0.80), (-116.50, 39.70, 0.90),
    # Sawtooths (Idaho)
    (-115.35, 44.30, 1.05), (-115.00, 44.50, 0.85),
    # Bitterroots (Montana/Idaho line)
    (-114.75, 46.05, 0.95), (-114.95, 46.50, 1.05),
    # Glacier country
    (-114.35, 48.50, 1.10), (-113.10, 48.82, 0.90),
    # Absaroka-Beartooth (south of the Beartooth Highway leg)
    (-109.55, 44.52, 0.95), (-109.10, 44.62, 0.75),
    # Tetons (south of Jackson, Snake River country)
    (-110.72, 43.15, 0.90),
    # Black Hills
    (-104.25, 43.95, 0.75), (-104.10, 43.65, 0.85),
    # Zion high country
    (-112.72, 36.95, 0.70),
    # Appalachians / Blue Ridge (WV-VA-NC)
    (-80.15, 38.40, 0.90), (-80.50, 37.75, 1.00), (-80.45, 37.35, 0.80),
    (-79.85, 38.75, 0.75),
]

CONIFERS = [
    # Montana / Idaho forests
    (-114.95, 47.50, 1.00), (-113.35, 47.10, 0.90), (-116.10, 45.20, 0.80),
    # Lodgepole country west of Yellowstone
    (-111.85, 44.25, 0.85),
    # Northwoods: Minnesota, Wisconsin, Michigan UP
    (-94.50, 46.55, 0.95), (-89.70, 45.85, 1.00), (-88.70, 46.25, 0.90),
    (-86.25, 46.30, 0.85),
]

BROADLEAF = [
    # California oaks near the 101
    (-120.00, 35.85, 0.80),
    # Ohio Valley hardwoods
    (-83.55, 39.55, 0.90), (-82.90, 38.45, 0.85),
]

# Stylized lakes the route ran alongside (simplified shapes).
LAKES = {
    "Great Salt Lake": [
        (-112.95, 41.35), (-112.75, 41.60), (-112.40, 41.70), (-112.20, 41.50),
        (-112.18, 41.20), (-112.35, 40.95), (-112.70, 40.85), (-112.92, 41.05),
    ],
    "Flathead Lake": [
        (-114.32, 47.95), (-114.15, 48.05), (-113.98, 47.95), (-113.95, 47.78),
        (-114.08, 47.66), (-114.25, 47.72),
    ],
    "Yellowstone Lake": [
        (-110.50, 44.48), (-110.32, 44.54), (-110.20, 44.44), (-110.28, 44.32),
        (-110.50, 44.36),
    ],
}

# Parks with day-stop evidence in data.json that lack an overnight label.
# (glyph kind, label position/alignment)
PARKS = [
    dict(name="Glacier National Park", lon=-113.55, lat=48.60, kind="mountain",
         dx=7, dy=-2, ha="left"),
    dict(name="Badlands", lon=-102.20, lat=43.62, kind="mountain",
         dx=0, dy=-11, ha="center"),
    dict(name="New River Gorge", lon=-81.95, lat=37.72, kind="tree",
         dx=-7, dy=-2, ha="right"),
]


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
def draw_mountain(ax, x, y, inch, s, zorder):
    """Two ink peaks with a snow chevron. (x, y) is the base center."""
    w = 0.13 * inch * s   # half-width of the main peak
    h = 0.145 * inch * s  # height of the main peak
    lw = 1.05 * s
    kw = dict(color=C_RELIEF, lw=lw, solid_capstyle="round",
              solid_joinstyle="round", zorder=zorder)
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


# ── Main render ──────────────────────────────────────────────────────────
def main():
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
    for lname, ring in LAKES.items():
        ax.add_patch(MplPolygon(project_ring(ring), closed=True,
                                facecolor=C_OCEAN, edgecolor=C_COAST,
                                lw=0.8, joinstyle="round", zorder=3.4))
    for lon, lat, s in MOUNTAINS:
        px, py = project(lon, lat)
        draw_mountain(ax, px, py, inch, s, zorder=3.6)
    for lon, lat, s in CONIFERS:
        px, py = project(lon, lat)
        draw_conifer(ax, px, py, inch, s, zorder=3.6)
    for lon, lat, s in BROADLEAF:
        px, py = project(lon, lat)
        draw_broadleaf(ax, px, py, inch, s, zorder=3.6)

    halo = [pe.withStroke(linewidth=2.6, foreground=C_PAPER)]

    for park in PARKS:
        px, py = project(park["lon"], park["lat"])
        if park["kind"] == "mountain":
            draw_mountain(ax, px, py, inch, 0.72, zorder=3.6)
        else:
            draw_broadleaf(ax, px, py, inch, 0.85, zorder=3.6)
        t = ax.annotate(
            park["name"], (px, py), xytext=(park["dx"], park["dy"]),
            textcoords="offset points", ha=park["ha"], va="center",
            fontsize=6.8, color=C_INK_SOFT, fontproperties=F_ITALIC, zorder=9,
        )
        t.set_path_effects(halo)

    # ── Route ───────────────────────────────────────────────────────────
    rx = [p[0] for p in proj_route]
    ry = [p[1] for p in proj_route]
    ax.plot(rx, ry, color=C_ROUTE_CASING, lw=5.6, solid_capstyle="round", zorder=4)
    ax.plot(
        rx, ry, color=C_ROUTE, lw=3.0, solid_capstyle="round", zorder=5,
        path_effects=[pe.SimpleLineShadow(offset=(1.2, -1.2), shadow_color="#8a6a50", alpha=0.25, rho=1), pe.Normal()],
    )

    # Dashed final leg to Raleigh
    ex, ey = proj_route[-1]
    qx, qy = project(*RALEIGH)
    ax.plot([ex, qx], [ey, qy], color=C_ROUTE, lw=2.2, ls=(0, (1.6, 2.4)),
            solid_capstyle="round", zorder=5, alpha=0.85)

    # ── Stops ───────────────────────────────────────────────────────────
    dx = [project(s["lng"], s["lat"])[0] for s in day_stops]
    dy = [project(s["lng"], s["lat"])[1] for s in day_stops]
    ax.scatter(dx, dy, s=10, c=C_DAY_DOT, alpha=0.6, lw=0, zorder=6)

    labels = []  # (display_name, x, y)
    seen = set()
    for s in overnights:
        key = (s["name"], s["arrival"][:10])
        name = DISPLAY_NAMES.get(key, s["name"])
        px, py = project(s["lng"], s["lat"])
        if name in seen:
            continue
        seen.add(name)
        labels.append((name, px, py))
    ovx = [x for _, x, _ in labels]
    ovy = [y for _, _, y in labels]
    ax.scatter(ovx, ovy, s=52, c=C_GOLD, edgecolors=C_INK, linewidths=1.1, zorder=7)

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
        t = ax.annotate(
            name, (px, py), xytext=(st["dx"], st["dy"]), textcoords="offset points",
            ha=st["ha"], va=st["va"], fontsize=size, color=color,
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
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    plt.rcParams["svg.fonttype"] = "path"   # embed fonts as outlines
    fig.savefig(OUT_DIR / "roadtrip_print_24x12.svg", format="svg",
                facecolor=fig.get_facecolor())
    fig.savefig(OUT_DIR / "roadtrip_print_24x12.png", dpi=PRINT_DPI,
                facecolor=fig.get_facecolor())
    fig.savefig(OUT_DIR / "preview.png", dpi=PREVIEW_DPI,
                facecolor=fig.get_facecolor())
    print(f"Wrote {OUT_DIR}/roadtrip_print_24x12.svg, .png ({PAGE_W_IN * PRINT_DPI:.0f}x{PAGE_H_IN * PRINT_DPI:.0f}), preview.png")


if __name__ == "__main__":
    main()
