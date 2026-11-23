"""Hauptschleife: dauerhaft ungesund -> main() gibt 1 zurueck (Container-Exit, Docker startet neu)."""
from ebus2mqtt import __main__ as M
from ebus2mqtt import bruecke as B

from test_bruecke import FalschesMqtt


class StummesEbusd:
    def __init__(self, host, port):
        self.host, self.port = host, port

    def info(self):
        return {"signal": "lost"}


class KeinLauscher:
    def __init__(self, *a):
        pass

    def start(self):
        pass


def test_main_beendet_sich_bei_dauerhaft_ungesund(monkeypatch):
    mqtt = FalschesMqtt()
    monkeypatch.setattr(M, "Befehl", StummesEbusd)
    monkeypatch.setattr(M, "PahoMqtt", lambda *a, **k: setattr(mqtt, "abonnieren", lambda f: None) or mqtt)
    monkeypatch.setattr(M, "Lauscher", KeinLauscher)
    monkeypatch.setattr(M, "web_starten", lambda *a: None)
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    monkeypatch.setattr(B.Bruecke, "runde", lambda self: None)
    monkeypatch.setattr(B.Bruecke, "discovery_senden", lambda self: None)
    for k, v in {"MQTT_HOST": "x", "HERZ_S": "0", "UNGESUND_ENDE_S": "1", "SET_AKTIV": "0", "WEB_PORT": ""}.items():
        monkeypatch.setenv(k, v)
    assert M.main() == 1
    assert mqtt.letzter("wcm/status") == "offline"
