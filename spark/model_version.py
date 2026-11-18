"""Versionado de modelos: huella SHA-256 de todos los archivos de un modelo guardado (nombre relativo + contenido, en orden).

Es la ÚNICA definición: la usan el entrenamiento (para escribir version.json / risk_metrics.json) y la prueba de Jenkins
(check_models.py) para confirmar que el modelo que se va a cargar es exactamente el versionado.
"""
import hashlib
import os


def fingerprint(path):
    h = hashlib.sha256()
    for root, _, files in sorted(os.walk(path)):
        for f in sorted(files):
            fp = os.path.join(root, f)
            h.update(os.path.relpath(fp, path).replace("\\", "/").encode())
            with open(fp, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
    return h.hexdigest()
