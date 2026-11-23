"""Web-Frontend: nur GET, Tabelle mit allen Werten, Quelle, Alter; ausgelassene Werte mit Quelle WCM-COM."""
import json
import os
import urllib.error
import urllib.request

import pytest

from ebus2mqtt import bruecke as B
from ebus2mqtt import katalog as K
from ebus2mqtt import web as W

from test_bruecke import SIEBEN, FalschesEbusd, FalschesMqtt, Uhr
from test_wandlung import ROH

VIER = SIEBEN[3:]


@pytest.fixture
def server():
    b = B.Bruecke(FalschesEbusd(ROH), FalschesMqtt(), uhr=Uhr(), herzdatei=os.devnull,
                  verfuegbar_topic="ebus2mqtt/verfuegbar", auslassen=VIER)
    b.runde()
    b.herzschlag()
    b.fremd_wert("Flamme", "ON")
    s = W.starten(b, 0, host="127.0.0.1")
    yield b, f"http://127.0.0.1:{s.server_address[1]}"
    s.shutdown()


def test_api_werte_vollstaendig(server):
    b, url = server
    d = json.loads(urllib.request.urlopen(url + "/api/werte").read())
    w = {x["name"]: x for x in d["werte"]}
    assert len(w) == len(K.R)
    p42 = w["P42-Pumpenleistung-min"]
    assert p42["bezeichnung"] == "P42 minimale Pumpenleistung Heizung" and p42["einheit"] == "%"
    p30 = w["P30-Min-VL-Soll"]
    assert p30["wert"] == "41.0" and p30["einheit"] == "°C" and p30["frisch"] and p30["alter_s"] == 0
    assert p30["quelle"] == "eBUS Kessel 08 · Slot 1e (50 03)" and p30["schreiben"] == "eBUS 50 04 an 03"
    assert w["I33-Aussentemperatur"]["quelle"] == "eBUS WCM-FS 35 · infoNr 12 (50 22)"
    assert w["111-Betriebsart"]["schreiben"].startswith("eBUS 50 23 an 35")
    assert w["151-Datum"]["schreiben"] == "über WCM-COM"
    assert w["Flamme"]["wert"] == "ON" and w["Flamme"]["quelle"].startswith("WCM-COM")
    assert d["gesund"] is True


def test_seite_nur_lesen(server):
    _, url = server
    html = urllib.request.urlopen(url + "/").read().decode()
    assert "api/werte" in html and "setInterval" in html
    assert "<button" not in html and "<form" not in html and "POST" not in html
    req = urllib.request.Request(url + "/api/werte", data=b"x", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 501
    assert urllib.request.urlopen(url + "/status").read() == b"ok"


def test_doku_je_wert_gesetzt_oder_bewusst_leer():
    assert set(K.DOKU) == set(K.READINGS)
    for n, d in K.DOKU.items():
        if d["url"]:
            assert d["url"].startswith("https://") and d.get("quelle"), n
            if "weishaupt.de" in d["url"]:
                assert "#page=" in d["url"], n
        else:
            assert d.get("grund"), n


def test_doku_link_in_api(server):
    _, url = server
    w = {x["name"]: x for x in json.loads(urllib.request.urlopen(url + "/api/werte").read())["werte"]}
    assert w["P42-Pumpenleistung-min"]["doku_url"].endswith("83247501_02_15.pdf#page=55")
    assert w["Flamme"]["doku_url"].endswith("Documentation/f6.md")
    assert w["ZP1-MO"]["doku_url"] is None and w["ZP1-MO"]["doku"]
