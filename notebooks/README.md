# Cuadernos de sustentación

- `sustentacion.ipynb`: **Entrega 1** (plataforma batch).
- `entrega2.ipynb`: **Entrega 2** (Kafka, streaming, ventanas, supervivencia, riesgo, alertas, API y pruebas de Jenkins). Ver la sección al final.

## Entrega 1: `sustentacion.ipynb`

`sustentacion.ipynb` recorre la plataforma con datos reales: arquitectura, dato crudo, limpieza con Dask, GeoJSON e índice `2dsphere`,
las tres consultas (`$near`, `$geoWithin`, `$geoNear`), vida y censura, MapReduce con su verificación, sentimiento, balanceo, la API y Jenkins.
Es solo material de apoyo para explicar; no forma parte del despliegue.

```bash
docker compose up -d            # stack levantado (en local: API en http://localhost:5050, Mongo en 127.0.0.1:27017)
pip install -r notebooks/requirements.txt
jupyter lab notebooks/sustentacion.ipynb
```

Las credenciales de MongoDB se leen del `.env` de la raíz (no se imprimen). El cuaderno corre sobre lo que haya en el stack:
en local es la muestra de desarrollo (`SAMPLE_REVIEWS`); en la nube, la corrida completa. Para apuntar a la nube basta cambiar `API` en la primera celda.

`sustentacion_respaldo.html` es la misma guía ya ejecutada y sin código, para abrirla sin el stack.

## Entrega 2: `entrega2.ipynb`

Recorre lo que agrega la Entrega 2 con datos reales del stack: la fecha de corte T y el modelo versionado, Kafka (KRaft) y el productor, la inferencia en streaming,
las ventanas por geohash con *watermark* y hotspots (con la justificación del umbral), Kaplan-Meier por categoría y zona, el modelo de riesgo, las alertas, los endpoints nuevos
y las pruebas de Jenkins (incluida la prueba del modelo versionado en vivo, con una copia alterada que debe fallar). Cierra con las mediciones de la corrida completa en AWS y las limitaciones.

Requisitos: el stack levantado (`docker compose up -d`) y **una reproducción previa** del flujo, porque las secciones leen lo que ésta dejó en MongoDB:

```bash
./scripts/reset_stream.sh
docker compose run --rm producer --seconds-per-month 2
```

`entrega2_respaldo.html` es la misma guía ya ejecutada y sin código, para abrirla sin el stack. Las cifras de la sección 11 son mediciones de la nube hechas el 18 de noviembre de 2026 (la VM ya no existe).
