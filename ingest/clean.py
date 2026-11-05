"""Limpieza con Dask del Yelp Open Dataset (lectura particionada) con conteos antes/después de cada regla.

Entradas : RAW_DIR/yelp_academic_dataset_{business,review}.json   (las deja download.py)
Salidas  : CLEAN_DIR/business.parquet, CLEAN_DIR/review.parquet, CLEAN_DIR/report.json

Configuración (variables de entorno):
  DASK_SCHEDULER   tcp://dask-scheduler:8786
  AREA_STATES      estados del área metropolitana a analizar (por defecto PA = área de Filadelfia)
  SAMPLE_REVIEWS   0 = todo el área; N = muestra de negocios completos hasta ~N reseñas (desarrollo local)
"""
import hashlib
import json
import os
import time
from pathlib import Path

import dask
import dask.bag as db
import dask.dataframe as dd
import pandas as pd
from dask.distributed import Client

RAW = Path(os.environ.get("RAW_DIR", "/data/raw"))
CLEAN = Path(os.environ.get("CLEAN_DIR", "/data/clean"))
SCHEDULER = os.environ.get("DASK_SCHEDULER", "tcp://dask-scheduler:8786")
AREA_STATES = [s.strip() for s in os.environ.get("AREA_STATES", "PA").split(",")]
SAMPLE_REVIEWS = int(os.environ.get("SAMPLE_REVIEWS", "0"))
SKIP_REVIEWS = os.environ.get("SKIP_REVIEWS") == "1"   # solo negocios (útil mientras baja el archivo de reseñas)
BLOCKSIZE = int(os.environ.get("BLOCKSIZE_MB", "16")) * 2**20

BUSINESS_COLS = ["business_id", "name", "city", "state", "latitude", "longitude",
                 "stars", "review_count", "is_open", "categories"]
REVIEW_COLS = ["review_id", "business_id", "stars", "text", "date"]


def read_jsonl(path, cols, meta):
    """Lectura particionada de JSON Lines. Parsea línea a línea y conserva solo `cols`: read_json de pandas
    expandía campos anidados (attributes, hours) y reventaba la memoria de los workers."""
    def parse(line):
        d = json.loads(line)
        return {c: d.get(c) for c in cols}
    bag = db.read_text(str(path), blocksize=BLOCKSIZE).map(parse)
    return bag.to_dataframe(meta=meta)


_BUSINESS_META = {"business_id": "object", "name": "object", "city": "object", "state": "object",
                  "latitude": "float64", "longitude": "float64", "stars": "float64",
                  "review_count": "int64", "is_open": "int64", "categories": "object"}
_REVIEW_META = {"review_id": "object", "business_id": "object", "stars": "float64",
                "text": "object", "date": "object"}


def clean_businesses(report: dict) -> pd.DataFrame:
    """El archivo de negocios (~120 MB) se lee particionado con Dask y se materializa: es la tabla pequeña."""
    steps = []
    b = read_jsonl(RAW / "yelp_academic_dataset_business.json", BUSINESS_COLS, _BUSINESS_META)
    b = b.compute()
    steps.append(("leídos", len(b)))

    b = b[b.state.isin(AREA_STATES)]
    steps.append((f"dentro del área ({','.join(AREA_STATES)})", len(b)))

    # Regla 1: coordenadas nulas o fuera de rango (un punto GeoJSON inválido rompe el índice 2dsphere).
    ok = b.latitude.between(-90, 90) & b.longitude.between(-180, 180)
    b = b[ok]
    steps.append(("coordenadas válidas", len(b)))

    # Regla 2: duplicados por business_id (la clave del negocio debe ser única en Mongo).
    b = b.drop_duplicates("business_id")
    steps.append(("sin duplicados", len(b)))

    # Regla 3: sin categorías no hay "categoría principal" para agrupar las tasas.
    b = b[b.categories.notna() & (b.categories.str.strip() != "")]
    steps.append(("con categorías", len(b)))
    b = b.assign(main_category=b.categories.str.split(",").str[0].str.strip())

    # Muestra para desarrollo: negocios completos (no reseñas sueltas) en orden pseudoaleatorio estable.
    if SAMPLE_REVIEWS > 0:
        key = b.business_id.map(lambda x: hashlib.md5(x.encode()).hexdigest())
        b = b.assign(_k=key).sort_values("_k")
        b = b[b.review_count.cumsum() <= SAMPLE_REVIEWS].drop(columns="_k")
        steps.append((f"muestra de desarrollo (~{SAMPLE_REVIEWS} reseñas)", len(b)))

    report["business_steps"] = steps
    return b.reset_index(drop=True)


def clean_reviews(business_ids: set, report: dict):
    r = read_jsonl(RAW / "yelp_academic_dataset_review.json", REVIEW_COLS, _REVIEW_META)
    n_raw = r.shape[0]

    # Regla 1: la reseña debe pertenecer a un negocio que sobrevivió a la limpieza (unión reseña–negocio).
    r1 = r[r.business_id.isin(business_ids)]
    n1 = r1.shape[0]

    # Regla 2: sin texto no hay sentimiento que clasificar.
    r2 = r1[r1.text.notnull() & (r1.text.str.strip() != "")]
    n2 = r2.shape[0]

    # Regla 3: estrellas válidas (1-5); la etiqueta de sentimiento se deriva de ellas.
    r3 = r2[r2.stars.between(1, 5)]
    n3 = r3.shape[0]

    # Regla 4: duplicados por review_id, con shuffle por clave para no concentrar todo en un worker.
    r4 = r3.shuffle(on="review_id", shuffle_method="tasks").map_partitions(
        lambda p: p.drop_duplicates("review_id"), meta=r3._meta)
    r4 = r4.assign(date=dd.to_datetime(r4["date"]))
    n4 = r4.shape[0]

    out = CLEAN / "review.parquet"
    t0 = time.time()
    # coerce_timestamps="ms": Spark no lee timestamps en nanosegundos
    counts, _ = dask.compute((n_raw, n1, n2, n3, n4), r4.to_parquet(out, write_index=False, compute=False, coerce_timestamps="ms", allow_truncated_timestamps=True))
    report["review_steps"] = [
        ("leídas", int(counts[0])), ("de negocios del área", int(counts[1])), ("con texto", int(counts[2])),
        ("con estrellas 1-5", int(counts[3])), ("sin duplicados", int(counts[4]))]
    report["review_seconds"] = round(time.time() - t0, 1)


def main():
    CLEAN.mkdir(parents=True, exist_ok=True)
    client = Client(SCHEDULER)
    print("Dask:", client.dashboard_link, "| workers:", len(client.scheduler_info()["workers"]), flush=True)
    report = {"area_states": AREA_STATES, "sample_reviews": SAMPLE_REVIEWS}

    b = clean_businesses(report)
    b.to_parquet(CLEAN / "business.parquet", index=False)
    if not SKIP_REVIEWS:
        clean_reviews(set(b.business_id), report)

    (CLEAN / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for tabla in [t for t in ("business_steps", "review_steps") if t in report]:
        print(f"\n{tabla}")
        prev = None
        for name, n in report[tabla]:
            print(f"  {name:<42}{n:>10,}" + (f"   ({n - prev:+,})" if prev is not None else ""))
            prev = n


if __name__ == "__main__":
    main()
