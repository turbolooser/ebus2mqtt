"""Quellen eines Readings (welche ebusd-Messages) und Umrechnung der Rohwerte in den MQTT-Text."""
import re

from . import katalog as K
from . import wandler as W
from .csvgen import datentyp, reg_name, slot_name

# ebusd-Zahlentypen (Wiki 4.3 "Builtin data types"): gueltiger Bereich und der ausgesparte Ersatzwert, den ebusd
# als "-" ausgibt. "-" ist darum kein Lesefehler, sondern genau dieser Rohwert: 27.11.2026 02:27 lieferte Reg 2572
# (I12, UIN, x0,1) "-" = 0xffff = -0,1 Grad, nachdem I12 von 0,1 auf 0 gefallen war (HA-Verlauf).
TYPEN = {"UCH": (0, 254, 0xFF), "SCH": (-127, 127, -128), "UIN": (0, 65534, 0xFFFF), "SIN": (-32767, 32767, -32768)}
ZAHL = re.compile(r"-?[0-9]+")
HEXBYTE = re.compile(r"[0-9a-fA-F]{2}")
# Nur fuer die vorzeichenbehafteten 16-bit-Wandler ist der UIN-Ersatzwert 0xffff ein echter Wert (-1 Zehntel); fuer
# Zahlen, Karten, Datum, Uhrzeit, Zeitprogramm und conv_calc2 (ohne Vorzeichen) heisst er "kein Wert".
ERSATZ_IST_WERT = ("conv_temp", "conv_temp2")


def schluessel(quelle):
    """Quell-Schluessel, unter denen der Rohwert-Speicher fuehrt: ('slot', s), ('reg', n), ('bc',)."""
    art = quelle[0]
    if art == "slot":
        return [("slot", quelle[1])]
    if art == "reg":
        return [("reg", quelle[1])]
    if art == "regs":
        return [("reg", n) for n in quelle[1]]
    if art in ("bc", "bcphase"):
        return [("bc",)]
    raise ValueError(quelle)


def ebusd_adresse(sch):
    """Quell-Schluessel -> (circuit, name, feld) fuer `read`."""
    if sch[0] == "slot":
        return "wtc", slot_name(sch[1]), "wert"
    if sch[0] == "reg":
        return "hk1", reg_name(sch[1]), "wert"
    if sch[0] == "bc":
        return K.BC_STATUS[0], K.BC_STATUS[1], "daten"
    raise ValueError(sch)


def ersatzwert(sch):
    """Rohwert, den ebusd fuer diesen Schluessel als "-" ausgibt (None fuer Broadcasts: HEX hat keinen)."""
    return None if sch[0] == "bc" else TYPEN[datentyp(sch)][2]


def roh_parsen(sch, text):
    """ebusd-Text -> Rohwert: int fuer Slot/Register, Liste von Bytes fuer Broadcasts. Alles, was nicht genau dem
    Datentyp entspricht (leer, Text, Komma, Ueberlauf, Felder zu viel/zu wenig), ist ValueError: das Reading bleibt
    stehen, es wird kein Wert geraten."""
    if sch[0] == "bc":
        teile = text.split()
        if not teile or not all(HEXBYTE.fullmatch(x) for x in teile):
            raise ValueError(f"kein HEX-Bytefeld: {text[:40]!r}")
        return [int(x, 16) for x in teile]
    felder = text.split(";")
    # read ... wert liefert ein Feld; listen liefert die ganze Message (Slot: typ;wert, Register: wert)
    if len(felder) > (2 if sch[0] == "slot" else 1):
        raise ValueError(f"{len(felder)} Felder: {text[:40]!r}")
    roh = felder[-1].strip()
    lo, hi, ersatz = TYPEN[datentyp(sch)]
    if roh == "-":
        return ersatz
    if not ZAHL.fullmatch(roh):
        raise ValueError(f"keine ganze Zahl: {text[:40]!r}")
    v = int(roh)
    if not lo <= v <= hi:
        raise ValueError(f"{v} ausserhalb {datentyp(sch)} {lo}..{hi}")
    return v


def wert(reading, roh):
    """reading (Katalog-Eintrag), roh: {schluessel: rohwert} -> MQTT-Text oder None (n/v)."""
    q, w = reading["quelle"], reading["wandel"]
    werte = [roh[s] for s in schluessel(q)]
    if q[0] == "bc":
        daten = werte[0]
        if len(daten) <= q[1]:
            return W.NV
        b = daten[q[1]]
        if w[0] == "bool":
            return W.conv_bool(b & q[2])
        return W.zahl(b * w[1], w[2])
    if q[0] == "bcphase":
        daten = werte[0]
        return W.conv_map(daten[1], w[1]) if len(daten) > 1 else W.NV
    art = w[0]
    if art not in ERSATZ_IST_WERT and any(v == ersatzwert(t) for v, t in zip(werte, schluessel(q))):
        return W.NV
    if art == "zahl":
        return W.zahl(werte[0] * w[1], w[2])
    if art == "lowbyte":
        return W.zahl((werte[0] & 0xFF) * w[1], w[2])
    if art == "conv_temp":
        return W.conv_temp(werte[0], w[1], w[2])
    if art == "conv_temp2":
        return W.conv_temp2(werte[0], w[1])
    if art == "conv_calc2":
        return W.conv_calc2(werte[0], w[1], w[2], w[3])
    if art == "map":
        return W.conv_map(werte[0], w[1])
    if art == "date":
        return W.conv_date(*(x & 0xFF for x in werte))
    if art == "time":
        return W.conv_time(*(x & 0xFF for x in werte))
    if art == "zp":
        return W.conv_timeprogram(werte)
    raise ValueError(w)


def roh_kandidaten():
    """Quell-Schluessel, deren Rohwert zusaetzlich unter <prefix>/_roh/ geht (Auswertung der Probe)."""
    out = [("slot", s) for s in K.KANDIDAT_SLOTS]
    out += [("slot", s) for s, v in K.SLOTS.items() if not v[3]]
    out += [("reg", n) for n in K.KANDIDAT_REG]
    out.append(("bc",))
    return out


def roh_name(sch):
    if sch[0] == "slot":
        return f"slot_{sch[1]:02x}"
    if sch[0] == "reg":
        return f"reg_{sch[1]}"
    return "bc_f1fe500a"
