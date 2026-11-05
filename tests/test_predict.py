from unittest.mock import MagicMock

from app import create_app, predict


def _client():
    return create_app(mongo_client=MagicMock()).test_client()


def test_predict_requires_text():
    assert _client().post("/predict", json={}).status_code == 400
    assert _client().post("/predict", json={"text": "   "}).status_code == 400
    assert _client().get("/predict").status_code == 400


def test_predict_rejects_huge_text():
    assert _client().post("/predict", json={"text": "a" * 6000}).status_code == 400


def test_predict_ok_with_stubbed_model(monkeypatch):
    monkeypatch.setattr(predict, "model_available", lambda: True)
    monkeypatch.setattr(predict, "predict_sentiment",
                        lambda t: {"sentiment": "positive", "probabilities": {"negative": 0.1, "neutral": 0.1, "positive": 0.8}})
    r = _client().post("/predict", json={"text": "great food"})
    assert r.status_code == 200 and r.get_json()["sentiment"] == "positive"


def test_predict_503_when_no_model(monkeypatch):
    monkeypatch.setattr(predict, "model_available", lambda: False)
    assert _client().post("/predict", json={"text": "ok"}).status_code == 503


def test_clean_text_matches_training():
    assert predict.clean_text("Great!! Visit http://x.co NOW 123") == "great   visit   now    "
