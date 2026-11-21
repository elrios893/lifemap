"""Curvas de supervivencia de Kaplan-Meier (las calcula ingest/survival.py y quedan en la colección `survival`)."""
from flask import Blueprint, current_app, jsonify, request

from .routes_live import clean
from .validation import ApiError, parse_limit

bp = Blueprint("survival", __name__)

_NOTE = ("Kaplan-Meier con negocios abiertos como censurados y entrada tardía excluida. status='insufficient' = el grupo "
         "no alcanza el mínimo de negocios y cierres; no se estima la curva. median_days=null = la curva no baja de 0,5.")


def _db():
    return current_app.config["DB"]


def _summary(d):
    keys = ("n", "events", "censored", "late_entry_excluded", "status", "median_days", "median_years", "median_days_with_late")
    return {k: d.get(k) for k in keys}


def _not_found(db, what, field, dimension):
    options = sorted(x[field] for x in db.survival.find({"dimension": dimension, "status": "ok"}, {field: 1}))[:30]
    raise ApiError(f"no hay curva para {what}; con curva disponible: {options}", 404)


@bp.get("/survival")
def survival_index():
    """Lista los grupos con su resumen (sin curvas) para saber cuáles consultar: ?dimension=category|zone|category_zone,
    ?status=ok|insufficient|all (por defecto solo los que tienen curva), de mayor a menor número de negocios."""
    dimension, status = request.args.get("dimension", "category"), request.args.get("status", "ok")
    if dimension not in ("category", "zone", "category_zone"):
        raise ApiError("'dimension' debe ser 'category', 'zone' o 'category_zone'")
    if status not in ("ok", "insufficient", "all"):
        raise ApiError("'status' debe ser 'ok', 'insufficient' o 'all'")
    q = {"dimension": dimension} | ({} if status == "all" else {"status": status})
    docs = list(_db().survival.find(q).sort("n", -1).limit(parse_limit(request.args, default=50)))
    return jsonify(dimension=dimension, status=status, count=len(docs), note=_NOTE,
                   results=[clean({"category": d.get("category"), "zone": d.get("zone")} | _summary(d)) for d in docs])


@bp.get("/survival/<path:category>")
def survival_category(category):
    """Curva de una categoría principal. ?zone=NOMBRE la restringe a una zona (solo categorías con más negocios);
    ?compare=zones devuelve la mediana y el tamaño de la categoría en cada zona, sin las curvas."""
    db, zone, compare = _db(), (request.args.get("zone") or "").strip(), request.args.get("compare")
    if compare not in (None, "", "zones"):
        raise ApiError("'compare' solo admite 'zones'")
    if zone and compare:
        raise ApiError("usa 'zone' o 'compare', no los dos")
    if compare == "zones":
        docs = list(db.survival.find({"dimension": "category_zone", "category": category}).sort("zone", 1))
        if not docs:
            raise ApiError(f"no hay comparación por zona para '{category}' (solo las categorías más grandes la tienen)", 404)
        return jsonify(category=category, note=_NOTE,
                       by_zone=[clean({"zone": d["zone"]} | _summary(d)) for d in docs])
    doc = (db.survival.find_one({"_id": f"category_zone|{category}|{zone}"}) if zone
           else db.survival.find_one({"_id": f"category|{category}"}))
    if not doc:
        _not_found(db, f"'{category}'" + (f" en la zona '{zone}'" if zone else ""), "category", "category")
    return jsonify(clean({"category": category, "zone": zone or None, "note": _NOTE, **_summary(doc),
                          "min_businesses": doc["min_businesses"], "min_events": doc["min_events"],
                          "min_at_risk": doc.get("min_at_risk"), "curve": doc["curve"], "computed_at": doc["computed_at"]}))


@bp.get("/survival/zone/<path:zone>")
def survival_zone(zone):
    """Curva de una zona (todas las categorías). Las zonas se definen como polígonos y se consultan con $geoWithin."""
    db = _db()
    doc = db.survival.find_one({"_id": f"zone|{zone}"})
    if not doc:
        _not_found(db, f"la zona '{zone}'", "zone", "zone")
    poly = (db.zones.find_one({"_id": zone}) or {}).get("geometry")
    return jsonify(clean({"zone": zone, "note": _NOTE, **_summary(doc), "geometry": poly, "curve": doc["curve"],
                          "computed_at": doc["computed_at"]}))
