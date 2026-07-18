# Project Status — July 18, 2026

Written after a full inventory of every copy of this project. Read this first
when returning to the project.

## Where everything lives

| Location | Role | State |
|---|---|---|
| github.com/cmprice1/picmap | Home of the code | **`main` = the full project** (v2 pipeline + trip app + print map) as of July 18, 2026. `v2-colab` merged into it; that branch can be deleted at leisure |
| `C:\Users\hgste\code\picmap` | **The live working copy** (this folder), on `main` | Moved out of OneDrive July 18, 2026 (git dirs + sync don't mix). Includes `output/photos/` app media (~1.4 GB, gitignored) |
| `…\Side Projects\Photo Tools\2025 Roadtrip Map\media\` (OneDrive) | Media archive | `curated_photos.zip` (1.4 GB) + `icloud-originals/` (the original iCloud `Photos (N).zip` exports rescued from the old clone) |
| `C:\Users\hgste\picmap` | Stale Feb 2026 clone of v1 `main` | **No unpushed commits, no stashes.** Pending deletion once its photo zips are confirmed archived |

## The three outputs

1. **Engine** — v2 two-phase pipeline (Colab metadata extraction + local
   clustering/geocoding/routing). Works; produced the 2025 trip. v1 one-shot
   engine (`python -m picmap`) still available for quick maps.
2. **Web app** — `output/index.html`, complete and polished. Serve `output/`
   on any static server; Mapbox token entered at runtime.
3. **Print map** — built July 18, 2026 by `build_print_map.py` →
   `output/print/roadtrip_print_24x12.{svg,png}` (24×12 in @ 300 DPI).
   Overnight-stop display names were mapped from county geocodes by
   coordinate (e.g. "Inyo County" → "Death Valley", "Park County WY" →
   "Yellowstone", "Stephenson Township" → "Cedar River"); the full mapping is
   `DISPLAY_NAMES` in the script — correct there and rerun if any is off.

## Trip data facts

- 8,435 photos, 6,137 with GPS; 154 stops (23 overnight); route = 10,320
  road-snapped points (10,146 from Mapbox Directions on the GPS track, plus
  174 for the final leg — see below — baked into `data.json`).
- GPS photo data ends near Mt Airy, NC (Surry County, Aug 3). The final drive
  into the Research Triangle (Mt Airy → Durham → Raleigh) had no geotagged
  photos; `build_final_leg.py` routed it on real roads via OSRM and appended
  it, so the route now reaches Raleigh with no synthetic dashed segment.
- Stats derived from route: ~7,226 miles driven, 17 states.

## Fixed on July 18, 2026 (uncommitted)

- `data.json`: `trip.start_date` was `1970-01-01` (a photo with unparseable
  EXIF timestamp dragged stop_01's arrival to the epoch). Set to
  `2025-06-28`; stop_01 arrival set to its departure time. **Root cause is
  still in the pipeline** (`extract_metadata.py` timestamp fallback) — fix
  before building another trip.
- `output/index.html` tab title said "Southwest Odyssey" (early working
  title); now "Great American Road Trip · 2025", matching `data.json`.
- `config.json`: same stale title + mojibake (`Â·`) repaired.
- `.gitignore`: added `curated_photos.zip`.
- New: `build_print_map.py`, `assets/us-states-10m.json`, `output/print/*`,
  this file, rewritten `README.md`.

## Cleanup log

Done July 18, 2026:

1. ~~Commit the July 18 working-tree changes~~ (`e62f80b`, on both branches).
2. ~~Merge `v2-colab` → `main` and push~~ — GitHub front page now shows the
   real project.
3. ~~Move the repo out of OneDrive~~ → `C:\Users\hgste\code\picmap`;
   `curated_photos.zip` → OneDrive `…\2025 Roadtrip Map\media\`.
4. ~~Archive the old clone's photo zips~~ → OneDrive `media\icloud-originals\`.

Still open:

5. Delete `C:\Users\hgste\picmap` (stale clone; nothing unique left).
6. Optional prune: `output/photos/` keeps 393 MB of HEIC originals + ~1 GB of
   video alongside the 74 MB of JPGs the app displays — verify references,
   then thin (originals live in Google Photos/Drive).
7. Pipeline TODO: epoch-timestamp fallback in `extract_metadata.py`;
   `build_route.py` reads its Mapbox token from a constant — switch to an env
   var so it can never be committed by accident.
