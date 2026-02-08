"""Incremental photo processing with SQLite caching."""

import argparse
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Tuple

from PIL import Image
import piexif
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.heic', '.heif'}


def init_db(conn: sqlite3.Connection) -> None:
    """Create cache tables if they do not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS photos (
            photo_id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            mtime INTEGER NOT NULL,
            size INTEGER NOT NULL,
            content_hash TEXT NULL,
            lat REAL NULL,
            lon REAL NULL,
            converted_path TEXT NULL,
            stage_converted INTEGER NOT NULL DEFAULT 0,
            stage_gps_extracted INTEGER NOT NULL DEFAULT 0,
            stage_geocoded INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache (
            lat_rounded REAL NOT NULL,
            lon_rounded REAL NOT NULL,
            provider TEXT NOT NULL,
            response_json TEXT NOT NULL,
            city TEXT NULL,
            state TEXT NULL,
            country TEXT NULL,
            display_name TEXT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_geocode_cache_unique
        ON geocode_cache (lat_rounded, lon_rounded, provider)
        """
    )
    conn.commit()


def iter_photo_paths(directory: str) -> Iterable[str]:
    """Yield supported photo paths from a directory tree."""
    for root, _, files in os.walk(directory):
        for file in files:
            if Path(file).suffix.lower() in PHOTO_EXTENSIONS:
                yield os.path.join(root, file)


def get_decimal_coordinates(gps_info: Dict) -> Optional[Tuple[float, float]]:
    """Convert GPS coordinates from degrees/minutes/seconds to decimal format."""
    try:
        lat = gps_info.get(piexif.GPSIFD.GPSLatitude)
        lat_ref = gps_info.get(piexif.GPSIFD.GPSLatitudeRef, b'N')
        lon = gps_info.get(piexif.GPSIFD.GPSLongitude)
        lon_ref = gps_info.get(piexif.GPSIFD.GPSLongitudeRef, b'E')

        if not lat or not lon:
            return None

        lat_decimal = (
            lat[0][0] / lat[0][1]
            + lat[1][0] / (lat[1][1] * 60)
            + lat[2][0] / (lat[2][1] * 3600)
        )
        lon_decimal = (
            lon[0][0] / lon[0][1]
            + lon[1][0] / (lon[1][1] * 60)
            + lon[2][0] / (lon[2][1] * 3600)
        )

        if lat_ref == b'S':
            lat_decimal = -lat_decimal
        if lon_ref == b'W':
            lon_decimal = -lon_decimal

        return (lat_decimal, lon_decimal)
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def extract_photo_coordinates(photo_path: str) -> Optional[Tuple[float, float]]:
    """Extract GPS coordinates from a photo's EXIF metadata."""
    try:
        img = Image.open(photo_path)
        exif_dict = piexif.load(img.info.get('exif', b''))
    except (OSError, ValueError, piexif.InvalidImageDataError):
        return None
    gps_info = exif_dict.get("GPS", {})
    return get_decimal_coordinates(gps_info)


def round_coordinates(lat: float, lon: float, precision: int = 3) -> Tuple[float, float]:
    """Round coordinates for cache lookups."""
    return (round(lat, precision), round(lon, precision))


def build_geocoder() -> Callable[[float, float], Optional[Dict[str, Optional[str]]]]:
    """Build a Nominatim reverse geocoder with rate limiting."""
    geolocator = Nominatim(user_agent="picmap")
    reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1)

    def reverse_geocode(lat: float, lon: float) -> Optional[Dict[str, Optional[str]]]:
        try:
            location = reverse((lat, lon), zoom=10, language='en')
        except Exception:
            return None
        if not location or not hasattr(location, 'raw'):
            return None

        raw = location.raw
        address = raw.get('address', {}) if isinstance(raw, dict) else {}
        return {
            "response_json": json.dumps(raw),
            "city": address.get('city') or address.get('town') or address.get('village'),
            "state": address.get('state'),
            "country": address.get('country'),
            "display_name": raw.get('display_name') if isinstance(raw, dict) else None,
        }

    return reverse_geocode


def fetch_photo(conn: sqlite3.Connection, path: str) -> Optional[sqlite3.Row]:
    """Fetch a photo row by path."""
    return conn.execute(
        """
        SELECT photo_id, path, mtime, size, lat, lon, stage_gps_extracted, stage_geocoded
        FROM photos
        WHERE path = ?
        """,
        (path,),
    ).fetchone()


def insert_photo(conn: sqlite3.Connection, path: str, mtime: int, size: int) -> None:
    """Insert a new photo record."""
    conn.execute(
        """
        INSERT INTO photos (path, mtime, size)
        VALUES (?, ?, ?)
        """,
        (path, mtime, size),
    )


def reset_photo_processing(conn: sqlite3.Connection, path: str, mtime: int, size: int) -> None:
    """Reset processing stages for a changed photo."""
    conn.execute(
        """
        UPDATE photos
        SET mtime = ?,
            size = ?,
            lat = NULL,
            lon = NULL,
            converted_path = NULL,
            stage_converted = 0,
            stage_gps_extracted = 0,
            stage_geocoded = 0
        WHERE path = ?
        """,
        (mtime, size, path),
    )


