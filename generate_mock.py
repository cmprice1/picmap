#!/usr/bin/env python3
"""
Generate mock data.json and SVG placeholder photos for the roadtrip-map app.
Run once to populate output/ so the frontend works end-to-end before real
Takeout files arrive.

Route: Las Vegas → Zion → Salt Flats → Arches → Canyonlands → Monument Valley → Grand Canyon
"""

import json
import math
from pathlib import Path

OUTPUT_DIR = Path("output")
PHOTOS_DIR = OUTPUT_DIR / "photos"


# ---------------------------------------------------------------------------
# Route (hand-tuned to follow real highways)
# ---------------------------------------------------------------------------

ROUTE_SEGMENTS = [
    # Las Vegas → Zion (I-15 N through St. George)
    [(-115.14, 36.17), (-114.65, 36.62), (-113.59, 37.10), (-113.03, 37.30)],

    # Zion → Bonneville Salt Flats (I-15 N through SLC, then I-80 W)
    [(-113.03, 37.30), (-111.89, 40.76), (-112.45, 40.73), (-113.78, 40.77)],

    # Salt Flats → Arches (I-80 E back to SLC, then US-6 SE, then US-191 N)
    [(-113.78, 40.77), (-111.89, 40.76), (-110.95, 39.52), (-110.30, 38.90),
     (-109.59, 38.73)],

    # Arches → Canyonlands (south to Moab, then UT-313 W into the park)
    [(-109.59, 38.73), (-109.55, 38.55), (-109.79, 38.21)],

    # Canyonlands → Monument Valley (back to Moab, US-191 S, US-163)
    [(-109.79, 38.21), (-109.55, 38.55), (-109.34, 37.87),
     (-109.55, 37.28), (-110.10, 37.00)],

    # Monument Valley → Grand Canyon (US-160 W → US-89 → AZ-64 S)
    [(-110.10, 37.00), (-111.00, 36.60), (-111.42, 36.06), (-112.14, 36.05)],
]


def build_route():
    coords = []
    for seg in ROUTE_SEGMENTS:
        for i in range(len(seg) - 1):
            p1, p2 = seg[i], seg[i + 1]
            for j in range(20):
                t = j / 20
                coords.append([p1[0] + (p2[0] - p1[0]) * t,
                                p1[1] + (p2[1] - p1[1]) * t])
    coords.append(ROUTE_SEGMENTS[-1][-1])
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}}


# ---------------------------------------------------------------------------
# Stop definitions  (7 stops: 4 overnight, 3 day)
# ---------------------------------------------------------------------------

