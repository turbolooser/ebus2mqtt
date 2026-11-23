"""Einzige Quelle: welches Reading kommt woher und wie wird es geschrieben.

Daraus entstehen die ebusd-CSV (tools/gen_csv.py, Test prueft Gleichstand) und die Bruecke.
Busteilnehmer (Mitschnitt 23.11.2026): Master ff = WCM-COM, 30/35 = WCM-FS (Heizkreis), f1 = Feuerungs-
automat, 03/08 = Kessel. ebusd liest als 31.

Quellen
- slot:  Kessel 08, Dienst 50 03, 1 Byte Slot. Antwort 0x00-0x7f: typ wert vor nach x x (Displaywert, 1 Byte);
         0x80-0xff: typ lo hi vor nach (16 bit). Belegung: wissen/heizung/bruecke/ebus-vs-wcm-leseliste.md.
- reg:   WCM-FS 35, Dienst 50 22, ID = Pruefbyte + infoNr LE (dieselben infoNr wie wcm2mqtt hk1.json/userzeit.json).
- bc:    Broadcast f1 -> fe 50 0a (13 Byte, alle 30 s) bzw. 30 -> f1 05 07; Byte-Index im Datenteil.
- eeprom: Kessel 08, Speicherlesen 50 00, 12-Byte-Bloecke (wtca-eeprom.csv vom 23.11.2026).

"belegt": aus Mitschnitt/Display bewiesen. "kandidat": Wert passt, Beweis steht aus -> die 24-h-Probe
entscheidet (tools/vergleich.py wertet die Rohkandidaten unter <prefix>/_roh/ aus).
"""

# ---------------------------------------------------------------- Kessel-Slots (50 03)
# slot: (ebusd-Name, Kommentar, vorzeichen, belegt)
SLOTS = {
    0x0b: ("P10", "Display P10", False, True),
    0x0c: ("P11", "Display P11", False, True),
    0x0d: ("P12", "Display P12", False, True),
    0x0e: ("P13", "Display P13", False, True),
    0x0f: ("P15", "Display P15", False, True),
    0x11: ("P17", "Display P17", False, True),
    0x12: ("P18", "Sonderniveau Heizbetrieb", False, True),
    0x14: ("P20", "Korrektur Aussenfuehler", True, True),
    0x15: ("P21", "Display P21", False, True),
    0x16: ("P22", "Display P22 (x0,5)", False, True),
    0x17: ("P23", "Anlagenfrostschutz", True, True),
    0x1e: ("P30", "Min-VL-Soll", False, True),
    0x1f: ("P31", "Max-VL-Soll", False, True),
    0x20: ("P32", "Schaltdifferenz VL", False, True),
    0x21: ("P33", "Abgas-Abschalttemperatur", False, True),
    0x22: ("P34", "Brenner-Taktsperre", False, True),
    0x23: ("P35", "Startgasmenge (x0,5 %)", False, True),
    0x24: ("P36", "Min-Leistung", False, True),
    0x25: ("P37", "Max-Leistung Heizung", False, True),
    0x27: ("P39", "Display P39 (x0,1)", False, True),
    0x28: ("P40", "Pumpenbetriebsart", False, True),
    0x29: ("P41", "Pumpennachlauf", False, True),
    0x2a: ("P42", "Pumpenleistung min Heizung", False, True),
    0x2b: ("P43", "Pumpenleistung max Heizung", False, True),
    0x46: ("P70", "Display P70 (x10 h)", False, True),
    0x48: ("P72", "Display P72 (x0,1)", False, True),
    # Info-Slots, 16 bit
    0x8b: ("I11", "Laststellung", False, True),
    0x8c: ("S8c", "Bedeutung offen (typ b6; blieb 3 als I33 auf 2 fiel)", True, False),
    0x8d: ("I13", "Waermeanforderung", False, True),
    0x9e: ("I30", "Vorlauftemperatur", False, True),
    0x9f: ("I31", "Abgastemperatur", False, True),
    0xa0: ("Sa0", "Bedeutung offen (typ 3c; 55-57)", True, False),
    0xa1: ("Sa1", "Aussentemperatur ganze Grad (folgt Reg 12)", True, False),
    0xaa: ("I42", "Schaltspiele Brenner (16 bit, Skala offen)", False, True),
    0xab: ("I43", "Betriebsstunden Brenner (16 bit, Skala offen)", False, True),
    0xad: ("I70", "Zeit seit Wartung", False, True),
}
# weitere Info-Slots nur als Rohkandidaten (Bedeutung offen, 23.11.2026 nicht 0x3055-Leerwert)
KANDIDAT_SLOTS = [0x8a, 0x8e, 0x8f, 0x94, 0x95, 0x96, 0x97, 0xa2, 0xa3, 0xa4, 0xa6, 0xa7, 0xa8, 0xa9, 0xac, 0xae]

