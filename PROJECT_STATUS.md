# Project Status — July 18, 2026

Written after a full inventory of every copy of this project. Read this first
when returning to the project.

## Where everything lives

| Location | Role | State |
|---|---|---|
| github.com/cmprice1/picmap | Home of the code | `main` = old v1 engine; **`v2-colab` = the real project** (11 commits ahead, fully pushed). Merge pending — see checklist |
| `…\Side Projects\Photo Tools\2025 Roadtrip Map\roadtrip-map\` | **The live working copy** (this folder), checkout of `v2-colab` | Working tree has: print-map work, README rewrite, data fixes (all July 18, 2026, uncommitted) |
| `C:\Users\hgste\picmap` | Stale Feb 2026 clone of v1 `main` | **No unpushed commits, no stashes.** Only unique content: original iCloud `Photos (N).zip` batches + HEIC→JPG experiments in `photos/` (~564 MB) and a v1 demo build in `output/` (~312 MB). Safe to delete once the zips are archived |

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

- 8,435 photos, 6,137 with GPS; 154 stops (23 overnight); route = 10,146
  road-snapped points (Mapbox Directions, already baked into `data.json`).
- GPS data ends at Surry County, NC (Aug 3). The final leg to Raleigh has no
  geotagged photos — the print map shows it as a dashed line.
- Stats derived from route: ~7,077 miles driven, 17 states.

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

## Cleanup checklist (pending approval / not yet done)

1. **Commit** the July 18 working-tree changes on `v2-colab`.
2. **Merge `v2-colab` → `main`** and push — makes GitHub's front page reflect
   the real project instead of v1.
3. **Move the repo out of OneDrive** (git dirs in OneDrive risk sync
   corruption; this working copy is 2.8 GB): repo → `C:\Users\hgste\code\picmap`;
   keep `curated_photos.zip` + full-res media in OneDrive/cloud, outside git.
4. **Archive then delete `C:\Users\hgste\picmap`**: move `photos/*.zip`
   (original iCloud exports) to a media archive first; everything else there
   is redundant (876 MB reclaimed).
5. Optional prune: `output/photos/` keeps 393 MB of HEIC originals + ~1 GB of
   video alongside the 74 MB of JPGs the app displays — verify references,
   then thin (originals live in Google Photos/Drive).
6. Pipeline TODO: epoch-timestamp fallback in `extract_metadata.py`;
   `build_route.py` reads its Mapbox token from a constant — switch to an env
   var so it can never be committed by accident.
