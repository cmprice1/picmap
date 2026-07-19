# Plan: Interactive Layout Editor for the Print Map

> **Status: IMPLEMENTED** (July 19, 2026) — see `map_editor.html`,
> `map_editor.js`, `serve_editor.py`, `map_layout.json`,
> `build_editor_context.py`, and the "Layout editor" section of README.md.
> Two deviations from the plan below: (1) saving uses a ~30-line stdlib
> `POST /api/save` handler in `serve_editor.py` instead of the File System
> Access API — simpler than the two-path browser approach and works in every
> browser, since a local server was needed to serve the page anyway; it also
> enabled a bonus `POST /api/render` endpoint (a "Render poster" button in
> the editor). (2) Added items the plan missed: ha/va anchor editing, glyph
> scale + Rockies-size toggles, zoom/pan, stop hide/restore, and renaming.

## Problem

`build_print_map.py` renders the 24×12in trip poster from a set of
hand-tuned Python constants: `LABEL_STYLE` (per-label dx/dy pixel offsets),
`STOP_OVERRIDES` (corrected lat/lon + display names for mis-geocoded
stops), and the pictorial-glyph coordinate lists `MOUNTAINS`, `CONIFERS`,
`BROADLEAF`, `LAKES`, `PARKS`, `WAYPOINTS`. Tuning any of these today means:
edit the Python literal → re-run the script → open the PNG → zoom into the
region you touched → repeat. That loop is slow and error-prone for a
spatial/visual task.

## Goal

A local, browser-based editor where you drag labels and glyph markers on a
simplified preview of the map, then save — writing the updated
offsets/coordinates back to a data file that `build_print_map.py` reads on
its next run.

## Scope call: don't chase pixel-perfect fidelity

The editor's preview will **not** match the final poster exactly — different
rendering engine (SVG/Canvas vs. matplotlib), different font metrics, no
attempt to reproduce the hand-drawn glyph art (mountain silhouettes, the
bridge arch, the skyline, etc.) pixel-for-pixel. That's fine and intentional:
the editor's job is *getting positions right*, not being a second renderer.
Glyphs can be shown as simple shape-coded placeholder markers (e.g. a
triangle for mountains, a circle outline for lakes, a small flag for parks)
rather than their true poster artwork.

**A coding agent picking this up should resist the urge to make the browser
preview "look like the poster."** That's scope creep with no payoff — the
Python script stays the source of truth for the actual print output; this
tool only needs to be good enough to place things correctly, checked
occasionally against a real render.

## Step 1 (do first, independent of the rest — low risk, high value)

Extract the layout constants out of `build_print_map.py` into a single JSON
file, e.g. `map_layout.json`:

```json
{
  "label_style": { "Paradise Valley": {"dx": 9, "dy": 17, "ha": "left", "va": "center"}, ... },
  "stop_overrides": { "Las Vegas|2025-07-03": {"name": "Pahrump", "lat": 36.2083, "lon": -115.9839}, ... },
  "mountains": [ [-118.60, 36.55, 0.85, false], ... ],
  "conifers": [...], "broadleaf": [...],
  "lakes": { "Redfish Lake": [[lon,lat], ...], ... },
  "parks": [ {"name": "...", "lon": ..., "lat": ..., "kind": "mountain", "big": true, "dx":7, "dy":-2, "ha":"left"}, ... ],
  "waypoints": [ {"name": "Cincinnati", "lon": -84.512, "lat": 39.103}, ... ]
}
```

Notes on the conversion:
- `STOP_OVERRIDES` keys are currently Python tuples `(name, date)` — use a
  joined string key (`"Las Vegas|2025-07-03"`) since JSON object keys must
  be strings.
- `build_print_map.py` loads this JSON at the top instead of the hardcoded
  literals. Keep the same variable names (`LABEL_STYLE`, `STOP_OVERRIDES`,
  etc.) downstream so the rest of the script is untouched.
- This step alone is a pure refactor — same output, just data instead of
  code. Verify by diffing a render before/after; the PNG should be
  byte-identical (or near enough — matplotlib SVG output can have
  nondeterministic ordering in edge cases, but pixel content should match).

## Step 2: the editor page

New files: `map_editor.html` + `map_editor.js` (vanilla JS is enough —
no build step, no framework needed for something this size). Served via
`python -m http.server` from the repo root (same pattern as the existing
web app) so `fetch()` calls to local JSON files aren't blocked by CORS.

### Data it loads (read-only inputs)
- `output/data.json` — route coordinates + stops (for context: drawing the
  route line, day-stop stipple, overnight markers at their *current*
  effective position after overrides)
- `assets/us-states-10m.json` — state outlines. **Pre-decode this once in
  Python** (there's already a `decode_topojson()` function in
  `build_print_map.py`) and dump the flat lon/lat polygon rings to a small
  JSON (`assets/us-states-simplified.json`) — avoids writing a second
  TopoJSON decoder in JS for no reason.
- `map_layout.json` — the editable data from Step 1

