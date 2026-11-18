#!/usr/bin/env bash
# Deja el flujo en cero para repetir la demostración: vacía el topic, el checkpoint de Spark y las colecciones del streaming.
# Hace falta porque, tras reproducir todo el año, el watermark queda en diciembre y una segunda reproducción se descartaría
# como datos tardíos. NO toca los negocios, las reseñas históricas, el modelo ni closure_stats.
#
# Uso:  ./scripts/reset_stream.sh      y luego:  docker compose run --rm producer --seconds-per-month 10
set -euo pipefail
cd "$(dirname "$0")/.."
export MSYS_NO_PATHCONV=1
VOL="${COMPOSE_PROJECT_NAME:-lifemap}_stream_ckpt"

docker compose stop stream
docker compose exec -T kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server kafka:9092 --delete --topic reviews --if-exists
docker run --rm -v "$VOL":/c alpine sh -c 'rm -rf /c/* /c/.[!.]* 2>/dev/null; true'
docker compose exec -T mongo sh -c 'mongosh -u "$MONGO_INITDB_ROOT_USERNAME" -p "$MONGO_INITDB_ROOT_PASSWORD" --authenticationDatabase admin "${MONGO_DB:-lifemap}" --quiet --eval "
  [\"reviews_stream\", \"geo_windows\", \"stream_status\", \"alerts\"].forEach(c => db.getCollection(c).deleteMany({}));
  db.risk_scores.updateMany({}, [{\$set: {probability: \"\$baseline.probability\", as_of: \"\$baseline.as_of\", source: \"baseline\", alert: false}}]);
  print(\"colecciones del streaming vaciadas; risk_scores vuelve a los puntajes base\")"'
sleep 3
docker compose up -d kafka-init
docker compose up -d stream
echo "listo: topic recreado y streaming reiniciado"
