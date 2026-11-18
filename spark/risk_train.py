"""Modelo de riesgo de cierre de un negocio (Entrega 2; patrón de KafkaMed aplicado a negocios).

Conjunto de entrenamiento (todo medido contra la fecha de corte T):
  * Variables: solo con reseñas hasta T (spark/risk_features.py, regla anti-fuga).
  * Etiqueta = 1 si el negocio está cerrado (is_open = 0) y su última reseña cae entre T y T + 12 meses.
    Etiqueta = 0 si sigue con actividad después de ese plazo, o sigue abierto.
  * Se EXCLUYEN los negocios sin actividad después de T (última reseña <= T) y los que no tienen reseñas hasta T.

Evaluación: validación cruzada de 5 pliegues repartidos por hash de business_id (cada negocio es una fila y cae en un solo
pliegue, así que ninguno aparece a la vez en entrenamiento y prueba). Las métricas salen de las predicciones fuera de pliegue:
AUC-ROC, AUC-PR (la principal: la clase positiva es rara) y recall/precisión en el umbral elegido (el que maximiza F1).
Se comparan regresión logística y GBT, ambos con pesos de clase por el desbalance.

Salidas en /models: risk_best (PipelineModel entrenado con todos los datos), risk_metrics.json.
Uso: spark-submit --master spark://spark-master:7077 /opt/jobs/risk_train.py
"""
import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from pymongo import MongoClient
from pyspark.ml import Pipeline
from pyspark.ml.classification import GBTClassifier, LogisticRegression
from pyspark.ml.evaluation import BinaryClassificationEvaluator
from pyspark.ml.feature import VectorAssembler
from pyspark.ml.functions import vector_to_array
from pyspark.sql import SparkSession, functions as F, types as T

from risk_features import FEATURES, compute, count_competitors

MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB = os.environ.get("MONGO_DB", "lifemap")
MODELS = os.environ.get("MODELS_DIR", "/models")
CUTOFF_T = os.environ.get("CUTOFF_T", "2021-01-19")
FOLDS = 5
CHUNK = 500


def horizon_end(t):
    """T + 12 meses, incluyendo el día completo."""
    return datetime(t.year + 1, t.month, t.day) + timedelta(days=1)


def build_rows(db, t):
    """Una fila por negocio evaluable: variables hasta T + etiqueta. Devuelve (filas, conteos de exclusión)."""
    t12 = horizon_end(t)
    biz = list(db.businesses.find({"life.last_review": {"$gt": t}},
                                  {"name": 1, "location": 1, "main_category": 1, "life.closed": 1, "life.last_review": 1}))
    sin_actividad = db.businesses.count_documents({"life": {"$exists": True}}) - len(biz)
    labels = {b["_id"]: int(b["life"]["closed"] == 1 and b["life"]["last_review"] <= t12) for b in biz}

    reviews = {}
    ids = list(labels)
    for i in range(0, len(ids), CHUNK):
        cur = db.reviews.find({"business_id": {"$in": ids[i:i + CHUNK]}, "date": {"$lte": t}}, {"business_id": 1, "stars": 1, "date": 1})
        for r in cur:
            reviews.setdefault(r["business_id"], []).append((r["date"], int(r["stars"])))

    with ThreadPoolExecutor(8) as pool:
        comp = dict(zip([b["_id"] for b in biz], pool.map(
            lambda b: count_competitors(db, b["location"], b["main_category"], b["_id"]), biz)))

    rows, sin_historia, meta = [], 0, {}
    for b in biz:
        f = compute(reviews.get(b["_id"], []), t, comp[b["_id"]])
        if f is None:
            sin_historia += 1
            continue
        rows.append((b["_id"], labels[b["_id"]]) + tuple(float(f[k]) for k in FEATURES))
        meta[b["_id"]] = {"name": b.get("name"), "main_category": b["main_category"], "geometry": b["location"], "features": f}
    return rows, {"sin_actividad_tras_T": sin_actividad, "sin_reseñas_hasta_T": sin_historia}, meta


def best_threshold(scored):
    """Umbral que maximiza F1 sobre las predicciones fuera de pliegue [(puntaje, etiqueta)]."""
    pos = sum(l for _, l in scored)
    best = (0.0, 0.5, 0.0, 0.0)
    tp = fp = 0
    for score, label in sorted(scored, key=lambda x: -x[0]):
        tp, fp = tp + label, fp + (1 - label)
        prec, rec = tp / (tp + fp), tp / pos
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if f1 > best[0]:
            best = (f1, score, prec, rec)
    return {"threshold": best[1], "f1": best[0], "precision": best[2], "recall": best[3]}


def fingerprint(path):
    h = hashlib.sha256()
    for root, _, files in sorted(os.walk(path)):
        for f in sorted(files):
            fp = os.path.join(root, f)
            h.update(os.path.relpath(fp, path).replace("\\", "/").encode())
            with open(fp, "rb") as fh:
                h.update(fh.read())
    return h.hexdigest()


