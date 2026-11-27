"""Schreibtelegramme fuer die Sets aus HA. Gesendet wird per ebusd `hex` (ebusd braucht --enablehex);
Quelle ist die Master-Adresse von ebusd (EBUSD_ADDRESS). Erfolg prueft die Bruecke am Rueckwert.

- Kessel-Parameter: `03 50 04 02 <slot> <wert>` an Master 03 (= Kessel 08), Master-Master, ohne CRC.
  Belegt 23.11.2026: WCM-Set "ff 03 50 04 02 1e 28"; von Quelle 31 angenommen fuer P30/P31/P42.
- Heizkreis (WCM-FS 35): `35 50 23 05 <crc> <adr lo> <adr hi> <wert lo> <wert hi>`, CRC-8 Polynom 0x5C ueber
  Adresse und Wert (aghulas/weishaupt-ebus evidence/register-write-crc.md). 35 quittiert auch von Quelle 31 mit 00,
  uebernimmt aber nur von ff (Test 23.11.2026 17:40: 413 -> 20,0 von 31 nicht uebernommen).
"""
import json
import math

from . import katalog as K
from . import wandler as W
from .crc import register_crc


class SchreibFehler(Exception):
    pass


class BusFehler(SchreibFehler):
    """ebusd hat das Telegramm nicht durchbekommen (ERR-Antwort): voruebergehend, die Bruecke wiederholt."""


def _zahl(text):
    try:
        v = float(text)
    except ValueError:
        raise SchreibFehler(f"keine Zahl: {text}")
    if not math.isfinite(v):
        raise SchreibFehler(f"keine endliche Zahl: {text}")
    return v


def _code(karte, text):
    for code, t in W.KARTEN[karte].items():
        if t == text:
            return code
    raise SchreibFehler(f"unbekannt in {karte}: {text}")


def kessel(slot, wert):
    return f"035004 02{slot:02x}{int(round(wert)) & 0xFF:02x}".replace(" ", "")


def register(info_nr, raw):
    adr = [info_nr & 0xFF, info_nr >> 8]
    val = [raw & 0xFF, (raw >> 8) & 0xFF]
    return "35502305" + bytes([register_crc(adr + val)] + adr + val).hex()


def _viertel(t):
    try:
        h, m = (int(x) for x in t.split(":"))
    except (AttributeError, ValueError):
        raise SchreibFehler(f"keine Uhrzeit HH:MM: {t!r}")
    if not (0 <= h <= 24 and m in (0, 15, 30, 45)) or h * 4 + m // 15 > 96:
        raise SchreibFehler(f"Uhrzeit nicht im Viertelstundenraster: {t}")
    return h * 4 + m // 15


def zeitprogramm(text):
    """JSON [{"from":"06:00","to":"13:00"}, ...] (hoechstens 3) -> 3 Registerwerte (hi = Beginn, lo = Ende)."""
    try:
        fenster = json.loads(text)
    except ValueError:
        raise SchreibFehler("kein JSON")
    if not isinstance(fenster, list) or len(fenster) > 3:
        raise SchreibFehler("hoechstens 3 Fenster")
    regs = []
    for f in fenster:
        if not isinstance(f, dict) or "from" not in f or "to" not in f:
            raise SchreibFehler(f"Fenster ohne from/to: {f!r}")
        a, e = _viertel(f["from"]), _viertel(f["to"])
        if a >= e:
            raise SchreibFehler(f"Fenster {f['from']}-{f['to']} leer oder verkehrt")
        regs.append((a << 8) | e)
    return regs + [0x8080] * (3 - len(regs))


def telegramme(name, text):
    """Reading-Name + Text aus HA -> Liste von Hex-Telegrammen (ohne Quelle)."""
    if name not in K.SCHREIBEN:
        raise SchreibFehler("kein Schreibweg")
    art, *p = K.SCHREIBEN[name]
    if art == "kessel":
        slot, lo, hi = p
        v = _zahl(text)
        if not lo <= v <= hi:
            raise SchreibFehler(f"{v} ausserhalb {lo}..{hi}")
        return [kessel(slot, v)]
    if art == "hk":
        info_nr, mul, lo, hi = p
        v = _zahl(text)
        if not lo <= v <= hi:
            raise SchreibFehler(f"{v} ausserhalb {lo}..{hi}")
        return [register(info_nr, int(round(v * mul)) & 0xFFFF)]
    if art == "hkmap":
        info_nr, karte = p
        return [register(info_nr, _code(karte, text))]
    if art == "zp":
        basis = K.READINGS[name]["quelle"][1][0]
        return [register(basis + i, raw) for i, raw in enumerate(zeitprogramm(text))]
    raise SchreibFehler(f"Art {art}")


def beschreibung(name):
    art = K.SCHREIBEN[name][0]
    return "eBUS 50 04 an 03" if art == "kessel" else "eBUS 50 23 an 35 (nur von Quelle ff)"


def soll_text(name, text):
    """Vergleichswert fuer das Ruecklesen."""
    if K.SCHREIBEN[name][0] == "zp":
        return json.dumps(json.loads(text), separators=(",", ":"))
    return text


def ebusd_schreiber(befehl):
    def schreiben(r, text):
        for tel in telegramme(r["name"], text):
            antwort = befehl.anfrage(f"hex {tel}")
            erste = antwort[0].strip() if antwort else ""
            if not erste or erste.startswith("ERR"):
                raise BusFehler(f"{tel}: {erste or 'leere Antwort'}")
    return schreiben
