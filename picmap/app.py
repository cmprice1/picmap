#!/usr/bin/env python3
"""
PicMap - Road Trip Photo Visualizer
Extracts EXIF GPS data from photos and generates an interactive map
"""

import os
import sys
import json
import argparse
import http.server
import socketserver
import hashlib
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple

try:
    from PIL import Image, ImageOps
    import piexif
    from geopy.geocoders import Nominatim
    from geopy.extra.rate_limiter import RateLimiter
except ImportError:
    print("Error: Required packages not installed. Run: pip install -r requirements.txt")
    sys.exit(1)


def get_decimal_coordinates(gps_info: Dict) -> Optional[Tuple[float, float]]:
    """
    Convert GPS coordinates from degrees/minutes/seconds to decimal format.
    
    Args:
        gps_info: Dictionary containing GPS EXIF data
        
    Returns:
        Tuple of (latitude, longitude) in decimal degrees, or None if invalid
    """
    try:
        # Get latitude
        lat = gps_info.get(piexif.GPSIFD.GPSLatitude)
        lat_ref = gps_info.get(piexif.GPSIFD.GPSLatitudeRef, b'N')
        
        # Get longitude
        lon = gps_info.get(piexif.GPSIFD.GPSLongitude)
        lon_ref = gps_info.get(piexif.GPSIFD.GPSLongitudeRef, b'E')
        
        if not lat or not lon:
            return None
        
        # Convert to decimal
        lat_decimal = lat[0][0] / lat[0][1] + lat[1][0] / (lat[1][1] * 60) + lat[2][0] / (lat[2][1] * 3600)
        lon_decimal = lon[0][0] / lon[0][1] + lon[1][0] / (lon[1][1] * 60) + lon[2][0] / (lon[2][1] * 3600)
        
        # Apply hemisphere reference
        if lat_ref == b'S':
            lat_decimal = -lat_decimal
        if lon_ref == b'W':
            lon_decimal = -lon_decimal
            
        return (lat_decimal, lon_decimal)
    except (KeyError, TypeError, ZeroDivisionError):
        return None


def get_exif_timestamp(exif_dict: Dict) -> Optional[str]:
    """
    Extract timestamp from EXIF data.
    
    Args:
        exif_dict: Dictionary containing EXIF data
        
    Returns:
        ISO format timestamp string, or None if not found
    """
    try:
        if "Exif" in exif_dict:
            timestamp = exif_dict["Exif"].get(piexif.ExifIFD.DateTimeOriginal)
            if timestamp:
                # Convert bytes to string and parse
                timestamp_str = timestamp.decode('utf-8')
                dt = datetime.strptime(timestamp_str, '%Y:%m:%d %H:%M:%S')
                return dt.isoformat()
    except (ValueError, AttributeError):
        pass
    return None


def get_exif_location_hint(exif_dict: Dict) -> Optional[str]:
    """
    Extract a human-friendly location hint from EXIF fields if present.
    """
    try:
        if "0th" in exif_dict:
            description = exif_dict["0th"].get(piexif.ImageIFD.ImageDescription)
            if description:
                if isinstance(description, bytes):
                    return description.decode('utf-8', errors='ignore').strip()
                if isinstance(description, str):
                    return description.strip()
            xp_title = exif_dict["0th"].get(piexif.ImageIFD.XPTitle)
            if xp_title:
                try:
                    return bytes(xp_title).decode('utf-16le', errors='ignore').strip()
                except (TypeError, ValueError):
                    return None
    except Exception:
        return None
    return None


def extract_photo_data(photo_path: str) -> Optional[Dict]:
    """
    Extract GPS coordinates, timestamp, and other metadata from a photo.
    
    Args:
        photo_path: Path to the photo file
        
    Returns:
        Dictionary containing photo metadata, or None if no GPS data
    """
    try:
        img = Image.open(photo_path)
        exif_dict = piexif.load(img.info.get('exif', b''))
        
        # Extract GPS data
        gps_info = exif_dict.get("GPS", {})
        coordinates = get_decimal_coordinates(gps_info)
        
        if not coordinates:
            return None
        
        # Extract timestamp
        timestamp = get_exif_timestamp(exif_dict)
        
        # Get file info
        filename = os.path.basename(photo_path)
        
        return {
            "filename": filename,
            "path": photo_path,
            "source_path": photo_path,
            "latitude": coordinates[0],
            "longitude": coordinates[1],
            "timestamp": timestamp or os.path.getmtime(photo_path),
            "location_hint": get_exif_location_hint(exif_dict)
        }
    except Exception as e:
        print(f"Warning: Could not process {photo_path}: {e}")
        return None


