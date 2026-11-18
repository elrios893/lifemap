"""Curvas de supervivencia de Kaplan-Meier por categoría principal, por zona y por categoría x zona (Entrega 2).

Tiempo = business_days (días de la primera a la última reseña, definición del enunciado). Evento = cierre (is_open = 0).
Los negocios abiertos son CENSURADOS: salen del riesgo en su duración observada, no son cierres y no se descartan.

Entrada tardía: un negocio con life.late_entry = 1 ya existía antes de empezar a observarse, así que contar su vida desde la
primera reseña la subestima (su edad real es mayor y desconocida). La curva principal los EXCLUYE; se guarda además la
mediana incluyéndolos (`median_days_with_late`) para mostrar cuánto cambia.

Grupos pequeños: si un grupo no tiene al menos MIN_BUSINESSES negocios y MIN_EVENTS cierres no se estima la curva
(status = "insufficient"): con pocos cierres la banda de confianza es tan ancha que no permite concluir nada.

Zonas: polígonos (rectángulos aproximados de Filadelfia y su periferia, definidos por el equipo). La pertenencia se
consulta en MongoDB con $geoWithin sobre el índice 2dsphere.

Cola de la curva: se corta donde quedan menos de MIN_AT_RISK negocios en riesgo (ahí la estimación no es confiable).

Salida: colecciones `survival` (una curva por grupo) y `zones` (polígono y conteo de cada zona).
Uso: python survival.py        Variables: MIN_BUSINESSES (100), MIN_EVENTS (20), MIN_AT_RISK (10), CURVE_STEP_DAYS (30), TOP_CATEGORIES_BY_ZONE (5)
"""
import os
from collections import defaultdict
from datetime import datetime, timezone

from km import curve, kaplan_meier, median_survival
from load_mongo import client as mongo_db

MIN_BUSINESSES = int(os.environ.get("MIN_BUSINESSES", "100"))
MIN_EVENTS = int(os.environ.get("MIN_EVENTS", "20"))
STEP = int(os.environ.get("CURVE_STEP_DAYS", "30"))
MIN_AT_RISK = int(os.environ.get("MIN_AT_RISK", "10"))
TOP_CATS = int(os.environ.get("TOP_CATEGORIES_BY_ZONE", "5"))

# nombre: (lat_min, lat_max, lon_min, lon_max). No se solapan entre sí.
ZONES = {
    "Center City": (39.935, 39.963, -75.185, -75.135),
    "West Philadelphia": (39.900, 40.000, -75.270, -75.185),
    "South Philadelphia": (39.890, 39.935, -75.185, -75.100),
    "North Philadelphia y Fishtown": (39.963, 40.000, -75.185, -74.950),
    "Northwest (Manayunk, Germantown)": (40.000, 40.085, -75.270, -75.120),
    "Northeast Philadelphia": (40.000, 40.150, -75.120, -74.950),
    "Suburbios del oeste (Main Line, Delaware)": (39.800, 40.150, -75.800, -75.270),
    "Suburbios del norte (Montgomery, Bucks)": (40.150, 40.450, -75.500, -74.780),
}


def polygon(box):
    la0, la1, lo0, lo1 = box
    return {"type": "Polygon", "coordinates": [[[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]]]}


def estimate(rows):
    """rows: [(business_days, closed, late_entry)] -> resumen + curva del grupo."""
    main = [(d, c) for d, c, late in rows if not late]
    n_late = len(rows) - len(main)
    events = sum(c for _, c in main)
    out = {"n_total": len(rows), "n": len(main), "events": events, "censored": len(main) - events,
           "late_entry_excluded": n_late, "min_businesses": MIN_BUSINESSES, "min_events": MIN_EVENTS}
    if len(main) < MIN_BUSINESSES or events < MIN_EVENTS:
        return {**out, "status": "insufficient", "median_days": None, "median_days_with_late": None, "curve": []}
    dur, evt = [d for d, _ in main], [c for _, c in main]
    table = kaplan_meier(dur, evt)
    med = median_survival(table)
    all_tab = kaplan_meier([d for d, _, _ in rows], [c for _, c, _ in rows])
    med_late = median_survival(all_tab)
    return {**out, "status": "ok", "median_days": med, "median_years": round(med / 365.0, 2) if med is not None else None,
            "median_days_with_late": med_late, "min_at_risk": MIN_AT_RISK,
            "curve": [p for p in curve(table, dur, step=STEP) if p["at_risk"] >= MIN_AT_RISK]}


