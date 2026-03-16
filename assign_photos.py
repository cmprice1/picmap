#!/usr/bin/env python3
"""
Assign ALL photos from trip_metadata.json to their nearest stop.
Outputs photo_assignments.json: { stop_id: [filename, ...], ... }

Uses GPS proximity + time overlap to match each photo to a stop.
Filters out videos, metadata files, and no-GPS photos without timestamps.
"""

import json
import math
from datetime import datetime
from pathlib import Path

SKIP_EXTENSIONS = {'.mov', '.mp4', '.avi', '.supplemental-metadata', ''}
SKIP_SUBSTRINGS = ['supplemental-metadata', 'supplemental-met', '.supple']


def is_image(filename):
    """Return True if filename looks like a real photo (not video/metadata)."""
    fn_lower = filename.lower()
    if any(sub in fn_lower for sub in SKIP_SUBSTRINGS):
        return False
    ext = Path(fn_lower).suffix
    if ext in SKIP_EXTENSIONS:
        return False
    if not ext:
        return False
    return True


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def parse_ts(s):
    try:
        return datetime.fromisoformat(s.replace('Z', '+00:00'))
    except Exception:
        return None


def main():
    meta_path = Path("output/trip_metadata.json")
    data_path = Path("output/data.json")
    out_path = Path("output/photo_assignments.json")

    with open(meta_path, encoding="utf-8") as f:
        meta = json.load(f)
    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    stops = data["stops"]
    # Parse stop times
    for s in stops:
        s["_arrival"] = parse_ts(s.get("arrival", ""))
        s["_departure"] = parse_ts(s.get("departure", ""))

    assignments = {s["id"]: [] for s in stops}
    assigned = 0
    skipped_type = 0
    skipped_no_match = 0

    for photo in meta["photos"]:
        fn = photo.get("filename", "")
        if not is_image(fn):
            skipped_type += 1
            continue

        lat = photo.get("lat")
        lon = photo.get("lon")
        ts = parse_ts(photo.get("timestamp", ""))

        best_stop = None
        best_score = float("inf")

        for s in stops:
            # GPS-based distance (if photo has GPS)
            if lat and lon and s["lat"] and s["lng"]:
                dist_km = haversine_km(lat, lon, s["lat"], s["lng"])
            else:
                dist_km = 999

            # Time-based scoring
            time_score = 999
            if ts and s["_arrival"] and s["_departure"]:
                if s["_arrival"] <= ts <= s["_departure"]:
                    time_score = 0  # within stop time range
                else:
                    # Hours away from nearest boundary
                    dt_arr = abs((ts - s["_arrival"]).total_seconds()) / 3600
                    dt_dep = abs((ts - s["_departure"]).total_seconds()) / 3600
                    time_score = min(dt_arr, dt_dep)

            # Combined score: prioritize GPS proximity, use time as tiebreaker
            if dist_km < 50:  # within 50km
                score = dist_km + time_score * 0.1
            elif time_score < 2:  # within 2 hours of stop
                score = dist_km * 0.1 + time_score
            else:
                score = dist_km + time_score

            if score < best_score:
                best_score = score
                best_stop = s["id"]

        # Only assign if reasonably close (< 100km or < 4 hours)
        if best_stop and best_score < 100:
            assignments[best_stop].append(fn)
            assigned += 1
        else:
            skipped_no_match += 1

    # Sort photos within each stop by filename (roughly chronological)
    for sid in assignments:
        assignments[sid].sort()

    # Remove empty stops
    assignments = {k: v for k, v in assignments.items() if v}

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(assignments, f, indent=2, ensure_ascii=False)

    total_photos = sum(len(v) for v in assignments.values())
    print(f"Assigned {total_photos} photos to {len(assignments)} stops")
    print(f"  Skipped: {skipped_type} non-image files, {skipped_no_match} no-match")

    # Show top stops by photo count
    by_count = sorted(assignments.items(), key=lambda x: -len(x[1]))
    stop_map = {s["id"]: s["name"] for s in stops}
    print(f"\nTop 10 stops by photo count:")
    for sid, photos in by_count[:10]:
        print(f"  {stop_map.get(sid, sid)}: {len(photos)} photos")


if __name__ == "__main__":
    main()
