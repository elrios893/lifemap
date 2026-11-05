FROM jenkins/jenkins:lts-jdk17

USER root
# Docker CLI + compose (el daemon es el del host, vía socket montado)
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg git \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
 && rm -rf /var/lib/apt/lists/*

# Jenkins arranca ya configurado (JCasC): usuario admin, credencial lifemap-env y job del pipeline.
RUN jenkins-plugin-cli --plugins git workflow-aggregator credentials-binding plain-credentials github \
    configuration-as-code job-dsl
COPY jenkins.yaml /var/jenkins_config/jenkins.yaml
ENV CASC_JENKINS_CONFIG=/var/jenkins_config/jenkins.yaml \
    JAVA_OPTS="-Djenkins.install.runSetupWizard=false"
