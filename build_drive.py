#!/usr/bin/env python3
"""
Google Drive ingestion script for roadtrip-map.

Downloads a Google Takeout export folder from Google Drive, then hands off
to build.py for clustering, geocoding, and output generation.

Usage:
    # First run — browser OAuth prompt will appear:
    python build_drive.py --output ./output

    # If you know the Drive folder ID (from the URL):
    python build_drive.py --folder-id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs --output ./output

    # Custom working directory for downloaded files:
    python build_drive.py --working-dir /tmp/takeout_dl --output ./output

Prerequisites:
    pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client
    credentials.json in the current directory (same OAuth client used for auth.py)

Notes:
    - Uses drive.readonly scope — never modifies your Drive.
    - Saves a separate drive_token.json so it doesn't conflict with the Photos token.
    - Already-downloaded files are skipped (safe to re-run after interruption).
    - Handles Takeout exports from multiple Google accounts merged into one folder.
    - Takeout ZIPs are NOT automatically extracted — if your export arrived as
      .zip files rather than a folder tree, unzip them into --working-dir first,
      then re-run with --skip-download to use the already-extracted files.
"""

import argparse
import io
import os
import subprocess
import sys
import time
from pathlib import Path

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
except ImportError:
    print("ERROR: Missing packages. Run:")
    print("  pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DRIVE_SCOPE   = "https://www.googleapis.com/auth/drive.readonly"
CREDS_FILE    = "credentials.json"
TOKEN_FILE    = "drive_token.json"

# File types to download (media + JSON sidecars)
MEDIA_EXTS    = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".webp",
                 ".gif", ".tif", ".tiff", ".mp4", ".mov", ".avi", ".m4v"}
SIDECAR_EXTS  = {".json"}
RELEVANT_EXTS = MEDIA_EXTS | SIDECAR_EXTS

# Takeout exports sometimes arrive as numbered zip archives
ZIP_EXTS      = {".zip", ".tgz", ".tar.gz"}


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def get_drive_credentials():
    """Return valid Drive credentials, running OAuth flow if necessary."""
    creds = None

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, [DRIVE_SCOPE])

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing Drive token…")
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDS_FILE):
                print(f"ERROR: {CREDS_FILE} not found. Download OAuth credentials from")
                print("  Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client IDs")
                sys.exit(1)
            print("Opening browser for Google Drive authorization…")
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, [DRIVE_SCOPE])
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        print(f"Drive token saved to {TOKEN_FILE}")

    return creds


# ---------------------------------------------------------------------------
# Drive helpers
# ---------------------------------------------------------------------------

def build_drive_service(creds):
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def find_folder_by_name(service, name, parent_id=None):
    """Return the first Drive folder matching `name`, or None."""
    q = (f"name='{name}' and "
         f"mimeType='application/vnd.google-apps.folder' and trashed=false")
    if parent_id:
        q += f" and '{parent_id}' in parents"
    result = service.files().list(
        q=q, fields="files(id, name)", pageSize=10
    ).execute()
    files = result.get("files", [])
    return files[0] if files else None


def list_files_recursive(service, folder_id, rel_path="", depth=0):
    """
    Recursively list all non-folder files under folder_id.
    Returns list of dicts: {id, name, mimeType, rel_path, size}
    """
    results = []
    page_token = None

    while True:
        resp = service.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, mimeType, size)",
            pageToken=page_token,
            pageSize=1000,
        ).execute()

        for item in resp.get("files", []):
            item_rel = f"{rel_path}/{item['name']}" if rel_path else item["name"]
            if item["mimeType"] == "application/vnd.google-apps.folder":
                results.extend(
                    list_files_recursive(service, item["id"], item_rel, depth + 1)
                )
            else:
                item["rel_path"] = item_rel
                results.append(item)

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return results


def is_relevant(name: str) -> bool:
    ext = Path(name).suffix.lower()
    return ext in RELEVANT_EXTS


def is_zip(name: str) -> bool:
    lower = name.lower()
    return any(lower.endswith(z) for z in ZIP_EXTS)


