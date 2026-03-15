#!/usr/bin/env python3
"""
Phase 1: Extract metadata from Google Takeout sidecars.

This script runs in Colab and:
1. Copies just .json sidecars to local storage (fast, ~24MB)
2. Parses all sidecars for GPS + timestamps
3. Saves trip_metadata.json (all photo metadata)
4. Clusters with loose thresholds to identify stops
5. Selects 3 sample photos per stop (representative, first, last)
6. Fetches ONLY those sample photos from Drive
7. Outputs data.json ready for local iteration

Usage (in Colab):
    python extract_metadata.py \
        --album "/content/drive/My Drive/.../Album Name" \
        --output "./output" \
        --config "config_phase1.json"
"""

import argparse
import json
import math
import os
import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: 'requests' package not found. Run: pip install requests")
    raise

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path="config_phase1.json"):
    defaults = {
        "overnight_threshold_hours": 4,
        "day_stop_threshold_minutes": 15,  # Loose: count shorter stops
        "cluster_radius_km": 1.5,          # Loose: smaller radius = more stops
        "cluster_time_gap_hours": 1.5,     # Loose: shorter gap = more stops
        "samples_per_stop": 3,             # Representative, first, last
        "geocode_rate_limit_seconds": 1.1,
        "trip_name": "Road Trip",
        "trip_subtitle": "",
    }
    if os.path.exists(path):
        with open(path) as f:
            defaults.update(json.load(f))
    return defaults

# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def copy_sidecars_to_local(album_dir, local_dir):
    """
    Copy just .json sidecar files from Drive album to local storage.
    Much faster than copying all media files.
    """
    album_path = Path(album_dir)
    local_path = Path(local_dir)
    local_path.mkdir(parents=True, exist_ok=True)

    print(f"Copying sidecars from: {album_path.name}")

    # List all files in album (one Drive operation)
    all_files = list(album_path.iterdir())
    json_files = [f for f in all_files if f.suffix.lower() == ".json"]

    print(f"  Found {len(json_files)} sidecar files")

    # Copy sidecars to local
    copied = 0
    for jf in json_files:
        dest = local_path / jf.name
        shutil.copy2(jf, dest)
        copied += 1
        if copied % 100 == 0:
            print(f"  ...copied {copied}/{len(json_files)} sidecars")

    print(f"  Copied {copied} sidecars to local storage")

    # Also save a manifest of all media files (for later photo fetching)
    media_files = [f.name for f in all_files if f.suffix.lower() in MEDIA_EXTS]
    manifest_path = local_path / "_media_manifest.json"
    with open(manifest_path, "w") as f:
        json.dump({"album_path": str(album_path), "media_files": media_files}, f)

    print(f"  Saved manifest with {len(media_files)} media files")

    return local_path, json_files


def parse_sidecar(sidecar_path):
    """Parse a Google Takeout JSON sidecar for GPS + timestamp."""
    with open(sidecar_path, encoding="utf-8") as f:
        data = json.load(f)

    # Prefer geoData; fall back to geoDataExif
    geo = data.get("geoData") or {}
    lat = geo.get("latitude", 0.0)
    lon = geo.get("longitude", 0.0)

    if lat == 0.0 and lon == 0.0:
        geo = data.get("geoDataExif") or {}
        lat = geo.get("latitude", 0.0)
        lon = geo.get("longitude", 0.0)

    has_gps = not (lat == 0.0 and lon == 0.0)

    # Timestamp
    ts_raw = (
        data.get("photoTakenTime") or
        data.get("creationTime") or {}
    ).get("timestamp", "0")

    try:
        ts = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
    except (ValueError, OSError):
        ts = None

    # Derive media filename from sidecar name
    sidecar_name = Path(sidecar_path).name
    if sidecar_name.endswith(".supplemental-metadata.json"):
        media_filename = sidecar_name.replace(".supplemental-metadata.json", "")
    elif sidecar_name.endswith(".json"):
        media_filename = sidecar_name[:-5]  # Remove .json
    else:
        media_filename = sidecar_name

    return {
        "filename": media_filename,
        "sidecar": sidecar_name,
        "timestamp": ts,
        "lat": lat if has_gps else None,
        "lon": lon if has_gps else None,
        "has_gps": has_gps,
        "title": data.get("title", ""),
        "description": data.get("description", ""),
    }


