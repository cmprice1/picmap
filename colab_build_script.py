#!/usr/bin/env python3
"""
colab_build_script.py — Roadtrip Map build pipeline for Google Colab.

Processes Google Takeout ZIPs from a Drive-mounted path and produces:
  - output/data.json     (stop metadata, GPS clusters, route)
  - output/photos/       (resized display photos)
  - output/photos.zip    (same photos, bundled for download)

Usage (in Colab after mounting Drive):
  python colab_build_script.py \\
    --takeout /content/drive/MyDrive/Takeout \\
    --output  /content/output \\
    --config  /content/roadtrip-map/config.json
"""

import argparse
import io
import json
import math
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIC_SUPPORT = True
    print("HEIC support enabled.")
except Exception:
    HEIC_SUPPORT = False
    print("pillow-heif not available — HEIC files will be skipped for display photos.")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp", ".gif", ".tif", ".tiff"}


# ─────────────────────────────────────────────────────────────────────────────
# Args + config
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Build roadtrip-map data from Takeout ZIPs.")
    p.add_argument("--takeout", required=True,
                   help="Path to folder containing Takeout .zip files (e.g. /content/drive/MyDrive/Takeout)")
    p.add_argument("--output", default="/content/output",
                   help="Output directory for data.json, photos/, and photos.zip")
    p.add_argument("--config", default="config.json",
                   help="Path to config.json (default: config.json)")
    return p.parse_args()


def load_config(path):
    defaults = {
        "overnight_threshold_hours":    4,
        "day_stop_threshold_minutes":   30,
        "cluster_radius_km":            2.5,
        "cluster_time_gap_hours":       3,
        "max_photos_displayed_per_stop": 12,
        "geocode_rate_limit_seconds":   1.1,
        "trip_name":     "Road Trip",
        "trip_subtitle": "2025",
    }
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        defaults.update(loaded)
        print(f"Config loaded from {path}")
    else:
        print(f"Config not found at {path}, using defaults.")
    return defaults


# ─────────────────────────────────────────────────────────────────────────────
# Helper functions
# ─────────────────────────────────────────────────────────────────────────────

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def centroid(photos):
    lats = [p["lat"] for p in photos if p.get("lat")]
    lons = [p["lon"] for p in photos if p.get("lon")]
    if not lats:
        return None, None
    return sum(lats) / len(lats), sum(lons) / len(lons)


def parse_sidecar(data, photo_name):
    geo = data.get("geoData") or {}
    lat, lon = geo.get("latitude", 0.0), geo.get("longitude", 0.0)
    if lat == 0.0 and lon == 0.0:
        geo = data.get("geoDataExif") or {}
        lat, lon = geo.get("latitude", 0.0), geo.get("longitude", 0.0)
    has_gps = not (lat == 0.0 and lon == 0.0)
    ts_raw = (data.get("photoTakenTime") or data.get("creationTime") or {}).get("timestamp", "0")
    try:
        ts = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
    except Exception:
        ts = None
    return {
        "filename":    photo_name,
        "timestamp":   ts,
        "lat":         lat if has_gps else None,
        "lon":         lon if has_gps else None,
        "has_gps":     has_gps,
        "description": data.get("description", ""),
        "title":       data.get("title", ""),
    }