def download_file(service, file_id: str, dest_path: Path, retries: int = 3) -> bool:
    """Download file_id from Drive to dest_path. Returns True on success."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(retries):
        try:
            request = service.files().get_media(fileId=file_id)
            with io.FileIO(dest_path, "wb") as fh:
                dl = MediaIoBaseDownload(fh, request, chunksize=4 * 1024 * 1024)
                done = False
                while not done:
                    _, done = dl.next_chunk()
            return True
        except Exception as exc:
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"    ERROR downloading {dest_path.name}: {exc}")
    return False


# ---------------------------------------------------------------------------
# Download orchestration
# ---------------------------------------------------------------------------

def download_takeout(service, folder_id: str, working_dir: Path) -> tuple[int, int, dict]:
    """
    Walk the Drive folder.
    - Media files (jpg, heic, mp4, …): record Drive URL, do NOT download.
    - JSON sidecar files: download locally for metadata parsing.
    - ZIP-only exports: warn and download ZIPs for manual extraction.

    Returns (downloaded_count, skipped_count, url_map)
    where url_map = {filename: "https://lh3.googleusercontent.com/d/FILE_ID"}
    """
    print("Listing files in Drive folder (may take a moment for large exports)…")
    all_files = list_files_recursive(service, folder_id)

    sidecar_files = [f for f in all_files if Path(f["name"]).suffix.lower() == ".json"]
    media_files   = [f for f in all_files if Path(f["name"]).suffix.lower() in MEDIA_EXTS]
    zip_files     = [f for f in all_files if is_zip(f["name"])]

    # Build URL map — photos stay in Drive, served via Google's CDN
    url_map = {f["name"]: f"https://lh3.googleusercontent.com/d/{f['id']}" for f in media_files}

    if zip_files and not sidecar_files:
        print("\nWARNING: The folder contains only ZIP archives, no extracted photos.")
        print("Google Takeout sometimes delivers exports as numbered .zip files.")
        print("Options:")
        print("  A) In Google Takeout, choose 'Add to Drive' (not 'Send download link')")
        print("     to get a proper folder tree with sidecar JSONs.")
        print("  B) Download and extract the ZIPs locally, then run:")
        print(f"     python build.py --takeout <extracted_path> --output ./output")
        return 0, 0, {}

    total = len(sidecar_files)
    print(f"Found {len(all_files)} total files:")
    print(f"  {len(media_files)} photos/videos → Drive URLs only (no download)")
    print(f"  {total} JSON sidecars → downloading for metadata")

    downloaded = skipped = errors = 0
    for i, f in enumerate(sidecar_files, 1):
        dest = working_dir / f["rel_path"]
        if dest.exists() and dest.stat().st_size > 0:
            skipped += 1
            continue

        size_kb = int(f.get("size", 0)) // 1024
        print(f"  [{i:>4}/{total}] {f['name']} ({size_kb} KB)")

        if download_file(service, f["id"], dest):
            downloaded += 1
        else:
            errors += 1

        if i % 100 == 0:
            time.sleep(1)

    return downloaded, skipped, url_map


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Download a Google Takeout export from Drive and run the ingestion pipeline."
    )
    parser.add_argument(
        "--folder-id",
        help="Google Drive folder ID (from the folder's URL). Preferred over --folder-name.",
    )
    parser.add_argument(
        "--folder-name",
        default="Takeout",
        help="Name of the Takeout folder in Drive to search for (default: 'Takeout').",
    )
    parser.add_argument(
        "--working-dir",
        default="./takeout_download",
        help="Local directory to download files into (default: ./takeout_download).",
    )
    parser.add_argument(
        "--output",
        default="./output",
        help="Output directory for data.json and photos (default: ./output).",
    )
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config.json (default: config.json).",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip the Drive download step and run the build pipeline on --working-dir as-is.",
    )
    args = parser.parse_args()

    working_dir = Path(args.working_dir)
    working_dir.mkdir(parents=True, exist_ok=True)

    # ── Download phase ───────────────────────────────────────────────────────
    if not args.skip_download:
        print("Authenticating with Google Drive…")
        creds   = get_drive_credentials()
        service = build_drive_service(creds)
        print("Authenticated.\n")

        if args.folder_id:
            folder_id = args.folder_id
            print(f"Using Drive folder ID: {folder_id}")
        else:
            print(f"Searching Drive for folder named '{args.folder_name}'…")
            folder = find_folder_by_name(service, args.folder_name)
            if not folder:
                print(f"\nERROR: No Drive folder named '{args.folder_name}' found.")
                print("Tips:")
                print("  • Pass --folder-id <id> (copy from the folder's Drive URL)")
                print("  • Or pass --folder-name with the exact folder name")
                sys.exit(1)
            folder_id = folder["id"]
            print(f"Found: '{folder['name']}' (ID: {folder_id})\n")

        dl, skip, url_map = download_takeout(service, folder_id, working_dir)
        if not url_map:
            sys.exit(1)  # ZIP-only export, can't proceed automatically
        print(f"\nDownload complete — {dl} sidecars downloaded, {skip} already present.")

        # Save URL map for build.py (and for re-runs with --skip-download)
        url_map_path = working_dir / "drive_url_map.json"
        with open(url_map_path, "w", encoding="utf-8") as f:
            import json
            json.dump(url_map, f, indent=2)
        print(f"URL map saved: {len(url_map)} photo URLs → {url_map_path}\n")
    else:
        print(f"Skipping download. Using existing files in: {working_dir}\n")
        url_map_path = working_dir / "drive_url_map.json"
        if not url_map_path.exists():
            print(f"ERROR: No URL map found at {url_map_path}.")
            print("Run without --skip-download first to build it.")
            sys.exit(1)

    # ── Build phase ──────────────────────────────────────────────────────────
    print(f"Running ingestion pipeline on {working_dir}…")
    result = subprocess.run(
        [
            sys.executable, "build.py",
            "--takeout", str(working_dir),
            "--output",  args.output,
            "--config",  args.config,
            "--url-map", str(url_map_path),
        ],
        check=False,
    )

    if result.returncode == 0:
        print(f"\nDone. Preview at: http://localhost:8080")
    else:
        print(f"\nBuild pipeline exited with code {result.returncode}.")

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
