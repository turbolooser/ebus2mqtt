# ebus-bridge: Python-Bruecke ebusd -> MQTT. Basis per Digest gepinnt (python:3.12-slim, Stand 08.11.2026).
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
COPY requirements.txt /opt/ebus2mqtt/requirements.txt
RUN pip install --no-cache-dir --require-hashes -r /opt/ebus2mqtt/requirements.txt
COPY ebus2mqtt /opt/ebus2mqtt/ebus2mqtt
WORKDIR /opt/ebus2mqtt
ENV PYTHONUNBUFFERED=1 HERZDATEI=/tmp/ebus2mqtt.herz WEB_PORT=8097
# Web-Frontend, nur lesen: / (Tabelle), /api/werte (JSON), /status
EXPOSE 8097
USER nobody
# gesund = Herzschlag-Datei juenger als 120 s; sie wird nur geschrieben, wenn ebusd Signal hat und in den
# letzten 120 s eine Abfrage beantwortet wurde (Bruecke.herzschlag)
HEALTHCHECK --interval=30s --timeout=5s --start-period=3m --retries=3 \
  CMD python -c "import os,sys,time; sys.exit(0 if time.time()-os.path.getmtime(os.environ['HERZDATEI'])<120 else 1)"
CMD ["python", "-m", "ebus2mqtt"]
