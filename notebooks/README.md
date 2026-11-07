# Cuaderno de sustentación

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
