"""Vida de cada negocio, calculada con Dask sobre review.parquet y escrita en el mismo documento GeoJSON.

Por negocio (campo `life`):
  first_review / last_review : fechas de su primera y última reseña
  n_reviews                  : reseñas observadas
  business_days              : días entre primera y última reseña (aproximación; Yelp no trae apertura ni cierre)
  closed                     : 1 si is_open = 0 (cierre observado, el evento)
  censored                   : 1 si is_open = 1 (solo se sabe que seguía abierto en la fecha de corte)
  cutoff                     : fecha de corte = última fecha de reseña en el dataset
  late_entry                 : 1 si su primera reseña cae en los primeros LATE_ENTRY_DAYS de la ventana observada:
                               el negocio casi seguro ya existía antes de empezar a observarse (entrada tardía,
                               truncamiento por la izquierda). Es una aproximación: el dataset no trae apertura.
Por negocio (campo `sent`): conteo de reseñas por etiqueta (negativo 1-2, neutral 3, positivo 4-5).

Uso: python life.py
"""
import os
from pathlib import Path

import dask.dataframe as dd
import pandas as pd
from dask.distributed import Client
from pymongo import UpdateOne

from load_mongo import client as mongo_db

CLEAN = Path(os.environ.get("CLEAN_DIR", "/data/clean"))
SCHEDULER = os.environ.get("DASK_SCHEDULER", "tcp://dask-scheduler:8786")
# Un negocio cuya primera reseña cae dentro de este margen desde el inicio de la ventana ya existía antes de observarse.
LATE_ENTRY_DAYS = int(os.environ.get("LATE_ENTRY_DAYS", "365"))
BATCH = 5000


def compute_life() -> pd.DataFrame:
    Client(SCHEDULER)
    r = dd.read_parquet(CLEAN / "review.parquet", columns=["business_id", "stars", "date"])
    r = r.assign(neg=(r.stars <= 2).astype("int64"), neu=(r.stars == 3).astype("int64"),
                 pos=(r.stars >= 4).astype("int64"))
    g = r.groupby("business_id").agg({"date": ["min", "max", "count"], "neg": "sum", "neu": "sum", "pos": "sum"})
    g.columns = ["first_review", "last_review", "n_reviews", "negative", "neutral", "positive"]
    return g.compute().reset_index()


def main():
    life = compute_life()
    cutoff = life.last_review.max()
    window_start = life.first_review.min()
    life["business_days"] = (life.last_review - life.first_review).dt.days
    life["late_entry"] = ((life.first_review - window_start).dt.days <= LATE_ENTRY_DAYS).astype(int)
    print(f"negocios con reseñas: {len(life):,} | ventana observada: {window_start.date()} -> {cutoff.date()}")

    db = mongo_db()
    is_open = {d["_id"]: d["is_open"] for d in db.businesses.find({}, {"is_open": 1})}
    ops = []
    n = 0
    for r in life.itertuples(index=False):
        if r.business_id not in is_open:
            continue
        closed = 1 if is_open[r.business_id] == 0 else 0
        ops.append(UpdateOne({"_id": r.business_id}, {"$set": {
            "life": {"first_review": r.first_review.to_pydatetime(), "last_review": r.last_review.to_pydatetime(),
                     "n_reviews": int(r.n_reviews), "business_days": int(r.business_days),
                     "closed": closed, "censored": 1 - closed, "cutoff": cutoff.to_pydatetime(),
                     "late_entry": int(r.late_entry)},
            "sent": {"n": int(r.n_reviews), "negative": int(r.negative), "neutral": int(r.neutral),
                     "positive": int(r.positive)}}}))
        if len(ops) >= BATCH:
            db.businesses.bulk_write(ops, ordered=False)
            n += len(ops)
            ops = []
    if ops:
        db.businesses.bulk_write(ops, ordered=False)
        n += len(ops)
    print(f"documentos actualizados con `life` y `sent`: {n:,}")

    c = db.businesses
    print("cierres observados:", c.count_documents({"life.closed": 1}),
          "| censurados:", c.count_documents({"life.censored": 1}),
          "| entrada tardía:", c.count_documents({"life.late_entry": 1}),
          "| sin reseñas en la muestra:", c.count_documents({"life": {"$exists": False}}))


if __name__ == "__main__":
    main()
