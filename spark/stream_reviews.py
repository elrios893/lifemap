"""Structured Streaming de la Entrega 2: Kafka -> inferencia de sentimiento -> MongoDB, y ventanas por geohash.

Una sola aplicación, dos consultas sobre el topic `reviews`:
  reviews : clasifica cada reseña con el modelo guardado en la Entrega 1 (/models/sentiment_best, SIN reentrenar) y la
            escribe en `reviews_stream` con predicción, probabilidad, versión del modelo y marca de procesamiento.
  windows : por celda de geohash, ventanas de 30 días con watermark de 7 días sobre el campo `date` de la reseña
            (tiempo del evento, no de ingesta); cuenta reseñas y % negativas, guarda cada ventana con la geometría de su
            celda en `geo_windows` y marca el hotspot comparando con la ventana anterior de la misma celda.

Alertas (E2.7): en el mismo foreachBatch, para los negocios que recibieron reseñas en el micro-lote se recalculan las variables
de riesgo con la historia hasta T más lo recibido por el flujo (spark/risk_features.py), se puntúan con /models/risk_best y los
que superan el umbral del modelo se guardan en `alerts` con su geometría. Todos los puntajes quedan en `risk_scores`.

Además un listener escribe en `stream_status` el retraso del consumidor (lo lee /health).

Regla de hotspot: la celda es hotspot si su % negativo sube HOTSPOT_DELTA puntos porcentuales frente a la ventana anterior,
y ambas ventanas tienen al menos HOTSPOT_MIN_N reseñas (con pocas reseñas el porcentaje es ruido).

Variables: MONGO_URI, MONGO_DB, KAFKA_BOOTSTRAP, KAFKA_TOPIC, CUTOFF_T, MODELS_DIR, CHECKPOINT_DIR, STREAM_PREFIX, TRIGGER_SECONDS,
           HOTSPOT_DELTA (puntos, 10), HOTSPOT_MIN_N (10), MAX_OFFSETS_PER_TRIGGER (2000).
"""
import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone

from pymongo import ASCENDING, GEOSPHERE, MongoClient, UpdateOne
from pyspark.ml import PipelineModel
from pyspark.ml.functions import vector_to_array
from pyspark.sql import SparkSession, functions as F, types as T
from pyspark.sql.streaming import StreamingQueryListener

from risk_features import FEATURES, compute, count_competitors

MONGO_URI = os.environ["MONGO_URI"]
MONGO_DB = os.environ.get("MONGO_DB", "lifemap")
BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "kafka:9092")
TOPIC = os.environ.get("KAFKA_TOPIC", "reviews")
CUTOFF_T = os.environ.get("CUTOFF_T", "2021-01-19")
MODELS = os.environ.get("MODELS_DIR", "/models")
CHECKPOINTS = os.environ.get("CHECKPOINT_DIR", "/checkpoints")
# Prefijo de las colecciones que escribe el flujo. Vacío en producción; la prueba de humo de Jenkins usa "smoke_" para no tocar
# los datos reales (junto con KAFKA_TOPIC=reviews_smoke y su propio checkpoint).
PREFIX = os.environ.get("STREAM_PREFIX", "")
TRIGGER = f'{os.environ.get("TRIGGER_SECONDS", "5")} seconds'
HOTSPOT_DELTA = float(os.environ.get("HOTSPOT_DELTA", "10"))
HOTSPOT_MIN_N = int(os.environ.get("HOTSPOT_MIN_N", "10"))
MAX_OFFSETS = os.environ.get("MAX_OFFSETS_PER_TRIGGER", "2000")
WINDOW_DAYS, WATERMARK_DAYS = 30, 7
LABELS = ["negative", "neutral", "positive"]
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"

SCHEMA = T.StructType([
    T.StructField("review_id", T.StringType()), T.StructField("business_id", T.StringType()),
    T.StructField("stars", T.IntegerType()), T.StructField("text", T.StringType()),
    T.StructField("date", T.StringType())])