def deduplicate(photos):
    seen, unique = set(), []
    for p in photos:
        if not p["timestamp"]:
            unique.append(p)
            continue
        key = (
            int(p["timestamp"].timestamp() // 5),
            round(p["lat"] or 0, 4),
            round(p["lon"] or 0, 4),
        )
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def cluster_photos(gps_photos, gap_hours, radius_km):
    if not gps_photos:
        return []
    photos = sorted(gps_photos, key=lambda p: p["timestamp"])
    clusters, current = [], [photos[0]]
    for photo in photos[1:]:
        prev = current[-1]
        gap_h = (
            (photo["timestamp"] - prev["timestamp"]).total_seconds() / 3600
            if prev["timestamp"] and photo["timestamp"] else 0
        )
        clat, clon = centroid(current)
        dist = (
            haversine_km(clat, clon, photo["lat"], photo["lon"])
            if clat and photo["lat"] else 0
        )
        if gap_h > gap_hours or dist > radius_km:
            clusters.append(current)
            current = [photo]
        else:
            current.append(photo)
    clusters.append(current)
    return clusters


def classify_stop(cluster, overnight_hours, day_minutes):
    ts = [p["timestamp"] for p in cluster if p["timestamp"]]
    if len(ts) < 2:
        return "waypoint"
    dur_h = (max(ts) - min(ts)).total_seconds() / 3600
    if dur_h >= overnight_hours:
        return "overnight"
    if dur_h >= day_minutes / 60:
        return "day"
    return "waypoint"


def select_representative(cluster):
    clat, clon = centroid(cluster)
    if not clat:
        return cluster[0]
    gps = [p for p in cluster if p["lat"]]
    return min(
        gps or cluster,
        key=lambda p: haversine_km(clat, clon, p["lat"] or 0, p["lon"] or 0),
    )


_last_geo = 0.0

def reverse_geocode(lat, lon, rate_limit):
    global _last_geo
    elapsed = time.time() - _last_geo
    if elapsed < rate_limit:
        time.sleep(rate_limit - elapsed)
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 10},
            headers={"User-Agent": "roadtrip-map/1.0 (personal project)"},
            timeout=10,
        )
        _last_geo = time.time()
        addr = r.json().get("address", {})
        parts = [
            addr.get("tourism") or addr.get("leisure") or addr.get("natural"),
            addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county"),
            addr.get("state"),
        ]
        return ", ".join(p for p in parts if p) or f"{lat:.4f}, {lon:.4f}"
    except Exception:
        _last_geo = time.time()
        return f"{lat:.4f}, {lon:.4f}"


