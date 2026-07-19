#!/usr/bin/env python3
"""
Export derived data for the map layout editor (map_editor.html).

Writes assets/editor_context.json containing:
  - view_bbox: the exact projected-coordinate window build_print_map.py
    renders (so the editor and the poster agree on where things land)
  - page inches + dpi constants
  - states: US state outlines pre-decoded from TopoJSON to flat lon/lat
    rings (so the editor needs no JS TopoJSON decoder)

Re-run whenever the route in output/data.json changes (it affects the
view window) or the state boundary asset is updated.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import build_print_map as m

OUT_PATH = Path(__file__).parent / "assets" / "editor_context.json"


def main():
    data = json.loads(m.DATA_PATH.read_text(encoding="utf-8"))
    topo = json.loads(m.STATES_PATH.read_text(encoding="utf-8"))

    route = [(lon, lat) for lon, lat in data["route"]["geometry"]["coordinates"]]

    # Reproduce main()'s view-window fit exactly.
    proj_route = [m.project(lon, lat) for lon, lat in route]
    pr_x = [p[0] for p in proj_route] + [m.project(*m.RALEIGH)[0]]
    pr_y = [p[1] for p in proj_route] + [m.project(*m.RALEIGH)[1]]
    x0, x1 = min(pr_x), max(pr_x)
    y0, y1 = min(pr_y), max(pr_y)
    pad_x = (x1 - x0) * 0.055
    pad_y = (y1 - y0) * 0.10
    x0, x1, y0, y1 = x0 - pad_x, x1 + pad_x, y0 - pad_y, y1 + pad_y

    target = m.PAGE_W_IN / m.PAGE_H_IN
    w, h = x1 - x0, y1 - y0
    if w / h < target:
        extra = target * h - w
        x0 -= extra / 2
        x1 += extra / 2
    else:
        extra = w / target - h
        y0 -= extra * 0.62
        y1 += extra * 0.38

    states = m.decode_topojson(topo, "states")
    state_rings = [
        {"name": name, "rings": [[[round(lon, 4), round(lat, 4)] for lon, lat in ring]
                                 for ring in rings]}
        for name, rings in states
    ]

    ctx = {
        "view_bbox": [x0, x1, y0, y1],
        "page_w_in": m.PAGE_W_IN,
        "page_h_in": m.PAGE_H_IN,
        "projection": {"lat0": m.LAT0, "lon0": m.LON0,
                       "std1": m.STD1, "std2": m.STD2},
        "states": state_rings,
    }
    OUT_PATH.write_text(json.dumps(ctx, ensure_ascii=False), encoding="utf-8")
    kb = OUT_PATH.stat().st_size / 1024
    print(f"Wrote {OUT_PATH} ({kb:.0f} KB): view_bbox={[round(v, 4) for v in ctx['view_bbox']]}, "
          f"{len(state_rings)} state shapes")


if __name__ == "__main__":
    main()