def geohash_bbox(gh):
    """(lat_min, lat_max, lon_min, lon_max) de una celda de geohash."""
    lat, lon, even = [-90.0, 90.0], [-180.0, 180.0], True
    for ch in gh:
        v = _BASE32.index(ch)
        for i in range(4, -1, -1):
            rng = lon if even else lat
            mid = (rng[0] + rng[1]) / 2
            rng[0 if (v >> i) & 1 else 1] = mid
            even = not even
    return lat[0], lat[1], lon[0], lon[1]


def cell_center(gh):
    la0, la1, lo0, lo1 = geohash_bbox(gh)
    return {"type": "Point", "coordinates": [(lo0 + lo1) / 2, (la0 + la1) / 2]}


def cell_polygon(gh):
    la0, la1, lo0, lo1 = geohash_bbox(gh)
    return {"type": "Polygon", "coordinates": [[[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]]]}


def window_offset_days():
    """Desplazamiento para que las ventanas de 30 días empiecen exactamente en T (y no en una rejilla arbitraria)."""
    return (date.fromisoformat(CUTOFF_T) - date(1970, 1, 1)).days % WINDOW_DAYS


def utcnow():
    return datetime.now(timezone.utc)


def mongo_db():
    return MongoClient(MONGO_URI)[MONGO_DB]


def read_model_version():
    with open(f"{MODELS}/version.json") as fh:
        return json.load(fh)


def scored_stream(spark, model, businesses):
    """Kafka -> JSON -> limpieza (igual que en el entrenamiento) -> modelo -> geohash del negocio."""
    raw = (spark.readStream.format("kafka").option("kafka.bootstrap.servers", BOOTSTRAP)
           .option("subscribe", TOPIC).option("startingOffsets", "earliest")
           .option("maxOffsetsPerTrigger", MAX_OFFSETS).option("failOnDataLoss", "false").load())
    msg = (raw.select(F.from_json(F.col("value").cast("string"), SCHEMA).alias("m"))
           .select("m.*").withColumn("event_time", F.to_timestamp("date")))
    clean = msg.withColumn("clean", F.regexp_replace(F.lower(F.col("text")), "https?://\\S+|[^a-z\\s]", " "))
    pred = model.transform(clean).withColumn("p", vector_to_array("probability"))
    return (pred.withColumn("sentiment", F.element_at(F.array(*[F.lit(l) for l in LABELS]), F.col("prediction").cast("int") + 1))
            .withColumn("probability", F.array_max("p"))
            .join(F.broadcast(businesses), "business_id", "left")
            .select("review_id", "business_id", "stars", "text", "event_time", "geohash", "sentiment", "probability", "p"))


def load_risk():
    """Modelo de riesgo y su umbral (None si todavía no se entrenó: el flujo sigue sin alertas)."""
    path = f"{MODELS}/risk_metrics.json"
    if not os.path.exists(path):
        print("sin modelo de riesgo (/models/risk_metrics.json): el flujo corre sin alertas", flush=True)
        return None
    with open(path) as fh:
        meta = json.load(fh)
    if meta["cutoff_t"] != CUTOFF_T:
        raise SystemExit(f'el modelo de riesgo se entrenó con T={meta["cutoff_t"]} y el flujo usa T={CUTOFF_T}')
    print(f'modelo de riesgo {meta["best_model"]} versión {meta["sha256"][:12]} umbral={meta["threshold"]:.3f}', flush=True)
    return {"model": PipelineModel.load(f"{MODELS}/risk_best"), "threshold": float(meta["threshold"]),
            "version": meta["sha256"][:12]}


_competitors = {}   # la densidad de competidores no cambia durante el flujo: se calcula una vez por negocio


