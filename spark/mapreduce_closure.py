"""MapReduce con RDD: tasa de cierre anualizada por categoría principal y por celda de geohash.

emite (clave, (cierre, días_negocio, reseñas, negativas, 1)) y suma con reduceByKey; el resultado se valida
contra un groupBy de DataFrames y se guarda en la colección `closure_stats` (la que lee /stats/closure).

  tasa de cierre (%) = cierres / (días-negocio / 365) * 100

Uso (desde el contenedor spark-master):
  spark-submit --master spark://spark-master:7077 /opt/jobs/mapreduce_closure.py
Variables: MONGO_URI, MONGO_DB (por defecto lifemap)
"""
import os
import sys

from pyspark.sql import SparkSession, functions as F

MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB = os.environ.get("MONGO_DB", "lifemap")


def rate(closures, days):
    return closures / (days / 365.0) * 100.0 if days else 0.0


def add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def main():
    spark = (SparkSession.builder.appName("mapreduce_closure")
             .config("spark.mongodb.read.connection.uri", MONGO_URI)
             .config("spark.mongodb.write.connection.uri", MONGO_URI)
             .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")

    biz = (spark.read.format("mongodb").option("database", MONGO_DB).option("collection", "businesses").load()
           .select("main_category", "geohash",
                   F.col("life.closed").alias("closed"), F.col("life.business_days").alias("days"),
                   F.col("sent.n").alias("reviews"), F.col("sent.negative").alias("negative"))
           .where(F.col("days").isNotNull()).cache())
    print("negocios con vida calculada:", biz.count())

    results = []
    for level, col in (("category", "main_category"), ("geohash", "geohash")):
        # --- MapReduce con RDD: (clave, (cierres, días, reseñas, negativas, negocios)) -> reduceByKey
        rdd = (biz.rdd.map(lambda r, c=col: (r[c], (int(r["closed"]), int(r["days"]), int(r["reviews"] or 0),
                                                   int(r["negative"] or 0), 1)))
               .reduceByKey(add))
        mr = dict(rdd.collect())

        # --- Validación con DataFrames
        df = biz.groupBy(col).agg(F.sum("closed").alias("c"), F.sum("days").alias("d"), F.sum("reviews").alias("r"),
                                  F.sum("negative").alias("n"), F.count("*").alias("b"))
        dfd = {r[col]: (int(r["c"]), int(r["d"]), int(r["r"] or 0), int(r["n"] or 0), int(r["b"])) for r in df.collect()}
        same = mr == dfd
        print("[%s] RDD reduceByKey == groupBy DataFrames: %s (%d claves)" % (level, same, len(mr)))
        if not same:
            for k in sorted(set(mr) | set(dfd), key=str):
                if mr.get(k) != dfd.get(k):
                    print("   diferencia en %s: rdd=%s df=%s" % (k, mr.get(k), dfd.get(k)))
            sys.exit("la validación contra groupBy falló")

        for key, (c, d, r, n, b) in mr.items():
            results.append((level, key, int(c), int(d), float(rate(c, d)), int(r),
                            float(100.0 * n / r) if r else None, int(b)))

    out = spark.createDataFrame(results, "level string, key string, closures long, business_days long, "
                                         "closure_rate_pct double, reviews long, pct_negative double, businesses long")
    out.write.format("mongodb").mode("overwrite").option("database", MONGO_DB).option("collection", "closure_stats").save()
    print("closure_stats escrita: %d filas" % out.count())
    out.where("level = 'category' and business_days >= 100000").orderBy(F.desc("closure_rate_pct")).show(8, False)
    spark.stop()


if __name__ == "__main__":
    main()
