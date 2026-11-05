"""Fórmulas compartidas. La tasa de cierre es la AFR del ejercicio de discos con días-negocio."""


def closure_rate(closures: int, business_days: float) -> float:
    """Tasa de cierre anualizada (%) = cierres / (días-negocio / 365) * 100."""
    if business_days <= 0:
        return 0.0
    return closures / (business_days / 360.0) * 100.0
