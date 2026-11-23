"""Bruecke mit falschem ebusd und falschem MQTT: Topics, Frische, Verfuegbarkeit, Set mit Ruecklesen,
Discovery gleich wcm2mqtt (unique_id, Topics, Plattform), CSV im Repo = Katalog."""
import json
import os

import pytest

from ebus2mqtt import bruecke as B
from ebus2mqtt import katalog as K
from ebus2mqtt import quellen as Q
from ebus2mqtt.csvgen import text as csv_text
from ebus2mqtt.ebusd import EbusdFehler

from test_wandlung import ROH

HIER = os.path.dirname(__file__)


class Uhr:
    def __init__(self):
        self.t = 1_795_442_000.0

    def __call__(self):
        return self.t


class FalschesEbusd:
    def __init__(self, roh):
        self.roh = dict(roh)
        self.fehler = set()
        self.anfragen = []

    def lesen(self, circ, name, feld=None, frisch=True):
        self.anfragen.append((circ, name))
        if name.startswith("Fachmann"):
            return "130;81", 0.1
        for sch, v in self.roh.items():
            if sch[0] != "bc" and Q.ebusd_adresse(sch)[:2] == (circ, name):
                if sch in self.fehler:
                    raise EbusdFehler("ERR: arbitration lost")
                return (f"54;{v}" if sch[0] == "slot" else str(v)), 0.12
        raise EbusdFehler("ERR: read timeout")

    def info(self):
        return {"signal": "acquired", "reconnects": "0"}

    def anfrage(self, zeile):
        if zeile.startswith("find -V -c wtc Status"):
            return [f"wtc Status = daten={self.bc} [ZZ=fe, lastup={self.bc_lastup}, passive read]"]
        raise AssertionError(zeile)

    bc = "01 00 47 12 00 4e ff ff 00 03 02 03 2d"
    bc_lastup = "2026-11-23 13:52:19"


class FalschesMqtt:
    def __init__(self):
        self.pub = []

    def publish(self, topic, payload, retain=False):
        self.pub.append((topic, payload, retain))

    def letzter(self, topic):
        for t, p, _ in reversed(self.pub):
            if t == topic:
                return p
        return None


@pytest.fixture
def br():
    uhr = Uhr()
    e, m = FalschesEbusd(ROH), FalschesMqtt()
    b = B.Bruecke(e, m, prefix="wcm", uhr=uhr, herzdatei=os.devnull)
    b.uhr_obj = uhr
    return b


def test_discovery_gleich_wcm2mqtt():
    with open(os.path.join(HIER, "daten", "wcm-discovery-2026-11-23.json"), encoding="utf-8") as f:
        alt = json.load(f)
    neu = B.discovery("wcm")
    assert neu["device"] == alt["device"]
    for n, a in alt["components"].items():
        c = neu["components"][n]
        assert c["unique_id"] == a["unique_id"] and c["state_topic"] == a["state_topic"]
        assert c.get("command_topic") == a.get("command_topic")
        for k in ("platform", "options", "min", "max", "step", "device_class", "unit_of_measurement",
                  "state_class", "expire_after"):
            if n in K.DISCOVERY_KORREKTUR and k in K.DISCOVERY_KORREKTUR[n]:
                continue
            assert c.get(k) == a.get(k), (n, k)
        assert {"topic": "wcm/status", "payload_available": "query OK", "payload_not_available": "offline"} \
            in c["availability"]
    neue = set(neu["components"]) - set(alt["components"])
    assert neue == {r["name"] for r in K.R if r["neu"]}
    assert all("command_topic" not in neu["components"][n] for n in neue)


def test_runde_publiziert_wert_und_frische(br):
    br.runde()
    m = br.mqtt
    assert m.letzter("wcm/P30-Min-VL-Soll/value") == "41.0"
    assert m.letzter("wcm/111-Betriebsart/value") == "Programm-3"
    assert m.letzter("wcm/ZP1-MO/value") == '[{"from":"06:00","to":"13:00"},{"from":"15:00","to":"22:00"}]'
    f = json.loads(m.letzter("wcm/P30-Min-VL-Soll/fresh"))
    assert f == {"ts": int(br.uhr_obj.t), "iv": 180}
    assert m.letzter("wcm/P30-Min-VL-Soll/available") == "online"
    # Rohkandidaten gehen unter _roh/, nicht retained
    roh = [(t, r) for t, _, r in m.pub if t == "wcm/_roh/slot_8c"]
    assert roh and roh[0][1] is False


