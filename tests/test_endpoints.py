from unittest.mock import MagicMock

from app import create_app


def _client():
    return create_app(mongo_client=MagicMock()).test_client()


def test_near_rejects_bad_input():
    r = _client().get("/businesses/near?lat=200&lon=0")
    assert r.status_code == 400 and "lat" in r.get_json()["error"]


def test_within_rejects_non_polygon():
    r = _client().post("/businesses/within", json={"polygon": {"type": "Point", "coordinates": [0, 0]}})
    assert r.status_code == 400


def test_summary_requires_point():
    assert _client().get("/zones/summary").status_code == 400
