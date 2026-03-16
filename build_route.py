#!/usr/bin/env python3
"""
Build a road-following route from trip GPS data using Mapbox Directions API.

Reads trip_metadata.json, samples waypoints along the chronological path,
calls Mapbox Directions API to get actual road geometry, and updates data.json.
"""

import json
import math
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

sys.setrecursionlimit(10000)

MAPBOX_TOKEN = "YOUR_MAPBOX_API_KEY"  # Get from mapbox.com → Account → Tokens
DIRECTIONS_URL = "https://api.mapbox.com/directions/v5/mapbox/driving"

# Minimum distance (km) between sampled waypoints
MIN_SAMPLE_DISTANCE_KM = 8
# Max waypoints per Mapbox request (API limit is 25)
BATCH_SIZE = 25


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def load_gps_points(metadata_path):
    """Load GPS photos, sort by timestamp, filter bad dates."""
    with open(metadata_path, encoding="utf-8") as f:
        data = json.load(f)

    gps = [p for p in data["photos"] if p["has_gps"] and p["lat"] and p["lon"]]
    # Filter out bad timestamps (before trip start)
    gps = [p for p in gps if p["timestamp"] and p["timestamp"] >= "2025-06-28"]
    gps.sort(key=lambda p: p["timestamp"])

    print(f"Loaded {len(gps)} GPS photos (Jun 28 - Aug 3, 2025)")
    return gps


def sample_waypoints(gps_points, min_dist_km):
    """Sample waypoints along the route, keeping one every min_dist_km."""
    if not gps_points:
        return []

    waypoints = [(gps_points[0]["lat"], gps_points[0]["lon"])]

    for p in gps_points[1:]:
        lat, lon = p["lat"], p["lon"]
        last_lat, last_lon = waypoints[-1]
        dist = haversine_km(last_lat, last_lon, lat, lon)

        if dist >= min_dist_km:
            waypoints.append((lat, lon))

    # Always include the last point
    last = gps_points[-1]
    if waypoints[-1] != (last["lat"], last["lon"]):
        waypoints.append((last["lat"], last["lon"]))

    print(f"Sampled {len(waypoints)} waypoints (min {min_dist_km}km apart)")
    return waypoints


def fetch_route_segment(waypoints, token):
    """Call Mapbox Directions API for a batch of waypoints. Returns GeoJSON coordinates."""
    coords_str = ";".join(f"{lon},{lat}" for lat, lon in waypoints)
    url = (
        f"{DIRECTIONS_URL}/{coords_str}"
        f"?geometries=geojson&overview=full&access_token={token}"
    )

    req = urllib.request.Request(url)
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    if data.get("code") != "Ok":
        print(f"  WARNING: API returned {data.get('code')}: {data.get('message', '')}")
        return None

    route = data["routes"][0]
    coords = route["geometry"]["coordinates"]
    dist_km = route["distance"] / 1000
    dur_hr = route["duration"] / 3600
    return {"coordinates": coords, "distance_km": dist_km, "duration_hr": dur_hr}


def build_full_route(waypoints, token):
    """Build the full route by batching waypoints through the Directions API."""
    all_coords = []
    total_dist = 0
    total_dur = 0

    # Split into overlapping batches (share last/first point for continuity)
    n_batches = math.ceil((len(waypoints) - 1) / (BATCH_SIZE - 1))
    print(f"Routing through {len(waypoints)} waypoints in {n_batches} batches...")

    for i in range(n_batches):
        start = i * (BATCH_SIZE - 1)
        end = min(start + BATCH_SIZE, len(waypoints))
        batch = waypoints[start:end]

        print(f"  Batch {i + 1}/{n_batches}: {len(batch)} waypoints "
              f"({batch[0][0]:.2f},{batch[0][1]:.2f} -> {batch[-1][0]:.2f},{batch[-1][1]:.2f})")

        result = fetch_route_segment(batch, token)
        if result is None:
            print(f"  FAILED — falling back to straight line for this segment")
            for lat, lon in batch:
                all_coords.append([lon, lat])
            continue

        # Append coordinates (skip first point of subsequent batches to avoid dupes)
        if all_coords:
            all_coords.extend(result["coordinates"][1:])
        else:
            all_coords.extend(result["coordinates"])

        total_dist += result["distance_km"]
        total_dur += result["duration_hr"]

        print(f"    -> {len(result['coordinates'])} road points, "
              f"{result['distance_km']:.0f}km, {result['duration_hr']:.1f}hr")

        # Rate limit: be kind to the API
        if i < n_batches - 1:
            time.sleep(0.5)

    print(f"\nTotal route: {len(all_coords)} coordinates, "
          f"{total_dist:.0f}km, {total_dur:.1f}hr driving")
    return all_coords


def simplify_route(coords, tolerance=0.0005):
    """Douglas-Peucker simplification for a list of [lon, lat] coords."""
    if len(coords) <= 2:
        return coords

    # Find the point farthest from the line between first and last
    first, last = coords[0], coords[-1]
    max_dist = 0
    max_idx = 0

    for i in range(1, len(coords) - 1):
        # Perpendicular distance from point to line (first -> last)
        dx = last[0] - first[0]
        dy = last[1] - first[1]
        if dx == 0 and dy == 0:
            dist = math.sqrt((coords[i][0] - first[0]) ** 2 + (coords[i][1] - first[1]) ** 2)
        else:
            dist = abs(dy * coords[i][0] - dx * coords[i][1] + last[0] * first[1] - last[1] * first[0]) / math.sqrt(dx * dx + dy * dy)
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    if max_dist > tolerance:
        left = simplify_route(coords[:max_idx + 1], tolerance)
        right = simplify_route(coords[max_idx:], tolerance)
        return left[:-1] + right
    else:
        return [first, last]


def main():
    output_dir = Path("output")
    metadata_path = output_dir / "trip_metadata.json"
    data_path = output_dir / "data.json"

    if not metadata_path.exists():
        print(f"ERROR: {metadata_path} not found")
        sys.exit(1)
    if not data_path.exists():
        print(f"ERROR: {data_path} not found")
        sys.exit(1)

    # Load and sample
    gps_points = load_gps_points(metadata_path)
    waypoints = sample_waypoints(gps_points, MIN_SAMPLE_DISTANCE_KM)

    # Build road route
    coords = build_full_route(waypoints, MAPBOX_TOKEN)

    # Simplify to reduce file size (tolerance ~50m in degrees)
    simplified = simplify_route(coords, tolerance=0.0005)
    print(f"Simplified: {len(coords)} -> {len(simplified)} coordinates "
          f"({100 * len(simplified) / len(coords):.1f}%)")

    # Round coordinates to 5 decimal places (~1m precision)
    simplified = [[round(c[0], 5), round(c[1], 5)] for c in simplified]

    # Update data.json
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    data["route"] = {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": simplified,
        },
    }

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\nUpdated {data_path} with road-following route ({len(simplified)} points)")


if __name__ == "__main__":
    main()
