"""Exporta las reseñas RESERVADAS (posteriores a la fecha de corte T) a CLEAN_DIR/reserved_reviews.parquet.

Son las que reproduce el productor de Kafka. Se guardan aparte porque el review.parquet completo es grande y no viaja al respaldo
de S3, mientras que este archivo (solo el último año) sí, y así la VM de la nube puede reproducir el flujo con el texto de cada reseña.

Uso: python export_reserved.py        Variables: CLEAN_DIR (/data/clean), CUTOFF_T (2021-01-19)
"""
import os
from pathlib import Path

import pandas as pd

CLEAN = Path(os.environ.get("CLEAN_DIR", "/data/clean"))
CUTOFF_T = os.environ.get("CUTOFF_T", "2021-01-19")


def main():
    df = pd.read_parquet(CLEAN / "review.parquet", columns=["review_id", "business_id", "stars", "text", "date"],
                         filters=[("date", ">", pd.Timestamp(CUTOFF_T))])
    df = df.sort_values(["date", "review_id"], kind="stable").reset_index(drop=True)
    out = CLEAN / "reserved_reviews.parquet"
    df.to_parquet(out, index=False, coerce_timestamps="ms", allow_truncated_timestamps=True)
    print(f"reseñas posteriores a T={CUTOFF_T}: {len(df):,} ({df.date.min().date()} -> {df.date.max().date()}) -> {out} "
          f"({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
