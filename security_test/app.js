// PicMap Application
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
            const popupContent = `
                <div class="photo-popup">
                    <img src="${props.path}" alt="${props.filename}" onerror="this.style.display='none'">
                    <h3>${props.filename}</h3>
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
