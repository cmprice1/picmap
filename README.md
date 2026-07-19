# PicMap — Road Trip Maps from Geotagged Photos

Turn a photo library from a road trip into three things:

1. **An engine** — a pipeline that extracts GPS/EXIF metadata from any photo
   collection, clusters it into stops, geocodes them, and builds a
   road-following route. Reusable for any past or future trip.
2. **An interactive web app** — a Mapbox GL experience for exploring one
   specific trip (landing page, animated hero photos, stop-by-stop gallery).
3. **A print map** — a high-resolution, stylized poster of the whole route,
   suitable for a photo album or framing.

The repo currently contains the built output for the **Summer 2025 Great
American Road Trip** (Los Angeles → Raleigh, June 28 – August 3: 37 days,
~7,000 miles, 17 states, 8,435 photographs).

---

## Repo layout

| Path | What it is |
|---|---|
| `output/` | The built 2025 trip: web app (`index.html`), trip data (`data.json`, `trip_metadata.json`, manifests), sample photos, print map (`output/print/`) |
| `extract_metadata.py`, `colab_launcher.ipynb` | **Phase 1** — runs in Google Colab against a Drive-mounted Google Takeout; scans photos + JSON sidecars, extracts GPS/timestamps → `trip_metadata.json` |
| `build_from_captured.py`, `classify_overnight.py`, `assign_photos.py`, `trim_photos.py` | **Phase 2** — local: clusters photos into stops, classifies day vs. overnight, geocodes names, assigns gallery photos → `data.json` |
| `build_route.py` | Snaps the chronological GPS path to real roads via the Mapbox Directions API → `route` in `data.json` (already done for 2025) |
| `build_final_leg.py` | Appends the final drive past the last GPS photo (Mt Airy → Durham → Raleigh) using OSRM road routing — no token needed; idempotent (already done for 2025) |
| `build_print_map.py` | Renders the print poster from `data.json` — no network needed |
| `assets/us-states-10m.json` | US state boundaries (public domain, [us-atlas](https://github.com/topojson/us-atlas) / US Census) used by the print map |
| `config.json` | Pipeline tuning: clustering radii, overnight thresholds, trip title |
| `picmap/`, `create_sample_photos.py`, `test_picmap.sh`, `tests/` | **v1 engine** — the original one-shot `python -m picmap <photo dir>` Leaflet app. Still works for quick maps of any folder. `IMPLEMENTATION_SUMMARY.md` / `USAGE_EXAMPLES.md` document this era |
| `PROJECT_STATUS.md` | Current state of the project, where everything lives, cleanup checklist |

## 1 · View the 2025 trip web app

```bash
python -m http.server 8080 --directory output
# open http://localhost:8080
```

The app asks for a Mapbox access token on first load (get one free at
mapbox.com → Account → Tokens); it is stored in your browser only. Full-size
photo streaming pulls from Google Drive; the bundled `output/photos/` has
representative photos per stop so the app works standalone.

## 2 · Build a picmap for a new trip (v2 pipeline)

1. Google Takeout of the trip's photos → Google Drive.
2. Open `colab_launcher.ipynb` in Colab, point it at the Takeout folder
   (use `--album` for a single album). It writes `trip_metadata.json`.
3. Locally: `python build_from_captured.py` (clusters + geocodes; tune
   `config.json`), then `python build_route.py` (needs a Mapbox token pasted
   at the top of the script — do not commit it).
4. Serve `output/` as above.

For a quick-and-dirty map of any local folder of geotagged photos, the v1
one-liner still works: `pip install -r requirements.txt && python -m picmap /path/to/photos`.

## 3 · Regenerate the print map

```bash
python build_print_map.py
```

Reads `output/data.json` + `assets/us-states-10m.json`, writes to
`output/print/`:

- `roadtrip_print_24x12.svg` — vector master, scales to any print size
- `roadtrip_print_24x12.png` — 7200×3600 (300 DPI at 24×12 in, i.e. a
  two-page spread in a 12×12 album)
- `preview.png` — small proof
- `versions/vN_<date>_<style>[-label].*` — **every run is archived here and
  never overwritten**; only the three unversioned files above (the
  "latest" pointer) get replaced. Pass `--label "some-tag"` to name a run.
  If you ever need an older render back, it's in `versions/`.

Pass `--plain` for the route + state outlines only (no mountains/trees/
lakes/park markers), written to `roadtrip_print_24x12_plain.{svg,png}` +
its own `versions/` entries.

All hand-tuned positioning (label offsets, per-stop corrections, glyph
coordinates) lives in **`map_layout.json`**, which the script loads at
startup. Page size, palette, and fonts remain constants in the script.
Fonts: DM Sans + Pinyon Script (`assets/fonts/`, matches the web app),
falling back to Windows system fonts if missing.

### Layout editor (drag-and-drop positioning)

```bash
python serve_editor.py
# open http://localhost:8081/map_editor.html
```

A browser editor for `map_layout.json`: drag stop labels and pictorial
glyphs (mountains, trees, lakes, park markers) into place on an
approximate preview — the side panel selects crowded items, edits
anchoring (`ha`/`va`), scale, and names, adds/removes glyphs, and can
hide stops. **Save** writes back to `map_layout.json` (with a `.bak`);
**Render poster** runs `build_print_map.py` for a real print-quality
check (`open last render`). Undo/redo with Ctrl+Z / Ctrl+Y; wheel zooms,
background-drag pans. Check "allow dragging stop markers" to move a
stop's corrected lat/lon rather than its label.

The preview is intentionally approximate (placeholder glyph shapes,
browser text metrics) — the Python script is the source of truth for the
actual print output. If the route ever changes, re-run
`python build_editor_context.py` to refresh the editor's basemap/window.

## Secrets & big files (not in git)

- `credentials.json`, `token.json`, `drive_token.json` — Google OAuth for
  Drive/Photos APIs; local only, gitignored, never committed.
- `curated_photos.zip` (~1.4 GB) and `output/photos/` originals — local /
  cloud-storage only; git carries the app, data JSON, and print outputs.