# ---------------------------------------------------------------- WCM-FS-Register (50 22 an 35)
REG = {
    4: "416 Vorlauf-Soll", 5: "413 Normal-Raumtemp", 8: "113 Absenk-Raumtemp", 270: "117 Steilheit",
    274: "111 Betriebsart", 278: "So-Wi-Umschalttemp", 306: "501 Reduzierbetrieb", 317: "Frostschutztemp",
    321: "Hk1-Regelvariante", 2419: "Fussbodenerwaermung", 2580: "Raumfrosttemp", 2586: "412 gem. Aussentemp",
    1: "I10 Fehlercode", 12: "I33 Aussentemperatur", 2572: "I12 ged. Aussentemperatur",
    290: "Datum Tag", 291: "Datum Monat", 292: "Datum Jahr", 293: "Uhrzeit Stunde", 294: "Uhrzeit Minute",
}
# Zeitprogramme: Basis-infoNr je ZP/Tag, je 3 Register (wcm2mqtt userzeit.json, autogen 3)
ZP_BASIS = {
    "ZP1": {"MO": 5136, "DI": 5152, "MI": 5168, "DO": 5184, "FR": 5200, "SA": 5216, "SO": 5232},
    "ZP2": {"MO": 5392, "DI": 5408, "MI": 5424, "DO": 5440, "FR": 5456, "SA": 5472, "SO": 5488},
    "ZP3": {"MO": 5648, "DI": 5664, "MI": 5680, "DO": 5696, "FR": 5712, "SA": 5728, "SO": 5744},
}
for _zp, _tage in ZP_BASIS.items():
    for _tag, _b in _tage.items():
        for _i in range(3):
            REG[_b + _i] = f"{_zp}-{_tag} Fenster {_i + 1}"
# Kandidaten: wcm2mqtt fragt diese infoNr am internen Bus 10 (WTC); ob das WCM-FS sie fuehrt, zeigt die Probe.
KANDIDAT_REG = [2, 81, 82, 373, 466, 1497]
for _n in KANDIDAT_REG:
    REG.setdefault(_n, f"Kandidat WTC-infoNr {_n}")

# ---------------------------------------------------------------- Broadcasts
# f1 fe 50 0a, 13 Datenbytes, z. B. 01 06 7f 52 22 52 ff ff 00 03 02 03 2d (Brenner an, 23.11. 14:13)
#  [1] Betriebsphase (= WCM I10, Codes 0/6/8/19 belegt)   [4] Laststellung % (= I11)   [5] Vorlauf x0,5 (= 3101)
#  [2] Bits: 0x47 aus / 0x7f Start+Betrieb   [3] Bits: 0x12 aus / 0x52 Anforderung   Rest bisher konstant
BC_STATUS = ("wtc", "Status", "f1", "fe", "500a", 13)
# 30 f1 05 07 (genormt): Zustand, Aktion, Kesselsollwert D2C, Druck D2C, Stellgrad, WW-Soll, Brennstoff
BC_REGLER = ("regler", "Betriebsdaten", "30", "f1", "0507", 9)

# ---------------------------------------------------------------- EEPROM (50 00), Bloecke wie 117
EEPROM_BLOECKE = {
    "Fachmann1": ("dfb21b", 0x1b, 12), "Fachmann2": ("e3b227", 0x27, 12), "Fachmann3": ("f7b233", 0x33, 12),
    "Fachmann4": ("fbb23f", 0x3f, 12),
}

