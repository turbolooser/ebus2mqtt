"""ebusd-CSV aus dem Katalog: nur Lese- und Passiv-Messages. Geschrieben wird per ebusd `hex` (schreiben.py),
weil das Pruefbyte der Heizkreis-Schreibtelegramme vom Wert abhaengt.

Feldnamen, die die Bruecke liest: Slot -> "wert", Register -> "wert", Broadcast -> "daten".
"""
from . import katalog as K
from .crc import register_id

KOPF = ("# type,circuit,name,comment,QQ,ZZ,PBSB,ID,field,part,datatype,divider/values,unit,comment\n"
        "# ERZEUGT von tools/gen_csv.py aus ebus2mqtt/katalog.py - nicht von Hand aendern.\n"
        "# Lesen: Kessel 08 (50 03 Slots), WCM-FS 35 (50 22 Register), Broadcasts f1/30.\n"
        "# Schreiben: per ebusd hex aus der Bruecke (schreiben.py), nicht ueber diese Datei.\n")


def slot_name(s):
    return K.SLOTS[s][0] if s in K.SLOTS else f"S{s:02x}"


def reg_name(n):
    return f"R{n}"


def _k(t):
    """Kommentar ohne Kommas (CSV-Trenner)."""
    return t.replace(",", ".")


def zeilen():
    out = []
    alle = dict(K.SLOTS)
    for s in K.KANDIDAT_SLOTS:
        alle.setdefault(s, (f"S{s:02x}", "Kandidat, Bedeutung offen", False, False))
    for s in sorted(alle):
        name, kommentar, vz, _ = alle[s]
        if s < 0x80:
            typ = "SCH" if vz else "UCH"
        else:
            typ = "SIN" if vz else "UIN"
        out.append(f"r,wtc,{name},{_k(kommentar)} (Slot {s:02x}),,08,5003,{s:02x},typ,s,UCH,,,,wert,s,{typ},,,")
    for n in sorted(K.REG):
        out.append(f"r,hk1,{reg_name(n)},{_k(K.REG[n])} (infoNr {n}),,35,5022,{register_id(n)},wert,s,UIN,,,")
    for circ, name, qq, zz, pbsb, laenge in (K.BC_STATUS, K.BC_REGLER):
        out.append(f"u,{circ},{name},Broadcast {qq}->{zz} {pbsb} roh,{qq},{zz},{pbsb},,daten,,HEX:{laenge},,,")
    return out


def text():
    return KOPF + "\n".join(zeilen()) + "\n"
