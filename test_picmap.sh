#!/bin/bash
# Test script for PicMap

set -e

echo "=========================================="
echo "PicMap Test Suite"
echo "=========================================="

# Test 1: Check dependencies
echo -e "\n[1/5] Checking dependencies..."
python -c "import PIL; import piexif; import geopy" && echo "✓ All dependencies installed"

# Test 2: Create sample photos
echo -e "\n[2/5] Creating sample photos..."
python create_sample_photos.py > /dev/null
[ -d sample_photos ] && echo "✓ Sample photos created ($(ls sample_photos/*.jpg | wc -l) files)"

# Test 3: Generate map (no server)
echo -e "\n[3/5] Generating map from photos..."
python -m picmap sample_photos -o test_run --no-server --no-geocode > /dev/null 2>&1
[ -f test_run/index.html ] && echo "✓ HTML generated"
[ -f test_run/app.js ] && echo "✓ JavaScript generated"
[ -f test_run/route.geojson ] && echo "✓ GeoJSON generated"

# Test 4: Validate GeoJSON
echo -e "\n[4/5] Validating GeoJSON..."
python -c "
import json
with open('test_run/route.geojson') as f:
    data = json.load(f)
    assert data['type'] == 'FeatureCollection'
    assert len(data['features']) == 6  # 5 points + 1 line
    print('✓ GeoJSON structure valid')
"

# Test 5: Check HTML content
echo -e "\n[5/5] Validating HTML content..."
grep -q "leaflet@1.9.4" test_run/index.html && echo "✓ Leaflet library included"
grep -q "id=\"map\"" test_run/index.html && echo "✓ Map container present"
grep -q "Export Map" test_run/index.html && echo "✓ Export functionality present"

# Cleanup
rm -rf test_run

echo -e "\n=========================================="
echo "✅ All tests passed!"
echo "=========================================="
