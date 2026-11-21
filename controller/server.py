"""Servidor mínimo (solo biblioteca estándar) que reproduce el flujo bajo demanda.

  POST /replay  {"seconds_per_month": 10}   inicia: reset_stream.sh y luego el productor (202; 409 si ya hay una en curso)
  GET  /status                                fase actual, velocidad, tiempos y últimas líneas del registro

Solo acepta ese comando: no expone una shell ni recibe rutas ni argumentos libres. Solo la API (misma red de Compose) lo alcanza.
"""
import json
import os
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.environ.get("REPO_DIR", "/opt/lifemap")
LOCK = threading.Lock()
STATE = {"phase": "idle", "seconds_per_month": None, "started_at": None, "finished_at": None, "error": None, "log": []}


def validate(body):
    """Velocidad en segundos reales por mes de reseñas: entre 0 (lo más rápido) y 60."""
    try:
        v = float(body.get("seconds_per_month", 10))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("'seconds_per_month' debe ser un número")
    if not 0 <= v <= 60:
        raise ValueError("'seconds_per_month' debe estar entre 0 y 60")
    return v


def log(line):
    STATE["log"] = (STATE["log"] + [line.rstrip()])[-40:]


def run(cmd):
    p = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    for line in p.stdout:
        log(line)
    if p.wait() != 0:
        raise RuntimeError("falló: " + " ".join(cmd))


def replay(speed):
    try:
        STATE["phase"] = "reiniciando"
        run(["bash", "scripts/reset_stream.sh"])
        STATE["phase"] = "publicando"
        run(["docker", "compose", "run", "--rm", "producer", "--seconds-per-month", str(speed)])
        STATE["phase"] = "terminado"
    except Exception as exc:  # noqa: BLE001
        STATE["phase"], STATE["error"] = "error", str(exc)
    finally:
        STATE["finished_at"] = time.time()


def start(body):
    """Devuelve (código HTTP, respuesta)."""
    try:
        speed = validate(body)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    with LOCK:
        if STATE["phase"] in ("reiniciando", "publicando"):
            return 409, {"error": "ya hay una reproducción en curso", **status()}
        STATE.update(phase="reiniciando", seconds_per_month=speed, started_at=time.time(), finished_at=None, error=None, log=[])
        threading.Thread(target=replay, args=(speed,), daemon=True).start()
    return 202, status()


def status():
    s = dict(STATE)
    s["elapsed_s"] = round((s["finished_at"] or time.time()) - s["started_at"]) if s["started_at"] else None
    return s


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self._send(*((200, status()) if self.path == "/status" else (404, {"error": "no existe"})))

    def do_POST(self):
        if self.path != "/replay":
            return self._send(404, {"error": "no existe"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self._send(400, {"error": "el cuerpo debe ser JSON"})
        self._send(*start(body))

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
