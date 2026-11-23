# ebusd mit eigener CSV fuer die WTC-25-A. Basis: offizielles Image john30/ebusd v26.1 (Digest gepinnt).
FROM john30/ebusd:v26.1@sha256:59bf92661bd49900ec64d6bb994556ee8f4f06c036f640163908439b684bc066
COPY ebusd/csv /etc/ebusd/wtc25
# Kein --scanconfig (Vorgabe des Images): nur unsere CSV. Kein eigenes Pollen (--pollinterval=0): die Bruecke
# bestimmt den Takt. Geraet, Adresse und MQTT kommen als EBUSD_*-Variablen aus dem Compose-Stack.
# --enablehex: die Bruecke schreibt per hex (Pruefbyte haengt vom Wert ab). Port 8888 nur im Stack-Netz, nicht
# veroeffentlichen.
CMD ["--configpath=/etc/ebusd/wtc25", "--pollinterval=0", "--port=8888", "--enablehex", "--log=all:notice"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=1m --retries=3 \
  CMD ebusctl info | grep -q "signal: acquired"