def score_and_alert(spark, db, rows, risk, now):
    """Actualiza las variables de los negocios del lote, los puntúa y guarda las alertas."""
    t = datetime.fromisoformat(CUTOFF_T)
    as_of = {}
    for r in rows:
        as_of[r["business_id"]] = max(as_of.get(r["business_id"], r["event_time"]), r["event_time"])
    ids = list(as_of)
    biz = {b["_id"]: b for b in db.businesses.find({"_id": {"$in": ids}}, {"name": 1, "main_category": 1, "location": 1, "is_open": 1})}
    hist, live = {}, {}
    for r in db.reviews.find({"business_id": {"$in": ids}, "date": {"$lte": t}}, {"business_id": 1, "stars": 1, "date": 1}):
        hist.setdefault(r["business_id"], []).append((r["date"], int(r["stars"])))
    for r in db[PREFIX + "reviews_stream"].find({"business_id": {"$in": ids}}, {"business_id": 1, "stars": 1, "date": 1}):
        live.setdefault(r["business_id"], []).append((r["date"], int(r["stars"])))

    feats = {}
    for bid in ids:
        if bid not in biz:
            continue
        if bid not in _competitors:
            b = biz[bid]
            _competitors[bid] = count_competitors(db, b["location"], b["main_category"], bid)
        f = compute(hist.get(bid, []) + live.get(bid, []), as_of[bid], _competitors[bid])
        if f:
            feats[bid] = f
    if not feats:
        return 0
    order = list(feats)
    df = spark.createDataFrame([tuple(float(feats[b][k]) for k in FEATURES) for b in order], FEATURES)
    probs = [float(x["p"]) for x in risk["model"].transform(df).select(vector_to_array("probability")[1].alias("p")).collect()]

    score_ops, alert_ops, n_alerts = [], [], 0
    for bid, p in zip(order, probs):
        b, hit = biz[bid], p >= risk["threshold"]
        n_alerts += hit
        score_ops.append(UpdateOne({"_id": bid}, {"$set": {
            "business_id": bid, "name": b.get("name"), "main_category": b.get("main_category"), "geometry": b["location"],
            "probability": round(p, 4), "as_of": as_of[bid], "source": "stream", "alert": hit, "features": feats[bid],
            "model_version": risk["version"], "updated_at": now}}, upsert=True))
        if hit:
            alert_ops.append(UpdateOne({"_id": bid}, {"$set": {
                "business_id": bid, "name": b.get("name"), "main_category": b.get("main_category"), "geometry": b["location"],
                "probability": round(p, 4), "threshold": risk["threshold"], "as_of": as_of[bid], "features": feats[bid],
                "model_version": risk["version"], "active": True, "updated_at": now,
                "dataset_is_open": int(b.get("is_open", 1))},   # solo para evaluar a posteriori las alertas
                "$setOnInsert": {"created_at": now}}, upsert=True))
        else:   # si ya tenía alerta y el puntaje bajó del umbral, deja de estar activa
            alert_ops.append(UpdateOne({"_id": bid, "active": True}, {"$set": {
                "active": False, "probability": round(p, 4), "as_of": as_of[bid], "updated_at": now}}))
    db[PREFIX + "risk_scores"].bulk_write(score_ops, ordered=False)
    db[PREFIX + "alerts"].bulk_write(alert_ops, ordered=False)
    return n_alerts


def make_review_writer(version, risk=None):
    def write(batch, epoch_id):
        rows = batch.collect()
        if not rows:
            return
        db, now = mongo_db(), utcnow()
        ops = [UpdateOne({"_id": r["review_id"]}, {"$set": {
            "business_id": r["business_id"], "stars": r["stars"], "text": r["text"], "date": r["event_time"],
            "geohash": r["geohash"], "sentiment": r["sentiment"], "probability": round(float(r["probability"]), 4),
            "probabilities": dict(zip(LABELS, [round(float(x), 4) for x in r["p"]])),
            "processed_at": now, "batch_id": int(epoch_id), "model_version": version["sha256"][:12]}}, upsert=True)
            for r in rows]
        db[PREFIX + "reviews_stream"].bulk_write(ops, ordered=False)
        if risk:
            n = score_and_alert(batch.sparkSession, db, rows, risk, now)
            print(f"lote {epoch_id}: {len(rows)} reseñas, alertas nuevas o vigentes: {n}", flush=True)
    return write


