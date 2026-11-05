# Contexto de build = raíz del repo (para poder copiar tests/).
FROM python:3.11-slim AS base
WORKDIR /srv
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY api/app app

# Etapa de pruebas: `docker build --target test` falla si pytest falla.
FROM base AS test
COPY tests tests
ENV PYTHONPATH=/srv
RUN pytest -q tests

# /predict carga el modelo de Spark en modo local, por eso la imagen lleva JRE y PySpark.
FROM base AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-21-jre-headless procps \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir pyspark==3.5.3 numpy
ENV PYTHONPATH=/srv
# 1 worker + hilos: una sola JVM de Spark para todas las peticiones.
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "1", "--threads", "4", "--timeout", "180", "app:create_app()"]
