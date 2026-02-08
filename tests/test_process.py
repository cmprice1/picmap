import sqlite3

from picmap import process


def test_geocode_cache_hits(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    photo = input_dir / "image.jpg"
    photo.write_text("fake")

    calls = []

    def fake_geocode(lat, lon):
        calls.append((lat, lon))
        return {
            "response_json": "{}",
            "city": "Testville",
            "state": "Test State",
            "country": "Testland",
            "display_name": "Testville, Testland",
        }

    def fake_extract(_path):
        return (10.123456, 20.654321)

    stats = process.process_photos(
        str(input_dir),
        str(db_path),
        geocode_func=fake_geocode,
        extract_coords_func=fake_extract,
    )
    assert stats == {"cache_hits": 0, "cache_misses": 1}
    assert calls == [(10.123456, 20.654321)]

    stats = process.process_photos(
        str(input_dir),
        str(db_path),
        geocode_func=fake_geocode,
        extract_coords_func=fake_extract,
    )
    assert stats == {"cache_hits": 1, "cache_misses": 0}
    assert calls == [(10.123456, 20.654321)]

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT COUNT(*) FROM geocode_cache"
    ).fetchone()
    conn.close()
    assert row[0] == 1


def test_rounding_and_precision(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    photo = input_dir / "image.jpg"
    photo.write_text("fake")

    def fake_geocode(_lat, _lon):
        return {
            "response_json": "{}",
            "city": None,
            "state": None,
            "country": None,
            "display_name": None,
        }

    def fake_extract(_path):
        return (12.3456789, -98.7654321)

    process.process_photos(
        str(input_dir),
        str(db_path),
        geocode_func=fake_geocode,
        extract_coords_func=fake_extract,
    )

    conn = sqlite3.connect(db_path)
    photo_row = conn.execute(
        "SELECT lat, lon FROM photos"
    ).fetchone()
    cache_row = conn.execute(
        "SELECT lat_rounded, lon_rounded FROM geocode_cache"
    ).fetchone()
    conn.close()

    assert photo_row == (12.3456789, -98.7654321)
    assert cache_row == (round(12.3456789, 3), round(-98.7654321, 3))


def test_failed_geocode_not_cached(tmp_path):
    """Test that failed geocode lookups (None response) are not cached and can be retried."""
    db_path = tmp_path / "cache.sqlite"
    input_dir = tmp_path / "photos"
    input_dir.mkdir()
    photo = input_dir / "image.jpg"
    photo.write_text("fake")

    calls = []
    fail_first_time = True

    def fake_geocode_with_failure(lat, lon):
        nonlocal fail_first_time
        calls.append((lat, lon))
        if fail_first_time:
            fail_first_time = False
            return None  # Simulate transient failure (network error, rate limit, etc.)
        return {
            "response_json": "{}",
            "city": "Testville",
            "state": "Test State",
            "country": "Testland",
            "display_name": "Testville, Testland",
        }

    def fake_extract(_path):
        return (10.123456, 20.654321)

    # First run: geocode fails, should not be cached
    stats = process.process_photos(
        str(input_dir),
        str(db_path),
        geocode_func=fake_geocode_with_failure,
        extract_coords_func=fake_extract,
    )
    assert stats == {"cache_hits": 0, "cache_misses": 1}
    assert len(calls) == 1

    # Verify that nothing was cached and photo is not marked as geocoded
    conn = sqlite3.connect(db_path)
    cache_row = conn.execute(
        "SELECT COUNT(*) FROM geocode_cache"
    ).fetchone()
    photo_row = conn.execute(
        "SELECT stage_geocoded FROM photos WHERE path = ?",
        (str(photo),)
    ).fetchone()
    conn.close()
    
    assert cache_row[0] == 0  # No cache entry
    assert photo_row[0] == 0  # Photo not marked as geocoded

    # Second run: geocode succeeds, should be cached now
    stats = process.process_photos(
        str(input_dir),
        str(db_path),
        geocode_func=fake_geocode_with_failure,
        extract_coords_func=fake_extract,
    )
    assert stats == {"cache_hits": 0, "cache_misses": 1}
    assert len(calls) == 2  # Geocode was called again

    # Verify that now it is cached and photo is marked as geocoded
    conn = sqlite3.connect(db_path)
    cache_row = conn.execute(
        "SELECT COUNT(*) FROM geocode_cache"
    ).fetchone()
    photo_row = conn.execute(
        "SELECT stage_geocoded FROM photos WHERE path = ?",
        (str(photo),)
    ).fetchone()
    conn.close()
    
    assert cache_row[0] == 1  # Cache entry exists
    assert photo_row[0] == 1  # Photo marked as geocoded

    # Third run: should use cache, no new geocode call
    stats = process.process_photos(
        str(input_dir),
        str(db_path),
        geocode_func=fake_geocode_with_failure,
        extract_coords_func=fake_extract,
    )
    assert stats == {"cache_hits": 1, "cache_misses": 0}
    assert len(calls) == 2  # No new geocode call