def scan_photos(directory: str) -> List[Dict]:
    """
    Scan a directory for photos and extract their metadata.
    
    Args:
        directory: Path to directory containing photos
        
    Returns:
        List of photo metadata dictionaries, sorted by timestamp
    """
    photo_extensions = {'.jpg', '.jpeg', '.png', '.tif', '.tiff'}
    photos = []
    
    print(f"Scanning directory: {directory}")
    
    for root, dirs, files in os.walk(directory):
        for file in files:
            if Path(file).suffix.lower() in photo_extensions:
                photo_path = os.path.join(root, file)
                photo_data = extract_photo_data(photo_path)
                if photo_data:
                    rel_path = os.path.relpath(photo_path, directory)
                    rel_path = rel_path.replace(os.sep, '/')
                    photo_data["path"] = f"photos/{rel_path}"
                    photos.append(photo_data)
                    print(f"  ✓ {file}")
                else:
                    print(f"  ✗ {file} (no GPS data)")
    
    # Sort by timestamp
    photos.sort(key=lambda x: x['timestamp'])
    
    print(f"\nFound {len(photos)} photos with GPS data")
    return photos


def _ensure_thumbnail_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS thumbnails (
            photo_id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            mtime INTEGER NOT NULL,
            size INTEGER NOT NULL,
            thumbnail_path TEXT NULL,
            stage_thumbnail INTEGER NOT NULL DEFAULT 0,
            thumbnail_mtime INTEGER NULL
        )
        """
    )
    columns = {
        row[1]: row[2]
        for row in conn.execute("PRAGMA table_info(thumbnails)")
    }
    if "thumbnail_path" not in columns:
        conn.execute("ALTER TABLE thumbnails ADD COLUMN thumbnail_path TEXT NULL")
    if "stage_thumbnail" not in columns:
        conn.execute(
            "ALTER TABLE thumbnails ADD COLUMN stage_thumbnail INTEGER NOT NULL DEFAULT 0"
        )
    if "thumbnail_mtime" not in columns:
        conn.execute("ALTER TABLE thumbnails ADD COLUMN thumbnail_mtime INTEGER NULL")
    conn.commit()


def _sanitize_stem(stem: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-_")
    return cleaned or "photo"


def _build_fallback_thumbnail_name(photo_path: str) -> str:
    stem = _sanitize_stem(Path(photo_path).stem)
    digest = hashlib.sha1(photo_path.encode("utf-8")).hexdigest()[:8]
    return f"{stem}-{digest}.jpg"


def generate_thumbnails(photos: List[Dict], output_dir: str) -> None:
    """
    Generate thumbnails for photos incrementally and cache progress in SQLite.
    """
    thumbnails_dir = os.path.join(output_dir, "thumbnails")
    os.makedirs(thumbnails_dir, exist_ok=True)
    db_path = os.path.join(output_dir, "picmap_cache.sqlite")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    _ensure_thumbnail_table(conn)

    for photo in photos:
        source_path = photo.get("source_path") or photo.get("path")
        if not source_path:
            continue

        try:
            stat = os.stat(source_path)
        except OSError:
            continue

        mtime = int(stat.st_mtime)
        size = stat.st_size

        conn.execute(
            """
            INSERT OR IGNORE INTO thumbnails (path, mtime, size)
            VALUES (?, ?, ?)
            """,
            (source_path, mtime, size),
        )

        row = conn.execute(
            """
            SELECT photo_id, mtime, size, thumbnail_path, stage_thumbnail
            FROM thumbnails
            WHERE path = ?
            """,
            (source_path,),
        ).fetchone()

        if row is None:
            continue

        if row["mtime"] != mtime or row["size"] != size:
            conn.execute(
                """
                UPDATE thumbnails
                SET mtime = ?,
                    size = ?,
                    thumbnail_path = NULL,
                    stage_thumbnail = 0,
                    thumbnail_mtime = NULL
                WHERE path = ?
                """,
                (mtime, size, source_path),
            )
            row = conn.execute(
                """
                SELECT photo_id, mtime, size, thumbnail_path, stage_thumbnail
                FROM thumbnails
                WHERE path = ?
                """,
                (source_path,),
            ).fetchone()
            if row is None:
                continue

        thumbnail_rel_path = row["thumbnail_path"]
        if row["stage_thumbnail"] == 1 and thumbnail_rel_path:
            thumbnail_full_path = os.path.join(output_dir, thumbnail_rel_path)
            if os.path.exists(thumbnail_full_path):
                photo["thumbnail_path"] = thumbnail_rel_path
                continue

        if row["photo_id"] is not None:
            filename = f"{row['photo_id']}.jpg"
        else:
            filename = _build_fallback_thumbnail_name(source_path)

        thumbnail_rel_path = f"thumbnails/{filename}"
        thumbnail_full_path = os.path.join(output_dir, thumbnail_rel_path)

        try:
            with Image.open(source_path) as img:
                img = ImageOps.exif_transpose(img)
                img.thumbnail((512, 512))
                if img.mode in ("RGBA", "LA") or (
                    img.mode == "P" and "transparency" in img.info
                ):
                    img = img.convert("RGB")
                elif img.mode != "RGB":
                    img = img.convert("RGB")
                img.save(thumbnail_full_path, format="JPEG", quality=85)
        except Exception as exc:
            print(f"Warning: Could not generate thumbnail for {source_path}: {exc}")
            continue

        conn.execute(
            """
            UPDATE thumbnails
            SET thumbnail_path = ?,
                stage_thumbnail = 1,
                thumbnail_mtime = ?
            WHERE path = ?
            """,
            (
                thumbnail_rel_path,
                int(os.path.getmtime(thumbnail_full_path)),
                source_path,
            ),
        )
        photo["thumbnail_path"] = thumbnail_rel_path

    conn.commit()
    conn.close()


def format_location(address: Dict) -> Optional[str]:
    """
    Format a reverse geocoded address into a human-friendly location name.
    """
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


def add_location_data(photos: List[Dict]) -> None:
    """
    Enrich photo metadata with location names via reverse geocoding.
    """
    geolocator = Nominatim(user_agent="picmap")
    reverse = RateLimiter(geolocator.reverse, min_delay_seconds=1)
    cache: Dict[Tuple[float, float], Optional[str]] = {}

    for photo in photos:
        lat = photo['latitude']
        lon = photo['longitude']
        cache_key = (round(lat, 5), round(lon, 5))

        if cache_key in cache:
            photo['location'] = cache[cache_key]
            continue

        location_name = None
        try:
            location = reverse((lat, lon), zoom=10, language='en')
            if location and hasattr(location, 'raw'):
                location_name = format_location(location.raw.get('address', {}))
        except Exception:
            location_name = None

        cache[cache_key] = location_name
        photo['location'] = location_name


def generate_geojson(photos: List[Dict]) -> Dict:
    """
    Generate GeoJSON FeatureCollection from photo data.
    
    Args:
        photos: List of photo metadata dictionaries
        
    Returns:
        GeoJSON FeatureCollection dictionary
    """
    features = []
    
    # Create point features for each photo
    for i, photo in enumerate(photos):
        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [photo['longitude'], photo['latitude']]
            },
            "properties": {
                "filename": photo['filename'],
                "timestamp": str(photo['timestamp']),
                "index": i,
                "path": photo['path'],
                "thumbnail_path": photo.get('thumbnail_path'),
                "location": photo.get('location')
            }
        }
        features.append(feature)
    
    # Create LineString for the route
    if len(photos) > 1:
        route_feature = {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[p['longitude'], p['latitude']] for p in photos]
            },
            "properties": {
                "type": "route"
            }
        }
        features.append(route_feature)
    
    geojson = {
        "type": "FeatureCollection",
        "features": features
    }
    
    return geojson


def save_geojson(geojson: Dict, output_path: str):
    """Save GeoJSON to file."""
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geojson, f, indent=2)
    print(f"\nGeoJSON saved to: {output_path}")


def create_html_app(output_dir: str, photos_dir: str):
    """
    Create the HTML/JS application files.
    
    Args:
        output_dir: Directory to save the HTML app
        photos_dir: Directory containing the photos (for relative paths)
    """
    html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PicMap - Road Trip Visualizer</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        #header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 1rem 2rem;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        #header h1 {
            font-size: 1.5rem;
            font-weight: 600;
        }
        #header p {
            font-size: 0.9rem;
            opacity: 0.9;
            margin-top: 0.25rem;
        }
        #controls {
            background: white;
            padding: 0.75rem 2rem;
            border-bottom: 1px solid #e5e7eb;
            display: flex;
            gap: 1rem;
            align-items: center;
            flex-wrap: wrap;
        }
        .btn {
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 0.375rem;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
            display: inline-block;
        }
        .btn-primary {
            background: #667eea;
            color: white;
        }
        .btn-primary:hover {
            background: #5568d3;
        }
        .btn-secondary {
            background: #e5e7eb;
            color: #374151;
        }
        .btn-secondary:hover {
            background: #d1d5db;
        }
        #info {
            color: #6b7280;
            font-size: 0.875rem;
        }
        #map {
            flex: 1;
            background: #f3f4f6;
        }
        .photo-popup {
            text-align: center;
            max-width: 300px;
        }
        .photo-popup img {
            max-width: 100%;
            height: auto;
            border-radius: 0.375rem;
            margin-bottom: 0.5rem;
        }
        .photo-popup h3 {
            font-size: 0.875rem;
            font-weight: 600;
            margin-bottom: 0.25rem;
            color: #111827;
        }
        .photo-popup p {
            font-size: 0.75rem;
            color: #6b7280;
        }
        
        @media print {
            #header, #controls {
                display: none;
            }
            #map {
                height: 100vh !important;
            }
        }
    </style>
</head>
<body>
    <div id="header">
        <h1>🗺️ PicMap - Road Trip Visualizer</h1>
        <p>Interactive map showing your journey through photos</p>
    </div>
    
    <div id="controls">
        <button class="btn btn-primary" onclick="fitMapToRoute()">📍 Fit to Route</button>
        <button class="btn btn-secondary" onclick="exportMap()">💾 Export Map (PNG)</button>
        <button class="btn btn-secondary" onclick="window.print()">🖨️ Print</button>
        <div id="info"></div>
    </div>
    
    <div id="map"></div>
    
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script src="app.js"></script>
</body>
</html>
"""
    
    js_content = """// PicMap Application
let map;
let routeLayer;
let markersLayer;
let geojsonData;

// Initialize the map
function initMap() {
    map = L.map('map').setView([0, 0], 2);
    
    // Add OpenStreetMap tiles (free and open source)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19
    }).addTo(map);
    
    // Create layer groups
    routeLayer = L.featureGroup().addTo(map);
    markersLayer = L.featureGroup().addTo(map);
    
    // Load GeoJSON data
    loadGeoJSON();
}

// Load and display GeoJSON data
async function loadGeoJSON() {
    try {
        const response = await fetch('route.geojson');
        geojsonData = await response.json();
        
        displayRoute(geojsonData);
        updateInfo(geojsonData);
    } catch (error) {
        console.error('Error loading GeoJSON:', error);
        document.getElementById('info').textContent = 'Error loading route data';
    }
}

// Display the route and markers
function displayRoute(geojson) {
    let photoCount = 0;
    
    geojson.features.forEach(feature => {
        if (feature.geometry.type === 'Point') {
            // Create marker for photo location
            const coords = feature.geometry.coordinates;
            const props = feature.properties;
            
            const marker = L.circleMarker([coords[1], coords[0]], {
                radius: 8,
                fillColor: '#667eea',
                color: '#fff',
                weight: 2,
                opacity: 1,
                fillOpacity: 0.8
            });
            
            // Create popup with photo preview
            const timestamp = new Date(props.timestamp).toLocaleString();
            const location = props.location || 'Unknown location';
            const imagePath = props.thumbnail_path || props.path;
            const popupContent = `
                <div class="photo-popup">
                    <img src="${imagePath}" alt="${props.filename}" onerror="this.style.display='none'">
                    <h3>${location}</h3>
                    <p>📅 ${timestamp}</p>
                    <p>📍 ${coords[1].toFixed(6)}, ${coords[0].toFixed(6)}</p>
                </div>
            `;
            
            marker.bindPopup(popupContent, {
                maxWidth: 320,
                className: 'custom-popup'
            });
            
            marker.addTo(markersLayer);
            photoCount++;
            
        } else if (feature.geometry.type === 'LineString') {
            // Draw route line
            const coords = feature.geometry.coordinates.map(c => [c[1], c[0]]);
            const polyline = L.polyline(coords, {
                color: '#764ba2',
                weight: 3,
                opacity: 0.7,
                smoothFactor: 1
            });
            
            polyline.addTo(routeLayer);
        }
    });
    
    // Fit map to show all markers
    if (markersLayer.getBounds().isValid()) {
        map.fitBounds(markersLayer.getBounds(), { padding: [50, 50] });
    }
}

// Update info display
function updateInfo(geojson) {
    const photoCount = geojson.features.filter(f => f.geometry.type === 'Point').length;
    document.getElementById('info').textContent = `📷 ${photoCount} photos on this trip`;
}

// Fit map to show entire route
function fitMapToRoute() {
    if (markersLayer.getBounds().isValid()) {
        map.fitBounds(markersLayer.getBounds(), { padding: [50, 50] });
    }
}

// Export map as PNG
async function exportMap() {
    const mapElement = document.getElementById('map');
    
    try {
        // Hide controls temporarily
        const controls = document.querySelectorAll('.leaflet-control-container');
        controls.forEach(c => c.style.display = 'none');
        
        const canvas = await html2canvas(mapElement, {
            useCORS: true,
            allowTaint: true,
            backgroundColor: '#f3f4f6'
        });
        
        // Restore controls
        controls.forEach(c => c.style.display = '');
        
        // Download image
        const link = document.createElement('a');
        link.download = `picmap-route-${Date.now()}.png`;
        link.href = canvas.toDataURL();
        link.click();
        
        alert('Map exported successfully!');
    } catch (error) {
        console.error('Export error:', error);
        alert('Could not export map. Please try using Print instead.');
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initMap);
"""
    
    # Save files
    os.makedirs(output_dir, exist_ok=True)
    
    with open(os.path.join(output_dir, 'index.html'), 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    with open(os.path.join(output_dir, 'app.js'), 'w', encoding='utf-8') as f:
        f.write(js_content)
    
    print(f"HTML app created in: {output_dir}")


def start_server(directory: str, port: int = 8000):
    """
    Start a simple HTTP server to serve the application.
    
    Args:
        directory: Directory to serve
        port: Port number (default: 8000)
    """
    os.chdir(directory)
    
    Handler = http.server.SimpleHTTPRequestHandler
    
    with socketserver.TCPServer(("", port), Handler) as httpd:
        print(f"\n{'='*60}")
        print(f"🚀 PicMap server running!")
        print(f"{'='*60}")
        print(f"Open your browser to: http://localhost:{port}")
        print(f"Press Ctrl+C to stop the server")
        print(f"{'='*60}\n")
        
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n\nServer stopped.")


def main():
    parser = argparse.ArgumentParser(
        description='PicMap - Visualize your road trip from photo GPS data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process photos and start server in one command
  python -m picmap /path/to/photos
  
  # Specify output directory and custom port
  python -m picmap /path/to/photos -o ./my-map -p 8080
  
  # Only generate files without starting server
  python -m picmap /path/to/photos --no-server

  # Skip reverse geocoding (location names)
  python -m picmap /path/to/photos --no-geocode
        """
    )
    
    parser.add_argument(
        'photos_dir',
        help='Directory containing photos with GPS EXIF data'
    )
    
    parser.add_argument(
        '-o', '--output',
        default='./output',
        help='Output directory for generated files (default: ./output)'
    )
    
    parser.add_argument(
        '-p', '--port',
        type=int,
        default=8000,
        help='Server port (default: 8000)'
    )
    
    parser.add_argument(
        '--no-server',
        action='store_true',
        help='Generate files only, do not start server'
    )

    parser.add_argument(
        '--no-geocode',
        action='store_true',
        help='Skip reverse geocoding for location names'
    )
    
    args = parser.parse_args()
    
    # Validate photos directory
    if not os.path.isdir(args.photos_dir):
        print(f"Error: Directory not found: {args.photos_dir}")
        sys.exit(1)
    
    print("\n🗺️  PicMap - Road Trip Photo Visualizer\n")
    
    # Scan photos
    photos = scan_photos(args.photos_dir)
    
    if not photos:
        print("\nError: No photos with GPS data found!")
        print("Make sure your photos have EXIF GPS information.")
        sys.exit(1)
    
    if not args.no_geocode:
        print("\nLooking up location names (reverse geocoding)...")
        add_location_data(photos)

    # Generate GeoJSON
    geojson = generate_geojson(photos)
    
    # Create output directory
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    generate_thumbnails(photos, output_dir)

    # Generate GeoJSON
    geojson = generate_geojson(photos)

    # Save GeoJSON
    geojson_path = os.path.join(output_dir, 'route.geojson')
    save_geojson(geojson, geojson_path)

    # Create HTML app
    create_html_app(output_dir, args.photos_dir)
    
    # Create symbolic link to photos directory for serving
    photos_link = os.path.join(output_dir, 'photos')
    if os.path.exists(photos_link):
        if os.path.islink(photos_link):
            os.unlink(photos_link)
        elif os.path.isdir(photos_link):
            import shutil
            shutil.rmtree(photos_link)
    
    try:
        os.symlink(os.path.abspath(args.photos_dir), photos_link, target_is_directory=True)
    except OSError:
        # If symlink fails (e.g., on Windows without permissions), copy photos
        import shutil
        shutil.copytree(args.photos_dir, photos_link, dirs_exist_ok=True)
    
    print(f"\n✅ All files generated successfully!")
    
    # Start server unless --no-server flag is set
    if not args.no_server:
        start_server(output_dir, args.port)
    else:
        print(f"\nTo view the map, run:")
        print(f"  cd {output_dir} && python -m http.server {args.port}")


if __name__ == '__main__':
    main()