def test_broadcast_ueber_listen(br):
    br.listen_zeile("wtc", "Status", "01 06 7f 52 22 52 ff ff 00 03 02 03 2d", br.uhr_obj.t)
    assert br.mqtt.letzter("wcm/I10-Betriebsphase/value") == "Brenner in Betrieb"
    assert br.mqtt.letzter("wcm/Vorlauf-Broadcast/value") == "41.0"
    br.listen_zeile("wtc", "P31", "54;45", br.uhr_obj.t)
    assert br.mqtt.letzter("wcm/P31-Max-VL-Soll/value") == "45.0"


def test_broadcast_nur_bei_neuem_lastup(br):
    assert br.broadcast() is True
    assert br.mqtt.letzter("wcm/I10-Betriebsphase/value") == "Brenner aus"
    n = len(br.mqtt.pub)
    assert br.broadcast() is False and len(br.mqtt.pub) == n      # gleiches Telegramm: keine neue Frische
    br.befehl.bc, br.befehl.bc_lastup = "01 06 7f 52 22 52 ff ff 00 03 02 03 2d", "2026-11-23 13:52:49"
    assert br.broadcast() is True
    assert br.mqtt.letzter("wcm/I10-Betriebsphase/value") == "Brenner in Betrieb"


def test_frische_laeuft_ab_und_meldet_offline(br):
    br.runde()
    br.uhr_obj.t += 3 * 180 + 1
    br.ebus = None
    br.befehl.fehler = {("slot", 0x1e)}
    br.faellig = {k: br.uhr_obj.t + 10_000 for k in K.TAKT}  # nichts neu lesen
    br.verfuegbarkeit()
    assert br.mqtt.letzter("wcm/P30-Min-VL-Soll/available") == "offline"
    st = br.status()
    assert "P30-Min-VL-Soll" in st["haengend"]


def test_status_zaehlt_arbitrierung_und_gesundheit(br):
    br.befehl.fehler = {("slot", 0x1e)}
    br.runde()
    st = br.herzschlag()
    assert st["arbitrierung_verloren"] == 1
    assert st["gesund"] is True
    assert br.mqtt.letzter("wcm/status") == "query OK"
    assert json.loads(br.mqtt.letzter("ebus2mqtt/status"))["lesungen"] >= 90
    br.uhr_obj.t += 121
    assert br.herzschlag()["gesund"] is False
    assert br.mqtt.letzter("wcm/status") == "offline"


def test_set_ohne_schreibweg_wird_abgelehnt(br):
    br.schreiber = lambda r, text: pytest.fail("darf nicht schreiben")
    assert br.set_befehl("151-Datum", "24.11.2026") is False         # kein eBUS-Schreibweg
    a = json.loads(br.mqtt.letzter("wcm/151-Datum/set_status"))
    assert a["ok"] is False and "gesperrt" in a["grund"]
    assert br.set_befehl("Vorlauftemperatur", "40") is False          # nur lesen
    assert br.set_befehl("P30-Min-VL-Soll", "90") is False            # > max 78
    assert br.set_befehl("111-Betriebsart", "Quatsch") is False       # nicht in options
    br.schreiber = None
    assert br.set_befehl("P30-Min-VL-Soll", "41") is False            # SET_AKTIV=0


def test_set_erfolg_erst_bei_passendem_rueckwert(br, monkeypatch):
    monkeypatch.setattr(B.time, "sleep", lambda s: None)
    geschrieben = []

    def schreiber(r, text):
        geschrieben.append((r["name"], text))
        br.befehl.roh[("slot", 0x1e)] = int(float(text))

    br.schreiber = schreiber
    assert br.set_befehl("P30-Min-VL-Soll", "42") is True
    assert br.mqtt.letzter("wcm/P30-Min-VL-Soll/value") == "42.0"
    # Schreiben "klappt", Kessel behaelt aber den alten Wert -> kein Erfolg
    br.schreiber = lambda r, text: None
    assert br.set_befehl("P30-Min-VL-Soll", "43") is False
    assert "!=" in json.loads(br.mqtt.letzter("wcm/P30-Min-VL-Soll/set_status"))["grund"]