def parse_all_sidecars(local_sidecar_dir):
    """Parse all sidecars in local directory (fast, no Drive I/O)."""
    sidecar_dir = Path(local_sidecar_dir)
    sidecars = list(sidecar_dir.glob("*.json"))
    sidecars = [s for s in sidecars if not s.name.startswith("_")]  # Skip manifest

    print(f"\nParsing {len(sidecars)} sidecars (local)...")

    photos = []
    for i, sc in enumerate(sidecars):
        if (i + 1) % 500 == 0:
            print(f"  ...parsed {i + 1}/{len(sidecars)}")
        parsed = parse_sidecar(sc)
        if parsed and parsed["timestamp"]:
            photos.append(parsed)

    print(f"  Parsed {len(photos)} photos with timestamps")
    return photos


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
        if prev["timestamp"] and photo["timestamp"]:
            gap_h = (photo["timestamp"] - prev["timestamp"]).total_seconds() / 3600
        else:
            gap_h = 0

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


# ---------------------------------------------------------------------------
# Sample selection
# ---------------------------------------------------------------------------

def select_sample_photos(cluster, num_samples=3):
    """
    Select representative sample photos from a cluster.
    Returns: [representative (center), first (earliest), last (latest)]
    """
    if not cluster:
        return []

    # Sort by timestamp
    sorted_photos = sorted(cluster, key=lambda p: p["timestamp"] or datetime.min.replace(tzinfo=timezone.utc))

    samples = []

    # 1. Representative: closest to centroid
    clat, clon = centroid(cluster)
    if clat is not None:
        gps_photos = [p for p in cluster if p["lat"] is not None]
        if gps_photos:
            rep = min(gps_photos, key=lambda p: haversine_km(clat, clon, p["lat"], p["lon"]))
            samples.append(rep)

    # 2. First: earliest timestamp
    if sorted_photos and sorted_photos[0] not in samples:
        samples.append(sorted_photos[0])

    # 3. Last: latest timestamp
    if len(sorted_photos) > 1 and sorted_photos[-1] not in samples:
        samples.append(sorted_photos[-1])

    # Fill remaining slots if needed
    for p in sorted_photos:
        if len(samples) >= num_samples:
            break
        if p not in samples:
            samples.append(p)

    return samples[:num_samples]


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------

_last_geocode_call = 0.0

def reverse_geocode(lat, lon, rate_limit=1.1):
    """Use Nominatim (OpenStreetMap) for geocoding."""
    global _last_geocode_call
    elapsed = time.time() - _last_geocode_call
    if elapsed < rate_limit:
        time.sleep(rate_limit - elapsed)

    url = "https://nominatim.openstreetmap.org/reverse"
    params = {"lat": lat, "lon": lon, "format": "json", "zoom": 10}
    headers = {"User-Agent": "roadtrip-map/1.0 (personal project)"}

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        _last_geocode_call = time.time()
        data = resp.json()
        addr = data.get("address", {})
        parts = [
            addr.get("tourism") or addr.get("leisure") or addr.get("natural"),
            addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county"),
            addr.get("state"),
        ]
        name = ", ".join(p for p in parts if p)
        return name or data.get("display_name", f"{lat:.4f}, {lon:.4f}")
    except Exception as e:
        print(f"  Geocode error: {e}")
        _last_geocode_call = time.time()
        return f"{lat:.4f}, {lon:.4f}"


# ---------------------------------------------------------------------------
# Photo fetching
# ---------------------------------------------------------------------------

def fetch_sample_photos(sample_filenames, album_dir, output_dir):
    """
    Fetch only the sample photos from Drive to local output.
    Returns dict of {filename: local_path}
    """
    album_path = Path(album_dir)
    photos_dir = Path(output_dir) / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nFetching {len(sample_filenames)} sample photos from Drive...")

    fetched = {}
    for i, filename in enumerate(sample_filenames):
        src = album_path / filename
        if src.exists():
            dest = photos_dir / filename
            shutil.copy2(src, dest)
            fetched[filename] = str(dest)
            if (i + 1) % 10 == 0:
                print(f"  ...fetched {i + 1}/{len(sample_filenames)}")
        else:
            print(f"  Warning: {filename} not found in album")

    print(f"  Fetched {len(fetched)} photos")
    return fetched


# ---------------------------------------------------------------------------
# Output building
# ---------------------------------------------------------------------------

