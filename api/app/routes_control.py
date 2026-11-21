"""Botón «Reproducir flujo» del panel: la API no ejecuta nada; reenvía la orden al servicio `controller`, que corre el reinicio
del flujo y el productor de Kafka. Sin clave a propósito (decisión del autor: la demostración no se expone a terceros)."""
import os

import requests
from flask import Blueprint, jsonify, request

from .validation import ApiError

bp = Blueprint("control", __name__)


def _url(path):
    return os.environ.get("CONTROLLER_URL", "http://controller:8000") + path


def _speed(body):
    try:
        v = float((body or {}).get("seconds_per_month", 10))
    except (TypeError, ValueError):
        raise ApiError("'seconds_per_month' debe ser un número") from None
    if not 0 <= v <= 60:
        raise ApiError("'seconds_per_month' debe estar entre 0 y 60 (0 = lo más rápido)")
    return v


def _relay(call):
    try:
        r = call()
    except requests.RequestException:
        raise ApiError("el servicio controller no responde (¿está desplegado?)", 503) from None
    return jsonify(r.json()), r.status_code


@bp.post("/replay")
def replay_start():
    """Reinicia el flujo y publica en Kafka las reseñas posteriores a T. Body JSON opcional: {"seconds_per_month": 10}."""
    speed = _speed(request.get_json(silent=True))
    return _relay(lambda: requests.post(_url("/replay"), json={"seconds_per_month": speed}, timeout=10))


@bp.get("/replay")
def replay_status():
    """Fase de la última reproducción: idle, reiniciando, publicando, terminado o error."""
    return _relay(lambda: requests.get(_url("/status"), timeout=5))
