#!/usr/bin/env python3
"""
Append the real driven road route for the final leg of the trip.

The GPS photo track ends near Mt Airy, NC (Surry County) on Aug 3, 2025;
the drive continued into the Research Triangle. This script fetches the
actual road geometry from the last GPS point through Durham to Raleigh and
appends it to output/data.json's route, replacing the synthetic dashed
straight line the print map used to draw for this stretch.

Routing uses the public OSRM demo server (router.project-osrm.org), which
follows OpenStreetMap roads — the same road data behind Google Maps'
shortest/fastest route — and needs no API token, unlike build_route.py's
Mapbox path. Waypoints: last GPS point -> Durham -> Raleigh.

Idempotent: if the route already reaches Raleigh, it does nothing.
Run once:  python build_final_leg.py
"""

import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
DATA_PATH = ROOT / "output" / "data.json"

# Downtown waypoints for the final leg (lon, lat), real-world sourced.
DURHAM = (-78.8986, 35.9940)
RALEIGH = (-78.6382, 35.7796)

OSRM_URL = "https://router.project-osrm.org/route/v1/driving"
SIMPLIFY_TOLERANCE = 0.0005   # ~50 m, matches build_route.py
JOIN_TOLERANCE_DEG = 0.05     # "already at Raleigh" guard (~5 km)


def simplify_route(coords, tolerance=SIMPLIFY_TOLERANCE):
    """Douglas-Peucker simplification for a list of [lon, lat] coords."""
    if len(coords) <= 2:
        return coords
    first, last = coords[0], coords[-1]
    max_dist, max_idx = 0, 0
    for i in range(1, len(coords) - 1):
        dx, dy = last[0] - first[0], last[1] - first[1]
        if dx == 0 and dy == 0:
            dist = math.hypot(coords[i][0] - first[0], coords[i][1] - first[1])
        else:
            dist = abs(dy * coords[i][0] - dx * coords[i][1]
                       + last[0] * first[1] - last[1] * first[0]) / math.hypot(dx, dy)
        if dist > max_dist:
            max_dist, max_idx = dist, i
    if max_dist > tolerance:
        left = simplify_route(coords[:max_idx + 1], tolerance)
        right = simplify_route(coords[max_idx:], tolerance)
        return left[:-1] + right
    return [first, last]


def fetch_osrm(waypoints):
    coords = ";".join(f"{lon},{lat}" for lon, lat in waypoints)
    url = f"{OSRM_URL}/{coords}?overview=full&geometries=geojson"
    with urllib.request.urlopen(url, timeout=60) as r:
        data = json.loads(r.read().decode())
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM returned {data.get('code')}: {data.get('message', '')}")
    route = data["routes"][0]
    return route["geometry"]["coordinates"], route["distance"] / 1609.344


def main():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    route = data["route"]["geometry"]["coordinates"]
    last = route[-1]

    if math.hypot(last[0] - RALEIGH[0], last[1] - RALEIGH[1]) < JOIN_TOLERANCE_DEG:
        print(f"Route already ends at Raleigh ({last}); nothing to do.")
        return

    print(f"Current route ends at {last} (Mt Airy area), {len(route)} points.")
    waypoints = [tuple(last), DURHAM, RALEIGH]
    coords, miles = fetch_osrm(waypoints)
    print(f"OSRM road route: {len(coords)} points, {miles:.1f} mi "
          f"(Mt Airy -> Durham -> Raleigh)")

    simplified = simplify_route(coords)
    simplified = [[round(c[0], 5), round(c[1], 5)] for c in simplified]
    print(f"Simplified: {len(coords)} -> {len(simplified)} points")

    # Append, skipping the first point (duplicates the current route end).
    data["route"]["geometry"]["coordinates"] = route + simplified[1:]

    # Record the leg + destination cities so the render and web app can
    # label them without re-deriving from geometry.
    data.setdefault("final_leg", {})
    data["final_leg"] = {
        "source": "OSRM (router.project-osrm.org), driving profile",
        "waypoints": [
            {"name": "Mt Airy", "lon": last[0], "lat": last[1], "note": "last GPS photo"},
            {"name": "Durham", "lon": DURHAM[0], "lat": DURHAM[1]},
            {"name": "Raleigh", "lon": RALEIGH[0], "lat": RALEIGH[1], "note": "destination"},
        ],
        "distance_miles": round(miles, 1),
    }

    DATA_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    total = len(data["route"]["geometry"]["coordinates"])
    print(f"Appended {len(simplified) - 1} points; route now {total} points, "
          f"ends at {data['route']['geometry']['coordinates'][-1]} (Raleigh).")


if __name__ == "__main__":
    main()
