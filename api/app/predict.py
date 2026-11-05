"""Inferencia de sentimiento con el modelo entrenado en Spark (/models/sentiment_best).

PySpark corre en modo local dentro de la API y se inicia la primera vez que se pide una predicción (la JVM tarda
unos segundos en arrancar). Se aplica la MISMA limpieza que en el entrenamiento.
"""
import os
import re
import threading

MODEL_PATH = os.environ.get("SENTIMENT_MODEL", "/models/sentiment_best")
LABELS = ["negative", "neutral", "positive"]
_lock = threading.Lock()
_state = {}


def clean_text(text: str) -> str:
    """Igual que sentiment_train.py: minúsculas, sin URLs y solo letras."""
    return re.sub(r"https?://\S+|[^a-z\s]", " ", text.lower())


def model_available() -> bool:
    return os.path.isdir(MODEL_PATH)


def _load():
    with _lock:
        if "model" not in _state:
            from pyspark.ml import PipelineModel
            from pyspark.sql import SparkSession
            spark = (SparkSession.builder.master("local[1]").appName("lifemap-predict")
                     .config("spark.driver.memory", "512m").config("spark.ui.enabled", "false")
                     .config("spark.sql.shuffle.partitions", "1").getOrCreate())
            spark.sparkContext.setLogLevel("ERROR")
            _state["spark"], _state["model"] = spark, PipelineModel.load(MODEL_PATH)
    return _state["spark"], _state["model"]


def predict_sentiment(text: str) -> dict:
    spark, model = _load()
    row = model.transform(spark.createDataFrame([(clean_text(text),)], ["clean"])).select("prediction", "probability").first()
    probs = [float(p) for p in row["probability"]]
    return {"sentiment": LABELS[int(row["prediction"])], "probabilities": dict(zip(LABELS, [round(p, 4) for p in probs]))}
