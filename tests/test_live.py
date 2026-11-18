from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from app import create_app

T0 = datetime(2021, 2, 18)


def _app(db):
    client = MagicMock()
    client.__getitem__.return_value = db
    return create_app(mongo_client=client).test_client()


def _cell(**kw):
    base = {"_id": "dr4e8|2021-02-18", "geohash": "dr4e8", "n": 30, "negatives": 12, "pct_negative": 40.0,
            "prev_pct_negative": 20.0, "delta_pp": 20.0, "hotspot": True, "window_start": T0,
            "window_end": T0 + timedelta(days=30), "center": {"type": "Point", "coordinates": [-75.16, 39.95]},
            "geometry": {"type": "Polygon", "coordinates": []}}
    return base | kw


def test_hotspots_shape_and_iso_dates():
    db = MagicMock()
    db.geo_windows.find_one.return_value = {"window_start": T0}
    db.geo_windows.find.return_value.sort.return_value.limit.return_value = [_cell()]
    body = _app(db).get("/live/hotspots").get_json()
    row = body["results"][0]
    assert body["window_start"] == "2021-02-18T00:00:00Z" and body["count"] == 1
    assert row["hotspot"] is True and row["lat"] == 39.95 and row["lon"] == -75.16 and "_id" not in row


def test_hotspots_with_radius_uses_geonear_on_cell_center():
    db = MagicMock()
    db.geo_windows.find_one.return_value = {"window_start": T0}
    db.geo_windows.aggregate.return_value = [_cell(distance_m=812.5)]
    body = _app(db).get("/live/hotspots?lat=39.95&lon=-75.16&radius=3000&only_hotspots=true").get_json()
    stage = db.geo_windows.aggregate.call_args[0][0][0]["$geoNear"]
    assert stage["key"] == "center" and stage["maxDistance"] == 3000.0 and stage["query"]["hotspot"] is True
    assert body["results"][0]["distance_m"] == 812.5


def test_hotspots_without_windows_explains_why():
    db = MagicMock()
    db.geo_windows.find_one.return_value = None
    body = _app(db).get("/live/hotspots").get_json()
    assert body["count"] == 0 and "streaming" in body["note"]


def test_hotspots_validation():
    c = _app(MagicMock())
    assert c.get("/live/hotspots?window=ayer").status_code == 400
    assert c.get("/live/hotspots?lat=39.9").status_code == 400          # solo uno de los dos
    assert c.get("/live/hotspots?lat=39.9&lon=-75&radius=0").status_code == 400


def test_trend_computes_pct_negative():
    db = MagicMock()
    db.geo_windows.aggregate.return_value = [{"_id": T0, "n": 200, "negatives": 50, "cells": 12, "hotspots": 2}]
    row = _app(db).get("/live/trend").get_json()["results"][0]
    assert row["pct_negative"] == 25.0 and row["hotspots"] == 2 and row["window_start"] == "2021-02-18T00:00:00Z"


def _alert(**kw):
    return {"_id": "b1", "business_id": "b1", "name": "Café", "main_category": "Food", "probability": 0.81, "threshold": 0.62,
            "as_of": T0, "active": True, "features": {"n_reviews": 9}, "geometry": {"type": "Point", "coordinates": [-75.1, 39.9]}} | kw


def test_alerts_by_polygon_and_radius_are_exclusive():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    r = _app(MagicMock()).post("/alerts?lat=39.9&lon=-75.1", json={"polygon": poly})
    assert r.status_code == 400 and "no los dos" in r.get_json()["error"]


def test_alerts_polygon_filter_and_defaults():
    db = MagicMock()
    db.alerts.find.return_value.sort.return_value.limit.return_value = [_alert()]
    poly = {"type": "Polygon", "coordinates": [[[-76, 39], [-75, 39], [-75, 40], [-76, 39]]]}
    body = _app(db).post("/alerts?min_probability=0.7", json={"polygon": poly}).get_json()
    q = db.alerts.find.call_args[0][0]
    assert q["active"] is True and q["probability"] == {"$gte": 0.7} and "$geoWithin" in q["geometry"]
    assert body["results"][0]["lat"] == 39.9 and body["results"][0]["probability"] == 0.81


