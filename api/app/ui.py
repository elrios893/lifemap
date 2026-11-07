from pathlib import Path

from flask import Blueprint, jsonify, send_from_directory

ui = Blueprint("ui", __name__)
_STATIC = Path(__file__).parent / "static"


@ui.get("/")
def index():
    """Interfaz web (HTML/JS estático): consume esta misma API desde el navegador."""
    return send_from_directory(_STATIC, "index.html")


@ui.get("/entregauno")
def entregauno():
    """Marca de la Entrega 1: sirve para ver en vivo que Jenkins desplegó este cambio."""
    return jsonify(entrega=1, estado="terminada", proyecto="LifeMap")
