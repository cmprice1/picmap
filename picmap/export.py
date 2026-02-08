"""Export cached photo locations to CSV."""

import argparse
import csv
import sqlite3
from typing import Iterable, Tuple

from .process import round_coordinates


def iter_photos(conn: sqlite3.Connection) -> Iterable[sqlite3.Row]:
    """Yield photos that have GPS coordinates."""
    return conn.execute(
        """
        SELECT path, lat, lon
        FROM photos
        WHERE lat IS NOT NULL AND lon IS NOT NULL
        ORDER BY path
        """
    )


def fetch_geocode(
    conn: sqlite3.Connection,
    lat_rounded: float,
    lon_rounded: float,
    provider: str,
) -> Tuple[str, str, str, str]:
    """Fetch cached geocode details for rounded coordinates."""
    row = conn.execute(
        """
        SELECT city, state, country, display_name
        FROM geocode_cache
        WHERE lat_rounded = ? AND lon_rounded = ? AND provider = ?
        """,
        (lat_rounded, lon_rounded, provider),
    ).fetchone()
    if row is None:
        return (None, None, None, None)
    return (row[0], row[1], row[2], row[3])


def export_locations(db_path: str, out_csv: str, provider: str = "nominatim") -> None:
    """Export photo locations from the cache database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    with open(out_csv, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(
            csvfile,
            fieldnames=[
                'path',
                'lat',
                'lon',
                'lat_rounded',
                'lon_rounded',
                'city',
                'state',
                'country',
                'display_name',
            ],
        )
        writer.writeheader()

        for row in iter_photos(conn):
            lat = row['lat']
            lon = row['lon']
            lat_rounded, lon_rounded = round_coordinates(lat, lon, 3)
            city, state, country, display_name = fetch_geocode(
                conn,
                lat_rounded,
                lon_rounded,
                provider,
            )
            writer.writerow(
                {
                    'path': row['path'],
                    'lat': lat,
                    'lon': lon,
                    'lat_rounded': lat_rounded,
                    'lon_rounded': lon_rounded,
                    'city': city,
                    'state': state,
                    'country': country,
                    'display_name': display_name,
                }
            )

    conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export cached photo locations to CSV.",
    )
    parser.add_argument(
        '--db',
        default='picmap_cache.sqlite',
        help='SQLite cache database path (default: picmap_cache.sqlite)',
    )
    parser.add_argument(
        '--out',
        default='locations.csv',
        help='Output CSV path (default: locations.csv)',
    )

    args = parser.parse_args()

    export_locations(args.db, args.out)


if __name__ == '__main__':
    main()
