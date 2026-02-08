import sqlite3
import time

import piexif
from PIL import Image

from picmap.app import generate_thumbnails


def _photo_metadata(photo_path):
    return {
        "source_path": str(photo_path),
        "path": f"photos/{photo_path.name}",
        "filename": photo_path.name,
    }


def test_generate_thumbnail_respects_exif_orientation(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    photo_path = tmp_path / "rotated.jpg"

    image = Image.new("RGB", (40, 20), color="red")
    exif_bytes = piexif.dump({"0th": {piexif.ImageIFD.Orientation: 6}})
    image.save(photo_path, "JPEG", exif=exif_bytes)

    photos = [_photo_metadata(photo_path)]
    generate_thumbnails(photos, str(output_dir))

    thumbnail_path = output_dir / photos[0]["thumbnail_path"]
    assert thumbnail_path.exists()

    with Image.open(thumbnail_path) as thumb:
        assert thumb.size == (20, 40)


def test_generate_thumbnails_is_incremental(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    photo_path = tmp_path / "image.jpg"

    image = Image.new("RGB", (80, 60), color="blue")
    image.save(photo_path, "JPEG")

    photos = [_photo_metadata(photo_path)]
    generate_thumbnails(photos, str(output_dir))

    thumbnail_path = output_dir / photos[0]["thumbnail_path"]
    first_mtime = thumbnail_path.stat().st_mtime

    time.sleep(1.1)
    generate_thumbnails(photos, str(output_dir))

    second_mtime = thumbnail_path.stat().st_mtime
    assert first_mtime == second_mtime

    conn = sqlite3.connect(output_dir / "picmap_cache.sqlite")
    row = conn.execute(
        "SELECT stage_thumbnail FROM thumbnails WHERE path = ?",
        (str(photo_path),),
    ).fetchone()
    conn.close()
    assert row[0] == 1