# ---------------------------------------------------------------- Schreiben
# Kessel-Parameter: 50 04 an Master 03 (= Kessel 08), Daten [Slot][Wert], Master-Master (nur ACK). Belegt 23.11.2026:
# WCM-Set 15:00 "ff 03 50 04 02 1e 28" (P30 41->40); von Quelle 31 angenommen (Freigabe-Test 15:07, P31 43->44->43,
# je ACK in 0,15 s, Ruecklesen per Slot sofort). Nur diese beiden sind belegt; alle anderen Sets bleiben gesperrt.
# P42 60->70 von Quelle 31 am 23.11.2026 17:34 angenommen (Slot + EEPROM 0x20 zurueckgelesen).
# Heizkreis-Werte (WCM-FS 35): 50 23 an 35 mit CRC; von Quelle 31 quittiert, aber nicht uebernommen (Test 17:40),
# also nur mit EBUSD_ADDRESS=ff - und das nur, wenn das WCM-COM (selbst ff) vom Bus getrennt ist.
# ("kessel", slot, min, max) | ("hk", infoNr, faktor, min, max) | ("hkmap", infoNr, karte) | ("zp",)
# Grenzen: Weishaupt-Anleitung 83247501 S. 54/55 bzw. Discovery von wcm2mqtt bzw. aghulas settings-writes.md.
SCHREIBEN = {
    "P30-Min-VL-Soll": ("kessel", 0x1e, 8, 78), "P31-Max-VL-Soll": ("kessel", 0x1f, 8, 82),
    "Schaltdifferenz-VL": ("kessel", 0x20, 1, 7), "Brenner-Taktsperre": ("kessel", 0x22, 1, 15),
    "P37-Max-Leistung-Heizung": ("kessel", 0x25, 1, 100), "Sondernieveau-Heizbetrieb": ("kessel", 0x12, 8, 82),
    "Korrektur-Außenfühler": ("kessel", 0x14, -4, 4), "Anlagenfrostschutz": ("kessel", 0x17, -10, 10),
    "P42-Pumpenleistung-min": ("kessel", 0x2a, 20, 100), "P43-Pumpenleistung-max": ("kessel", 0x2b, 20, 100),
    "413-Normal-Raumtemp": ("hk", 5, 10, 10, 30), "113-Absenk-Raumtemp": ("hk", 8, 10, 10, 30),
    "117-Steilheit": ("hk", 270, 10, 2.5, 40), "So-Wi-Umschalttemperatur": ("hk", 278, 10, -4, 30),
    "Raumfrosttemperatur": ("hk", 2580, 10, 4, 16),
    "111-Betriebsart": ("hkmap", 274, "Program"), "501-Reduzierbetrieb": ("hkmap", 306, "Reduzierbetrieb"),
    "Hk1-Regelvariante": ("hkmap", 321, "Regelvariante"),
}
for _zp, _tage in ZP_BASIS.items():
    for _tag in _tage:
        SCHREIBEN[f"{_zp}-{_tag}"] = ("zp",)
# Bei Quelle 31 (WCM-COM noch am Bus, schreibt die uebrigen Werte selbst) nur diese; bei ff alle.
SCHREIBEN_BEI_31 = ["P30-Min-VL-Soll", "P31-Max-VL-Soll", "P42-Pumpenleistung-min", "P43-Pumpenleistung-max"]


def schreibbar(adresse):
    """Readings, deren Sets die Bruecke bei dieser ebusd-Master-Adresse abonniert."""
    return list(SCHREIBEN) if adresse.lower() == "ff" else list(SCHREIBEN_BEI_31)

# ---------------------------------------------------------------- Takte (s)
TAKT = {"schnell": 60, "param": 180, "hk": 300, "zeit": 300, "display": 900, "eeprom": 900, "kandidat": 180}

# ---------------------------------------------------------------- Readings
# Felder: name (= Topic + unique_id wie wcm2mqtt), quelle, wandel, takt (iv in fresh), neu (nicht in wcm2mqtt)
# quelle: ("slot", s) | ("reg", n) | ("regs", [n..]) | ("bc", feld, maske) | ("bcphase",)
# wandel: ("zahl", mul, fmt) | ("conv_temp", div, acc) | ("conv_calc2", div, mul, acc) | ("map", karte)
#         | ("bool",) | ("date",) | ("time",) | ("zp",) | ("lowbyte", mul, fmt)
R = []


def _r(name, quelle, wandel, takt, neu=False, belegt=True, ha=None):
    R.append(dict(name=name, quelle=quelle, wandel=wandel, takt=takt, neu=neu, belegt=belegt, ha=ha or {}))


