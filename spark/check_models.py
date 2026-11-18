"""Prueba de Jenkins: el modelo que se va a cargar es el versionado (Entrega 2).

Recalcula la huella SHA-256 de los modelos guardados en /models y la compara con la que quedó escrita al entrenarlos:
  sentiment_best  vs  version.json["sha256"]
  risk_best       vs  risk_metrics.json["sha256"]
y comprueba que los dos se entrenaron con la misma fecha de corte T que usa el flujo (CUTOFF_T).
Si algo no coincide (un modelo reemplazado a mano, a medias o de otra versión) sale con código 1 y Jenkins no despliega.

Uso: python3 check_models.py        Variables: MODELS_DIR (/models), CUTOFF_T (2021-01-19)
"""
import json
import os
import sys

from model_version import fingerprint

MODELS = os.environ.get("MODELS_DIR", "/models")
CUTOFF_T = os.environ.get("CUTOFF_T", "2021-01-19")


def load(name):
    path = os.path.join(MODELS, name)
    if not os.path.exists(path):
        raise SystemExit(f"FALLA: no existe {path}; el modelo no está versionado")
    with open(path) as fh:
        return json.load(fh)


def main():
    errors = []
    for label, meta_file, model_dir in (("sentimiento", "version.json", "sentiment_best"), ("riesgo", "risk_metrics.json", "risk_best")):
        meta = load(meta_file)
        if not os.path.isdir(os.path.join(MODELS, model_dir)):
            errors.append(f"{label}: falta la carpeta {model_dir}")
            continue
        actual = fingerprint(os.path.join(MODELS, model_dir))
        ok = actual == meta["sha256"]
        print(f"{label:<12} versión {meta['sha256'][:12]} | huella actual {actual[:12]} | {'OK' if ok else 'NO COINCIDE'}"
              f" | corte T del modelo {meta['cutoff_t']}")
        if not ok:
            errors.append(f"{label}: la huella de {model_dir} no coincide con la versionada")
        if meta["cutoff_t"] != CUTOFF_T:
            errors.append(f"{label}: entrenado con T={meta['cutoff_t']} pero el flujo usa T={CUTOFF_T}")
    if errors:
        print("\n".join("FALLA: " + e for e in errors))
        sys.exit(1)
    print("modelos versionados: OK")


if __name__ == "__main__":
    main()
