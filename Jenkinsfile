// Pipeline: checkout -> validar compose -> pruebas (pytest dentro del build) -> build -> modelo versionado -> prueba de humo
// del flujo -> despliegue solo en main -> pruebas contra lo desplegado. Cualquier falla ANTES de 'Desplegar' lo impide.
// Credenciales en Jenkins (Manage Credentials), nunca en el repo:
//   'lifemap-env' (Secret file) = contenido de .env (MONGO_*, KAGGLE_*, NGROK_*, COMPOSE_PROFILES)
pipeline {
    agent any
    options { disableConcurrentBuilds() }
    triggers { pollSCM('H/2 * * * *') }   // respaldo si el webhook de GitHub no llega

    environment {
        COMPOSE_PROJECT_NAME = 'lifemap'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script { env.GIT_COMMIT_SHORT = sh(returnStdout: true, script: 'git rev-parse HEAD').trim() }
            }
        }

        stage('Validar compose') {
            steps {
                withCredentials([file(credentialsId: 'lifemap-env', variable: 'ENV_FILE')]) {
                    sh 'docker compose --env-file "$ENV_FILE" config --quiet'
                }
            }
        }

        stage('Pruebas unitarias') {
            // Falla el build de la imagen si falla pytest -> no se despliega.
            steps { sh 'docker build --target test -f api/Dockerfile .' }
        }

        stage('Build imágenes') {
            steps {
                withCredentials([file(credentialsId: 'lifemap-env', variable: 'ENV_FILE')]) {
                    sh 'GIT_COMMIT=$GIT_COMMIT_SHORT docker compose --env-file "$ENV_FILE" build api dask-scheduler spark-master controller'
                }
            }
        }

        // Entrega 2: el modelo que se va a cargar debe ser exactamente el versionado (huella SHA-256 + fecha de corte T).
        stage('Modelo versionado') {
            steps {
                sh 'docker run --rm -v lifemap_models:/models:ro --entrypoint python3 lifemap-spark:latest /opt/jobs/check_models.py'
            }
        }

        // Entrega 2: publica 100 mensajes en Kafka con el código NUEVO (entorno aislado: topic reviews_smoke y colecciones
        // smoke_*) y verifica que aparecen clasificados en MongoDB. Si falla, no se despliega.
        stage('Prueba de humo del flujo') {
            steps {
                withCredentials([file(credentialsId: 'lifemap-env', variable: 'ENV_FILE')]) {
                    sh 'ENV_FILE="$ENV_FILE" bash scripts/smoke_stream.sh'
                }
            }
        }

        stage('Desplegar') {
            when { expression { env.GIT_BRANCH in ['origin/main', 'main'] } }
            steps {
                withCredentials([file(credentialsId: 'lifemap-env', variable: 'ENV_FILE')]) {
                    sh 'GIT_COMMIT=$GIT_COMMIT_SHORT docker compose --env-file "$ENV_FILE" up -d --remove-orphans api mongo dask-scheduler dask-worker-1 dask-worker-2 spark-master spark-worker kafka kafka-init stream controller'
                }
            }
        }

        stage('Prueba contra la API') {
            when { expression { env.GIT_BRANCH in ['origin/main', 'main'] } }
            steps {
                sh '''
                  for i in $(seq 1 30); do
                    out=$(docker run --rm --network lifemap_default curlimages/curl -sf http://api:5000/health) && break
                    sleep 5
                  done
                  echo "$out"
                  echo "$out" | grep -q "$GIT_COMMIT_SHORT"
                '''
            }
        }

        // Entrega 2: el streaming desplegado cargó el modelo versionado (lo informa /health y lo escribe el propio job).
        stage('Modelo cargado en producción') {
            when { expression { env.GIT_BRANCH in ['origin/main', 'main'] } }
            steps {
                sh '''
                  expected=$(docker run --rm -v lifemap_models:/models:ro --entrypoint cat lifemap-spark:latest /models/version.json | grep -oE '"sha256": *"[0-9a-f]{12}' | grep -oE '[0-9a-f]{12}$')
                  echo "modelo versionado: $expected"
                  for i in $(seq 1 36); do
                    out=$(docker run --rm --network lifemap_default curlimages/curl -sf http://api:5000/health || true)
                    echo "$out" | grep -q "model_version.:.$expected" && { echo "el streaming cargó el modelo versionado"; exit 0; }
                    sleep 5
                  done
                  echo "FALLA: el streaming no informa el modelo versionado $expected"; echo "$out"; exit 1
                '''
            }
        }
    }

    post {
        failure { echo 'Pipeline fallido: no se despliega (o se revirtió el último estado sano).' }
    }
}
