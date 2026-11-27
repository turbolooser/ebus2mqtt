"""Extremwerte (Thomas 27.11.2026): jedes Reading, jeder Broadcast-Wert und jedes Set mit allem, was Therme, Regler
oder ebusd liefern koennten. Erwartet je Fall:
- die Bruecke laeuft weiter (keine Ausnahme verlaesst lese/broadcast/listen_zeile/set_befehl/runde),
- ein Wert, der nicht genau zum ebusd-Datentyp passt, laesst nur dieses Reading stehen (nichts publiziert, kein
  geratener Wert, nichts still geklemmt); "-" ist der Ersatzwert des Typs und wird als genau dieser Rohwert gewandelt,
- ein Set ausserhalb der Grenzen oder ohne gueltiges Format geht nie als Telegramm auf den Bus.
Der Datentyp je Message kommt aus der ebusd-CSV im Repo (das, was ebusd wirklich nutzt), die Bereiche aus dem
ebusd-Wiki 4.3 "Builtin data types" - beides unabhaengig vom Code unter Test.
"""
import json
import math
import os

import pytest

from ebus2mqtt import bruecke as B
from ebus2mqtt import katalog as K
from ebus2mqtt import quellen as Q
from ebus2mqtt import schreiben as S
from ebus2mqtt.ebusd import EbusdFehler

from test_bruecke import FalschesEbusd, FalschesMqtt, Uhr
from test_wandlung import ROH

HIER = os.path.dirname(__file__)
# ebusd-Wiki 4.3: gueltiger Bereich; der ausgesparte Wert ist der Ersatzwert, ausgegeben als "-"
WIKI = {"UCH": (0, 254, 0xFF), "SCH": (-127, 127, -128), "UIN": (0, 65534, 0xFFFF), "SIN": (-32767, 32767, -32768)}
UNGUELTIG = object()


def csv_typen():
    """(circuit, name) -> Datentyp des Feldes "wert" laut ebusd/csv/wtc25.csv."""
    out = {}
    with open(os.path.join(HIER, "..", "ebusd", "csv", "wtc25.csv"), encoding="utf-8") as f:
        for z in f:
            t = z.rstrip("\n").split(",")
            if z.startswith("r,") and "wert" in t:
                out[(t[1], t[2])] = t[t.index("wert") + 2]
    return out


TYP = csv_typen()


def typ(sch):
    return TYP[Q.ebusd_adresse(sch)[:2]]


# Text, wie ebusd ihn fuer das Feld liefern koennte, das nicht vom Datentyp abhaengt
TEXTE = {
    "strich": "-", "leer": "", "leerzeichen": "   ", "None": "None", "null": "null", "n/a": "n/a", "n/v": "n/v",
    "nan": "nan", "inf": "inf", "-inf": "-inf", "komma": "1,5", "punkt": "1.5", "hex 0x8000": "0x8000",
    "text": "abc", "exponent": "1e3", "unterstrich": "1_0", "fremde ziffer": "٣", "plus": "+5",
    "feld fehlt": "54;", "felder zu viel": "1;2;3", "nur trenner": ";", "riesig": "1" + "0" * 30,
}
# Zahlen je Datentyp: Grenzen, eins darueber/darunter, Ersatzwerte anderer Typen, negativ bei unsigned
ZAHLEN = {
    "min": lambda t: WIKI[t][0], "max": lambda t: WIKI[t][1], "min-1": lambda t: WIKI[t][0] - 1,
    "max+1": lambda t: WIKI[t][1] + 1, "0x00": lambda t: 0, "-1": lambda t: -1, "0x7f": lambda t: 0x7F,
    "0xff": lambda t: 0xFF, "0x7fff": lambda t: 0x7FFF, "0x8000": lambda t: 0x8000, "0xffff": lambda t: 0xFFFF,
    "65536": lambda t: 65536, "-32768": lambda t: -32768,
}
FAELLE = sorted(TEXTE) + sorted(ZAHLEN)


def text_und_soll(fall, sch):
    """-> (ebusd-Text, erwarteter Rohwert oder UNGUELTIG) nach dem Wiki, nicht nach dem Code."""
    lo, hi, ersatz = WIKI[typ(sch)]
    if fall in ZAHLEN:
        v = ZAHLEN[fall](typ(sch))
        return str(v), (v if lo <= v <= hi else UNGUELTIG)
    t = TEXTE[fall]
    if t == "-":
        return t, ersatz
    if t == "+5":
        return t, UNGUELTIG  # ebusd schreibt nie ein Pluszeichen
    return t, UNGUELTIG