STOPS = [
    {
        "id": "stop_01",
        "name": "Las Vegas",
        "location": "Las Vegas, Nevada",
        "lat": 36.1699, "lng": -115.1398,
        "arrival":   "2025-05-14T15:00:00",
        "departure": "2025-05-15T09:00:00",
        "duration_hours": 18.0,
        "type": "overnight",
        "order": 1,
        "theme": "lasvegas",
        "photo_captions": [
            "The Strip at dusk",
            "Fremont Street Experience",
            "Neon signs after midnight",
            "Desert sunrise on the way out",
        ],
    },
    {
        "id": "stop_02",
        "name": "Zion National Park",
        "location": "Zion National Park, Utah",
        "lat": 37.2982, "lng": -113.0263,
        "arrival":   "2025-05-15T13:00:00",
        "departure": "2025-05-17T08:00:00",
        "duration_hours": 43.0,
        "type": "overnight",
        "order": 2,
        "theme": "zion",
        "photo_captions": [
            "Angels Landing summit",
            "Virgin River Narrows",
            "Emerald Pools waterfall",
            "Canyon overlook at sunset",
            "Watchman from the valley",
            "Dawn light on the canyon walls",
            "Riverside Walk fog",
            "Kolob Arch viewpoint",
        ],
    },
    {
        "id": "stop_03",
        "name": "Bonneville Salt Flats",
        "location": "Bonneville Salt Flats, Utah",
        "lat": 40.7655, "lng": -113.8935,
        "arrival":   "2025-05-17T14:00:00",
        "departure": "2025-05-17T16:30:00",
        "duration_hours": 2.5,
        "type": "day",
        "order": 3,
        "theme": "saltflats",
        "photo_captions": [
            "Infinite white expanse",
            "Sky reflection in the brine",
            "Horizon line at the flats",
        ],
    },
    {
        "id": "stop_04",
        "name": "Arches National Park",
        "location": "Arches National Park, Utah",
        "lat": 38.7331, "lng": -109.5925,
        "arrival":   "2025-05-18T12:00:00",
        "departure": "2025-05-20T08:30:00",
        "duration_hours": 44.5,
        "type": "overnight",
        "order": 4,
        "theme": "arches",
        "photo_captions": [
            "Delicate Arch at golden hour",
            "Landscape Arch morning mist",
            "Double Arch framing the sky",
            "Balanced Rock silhouette",
            "Park Avenue sandstone fins",
            "Fiery Furnace labyrinth",
            "Sunset over the Windows",
        ],
    },
    {
        "id": "stop_05",
        "name": "Canyonlands",
        "location": "Canyonlands National Park, Utah",
        "lat": 38.2136, "lng": -109.7932,
        "arrival":   "2025-05-20T10:00:00",
        "departure": "2025-05-20T13:30:00",
        "duration_hours": 3.5,
        "type": "day",
        "order": 5,
        "theme": "canyonlands",
        "photo_captions": [
            "Island in the Sky overlook",
            "Mesa Arch at sunrise",
            "Colorado River far below",
            "Upheaval Dome crater",
        ],
    },
    {
        "id": "stop_06",
        "name": "Monument Valley",
        "location": "Monument Valley Navajo Tribal Park, Arizona",
        "lat": 36.9988, "lng": -110.0985,
        "arrival":   "2025-05-20T18:00:00",
        "departure": "2025-05-21T09:00:00",
        "duration_hours": 15.0,
        "type": "overnight",
        "order": 6,
        "theme": "monument",
        "photo_captions": [
            "The Mittens at sunset",
            "John Ford Point dust trail",
            "Merrick Butte silhouette",
            "Milky Way over the buttes",
            "Dawn breaking on the valley",
        ],
    },
    {
        "id": "stop_07",
        "name": "Grand Canyon",
        "location": "Grand Canyon South Rim, Arizona",
        "lat": 36.0544, "lng": -112.1401,
        "arrival":   "2025-05-21T12:00:00",
        "departure": "2025-05-21T16:00:00",
        "duration_hours": 4.0,
        "type": "day",
        "order": 7,
        "theme": "grandcanyon",
        "photo_captions": [
            "Mather Point panorama",
            "Bright Angel Trail descent",
            "Colorado River ribbon far below",
            "Sunset from the South Rim",
            "Canyon layers at last light",
        ],
    },
]

WAYPOINTS = [
    {"id": "wp_01", "name": "St. George, UT",
     "lat": 37.105, "lng": -113.583, "timestamp": "2025-05-15T11:30:00"},
    {"id": "wp_02", "name": "Salt Lake City",
     "lat": 40.760, "lng": -111.891, "timestamp": "2025-05-17T10:00:00"},
    {"id": "wp_03", "name": "Price Canyon, UT",
     "lat": 39.52, "lng": -110.95, "timestamp": "2025-05-18T08:30:00"},
    {"id": "wp_04", "name": "Moab, UT",
     "lat": 38.573, "lng": -109.549, "timestamp": "2025-05-20T09:00:00"},
]


# ---------------------------------------------------------------------------
# SVG helpers
# ---------------------------------------------------------------------------

