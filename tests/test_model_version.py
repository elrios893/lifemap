import json

import pytest

import check_models
from model_version import fingerprint


def _model(tmp_path, name="sentiment_best", content=b"pesos"):
    d = tmp_path / name
    (d / "stages").mkdir(parents=True)
    (d / "stages" / "part-0").write_bytes(content)
    (d / "metadata").write_text("{}")
    return d


def test_fingerprint_is_deterministic_and_detects_any_change(tmp_path):
    d = _model(tmp_path)
    h = fingerprint(str(d))
    assert h == fingerprint(str(d)) and len(h) == 64
    (d / "stages" / "part-0").write_bytes(b"pesos alterados")
    assert fingerprint(str(d)) != h


def _setup(tmp_path, monkeypatch, t="2021-01-19"):
    for model, meta in (("sentiment_best", "version.json"), ("risk_best", "risk_metrics.json")):
        d = _model(tmp_path, model, model.encode())
        (tmp_path / meta).write_text(json.dumps({"sha256": fingerprint(str(d)), "cutoff_t": t}))
    monkeypatch.setattr(check_models, "MODELS", str(tmp_path))
    monkeypatch.setattr(check_models, "CUTOFF_T", "2021-01-19")


def test_check_models_passes_when_versioned(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    check_models.main()   # no lanza SystemExit


def test_check_models_fails_when_model_was_replaced(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    (tmp_path / "risk_best" / "stages" / "part-0").write_bytes(b"otro modelo")
    with pytest.raises(SystemExit) as e:
        check_models.main()
    assert e.value.code == 1


def test_check_models_fails_when_cutoff_differs(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, t="2020-06-01")
    with pytest.raises(SystemExit):
        check_models.main()


def test_check_models_fails_when_not_versioned(tmp_path, monkeypatch):
    monkeypatch.setattr(check_models, "MODELS", str(tmp_path))
    with pytest.raises(SystemExit):
        check_models.main()
