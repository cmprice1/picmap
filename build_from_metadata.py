#!/usr/bin/env python3
"""
Phase 2: Build data.json from cached metadata (runs locally, no Drive needed).

This script takes the trip_metadata.json generated in Phase 1 and:
1. Loads all photo GPS/timestamp data
2. Applies clustering with your chosen thresholds
3. Generates data.json for the frontend
4. Uses existing sample photos (fetched in Phase 1)

Usage (local):
    python build_from_metadata.py --config config.json

Iterate on clustering:
    # Edit config.json thresholds, then re-run
    python build_from_metadata.py --config config.json
"""

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path="config.json"):
    defaults = {
        "overnight_threshold_hours": 4,
        "day_stop_threshold_minutes": 30,
        "cluster_radius_km": 2.5,
        "cluster_time_gap_hours": 3,
        "max_photos_per_stop": 12,
        "trip_name": "Road Trip",
        "trip_subtitle": "",
    }
    if os.path.exists(path):
        with open(path) as f:
            defaults.update(json.load(f))
    return defaults

# ---------------------------------------------------------------------------
# Geometry
# ---------------------------------------------------------------------------

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def centroid(photos):
    lats = [p["lat"] for p in photos if p["lat"] is not None]
    lons = [p["lon"] for p in photos if p["lon"] is not None]
    if not lats:
        return None, None
    return sum(lats) / len(lats), sum(lons) / len(lons)

# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def cluster_photos(photos_with_gps, config):
    """Cluster photos by time gap and distance."""
    if not photos_with_gps:
        return []

    photos = sorted(photos_with_gps, key=lambda p: p["timestamp"])
    clusters = []
    current = [photos[0]]

    for photo in photos[1:]:
        prev = current[-1]
        gap_h = (photo["timestamp"] - prev["timestamp"]).total_seconds() / 3600

        clat, clon = centroid(current)
        if clat is not None and photo["lat"] is not None:
            dist = haversine_km(clat, clon, photo["lat"], photo["lon"])
        else:
            dist = 0

        if gap_h > config["cluster_time_gap_hours"] or dist > config["cluster_radius_km"]:
            clusters.append(current)
            current = [photo]
        else:
            current.append(photo)

    clusters.append(current)
    return clusters


def classify_stop(cluster, config):
    """Return 'overnight', 'day', or 'waypoint'."""
    timestamps = [p["timestamp"] for p in cluster if p["timestamp"]]
    if len(timestamps) < 2:
        return "waypoint"
    duration_h = (max(timestamps) - min(timestamps)).total_seconds() / 3600
    if duration_h >= config["overnight_threshold_hours"]:
        return "overnight"
    if duration_h >= config["day_stop_threshold_minutes"] / 60:
        return "day"
    return "waypoint"


def select_representative(cluster):
    """Choose photo closest to cluster centroid."""
    clat, clon = centroid(cluster)
    if clat is None:
        return cluster[0]
    gps_photos = [p for p in cluster if p["lat"] is not None]
    if not gps_photos:
        return cluster[0]
    return min(gps_photos, key=lambda p: haversine_km(clat, clon, p["lat"], p["lon"]))

# ---------------------------------------------------------------------------
# Output building
# ---------------------------------------------------------------------------

def build_route(stops):
    """Build a GeoJSON LineString through all stops."""
    ordered = sorted(stops, key=lambda s: s["arrival"])
    coords = []
    pts = [[s["lng"], s["lat"]] for s in ordered]

    for i in range(len(pts) - 1):
        p1, p2 = pts[i], pts[i + 1]
        for j in range(20):
            t = j / 20
            coords.append([p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t])

    if pts:
        coords.append(pts[-1])

    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}}


def check_photo_exists(filename, photos_dir):
    """Check if a sample photo exists locally."""
    photo_path = photos_dir / filename
    return photo_path.exists()


