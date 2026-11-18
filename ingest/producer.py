"""Productor de Kafka con reloj acelerado (Entrega 2).

Publica en el topic `reviews` las reseñas POSTERIORES a la fecha de corte T (las reservadas: el modelo nunca las vio),
en orden de fecha, con clave = business_id (así las reseñas de un negocio caen en la misma partición y conservan su orden).

Velocidad: --seconds-per-month N reproduce 30 días de reseñas cada N segundos reales (por defecto 10; 0 = lo más rápido).
La fecha de la reseña (tiempo del evento) viaja en el mensaje, no se reemplaza por la hora de envío.

Uso: python producer.py [--seconds-per-month 10] [--limit N] [--from-date YYYY-MM-DD]
Requiere el topic creado (servicio kafka-init) y CLEAN_DIR/review.parquet.
"""
import argparse
import json
import os
import time
from pathlib import Path

import pandas as pd

CLEAN = Path(os.environ.get("CLEAN_DIR", "/data/clean"))
BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC = os.environ.get("KAFKA_TOPIC", "reviews")
CUTOFF_T = os.environ.get("CUTOFF_T", "2021-01-19")


def reserved_reviews(cutoff: str, clean: Path = CLEAN) -> pd.DataFrame:
    """Reseñas con date > T, ordenadas por fecha (desempate por review_id para que el orden sea determinista)."""
    # Si existe reserved_reviews.parquet (solo las posteriores a T, ~pocas decenas de MB: es lo que viaja en el respaldo de S3
    # a la VM) se lee ese; si no, se filtra el review.parquet completo.
    reserved = clean / "reserved_reviews.parquet"
    df = pd.read_parquet(reserved if reserved.exists() else clean / "review.parquet",
                         columns=["review_id", "business_id", "stars", "text", "date"],
                         filters=[("date", ">", pd.Timestamp(cutoff))])
    return df.sort_values(["date", "review_id"], kind="stable").reset_index(drop=True)


def delays(dates: pd.Series, seconds_per_month: float) -> list:
    """Segundos reales (desde el inicio) en que debe salir cada mensaje: el tiempo del evento se comprime."""
    if seconds_per_month <= 0:
        return [0.0] * len(dates)
    days = (dates - dates.iloc[0]).dt.total_seconds() / 86400.0
    return (days / 30.0 * seconds_per_month).tolist()


def main():
    from kafka import KafkaProducer

    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds-per-month", type=float, default=10.0,
                    help="segundos reales por cada 30 días de reseñas (0 = sin pausa)")
    ap.add_argument("--limit", type=int, default=0, help="publicar solo las primeras N reseñas (0 = todas)")
    ap.add_argument("--from-date", default=CUTOFF_T, help="solo reseñas posteriores a esta fecha (por defecto T)")
    a = ap.parse_args()
    if a.from_date < CUTOFF_T:
        raise SystemExit(f"--from-date {a.from_date} es anterior al corte T={CUTOFF_T}: esas reseñas se usaron para entrenar")

    df = reserved_reviews(a.from_date)
    if a.limit:
        df = df.head(a.limit)
    if df.empty:
        raise SystemExit("no hay reseñas posteriores a T")
    when = delays(df["date"], a.seconds_per_month)
    print(f"{len(df):,} reseñas posteriores a {a.from_date}: {df.date.min().date()} -> {df.date.max().date()} "
          f"| {a.seconds_per_month}s por mes | topic={TOPIC} broker={BOOTSTRAP}", flush=True)

    producer = KafkaProducer(bootstrap_servers=BOOTSTRAP, acks="all", linger_ms=20, retries=5,
                             key_serializer=lambda k: k.encode("utf-8"),
                             value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"))
    t0, sent, last_report = time.time(), 0, time.time()
    for row, due in zip(df.itertuples(index=False), when):
        wait = due - (time.time() - t0)
        if wait > 0:
            time.sleep(wait)
        producer.send(TOPIC, key=row.business_id, value={
            "review_id": row.review_id, "business_id": row.business_id, "stars": int(row.stars),
            "text": row.text, "date": row.date.strftime("%Y-%m-%dT%H:%M:%S")})
        sent += 1
        if time.time() - last_report >= 5:
            print(f"  {sent:,}/{len(df):,} enviados | fecha simulada {row.date.date()} | {time.time() - t0:.0f}s", flush=True)
            last_report = time.time()
    producer.flush()
    print(f"listo: {sent:,} mensajes en {time.time() - t0:.1f}s", flush=True)


if __name__ == "__main__":
    main()
