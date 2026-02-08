# PicMap Usage Examples

## Quick Start

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Create Test Photos (Optional)
Generate sample photos with GPS data for testing:
```bash
python create_sample_photos.py
```

This creates 5 sample photos representing a road trip from San Francisco to Las Vegas.

### 3. Run PicMap
Process your photos and start the web server:
```bash
# With sample photos
python -m picmap sample_photos

# With your own photos
python -m picmap /path/to/your/photos
```

The application will:
1. Scan the directory for photos with GPS EXIF data
2. Extract GPS coordinates and timestamps
3. Generate a GeoJSON file with the route
4. Create an interactive HTML/JS map application
5. Start a local web server at http://localhost:8000

## Advanced Usage

### Custom Output Directory
```bash
python -m picmap /path/to/photos -o ./my-trip-map
```

### Custom Port
```bash
python -m picmap /path/to/photos -p 3000
```

### Generate Files Only (No Server)
```bash
python -m picmap /path/to/photos --no-server
```

Then manually start a server:
```bash
cd output
python -m http.server 8000
```

## Using the Web Interface

Once the server is running, open http://localhost:8000 in your browser.

### Features:
- **Interactive Map**: Pan and zoom to explore your route
- **Photo Markers**: Click any purple marker to see photo details
- **Fit to Route**: Button to zoom and center the entire route
- **Export Map**: Download the current view as a PNG image
- **Print**: Create a print-friendly version of the map

### Photo Popups Include:
- Photo preview (thumbnail)
- Filename
- Timestamp
- GPS coordinates

## File Structure

After running PicMap, you'll have:

```
output/
├── index.html      # Main web application
├── app.js          # JavaScript for map functionality
├── route.geojson   # Generated route data
└── photos/         # Symlink/copy of your photos directory
```

## GeoJSON Format

The generated `route.geojson` contains:
- **Point Features**: One for each photo with GPS data
  - Properties: filename, timestamp, GPS coordinates
- **LineString Feature**: Connects all photos in chronological order

Example:
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [-122.419, 37.7749]
      },
      "properties": {
        "filename": "photo_01.jpg",
        "timestamp": "2024-07-15T09:00:00",
        "index": 0
      }
    },
    ...
  ]
}
```

## Troubleshooting

### No Photos Found
- Ensure photos have GPS EXIF data (check with `exiftool` or similar)
- Verify file extensions are supported (.jpg, .jpeg, .png, .tif, .tiff)
- Check the directory path is correct

### Photos Don't Show in Popups
- Make sure the `photos` symlink/directory exists in output folder
- Check browser console for errors
- Verify photos are accessible from the web server

### Port Already in Use
- Change the port: `python -m picmap photos -p 8080`
- Or kill the process using port 8000

## Examples

### Example 1: Process Trip Photos
```bash
python -m picmap ~/Pictures/summer-road-trip/
```

### Example 2: Custom Configuration
```bash
python -m picmap ~/Pictures/vacation/ -o ./vacation-map -p 9000
```

### Example 3: Generate and Deploy
```bash
# Generate files
python -m picmap photos/ -o ./dist --no-server

# Copy to web server
scp -r ./dist/* user@server:/var/www/mytrip/
```

## Tips

1. **Photo Organization**: Keep photos in chronological order (by timestamp)
2. **GPS Privacy**: Be aware that EXIF GPS data reveals exact locations
3. **Export Quality**: Use the Export button for high-quality PNG exports
4. **Browser Support**: Works best in modern browsers (Chrome, Firefox, Safari, Edge)
5. **Offline Use**: The generated files work offline except for map tiles
