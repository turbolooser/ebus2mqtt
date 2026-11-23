"""Umrechnung gegen echte Werte: Rohdaten vom eBUS (Mitschnitt 23.11.2026, WTC-25-A) muessen denselben
Text ergeben, den wcm2mqtt zur selben Zeit unter wcm/<name>/value publizierte (tests/daten/*.tsv, 15:00)."""
import os

import pytest

from ebus2mqtt import katalog as K
from ebus2mqtt import quellen as Q
from ebus2mqtt.crc import ebus_crc, register_id

DATEN = os.path.join(os.path.dirname(__file__), "daten")


def wcm_werte():
    out = {}
    with open(os.path.join(DATEN, "wcm-werte-2026-11-23T1500.tsv"), encoding="utf-8") as f:
        for z in f:
            n, v = z.rstrip("\n").split("\t", 1)
            out[n] = v
    return out


# Rohwerte, wie ebusd sie liefert (read -f ... wert), 23.11.2026 14:47-15:11; Quelle: Slot-Scan + WCM-Mitschnitt
ROH = {
    ("slot", 0x12): 60, ("slot", 0x14): -1, ("slot", 0x17): 5, ("slot", 0x1e): 41, ("slot", 0x1f): 44,
    ("slot", 0x20): 3, ("slot", 0x22): 5, ("slot", 0x25): 60, ("slot", 0x8b): 82, ("slot", 0x8d): 41,
    ("slot", 0x9e): 37, ("slot", 0x9f): 39, ("slot", 0xaa): 486, ("slot", 0xab): 359, ("slot", 0xad): 178,
    ("slot", 0x8c): 3, ("slot", 0xa0): 3, ("reg", 12): 30, ("reg", 2572): 30,
    ("reg", 274): 13, ("reg", 8): 195, ("reg", 270): 110, ("reg", 2586): 30, ("reg", 5): 195, ("reg", 4): 453,
    ("reg", 306): 1, ("reg", 321): 1, ("reg", 278): 160, ("reg", 2580): 100, ("reg", 317): 0, ("reg", 2419): 2,
    ("reg", 1): 0,
    ("reg", 290): 23, ("reg", 291): 11, ("reg", 292): 26, ("reg", 293): 14, ("reg", 294): 56,
    # 14:00:20 UTC: Phase 19, Brenner startet (WCM zeigte Phase 19, Flamme/Gas noch OFF, Pumpe ON)
    ("bc",): [0x01, 0x13, 0x47, 0x12, 0x51, 0x4a, 0xff, 0xff, 0x00, 0x03, 0x02, 0x03, 0x2d],
}
for _zp, _tage in K.ZP_BASIS.items():
    for _tag, _b in _tage.items():
        ROH[("reg", _b)] = {"ZP1": 0x1834, "ZP2": 0x1836, "ZP3": 0x185a}[_zp]
        ROH[("reg", _b + 1)] = {"ZP1": 0x3c58, "ZP2": 0x3c5c, "ZP3": 0x8080}[_zp]
        ROH[("reg", _b + 2)] = 0x8080

# Diese stehen am Bus noch nicht belegt (Kandidaten) oder WCM-Wert ist zeitlich anders (Phase am Bus frueher)
NICHT_VERGLICHEN = {"Flamme", "Gasventil", "Pumpe", "Brenneranforderung-Heizung"}


@pytest.mark.parametrize("name", [n for n in K.WCM_NAMEN if n not in NICHT_VERGLICHEN])
def test_text_wie_wcm(name):
    r = K.READINGS[name]
    roh = {s: ROH[s] for s in Q.schluessel(r["quelle"])}
    assert Q.wert(r, roh) == wcm_werte()[name]


def test_alle_58_wcm_readings_im_katalog():
    assert sorted(K.WCM_NAMEN) == sorted(wcm_werte())
    assert len(K.WCM_NAMEN) == 58


def test_lowbyte_wie_wcm_und_roh_echt():
    # wcm2mqtt nimmt bei I42/I43 nur das Low-Byte des 16-bit-Werts; der Rohwert geht zusaetzlich raus
    assert Q.wert(K.READINGS["I42-Schaltspiele-roh"], {("slot", 0xaa): 486}) == "486"
    assert Q.wert(K.READINGS["I42-Schaltspielzahl-Brenner"], {("slot", 0xaa): 486}) == "230000"


@pytest.mark.parametrize("phase,text", [(0, "Brenner aus"), (6, "Brenner in Betrieb"), (8,
                         "Nachbelüftungsdrehzahl erreichen und Nachbelüftung"), (19, "Phase 19 (unbelegt)")])
def test_phase_aus_broadcast(phase, text):
    bc = list(ROH[("bc",)])
    bc[1] = phase
    assert Q.wert(K.READINGS["I10-Betriebsphase"], {("bc",): bc}) == text


def test_aussentemperatur_conv_temp2_wie_wcm():
    r = K.READINGS["I33-Aussentemperatur"]
    assert Q.wert(r, {("reg", 12): 20}) == "2"
    assert Q.wert(r, {("reg", 12): 25}) == "2.5"
    assert Q.wert(r, {("reg", 12): 0xFFF6}) == "-1"           # -1,0 Grad
    assert Q.wert(r, {("reg", 12): 0x8000}) is None           # n/v


def test_vorlauf_broadcast_halbe_grad():
    assert Q.wert(K.READINGS["Vorlauf-Broadcast"], {("bc",): ROH[("bc",)]}) == "37.0"


def test_nv_wird_nicht_publiziert():
    assert Q.wert(K.READINGS["113-Absenk-Raumtemp"], {("reg", 8): 0x8000}) is None
    assert Q.wert(K.READINGS["151-Datum"], {("reg", 290): 0, ("reg", 291): 11, ("reg", 292): 26}) is None


@pytest.mark.parametrize("nr,ident", [(5, "700500"), (8, "580800"), (270, "cd0e01"), (2580, "96140a"),
                                      (278, "251601"), (19, "541300"), (650, "128a02"), (2, "b80200"),
                                      (274, "091201"), (81, "945100"), (12, "740c00")])
def test_register_id_wie_mitschnitt(nr, ident):
    assert register_id(nr) == ident


def test_ebus_crc_echtes_telegramm():
    # 31 08 50 00 03 df b2 1b -> CRC c8 (raw.log 23.11.2026 13:52:07, vom Kessel quittiert)
    assert ebus_crc([0x31, 0x08, 0x50, 0x00, 0x03, 0xdf, 0xb2, 0x1b]) == 0xc8


def test_zaehler_richtig_skaliert_nach_anleitung():
    # S. 53: i 42 Brennerstarts x 1000, i 43 Betriebsstunden h x 100 (Rohwerte 23.11.2026: 486 / 359)
    assert Q.wert(K.READINGS["I42-Brennerstarts"], {("slot", 0xaa): 486}) == "486000"
    assert Q.wert(K.READINGS["I43-Betriebsstunden-h"], {("slot", 0xab): 359}) == "35900"
