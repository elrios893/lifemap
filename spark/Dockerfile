FROM apache/spark:3.5.3
USER root
# Conector de MongoDB horneado para no depender de --packages en tiempo de ejecución.
ADD https://repo1.maven.org/maven2/org/mongodb/spark/mongo-spark-connector_2.12/10.4.0/mongo-spark-connector_2.12-10.4.0.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-sync/5.1.4/mongodb-driver-sync-5.1.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/mongodb-driver-core/5.1.4/mongodb-driver-core-5.1.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/bson/5.1.4/bson-5.1.4.jar /opt/spark/jars/
ADD https://repo1.maven.org/maven2/org/mongodb/bson-record-codec/5.1.4/bson-record-codec-5.1.4.jar /opt/spark/jars/
RUN chmod 644 /opt/spark/jars/*.jar && mkdir -p /models && chown spark /models
RUN pip3 install --no-cache-dir numpy
COPY . /opt/jobs
USER spark
