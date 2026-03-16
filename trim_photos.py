#!/usr/bin/env python3
"""
Trim data.json photo arrays to keep only 3 per overnight, 1 per day stop.
Also cleans out 'metadata' pseudo-entries and fixes photo URLs.
Run this AFTER extracting curated_photos.zip into output/photos/.
"""

import json
from pathlib import Path


def resolve_photo(filename, photos_dir):
    """Find a photo file, handling HEIC->jpg conversion and filtering non-images."""
    # Skip metadata pseudo-entries and supplemental-metadata files
    if not filename or filename == "metadata" or "supplemental-metadata" in filename:
        return None
    # Skip video files
    if filename.lower().endswith((".mov", ".mp4", ".avi")):
        return None
    # Always prefer .jpg version (converted from HEIC for browser compatibility)
    if filename.upper().endswith(".HEIC"):
        jpg_name = Path(filename).stem + ".jpg"
        if (photos_dir / jpg_name).exists():
            return jpg_name
    # Check original filename
    if (photos_dir / filename).exists():
        return filename
    return None


def main():
    data_path = Path("output/data.json")
    photos_dir = Path("output/photos")

    with open(data_path, encoding="utf-8") as f:
        data = json.load(f)

    total_kept = 0
    total_available = 0

    for stop in data["stops"]:
        raw = stop.get("photos", [])

        # Resolve each photo: filter bad entries, map HEIC->jpg, check existence
        resolved = []
        for p in raw:
            fn = resolve_photo(p.get("filename", ""), photos_dir)
            if fn:
                resolved.append({**p, "filename": fn})

        # Keep 3 for overnight, 1 for day
        n = 3 if stop["type"] == "overnight" else 1
        kept = resolved[:n]

        # Set URLs for kept photos
        for p in kept:
            p["url"] = f"photos/{p['filename']}"

        stop["photos"] = kept
        if kept:
            stop["representative_photo"] = kept[0]["url"]
        else:
            stop["representative_photo"] = ""

        total_kept += len(kept)
        total_available += len(kept)

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    overnight = sum(1 for s in data["stops"] if s["type"] == "overnight")
    day = sum(1 for s in data["stops"] if s["type"] == "day")
    print(f"Trimmed to {total_available} photos ({total_kept} selected, {total_available} found locally)")
    print(f"Stops: {len(data['stops'])} ({overnight} overnight x3, {day} day x1)")
    print(f"Updated {data_path}")


if __name__ == "__main__":
    main()