def test_csv_im_repo_gleich_katalog():
    with open(os.path.join(HIER, "..", "ebusd", "csv", "wtc25.csv"), encoding="utf-8") as f:
        assert f.read() == csv_text(), "tools/gen_csv.py ausfuehren"


def test_csv_nur_lesen():
    for z in csv_text().splitlines():
        if not z.startswith("#"):
            assert z.split(",")[0] in ("r", "u"), z


SIEBEN = ["I33-Aussentemperatur", "I12-Ged-Aussentemperatur", "I10-Fehler", "Flamme", "Gasventil", "Pumpe",
          "Brenneranforderung-Heizung"]


def test_mischbetrieb_kein_doppel_publisher():
    uhr = Uhr()
    e, m = FalschesEbusd(ROH), FalschesMqtt()
    b = B.Bruecke(e, m, prefix="wcm", uhr=uhr, herzdatei=os.devnull, verfuegbar_topic="ebus2mqtt/verfuegbar",
                  auslassen=SIEBEN)
    b.runde()
    b.herzschlag()
    themen = {t for t, _, _ in m.pub}
    for n in SIEBEN:
        assert not any(t.startswith(f"wcm/{n}/") for t in themen), n      # gehoert wcm2mqtt
    assert "wcm/status" not in themen                                        # gehoert wcm2mqtt
    assert m.letzter("ebus2mqtt/verfuegbar") == "query OK"
    assert m.letzter("wcm/P30-Min-VL-Soll/value") == "41.0"
    assert any(t.startswith("wcm/_roh/") for t in themen)                    # Kandidaten laufen weiter
    st = b.status()
    assert st["gesamt"] == len(K.R) - 7 and not set(st["haengend"]) & set(K.WCM_NAMEN)  # Testdaten ohne P10-P72
    d = B.discovery("wcm", verfuegbar_topic="ebus2mqtt/verfuegbar", auslassen=SIEBEN)["components"]
    assert d["Flamme"]["availability_topic"] == "wcm/status" and "availability" not in d["Flamme"]
    assert d["P30-Min-VL-Soll"]["availability"][0]["topic"] == "ebus2mqtt/verfuegbar"
    assert len(d) == len(K.R)
    assert b.set_befehl("Flamme", "ON") is False


def test_auslassen_tippfehler_bricht_ab():
    with pytest.raises(ValueError):
        B.Bruecke(FalschesEbusd(ROH), FalschesMqtt(), auslassen=["Flame"])


def test_jede_quelle_hat_eine_csv_message():
    namen = {(z.split(",")[1], z.split(",")[2]) for z in csv_text().splitlines() if z.startswith(("r,", "u,"))}
    for r in K.R:
        for sch in Q.schluessel(r["quelle"]):
            circ, name, _ = Q.ebusd_adresse(sch)
            assert (circ, name) in namen, (r["name"], name)


def test_einheiten_korrektur_nur_ohne_langzeitstatistik():
    with open(os.path.join(HIER, "daten", "wcm-discovery-2026-11-23.json"), encoding="utf-8") as f:
        alt = json.load(f)["components"]
    neu = B.discovery("wcm")["components"]
    for n in K.DISCOVERY_KORREKTUR:
        # HA fuehrt Langzeitstatistik nur fuer sensor mit state_class; number kennt kein state_class
        # (HA-Attribut state_class = None bei number.wcm_com_117_steilheit, gemessen 23.11.2026)
        assert not (alt[n]["platform"] == "sensor" and "state_class" in alt[n]), n
    assert "unit_of_measurement" not in neu["117-Steilheit"] and "device_class" not in neu["117-Steilheit"]
    assert neu["Schaltdifferenz-VL"]["unit_of_measurement"] == "K"
    assert neu["P30-Min-VL-Soll"]["unit_of_measurement"] == "°C"
