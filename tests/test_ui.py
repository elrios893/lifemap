from unittest.mock import MagicMock

from app import create_app


def test_ui_pages_are_served():
    c = create_app(mongo_client=MagicMock()).test_client()
    r = c.get("/")
    assert r.status_code == 200 and b"LifeMap" in r.data
    assert c.get("/static/app.js").status_code == 200
    assert c.get("/static/vendor/leaflet.js").status_code == 200


def test_entregauno():
    c = create_app(mongo_client=MagicMock()).test_client()
    r = c.get("/entregauno")
    assert r.status_code == 200 and r.get_json()["estado"] == "terminada"
