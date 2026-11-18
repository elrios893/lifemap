"""Estimador de Kaplan-Meier en Python puro (sin dependencias), con intervalo de Greenwood.

Entrada: duraciones (días desde la primera reseña) y eventos (1 = cierre observado, 0 = censurado por la derecha:
el negocio seguía abierto en la fecha de corte). Los negocios censurados SALEN del conjunto en riesgo en su duración,
pero nunca cuentan como cierre ni se descartan.
"""
from bisect import bisect_left


def kaplan_meier(durations, events):
    """Tabla en los tiempos de evento: [(t, cierres, en_riesgo, S(t), suma_greenwood)]."""
    data = sorted(zip(durations, events))
    n, at_risk, surv, green, i, table = len(data), len(data), 1.0, 0.0, 0, []
    while i < n:
        t, d, c = data[i][0], 0, 0
        while i < n and data[i][0] == t:
            d += data[i][1]
            c += 1 - data[i][1]
            i += 1
        if d:
            surv *= 1.0 - d / at_risk
            if at_risk > d:
                green += d / (at_risk * (at_risk - d))
            table.append((t, d, at_risk, surv, green))
        at_risk -= d + c
    return table


def median_survival(table):
    """Primer tiempo en que S(t) <= 0,5; None si la curva nunca baja de 0,5 (la mediana no se alcanza)."""
    return next((t for t, _, _, s, _ in table if s <= 0.5), None)


def curve(table, durations, step=30, z=1.96):
    """Curva en una rejilla regular de `step` días: S(t), banda de confianza y número en riesgo en cada punto."""
    ordered = sorted(durations)
    n, tmax = len(ordered), (ordered[-1] if ordered else 0)
    points, j, surv, green = [], 0, 1.0, 0.0
    for t in range(0, tmax + step, step):
        while j < len(table) and table[j][0] <= t:
            surv, green = table[j][3], table[j][4]
            j += 1
        se = surv * green ** 0.5
        points.append({"t": t, "s": round(surv, 4), "lo": round(max(0.0, surv - z * se), 4),
                       "hi": round(min(1.0, surv + z * se), 4), "at_risk": n - bisect_left(ordered, t)})
    return points