def build_output(clusters, all_photos, output_dir, config):
    """Build data.json from clusters, using existing sample photos."""
    output_dir = Path(output_dir)
    photos_dir = output_dir / "photos"

    # Get list of available sample photos
    available_photos = set()
    if photos_dir.exists():
        available_photos = {f.name for f in photos_dir.iterdir() if f.is_file()}

    stops = []
    waypoints = []
    stop_order = 0

    print(f"\nProcessing {len(clusters)} clusters...")
    print(f"Available sample photos: {len(available_photos)}")

    for cluster in clusters:
        stop_type = classify_stop(cluster, config)
        clat, clon = centroid(cluster)
        if clat is None:
            continue

        timestamps = [p["timestamp"] for p in cluster if p["timestamp"]]
        arrival = min(timestamps).isoformat() if timestamps else None
        departure = max(timestamps).isoformat() if timestamps else None
        duration_h = (max(timestamps) - min(timestamps)).total_seconds() / 3600 if len(timestamps) > 1 else 0

        if stop_type == "waypoint":
            waypoints.append({
                "id": f"wp_{len(waypoints):02d}",
                "lat": clat,
                "lng": clon,
                "timestamp": arrival,
                "name": "",
            })
            continue

        stop_order += 1

        # Find photos that have samples available
        stop_photos = []
        for p in cluster[:config.get("max_photos_per_stop", 12)]:
            if p["filename"] in available_photos:
                stop_photos.append({
                    "id": p["filename"],
                    "filename": p["filename"],
                    "url": "photos/" + p["filename"],
                    "timestamp": p["timestamp"].isoformat() if p["timestamp"] else None,
                    "caption": "",
                })

        # Generate location name from coordinates (simple version)
        location_name = f"Stop {stop_order} ({clat:.2f}, {clon:.2f})"

        stops.append({
            "id": f"stop_{stop_order:02d}",
            "name": f"Stop {stop_order}",
            "location": location_name,
            "lat": clat,
            "lng": clon,
            "arrival": arrival,
            "departure": departure,
            "duration_hours": round(duration_h, 1),
            "type": stop_type,
            "order": stop_order,
            "photo_count": len(cluster),
            "representative_photo": stop_photos[0]["url"] if stop_photos else "",
            "photos": stop_photos,
        })

    route = build_route(stops)

    # Hero photos
    hero_stops = [s for s in stops if s["type"] == "overnight"][:3]
    hero_photos = [s["representative_photo"] for s in hero_stops if s["representative_photo"]]

    data = {
        "trip": {
            "title": config["trip_name"],
            "subtitle": config["trip_subtitle"],
            "start_date": stops[0]["arrival"][:10] if stops else "",
            "end_date": stops[-1]["departure"][:10] if stops else "",
            "hero_photos": hero_photos,
        },
        "stops": stops,
        "waypoints": waypoints,
        "route": route,
    }

    # Save data.json
    data_path = output_dir / "data.json"
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return data

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Phase 2: Build data.json from cached metadata.")
    parser.add_argument("--metadata", default="./output/trip_metadata.json", help="Path to trip_metadata.json")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--config", default="config.json", help="Config file with clustering thresholds")
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)
    print(f"Config: cluster_radius={config['cluster_radius_km']}km, "
          f"time_gap={config['cluster_time_gap_hours']}h")

    # Load metadata
    print(f"\nLoading metadata from {args.metadata}...")
    with open(args.metadata) as f:
        metadata = json.load(f)

    # Convert to photo objects with datetime
    photos = []
    for p in metadata["photos"]:
        if p["timestamp"]:
            photos.append({
                "filename": p["filename"],
                "timestamp": datetime.fromisoformat(p["timestamp"]),
                "lat": p["lat"],
                "lon": p["lon"],
                "has_gps": p["has_gps"],
            })

    print(f"Loaded {len(photos)} photos with timestamps")

    # Separate GPS vs no-GPS
    gps_photos = [p for p in photos if p["has_gps"]]
    no_gps_photos = [p for p in photos if not p["has_gps"]]
    print(f"GPS: {len(gps_photos)}, no-GPS: {len(no_gps_photos)}")

    # Cluster
    clusters = cluster_photos(gps_photos, config)
    print(f"Clusters: {len(clusters)}")

    # Attach no-GPS photos
    for p in no_gps_photos:
        if not clusters:
            continue
        best = min(
            clusters,
            key=lambda c: min(
                abs((p["timestamp"] - q["timestamp"]).total_seconds())
                for q in c if q["timestamp"]
            ),
        )
        best.append(p)

    # Build output
    data = build_output(clusters, photos, args.output, config)

    n_stops = len(data["stops"])
    n_waypoints = len(data["waypoints"])
    overnight = sum(1 for s in data["stops"] if s["type"] == "overnight")
    day = sum(1 for s in data["stops"] if s["type"] == "day")

    print(f"\nDone!")
    print(f"  {n_stops} stops ({overnight} overnight, {day} day)")
    print(f"  {n_waypoints} waypoints")
    print(f"  Output: {args.output}/data.json")


if __name__ == "__main__":
    main()