def hex_darken(hex_color, factor=0.25):
    h = hex_color.lstrip("#")
    r = int(int(h[0:2], 16) * (1 - factor))
    g = int(int(h[2:4], 16) * (1 - factor))
    b = int(int(h[4:6], 16) * (1 - factor))
    return f"#{r:02x}{g:02x}{b:02x}"


# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

THEMES = {
    "lasvegas": {
        "sky_top": "#0a0520", "sky_mid": "#1a0a40", "ground": "#0d0d1a",
        "silhouette": "#15083a", "accent": "#cc44ff", "label_color": "#ff99ff",
        "scene": "city_night",
    },
    "zion": {
        "sky_top": "#5ba3d0", "sky_mid": "#f4a261", "ground": "#7a2e1a",
        "silhouette": "#5c2010", "accent": "#e07b54", "label_color": "#fde9d9",
        "scene": "canyon",
    },
    "saltflats": {
        "sky_top": "#2560a0", "sky_mid": "#a8cce8", "ground": "#eef4f8",
        "silhouette": "#7a9ab8", "accent": "#50a0d8", "label_color": "#e0f0fc",
        "scene": "saltflats",
    },
    "arches": {
        "sky_top": "#87c4e8", "sky_mid": "#f9c74f", "ground": "#8b3a14",
        "silhouette": "#6b2a0e", "accent": "#f4a460", "label_color": "#fde8cc",
        "scene": "arch",
    },
    "canyonlands": {
        "sky_top": "#4a90c0", "sky_mid": "#e09060", "ground": "#7a2a10",
        "silhouette": "#5c2010", "accent": "#e07040", "label_color": "#fde0c8",
        "scene": "wide_mesa",
    },
    "monument": {
        "sky_top": "#e86030", "sky_mid": "#ffc040", "ground": "#7a1a0a",
        "silhouette": "#5c1008", "accent": "#ffd700", "label_color": "#fff5cc",
        "scene": "buttes",
    },
    "grandcanyon": {
        "sky_top": "#1a1040", "sky_mid": "#c2410c", "ground": "#6b1a0a",
        "silhouette": "#4a1008", "accent": "#f97316", "label_color": "#ffe0cc",
        "scene": "layers",
    },
}


# ---------------------------------------------------------------------------
# Scene functions
# ---------------------------------------------------------------------------

def svg_scene_city_night(t, variant):
    """Las Vegas – night skyline with neon glow."""
    s = t["silhouette"]
    a = t["accent"]
    heights = [88, 110, 140, 95, 130, 160, 115, 100, 145, 120, 90, 135, 155, 105, 80]
    pts, x = "0,340 ", 0
    for i, h in enumerate(heights):
        adj = h + (i * 47 + variant * 31) % 28 - 14
        top = 533 - adj
        w = 38 + (i * 13) % 18
        pts += f"{x},{top} {x+w},{top} "
        x += w + 4 + (i * 5) % 7
    pts += f"800,340 800,533 0,533"
    # Glowing windows
    windows, wx = "", 10
    for col in range(len(heights)):
        h = heights[col % len(heights)]
        w = 38 + (col * 13) % 18
        for row in range(3):
            wy = 533 - h + 18 + row * 26
            op = 0.30 + ((col * 7 + row * 3) % 10) / 14
            windows += (f'<rect x="{wx+5}" y="{wy}" width="5" height="9" fill="{a}" opacity="{op:.2f}"/>'
                        f'<rect x="{wx+w-11}" y="{wy}" width="5" height="9" fill="{a}" opacity="{op:.2f}"/>')
        wx += w + 4 + (col * 5) % 7
    return f'<polygon points="{pts}" fill="{s}"/>{windows}'


