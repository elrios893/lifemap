# LifeMap: reputación, ubicación y supervivencia de negocios

Curso Big Data · IUE 2026-2. Dataset: Yelp Open Dataset (Kaggle). Ver `docs/` para el informe.

**URL desplegada:** _(pendiente — se registra aquí tras `terraform apply`)_
**Jenkins:** `http://<IP>:8088` · **Commit desplegado:** visible en `/health`.

## Arquitectura

Un solo `docker-compose.yml`: MongoDB, Spark (master + worker, con conector de Mongo), Dask (scheduler + 2 workers),
API Flask, Jenkins y, opcionalmente, ngrok (URL fija). Kafka se suma en la Entrega 2.

## Reconstruir desde cero (local)

```bash
cp .env.example .env      # editar credenciales
docker compose up -d --build
curl localhost/health
```

## Despliegue en AWS con Terraform (armar / desarmar)

Requisitos: `terraform`, `aws` CLI con credenciales, una llave SSH (`ssh-keygen -t ed25519`) y el repo en GitHub.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # admin_cidr, repo_url, mongo_password
terraform init
terraform apply        # crea VM (t3.xlarge), IP elástica, firewall y arranca todo con cloud-init
terraform output       # IP, URL de /health, URL de Jenkins, comando ssh
terraform destroy      # desarma todo (y deja de cobrar)
```

El arranque tarda ~5–10 min (log en la VM: `/var/log/lifemap-init.log`).

### URL fija con ngrok (opcional)
Si se define `ngrok_authtoken` y `ngrok_domain` (dominio estático gratuito del dashboard de ngrok), el servicio `ngrok`
expone la API en esa URL aunque la IP cambie entre `apply`/`destroy`.

## CI/CD (Jenkins)

1. Abrir `http://<IP>:8088`, desbloquear con `docker compose exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword`.
2. Crear credencial **Secret file** con id `lifemap-env` (contenido = `.env` del servidor).
3. Crear un job Pipeline desde SCM apuntando a este repo, rama `main`.
4. Webhook de GitHub: `http://<IP>:8088/github-webhook/`. Si no llega, el `Jenkinsfile` usa `pollSCM` cada 2 min.

Etapas: checkout → validar compose → pytest (build `--target test`) → build → desplegar (solo `main`) → prueba contra `/health`.
Una prueba que falla detiene el build y no se despliega.

## Estado

- [x] Esqueleto: Compose, `/health`, Jenkinsfile, Terraform
- [ ] Ingesta Dask + limpieza · [ ] GeoJSON + 2dsphere · [ ] vida de negocios
- [ ] Sentimiento (NB + LR) · [ ] MapReduce + tasas · [ ] balanceo · [ ] endpoints geo
