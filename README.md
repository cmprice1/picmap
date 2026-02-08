# 🗺️ PicMap - Road Trip Photo Visualizer

Automated generation of an interactive map to visualize your road trip from photos. PicMap extracts GPS coordinates and timestamps from your photo's EXIF metadata to create a beautiful interactive map showing your journey.

![PicMap Demo](https://img.shields.io/badge/Python-3.7+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)

## ✨ Features

- 📸 **Automatic EXIF extraction** - Reads GPS coordinates and timestamps from photo metadata
- 🗺️ **Interactive map** - Beautiful Leaflet-based map with OpenStreetMap tiles
- 📍 **Route visualization** - Shows your journey path connecting all photo locations
- 🖼️ **Photo popups** - Click markers to see photo previews and details
- 💾 **Export functionality** - Save your map as PNG or print-friendly PDF
- 🚀 **One-command setup** - Get started instantly with a single command
- 🆓 **100% free & open-source** - Uses only free libraries and services

## 🚀 Quick Start

### Prerequisites

- Python 3.7 or higher
- Photos with GPS EXIF data (most smartphone photos include this)

### Installation & Run (One Command!)

```bash
# Clone the repository
git clone https://github.com/cmprice1/picmap.git
cd picmap

# Install dependencies and run
pip install -r requirements.txt && python -m picmap /path/to/your/photos
```

That's it! Your browser will automatically open to `http://localhost:8000` showing your interactive road trip map.

## 📖 Usage

### Basic Usage

Process photos from a directory and start the web server:

```bash
python -m picmap /path/to/photos
```

### Advanced Options

```bash
# Specify custom output directory
python -m picmap /path/to/photos -o ./my-trip-map

# Use a different port
python -m picmap /path/to/photos -p 8080

# Generate files only (no server)
python -m picmap /path/to/photos --no-server
```

### View Help

```bash
python -m picmap --help
```

## 📁 Project Structure

```
picmap/
├── picmap/             # PicMap package
├── requirements.txt    # Python dependencies
├── README.md          # This file
└── output/            # Generated files (created automatically)
    ├── index.html     # Web application
    ├── app.js         # JavaScript for map interactivity
    ├── route.geojson  # Generated route data
    └── photos/        # Symlink to your photos directory
```

## 🔧 How It Works

1. **Scan Photos** - Recursively scans the specified directory for image files (JPG, PNG, TIFF)
2. **Extract EXIF** - Reads GPS coordinates and timestamps from each photo's EXIF metadata
3. **Generate Route** - Creates a GeoJSON file with points for each photo and a line connecting them
4. **Build App** - Generates a static HTML/JavaScript application
5. **Serve** - Starts a local web server to view the interactive map

## 🗺️ Map Features

### Interactive Elements
- **Markers** - Purple circular markers at each photo location
- **Route Line** - Smooth line connecting photos in chronological order
- **Popups** - Click any marker to see:
  - Photo preview (thumbnail)
  - Filename
  - Timestamp
  - GPS coordinates

### Controls
- **Fit to Route** - Automatically zoom and pan to show the entire journey
- **Export Map** - Download the current map view as a PNG image
- **Print** - Generate a print-friendly version of the map

## 📦 Dependencies

All dependencies are free and open-source:

- **[Pillow](https://python-pillow.org/)** (10.2.0) - Image processing library
- **[piexif](https://github.com/hMatoba/Piexif)** (1.1.3) - EXIF data extraction
- **[geopy](https://github.com/geopy/geopy)** (2.4.1) - Geographic calculations
- **[Leaflet](https://leafletjs.com/)** (1.9.4) - Interactive map library (CDN)
- **[OpenStreetMap](https://www.openstreetmap.org/)** - Free map tiles

## 📸 Photo Requirements

For PicMap to work, your photos must have GPS EXIF data. Most modern smartphones automatically embed this information when taking photos (if location services are enabled).

### Checking Your Photos

To verify if your photos have GPS data:

**On Mac:**
```bash
mdls -name kMDItemLatitude -name kMDItemLongitude photo.jpg
```

**On Linux:**
```bash
exiftool photo.jpg | grep GPS
```

**On Windows:**
- Right-click photo → Properties → Details → Look for GPS section

### Sample Photos

If you don't have photos with GPS data, you can:
1. Enable location services on your smartphone camera
2. Use sample photos from your past trips
3. Add GPS data to existing photos using tools like [ExifTool](https://exiftool.org/)

## 🎨 Customization

### Changing Map Style

Edit `picmap/app.py` in the `create_html_app` function to use different tile providers:

```javascript
// Alternative free tile providers:

// Topographic map
L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenTopoMap contributors'
}).addTo(map);

// Humanitarian map
L.tileLayer('https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors, Tiles courtesy of HOT'
}).addTo(map);
```

### Customizing Colors

In the generated `app.js` file, you can modify:
- Marker colors: `fillColor` property
- Route line color: `color` property in polyline options
- UI gradient: CSS in `index.html`

## 🐛 Troubleshooting

### No photos found
- Ensure photos have GPS EXIF data
- Check that photos have supported extensions (.jpg, .jpeg, .png, .tif, .tiff)
- Verify the directory path is correct

### Photos not displaying in popups
- Make sure the photos directory is accessible
- Check browser console for CORS errors
- Try copying photos instead of symlinking (happens automatically on Windows)

### Server won't start
- Check if port 8000 is already in use
- Try a different port with `-p` flag
- Ensure you have necessary permissions

## 📜 License

MIT License - feel free to use this project for personal or commercial purposes.

## 🤝 Contributing

Contributions are welcome! Feel free to:
- Report bugs
- Suggest features
- Submit pull requests

## 🙏 Acknowledgments

- [Leaflet](https://leafletjs.com/) - Amazing open-source mapping library
- [OpenStreetMap](https://www.openstreetmap.org/) - Free, collaborative world map
- All the open-source contributors who make projects like this possible

## 📧 Support

If you encounter any issues or have questions, please open an issue on GitHub.

---

**Happy mapping! 🗺️✈️📸**
