"""Balanceo de carga.

Operación medida: la agregación del MapReduce (reseña -> categoría principal, suma de reseñas y negativas con reduceByKey).
1) Tiempos con 2, 8, 32 y 200 particiones, repartiendo SIN clave (repartition, round-robin) y CON clave
   (partitionBy sobre la categoría), con N repeticiones; se reportan media y desviación estándar.
2) Sesgo: filas por partición con spark_partition_id(), con y sin clave, para explicar los tiempos.

Uso: spark-submit --master spark://spark-master:7077 /opt/jobs/balanceo.py [repeticiones]
Salida: /models/balanceo.json (y tablas por consola)
"""
import json
import os
import statistics
import sys
import time

from pyspark.sql import SparkSession, functions as F

CLEAN = os.environ.get("CLEAN_DIR", "/data/clean")
OUT = os.environ.get("MODELS_DIR", "/models") + "/balanceo.json"
REPS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
PARTICIONES = [2, 8, 32, 200]


def sumar(a, b):
    return (a[0] + b[0], a[1] + b[1])


def main():
    spark = (SparkSession.builder.appName("balanceo").config("spark.sql.shuffle.partitions", "8").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")

    rev = spark.read.parquet(f"{CLEAN}/review.parquet").select("business_id", "stars")
    biz = spark.read.parquet(f"{CLEAN}/business.parquet").select("business_id", "main_category")
    df = rev.join(F.broadcast(biz), "business_id").select("main_category", "stars").cache()
    n = df.count()
    print("reseñas con categoría: %d | categorías distintas: %d" % (n, df.select("main_category").distinct().count()))

    pares = df.rdd.map(lambda r: (r["main_category"], (1, int(r["stars"] <= 2)))).cache()
    pares.count()

    def ejecutar(k, modo):
        t0 = time.time()
        base = pares.repartition(k) if modo == "sin_clave" else pares.partitionBy(k)
        claves = base.reduceByKey(sumar).count()
        return time.time() - t0, claves

    ejecutar(8, "sin_clave")  # calentamiento (JVM, caché, executors): no se registra

    tiempos = []
    for k in PARTICIONES:
        for modo in ("sin_clave", "con_clave"):
            runs = []
            for rep in range(1, REPS + 1):
                seg, claves = ejecutar(k, modo)
                runs.append(seg)
                print("  k=%-3d %-9s rep %d: %6.2fs (%d claves)" % (k, modo, rep, seg, claves), flush=True)
            tiempos.append({"particiones": k, "reparto": modo, "repeticiones": REPS,
                            "media_s": round(statistics.mean(runs), 3), "desv_s": round(statistics.stdev(runs), 3),
                            "min_s": round(min(runs), 3), "max_s": round(max(runs), 3)})

    print("\nResumen de tiempos (%d repeticiones, segundos)" % REPS)
    print("%-11s %-10s %8s %8s %8s %8s" % ("particiones", "reparto", "media", "desv", "min", "max"))
    for t in tiempos:
        print("%-11d %-10s %8.3f %8.3f %8.3f %8.3f" % (t["particiones"], t["reparto"], t["media_s"], t["desv_s"], t["min_s"], t["max_s"]))

    sesgo = []
    for k in PARTICIONES:
        for modo, rep in (("sin_clave", df.repartition(k)), ("con_clave", df.repartition(k, "main_category"))):
            cuentas = {r["pid"]: r["filas"] for r in
                       rep.groupBy(F.spark_partition_id().alias("pid")).agg(F.count("*").alias("filas")).collect()}
            filas = [cuentas.get(i, 0) for i in range(k)]   # particiones sin filas cuentan como 0
            media = n / k
            sesgo.append({"particiones": k, "reparto": modo, "min": min(filas), "max": max(filas),
                          "desv": round(statistics.pstdev(filas), 1), "vacias": sum(1 for f in filas if f == 0),
                          "max_sobre_media": round(max(filas) / media, 2)})

    print("\nFilas por partición (spark_partition_id), total %d filas" % n)
    print("%-11s %-10s %8s %8s %9s %7s %12s" % ("particiones", "reparto", "min", "max", "desv", "vacias", "max/media"))
    for s in sesgo:
        print("%-11d %-10s %8d %8d %9.1f %7d %12.2f" % (s["particiones"], s["reparto"], s["min"], s["max"], s["desv"], s["vacias"], s["max_sobre_media"]))

    with open(OUT, "w") as fh:
        json.dump({"filas": n, "tiempos": tiempos, "sesgo": sesgo}, fh, ensure_ascii=False, indent=2)
    print("\nguardado en", OUT)
    spark.stop()


if __name__ == "__main__":
    main()
