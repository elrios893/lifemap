// Pipeline: checkout -> validar compose -> pruebas (pytest dentro del build) -> despliegue solo en main.
// Credenciales en Jenkins (Manage Credentials), nunca en el repo:
//   'lifemap-env' (Secret file) = contenido de .env (MONGO_*, KAGGLE_*, NGROK_*, COMPOSE_PROFILES)
pipeline {
    agent any
    options { timestamps(); disableConcurrentBuilds() }
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
                    sh 'GIT_COMMIT=$GIT_COMMIT_SHORT docker compose --env-file "$ENV_FILE" build'
                }
            }
        }

        stage('Desplegar') {
            when { expression { env.GIT_BRANCH in ['origin/main', 'main'] } }
            steps {
                withCredentials([file(credentialsId: 'lifemap-env', variable: 'ENV_FILE')]) {
                    sh 'GIT_COMMIT=$GIT_COMMIT_SHORT docker compose --env-file "$ENV_FILE" up -d --remove-orphans api mongo dask-scheduler dask-worker-1 dask-worker-2 spark-master spark-worker'
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
    }

    post {
        failure { echo 'Pipeline fallido: no se despliega (o se revirtió el último estado sano).' }
    }
}