def bruecke(befehl=None):
    uhr = Uhr()
    e = befehl or FalschesEbusd(ROH)
    b = B.Bruecke(e, FalschesMqtt(), prefix="wcm", uhr=uhr, herzdatei=os.devnull, schlaf=lambda s: None,
                  schreiber=S.ebusd_schreiber(e))
    b.uhr_obj = uhr
    return b


def gruppe(r):
    q, w = r["quelle"], r["wandel"][0]
    if q[0] in ("bc", "bcphase"):
        return f"Broadcast {w}"
    return f"{q[0]} {typ(Q.schluessel(q)[0])} {w}"


LESBAR = [r for r in K.R if r["quelle"][0] in ("slot", "reg", "regs")]


def lese_mit(b, r, text):
    """Alle Teile des Readings liefern diesen Text; alle anderen ihren Normalwert."""
    teile = Q.schluessel(r["quelle"])
    orig = b.befehl.lesen
    adressen = {Q.ebusd_adresse(s)[:2] for s in teile}
    b.befehl.lesen = lambda c, n, f=None, frisch=True: (text, 0.1) if (c, n) in adressen else orig(c, n, f)
    b.mqtt.pub.clear()
    ergebnis = [b.lese(s) for s in teile]
    b.befehl.lesen = orig
    return ergebnis


def pruefe_reading(b, r, roh_soll):
    """roh_soll: {sch: rohwert | UNGUELTIG}. Publiziert genau dann, wenn alle Teile gueltig sind und der Wandler
    einen Wert liefert - und dann genau diesen Text."""
    topic = f"wcm/{r['name']}/value"
    pub = b.mqtt.letzter(topic)
    if any(v is UNGUELTIG for v in roh_soll.values()):
        assert pub is None, f"{r['name']}: unbrauchbarer Wert publiziert: {pub!r}"
        return "steht"
    soll = Q.wert(r, roh_soll)
    erst = Q.schluessel(r["quelle"])[0]
    if r["wandel"][0] not in ("conv_temp", "conv_temp2") and roh_soll[erst] == WIKI[typ(erst)][2]:
        assert soll is None, f"{r['name']}: Ersatzwert als Wert"   # nur vorzeichenbehaftet ist 0xffff = -1
    assert pub == soll, f"{r['name']}: {pub!r} != {soll!r}"
    if pub is not None:
        assert "nan" not in pub.lower() and "inf" not in pub.lower()
    return "steht (n/v)" if pub is None else "Wert"


@pytest.mark.parametrize("fall", FAELLE)
@pytest.mark.parametrize("r", LESBAR, ids=lambda r: r["name"])
def test_lesen_extremwert(r, fall):
    b = bruecke()
    teile = Q.schluessel(r["quelle"])
    text, roh = text_und_soll(fall, teile[0])
    ok = lese_mit(b, r, text)
    assert ok == [roh is not UNGUELTIG] * len(teile)
    pruefe_reading(b, r, {s: roh for s in teile})
    if roh is UNGUELTIG:
        assert all(s not in b.roh for s in teile)
        assert b.fehler, "Fehler muss gezaehlt werden"
    assert b.lese(("slot", 0x1e)) is True  # Bruecke liest weiter


@pytest.mark.parametrize("fall", FAELLE)
@pytest.mark.parametrize("r", LESBAR, ids=lambda r: r["name"])
def test_listen_extremwert(r, fall):
    # derselbe Wert ueber `listen` (ganze Message: Slot "typ;wert", Register "wert")
    b = bruecke()
    teile = Q.schluessel(r["quelle"])
    text, roh = text_und_soll(fall, teile[0])
    if teile[0][0] == "slot":
        text = "54;" + text
        if fall in ("feld fehlt", "felder zu viel", "nur trenner"):
            roh = UNGUELTIG
    b.mqtt.pub.clear()
    for s in teile:
        circ, name, _ = Q.ebusd_adresse(s)
        b.listen_zeile(circ, name, text, b.uhr())
    pruefe_reading(b, r, {s: roh for s in teile})


@pytest.mark.parametrize("fehler", [EbusdFehler("ERR: read timeout"), EbusdFehler("ERR: element not found"),
                                    EbusdFehler("ERR: arbitration lost"), TimeoutError("timed out"),
                                    ConnectionResetError("reset"), RuntimeError("unerwartet"), UnicodeError("x")],
                         ids=lambda e: f"{type(e).__name__}:{e}")
def test_lesefehler_von_ebusd(fehler):
    b = bruecke()

    def wirf(c, n, f=None, frisch=True):
        raise fehler
    b.befehl.lesen = wirf
    for r in LESBAR:
        assert all(b.lese(s) is False for s in Q.schluessel(r["quelle"]))
    assert not [t for t, _, _ in b.mqtt.pub if t.endswith("/value")]
    assert b.sicher(b.runde) is None and b.sicher(b.herzschlag)["gesund"] is False