# --- wtc-g (23)
_r("Anlagenfrostschutz", ("slot", 0x17), ("zahl", 1, "f1"), "param")
_r("Brenner-Taktsperre", ("slot", 0x22), ("zahl", 1, "g"), "param")
_r("Flamme", ("bc", 2, 0x08), ("bool",), "schnell", belegt=False)
_r("Gasventil", ("bc", 2, 0x10), ("bool",), "schnell", belegt=False)
_r("I10-Betriebsphase", ("bcphase",), ("map", "HzZustand"), "schnell")
# I10-Fehler/I12/I33: das WCM-FS (35) fuehrt dieselben infoNr wie wcm2mqtt wtc-g.json (Probe 23.11.2026: Reg 1 = 0,
# Reg 2572 = 30 = WCM 3; Reg 12 folgte den WCM-Wechseln 3->2 16:54 und 2->3 16:55 je im naechsten Lesezyklus)
_r("I10-Fehler", ("reg", 1), ("map", "ErrorCodes"), "param")
_r("I11-Laststellung", ("slot", 0x8b), ("zahl", 1, "g"), "schnell")
_r("I12-Ged-Aussentemperatur", ("reg", 2572), ("conv_temp2", 10), "param")
_r("I13-Wärmeanforderung", ("slot", 0x8d), ("zahl", 1, "g"), "schnell")
_r("I31-Abgastemperatur", ("slot", 0x9f), ("zahl", 1, "g"), "schnell")
_r("I33-Aussentemperatur", ("reg", 12), ("conv_temp2", 10), "param")
# wcm2mqtt conv_calc nimmt nur das Low-Byte (486 -> 230 -> "230000"); nachgebildet, damit HA gleich bleibt
_r("I42-Schaltspielzahl-Brenner", ("slot", 0xaa), ("lowbyte", 1000, "g"), "param")
_r("I43-Betriebsstunden-Brenner", ("slot", 0xab), ("lowbyte", 1000, "g"), "param")
_r("Korrektur-Außenfühler", ("slot", 0x14), ("zahl", 1, "g"), "param")
_r("P30-Min-VL-Soll", ("slot", 0x1e), ("zahl", 1, "f1"), "param")
_r("P31-Max-VL-Soll", ("slot", 0x1f), ("zahl", 1, "f1"), "param")
_r("P37-Max-Leistung-Heizung", ("slot", 0x25), ("zahl", 1, "g"), "param")
_r("Pumpe", ("bc", 2, 0x40), ("bool",), "schnell", belegt=False)
_r("Schaltdifferenz-VL", ("slot", 0x20), ("zahl", 1, "f1"), "param")
_r("Sondernieveau-Heizbetrieb", ("slot", 0x12), ("zahl", 1, "g"), "param")
_r("Vorlauftemperatur", ("slot", 0x9e), ("zahl", 1, "g"), "schnell")
_r("Zeit-letzte-Wartung", ("slot", 0xad), ("zahl", 10, "d"), "param")
_r("Brenneranforderung-Heizung", ("bc", 3, 0x40), ("bool",), "schnell", belegt=False)
# --- hk1 (12)
_r("111-Betriebsart", ("reg", 274), ("map", "Program"), "hk")
_r("113-Absenk-Raumtemp", ("reg", 8), ("conv_temp", 10, 0.5), "hk")
_r("117-Steilheit", ("reg", 270), ("conv_temp", 10, 0.5), "hk")
_r("412-Gemischte-Aussentemperatur", ("reg", 2586), ("conv_temp", 10, 0.5), "hk")
_r("413-Normal-Raumtemp", ("reg", 5), ("conv_temp", 10, 0.5), "hk")
_r("416-Soll-Temp", ("reg", 4), ("conv_temp", 10, 1.0), "hk")
_r("501-Reduzierbetrieb", ("reg", 306), ("map", "Reduzierbetrieb"), "hk")
_r("Hk1-Regelvariante", ("reg", 321), ("map", "Regelvariante"), "hk")
_r("So-Wi-Umschalttemperatur", ("reg", 278), ("conv_temp", 10, 0.1), "hk")
_r("Raumfrosttemperatur", ("reg", 2580), ("conv_temp", 10, 0.1), "hk")
_r("Frostschutztemperatur", ("reg", 317), ("conv_temp", 10, 0.1), "hk")
_r("Fussbodenerwaermung", ("reg", 2419), ("conv_calc2", 1, 1, 1.0), "hk")
# --- userzeit (23)
_r("151-Datum", ("regs", [290, 291, 292]), ("date",), "zeit")
_r("152-Uhrzeit", ("regs", [293, 294]), ("time",), "zeit")
for _zp, _tage in ZP_BASIS.items():
    for _tag in ("DI", "DO", "FR", "MI", "MO", "SA", "SO"):
        _b = _tage[_tag]
        _r(f"{_zp}-{_tag}", ("regs", [_b, _b + 1, _b + 2]), ("zp",), "zeit")

