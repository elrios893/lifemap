from flask import Blueprint, current_app, jsonify, request

from .rates import closure_rate
from .validation import (ApiError, parse_category, parse_limit, parse_min_days, parse_point, parse_polygon,
                         parse_radius)

bp = Blueprint("geo", __name__)
_PROJ = {"name": 1, "city": 1, "stars": 1, "review_count": 1, "is_open": 1, "main_category": 1,
         "geohash": 1, "location": 1, "life": 1}


def _db():
    return current_app.config["DB"]


def _feature(d):
    props = {k: v for k, v in d.items() if k not in ("location", "_id")}
    props["id"] = d["_id"]
    return {"type": "Feature", "geometry": d["location"], "properties": props}


def _collection(docs):
    return jsonify(type="FeatureCollection", count=len(docs), features=[_feature(d) for d in docs])


@bp.get("/businesses/near")
def businesses_near():
    lat, lon = parse_point(request.args)
    radius, limit, cat = parse_radius(request.args), parse_limit(request.args), parse_category(request.args)
    q = {"location": {"$near": {"$geometry": {"type": "Point", "coordinates": [lon, lat]}, "$maxDistance": radius}}}
    if cat:
        q["main_category"] = cat
    return _collection(list(_db().businesses.find(q, _PROJ).limit(limit)))  # $near ya ordena por distancia


@bp.route("/businesses/within", methods=["GET", "POST"])
def businesses_within():
    if request.method == "POST":
        raw = (request.get_json(silent=True) or {}).get("polygon")
    else:
        raw = request.args.get("polygon")
    poly = parse_polygon(raw if raw is not None else "")
    limit, cat = parse_limit(request.args), parse_category(request.args)
    q = {"location": {"$geoWithin": {"$geometry": poly}}}
    if cat:
        q["main_category"] = cat
    return _collection(list(_db().businesses.find(q, _PROJ).limit(limit)))


@bp.get("/stats/closure")
def stats_closure():
    """Tasas de cierre anualizadas por categoría o geohash (colecciones que escribe el job MapReduce de Spark).
    min_days descarta grupos con pocos días-negocio para no concluir sobre grupos pequeños."""
    level = request.args.get("by", "category")
    if level not in ("category", "geohash"):
        raise ApiError("'by' debe ser 'category' o 'geohash'")
    min_days, limit = parse_min_days(request.args, default=0.0), parse_limit(request.args, default=50)
    order = request.args.get("order", "desc")
    if order not in ("asc", "desc"):
        raise ApiError("'order' debe ser 'asc' o 'desc'")
    q = {"level": level, "business_days": {"$gte": min_days}}
    docs = list(_db().closure_stats.find(q, {"_id": 0}).sort("closure_rate_pct", 1 if order == "asc" else -1).limit(limit))
    return jsonify(by=level, min_days=min_days, count=len(docs), results=docs)


@bp.get("/zones/summary")
def zones_summary():
    """Resumen alrededor de un punto con $geoNear: negocios, estrellas, sentimiento y tasa de cierre."""
    lat, lon = parse_point(request.args)
    radius, min_days = parse_radius(request.args, default=1000.0), parse_min_days(request.args)
    pipe = [
        {"$geoNear": {"near": {"type": "Point", "coordinates": [lon, lat]}, "distanceField": "dist_m",
                      "maxDistance": radius, "spherical": True}},
        {"$group": {"_id": None, "businesses": {"$sum": 1}, "avg_stars": {"$avg": "$stars"},
                    "closed": {"$sum": {"$cond": [{"$eq": ["$is_open", 0]}, 1, 0]}},
                    "business_days": {"$sum": {"$ifNull": ["$life.business_days", 0]}},
                    "closures": {"$sum": {"$ifNull": ["$life.closed", 0]}},
                    "reviews": {"$sum": {"$ifNull": ["$sent.n", 0]}},
                    "negative": {"$sum": {"$ifNull": ["$sent.negative", 0]}}}},
    ]
    r = next(iter(_db().businesses.aggregate(pipe)), None)
    out = {"center": {"lat": lat, "lon": lon}, "radius_m": radius, "businesses": 0}
    if r:
        enough = r["business_days"] > 0 and r["business_days"] >= min_days
        out.update(
            businesses=r["businesses"], avg_stars=round(r["avg_stars"], 3), closed=r["closed"],
            reviews=r["reviews"], business_days=r["business_days"], min_days=min_days,
            pct_negative=round(100 * r["negative"] / r["reviews"], 2) if r["reviews"] else None,
            closure_rate_pct=round(closure_rate(r["closures"], r["business_days"]), 3) if enough else None)
    return jsonify(out)
