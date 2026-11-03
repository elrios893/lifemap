from unittest.mock import MagicMock

from app import create_app


def test_health_reports_services_and_commit(monkeypatch):
    monkeypatch.setenv("GIT_COMMIT", "abc123")
    monkeypatch.delenv("SPARK_MASTER_UI", raising=False)
    monkeypatch.delenv("DASK_SCHEDULER_UI", raising=False)
    client = MagicMock()
    app = create_app(mongo_client=client)
    r = app.test_client().get("/health")
    body = r.get_json()
    assert r.status_code == 200
    assert body["commit"] == "abc123"
    assert body["services"]["mongo"] == "up"
