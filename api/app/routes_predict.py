from flask import Blueprint, jsonify, request

from . import predict
from .validation import ApiError

bp = Blueprint("predict", __name__)
MAX_CHARS = 5000


@bp.route("/predict", methods=["GET", "POST"])
def predict_route():
    """Sentimiento (negative / neutral / positive) de un texto nuevo en inglés."""
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        text = body.get("text")
    else:
        text = request.args.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ApiError("falta el campo 'text' (texto en inglés, no vacío)")
    if len(text) > MAX_CHARS:
        raise ApiError(f"'text' supera {MAX_CHARS} caracteres")
    if not predict.model_available():
        return jsonify(error="el modelo de sentimiento aún no está entrenado"), 503
    return jsonify(text=text, **predict.predict_sentiment(text))
