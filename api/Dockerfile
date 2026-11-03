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

FROM base AS runtime
ENV PYTHONPATH=/srv
CMD ["gunicorn", "-b", "0.0.0.0:5000", "-w", "2", "app:create_app()"]
