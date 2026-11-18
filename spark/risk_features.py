"""Variables del modelo de riesgo de cierre (Entrega 2). UNA sola definición, usada igual al entrenar (as_of = T) y al
puntuar en streaming (as_of = fecha de la última reseña recibida): así no hay diferencia entre lo que se entrenó y lo que se puntúa.

Regla anti-fuga: `compute` ignora toda reseña con fecha posterior a `as_of`. Con as_of = T, nada de lo que pasó después de T
entra en las variables.

Variables (todas calculadas con datos hasta as_of):
  n_reviews        número de reseñas
  avg_stars        estrellas promedio de las reseñas
  sent_mean        sentimiento medio (negativo -1, neutral 0, positivo +1; etiqueta derivada de las estrellas)
  pct_neg_6m       % de reseñas negativas en los últimos 6 meses (si no hubo, el % negativo histórico)
  trend_neg        tendencia: pct_neg_6m menos el % negativo de los 6 meses anteriores (0 si falta alguno de los dos)
  n_reviews_6m     reseñas en los últimos 6 meses (actividad reciente)
  age_days         edad: días desde su primera reseña hasta as_of
  days_since_last  días desde su última reseña hasta as_of
  competitors_500m negocios de la misma categoría a menos de 500 m ($geoNear), sin contarse a sí mismo
"""
from datetime import timedelta

FEATURES = ["n_reviews", "avg_stars", "sent_mean", "pct_neg_6m", "trend_neg", "n_reviews_6m", "age_days",
            "days_since_last", "competitors_500m"]
HALF_YEAR = 183


def sent_score(stars):
    return -1 if stars <= 2 else (0 if stars == 3 else 1)


def _pct_neg(stars_list):
    return sum(1 for s in stars_list if s <= 2) / len(stars_list) * 100.0


def compute(reviews, as_of, competitors):
    """reviews: iterable de (fecha, estrellas). Devuelve el dict de variables o None si no hay reseñas hasta as_of."""
    rs = [(d, s) for d, s in reviews if d <= as_of]
    if not rs:
        return None
    n = len(rs)
    recent_from, prev_from = as_of - timedelta(days=HALF_YEAR), as_of - timedelta(days=2 * HALF_YEAR)
    recent = [s for d, s in rs if d > recent_from]
    prev = [s for d, s in rs if prev_from < d <= recent_from]
    pct_recent = _pct_neg(recent) if recent else _pct_neg([s for _, s in rs])
    return {
        "n_reviews": n,
        "avg_stars": sum(s for _, s in rs) / n,
        "sent_mean": sum(sent_score(s) for _, s in rs) / n,
        "pct_neg_6m": pct_recent,
        "trend_neg": (_pct_neg(recent) - _pct_neg(prev)) if (recent and prev) else 0.0,
        "n_reviews_6m": len(recent),
        "age_days": (as_of - min(d for d, _ in rs)).days,
        "days_since_last": (as_of - max(d for d, _ in rs)).days,
        "competitors_500m": int(competitors),
    }


def count_competitors(db, location, category, business_id, meters=500):
    """Negocios de la misma categoría a menos de `meters` metros, con $geoNear sobre el índice 2dsphere."""
    out = list(db.businesses.aggregate([
        {"$geoNear": {"near": location, "distanceField": "dist", "maxDistance": meters, "spherical": True,
                      "query": {"main_category": category, "_id": {"$ne": business_id}}}},
        {"$count": "n"}]))
    return out[0]["n"] if out else 0
