#!/usr/bin/env bash
# Restaura desde S3 lo que dejó backup_to_s3.sh. Si no hay respaldo, termina sin error (entonces se corre
# scripts/run_pipeline.sh para calcularlo todo desde cero, ~40 min).
#
# Uso (en la VM, con el sistema levantado):  ./scripts/restore_from_s3.sh
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

env_get() { grep "^$1=" .env | cut -d= -f2- | tr -d '\r'; }
BUCKET="$(env_get S3_BUCKET)"; PREFIX="$(env_get S3_PREFIX)"; PREFIX="${PREFIX:-lifemap}"
MU="$(env_get MONGO_USER)"; MP="$(env_get MONGO_PASSWORD)"; DB="$(env_get MONGO_DB)"; DB="${DB:-lifemap}"
PROJECT="${COMPOSE_PROJECT_NAME:-lifemap}"
SRC="s3://$BUCKET/$PREFIX/backup"

if ! aws s3 ls "$SRC/mongo.archive.gz" >/dev/null 2>&1; then
  echo "No hay respaldo en $SRC: nada que restaurar. Corre scripts/run_pipeline.sh para calcular los datos."
  exit 0
fi
echo "Respaldo encontrado:"; aws s3 cp "$SRC/manifest.json" - 2>/dev/null || true; echo

echo "esperando a MongoDB..."
for _ in $(seq 1 60); do
  docker compose exec -T mongo mongosh -u "$MU" -p "$MP" --authenticationDatabase admin --quiet --eval 'db.adminCommand("ping").ok' >/dev/null 2>&1 && break
  sleep 5
done

echo "1/2 MongoDB <- $SRC/mongo.archive.gz"
aws s3 cp "$SRC/mongo.archive.gz" - \
  | docker compose exec -T mongo mongorestore -u "$MU" -p "$MP" --authenticationDatabase admin --archive --gzip --drop --quiet

echo "2/2 Modelos y métricas <- $SRC/models.tgz"
aws s3 cp "$SRC/models.tgz" - \
  | docker run -i --rm --user root -v "${PROJECT}_models":/m --entrypoint sh lifemap-spark:latest \
      -c 'tar xzf - -C /m && chown -R spark /m'

docker compose exec -T mongo mongosh -u "$MU" -p "$MP" --authenticationDatabase admin "$DB" --quiet \
  --eval 'printjson({businesses: db.businesses.countDocuments({}), reviews: db.reviews.countDocuments({}), closure_stats: db.closure_stats.countDocuments({}), indices: db.businesses.getIndexes().map(i => i.name)})'
echo "restauración completa"