def svg_scene_canyon(t, variant):
    """Zion – slot canyon walls framing a sky corridor."""
    s = t["silhouette"]
    d = hex_darken(s, 0.2)
    o = variant * 9
    lwall = f"0,0 0,533 {258+o},533 {263+o},72 {238+o},38 {268+o},0"
    rwall = f"800,0 800,533 {542-o},533 {537-o},82 {565-o},45 {532-o},0"
    river = f"M{245+o},533 Q{350},405 {400},370 Q{452},338 {555-o},533"
    return (f'<polygon points="{lwall}" fill="{s}"/>'
            f'<polygon points="{rwall}" fill="{s}"/>'
            f'<polygon points="{lwall}" fill="{d}" opacity="0.22"/>'
            f'<path d="{river}" stroke="#4a9aba" stroke-width="22" fill="none" opacity="0.40"/>')


def svg_scene_saltflats(t, variant):
    """Bonneville Salt Flats – infinite white horizon, sky reflection."""
    sky_mid = t["sky_mid"]
    mtn = t["silhouette"]
    horizon = 295 + (variant % 3) * 8
    # Distant mountain ridge (barely visible, very low contrast)
    mtn_ridge = (f'<polygon points="0,{horizon} 60,{horizon-22} 150,{horizon-18} '
                 f'270,{horizon-32} 370,{horizon-12} 490,{horizon-28} '
                 f'600,{horizon-16} 720,{horizon-24} 800,{horizon-10} 800,{horizon} " '
                 f'fill="{mtn}" opacity="0.30"/>')
    # White salt ground
    ground = f'<rect x="0" y="{horizon}" width="800" height="{533-horizon}" fill="#eef5f8"/>'
    # Sky-tinted reflection stripe near horizon
    refl = f'<rect x="0" y="{horizon}" width="800" height="35" fill="{sky_mid}" opacity="0.30"/>'
    # Shallow salt-crack lines
    cracks = "".join(
        f'<path d="M{(i*119+variant*43)%720+10},{horizon+25+(i*31+variant*17)%80} '
        f'l{20+(i*17)%25},{10+(i*11)%12} l{15+(i*9)%18},{-6+(i*7)%10}" '
        f'stroke="#b8ccd8" stroke-width="0.7" fill="none" opacity="0.55"/>'
        for i in range(8)
    )
    # Distant vehicle dot (gives sense of scale)
    vx = 380 + (variant * 47) % 80
    vehicle = f'<circle cx="{vx}" cy="{horizon+4}" r="3" fill="#a0b0c0" opacity="0.5"/>'
    return ground + refl + cracks + mtn_ridge + vehicle


def svg_scene_arch(t, variant):
    """Arches NP – freestanding sandstone arch against open sky."""
    s = t["silhouette"]
    g = t["ground"]
    d = hex_darken(s, 0.2)
    sh = variant * 16
    mesa = (f'<polygon points="0,298 {90+sh},248 {210+sh},260 {610-sh},253 '
            f'{710-sh},265 800,293 800,382 0,382" fill="{d}" opacity="0.55"/>')
    ground = f'<polygon points="0,382 800,362 800,533 0,533" fill="{g}"/>'
    lleg = (f'<polygon points="{268+sh},533 {294+sh},382 {336+sh},372 {346+sh},533" '
            f'fill="{s}"/>')
    rleg = (f'<polygon points="{454-sh},533 {464-sh},372 {506-sh},382 {532-sh},533" '
            f'fill="{s}"/>')
    keystone = (f'M{294+sh},382 Q{400},258 {464-sh},372 '
                f'Q{440},298 {400},288 Q{360},298 {336+sh},372 Z')
    return mesa + ground + lleg + rleg + f'<path d="{keystone}" fill="{s}"/>'