def write_windows(batch, epoch_id):
    rows = batch.collect()
    if not rows:
        return
    db, now = mongo_db(), utcnow()
    step = timedelta(days=WINDOW_DAYS)
    wid = lambda gh, start: f"{gh}|{start:%Y-%m-%d}"  # noqa: E731
    ops, touched = [], []
    for r in rows:
        start, end = r["window"]["start"], r["window"]["end"]
        n, neg = int(r["n"]), int(r["negatives"])
        touched.append((r["geohash"], start))
        ops.append(UpdateOne({"_id": wid(r["geohash"], start)}, {"$set": {
            "geohash": r["geohash"], "window_start": start, "window_end": end, "n": n, "negatives": neg,
            "pct_negative": round(neg / n * 100.0, 2), "geometry": cell_polygon(r["geohash"]),
            "center": cell_center(r["geohash"]), "updated_at": now, "batch_id": int(epoch_id)}}, upsert=True))
    db[PREFIX + "geo_windows"].bulk_write(ops, ordered=False)

    # Hotspot: se recalcula para cada ventana tocada Y para la siguiente (su ventana anterior pudo cambiar), con los conteos
    # ya guardados. Así el resultado depende solo de los datos y no del ritmo con que llegaron los lotes.
    todo = {(gh, s) for gh, s in touched} | {(gh, s + step) for gh, s in touched}
    ids = {wid(gh, s) for gh, s in todo} | {wid(gh, s - step) for gh, s in todo}
    docs = {d["_id"]: d for d in db[PREFIX + "geo_windows"].find({"_id": {"$in": list(ids)}}, {"n": 1, "pct_negative": 1})}
    flags = []
    for gh, s in todo:
        cur, prev = docs.get(wid(gh, s)), docs.get(wid(gh, s - step))
        if not cur:
            continue
        delta = round(cur["pct_negative"] - prev["pct_negative"], 2) if prev else None
        hotspot = bool(prev and cur["n"] >= HOTSPOT_MIN_N and prev["n"] >= HOTSPOT_MIN_N and delta >= HOTSPOT_DELTA)
        flags.append(UpdateOne({"_id": wid(gh, s)}, {"$set": {
            "prev_pct_negative": prev["pct_negative"] if prev else None, "delta_pp": delta, "hotspot": hotspot}}))
    if flags:
        db[PREFIX + "geo_windows"].bulk_write(flags, ordered=False)


def start_heartbeat(spark, version, every=10):
    """Latido: sin datos, Spark no emite eventos de progreso, así que un hilo escribe cada pocos segundos que el job sigue vivo
    y si sus consultas están activas. /health lo usa para distinguir 'sin datos' de 'detenido'."""
    def beat():
        while True:
            try:
                queries = {q.name: bool(q.isActive) for q in spark.streams.active}
                mongo_db()[PREFIX + "stream_status"].update_one({"_id": "stream"}, {"$set": {
                    "heartbeat_at": utcnow(), "queries": queries, "model_version": version["sha256"][:12],
                    "cutoff_t": CUTOFF_T}}, upsert=True)
            except Exception as exc:  # noqa: BLE001  (un fallo de Mongo no debe tumbar el flujo)
                print("latido: no se pudo escribir en MongoDB:", exc, flush=True)
            time.sleep(every)
    threading.Thread(target=beat, name="heartbeat", daemon=True).start()


