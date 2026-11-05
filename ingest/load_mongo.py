"""Carga por lotes a MongoDB: negocios como GeoJSON (índice 2dsphere) y reseñas que referencian su negocio.

Idempotente (upsert por _id). Lee CLEAN_DIR/business.parquet y, si existe, CLEAN_DIR/review.parquet.
Uso: python load_mongo.py
"""
import os
import time
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
from pymongo import ASCENDING, GEOSPHERE, MongoClient, ReplaceOne

from geo import geohash

CLEAN = Path(os.environ.get("CLEAN_DIR", "/data/clean"))
BATCH = int(os.environ.get("BATCH", "5000"))
GEOHASH_PRECISION = 5


def client():
    uri = os.environ.get("MONGO_URI") or (
        f"mongodb://{os.environ['MONGO_USER']}:{os.environ['MONGO_PASSWORD']}@mongo:27017/?authSource=admin")
    return MongoClient(uri)[os.environ.get("MONGO_DB", "lifemap")]


def sentiment(stars: float) -> str:
    """1-2 negativo, 3 neutral, 4-5 positivo (definición del enunciado)."""
    return "negative" if stars <= 2 else "neutral" if stars == 3 else "positive"


def business_docs(df: pd.DataFrame):
    for r in df.itertuples(index=False):
        yield ReplaceOne({"_id": r.business_id}, {
            "_id": r.business_id,
            "name": r.name, "city": r.city, "state": r.state,
            "stars": float(r.stars), "review_count": int(r.review_count), "is_open": int(r.is_open),
            "categories": [c.strip() for c in r.categories.split(",")],
            "main_category": r.main_category,
            "geohash": geohash(r.latitude, r.longitude, GEOHASH_PRECISION),
            # GeoJSON: [longitud, latitud] (el orden inverso es el error clásico)
            "location": {"type": "Point", "coordinates": [float(r.longitude), float(r.latitude)]},
        }, upsert=True)


def review_docs(df: pd.DataFrame):
    for r in df.itertuples(index=False):
        yield ReplaceOne({"_id": r.review_id}, {
            "_id": r.review_id, "business_id": r.business_id, "stars": int(r.stars),
            "sentiment": sentiment(r.stars), "text": r.text, "date": r.date.to_pydatetime(),
        }, upsert=True)


def flush(col, ops):
    if ops:
        col.bulk_write(ops, ordered=False)
    return len(ops)


def load(col, docs, label):
    t0, n, ops = time.time(), 0, []
    for op in docs:
        ops.append(op)
        if len(ops) >= BATCH:
            n += flush(col, ops)
            ops = []
            print(f"  {label}: {n:,}", flush=True)
    n += flush(col, ops)
    print(f"{label}: {n:,} documentos en {time.time() - t0:.1f}s", flush=True)


def main():
    db = client()
    for name in ("businesses", "reviews"):   # recarga limpia: la colección refleja exactamente el parquet
        db[name].drop()
    load(db.businesses, business_docs(pd.read_parquet(CLEAN / "business.parquet")), "businesses")
    db.businesses.create_index([("location", GEOSPHERE)], name="location_2dsphere")
    db.businesses.create_index([("main_category", ASCENDING)])
    db.businesses.create_index([("geohash", ASCENDING)])

    rpath = CLEAN / "review.parquet"
    if rpath.exists():
        pf = pq.ParquetFile(next(rpath.glob("*.parquet"))) if rpath.is_dir() else pq.ParquetFile(rpath)
        files = sorted(rpath.glob("*.parquet")) if rpath.is_dir() else [rpath]
        for f in files:
            for batch in pq.ParquetFile(f).iter_batches(batch_size=BATCH):
                load(db.reviews, review_docs(batch.to_pandas()), f"reviews[{f.name}]")
        db.reviews.create_index([("business_id", ASCENDING), ("date", ASCENDING)])
        db.reviews.create_index([("sentiment", ASCENDING)])
    else:
        print("(sin review.parquet: solo se cargaron negocios)")

    print("\nconteos:", {c: db[c].count_documents({}) for c in ("businesses", "reviews")})
    print("índices businesses:", [i["name"] for i in db.businesses.list_indexes()])


if __name__ == "__main__":
    main()