def svg_scene_wide_mesa(t, variant):
    """Canyonlands – panoramic red-rock mesa and canyon system."""
    s = t["silhouette"]
    g = t["ground"]
    d = hex_darken(s, 0.18)
    sh = variant * 11
    far  = (f'<polygon points="0,278 {140+sh},238 {300+sh},254 {460+sh},232 '
            f'{610-sh},248 {760-sh},236 800,253 800,312 0,312" '
            f'fill="{d}" opacity="0.45"/>')
    mid  = (f'<polygon points="0,312 {100+sh},278 {260+sh},290 {420+sh},268 '
            f'{570-sh},283 {720-sh},276 800,294 800,402 0,402" '
            f'fill="{s}" opacity="0.68"/>')
    fore = (f'<polygon points="0,402 0,533 800,533 800,392 {700-sh},381 '
            f'{580-sh},391 {440+sh},376 {290+sh},386 {140+sh},379 40,389" '
            f'fill="{g}"/>')
    slot = (f'<path d="M{385+sh},533 Q{396+sh},448 {406+sh},428 '
            f'Q{416+sh},448 {427+sh},533 Z" fill="{d}" opacity="0.65"/>')
    return far + mid + fore + slot


def svg_scene_buttes(t, variant):
    """Monument Valley – the iconic left and right Mitten buttes."""
    s = t["silhouette"]
    g = t["ground"]
    d = hex_darken(s, 0.22)
    sh = variant * 9
    lm = (f"{75+sh},533 {75+sh},308 {96+sh},298 {128+sh},308 "
          f"{128+sh},276 {158+sh},266 {190+sh},276 {200+sh},308 "
          f"{233+sh},313 {244+sh},533")
    rm = (f"{556-sh},533 {550-sh},313 {564-sh},308 {598-sh},276 "
          f"{633-sh},266 {663-sh},276 {672-sh},308 {704-sh},298 "
          f"{725-sh},308 {725-sh},533")
    sp = f"{368},533 {368},218 {389},197 {411},197 {432},218 {432},533"
    return (f'<polygon points="0,428 800,408 800,533 0,533" fill="{g}"/>'
            f'<polygon points="{lm}" fill="{s}"/>'
            f'<polygon points="{lm}" fill="{d}" opacity="0.22"/>'
            f'<polygon points="{rm}" fill="{s}"/>'
            f'<polygon points="{rm}" fill="{d}" opacity="0.22"/>'
            f'<polygon points="{sp}" fill="{s}"/>')


def svg_scene_layers(t, variant):
    """Grand Canyon – horizontal geological strata."""
    s = t["silhouette"]
    layer_colors = ["#922800", "#a83410", "#7e2000", "#6a1600", "#581008", "#460c05"]
    layers = ""
    for i, color in enumerate(layer_colors):
        y0 = 202 + i * 44 + (variant % 3) * 6
        y1 = y0 + 50
        wo = (i * 19 + variant * 13) % 22
        pts = (f"0,{y1} 0,{y0+wo} 200,{y0} 400,{y0+10} "
               f"600,{y0-6} 800,{y0+wo} 800,{y1}")
        layers += f'<polygon points="{pts}" fill="{color}" opacity="0.83"/>'
    rim = (f"0,202 0,533 800,533 800,196 700,186 600,191 "
           f"500,181 400,189 300,179 200,186 100,181")
    return layers + f'<polygon points="{rim}" fill="{s}"/>'


SCENE_FNS = {
    "city_night": svg_scene_city_night,
    "canyon":     svg_scene_canyon,
    "saltflats":  svg_scene_saltflats,
    "arch":       svg_scene_arch,
    "wide_mesa":  svg_scene_wide_mesa,
    "buttes":     svg_scene_buttes,
    "layers":     svg_scene_layers,
}


# ---------------------------------------------------------------------------
# SVG assembly
# ---------------------------------------------------------------------------