class LagListener(StreamingQueryListener):
    """Guarda en stream_status el retraso del consumidor: suma de (último offset disponible - offset procesado)."""

    def __init__(self, version):
        self.version = version

    def onQueryStarted(self, event):
        pass

    def onQueryTerminated(self, event):
        pass

    def onQueryProgress(self, event):
        p = event.progress
        if p.name != "reviews" or not p.sources:
            return
        src = p.sources[0]
        try:
            latest, end = json.loads(src.latestOffset)[TOPIC], json.loads(src.endOffset)[TOPIC]
            lag = sum(int(latest[k]) - int(end.get(k, 0)) for k in latest)
        except Exception:  # noqa: BLE001  (sin datos todavía)
            lag = None
        mongo_db()[PREFIX + "stream_status"].update_one({"_id": "stream"}, {"$set": {
            "consumer_lag": lag, "batch_id": int(p.batchId), "input_rows": int(p.numInputRows),
            "updated_at": utcnow(), "model_version": self.version["sha256"][:12], "cutoff_t": CUTOFF_T}}, upsert=True)


def main():
    spark = (SparkSession.builder.appName("stream_reviews")
             .config("spark.sql.session.timeZone", "UTC").config("spark.sql.shuffle.partitions", "4")
             .config("spark.mongodb.read.connection.uri", MONGO_URI).config("spark.ui.enabled", "false")
             .getOrCreate())
    spark.sparkContext.setLogLevel("WARN")

    version = read_model_version()
    model = PipelineModel.load(f"{MODELS}/sentiment_best")
    print(f'modelo {version["best_model"]} versión {version["sha256"][:12]} (corte T={version["cutoff_t"]})', flush=True)
    if version["cutoff_t"] != CUTOFF_T:
        raise SystemExit(f'el modelo se entrenó con T={version["cutoff_t"]} y el flujo usa T={CUTOFF_T}')

    db = mongo_db()
    db[PREFIX + "geo_windows"].create_index([("geometry", GEOSPHERE)])
    db[PREFIX + "geo_windows"].create_index([("geohash", ASCENDING), ("window_start", ASCENDING)])
    db[PREFIX + "geo_windows"].create_index([("center", GEOSPHERE)])
    db[PREFIX + "reviews_stream"].create_index([("business_id", ASCENDING), ("date", ASCENDING)])
    db[PREFIX + "alerts"].create_index([("geometry", GEOSPHERE)])
    db[PREFIX + "alerts"].create_index([("active", ASCENDING), ("probability", -1)])
    risk = load_risk()
    businesses = (spark.read.format("mongodb").option("database", MONGO_DB).option("collection", "businesses").load()
                  .select(F.col("_id").alias("business_id"), "geohash").where(F.col("geohash").isNotNull()).cache())
    print("negocios con geohash:", businesses.count(), flush=True)
    if businesses.count() == 0:
        raise SystemExit("MongoDB todavía no tiene negocios (¿restauración en curso?)")

    spark.streams.addListener(LagListener(version))
    stream = scored_stream(spark, model, businesses)

    (stream.writeStream.queryName("reviews").foreachBatch(make_review_writer(version, risk))
     .option("checkpointLocation", f"{CHECKPOINTS}/reviews").trigger(processingTime=TRIGGER).start())

    windows = (stream.where(F.col("geohash").isNotNull())
               .withWatermark("event_time", f"{WATERMARK_DAYS} days")
               .groupBy(F.window("event_time", f"{WINDOW_DAYS} days", f"{WINDOW_DAYS} days", f"{window_offset_days()} days"), "geohash")
               .agg(F.count("*").alias("n"), F.sum(F.when(F.col("sentiment") == "negative", 1).otherwise(0)).alias("negatives")))
    (windows.writeStream.queryName("windows").outputMode("update").foreachBatch(write_windows)
     .option("checkpointLocation", f"{CHECKPOINTS}/windows").trigger(processingTime=TRIGGER).start())

    start_heartbeat(spark, version)
    spark.streams.awaitAnyTermination()


if __name__ == "__main__":
    main()
