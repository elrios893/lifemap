import os

import requests
from flask import Flask, jsonify
from pymongo import MongoClient

from .validation import ApiError


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

    @app.errorhandler(ApiError)
    def bad_request(e):
        return jsonify(error=e.message), e.status

    def http_ok(url):
        requests.get(url, timeout=3).raise_for_status()

    @app.get("/health")
    def health():
        spark = os.environ.get("SPARK_MASTER_UI")
        dask = os.environ.get("DASK_SCHEDULER_UI")
        services = {
            "api": "up",
            "mongo": _probe(lambda: app.config["DB"].client.admin.command("ping")),
            "spark": _probe(lambda: http_ok(f"{spark}/json/")) if spark else "not-configured",
            "dask": _probe(lambda: http_ok(f"{dask}/health")) if dask else "not-configured",
            # E2: "kafka" y retraso del consumidor
        }
        ok = all(v in ("up", "not-configured") for v in services.values())
        return jsonify(status="ok" if ok else "degraded", services=services,
                       commit=os.environ.get("GIT_COMMIT", "unknown")), (200 if ok else 503)

    return app
