#!/usr/bin/env python3
"""
Google Takeout ingestion script for roadtrip-map.

Usage:
    python build.py --takeout /path/to/takeout/folder --output ./output

Supports merged exports from multiple Google accounts in a single folder.
Photos without GPS are attached to the nearest stop by time.
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
# Config helpers
# ---------------------------------------------------------------------------

def load_config(path="config.json"):
    defaults = {
        "overnight_threshold_hours": 4,
        "day_stop_threshold_minutes": 30,
        "cluster_radius_km": 2.5,
        "cluster_time_gap_hours": 3,
        "min_photos_per_stop": 1,
        "max_photos_displayed_per_stop": 12,
        "geocode_rate_limit_seconds": 1.1,
        "trip_name": "My Road Trip",
        "trip_subtitle": "",
    }
    if os.path.exists(path):
        with open(path) as f:
            defaults.update(json.load(f))
    return defaults


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".tif", ".tiff"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS


def find_sidecars_only(takeout_dir, url_map):
    """
    Drive mode: only JSON sidecars exist locally; images live at cloud URLs.
    Walk all .json files and include those whose derived media filename is in url_map.
    Returns list of dicts: {image_path: None, sidecar_path}
    """
    results = []
    root = Path(takeout_dir)
    url_keys = set(url_map.keys())
    for sidecar_path in root.rglob("*.json"):
        media_name = sidecar_path.stem   # "IMG_1234.jpg.json" → "IMG_1234.jpg"
        if media_name in url_keys:
            results.append({"image_path": None, "sidecar_path": sidecar_path})
    return results


def find_media_with_sidecars(takeout_dir):
    """
    Walk a (possibly merged) Takeout export folder and collect every media
    file that has a matching .json sidecar.

    Single-pass scan: walks all files once, then matches in memory.
    Handles sidecar naming variants:
        photo.jpg  →  photo.jpg.json
        photo.jpg  →  photo.jpg.supplemental-metadata.json
        photo.jpg  →  photo.json
        long_name… →  long_name….json  (truncated at 46 chars)

    Returns a list of dicts: {image_path, sidecar_path}
    """
    root = Path(takeout_dir)

    # Single pass: collect all files, split into media and json
    media_by_dir = {}   # dir -> {filename: path}
    json_by_dir = {}    # dir -> {filename: path}

    print("  Scanning files (single pass)...")
    file_count = 0
    for fpath in root.rglob("*"):
        if not fpath.is_file():
            continue
        file_count += 1
        if file_count % 500 == 0:
            print(f"    ...scanned {file_count} files")

        d = str(fpath.parent)
        name_lower = fpath.name.lower()

        if fpath.suffix.lower() in MEDIA_EXTS:
            media_by_dir.setdefault(d, {})[fpath.name] = fpath
        elif name_lower.endswith(".json"):
            json_by_dir.setdefault(d, {})[fpath.name] = fpath

    print(f"  Scan complete: {file_count} files")

    # Match in memory
    results = []
    for d, media_files in media_by_dir.items():
        jsons = json_by_dir.get(d, {})
        for media_name, media_path in media_files.items():
            stem = Path(media_name).stem  # IMG_0760

            # Try candidates in priority order
            candidates = [
                media_name + ".json",                              # IMG_0760.JPG.json
                media_name + ".supplemental-metadata.json",        # IMG_0760.JPG.supplemental-metadata.json
                stem + ".json",                                    # IMG_0760.json
                stem + ".supplemental-metadata.json",              # IMG_0760.supplemental-metadata.json
            ]

            sidecar = None
            for c in candidates:
                if c in jsons:
                    sidecar = jsons[c]
                    break

            # Prefix-match fallback for truncated names
            if sidecar is None:
                prefix = media_name[:45]
                for jname, jpath in jsons.items():
                    if jname.startswith(prefix):
                        sidecar = jpath
                        break

            if sidecar:
                results.append({"image_path": media_path, "sidecar_path": sidecar})

    return results


def find_media_in_album(album_dir):
    """
    Scan a single album folder (e.g., 'Google Photos/Album Name') for media + sidecars.
    Much faster than scanning entire Takeout since it's just one folder.

    Returns a list of dicts: {image_path, sidecar_path}
    """
    root = Path(album_dir)

    if not root.exists():
        raise FileNotFoundError(f"Album folder not found: {album_dir}")

    # Collect media and JSON files in this folder
    media_files = {}
    json_files = {}

    print(f"  Scanning album: {root.name}")
    for fpath in root.iterdir():
        if not fpath.is_file():
            continue

        name_lower = fpath.name.lower()
        if fpath.suffix.lower() in MEDIA_EXTS:
            media_files[fpath.name] = fpath
        elif name_lower.endswith(".json"):
            json_files[fpath.name] = fpath

    print(f"  Found {len(media_files)} media, {len(json_files)} sidecars")

    # Match in memory
    results = []
    for media_name, media_path in media_files.items():
        stem = Path(media_name).stem

        # Try candidates in priority order
        candidates = [
            media_name + ".json",
            media_name + ".supplemental-metadata.json",
            stem + ".json",
            stem + ".supplemental-metadata.json",
        ]

        sidecar = None
        for c in candidates:
            if c in json_files:
                sidecar = json_files[c]
                break

        if sidecar:
            results.append({"image_path": media_path, "sidecar_path": sidecar})

    return results


# ---------------------------------------------------------------------------
# Sidecar parsing
# ---------------------------------------------------------------------------

def parse_sidecar(sidecar_path):
    """
    Parse a Google Takeout JSON sidecar.
    Returns a dict or None if GPS is unavailable.
    """
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

    # Timestamp — prefer photoTakenTime
    ts_raw = (
        data.get("photoTakenTime") or
        data.get("creationTime") or {}
    ).get("timestamp", "0")

    try:
        ts = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
    except (ValueError, OSError):
        ts = None

    return {
        "filename": Path(sidecar_path).stem,   # e.g. "IMG_1234.jpg"
        "title": data.get("title", ""),
        "timestamp": ts,
        "lat": lat if has_gps else None,
        "lon": lon if has_gps else None,
        "has_gps": has_gps,
        "altitude": geo.get("altitude", 0.0),
        "description": data.get("description", ""),
    }


# ---------------------------------------------------------------------------
# Geometry helpers
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
# Deduplication (multi-account merges)
# ---------------------------------------------------------------------------

def deduplicate(photos):
    """
    Remove photos that share the same timestamp and GPS location (within 10m).
    Keeps the first occurrence encountered.
    """
    seen = set()
    unique = []
    for p in photos:
        if p["timestamp"] is None:
            unique.append(p)
            continue
        ts_key = int(p["timestamp"].timestamp() // 5)  # 5-second bucket
        lat_key = round(p["lat"] or 0, 4)
        lon_key = round(p["lon"] or 0, 4)
        key = (ts_key, lat_key, lon_key)
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def cluster_photos(photos_with_gps, config):
    """
    Sort by timestamp, then break into a new cluster whenever:
      - Time gap > cluster_time_gap_hours, OR
      - Distance from running cluster centroid > cluster_radius_km
    """
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


# ---------------------------------------------------------------------------
# Stop classification
# ---------------------------------------------------------------------------

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
# Reverse geocoding
# ---------------------------------------------------------------------------

_last_geocode_call = 0.0


def reverse_geocode(lat, lon, rate_limit=1.1):
    """Use Nominatim (OpenStreetMap) — free, no API key required."""
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
        # Build a short human-readable name
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
# Photo selection
# ---------------------------------------------------------------------------

def select_representative_photo(cluster):
    """Choose the most 'central' photo by GPS proximity to centroid."""
    clat, clon = centroid(cluster)
    if clat is None:
        return cluster[0]
    photos_with_gps = [p for p in cluster if p["lat"] is not None]
    if not photos_with_gps:
        return cluster[0]
    return min(photos_with_gps, key=lambda p: haversine_km(clat, clon, p["lat"], p["lon"]))


# ---------------------------------------------------------------------------
# Route building
# ---------------------------------------------------------------------------

def interpolate_segment(p1, p2, steps=12):
    """Linear interpolation between two [lon, lat] points."""
    coords = []
    for i in range(steps):
        t = i / steps
        coords.append([p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t])
    return coords


def build_route(stops):
    """Build a smoothed GeoJSON LineString through all stops in order."""
    ordered = sorted(stops, key=lambda s: s["arrival"])
    coords = []
    pts = [[s["lng"], s["lat"]] for s in ordered]
    for i in range(len(pts) - 1):
        coords.extend(interpolate_segment(pts[i], pts[i + 1], steps=20))
    coords.append(pts[-1])
    return {"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords}}


# ---------------------------------------------------------------------------
# Output builder
# ---------------------------------------------------------------------------

def build_output(clusters, all_photos, output_dir, config, image_map=None, url_map=None):
    """
    Construct the data.json structure.
    image_map: {filename: original_path}  — local mode, photos copied to output/photos/
    url_map:   {filename: cloud_url}      — Drive mode, photos served from URL directly
    """
    output_dir = Path(output_dir)
    photos_dir = output_dir / "photos"
    photos_dir.mkdir(parents=True, exist_ok=True)

    stops = []
    waypoints = []
    stop_order = 0
    total_photos_copied = 0

    for ci, cluster in enumerate(clusters):
        if (ci + 1) % 20 == 0:
            print(f"  Processing cluster {ci + 1}/{len(clusters)}...")
        stop_type = classify_stop(cluster, config)
        clat, clon = centroid(cluster)
        if clat is None:
            continue

        timestamps = [p["timestamp"] for p in cluster if p["timestamp"]]
        arrival = min(timestamps).isoformat() if timestamps else None
        departure = max(timestamps).isoformat() if timestamps else None
        duration_h = (max(timestamps) - min(timestamps)).total_seconds() / 3600 if len(timestamps) > 1 else 0

        rep = select_representative_photo(cluster)

        # Build photo list — only copy max_photos_downloaded_per_stop to output/
        # All photos included in data.json for reference, but only sample copied locally
        stop_photos = []
        photos_to_copy = cluster[:config.get("max_photos_downloaded_per_stop", 6)]

        for p in cluster[:config["max_photos_displayed_per_stop"]]:
            fname = p["filename"]
            should_copy = p in photos_to_copy  # Only copy selected photos

            if url_map and fname in url_map:
                # Drive mode: photo lives in the cloud
                stop_photos.append({
                    "id":        fname,
                    "filename":  fname,
                    "url":       url_map[fname],
                    "timestamp": p["timestamp"].isoformat() if p["timestamp"] else None,
                    "caption":   p["description"] or p["title"] or "",
                })
            elif image_map:
                # Local mode: only copy selected photos to output/photos/
                src = image_map.get(fname)
                if src:
                    if should_copy:
                        dest = photos_dir / src.name
                        shutil.copy2(src, dest)
                        total_photos_copied += 1
                        if total_photos_copied % 20 == 0:
                            print(f"    ...copied {total_photos_copied} photos")
                    stop_photos.append({
                        "id":        fname,
                        "filename":  src.name,
                        "url":       "photos/" + src.name,
                        "timestamp": p["timestamp"].isoformat() if p["timestamp"] else None,
                        "caption":   p["description"] or p["title"] or "",
                    })

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
        print(f"  Geocoding stop {stop_order}: {clat:.4f}, {clon:.4f} …")
        location_name = reverse_geocode(clat, clon, config["geocode_rate_limit_seconds"])

        if url_map:
            rep_url = url_map.get(rep["filename"], stop_photos[0]["url"] if stop_photos else "")
        else:
            rep_src = (image_map or {}).get(rep["filename"])
            rep_url = ("photos/" + rep_src.name) if rep_src else (stop_photos[0]["url"] if stop_photos else "")

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
            "representative_photo": rep_url,
            "photos": stop_photos,
        })

    route = build_route(stops)

    # Pick hero photos: rep photo from first 3 overnight stops
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

    out_path = output_dir / "data.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    return data


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ingest Google Takeout export into roadtrip-map data.")
    parser.add_argument("--takeout", default="/content/drive/My Drive/PicMap-V2 Project/Takeout",
                        help="Path to Takeout export folder (default: Colab Drive location)")
    parser.add_argument("--album", default=None,
                        help="Path to specific album folder (faster than full Takeout scan). "
                             "Example: /content/drive/My Drive/PicMap-V2 Project/Takeout/Google Photos/Album Name")
    parser.add_argument("--output", default="./output", help="Output folder (default: ./output)")
    parser.add_argument("--config", default="config.json", help="Config file (default: config.json)")
    parser.add_argument("--url-map", dest="url_map", default=None,
                        help="JSON file mapping {filename: cloud_url}. "
                             "When provided, photos are linked from the cloud instead of copied locally.")
    args = parser.parse_args()

    config = load_config(args.config)
    print(f"Config loaded. Thresholds: overnight>{config['overnight_threshold_hours']}h, "
          f"day>{config['day_stop_threshold_minutes']}min, "
          f"waypoint<{config['day_stop_threshold_minutes']}min")

    # Load URL map (Drive mode) if provided
    url_map = None
    image_map = {}
    if args.url_map:
        with open(args.url_map, encoding="utf-8") as f:
            url_map = json.load(f)
        print(f"Drive mode: loaded URL map with {len(url_map)} photo URLs")

    print(f"\nScanning media...")
    if args.album:
        # Album mode: scan specific folder only (fast)
        media_files = find_media_in_album(args.album)
    elif url_map:
        # Drive mode: only sidecars downloaded locally; images served from cloud
        media_files = find_sidecars_only(args.takeout, url_map)
        print(f"Found {len(media_files)} sidecar files matched to Drive URLs")
    else:
        # Full Takeout mode: recursive scan
        print(f"Takeout: {args.takeout}")
        media_files = find_media_with_sidecars(args.takeout)

    print(f"Found {len(media_files)} media files with sidecars")

    # Parse all sidecars (threaded for Drive I/O performance)
    print(f"\nParsing {len(media_files)} sidecars...")
    photos = []
    image_map = {} if not image_map else image_map

    def _parse_one(mf):
        return mf, parse_sidecar(mf["sidecar_path"])

    done = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = {pool.submit(_parse_one, mf): mf for mf in media_files}
        for future in as_completed(futures):
            done += 1
            if done % 500 == 0 or done == len(media_files):
                print(f"  ...parsed {done}/{len(media_files)} sidecars")
            mf, parsed = future.result()
            if parsed and parsed["timestamp"]:
                parsed["_image_path"] = mf["image_path"]
                photos.append(parsed)
                if mf["image_path"]:
                    image_map[parsed["filename"]] = mf["image_path"]

    print(f"Parsed {len(photos)} photos with timestamps")

    # Deduplicate (handles multi-account merged exports)
    photos = deduplicate(photos)
    print(f"After dedup: {len(photos)} unique photos")

    # Separate GPS vs no-GPS
    gps_photos = [p for p in photos if p["has_gps"]]
    no_gps_photos = [p for p in photos if not p["has_gps"]]
    print(f"GPS: {len(gps_photos)}, no-GPS: {len(no_gps_photos)}")

    # Cluster GPS photos
    clusters = cluster_photos(gps_photos, config)
    print(f"Clusters: {len(clusters)}")

    # Attach no-GPS photos to nearest cluster by time
    for p in no_gps_photos:
        if not p["timestamp"]:
            continue
        best_cluster = min(
            clusters,
            key=lambda c: min(
                abs((p["timestamp"] - q["timestamp"]).total_seconds())
                for q in c if q["timestamp"]
            ),
            default=None,
        )
        if best_cluster is not None:
            best_cluster.append(p)

    # Build output
    print(f"\nBuilding output in: {args.output}")
    data = build_output(clusters, photos, args.output, config,
                        image_map=image_map or None, url_map=url_map)

    n_stops = len(data["stops"])
    n_wps = len(data["waypoints"])
    print(f"\nDone. {n_stops} stops ({sum(1 for s in data['stops'] if s['type']=='overnight')} overnight, "
          f"{sum(1 for s in data['stops'] if s['type']=='day')} day), "
          f"{n_wps} waypoints.")
    print(f"Output: {Path(args.output) / 'data.json'}")


if __name__ == "__main__":
    main()
