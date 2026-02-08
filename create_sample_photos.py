#!/usr/bin/env python3
"""
Create sample photos with GPS EXIF data for testing PicMap
"""

import os
from PIL import Image
import piexif
from datetime import datetime, timedelta

def create_sample_photo_with_gps(filename, latitude, longitude, timestamp):
    """Create a sample photo with GPS EXIF data."""
    # Create a simple colored image
    img = Image.new('RGB', (400, 300), color='skyblue')
    
    # Prepare GPS EXIF data
    def decimal_to_dms(decimal):
        """Convert decimal degrees to degrees, minutes, seconds."""
        degrees = int(decimal)
        minutes_decimal = (decimal - degrees) * 60
        minutes = int(minutes_decimal)
        seconds = int((minutes_decimal - minutes) * 60 * 100)  # Store as rational
        return ((abs(degrees), 1), (abs(minutes), 1), (abs(seconds), 100))
    
    # Convert coordinates
    lat_dms = decimal_to_dms(latitude)
    lon_dms = decimal_to_dms(longitude)
    
    lat_ref = b'N' if latitude >= 0 else b'S'
    lon_ref = b'E' if longitude >= 0 else b'W'
    
    # Create EXIF data
    exif_dict = {
        "GPS": {
            piexif.GPSIFD.GPSLatitude: lat_dms,
            piexif.GPSIFD.GPSLatitudeRef: lat_ref,
            piexif.GPSIFD.GPSLongitude: lon_dms,
            piexif.GPSIFD.GPSLongitudeRef: lon_ref,
        },
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: timestamp.strftime('%Y:%m:%d %H:%M:%S').encode(),
        }
    }
    
    exif_bytes = piexif.dump(exif_dict)
    img.save(filename, exif=exif_bytes)
    print(f"Created: {filename} at ({latitude}, {longitude})")


def main():
    # Create sample_photos directory
    output_dir = os.path.join(os.path.dirname(__file__), "sample_photos")
    os.makedirs(output_dir, exist_ok=True)
    
    # Sample road trip: San Francisco -> Los Angeles -> Las Vegas
    # These are real coordinates representing a classic West Coast road trip
    locations = [
        (37.7749, -122.4194, "San Francisco, CA"),  # San Francisco
        (36.7783, -119.4179, "Fresno, CA"),          # Fresno (midpoint)
        (34.0522, -118.2437, "Los Angeles, CA"),     # Los Angeles
        (35.6870, -117.8260, "Barstow, CA"),         # Barstow (desert stop)
        (36.1699, -115.1398, "Las Vegas, NV"),       # Las Vegas
    ]
    
    # Create photos with timestamps 2 hours apart
    base_time = datetime(2024, 7, 15, 9, 0, 0)  # Starting at 9 AM
    
    for i, (lat, lon, name) in enumerate(locations):
        timestamp = base_time + timedelta(hours=i * 2)
        filename = os.path.join(output_dir, f"photo_{i+1:02d}_{name.replace(' ', '_').replace(',', '')}.jpg")
        create_sample_photo_with_gps(filename, lat, lon, timestamp)
    
    print(f"\n✅ Created {len(locations)} sample photos in: {output_dir}")
    print(f"\nTest the app with:")
    print(f"  python picmap.py {os.path.abspath(output_dir)}")


if __name__ == '__main__':
    main()