# --- neu, nur lesen (nicht in wcm2mqtt). unique_id = name, Geraet bleibt "wcm".
_T = {"device_class": "temperature", "state_class": "measurement", "unit_of_measurement": "°C"}
_P = {"state_class": "measurement", "unit_of_measurement": "%"}
for _s, _name, _mul, _fmt, _ha in [
    (0x0b, "P10-Display", 1, "g", {}), (0x0c, "P11-Display", 1, "g", {}), (0x0d, "P12-Display", 1, "g", {}),
    (0x0e, "P13-Display", 1, "g", {}), (0x0f, "P15-Display", 1, "g", {}), (0x11, "P17-Display", 1, "g", {}),
    (0x15, "P21-Display", 1, "g", {}), (0x16, "P22-Display", 0.5, "f1", {}),
    (0x21, "P33-Abgas-Abschalttemperatur", 1, "g", _T), (0x23, "P35-Startgas", 0.5, "f1", _P),
    (0x24, "P36-Min-Leistung", 1, "g", _P), (0x27, "P39-Display", 0.1, "f1", {}),
    (0x28, "P40-Pumpenbetriebsart", 1, "g", {}), (0x29, "P41-Pumpennachlauf", 1, "g", {"unit_of_measurement": "min"}),
    (0x2a, "P42-Pumpenleistung-min", 1, "g", _P), (0x2b, "P43-Pumpenleistung-max", 1, "g", _P),
    # P70 S. 56: "100 … 500 h x 10" - Wert wie am Display, Einheit "× 10 h"
    (0x46, "P70-Display", 10, "g", {"unit_of_measurement": "× 10 h"}), (0x48, "P72-Display", 0.1, "f1", {}),
]:
    _r(_name, ("slot", _s), ("zahl", _mul, _fmt), "display", neu=True, ha=dict(platform="sensor", **_ha))
_r("I42-Schaltspiele-roh", ("slot", 0xaa), ("zahl", 1, "g"), "param", neu=True,
   ha={"platform": "sensor", "state_class": "total_increasing"})
_r("I43-Betriebsstunden-roh", ("slot", 0xab), ("zahl", 1, "g"), "param", neu=True,
   ha={"platform": "sensor", "state_class": "total_increasing"})
# richtig skaliert nach Anleitung S. 53 (i 42 "x 1000", i 43 "h x 100"); die WCM-kompatiblen I42/I43 bleiben
_r("I42-Brennerstarts", ("slot", 0xaa), ("zahl", 1000, "d"), "param", neu=True,
   ha={"platform": "sensor", "state_class": "total_increasing"})
_r("I43-Betriebsstunden-h", ("slot", 0xab), ("zahl", 100, "d"), "param", neu=True,
   ha={"platform": "sensor", "state_class": "total_increasing", "device_class": "duration",
       "unit_of_measurement": "h"})
_r("Vorlauf-Broadcast", ("bc", 5, None), ("zahl", 0.5, "f1"), "schnell", neu=True, ha=dict(platform="sensor", **_T))

READINGS = {r["name"]: r for r in R}
WCM_NAMEN = [r["name"] for r in R if not r["neu"]]