def resize_image(img_bytes, max_dim, quality):
    try:
        img = Image.open(io.BytesIO(img_bytes))
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        if max(img.width, img.height) > max_dim:
            ratio = max_dim / max(img.width, img.height)
            img = img.resize(
                (int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS
            )
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception as e:
        print(f"    Warning: could not resize image: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline steps
# ─────────────────────────────────────────────────────────────────────────────

def find_takeout_path(configured):
    """Return the directory containing Takeout ZIPs, auto-detecting if needed."""
    if configured:
        p = Path(configured)
        if p.exists() and list(p.glob("*.zip")):
            return p
        if p.exists():
            print(f"Warning: {configured} exists but contains no .zip files.")
        else:
            print(f"Warning: {configured} not found.")

    print("Auto-scanning /content/drive/MyDrive for ZIP files (may take ~60s)...")
    result = subprocess.run(
        ["find", "/content/drive/MyDrive", "-name", "*.zip", "-maxdepth", "4"],
        capture_output=True, text=True, timeout=120,
    )
    found = [p for p in result.stdout.strip().split("\n") if p.strip()]
    if not found:
        raise FileNotFoundError(
            "No .zip files found in My Drive.\n"
            "Add a shortcut to the Takeout folder: right-click → Organize → Add shortcut → My Drive"
        )
    dirs = {}
    for f in found:
        d = str(Path(f).parent)
        dirs[d] = dirs.get(d, 0) + 1
    best = max(dirs, key=dirs.get)
    print(f"Auto-detected: {best}  ({dirs[best]} ZIP files)")
    print(f'Tip: pass --takeout "{best}" to skip this scan next time.')
    return Path(best)


def step1_index_zips(takeout_dir):
    """Read ZIP central directories (fast, no full download). Returns photo_index, sidecar_list."""
    zip_paths = sorted(takeout_dir.glob("*.zip"))
    if not zip_paths:
        raise FileNotFoundError(f"No ZIP files found in {takeout_dir}")

    print(f"\nStep 1 — Indexing {len(zip_paths)} ZIP file(s):")
    for z in zip_paths:
        print(f"  {z.name}  ({z.stat().st_size / 1e9:.1f} GB)")

    photo_index = {}   # filename → (zip_path, member_path)
    sidecar_list = []  # (zip_path, member_path, basename)

    for zip_path in zip_paths:
        print(f"  Indexing {zip_path.name} ...", end=" ", flush=True)
        n_photos = n_sidecars = 0
        with zipfile.ZipFile(zip_path) as zf:
            for info in zf.infolist():
                name     = info.filename
                basename = Path(name).name
                ext      = Path(basename).suffix.lower()
                stem     = Path(basename).stem
                stem_ext = Path(stem).suffix.lower()

                if ext in IMAGE_EXTS:
                    if basename not in photo_index:
                        photo_index[basename] = (zip_path, name)
                    n_photos += 1
                elif ext == ".json" and stem_ext in IMAGE_EXTS:
                    sidecar_list.append((zip_path, name, basename))
                    n_sidecars += 1

        print(f"{n_photos} photos, {n_sidecars} sidecars")

    print(f"\nTotal: {len(photo_index):,} photos indexed, {len(sidecar_list):,} sidecars")
    return photo_index, sidecar_list


def step2_extract_metadata(sidecar_list):
    """Parse GPS + timestamps from sidecar JSONs. Returns list of photo dicts."""
    print(f"\nStep 2 — Parsing {len(sidecar_list):,} sidecar files...")
    all_photos = []

    sidecars_by_zip = defaultdict(list)
    for zip_path, member, basename in sidecar_list:
        sidecars_by_zip[zip_path].append((member, basename))

    for zip_path, entries in sidecars_by_zip.items():
        with zipfile.ZipFile(zip_path) as zf:
            for member, basename in entries:
                photo_name = Path(basename).stem
                try:
                    data   = json.loads(zf.read(member))
                    parsed = parse_sidecar(data, photo_name)
                    if parsed and parsed["timestamp"]:
                        all_photos.append(parsed)
                except Exception:
                    pass

    print(f"Parsed {len(all_photos):,} photos with timestamps")
    all_photos = deduplicate(all_photos)
    print(f"After dedup: {len(all_photos):,} unique photos")

    gps_photos   = [p for p in all_photos if p["has_gps"]]
    nogps_photos = [p for p in all_photos if not p["has_gps"]]
    print(f"  GPS: {len(gps_photos):,}   no-GPS: {len(nogps_photos):,}")
    return gps_photos, nogps_photos


def step3_cluster_geocode(gps_photos, nogps_photos, cfg):
    """Cluster photos into stops and reverse-geocode each stop."""
    oh    = cfg["overnight_threshold_hours"]
    dm    = cfg["day_stop_threshold_minutes"]
    gap   = cfg["cluster_time_gap_hours"]
    rad   = cfg["cluster_radius_km"]
    rl    = cfg["geocode_rate_limit_seconds"]

    print(f"\nStep 3 — Clustering photos into stops...")
    clusters = cluster_photos(gps_photos, gap, rad)
    print(f"Found {len(clusters)} raw clusters")

    for p in nogps_photos:
        if not p["timestamp"] or not clusters:
            continue
        best = min(clusters, key=lambda c: min(
            abs((p["timestamp"] - q["timestamp"]).total_seconds())
            for q in c if q["timestamp"]
        ), default=None)
        if best is not None:
            best.append(p)

    stop_clusters     = [c for c in clusters if classify_stop(c, oh, dm) in ("overnight", "day")]
    waypoint_clusters = [c for c in clusters if classify_stop(c, oh, dm) == "waypoint"]
    overnight_n = sum(1 for c in stop_clusters if classify_stop(c, oh, dm) == "overnight")
    day_n       = len(stop_clusters) - overnight_n
    print(f"  {overnight_n} overnight, {day_n} day, {len(waypoint_clusters)} waypoints")

    if not stop_clusters:
        print("\nWARNING: No overnight or day stops found.")
        print("Possible causes:")
        print("  • Takeout folder has no photos with GPS data")
        print("  • cluster_time_gap_hours is too high — try lowering it in config.json")
        return [], waypoint_clusters

    print(f"\nReverse-geocoding {len(stop_clusters)} stops (~{len(stop_clusters)*1.2:.0f}s)...")
    geocoded = []
    for i, cluster in enumerate(stop_clusters):
        stop_type = classify_stop(cluster, oh, dm)
        clat, clon = centroid(cluster)
        if not clat:
            continue
        ts  = [p["timestamp"] for p in cluster if p["timestamp"]]
        loc = reverse_geocode(clat, clon, rl)
        geocoded.append({
            "_cluster":   cluster,
            "_type":      stop_type,
            "_lat":       clat,
            "_lon":       clon,
            "_arrival":   min(ts),
            "_departure": max(ts),
            "_duration_h": (max(ts) - min(ts)).total_seconds() / 3600 if len(ts) > 1 else 0,
            "_name":      loc.split(",")[0].strip(),
            "_location":  loc,
            "_rep":       select_representative(cluster),
        })
        print(f"  {i+1}/{len(stop_clusters)}: {loc.split(',')[0].strip()} ({stop_type})")

    print(f"\nGeocoded {len(geocoded)} stops.")
    return geocoded, waypoint_clusters


def step4_extract_photos(geocoded, photo_index, output_photos_dir, cfg):
    """Extract and resize display photos from ZIPs."""
    max_photos = cfg["max_photos_displayed_per_stop"]
    max_dim    = cfg.get("max_image_dim", 1200)
    quality    = cfg.get("jpeg_quality", 82)

    print(f"\nStep 4 — Extracting display photos (max {max_photos}/stop)...")
    os.makedirs(output_photos_dir, exist_ok=True)

    to_extract = {}
    for s in geocoded:
        for p in s["_cluster"][:max_photos]:
            fname = p["filename"]
            if fname in photo_index:
                out_name = Path(fname).stem + ".jpg"
                to_extract[fname] = os.path.join(output_photos_dir, out_name)

    print(f"Need {len(to_extract)} unique photos across all stops")

    by_zip = defaultdict(list)
    for fname, out_path in to_extract.items():
        zip_path, member = photo_index[fname]
        by_zip[zip_path].append((fname, member, out_path))

    total = len(to_extract)
    done = errors = 0

    for zip_path, entries in by_zip.items():
        print(f"  {zip_path.name}: {len(entries)} photos")
        with zipfile.ZipFile(zip_path) as zf:
            for fname, member, out_path in entries:
                if os.path.exists(out_path):
                    done += 1
                    continue
                ext = Path(fname).suffix.lower()
                if ext in (".heic", ".heif") and not HEIC_SUPPORT:
                    done += 1
                    continue
                try:
                    img_bytes = zf.read(member)
                    resized   = resize_image(img_bytes, max_dim, quality)
                    if resized:
                        with open(out_path, "wb") as f:
                            f.write(resized)
                except Exception as e:
                    print(f"    Error on {fname}: {e}")
                    errors += 1
                done += 1
                if done % 25 == 0:
                    print(f"    {done}/{total} processed...")

    saved = len([f for f in os.listdir(output_photos_dir) if f.endswith(".jpg")])
    total_mb = sum(
        os.path.getsize(os.path.join(output_photos_dir, f))
        for f in os.listdir(output_photos_dir)
    ) / 1e6
    print(f"Done: {saved} photos, {total_mb:.1f} MB, {errors} errors")


def step5_build_json(geocoded, waypoint_clusters, output_dir, cfg):
    """Write data.json."""

    def interpolate_segment(p1, p2, steps=20):
        return [
            [p1[0] + (p2[0] - p1[0]) * i / steps, p1[1] + (p2[1] - p1[1]) * i / steps]
            for i in range(steps)
        ]

    max_photos = cfg["max_photos_displayed_per_stop"]
    output_photos_dir = os.path.join(output_dir, "photos")
    stops_out   = []
    hero_photos = []
    stop_order  = 0

    for s in geocoded:
        stop_order += 1
        rep_name = s["_rep"]["filename"]
        rep_url  = f"photos/{Path(rep_name).stem}.jpg"

        photos_out = []
        for p in s["_cluster"][:max_photos]:
            out_name = Path(p["filename"]).stem + ".jpg"
            out_path = os.path.join(output_photos_dir, out_name)
            if not os.path.exists(out_path):
                continue
            photos_out.append({
                "id":        p["filename"],
                "filename":  out_name,
                "url":       f"photos/{out_name}",
                "timestamp": p["timestamp"].isoformat() if p["timestamp"] else None,
                "caption":   p["description"] or p["title"] or "",
            })

        stops_out.append({
            "id":                   f"stop_{stop_order:02d}",
            "name":                 s["_name"],
            "location":             s["_location"],
            "lat":                  round(s["_lat"], 6),
            "lng":                  round(s["_lon"], 6),
            "arrival":              s["_arrival"].isoformat(),
            "departure":            s["_departure"].isoformat(),
            "duration_hours":       round(s["_duration_h"], 1),
            "type":                 s["_type"],
            "order":                stop_order,
            "representative_photo": rep_url,
            "photos":               photos_out,
        })

        if s["_type"] == "overnight" and len(hero_photos) < 3:
            hero_photos.append(rep_url)

    pts    = [[s["lng"], s["lat"]] for s in stops_out]
    coords = []
    if len(pts) >= 2:
        for i in range(len(pts) - 1):
            coords.extend(interpolate_segment(pts[i], pts[i + 1]))
        coords.append(pts[-1])
    elif len(pts) == 1:
        coords = pts

    waypoints_out = []
    for i, cluster in enumerate(waypoint_clusters):
        clat, clon = centroid(cluster)
        if not clat:
            continue
        ts = [p["timestamp"] for p in cluster if p["timestamp"]]
        waypoints_out.append({
            "id":        f"wp_{i:02d}",
            "lat":       round(clat, 6),
            "lng":       round(clon, 6),
            "timestamp": min(ts).isoformat() if ts else None,
            "name":      "",
        })

    data = {
        "trip": {
            "title":       cfg["trip_name"],
            "subtitle":    cfg["trip_subtitle"],
            "start_date":  stops_out[0]["arrival"][:10]    if stops_out else "",
            "end_date":    stops_out[-1]["departure"][:10] if stops_out else "",
            "hero_photos": hero_photos,
        },
        "stops":     stops_out,
        "waypoints": waypoints_out,
        "route": {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
        },
    }

    data_json_path = os.path.join(output_dir, "data.json")
    with open(data_json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    overnight_n   = sum(1 for s in stops_out if s["type"] == "overnight")
    day_n         = sum(1 for s in stops_out if s["type"] == "day")
    total_display = sum(len(s["photos"]) for s in stops_out)
    print(f"\nStep 5 — data.json written to {data_json_path}")
    print(f"  {overnight_n} overnight + {day_n} day stops")
    print(f"  {total_display} display photos")
    print(f"  {len(waypoints_out)} waypoints, {len(coords)} route coordinates")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    args   = parse_args()
    cfg    = load_config(args.config)

    output_dir        = args.output
    output_photos_dir = os.path.join(output_dir, "photos")
    os.makedirs(output_photos_dir, exist_ok=True)

    takeout_dir = find_takeout_path(args.takeout)
    print(f"Takeout path: {takeout_dir}\n")

    photo_index, sidecar_list = step1_index_zips(takeout_dir)
    gps_photos, nogps_photos  = step2_extract_metadata(sidecar_list)
    geocoded, waypoint_clusters = step3_cluster_geocode(gps_photos, nogps_photos, cfg)

    if not geocoded:
        print("\nNo stops found — aborting. Check config.json clustering thresholds.")
        sys.exit(1)

    step4_extract_photos(geocoded, photo_index, output_photos_dir, cfg)
    step5_build_json(geocoded, waypoint_clusters, output_dir, cfg)

    # Bundle photos for download
    bundle_path = os.path.join(output_dir, "photos")
    zip_path    = os.path.join(output_dir, "photos.zip")
    print(f"\nBundling photos → {zip_path} ...")
    shutil.make_archive(os.path.join(output_dir, "photos"), "zip", output_photos_dir)
    bundle_mb = os.path.getsize(zip_path) / 1e6
    print(f"photos.zip: {bundle_mb:.1f} MB")

    print("\n=== Done ===")
    print(f"Download from Colab:")
    print(f"  {output_dir}/data.json")
    print(f"  {output_dir}/photos.zip")


if __name__ == "__main__":
    main()
