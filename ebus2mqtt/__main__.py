"""Start: python -m ebus2mqtt. Konfiguration nur ueber Umgebungsvariablen (README, stack.env.example)."""
import logging
import os
import signal
import threading
import time

from . import katalog as K
from .bruecke import Bruecke
from .ebusd import Befehl, Lauscher
from .schreiben import ebusd_schreiber
from .web import starten as web_starten


def env(name, vorgabe=""):
    return os.environ.get(name, vorgabe)


class PahoMqtt:
    """Duenne Huelle um paho-mqtt 2.x: publish(topic, payload, retain), Set-Abo mit Rueckruf."""

    def __init__(self, host, port, user, passwort, client_id, lwt_topic, auf_set, auf_wert=None):
        import paho.mqtt.client as mqtt
        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if user:
            self.c.username_pw_set(user, passwort)
        self.c.will_set(lwt_topic, "offline", retain=True)
        self.auf_set = auf_set
        self.auf_wert = auf_wert
        self.set_filter = None
        self.c.on_connect = self._verbunden
        self.c.on_message = self._nachricht
        self.c.reconnect_delay_set(1, 30)
        self.c.connect_async(host, port, keepalive=60)
        self.c.loop_start()

    def abonnieren(self, filter_liste):
        self.set_filter = list(filter_liste)
        if self.c.is_connected():
            for f in self.set_filter:
                self.c.subscribe(f)

    def _verbunden(self, client, userdata, flags, reason, props=None):
        logging.info("MQTT verbunden (%s)", reason)
        for f in self.set_filter or []:
            client.subscribe(f)

    def _nachricht(self, client, userdata, msg):
        teile = msg.topic.split("/")
        text = msg.payload.decode("utf-8", "replace").strip()
        if len(teile) >= 3 and teile[-1] == "set":
            threading.Thread(target=self.auf_set, args=(teile[-2], text), daemon=True).start()
        elif len(teile) >= 3 and teile[-1] == "value" and self.auf_wert:
            self.auf_wert(teile[-2], text)

    def publish(self, topic, payload, retain=False):
        self.c.publish(topic, payload, qos=1, retain=retain)


def main():
    logging.basicConfig(level=env("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    prefix = env("MQTT_PREFIX", "wcm")
    verfuegbar = env("VERFUEGBAR_TOPIC") or f"{prefix}/status"
    auslassen = [n.strip() for n in env("AUSLASSEN").split(",") if n.strip()]
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    befehl = Befehl(env("EBUSD_HOST", "ebusd"), int(env("EBUSD_PORT", "8888")))
    halter = {}
    if not env("MQTT_HOST"):
        raise SystemExit("MQTT_HOST fehlt (Broker-Adresse)")
    mqtt = PahoMqtt(env("MQTT_HOST"), int(env("MQTT_PORT", "1883")), env("MQTT_USER"),
                    env("MQTT_PASSWORD"), env("MQTT_CLIENT_ID", "ebus2mqtt"), verfuegbar,
                    lambda n, t: halter["b"].set_befehl(n, t), lambda n, t: halter["b"].fremd_wert(n, t))
    b = Bruecke(befehl, mqtt, prefix=prefix, status_topic=env("STATUS_TOPIC", "ebus2mqtt/status"),
                disc_prefix=env("HA_DISCOVERY_PREFIX", "homeassistant"), roh=env("ROH", "1") == "1",
                kuma_url=env("KUMA_PUSH_URL"), herzdatei=env("HERZDATEI", "/tmp/ebus2mqtt.herz"),
                schreiber=ebusd_schreiber(befehl) if env("SET_AKTIV", "1") == "1" else None,
                verfuegbar_topic=verfuegbar, auslassen=auslassen)
    halter["b"] = b
    abos = [f"{prefix}/{n}/value" for n in auslassen]   # nur zur Anzeige im Web-Frontend
    if env("SET_AKTIV", "1") == "1":
        # nur die Werte mit belegtem eBUS-Schreibweg; alle anderen Sets bedient im Mischbetrieb wcm2mqtt
        adresse = env("EBUS_ADRESSE", "31")
        abos += [f"{prefix}/{n}/set" for n in K.schreibbar(adresse) if n not in auslassen]
        logging.info("Sets abonniert (ebusd-Adresse %s): %s", adresse, len(abos))
    mqtt.abonnieren(abos)
    if env("WEB_PORT", "8097"):
        web_starten(b, int(env("WEB_PORT", "8097")))
    Lauscher(befehl.host, befehl.port, b.listen_zeile, stop).start()
    time.sleep(3)
    b.discovery_senden()
    herz_alle = int(env("HERZ_S", "30"))
    naechstes_herz = 0.0
    logging.info("ebus2mqtt gestartet: prefix=%s ebusd=%s:%s", prefix, befehl.host, befehl.port)
    while not stop.is_set():
        b.runde()
        if time.time() >= naechstes_herz:
            b.herzschlag()
            naechstes_herz = time.time() + herz_alle
        stop.wait(1)
    mqtt.publish(verfuegbar, "offline", retain=True)
    time.sleep(1)


if __name__ == "__main__":
    main()