# ---------------------------------------------------------------- Klartext fuer das Web-Frontend
# Bezeichnung, Gruppe; Einheit nur, wo die Discovery keine traegt. P-Nummern nach Weishaupt-Fachmannebene WTC-25-A.
BEZEICHNUNG = {
    "Anlagenfrostschutz": ("P23 Anlagenfrostschutz", "Kessel"),
    "Brenner-Taktsperre": ("P34 Brenner-Taktsperre", "Kessel"),
    "Flamme": ("Flamme", "Brenner"),
    "Gasventil": ("Gasventil", "Brenner"),
    "I10-Betriebsphase": ("I10 Betriebsphase", "Brenner"),
    "I10-Fehler": ("I10 Fehler", "Brenner"),
    "I11-Laststellung": ("I11 Laststellung (Modulation)", "Brenner"),
    "I12-Ged-Aussentemperatur": ("I12 gedämpfte Außentemperatur", "Kessel"),
    "I13-Wärmeanforderung": ("I13 Wärmeanforderung (Kesselsoll)", "Kessel"),
    "I31-Abgastemperatur": ("I31 Abgastemperatur", "Kessel"),
    "I33-Aussentemperatur": ("I33 Außentemperatur", "Kessel"),
    "I42-Schaltspielzahl-Brenner": ("I42 Brennerstarts (wie WCM: Low-Byte × 1000)", "Zähler"),
    "I43-Betriebsstunden-Brenner": ("I43 Betriebsstunden (wie WCM: Low-Byte × 1000)", "Zähler"),
    "Korrektur-Außenfühler": ("P20 Korrektur Außenfühler", "Kessel"),
    "P30-Min-VL-Soll": ("P30 minimale Vorlauf-Solltemperatur", "Kessel"),
    "P31-Max-VL-Soll": ("P31 maximale Vorlauf-Solltemperatur", "Kessel"),
    "P37-Max-Leistung-Heizung": ("P37 maximale Leistung Heizung", "Kessel"),
    "Pumpe": ("Kesselpumpe", "Brenner"),
    "Schaltdifferenz-VL": ("P32 Schaltdifferenz Vorlauf", "Kessel"),
    "Sondernieveau-Heizbetrieb": ("P18 Sonderniveau Heizbetrieb", "Kessel"),
    "Vorlauftemperatur": ("Vorlauftemperatur (eSTB)", "Kessel"),
    "Zeit-letzte-Wartung": ("I45 Zeit seit letzter Wartung (h)", "Zähler"),
    "Brenneranforderung-Heizung": ("Brenneranforderung Heizung", "Brenner"),
    "111-Betriebsart": ("111 Betriebsart Heizkreis", "Heizkreis"),
    "113-Absenk-Raumtemp": ("113 Absenk-Raumtemperatur", "Heizkreis"),
    "117-Steilheit": ("117 Heizkurve Steilheit", "Heizkreis"),
    "412-Gemischte-Aussentemperatur": ("412 gemischte Außentemperatur", "Heizkreis"),
    "413-Normal-Raumtemp": ("413 Normal-Raumtemperatur", "Heizkreis"),
    "416-Soll-Temp": ("416 Vorlauf-Solltemperatur Heizkreis", "Heizkreis"),
    "501-Reduzierbetrieb": ("501 Reduzierbetrieb", "Heizkreis"),
    "Hk1-Regelvariante": ("Regelvariante Heizkreis 1", "Heizkreis"),
    "So-Wi-Umschalttemperatur": ("119 Sommer/Winter-Umschalttemperatur", "Heizkreis"),
    "Raumfrosttemperatur": ("118 Raumfrosttemperatur", "Heizkreis"),
    "Frostschutztemperatur": ("Frostschutztemperatur", "Heizkreis"),
    "Fussbodenerwaermung": ("Fußbodenerwärmung (Heizkreistyp)", "Heizkreis"),
    "151-Datum": ("151 Datum Regler", "Zeit"),
    "152-Uhrzeit": ("152 Uhrzeit Regler", "Zeit"),
    "P10-Display": ("P10 Gerätekonfiguration", "Display P10–P72"),
    "P11-Display": ("P11 Gasart", "Display P10–P72"),
    "P12-Display": ("P12 Kesseladresse", "Display P10–P72"),
    "P13-Display": ("P13 Funktion variabler Ausgang", "Display P10–P72"),
    "P15-Display": ("P15 Funktion Eingang H1", "Display P10–P72"),
    "P17-Display": ("P17 Funktion Eingang H2", "Display P10–P72"),
    "P21-Display": ("P21 Bewertung Gebäude", "Display P10–P72"),
    "P22-Display": ("P22 Heizkennlinien-Steilheit (Kessel)", "Display P10–P72"),
    "P33-Abgas-Abschalttemperatur": ("P33 Abgas-Abschalttemperatur", "Display P10–P72"),
    "P35-Startgas": ("P35 Startgasmenge", "Display P10–P72"),
    "P36-Min-Leistung": ("P36 minimale Leistung", "Display P10–P72"),
    "P39-Display": ("P39 O2-Korrektur gesamter Bereich", "Display P10–P72"),
    "P40-Pumpenbetriebsart": ("P40 Pumpenbetriebsart", "Display P10–P72"),
    "P41-Pumpennachlauf": ("P41 Pumpennachlaufzeit", "Display P10–P72"),
    "P42-Pumpenleistung-min": ("P42 minimale Pumpenleistung Heizung", "Display P10–P72"),
    "P43-Pumpenleistung-max": ("P43 maximale Pumpenleistung Heizung", "Display P10–P72"),
    "P70-Display": ("P70 Wartungsintervall", "Display P10–P72"),
    "P72-Display": ("P72 O2-Korrektur unterer Bereich", "Display P10–P72"),
    "I42-Schaltspiele-roh": ("I42 Brennerstarts × 1000 (Rohwert 16 bit)", "Zähler"),
    "I43-Betriebsstunden-roh": ("I43 Betriebsstunden h × 100 (Rohwert 16 bit)", "Zähler"),
    "Vorlauf-Broadcast": ("Vorlauftemperatur aus Broadcast (0,5 K)", "Kessel"),
    "I42-Brennerstarts": ("I42 Brennerstarts (richtig skaliert, × 1000)", "Zähler"),
    "I43-Betriebsstunden-h": ("I43 Betriebsstunden Brenner (richtig skaliert, h × 100)", "Zähler"),
}
for _zp in ("ZP1", "ZP2", "ZP3"):
    for _tag, _lang in (("MO", "Montag"), ("DI", "Dienstag"), ("MI", "Mittwoch"), ("DO", "Donnerstag"),
                        ("FR", "Freitag"), ("SA", "Samstag"), ("SO", "Sonntag")):
        BEZEICHNUNG[f"{_zp}-{_tag}"] = (f"Zeitprogramm {_zp[-1]} {_lang}", "Zeitprogramme")