def test_alerts_radius_uses_geonear():
    db = MagicMock()
    db.alerts.aggregate.return_value = [_alert(distance_m=120.0)]
    body = _app(db).get("/alerts?lat=39.9&lon=-75.1&radius=500").get_json()
    assert db.alerts.aggregate.call_args[0][0][0]["$geoNear"]["maxDistance"] == 500.0
    assert body["count"] == 1


def test_risk_near_requires_point_and_sorts_by_probability():
    db = MagicMock()
    c = _app(db)
    assert c.get("/risk/near").status_code == 400
    db.risk_scores.aggregate.return_value = [_alert(alert=True, source="stream", model_version="abc")]
    body = c.get("/risk/near?lat=39.9&lon=-75.1&radius=800").get_json()
    pipe = db.risk_scores.aggregate.call_args[0][0]
    assert pipe[1] == {"$sort": {"probability": -1}} and body["results"][0]["source"] == "stream"


def _surv(**kw):
    return {"n": 470, "events": 179, "censored": 291, "late_entry_excluded": 6, "status": "ok", "median_days": 4458,
            "median_years": 12.21, "median_days_with_late": 4270, "min_businesses": 100, "min_events": 20, "min_at_risk": 10,
            "curve": [{"t": 0, "s": 1.0, "lo": 1.0, "hi": 1.0, "at_risk": 470}], "computed_at": T0} | kw


def test_survival_category():
    db = MagicMock()
    db.survival.find_one.return_value = _surv()
    r = _app(db).get("/survival/Beauty%20%26%20Spas")
    assert db.survival.find_one.call_args[0][0] == {"_id": "category|Beauty & Spas"}
    body = r.get_json()
    assert body["median_years"] == 12.21 and body["curve"][0]["at_risk"] == 470 and body["late_entry_excluded"] == 6


def test_survival_unknown_category_lists_available():
    db = MagicMock()
    db.survival.find_one.return_value = None
    db.survival.find.return_value = [{"category": "Restaurants"}, {"category": "Food"}]
    r = _app(db).get("/survival/Inexistente")
    assert r.status_code == 404 and "Restaurants" in r.get_json()["error"]


def test_survival_zone_and_compare():
    db = MagicMock()
    db.survival.find_one.return_value = _surv()
    c = _app(db)
    c.get("/survival/Restaurants?zone=Center%20City")
    assert db.survival.find_one.call_args[0][0] == {"_id": "category_zone|Restaurants|Center City"}
    db.survival.find.return_value.sort.return_value = [_surv(zone="Center City", category="Restaurants")]
    body = c.get("/survival/Restaurants?compare=zones").get_json()
    assert body["by_zone"][0]["zone"] == "Center City" and "curve" not in body["by_zone"][0]
    assert c.get("/survival/Restaurants?compare=otra").status_code == 400
    assert c.get("/survival/Restaurants?zone=X&compare=zones").status_code == 400


def test_survival_by_zone_route_is_not_swallowed_by_category_route():
    db = MagicMock()
    db.survival.find_one.return_value = _surv()
    _app(db).get("/survival/zone/Center%20City")
    assert db.survival.find_one.call_args[0][0] == {"_id": "zone|Center City"}


def test_health_reports_stream_lag_without_changing_status():
    db = MagicMock()
    now = datetime.now(timezone.utc)
    db.stream_status.find_one.return_value = {"_id": "stream", "consumer_lag": 42, "batch_id": 7, "updated_at": now - timedelta(minutes=30),
                                              "heartbeat_at": now, "queries": {"reviews": True, "windows": True}, "model_version": "abc"}
    r = _app(db).get("/health")
    body = r.get_json()
    # sin datos hace 30 min pero con latido reciente: el servicio está vivo ('up'), no 'stale'
    assert r.status_code == 200 and body["streaming"]["consumer_lag"] == 42 and body["streaming"]["status"] == "up"
    assert body["streaming"]["seconds_since_last_batch"] >= 1800
    db.stream_status.find_one.return_value = {"_id": "stream", "heartbeat_at": now - timedelta(minutes=5), "queries": {"reviews": True}}
    assert _app(db).get("/health").get_json()["streaming"]["status"] == "stale"
    db.stream_status.find_one.return_value = {"_id": "stream", "heartbeat_at": now, "queries": {"reviews": True, "windows": False}}
    assert _app(db).get("/health").get_json()["streaming"]["status"] == "degraded"
    db.stream_status.find_one.return_value = None
    assert _app(db).get("/health").get_json()["streaming"]["status"] == "not-started"
