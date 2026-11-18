import os
import socket
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify
from pymongo import MongoClient

from .validation import ApiError


STALE_SECONDS = 60


def stream_status(db):
    """Estado del job de streaming (lo escribe stream_reviews.py): retraso del consumidor y latido. Informativo: no cambia el
    código HTTP de /health, porque el flujo puede estar legítimamente detenido (p. ej. mientras se restauran los datos)."""
    try:
        doc = db.stream_status.find_one({"_id": "stream"})
    except Exception as exc:  # noqa: BLE001
        return {"status": f"down: {exc.__class__.__name__}"}
    if not isinstance(doc, dict) or not doc.get("updated_at"):
        return {"status": "not-started"}
    age = (datetime.now(timezone.utc) - doc["updated_at"].replace(tzinfo=timezone.utc)).total_seconds()
    return {"status": "up" if age <= STALE_SECONDS else "stale", "consumer_lag": doc.get("consumer_lag"),
            "last_batch": doc.get("batch_id"), "seconds_since_last_progress": round(age),
            "model_version": doc.get("model_version"), "cutoff_t": doc.get("cutoff_t")}


def _probe(fn):
    try:
        fn()
        return "up"
    except Exception as exc:  # noqa: BLE001
        return f"down: {exc.__class__.__name__}"


def create_app(mongo_client=None):
    app = Flask(__name__)
    client = mongo_client or MongoClient(os.environ["MONGO_URI"], serverSelectionTimeoutMS=3000)
    app.config["DB"] = client[os.environ.get("MONGO_DB", "lifemap")]

    from .routes_geo import bp as geo_bp
    app.register_blueprint(geo_bp)
    from .routes_predict import bp as predict_bp
    app.register_blueprint(predict_bp)
    from .routes_live import bp as live_bp
    app.register_blueprint(live_bp)
    from .routes_survival import bp as survival_bp
    app.register_blueprint(survival_bp)
    from .ui import ui as ui_bp
    app.register_blueprint(ui_bp)

    @app.errorhandler(ApiError)
    def bad_request(e):
        return jsonify(error=e.message), e.status

    def http_ok(url):
        requests.get(url, timeout=3).raise_for_status()

    def tcp_ok(hostport):
        host, port = hostport.rsplit(":", 1)
        socket.create_connection((host, int(port)), timeout=3).close()

    @app.get("/health")
    def health():
        spark = os.environ.get("SPARK_MASTER_UI")
        dask = os.environ.get("DASK_SCHEDULER_UI")
        kafka = os.environ.get("KAFKA_BOOTSTRAP")
        services = {
            "api": "up",
            "mongo": _probe(lambda: app.config["DB"].client.admin.command("ping")),
            "spark": _probe(lambda: http_ok(f"{spark}/json/")) if spark else "not-configured",
            "dask": _probe(lambda: http_ok(f"{dask}/health")) if dask else "not-configured",
            "kafka": _probe(lambda: tcp_ok(kafka)) if kafka else "not-configured",
            # E2: retraso del consumidor
        }
        ok = all(v in ("up", "not-configured") for v in services.values())
        return jsonify(status="ok" if ok else "degraded", services=services, streaming=stream_status(app.config["DB"]),
                       commit=os.environ.get("GIT_COMMIT", "unknown")), (200 if ok else 503)

    return app