def build_output(clusters, all_photos, output_dir, config, album_dir):
    """Build data.json with sample photos per stop."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    stops = []
    waypoints = []
    all_samples = []
    stop_order = 0

    print(f"\nProcessing {len(clusters)} clusters...")

    for cluster in clusters:
        stop_type = classify_stop(cluster, config)
        clat, clon = centroid(cluster)
        if clat is None:
            continue

        timestamps = [p["timestamp"] for p in cluster if p["timestamp"]]
        arrival = min(timestamps).isoformat() if timestamps else None
        departure = max(timestamps).isoformat() if timestamps else None
        duration_h = (max(timestamps) - min(timestamps)).total_seconds() / 3600 if len(timestamps) > 1 else 0

        # Select sample photos
        samples = select_sample_photos(cluster, config.get("samples_per_stop", 3))
        all_samples.extend(samples)

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
        print(f"  Geocoding stop {stop_order}: {clat:.4f}, {clon:.4f}...")
        location_name = reverse_geocode(clat, clon, config["geocode_rate_limit_seconds"])

        # Build photo list (just references for now)
        stop_photos = []
        for p in samples:
            stop_photos.append({
                "id": p["filename"],
                "filename": p["filename"],
                "url": "photos/" + p["filename"],
                "timestamp": p["timestamp"].isoformat() if p["timestamp"] else None,
                "caption": p["description"] or p["title"] or "",
            })

        stops.append({
            "id": f"stop_{stop_order:02d}",
            "name": location_name.split(",")[0].strip(),
            "location": location_name,
            "lat": clat,
            "lng": clon,
            "arrival": arrival,
            "departure": departure,
            "duration_hours": round(duration_h, 1),
            "type": stop_type,
            "order": stop_order,
            "photo_count": len(cluster),  # Total photos at this stop
            "representative_photo": stop_photos[0]["url"] if stop_photos else "",
            "photos": stop_photos,
        })

    # Fetch sample photos from Drive
    sample_filenames = list(set(p["filename"] for p in all_samples))
    fetch_sample_photos(sample_filenames, album_dir, output_dir)

    # Build route
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

    # Save full metadata for Phase 2 iteration
    metadata = {
        "photos": [
            {
                "filename": p["filename"],
                "timestamp": p["timestamp"].isoformat() if p["timestamp"] else None,
                "lat": p["lat"],
                "lon": p["lon"],
                "has_gps": p["has_gps"],
            }
            for p in all_photos
        ],
        "config": config,
        "generated": datetime.now(timezone.utc).isoformat(),
    }
    metadata_path = output_dir / "trip_metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    print(f"\nSaved {len(metadata['photos'])} photo metadata to trip_metadata.json")

    return data


def build_route(stops):
    """Build a GeoJSON LineString through all stops."""
    ordered = sorted(stops, key=lambda s: s["arrival"])
    coords = []
    pts = [[s["lng"], s["lat"]] for s in ordered]

    for i in range(len(pts) - 1):
        # Interpolate between stops
        p1, p2 = pts[i], pts[i + 1]
        for j in range(20):
            t = j / 20
            coords.append([p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t])

    if pts:
        coords.append(pts[-1])

    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Phase 1: Extract metadata and sample photos from Takeout.")
    parser.add_argument("--album", required=True, help="Path to album folder in Drive")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--config", default="config_phase1.json", help="Config file")
    parser.add_argument("--local-cache", default="/content/local_sidecars", help="Local cache for sidecars")
    args = parser.parse_args()

    config = load_config(args.config)
    print(f"Config: cluster_radius={config['cluster_radius_km']}km, "
          f"time_gap={config['cluster_time_gap_hours']}h, "
          f"samples_per_stop={config.get('samples_per_stop', 3)}")

    # Step 1: Copy sidecars to local (fast)
    local_sidecar_dir, _ = copy_sidecars_to_local(args.album, args.local_cache)

    # Step 2: Parse all sidecars locally (very fast)
    photos = parse_all_sidecars(local_sidecar_dir)

    # Step 3: Separate GPS vs no-GPS
    gps_photos = [p for p in photos if p["has_gps"]]
    no_gps_photos = [p for p in photos if not p["has_gps"]]
    print(f"\nGPS: {len(gps_photos)}, no-GPS: {len(no_gps_photos)}")

    # Step 4: Cluster
    clusters = cluster_photos(gps_photos, config)
    print(f"Clusters: {len(clusters)}")

    # Step 5: Attach no-GPS photos to nearest cluster
    for p in no_gps_photos:
        if not p["timestamp"] or not clusters:
            continue
        best = min(
            clusters,
            key=lambda c: min(
                abs((p["timestamp"] - q["timestamp"]).total_seconds())
                for q in c if q["timestamp"]
            ),
        )
        best.append(p)

    # Step 6: Build output (includes sample photo fetching)
    data = build_output(clusters, photos, args.output, config, args.album)

    n_stops = len(data["stops"])
    n_samples = sum(len(s["photos"]) for s in data["stops"])
    print(f"\nDone! {n_stops} stops, {n_samples} sample photos")
    print(f"Output: {args.output}/data.json")
    print(f"Metadata: {args.output}/trip_metadata.json")


if __name__ == "__main__":
    main()
