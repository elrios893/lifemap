# Controlador de la demostración: recibe de la API la orden de reproducir el flujo y ejecuta lo mismo que se hacía a mano
# (scripts/reset_stream.sh y luego el productor). Necesita el socket de Docker y el repositorio montado en la misma ruta del host.
FROM docker:27-cli
RUN apk add --no-cache bash python3
COPY server.py /srv/server.py
CMD ["python3", "/srv/server.py"]
