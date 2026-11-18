from km import curve, kaplan_meier, median_survival

# Ejemplo clásico (Freireich, leucemia, grupo 6-MP): 21 pacientes, 9 eventos y 12 censuras.
DUR = [6, 6, 6, 7, 10, 13, 16, 22, 23, 6, 9, 10, 11, 17, 19, 20, 25, 32, 32, 34, 35]
EVT = [1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]


def test_matches_textbook_values():
    table = {t: (d, n, round(s, 3)) for t, d, n, s, _ in kaplan_meier(DUR, EVT)}
    assert table[6] == (3, 21, 0.857)     # 3 cierres de 21 en riesgo (la censura de 6+ no cuenta como cierre)
    assert table[7] == (1, 17, 0.807)
    assert table[10] == (1, 15, 0.753)
    assert table[23] == (1, 6, 0.448)


def test_median_and_unreached_median():
    assert median_survival(kaplan_meier(DUR, EVT)) == 23
    assert median_survival(kaplan_meier([5, 10, 20], [1, 0, 0])) is None   # S nunca baja de 0,5


def test_censored_are_not_closures():
    # Si todos fueran cierres la supervivencia final sería 0; con censura queda por encima.
    assert kaplan_meier([10, 20, 30], [0, 0, 0]) == []
    assert kaplan_meier([10, 20, 30], [1, 0, 0])[-1][3] > 0.6


def test_curve_has_at_risk_and_monotone_survival():
    pts = curve(kaplan_meier(DUR, EVT), DUR, step=5)
    assert pts[0] == {"t": 0, "s": 1.0, "lo": 1.0, "hi": 1.0, "at_risk": 21}
    assert all(a["s"] >= b["s"] for a, b in zip(pts, pts[1:]))
    assert all(a["at_risk"] >= b["at_risk"] for a, b in zip(pts, pts[1:]))