EINHEIT = {"Brenner-Taktsperre": "min", "Zeit-letzte-Wartung": "h", "P39-Display": "%-Pkt.",
           "P72-Display": "%-Pkt.", "P37-Max-Leistung-Heizung": "%", "I11-Laststellung": "%",
           "Sondernieveau-Heizbetrieb": "°C", "P35-Startgas": "%"}

# Doku-Link je Reading (daten/doku.json): {"url", "quelle"} oder bewusst leer {"url": null, "grund"}.
# Reihenfolge der Quellen: Weishaupt-Anleitung WTC 15-A/25-A mit PDF-Seite, dann eBUS-Quellen (jdanion, aghulas).
import json as _json  # noqa: E402
import os as _os  # noqa: E402

with open(_os.path.join(_os.path.dirname(__file__), "daten", "doku.json"), encoding="utf-8") as _f:
    DOKU = _json.load(_f)

# Einheiten-Korrekturen der Discovery gegenueber wcm2mqtt, belegt mit der Weishaupt-Anleitung 83247501.
# Nur Entitaeten ohne Langzeitstatistik in HA (number, oder sensor ohne state_class), also kein Bruch.
# None = Schluessel entfernen.
DISCOVERY_KORREKTUR = {
    # S. 55 P 22 "Heizkennlinien-Steilheit 2.5 … 40" ohne Einheit, S. 60 "Steilheit" dimensionslos
    "117-Steilheit": {"unit_of_measurement": None, "device_class": None},
    # S. 55 P 32 "Schaltdifferenz Vorlauf +1 … 7 K": Differenz in K, keine absolute Temperatur
    "Schaltdifferenz-VL": {"unit_of_measurement": "K", "device_class": None},
    # S. 55 P 20 "Außenfühler-Korrektur -4 … 4 K": Differenz; device_class temperature wuerde K als Kelvin deuten
    "Korrektur-Außenfühler": {"device_class": None},
    "Brenner-Taktsperre": {"unit_of_measurement": "min"},          # S. 55 P 34 "1 … 15 min"
    "P37-Max-Leistung-Heizung": {"unit_of_measurement": "%"},      # S. 55 P 37 "… 100 %"
    "I11-Laststellung": {"unit_of_measurement": "%"},              # S. 52 i 11 "Leistung %"
    "Zeit-letzte-Wartung": {"unit_of_measurement": "h"},           # S. 53 i 45 "h x 10" (Wert schon x 10)
}