def main():
    t = datetime.fromisoformat(CUTOFF_T)
    spark = (SparkSession.builder.appName("risk_train").config("spark.sql.shuffle.partitions", "8")
             .config("spark.ui.enabled", "false").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")

    mongo = MongoClient(MONGO_URI)[MONGO_DB]
    rows, excl, meta = build_rows(mongo, t)
    n, n_pos = len(rows), sum(r[1] for r in rows)
    print(f"negocios evaluables: {n:,} | cierres (etiqueta 1): {n_pos:,} ({n_pos / n:.2%}) | excluidos: {excl}", flush=True)
    if n_pos < 5:
        raise SystemExit("muy pocos positivos para entrenar")

    schema = T.StructType([T.StructField("business_id", T.StringType()), T.StructField("label", T.DoubleType())]
                          + [T.StructField(k, T.DoubleType()) for k in FEATURES])
    df = spark.createDataFrame([(r[0], float(r[1])) + r[2:] for r in rows], schema)
    w_pos = (n - n_pos) / n_pos   # peso de la clase rara
    df = (df.withColumn("w", F.when(F.col("label") == 1.0, F.lit(w_pos)).otherwise(F.lit(1.0)))
            .withColumn("fold", F.abs(F.hash("business_id")) % FOLDS).cache())
    print("positivos por pliegue:", {r["fold"]: r["n"] for r in df.where("label = 1").groupBy("fold").agg(F.count("*").alias("n")).collect()}, flush=True)

    def pipeline(name):
        asm = VectorAssembler(inputCols=FEATURES, outputCol="features")
        clf = (LogisticRegression(maxIter=100, regParam=0.01, weightCol="w") if name == "logistic_regression"
               else GBTClassifier(maxIter=40, maxDepth=3, seed=7, weightCol="w"))
        return Pipeline(stages=[asm, clf])

    ev = {m: BinaryClassificationEvaluator(rawPredictionCol="score", labelCol="label", metricName=m)
          for m in ("areaUnderROC", "areaUnderPR")}
    report = {"cutoff_t": CUTOFF_T, "horizon_end": horizon_end(t).date().isoformat(), "features": FEATURES,
              "businesses": n, "positives": n_pos, "prevalence": round(n_pos / n, 4), "excluded": excl, "folds": FOLDS,
              "class_weight_positive": round(w_pos, 2), "models": []}
    oof_scores = {}
    for name in ("logistic_regression", "gradient_boosted_trees"):
        parts = []
        for k in range(FOLDS):
            model = pipeline(name).fit(df.where(F.col("fold") != k))
            pred = model.transform(df.where(F.col("fold") == k))
            parts.append(pred.select("business_id", "label", vector_to_array("probability")[1].alias("score")))
        oof = parts[0]
        for p in parts[1:]:
            oof = oof.union(p)
        oof = oof.cache()
        collected = oof.collect()
        oof_scores[name] = {r["business_id"]: float(r["score"]) for r in collected}
        scored = [(float(r["score"]), int(r["label"])) for r in collected]
        th = best_threshold(scored)
        m = {"model": name, "auc_roc": round(ev["areaUnderROC"].evaluate(oof), 4), "auc_pr": round(ev["areaUnderPR"].evaluate(oof), 4),
             "auc_pr_baseline": round(n_pos / n, 4), **{k: round(v, 4) for k, v in th.items()},
             "flagged_pct": round(sum(1 for s, _ in scored if s >= th["threshold"]) / n * 100, 2)}
        report["models"].append(m)
        print(f"== {name}: AUC-ROC={m['auc_roc']} AUC-PR={m['auc_pr']} (azar={m['auc_pr_baseline']}) | umbral={m['threshold']:.3f} "
              f"recall={m['recall']} precisión={m['precision']} F1={m['f1']} | marca {m['flagged_pct']}% de los negocios", flush=True)

    best = max(report["models"], key=lambda m: m["auc_pr"])
    report["best_model"], report["threshold"] = best["model"], best["threshold"]
    final = pipeline(best["model"]).fit(df)
    path = f"{MODELS}/risk_best"
    shutil.rmtree(path, ignore_errors=True)
    final.write().overwrite().save(path)
    report["sha256"] = fingerprint(path)
    report["trained_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(f"{MODELS}/risk_metrics.json", "w") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    # Puntajes base (fuera de pliegue: ningún negocio se puntúa con un modelo que lo vio entrenar) para /risk/near.
    now, version = datetime.now(timezone.utc), report["sha256"][:12]
    docs = []
    for bid, p in oof_scores[best["model"]].items():
        m = meta[bid]
        docs.append({"_id": bid, "business_id": bid, "name": m["name"], "main_category": m["main_category"],
                     "geometry": m["geometry"], "probability": round(p, 4), "as_of": t, "source": "baseline",
                     "alert": False, "features": m["features"], "model_version": version, "updated_at": now,
                     "baseline": {"probability": round(p, 4), "as_of": t}})
    mongo.risk_scores.delete_many({})
    mongo.risk_scores.insert_many(docs)
    mongo.risk_scores.create_index([("geometry", "2dsphere")])
    mongo.risk_scores.create_index([("probability", -1)])
    print(f"puntajes base guardados en risk_scores: {len(docs):,}")
    print(f"\nmejor modelo por AUC-PR: {best['model']} -> {path} (versión {report['sha256'][:12]})")
    spark.stop()


if __name__ == "__main__":
    main()
