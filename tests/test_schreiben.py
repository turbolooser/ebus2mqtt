"""Schreibtelegramme: Bytes wie am 23.11.2026 am Bus gesendet bzw. von aghulas belegt."""
import json

import pytest

from ebus2mqtt import katalog as K
from ebus2mqtt import quellen as Q
from ebus2mqtt import schreiben as S


def test_kessel_wie_am_bus():
    assert S.telegramme("P42-Pumpenleistung-min", "70") == ["035004022a46"]     # 17:34:31, angenommen
    assert S.telegramme("P43-Pumpenleistung-max", "80") == ["035004022b50"]     # 17:46:33, angenommen
    assert S.telegramme("P30-Min-VL-Soll", "40.0") == ["035004021e28"]          # WCM-Set 15:00 "ff 03 50 04 02 1e 28"
    assert S.telegramme("Korrektur-Außenfühler", "-1") == ["0350040214ff"]


def test_heizkreis_crc_wie_aghulas():
    assert S.telegramme("413-Normal-Raumtemp", "20.0") == ["35502305f80500c800"]   # 17:40:12 gesendet
    assert S.telegramme("413-Normal-Raumtemp", "19.5") == ["35502305440500c300"]
    assert S.register(0x011b, 29) == "35502305fc1b011d00"                       # aghulas write-methods.md
    assert S.telegramme("So-Wi-Umschalttemperatur", "-4") == [S.register(278, 0xFFD8)]
    assert S.telegramme("111-Betriebsart", "Programm-3") == [S.register(274, 13)]


def test_zeitprogramm_rundlauf():
    text = '[{"from":"06:00","to":"13:00"},{"from":"15:00","to":"22:00"}]'
    tel = S.telegramme("ZP1-MO", text)
    assert tel == [S.register(5136, 0x1834), S.register(5137, 0x3c58), S.register(5138, 0x8080)]
    # Ruecklesen derselben Register ergibt wieder denselben Text
    r = K.READINGS["ZP1-MO"]
    assert Q.wert(r, {("reg", 5136): 0x1834, ("reg", 5137): 0x3c58, ("reg", 5138): 0x8080}) == S.soll_text("ZP1-MO", text)


@pytest.mark.parametrize("name,text", [("P42-Pumpenleistung-min", "10"), ("117-Steilheit", "50"),
                                       ("ZP1-MO", '[{"from":"06:10","to":"13:00"}]'),
                                       ("ZP1-MO", json.dumps([{"from": "06:00", "to": "07:00"}] * 4)),
                                       ("501-Reduzierbetrieb", "Quatsch")])
def test_ungueltig(name, text):
    with pytest.raises(S.SchreibFehler):
        S.telegramme(name, text)


def test_jeder_schreibweg_hat_ein_reading():
    assert set(S.K.SCHREIBEN) <= set(K.READINGS)


def test_bei_31_nur_kessel_sets_mit_beleg():
    assert K.schreibbar("31") == ["P30-Min-VL-Soll", "P31-Max-VL-Soll", "P42-Pumpenleistung-min", "P43-Pumpenleistung-max"]
    alle = K.schreibbar("ff")
    assert "413-Normal-Raumtemp" in alle and "ZP3-SO" in alle and len(alle) == len(K.SCHREIBEN)
