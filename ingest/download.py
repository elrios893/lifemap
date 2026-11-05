"""Descarga automática del Yelp Open Dataset con la API de Kaggle.

Credenciales: variables de entorno KAGGLE_USERNAME + KAGGLE_API_TOKEN (o KAGGLE_KEY); nunca en el repo.
Idempotente: si el archivo ya está descomprimido en RAW_DIR, no lo vuelve a bajar.

Uso: python download.py            (dentro del contenedor ingest, con el volumen /data montado)
"""
import os
import subprocess
import sys
import zipfile
from pathlib import Path

DATASET = "yelp-dataset/yelp-dataset"
FILES = ["yelp_academic_dataset_business.json", "yelp_academic_dataset_review.json"]
RAW_DIR = Path(os.environ.get("RAW_DIR", "/data/raw"))
RETRIES = 4


def fetch(name: str) -> Path:
    target = RAW_DIR / name
    if target.exists() and target.stat().st_size > 0:
        print(f"[skip] {name} ya existe ({target.stat().st_size / 1e6:.0f} MB)", flush=True)
        return target
    for attempt in range(1, RETRIES + 1):
        cmd = ["kaggle", "datasets", "download", "-d", DATASET, "-f", name, "-p", str(RAW_DIR)]
        print(f"[get] {name} intento {attempt}/{RETRIES}", flush=True)
        if subprocess.run(cmd).returncode == 0:
            break
    else:
        sys.exit(f"no se pudo descargar {name}")
    zpath = RAW_DIR / f"{name}.zip"
    if zpath.exists():  # Kaggle entrega el archivo comprimido
        with zipfile.ZipFile(zpath) as z:
            z.extractall(RAW_DIR)
        zpath.unlink()
    print(f"[ok] {name} -> {target.stat().st_size / 1e6:.0f} MB", flush=True)
    return target


def main():
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        fetch(f)


if __name__ == "__main__":
    main()