### Rendering surface
An SVG element, viewBox sized to the 24:12 aspect ratio (e.g.
`viewBox="0 0 2400 1200"`, i.e. 100 units per inch — arbitrary but
convenient). Layers, back to front:
1. State fills + borders (static, not interactive)
2. Route line (decimate to ~500-1000 points for editor performance; the
   full 10,320-point route doesn't need to render at editor resolution)
3. Day-stop stipple dots (static)
4. Pictorial glyph markers — **draggable**
5. Overnight/waypoint markers — static position (position comes from
   `stop_overrides`, which is a separate, less-frequently-touched edit;
   don't conflate marker-position editing with label-offset editing,
   see below)
6. Labels (SVG `<text>`, using the same DM Sans files via `@font-face` —
   already in `assets/fonts/`) — **draggable**

### Projection (port from Python, exact same formulas)

```js
const LAT0 = 40.0, LON0 = -99.0, STD1 = 36.0, STD2 = 47.0;
const toRad = d => d * Math.PI / 180;
const p1 = toRad(STD1), p2 = toRad(STD2);
const n = 0.5 * (Math.sin(p1) + Math.sin(p2));
const C = Math.cos(p1) ** 2 + 2 * n * Math.sin(p1);
const rho0 = Math.sqrt(C - 2 * n * Math.sin(toRad(LAT0))) / n;

function project(lon, lat) {
  const theta = n * toRad(lon - LON0);
  const rho = Math.sqrt(C - 2 * n * Math.sin(toRad(lat))) / n;
  return [rho * Math.sin(theta), rho0 - rho * Math.cos(theta)];
}

// Inverse — needed for glyph dragging (screen pixel -> lon/lat)
function unproject(x, y) {
  const rho = Math.hypot(x, rho0 - y);
  const theta = Math.atan2(x, rho0 - y);
  const lat = Math.asin((C - (rho * n) ** 2) / (2 * n)) * 180 / Math.PI;
  const lon = LON0 + (theta / n) * 180 / Math.PI;
  return [lon, lat];
}
```

The view-window fitting (bbox + padding + aspect-ratio correction) in
`main()` also needs porting — it's ~20 lines of arithmetic, no surprises,
just needs to produce the same `x0,x1,y0,y1` the Python script computes so
dragged coordinates map back consistently. Simplest approach: **compute
that bounding box once in Python and include it in the exported JSON**
(`view_bbox: [x0,x1,y0,y1]` in projected units) rather than re-deriving it
from the route in JS — one less thing to keep in sync.

### Interactions

**Dragging a label**: labels are positioned as `anchor + offset(dx,dy in
points)`. On drag, compute the pixel delta, convert to the same point
units `LABEL_STYLE` already uses (a fixed px-per-point ratio, since the
editor's SVG viewBox is a fixed scale), and update `dx`/`dy` live. This is
the single most valuable interaction — it's most of what "editing labels"
means in practice.

**Dragging a glyph** (mountain/tree/lake/park marker): these are
positioned by absolute lon/lat, not an offset. On drag, take the new
screen position, run `unproject()`, and overwrite that glyph's
`[lon, lat, scale, big]` (or dict fields for `PARKS`) entry.

**Moving an overnight-stop marker** (i.e. editing `STOP_OVERRIDES` lat/lon,
like today's Pahrump/Billings corrections): treat this as a distinct,
opt-in action (e.g. a toggle "edit stop positions" mode, or a modifier key
while dragging) rather than always-draggable — these are rarer, more
consequential edits than nudging a label, and shouldn't be one accidental
drag away from the common label-nudging workflow.

**Side panel**: a simple list of every label/glyph by name, so items can be
selected/highlighted even when visually crowded (several of today's edits
were exactly this problem — Paradise Valley vs. Billings, Door County vs.
Traverse City). Clicking a list entry highlights/selects the corresponding
SVG element. Include basic add/remove for glyphs (choose a kind from a
dropdown, click the map to place; select + delete to remove) so new
mountains/trees/parks can be added without hand-editing JSON.

**Undo**: keep an in-memory array of full-layout snapshots after each
committed change (drag-end, add, delete); simple linear undo/redo, no need
for anything fancier.

### Saving

Static pages can't freely write local files, so pick one:

- **Preferred**: the File System Access API
  (`window.showSaveFilePicker()` / re-opening the same handle on
  subsequent saves) — one-time permission grant, then a "Save" button
  writes `map_layout.json` directly. Supported in Chromium-based browsers
  (Chrome, Edge); not in Firefox/Safari as of today.
- **Fallback** (works everywhere, zero extra tooling): a "Download JSON"
  button that triggers a normal file download; the user manually
  overwrites `map_layout.json` with the downloaded file. More friction,
  but no server component needed.

Given this is a solo local tool, implement the File System Access path as
primary and the download-fallback as the safety net for other browsers.
Skip building a local write-back server (Flask/Express) purely to avoid
this — it's more moving parts than the problem needs.

## Step 3: close the loop

After saving `map_layout.json`, run `python build_print_map.py` (and
`--plain`) as before — it now reads the edited JSON, so the next real
render reflects the dragged positions. The editor is the fast/approximate
pass; the Python script remains the final-quality pass. Expect a couple of
these round trips per session (drag → save → render → spot-check → back to
editor) rather than expecting the editor preview alone to be trustworthy
for final placement.

## Effort estimate

| Piece | Estimate |
|---|---|
| Step 1: extract constants to JSON, wire script to read them | 30–60 min |
| Projection port + state outline/route rendering | 1–2 hrs |
| Label dragging + glyph dragging (incl. inverse projection) | 2–3 hrs |
| Side panel (list/select/add/remove) + save/export | 2–3 hrs |
| Polish (font loading, zoom/pan, basic styling) | 1–2 hrs, open-ended |
| **Total** | **roughly one day** for a front-end-capable coding agent |

## Files a coding agent would touch/create

- `map_layout.json` — new, generated once from today's Python constants
- `build_print_map.py` — modified to load `map_layout.json` instead of
  hardcoding `LABEL_STYLE` / `STOP_OVERRIDES` / `MOUNTAINS` / etc.
- `assets/us-states-simplified.json` — new, pre-decoded state outlines
  (flat lon/lat rings) for the editor to consume without a JS TopoJSON
  decoder
- `map_editor.html`, `map_editor.js` — new, the editor itself
- `README.md` — a short section documenting the editor + the
  edit → save → re-render workflow