def mark_gps_extracted(
    conn: sqlite3.Connection,
    path: str,
    lat: Optional[float],
    lon: Optional[float],
    stage_geocoded: int,
) -> None:
    """Store GPS extraction results."""
    conn.execute(
        """
        UPDATE photos
        SET lat = ?,
            lon = ?,
            stage_gps_extracted = 1,
            stage_geocoded = ?
        WHERE path = ?
        """,
        (lat, lon, stage_geocoded, path),
    )


def mark_geocoded(conn: sqlite3.Connection, path: str) -> None:
    """Mark a photo as geocoded."""
    conn.execute(
        """
        UPDATE photos
        SET stage_geocoded = 1
        WHERE path = ?
        """,
        (path,),
    )


def lookup_geocode_cache(
    conn: sqlite3.Connection,
    lat_rounded: float,
    lon_rounded: float,
    provider: str,
) -> Optional[sqlite3.Row]:
    """Look up a cached geocode response."""
    return conn.execute(
        """
        SELECT response_json, city, state, country, display_name
        FROM geocode_cache
        WHERE lat_rounded = ? AND lon_rounded = ? AND provider = ?
        """,
        (lat_rounded, lon_rounded, provider),
    ).fetchone()


def upsert_geocode_cache(
    conn: sqlite3.Connection,
    lat_rounded: float,
    lon_rounded: float,
    provider: str,
    response: Optional[Dict[str, Optional[str]]],
) -> None:
    """Insert or update a geocode cache entry."""
    if response is None:
        response = {
            "response_json": "{}",
            "city": None,
            "state": None,
            "country": None,
            "display_name": None,
        }
    conn.execute(
        """
        INSERT INTO geocode_cache (
            lat_rounded,
            lon_rounded,
            provider,
            response_json,
            city,
            state,
            country,
            display_name,
            fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(lat_rounded, lon_rounded, provider)
        DO UPDATE SET
            response_json = excluded.response_json,
            city = excluded.city,
            state = excluded.state,
            country = excluded.country,
            display_name = excluded.display_name,
            fetched_at = excluded.fetched_at
        """,
        (
            lat_rounded,
            lon_rounded,
            provider,
            response.get("response_json", "{}"),
            response.get("city"),
            response.get("state"),
            response.get("country"),
            response.get("display_name"),
            datetime.utcnow().isoformat(),
        ),
    )


def process_photos(
    input_dir: str,
    db_path: str,
    geocode_func: Optional[Callable[[float, float], Optional[Dict[str, Optional[str]]]]] = None,
    extract_coords_func: Optional[Callable[[str], Optional[Tuple[float, float]]]] = None,
    provider: str = "nominatim",
) -> Dict[str, int]:
    """Process photos incrementally and cache geocoding results."""
    if geocode_func is None:
        geocode_func = build_geocoder()
    if extract_coords_func is None:
        extract_coords_func = extract_photo_coordinates

    cache_hits = 0
    cache_misses = 0

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    for path in sorted(iter_photo_paths(input_dir)):
        stat = os.stat(path)
        mtime = int(stat.st_mtime)
        size = stat.st_size

        row = fetch_photo(conn, path)
        if row is None:
            insert_photo(conn, path, mtime, size)
            row = fetch_photo(conn, path)
        elif row['mtime'] != mtime or row['size'] != size:
            reset_photo_processing(conn, path, mtime, size)
            row = fetch_photo(conn, path)

        if row is None:
            continue

        if row['stage_gps_extracted'] == 0:
            coords = extract_coords_func(path)
            if coords is None:
                mark_gps_extracted(conn, path, None, None, 1)
                row = fetch_photo(conn, path)
            else:
                lat, lon = coords
                mark_gps_extracted(conn, path, lat, lon, 0)
                row = fetch_photo(conn, path)

        if row is None:
            continue

        lat = row['lat']
        lon = row['lon']
        if lat is None or lon is None:
            continue

        lat_rounded, lon_rounded = round_coordinates(lat, lon, 3)
        cached = lookup_geocode_cache(conn, lat_rounded, lon_rounded, provider)

        if row['stage_geocoded'] == 1:
            if cached is not None:
                cache_hits += 1
            continue

        if cached is not None:
            cache_hits += 1
            mark_geocoded(conn, path)
            continue

        cache_misses += 1
        response = geocode_func(lat, lon)
        upsert_geocode_cache(conn, lat_rounded, lon_rounded, provider, response)
        mark_geocoded(conn, path)

    conn.commit()
    conn.close()

    return {"cache_hits": cache_hits, "cache_misses": cache_misses}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Incrementally process photos and cache reverse geocoding.",
    )
    parser.add_argument(
        '--input',
        required=True,
        help='Directory containing photos to process',
    )
    parser.add_argument(
        '--db',
        default='picmap_cache.sqlite',
        help='SQLite cache database path (default: picmap_cache.sqlite)',
    )

    args = parser.parse_args()

    if not os.path.isdir(args.input):
        raise SystemExit(f"Input directory not found: {args.input}")

    stats = process_photos(args.input, args.db)
    print(
        "Geocode cache hits: {hits}, misses: {misses}".format(
            hits=stats["cache_hits"],
            misses=stats["cache_misses"],
        )
    )


if __name__ == '__main__':
    main()
