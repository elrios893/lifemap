# LifeMap: reputación, ubicación y supervivencia de negocios

Curso Big Data · IUE 2026-2 · Juan Pablo Rios Ortiz. Dataset: Yelp Open Dataset (Kaggle), área de Filadelfia (estado `PA`).
Informe de la Entrega 1: `docs/Informe_LifeMap_Entrega1.docx`. Guía de sustentación con datos reales: `notebooks/sustentacion.ipynb`
(y `notebooks/sustentacion_respaldo.html`, la misma ya ejecutada y sin código).

## URL desplegada

**https://unmovable-crumpet-opposite.ngrok-free.dev** (URL fija de ngrok; la interfaz web está en `/` y el estado en `/health`).

El sistema corre en una VM de AWS que se **arma y se desarma con Terraform** para no pagar mientras no se usa, así que la URL solo responde
cuando la VM está arriba (`terraform apply`, ≈ 5 min hasta `/health` y ≈ 7 min con los datos restaurados). `/health` incluye el **hash del commit desplegado**.
Jenkins: `http://<IP de la VM>:8088` (la IP sale de `terraform output`).

> **Aviso de ngrok.** La primera vez que se abre la URL en un navegador, ngrok (plan gratuito) muestra una página de aviso con el botón **Visit Site**; basta pulsarlo una vez.
> Las llamadas con `curl` o desde otros programas no la ven. Si se prefiere evitarla, se puede entrar por la IP de la VM (`http://<IP>/`).

## Qué hace

Plataforma batch sobre `docker compose`: descarga con la API de Kaggle → limpieza distribuida (Dask) → MongoDB con GeoJSON e índice `2dsphere`
→ vida y censura de cada negocio → MapReduce de tasas de cierre y modelos de sentimiento (Spark) → API Flask con interfaz web.
Jenkins reconstruye y despliega la API cuando cambia `main`. Kafka y el streaming se suman en la Entrega 2.

| Servicio | Imagen / rol |
|---|---|
| `mongo` | MongoDB 7 (negocios GeoJSON, reseñas, `closure_stats`) |
| `dask-scheduler`, `dask-worker-1/2` | limpieza, vida de negocios |
| `spark-master`, `spark-worker` | MapReduce, sentimiento, balanceo (con el conector de Mongo) |
| `api` | Flask + gunicorn, sirve los endpoints y la interfaz |
| `jenkins` | CI/CD, configurado con JCasC (usuario, credencial y job se crean solos) |
| `ngrok` | perfil `tunnel`: URL fija |

## Endpoints

| Ruta | Qué hace |
|---|---|
| `GET /health` | estado de Mongo, Spark y Dask + commit desplegado |
| `GET /businesses/near?lat&lon&radius[&category&limit]` | `$near`, ordenado por cercanía |
| `GET`/`POST /businesses/within` | `$geoWithin` con un polígono GeoJSON (`polygon`) |
| `GET /stats/closure?by=category\|geohash[&min_days&order&limit]` | tasa de cierre anualizada (MapReduce) |
| `GET /zones/summary?lat&lon&radius` | resumen de una zona con `$geoNear`: negocios, estrellas, % negativo, tasa de cierre |
| `GET`/`POST /predict` (`text`) | sentimiento de una reseña nueva (mejor modelo guardado) |
| `GET /` | interfaz web (mapa) que consume los endpoints anteriores |
| `GET /entregauno` | marca de la Entrega 1 (`{"entrega":1,"estado":"terminada"}`), útil para ver un despliegue en vivo |

Tasa de cierre = `cierres / (días-negocio / 365) × 100`.

## Resultados (corrida completa en AWS)

- Reseñas: 6.990.280 leídas → **1.598.776** del área; negocios: **34.013** (7.747 cerrados, 26.266 censurados), ventana 2005-02-16 → 2022-01-19.
- MapReduce con `reduceByKey` validado contra `groupBy` (898 categorías, 268 celdas geohash).
- Sentimiento (partición por negocio, 0 negocios compartidos): regresión logística accuracy 0,846 / macro-F1 0,698 (mejor); Naive Bayes 0,719 / 0,640.
- Balanceo con 2, 8, 32 y 200 particiones, con y sin clave: ver el informe y la sección 9 del cuaderno.
- Tasa de cierre: Restaurants 5,41 % · Food 4,22 % · Shopping 3,07 % · Beauty & Spas 2,08 %.

## Reconstruir desde cero (local)

Requisitos: Docker con ≈ 8 GB de RAM. Se usa una **muestra** (`SAMPLE_REVIEWS`) para que quepa.

```bash
cp .env.example .env      # editar credenciales (Mongo, Kaggle, Jenkins)
# en .env local:  COMPOSE_FILE=docker-compose.yml:docker-compose.local.yml  y  COMPOSE_PATH_SEPARATOR=:
docker compose up -d --build
SAMPLE_REVIEWS=200000 ./scripts/run_pipeline.sh     # 7 pasos: descarga, limpieza, carga, vida, MapReduce, sentimiento, balanceo
curl localhost:5050/health                           # en local la API queda en el puerto 5050; abrir http://localhost:5050
```

Sin `SAMPLE_REVIEWS` el pipeline procesa toda el área (≈ 40 min en una máquina de 4 vCPU / 16 GB).

## Despliegue en AWS con Terraform (armar / desarmar)

Requisitos: `terraform`, `aws` CLI con un perfil, una llave SSH y el repo en GitHub.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # admin_cidr, repo_url, contraseñas, ngrok_authtoken/ngrok_domain
terraform init
terraform apply        # VM t3.xlarge, IP elástica, firewall; cloud-init instala Docker, clona el repo y levanta todo
terraform output       # IP, URL de /health, URL de Jenkins, comando ssh
terraform destroy      # desarma todo y deja de cobrar
```

El arranque restaura los datos desde S3 si hay respaldo: `scripts/backup_to_s3.sh` guarda Mongo, modelos y métricas (≈ 480 MB, < 0,01 USD/día)
y `scripts/restore_from_s3.sh` los recupera, así se evita repetir los ≈ 40 min del pipeline. Log de la VM: `/var/log/lifemap-init.log`.

## CI/CD (Jenkins)

Jenkins se configura solo con JCasC (`jenkins/jenkins.yaml`): usuario `admin` (contraseña = `jenkins_admin_password` de Terraform), la credencial
`lifemap-env` (el `.env` del servidor) y el job `lifemap`, que apunta a este repo, rama `main`.

- **Disparo:** `pollSCM` cada 2 minutos (respaldo documentado del webhook de GitHub, que no se configuró) y `githubPush` si llega.
- **Etapas:** checkout → validar compose → pytest (`docker build --target test`) → build → desplegar (solo `main`) → prueba contra `/health`.
- **Bloqueo:** una prueba que falla detiene el build y **no se despliega**. El commit `575f188` rompe una prueba a propósito para demostrarlo y `e5d4bf3` la restaura.

## Estado

- [x] Orquestación reproducible con Compose (y reconstrucción desde cero en la nube verificada)
- [x] Ingesta y limpieza con Dask (conteos antes/después de cada regla)
- [x] GeoJSON + índice `2dsphere`, vida y censura de cada negocio
- [x] Sentimiento (Naive Bayes y regresión logística) con partición por negocio
- [x] MapReduce de tasas de cierre validado contra `groupBy`; balanceo de carga
- [x] 6 endpoints + `/health` + interfaz web; despliegue con Terraform; CI/CD con Jenkins
- [ ] Entrega 2: Kafka (KRaft), inferencia en streaming, ventanas por geohash, Kaplan-Meier, riesgo, alertas, dashboard
