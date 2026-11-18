"""Endpoints de la Entrega 2 sobre lo que escribe el streaming: hotspots, evolución, alertas y riesgo.

Todas las fechas salen en ISO 8601 (UTC). Sin lat/lon se devuelve todo el mapa (lo usa el dashboard de Power BI).
"""
from datetime import datetime

from flask import Blueprint, current_app, jsonify, request

from .validation import (ApiError, parse_bool, parse_category, parse_limit, parse_optional_point, parse_point,
                         parse_polygon, parse_probability, parse_radius, parse_window)

bp = Blueprint("live", __name__)


def _db():
    return current_app.config["DB"]


def clean(value):
    """Fechas a ISO 8601 y sin el _id de Mongo, de forma recursiva (jsonify de Flask las daría en formato HTTP)."""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if k != "_id"}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value


def _lonlat(geometry):
    lon, lat = geometry["coordinates"]
    return lat, lon


def _near_stage(point, radius, key):
    lat, lon = point
    return {"$geoNear": {"near": {"type": "Point", "coordinates": [lon, lat]}, "distanceField": "distance_m",
                         "maxDistance": radius, "spherical": True, "key": key}}


def _window_start(db, wanted):
    """Inicio de la ventana pedida; con 'latest', la más reciente que haya en geo_windows."""
    if wanted is not None:
        return wanted
    last = db.geo_windows.find_one({}, {"window_start": 1}, sort=[("window_start", -1)])
    return last["window_start"] if last else None


@bp.get("/live/hotspots")
def live_hotspots():
    """Celdas de geohash de una ventana de 30 días con su % negativo y si son hotspot.
    Con lat/lon/radius: solo las celdas cuyo CENTRO está a menos de `radius` metros (las celdas miden ~5 km)."""
    point, limit = parse_optional_point(request.args), parse_limit(request.args, default=200)
    radius = parse_radius(request.args, default=5000.0)
    only = parse_bool(request.args, "only_hotspots", False)
    db = _db()
    start = _window_start(db, parse_window(request.args))
    if start is None:
        return jsonify(window=None, count=0, results=[], note="todavía no hay ventanas: el streaming no ha recibido reseñas")
    q = {"window_start": start}
    if only:
        q["hotspot"] = True
    if point:
        stage = _near_stage(point, radius, "center")
        stage["$geoNear"]["query"] = q
        docs = list(db.geo_windows.aggregate([stage, {"$sort": {"delta_pp": -1}}, {"$limit": limit}]))
    else:
        docs = list(db.geo_windows.find(q).sort("delta_pp", -1).limit(limit))
    out = []
    for d in docs:
        lat, lon = _lonlat(d["center"])
        out.append(clean({k: d.get(k) for k in ("geohash", "n", "negatives", "pct_negative", "prev_pct_negative",
                                                "delta_pp", "hotspot", "window_start", "window_end", "geometry", "distance_m")}
                         | {"lat": round(lat, 5), "lon": round(lon, 5)}))
    return jsonify(window_start=clean(start), center=None if not point else {"lat": point[0], "lon": point[1]},
                   radius_m=radius if point else None, only_hotspots=only, count=len(out), results=out)


@bp.get("/live/trend")
def live_trend():
    """Evolución del % de reseñas negativas por ventana de 30 días (todas las celdas, o las del radio indicado)."""
    point, radius = parse_optional_point(request.args), parse_radius(request.args, default=5000.0)
    db = _db()
    group = {"$group": {"_id": "$window_start", "n": {"$sum": "$n"}, "negatives": {"$sum": "$negatives"},
                        "cells": {"$sum": 1}, "hotspots": {"$sum": {"$cond": ["$hotspot", 1, 0]}}}}
    pipe = ([_near_stage(point, radius, "center")] if point else []) + [group, {"$sort": {"_id": 1}}]
    rows = [{"window_start": clean(r["_id"]), "n": r["n"], "negatives": r["negatives"],
             "pct_negative": round(100.0 * r["negatives"] / r["n"], 2) if r["n"] else None,
             "cells": r["cells"], "hotspots": r["hotspots"]} for r in db.geo_windows.aggregate(pipe)]
    return jsonify(center=None if not point else {"lat": point[0], "lon": point[1]},
                   radius_m=radius if point else None, count=len(rows), results=rows)


def _alert_row(d):
    lat, lon = _lonlat(d["geometry"])
    row = {k: d.get(k) for k in ("business_id", "name", "main_category", "probability", "threshold", "as_of", "active",
                                 "created_at", "updated_at", "features", "distance_m", "dataset_is_open")}
    return clean(row | {"lat": round(lat, 6), "lon": round(lon, 6)})


@bp.route("/alerts", methods=["GET", "POST"])
def alerts():
    """Alertas de riesgo de cierre que genera el streaming. Filtros: radio (lat, lon, radius) o polígono (polygon),
    min_probability, category y active (por defecto solo las vigentes)."""
    args = request.args
    raw_poly = (request.get_json(silent=True) or {}).get("polygon") if request.method == "POST" else args.get("polygon")
    point = parse_optional_point(args)
    if point and raw_poly:
        raise ApiError("usa un radio (lat, lon, radius) o un polígono, no los dos")
    minp, limit, cat = parse_probability(args), parse_limit(args, default=100), parse_category(args)
    q = {"probability": {"$gte": minp}}
    if parse_bool(args, "active", True):
        q["active"] = True
    if cat:
        q["main_category"] = cat
    db = _db()
    if point:
        radius = parse_radius(args, default=1000.0)
        stage = _near_stage(point, radius, "geometry")
        stage["$geoNear"]["query"] = q
        docs = list(db.alerts.aggregate([stage, {"$sort": {"probability": -1}}, {"$limit": limit}]))
    else:
        if raw_poly is not None:
            q["geometry"] = {"$geoWithin": {"$geometry": parse_polygon(raw_poly)}}
        docs = list(db.alerts.find(q).sort("probability", -1).limit(limit))
    return jsonify(count=len(docs), results=[_alert_row(d) for d in docs])


@bp.get("/risk/near")
def risk_near():
    """Riesgo de cierre (probabilidad de cerrar en los próximos 12 meses) de los negocios alrededor de un punto,
    de mayor a menor riesgo. `source` indica si el puntaje es el base (a la fecha T) o ya lo actualizó el streaming."""
    lat, lon = parse_point(request.args)
    radius, limit = parse_radius(request.args, default=1000.0), parse_limit(request.args, default=50)
    minp, cat = parse_probability(request.args), parse_category(request.args)
    q = {"probability": {"$gte": minp}}
    if cat:
        q["main_category"] = cat
    stage = _near_stage((lat, lon), radius, "geometry")
    stage["$geoNear"]["query"] = q
    docs = list(_db().risk_scores.aggregate([stage, {"$sort": {"probability": -1}}, {"$limit": limit}]))
    rows = []
    for d in docs:
        la, lo = _lonlat(d["geometry"])
        rows.append(clean({k: d.get(k) for k in ("business_id", "name", "main_category", "probability", "alert", "source",
                                                 "as_of", "features", "distance_m", "model_version")}
                          | {"lat": round(la, 6), "lon": round(lo, 6)}))
    return jsonify(center={"lat": lat, "lon": lon}, radius_m=radius, count=len(rows), results=rows)