# ---------------------------------------------------------------- Broadcast f1 fe 50 0a
NORMAL = "01 06 7f 52 22 52 ff ff 00 03 02 03 2d"
BC_FAELLE = {
    "normal": NORMAL, "alle ff": " ".join(["ff"] * 13), "alle 00": " ".join(["00"] * 13),
    "unbekannte bits": "01 13 ff ff ff ff ff ff ff ff ff ff ff", "ein byte": "01", "zwei byte": "01 06",
    "sechs byte": "01 06 7f 52 22 52", "zu lang": " ".join(["7f"] * 31), "leer": "", "strich": "-",
    "drei ziffern": "01 006 7f", "kein hex": "zz 06", "grossbuchstaben": NORMAL.upper(), "ohne trenner": "01067f",
}
BC_READINGS = [r for r in K.R if r["quelle"][0] in ("bc", "bcphase")]


def bc_soll(text):
    teile = text.split()
    if not teile or any(len(x) != 2 or any(c not in "0123456789abcdefABCDEF" for c in x) for x in teile):
        return UNGUELTIG
    return [int(x, 16) for x in teile]


@pytest.mark.parametrize("fall", sorted(BC_FAELLE))
def test_broadcast_extremwert_listen(fall):
    b = bruecke()
    b.mqtt.pub.clear()
    b.listen_zeile(*K.BC_STATUS[:2], BC_FAELLE[fall], b.uhr())
    soll = bc_soll(BC_FAELLE[fall])
    for r in BC_READINGS:
        pub = b.mqtt.letzter(f"wcm/{r['name']}/value")
        if soll is UNGUELTIG:
            assert pub is None, (r["name"], pub)
        else:
            assert pub == Q.wert(r, {("bc",): soll}), r["name"]


@pytest.mark.parametrize("fall", sorted(BC_FAELLE))
def test_broadcast_extremwert_find(fall):
    b = bruecke()
    b.befehl.bc = BC_FAELLE[fall]
    b.befehl.bc_lastup = "2026-11-27 02:27:00"
    b.mqtt.pub.clear()
    b.broadcast()  # darf nie werfen; FIND_BC laesst nur Kleinbuchstaben-Hex durch
    for r in BC_READINGS:
        pub = b.mqtt.letzter(f"wcm/{r['name']}/value")
        if pub is not None:
            assert pub == Q.wert(r, {("bc",): bc_soll(BC_FAELLE[fall])}), r["name"]


def test_broadcast_find_ebusd_weg():
    b = bruecke()

    def weg(zeile):
        raise TimeoutError("timed out")
    b.befehl.anfrage = weg
    assert b.broadcast() is False


def test_broadcast_bits_nur_nach_maske():
    # unbekannte Bits duerfen kein Flag setzen, das nicht zur Maske gehoert
    for byte in range(256):
        daten = [1, byte, byte, byte, 0, 0, 0, 0, 0, 0, 0, 0, 0]
        for r in BC_READINGS:
            if r["wandel"][0] == "bool":
                _, idx, maske = r["quelle"]
                assert Q.wert(r, {("bc",): daten}) == ("ON" if daten[idx] & maske else "OFF")


def test_betriebsphase_unbekannter_code():
    r = K.READINGS["I10-Betriebsphase"]
    for code in range(256):
        t = Q.wert(r, {("bc",): [1, code]})
        assert isinstance(t, str) and t


# ---------------------------------------------------------------- Sets
class Bus(FalschesEbusd):
    """Zaehlt, was als Telegramm auf den Bus ginge."""

    def __init__(self):
        super().__init__(ROH)
        self.telegramme = []

    def anfrage(self, zeile):
        if zeile.startswith("hex "):
            self.telegramme.append(zeile[4:])
            return ["00"]
        return super().anfrage(zeile)


ZAHL_SETS = [n for n, v in K.SCHREIBEN.items() if v[0] in ("kessel", "hk")]
MAP_SETS = [n for n, v in K.SCHREIBEN.items() if v[0] == "hkmap"]
ZP_SETS = [n for n, v in K.SCHREIBEN.items() if v[0] == "zp"]


def grenzen(name):
    v = K.SCHREIBEN[name]
    lo, hi = (v[2], v[3]) if v[0] == "kessel" else (v[3], v[4])
    komp = B.discovery("wcm")["components"][name]
    return max(lo, komp.get("min", lo)), min(hi, komp.get("max", hi))


