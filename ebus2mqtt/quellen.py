"""Quellen eines Readings (welche ebusd-Messages) und Umrechnung der Rohwerte in den MQTT-Text."""
from . import katalog as K
from . import wandler as W
from .csvgen import reg_name, slot_name


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


def roh_parsen(sch, text):
    """ebusd-Text -> Rohwert: int fuer Slot/Register, Liste von Bytes fuer Broadcasts."""
    if sch[0] == "bc":
        return [int(x, 16) for x in text.split()]
    return int(text.split(";")[-1])


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