def make_svg(theme_key: str, label: str, photo_idx: int) -> str:
    t = THEMES[theme_key]
    w, h = 800, 533
    gid = f"g{theme_key}{photo_idx}"
    scene_svg = SCENE_FNS[t["scene"]](t, photo_idx)

    # Sun / moon accent circle
    sx = 650 - (photo_idx * 57) % 320
    sy = 72 + (photo_idx * 29) % 88
    sr = 24 + (photo_idx * 9) % 24
    sun = (f'<circle cx="{sx}" cy="{sy}" r="{sr}" fill="{t["accent"]}" opacity="0.48"/>'
           f'<circle cx="{sx}" cy="{sy}" r="{sr+16}" fill="{t["accent"]}" opacity="0.11"/>')

    label_esc = label.replace("&", "&amp;").replace("<", "&lt;")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">
  <defs>
    <linearGradient id="{gid}" x1="0%" y1="0%" x2="0%" y2="100%">
      <stop offset="0%" stop-color="{t['sky_top']}"/>
      <stop offset="66%" stop-color="{t['sky_mid']}"/>
    </linearGradient>
    <radialGradient id="vig{photo_idx}" cx="50%" cy="50%" r="70%">
      <stop offset="0%" stop-color="transparent"/>
      <stop offset="100%" stop-color="rgba(0,0,0,0.40)"/>
    </radialGradient>
  </defs>
  <rect width="{w}" height="{h}" fill="url(#{gid})"/>
  {sun}
  {scene_svg}
  <rect width="{w}" height="{h}" fill="url(#vig{photo_idx})"/>
  <text x="{w//2}" y="{h-22}" text-anchor="middle"
        font-family="Georgia,'Times New Roman',serif"
        font-size="17" letter-spacing="4"
        fill="{t['label_color']}" opacity="0.78">{label_esc}</text>
</svg>"""


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate():
    PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    # Remove old photos
    for f in PHOTOS_DIR.glob("*.svg"):
        f.unlink()

    stops_out  = []
    hero_photos = []

    for stop in STOPS:
        theme    = stop["theme"]
        captions = stop["photo_captions"]
        photos_out = []

        for i, caption in enumerate(captions):
            filename = f"{theme}_{i+1:02d}.svg"
            (PHOTOS_DIR / filename).write_text(
                make_svg(theme, stop["name"].upper(), i), encoding="utf-8"
            )
            photos_out.append({
                "id":        f"{stop['id']}_p{i+1:02d}",
                "filename":  filename,
                "url":       f"photos/{filename}",
                "timestamp": f"{stop['arrival'][:10]}T{12 + i*2:02d}:00:00",
                "caption":   caption,
            })

        rep_filename = photos_out[1]["filename"] if len(photos_out) > 1 else photos_out[0]["filename"]
        rep = f"photos/{rep_filename}"

        stops_out.append({
            "id":                   stop["id"],
            "name":                 stop["name"],
            "location":             stop["location"],
            "lat":                  stop["lat"],
            "lng":                  stop["lng"],
            "arrival":              stop["arrival"],
            "departure":            stop["departure"],
            "duration_hours":       stop["duration_hours"],
            "type":                 stop["type"],
            "order":                stop["order"],
            "representative_photo": rep,
            "photos":               photos_out,
        })

        if stop["type"] == "overnight" and len(hero_photos) < 3:
            hero_photos.append(rep)

    route = build_route()

    data = {
        "trip": {
            "title":       "Southwest Odyssey",
            "subtitle":    "Nevada · Utah · Arizona · 2025",
            "start_date":  "2025-05-14",
            "end_date":    "2025-05-21",
            "hero_photos": hero_photos,
        },
        "stops":     stops_out,
        "waypoints": WAYPOINTS,
        "route":     route,
    }

    out_path = OUTPUT_DIR / "data.json"
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    total_photos = sum(len(s["photos"]) for s in stops_out)
    overnight = sum(1 for s in stops_out if s["type"] == "overnight")
    day       = sum(1 for s in stops_out if s["type"] == "day")
    print(f"Generated {total_photos} SVG photos -> {PHOTOS_DIR}/")
    print(f"Generated {out_path}")
    print(f"  {len(stops_out)} stops: {overnight} overnight, {day} day")
    print(f"  {len(WAYPOINTS)} waypoints")
    print(f"  {len(route['geometry']['coordinates'])} route coordinates")


if __name__ == "__main__":
    generate()
