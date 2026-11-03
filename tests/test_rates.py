from app.rates import closure_rate


def test_closure_rate_formula():
    # 2 cierres en 730 días-negocio = 2 años-negocio -> 1 cierre/año -> 100 %
    assert closure_rate(2, 730) == 100.0
    # 3 cierres en 36500 días-negocio (100 años) -> 3 %
    assert closure_rate(3, 36500) == 3.0


def test_closure_rate_zero_days():
    assert closure_rate(5, 0) == 0.0
