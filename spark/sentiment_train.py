"""Sentimiento en Spark: limpieza -> tokenización -> stopwords (inglés) -> HashingTF/IDF -> Naive Bayes y regresión logística.

Etiqueta (del enunciado): 1-2 estrellas = negativo (0), 3 = neutral (1), 4-5 = positivo (2).
Partición entrenamiento/prueba POR NEGOCIO: un mismo negocio nunca queda en los dos lados (evita fuga de información,
porque las reseñas de un negocio se parecen entre sí).

Salidas (volumen /models):
  /models/sentiment_nb, /models/sentiment_lr   PipelineModel de cada clasificador
  /models/sentiment_best                        copia del mejor por F1 macro (lo que carga /predict y, en E2, el streaming)
  /models/metrics.json                          métricas por clase, matriz de confusión, distribución y tiempos

Uso: spark-submit --master spark://spark-master:7077 /opt/jobs/sentiment_train.py
"""
import json
import os
import shutil
import time

from pyspark.ml import Pipeline
from pyspark.ml.classification import LogisticRegression, NaiveBayes
from pyspark.ml.feature import HashingTF, IDF, RegexTokenizer, StopWordsRemover
from pyspark.sql import SparkSession, functions as F

CLEAN = os.environ.get("CLEAN_DIR", "/data/clean")
MODELS = os.environ.get("MODELS_DIR", "/models")
NUM_FEATURES = int(os.environ.get("NUM_FEATURES", str(2 ** 16)))
TEST_PCT = 20
LABELS = ["negative", "neutral", "positive"]


def build_pipeline(classifier):
    """Mismo esquema que SentimentStream: limpieza, tokenización, stopwords, TF-IDF, clasificador."""
    tokenizer = RegexTokenizer(inputCol="clean", outputCol="tokens", pattern="\\s+", minTokenLength=2)
    stop = StopWordsRemover(inputCol="tokens", outputCol="filtered", stopWords=StopWordsRemover.loadDefaultStopWords("english"))
    tf = HashingTF(inputCol="filtered", outputCol="tf", numFeatures=NUM_FEATURES)
    idf = IDF(inputCol="tf", outputCol="features", minDocFreq=2)
    return Pipeline(stages=[tokenizer, stop, tf, idf, classifier])


def evaluate(pred, name, train_s):
    """Precision, recall y F1 por clase + matriz de confusión + accuracy, calculados desde el conteo (label, prediction)."""
    cm = {(int(r["label"]), int(r["prediction"])): r["count"]
          for r in pred.groupBy("label", "prediction").count().collect()}
    total = sum(cm.values())
    per_class = {}
    for i, lab in enumerate(LABELS):
        tp = cm.get((i, i), 0)
        fp = sum(cm.get((j, i), 0) for j in range(3)) - tp
        fn = sum(cm.get((i, j), 0) for j in range(3)) - tp
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        per_class[lab] = {"precision": round(p, 4), "recall": round(r, 4), "f1": round(f1, 4), "support": tp + fn}
    return {
        "model": name, "train_seconds": round(train_s, 1),
        "accuracy": round(sum(cm.get((i, i), 0) for i in range(3)) / total, 4),
        "macro_f1": round(sum(c["f1"] for c in per_class.values()) / 3, 4),
        "per_class": per_class,
        "confusion_matrix": {"rows_true_cols_pred": LABELS,
                             "values": [[cm.get((i, j), 0) for j in range(3)] for i in range(3)]},
    }


def main():
    spark = (SparkSession.builder.appName("sentiment_train")
             .config("spark.sql.shuffle.partitions", "16").getOrCreate())
    spark.sparkContext.setLogLevel("WARN")

    r = spark.read.parquet(f"{CLEAN}/review.parquet").select("review_id", "business_id", "stars", "text")
    df = (r.withColumn("label", F.when(F.col("stars") <= 2, 0.0).when(F.col("stars") == 3, 1.0).otherwise(2.0))
           # limpieza: minúsculas, quita URLs y todo lo que no sea letra
           .withColumn("clean", F.regexp_replace(F.lower(F.col("text")), "https?://\\S+|[^a-z\\s]", " ")))

    # Partición por negocio: el hash del business_id decide el lado, así todas sus reseñas quedan juntas.
    bucket = F.abs(F.hash("business_id")) % 100
    train, test = df.where(bucket >= TEST_PCT).cache(), df.where(bucket < TEST_PCT).cache()
    n_train, n_test = train.count(), test.count()
    shared = (train.select("business_id").distinct().join(test.select("business_id").distinct(), "business_id")).count()
    dist = {LABELS[int(row["label"])]: row["count"] for row in df.groupBy("label").count().collect()}
    print("distribución de clases:", dist)
    print("train: %d reseñas | test: %d reseñas | negocios en ambos lados: %d" % (n_train, n_test, shared))
    assert shared == 0, "fuga: hay negocios en train y test"

    report = {"class_distribution": dist, "train_reviews": n_train, "test_reviews": n_test,
              "businesses_in_both_splits": shared, "num_features": NUM_FEATURES, "models": []}
    fitted = {}
    for name, clf in (("naive_bayes", NaiveBayes(smoothing=1.0, modelType="multinomial")),
                      ("logistic_regression", LogisticRegression(maxIter=30, regParam=0.01, family="multinomial"))):
        t0 = time.time()
        model = build_pipeline(clf).fit(train)
        secs = time.time() - t0
        m = evaluate(model.transform(test), name, secs)
        report["models"].append(m)
        fitted[name] = model
        print("\n== %s (entrenó en %.1fs) accuracy=%.4f macroF1=%.4f" % (name, secs, m["accuracy"], m["macro_f1"]))
        for lab, c in m["per_class"].items():
            print("   %-9s P=%.3f R=%.3f F1=%.3f  n=%d" % (lab, c["precision"], c["recall"], c["f1"], c["support"]))
        print("   matriz (filas=real, cols=pred):", m["confusion_matrix"]["values"])

    best = max(report["models"], key=lambda m: m["macro_f1"])["model"]
    report["best_model"] = best
    os.makedirs(MODELS, exist_ok=True)
    for name, model in fitted.items():
        model.write().overwrite().save(f"{MODELS}/sentiment_{name}")
    shutil.rmtree(f"{MODELS}/sentiment_best", ignore_errors=True)
    shutil.copytree(f"{MODELS}/sentiment_{best}", f"{MODELS}/sentiment_best")
    with open(f"{MODELS}/metrics.json", "w") as fh:
        json.dump(report, fh, ensure_ascii=False, indent=2)
    print("\nmejor modelo por F1 macro:", best, "-> guardado en", f"{MODELS}/sentiment_best")
    spark.stop()


if __name__ == "__main__":
    main()
