#!/usr/bin/env bash
# Respalda en S3 lo que costó calcular: la base MongoDB (negocios con vida y sentimiento, reseñas, tasas), los modelos
# de Spark, las métricas y el reporte de limpieza. Con esto se puede hacer `terraform destroy` y rearmar en minutos.
#
# Uso (en la VM, con el sistema levantado):  ./scripts/backup_to_s3.sh
# Requiere: .env con S3_BUCKET/S3_PREFIX, aws cli y el rol de instancia con escritura en s3://BUCKET/PREFIX/*
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1

env_get() { grep "^$1=" .env | cut -d= -f2- | tr -d '\r'; }
BUCKET="$(env_get S3_BUCKET)"; PREFIX="$(env_get S3_PREFIX)"; PREFIX="${PREFIX:-lifemap}"
MU="$(env_get MONGO_USER)"; MP="$(env_get MONGO_PASSWORD)"; DB="$(env_get MONGO_DB)"; DB="${DB:-lifemap}"
PROJECT="${COMPOSE_PROJECT_NAME:-lifemap}"
DEST="s3://$BUCKET/$PREFIX/backup"
[ -n "$BUCKET" ] || { echo "falta S3_BUCKET en .env"; exit 1; }

echo "1/4 MongoDB -> $DEST/mongo.archive.gz"
docker compose exec -T mongo mongodump -u "$MU" -p "$MP" --authenticationDatabase admin --db "$DB" --archive --gzip --quiet \
  | aws s3 cp - "$DEST/mongo.archive.gz"

echo "2/4 Modelos y métricas (volumen models) -> $DEST/models.tgz"
docker run --rm -v "${PROJECT}_models":/m --entrypoint tar lifemap-spark:latest czf - -C /m . \
  | aws s3 cp - "$DEST/models.tgz"

echo "3/4 Reporte de limpieza -> $DEST/clean_report.json"
docker run --rm -v "${PROJECT}_data":/d --entrypoint cat lifemap-ingest:latest /d/clean/report.json \
  | aws s3 cp - "$DEST/clean_report.json"

echo "4/4 Manifiesto"
COUNTS="$(docker compose exec -T mongo mongosh -u "$MU" -p "$MP" --authenticationDatabase admin "$DB" --quiet \
  --eval 'print(JSON.stringify({businesses: db.businesses.countDocuments({}), reviews: db.reviews.countDocuments({}), closure_stats: db.closure_stats.countDocuments({})}))' | tr -d '\r')"
printf '{"created_utc":"%s","commit":"%s","counts":%s}\n' "$(date -u +%FT%TZ)" "$(git rev-parse HEAD)" "$COUNTS" \
  | aws s3 cp - "$DEST/manifest.json"

echo; aws s3 ls "$DEST/" --human-readable
