"""Validación de parámetros de entrada. Lanza ApiError (400) con un mensaje claro."""
import json


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


def _num(args, name, lo, hi, default=None):
    raw = args.get(name)
    if raw in (None, ""):
        if default is None:
            raise ApiError(f"falta el parámetro '{name}'")
        return default
    try:
        v = float(raw)
    except (TypeError, ValueError):
        raise ApiError(f"'{name}' debe ser numérico") from None
    if v != v or not (lo <= v <= hi):
        raise ApiError(f"'{name}' debe estar entre {lo} y {hi}")
    return v


def parse_point(args):
    return _num(args, "lat", -90, 90), _num(args, "lon", -180, 180)


def parse_radius(args, default=1000.0, max_m=50_000.0):
    return _num(args, "radius", 1, max_m, default)


def parse_limit(args, default=50, max_n=500):
    return int(_num(args, "limit", 1, max_n, default))


def parse_min_days(args, default=0.0):
    return _num(args, "min_days", 0, 1e12, default)


def parse_polygon(obj):
    """Acepta un GeoJSON Polygon (dict o string JSON). Verifica anillo cerrado y coordenadas en rango."""
    if isinstance(obj, str):
        try:
            obj = json.loads(obj)
        except ValueError:
            raise ApiError("el polígono no es JSON válido") from None
    if not isinstance(obj, dict) or obj.get("type") != "Polygon" or not isinstance(obj.get("coordinates"), list):
        raise ApiError("se espera un GeoJSON de tipo Polygon con 'coordinates'")
    ring = obj["coordinates"][0] if obj["coordinates"] else []
    if len(ring) < 4:
        raise ApiError("el anillo del polígono necesita al menos 4 puntos (el último igual al primero)")
    for p in ring:
        if (not isinstance(p, list) or len(p) != 2 or not all(isinstance(c, (int, float)) for c in p)
                or not (-180 <= p[0] <= 180 and -90 <= p[1] <= 90)):
            raise ApiError("coordenadas fuera de rango o mal formadas; el orden es [lon, lat]")
    if ring[0] != ring[-1]:
        raise ApiError("el anillo del polígono debe cerrarse (primer punto igual al último)")
    return obj


def parse_category(args):
    c = (args.get("category") or "").strip()
    if len(c) > 80:
        raise ApiError("'category' demasiado larga")
    return c or None
