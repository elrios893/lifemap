#!/usr/bin/env bash
# Pipeline completo de datos de la Entrega 1, sobre el sistema ya levantado (docker compose up -d).
#   descarga Kaggle -> limpieza Dask -> carga Mongo GeoJSON -> vida de negocios
#   -> MapReduce de tasas -> sentimiento (NB y LR) -> balanceo
#
# Uso:  ./scripts/run_pipeline.sh            (todo el área, p. ej. > 1.000.000 reseñas)
#       SAMPLE_REVIEWS=200000 ./scripts/run_pipeline.sh   (muestra para desarrollo local)
# Requiere en .env: MONGO_USER, MONGO_PASSWORD, KAGGLE_USERNAME, KAGGLE_API_TOKEN.
set -euo pipefail
cd "$(dirname "$0")/.."

SAMPLE_REVIEWS="${SAMPLE_REVIEWS:-0}"
NET="${COMPOSE_PROJECT_NAME:-lifemap}_default"
VOL="${COMPOSE_PROJECT_NAME:-lifemap}_data"
MONGO_PASSWORD="$(grep '^MONGO_PASSWORD=' .env | cut -d= -f2- | tr -d '\r')"
MONGO_USER="$(grep '^MONGO_USER=' .env | cut -d= -f2- | tr -d '\r')"
export MSYS_NO_PATHCONV=1

ingest() { docker run --rm --network "$NET" --env-file .env -v "$VOL":/data "$@" lifemap-ingest:latest; }
spark_job() {
  docker exec -e MONGO_URI="mongodb://$MONGO_USER:$MONGO_PASSWORD@mongo:27017/?authSource=admin" \
    "$(docker compose ps -q spark-master)" /opt/spark/bin/spark-submit --master spark://spark-master:7077 \
    --driver-memory "${DRIVER_MEMORY:-1g}" --executor-memory "${EXECUTOR_MEMORY:-2500m}" \
    --conf spark.jars.ivy=/tmp/ivy "$@"
}
step() { echo; echo "=== $(date +%H:%M:%S) $*"; }

step "1/7 Descarga de Yelp (API de Kaggle)";           ingest python download.py
step "2/7 Limpieza con Dask (SAMPLE_REVIEWS=$SAMPLE_REVIEWS)"; ingest -e SAMPLE_REVIEWS="$SAMPLE_REVIEWS" python clean.py
step "3/7 Carga a MongoDB (GeoJSON + 2dsphere)";        ingest python load_mongo.py
step "4/7 Vida de los negocios (días-negocio, evento, censura)"; ingest python life.py
step "5/7 MapReduce: tasas de cierre";                  spark_job /opt/jobs/mapreduce_closure.py
step "6/7 Sentimiento: Naive Bayes y regresión logística"; spark_job /opt/jobs/sentiment_train.py
step "7/7 Balanceo de carga";                           spark_job /opt/jobs/balanceo.py 5
step "LISTO"
