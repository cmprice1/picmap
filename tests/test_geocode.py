import sqlite3

from picmap import geocode


def test_normalize_coordinates_precision():
    lat, lon = geocode.normalize_coordinates(37.7749295, -122.4194155, precision=5)
    assert lat == 37.77493
    assert lon == -122.41942


def test_cache_hit_miss(tmp_path):
    db_path = tmp_path / "cache.sqlite"
    conn = sqlite3.connect(db_path)
    geocode.init_db(conn)

    calls = []

    def fake_geocode(lat, lon):
        calls.append((lat, lon))
        return "Testville"

    location, normalized, hit = geocode.resolve_location(conn, 10.123456, 20.654321, fake_geocode)
    assert location == "Testville"
    assert normalized == geocode.normalize_coordinates(10.123456, 20.654321)
    assert hit is False
    assert calls == [(10.123456, 20.654321)]

    location, normalized, hit = geocode.resolve_location(conn, 10.123456, 20.654321, fake_geocode)
    assert location == "Testville"
    assert normalized == geocode.normalize_coordinates(10.123456, 20.654321)
    assert hit is True
    assert calls == [(10.123456, 20.654321)]

    conn.close()
