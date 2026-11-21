import sys
from pathlib import Path
from unittest.mock import MagicMock

import requests

from app import create_app

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))
import server  # noqa: E402


def client():
    return create_app(mongo_client=MagicMock()).test_client()


def test_replay_rejects_bad_speed():
    for bad in ("rapido", -1, 61):
        r = client().post("/replay", json={"seconds_per_month": bad})
        assert r.status_code == 400, bad


def test_replay_forwards_to_controller(monkeypatch):
    sent = {}

    def fake_post(url, json=None, timeout=None):
        sent.update(url=url, json=json)
        return MagicMock(status_code=202, json=lambda: {"phase": "reiniciando"})

    monkeypatch.setattr(requests, "post", fake_post)
    r = client().post("/replay", json={"seconds_per_month": 5})
    assert r.status_code == 202 and r.get_json()["phase"] == "reiniciando"
    assert sent["json"] == {"seconds_per_month": 5.0} and sent["url"].endswith("/replay")


def test_replay_without_body_uses_default_speed(monkeypatch):
    monkeypatch.setattr(requests, "post", lambda url, json=None, timeout=None: MagicMock(status_code=202, json=lambda: json))
    assert client().post("/replay").get_json() == {"seconds_per_month": 10.0}


def test_replay_reports_controller_down(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "get", boom)
    r = client().get("/replay")
    assert r.status_code == 503 and "controller" in r.get_json()["error"]


def test_controller_validates_and_refuses_second_run(monkeypatch):
    monkeypatch.setattr(server, "replay", lambda speed: None)   # no lanza Docker en las pruebas
    server.STATE.update(phase="idle", started_at=None, finished_at=None)
    assert server.start({"seconds_per_month": 99})[0] == 400
    code, body = server.start({"seconds_per_month": 2})
    assert code == 202 and body["seconds_per_month"] == 2.0
    assert server.start({})[0] == 409            # la fase sigue "reiniciando" (replay simulado no la cambia)
    server.STATE["phase"] = "idle"
