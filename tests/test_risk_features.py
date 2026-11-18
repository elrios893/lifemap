from datetime import datetime, timedelta

from risk_features import FEATURES, compute

T = datetime(2021, 1, 19)


def d(days_before):
    return T - timedelta(days=days_before)


def test_ignores_reviews_after_as_of():
    base = [(d(400), 5), (d(100), 4)]
    future = [(T + timedelta(days=30), 1), (T + timedelta(days=200), 1)]
    assert compute(base + future, T, 0) == compute(base, T, 0)   # nada posterior a T entra


def test_no_reviews_until_as_of_gives_none():
    assert compute([(T + timedelta(days=1), 3)], T, 0) is None


def test_trend_and_recent_activity():
    # Últimos 6 meses: 2 de 4 negativas (50 %). Seis meses anteriores: 1 de 4 (25 %). Tendencia = +25 puntos.
    rev = [(d(10), 1), (d(20), 1), (d(30), 5), (d(40), 5),
           (d(200), 1), (d(210), 5), (d(220), 5), (d(230), 5)]
    f = compute(rev, T, 3)
    assert f["pct_neg_6m"] == 50.0 and f["trend_neg"] == 25.0 and f["n_reviews_6m"] == 4
    assert f["competitors_500m"] == 3 and f["age_days"] == 230 and f["days_since_last"] == 10
    assert set(f) == set(FEATURES)


def test_sentiment_and_stars():
    f = compute([(d(5), 5), (d(6), 3), (d(7), 1)], T, 0)
    assert f["avg_stars"] == 3.0 and f["sent_mean"] == 0.0


def test_inactive_business_falls_back_to_historical_pct_negative():
    f = compute([(d(900), 1), (d(800), 5)], T, 0)   # sin reseñas en los últimos 6 meses
    assert f["n_reviews_6m"] == 0 and f["pct_neg_6m"] == 50.0 and f["trend_neg"] == 0.0
