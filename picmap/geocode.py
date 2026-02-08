"""Reverse geocoding with local caching for PicMap."""

import argparse
import csv
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional, Tuple

from PIL import Image
import piexif
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim

PhotoRecord = Dict[str, Optional[str]]

PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}


def normalize_coordinates(lat: float, lon: float, precision: int = 5) -> Tuple[float, float]:
    """Normalize coordinates to a fixed precision for caching."""
    return (round(lat, precision), round(lon, precision))


def source_signature(path: str) -> str:
    """Build a lightweight signature so we can skip unchanged photos."""
    stat = os.stat(path)
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def init_db(conn: sqlite3.Connection) -> None:
    """Create the cache tables if they do not exist."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS geocode_cache (
            normalized_lat REAL NOT NULL,
            normalized_lon REAL NOT NULL,
            location TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (normalized_lat, normalized_lon)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS photos (
            path TEXT PRIMARY KEY,
            signature TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            normalized_lat REAL,
            normalized_lon REAL,
            location TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_photos_signature
        ON photos(signature)
        """
    )
    conn.commit()


def get_decimal_coordinates(gps_info: Dict) -> Optional[Tuple[float, float]]:
    """Convert GPS coordinates from degrees/minutes/seconds to decimal format."""
    try:
        lat = gps_info.get(piexif.GPSIFD.GPSLatitude)
        lat_ref = gps_info.get(piexif.GPSIFD.GPSLatitudeRef, b'N')
        lon = gps_info.get(piexif.GPSIFD.GPSLongitude)
        lon_ref = gps_info.get(piexif.GPSIFD.GPSLongitudeRef, b'E')

        if not lat or not lon:
            return None

        lat_decimal = lat[0][0] / lat[0][1] + lat[1][0] / (lat[1][1] * 60) + lat[2][0] / (lat[2][1] * 3600)
        lon_decimal = lon[0][0] / lon[0][1] + lon[1][0] / (lon[1][1] * 60) + lon[2][0] / (lon[2][1] * 3600)

        if lat_ref == b'S':
            lat_decimal = -lat_decimal
        if lon_ref == b'W':
            lon_decimal = -lon_decimal

        return (lat_decimal, lon_decimal)
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def extract_photo_coordinates(photo_path: str) -> Optional[Tuple[float, float]]:
    """Extract GPS coordinates from a photo's EXIF metadata."""
    img = Image.open(photo_path)
    exif_dict = piexif.load(img.info.get('exif', b''))
    gps_info = exif_dict.get("GPS", {})
    return get_decimal_coordinates(gps_info)


def iter_photo_paths(directory: str) -> Iterable[str]:
    """Yield supported photo paths from a directory tree."""
    for root, _, files in os.walk(directory):
        for file in files:
            if Path(file).suffix.lower() in PHOTO_EXTENSIONS:
                yield os.path.join(root, file)


def format_location(address: Dict) -> Optional[str]:
    """Format a reverse geocoded address into a human-friendly location name."""
    if not address:
        return None

    primary = (
        address.get('attraction')
        or address.get('tourism')
        or address.get('amenity')
        or address.get('leisure')
        or address.get('natural')
        or address.get('shop')
        or address.get('road')
        or address.get('neighbourhood')
        or address.get('suburb')
        or address.get('village')
        or address.get('town')
        or address.get('city')
        or address.get('county')
        or address.get('state')
        or address.get('country')
    )

    secondary = (
        address.get('city')
        or address.get('town')
        or address.get('village')
        or address.get('state')
        or address.get('country')
    )

    if primary and secondary and primary != secondary:
        return f"{primary}, {secondary}"
    return primary or secondary


def build_geocode_client() -> Callable[[float, float], Optional[str]]:
    """Create a Nominatim reverse geocoder."""
    geolocator = Nominatim(user_agent="picmap")
    reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1)

    def reverse_geocode(lat: float, lon: float) -> Optional[str]:
        try:
            location = reverse((lat, lon), zoom=10, language='en')
        except Exception:
            return None
        if location and hasattr(location, 'raw'):
            return format_location(location.raw.get('address', {}))
        return None

    return reverse_geocode


def lookup_cache(
    conn: sqlite3.Connection,
    normalized_lat: float,
    normalized_lon: float,
) -> Tuple[bool, Optional[str]]:
    """Return cached location and whether the cache entry exists."""
    row = conn.execute(
        """
        SELECT location
        FROM geocode_cache
        WHERE normalized_lat = ? AND normalized_lon = ?
        """,
        (normalized_lat, normalized_lon),
    ).fetchone()
    if row is None:
        return False, None
    return True, row[0]


def upsert_cache(
    conn: sqlite3.Connection,
    normalized_lat: float,
    normalized_lon: float,
    location: Optional[str],
) -> None:
    """Insert or update the geocode cache."""
    conn.execute(
        """
        INSERT INTO geocode_cache (normalized_lat, normalized_lon, location, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(normalized_lat, normalized_lon)
        DO UPDATE SET location = excluded.location, updated_at = excluded.updated_at
        """,
        (normalized_lat, normalized_lon, location, datetime.utcnow().isoformat()),
    )