def main():
    db = mongo_db()
    cols = {"_id": 1, "main_category": 1, "life.business_days": 1, "life.closed": 1, "life.late_entry": 1}
    biz = {d["_id"]: (d.get("main_category") or "(sin categoría)", int(d["life"]["business_days"]),
                      int(d["life"]["closed"]), int(d["life"]["late_entry"]))
           for d in db.businesses.find({"life": {"$exists": True}}, cols)}
    print(f"negocios con vida calculada: {len(biz):,}")

    zone_of, zone_docs = {}, []
    for name, box in ZONES.items():
        ids = [d["_id"] for d in db.businesses.find(
            {"location": {"$geoWithin": {"$geometry": polygon(box)}}, "life": {"$exists": True}}, {"_id": 1})]
        zone_of.update({i: name for i in ids})
        zone_docs.append({"_id": name, "name": name, "geometry": polygon(box), "businesses": len(ids)})
        print(f"  zona {name}: {len(ids):,} negocios")
    print(f"  fuera de toda zona: {len(biz) - len(zone_of):,}")

    by_cat, by_zone, by_cz = defaultdict(list), defaultdict(list), defaultdict(list)
    for bid, (cat, days, closed, late) in biz.items():
        row = (days, closed, late)
        by_cat[cat].append(row)
        z = zone_of.get(bid)
        if z:
            by_zone[z].append(row)
            by_cz[(cat, z)].append(row)

    top = [c for c, _ in sorted(by_cat.items(), key=lambda kv: -len(kv[1]))[:TOP_CATS]]
    now = datetime.now(timezone.utc)
    docs = []
    for cat, rows in by_cat.items():
        docs.append({"_id": f"category|{cat}", "dimension": "category", "category": cat, "zone": None, **estimate(rows)})
    for z, rows in by_zone.items():
        docs.append({"_id": f"zone|{z}", "dimension": "zone", "category": None, "zone": z, **estimate(rows)})
    for (cat, z), rows in by_cz.items():
        if cat in top:
            docs.append({"_id": f"category_zone|{cat}|{z}", "dimension": "category_zone", "category": cat, "zone": z, **estimate(rows)})
    for d in docs:
        d["computed_at"] = now

    db.survival.delete_many({})
    db.survival.insert_many(docs)
    db.survival.create_index([("dimension", 1), ("category", 1), ("zone", 1)])
    db.zones.delete_many({})
    db.zones.insert_many(zone_docs)
    from pymongo import GEOSPHERE
    db.zones.create_index([("geometry", GEOSPHERE)])

    ok = [d for d in docs if d["status"] == "ok"]
    print(f"\ngrupos: {len(docs)} | con curva: {len(ok)} | insuficientes: {len(docs) - len(ok)}"
          f" (mínimo {MIN_BUSINESSES} negocios y {MIN_EVENTS} cierres)")
    print(f"{'grupo':<58}{'n':>6}{'cierres':>9}{'mediana (años)':>16}{'con entrada tardía':>20}")
    for d in sorted(ok, key=lambda d: -d["n"])[:14]:
        label = d["_id"].split("|", 1)[1]
        m = f"{d['median_years']:.1f}" if d["median_years"] is not None else "no alcanzada"
        ml = f"{d['median_days_with_late'] / 365:.1f}" if d["median_days_with_late"] is not None else "no alcanzada"
        print(f"{label[:56]:<58}{d['n']:>6}{d['events']:>9}{m:>16}{ml:>20}")


if __name__ == "__main__":
    main()
