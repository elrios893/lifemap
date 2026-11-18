#!/usr/bin/env bash
# Prueba de humo del flujo (Entrega 2): publica N mensajes en Kafka y verifica que aparecen CLASIFICADOS en MongoDB.
#
# Usa el código NUEVO (imagen lifemap-spark recién construida) pero en un entorno aislado, para poder correr ANTES de desplegar:
# topic `reviews_smoke`, colecciones `smoke_*` y checkpoint propio. No toca el flujo ni los datos reales. Si falla, sale con
# código 1 y el pipeline de Jenkins no despliega.
#
# Verifica por cada mensaje: sentimiento válido, probabilidad en [0,1], marca de procesamiento, geohash y que el modelo
# que lo clasificó es el versionado (version.json).
#
# Uso: ./scripts/smoke_stream.sh           (Jenkins pasa ENV_FILE=<ruta del .env>)
# Variables: SMOKE_MESSAGES (100), ENV_FILE
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

N="${SMOKE_MESSAGES:-100}"
TOPIC=reviews_smoke
NAME=lifemap-smoke-stream
PROJECT="${COMPOSE_PROJECT_NAME:-lifemap}"
dc() { docker compose ${ENV_FILE:+--env-file "$ENV_FILE"} "$@"; }
mongo_js() {   # el JS viaja en una variable de entorno (sin problemas de comillas) y se imprime lo que haga print()
  dc exec -T -e JS="$1" mongo sh -c 'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin lifemap --quiet --eval "$JS"'
}
say() { echo "[humo $(date +%H:%M:%S)] $*"; }
fail() { say "FALLA: $*"; docker logs --tail 40 "$NAME" 2>&1 | grep -v "INFO\|WARN" | tail -15 || true; exit 1; }

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  dc exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --delete --topic "$TOPIC" --if-exists >/dev/null 2>&1 || true
  mongo_js '["smoke_reviews_stream","smoke_geo_windows","smoke_stream_status","smoke_alerts","smoke_risk_scores"].forEach(c => db.getCollection(c).drop())' >/dev/null 2>&1 || true
}
trap cleanup EXIT

say "versión de modelo esperada (version.json)"
EXPECTED=$(docker run --rm -v "${PROJECT}_models":/models:ro --entrypoint cat lifemap-spark:latest /models/version.json | grep -oE '"sha256": *"[0-9a-f]{12}' | grep -oE '[0-9a-f]{12}$') && [ -n "$EXPECTED" ] || fail "no se pudo leer /models/version.json"
say "modelo versionado: $EXPECTED"

say "infraestructura (Mongo y Kafka)"
dc up -d --wait --wait-timeout 180 mongo kafka >/dev/null || fail "Mongo o Kafka no quedaron sanos"
cleanup 2>/dev/null || true
dc exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --create --if-not-exists --topic "$TOPIC" --partitions 3 --replication-factor 1 >/dev/null

say "arrancando el streaming nuevo en aislamiento (prefijo smoke_, topic $TOPIC)"
STREAM_MEMORY=900m dc run -d --no-deps --name "$NAME" -e STREAM_PREFIX=smoke_ -e KAFKA_TOPIC="$TOPIC" -e CHECKPOINT_DIR=/tmp/smoke_ckpt \
  -e TRIGGER_SECONDS=2 -e STREAM_MEMORY=800m stream >/dev/null
for i in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME" 2>/dev/null)" = "true" ] || fail "el streaming de prueba se detuvo"
  [ "$(mongo_js 'print(db.smoke_stream_status.countDocuments({}))' | tr -d '[:space:]')" = "1" ] && break
  sleep 5
  [ "$i" = 60 ] && fail "el streaming no arrancó en 5 minutos"
done
say "streaming listo"

say "publicando $N mensajes"
dc run --rm --no-deps -e KAFKA_TOPIC="$TOPIC" producer --limit "$N" --seconds-per-month 0 2>&1 | grep -E "listo|reseñas posteriores" || fail "el productor no publicó"

say "esperando a que aparezcan clasificados en MongoDB"
for i in $(seq 1 60); do
  got=$(mongo_js 'print(db.smoke_reviews_stream.countDocuments({}))' | tr -d '[:space:]')
  [ "$got" = "$N" ] && break
  sleep 3
  [ "$i" = 60 ] && fail "llegaron $got de $N mensajes a MongoDB"
done

res=$(mongo_js "const d = db.smoke_reviews_stream;
  const ok = d.countDocuments({sentiment: {\$in: ['negative','neutral','positive']}, probability: {\$gte: 0, \$lte: 1},
    processed_at: {\$type: 'date'}, geohash: {\$type: 'string'}, model_version: '$EXPECTED'});
  const posteriores = d.countDocuments({date: {\$gt: new Date('${CUTOFF_T:-2021-01-19}')}});
  print(d.countDocuments({}) + ' ' + ok + ' ' + posteriores)" | tr -d '\r')
read -r total ok posteriores <<< "$res"
say "mensajes en Mongo: $total | con predicción, probabilidad, marca de procesamiento, geohash y modelo versionado: $ok | posteriores a T: $posteriores"
[ "$total" = "$N" ] && [ "$ok" = "$N" ] && [ "$posteriores" = "$N" ] || fail "no todos los mensajes salieron bien clasificados"
say "PRUEBA DE HUMO OK"