def zahl_faelle(name):
    lo, hi = grenzen(name)
    return {"min": repr(lo), "max": repr(hi), "min-1": repr(lo - 1), "max+1": repr(hi + 1),
            "min-0.01": repr(lo - 0.01), "max+0.01": repr(hi + 0.01), "nan": "nan", "inf": "inf", "-inf": "-inf",
            "1e400": "1e400", "leer": "", "strich": "-", "text": "abc", "komma": "1,5", "None": "None",
            "riesig": "1e30", "negativ": "-999", "hex": "0x10", "mitte": repr((lo + hi) / 2)}


def set_erlaubt(name, text):
    lo, hi = grenzen(name)
    try:
        v = float(text)
    except ValueError:
        return False
    return math.isfinite(v) and lo <= v <= hi


@pytest.mark.parametrize("fall", sorted(zahl_faelle("P30-Min-VL-Soll")))
@pytest.mark.parametrize("name", ZAHL_SETS)
def test_set_zahl_extremwert(name, fall):
    bus = Bus()
    b = bruecke(bus)
    text = zahl_faelle(name)[fall]
    b.set_befehl(name, text)
    st = json.loads(b.mqtt.letzter(f"wcm/{name}/set_status"))
    if set_erlaubt(name, text):
        assert len(bus.telegramme) == 1, (name, text, st)
        tel = bytes.fromhex(bus.telegramme[0])
        v = float(text)
        if K.SCHREIBEN[name][0] == "kessel":
            assert tel[-1] == int(round(v)) & 0xFF and tel[-2] == K.SCHREIBEN[name][1]
        else:
            mul = K.SCHREIBEN[name][2]
            assert int.from_bytes(tel[-2:], "little") == int(round(v * mul)) & 0xFFFF
    else:
        assert bus.telegramme == [], (name, text)
        assert st["ok"] is False


@pytest.mark.parametrize("name", MAP_SETS)
def test_set_map_extremwert(name):
    karte = K.SCHREIBEN[name][2]
    optionen = list(B.discovery("wcm")["components"][name]["options"])
    for text in optionen:
        bus = Bus()
        bruecke(bus).set_befehl(name, text)
        assert len(bus.telegramme) == 1, text
    for text in ["", "-", "Code 99", optionen[0].upper() + "x", "0", "null", " " + optionen[0]]:
        bus = Bus()
        bruecke(bus).set_befehl(name, text)
        assert bus.telegramme == [], (karte, text)


ZP_GUT = ['[]', '[{"from":"06:00","to":"13:00"}]', '[{"from":"00:00","to":"24:00"}]',
          '[{"from":"06:00","to":"07:00"},{"from":"08:00","to":"09:00"},{"from":"10:00","to":"11:00"}]']
ZP_SCHLECHT = ['', '-', 'null', '{}', '"06:00"', '[1]', '["06:00-13:00"]', '[{"from":"06:00"}]',
               '[{"from":"06:00","to":"24:15"}]', '[{"from":"25:00","to":"26:00"}]', '[{"from":"06:10","to":"07:00"}]',
               '[{"from":"13:00","to":"06:00"}]', '[{"from":"06:00","to":"06:00"}]', '[{"from":6,"to":7}]',
               '[{"from":"-1:00","to":"07:00"}]', '[{"from":"a:b","to":"07:00"}]',
               '[{"from":"01:00","to":"02:00"},{"from":"03:00","to":"04:00"},{"from":"05:00","to":"06:00"},'
               '{"from":"07:00","to":"08:00"}]', '[{"from":"06:00","to":"07:00"}', 'NaN']


@pytest.mark.parametrize("text", ZP_GUT + ZP_SCHLECHT)
def test_set_zeitprogramm_extremwert(text):
    bus = Bus()
    b = bruecke(bus)
    b.set_befehl(ZP_SETS[0], text)
    st = json.loads(b.mqtt.letzter(f"wcm/{ZP_SETS[0]}/set_status"))
    if text in ZP_GUT:
        assert len(bus.telegramme) == 3, st
    else:
        assert bus.telegramme == [], (text, st)
        assert st["ok"] is False


def test_zeitprogramm_lesen_ueber_24_uhr_steht():
    r = K.READINGS["ZP1-MO"]
    teile = Q.schluessel(r["quelle"])
    assert Q.wert(r, dict(zip(teile, [0x1834, 0x6162, 0x8080]))) is None    # 24:15-24:30 ist keine Uhrzeit
    assert Q.wert(r, dict(zip(teile, [0x1834, 0x8080, 0x8080]))) == '[{"from":"06:00","to":"13:00"}]'


def test_hauptschleife_ueberlebt_unerwartetes():
    b = bruecke()

    def kaputt():
        raise ZeroDivisionError("x")
    kaputt.__name__ = "runde"
    assert b.sicher(kaputt) is None and b.sicher(kaputt) is None
    assert sum(v for k, v in b.fehler.items() if k.startswith("Hauptschleife")) == 2