def resolve_location(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    geocode_func: Callable[[float, float], Optional[str]],
    precision: int = 5,
) -> Tuple[Optional[str], Tuple[float, float], bool]:
    """Resolve a location name with caching."""
    normalized_lat, normalized_lon = normalize_coordinates(lat, lon, precision)
    cache_hit, location = lookup_cache(conn, normalized_lat, normalized_lon)
    if cache_hit:
        return location, (normalized_lat, normalized_lon), True

    try:
        location = geocode_func(lat, lon)
    except Exception:
        location = None
    upsert_cache(conn, normalized_lat, normalized_lon, location)
    return location, (normalized_lat, normalized_lon), False


def get_photo_record(conn: sqlite3.Connection, path: str) -> Optional[sqlite3.Row]:
    """Fetch an existing photo record by path."""
    return conn.execute(
        """
        SELECT path, signature, latitude, longitude, normalized_lat, normalized_lon, location
        FROM photos
        WHERE path = ?
        """,
        (path,),
    ).fetchone()


def upsert_photo_record(
    conn: sqlite3.Connection,
    path: str,
    signature: str,
    latitude: Optional[float],
    longitude: Optional[float],
    normalized_lat: Optional[float],
    normalized_lon: Optional[float],
    location: Optional[str],
) -> None:
    """Insert or update a processed photo record."""
    conn.execute(
        """
        INSERT INTO photos (
            path, signature, latitude, longitude, normalized_lat, normalized_lon, location, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            signature = excluded.signature,
            latitude = excluded.latitude,
            longitude = excluded.longitude,
            normalized_lat = excluded.normalized_lat,
            normalized_lon = excluded.normalized_lon,
            location = excluded.location,
            updated_at = excluded.updated_at
        """,
        (
            path,
            signature,
            latitude,
            longitude,
            normalized_lat,
            normalized_lon,
            location,
            datetime.utcnow().isoformat(),
        ),
    )


def process_photo(
    conn: sqlite3.Connection,
    path: str,
    geocode_func: Callable[[float, float], Optional[str]],
    precision: int,
) -> Optional[Dict[str, Optional[str]]]:
    """Process a single photo, returning a record suitable for CSV output."""
    signature = source_signature(path)
    existing = get_photo_record(conn, path)
    if existing and existing[1] == signature:
        return {
            "path": existing[0],
            "latitude": existing[2],
            "longitude": existing[3],
            "normalized_lat": existing[4],
            "normalized_lon": existing[5],
            "location": existing[6],
        }

    coordinates = extract_photo_coordinates(path)
    if not coordinates:
        upsert_photo_record(conn, path, signature, None, None, None, None, None)
        return None

    lat, lon = coordinates
    location, (normalized_lat, normalized_lon), _ = resolve_location(
        conn, lat, lon, geocode_func, precision
    )

    upsert_photo_record(
        conn,
        path,
        signature,
        lat,
        lon,
        normalized_lat,
        normalized_lon,
        location,
    )

    return {
        "path": path,
        "latitude": lat,
        "longitude": lon,
        "normalized_lat": normalized_lat,
        "normalized_lon": normalized_lon,
        "location": location,
    }


def process_photos(
    input_dir: str,
    db_path: str,
    out_csv: str,
    geocode_func: Optional[Callable[[float, float], Optional[str]]] = None,
    precision: int = 5,
) -> None:
    """Process photos and write a CSV of reverse geocoded locations."""
    if geocode_func is None:
        geocode_func = build_geocode_client()

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_db(conn)

    records = []
    for path in sorted(iter_photo_paths(input_dir)):
        record = process_photo(conn, path, geocode_func, precision)
        if record and record.get("latitude") is not None:
            records.append(record)

    with open(out_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=[
                'path',
                'latitude',
                'longitude',
                'normalized_lat',
                'normalized_lon',
                'location',
            ],
        )
        writer.writeheader()
        writer.writerows(records)

    conn.commit()
    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reverse geocode photo coordinates with caching",
    )
    parser.add_argument(
        '--input',
        required=True,
        help='Directory containing photos to process',
    )
    parser.add_argument(
        '--db',
        required=True,
        help='SQLite cache database path',
    )
    parser.add_argument(
        '--out',
        required=True,
        help='Output CSV path',
    )
    parser.add_argument(
        '--precision',
        type=int,
        default=5,
        help='Decimal precision for coordinate normalization (default: 5)',
    )

    args = parser.parse_args()

    if not os.path.isdir(args.input):
        raise SystemExit(f"Input directory not found: {args.input}")

    process_photos(args.input, args.db, args.out, precision=args.precision)


if __name__ == '__main__':
    main()
