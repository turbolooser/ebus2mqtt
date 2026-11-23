"""Rohwerte -> MQTT-Text, Zeichen fuer Zeichen wie wcm2mqtt (converters/*.cpp von WcmToMqtt,
https://git.uli-eckhardt.de/WcmToMqtt, GPL-3.0).

wcm2mqtt schreibt Zahlen mit C++-`stringstream`: Genauigkeit 1.0 -> Standardformat (wie `%g`), sonst
`fixed setprecision(1)`. Darum traegt jedes Reading ein `fmt`: "g", "f1" oder "d".
"""
import json
import math
import os

NV = None  # "nicht verfuegbar": kein Publish, Frische laeuft ab

# maps.json von WcmToMqtt (GPL-3.0; genutzte Tabellen, unveraendert kopiert, siehe NOTICE)
KARTEN = {k: {e["code"]: e["text"] for e in v}
          for k, v in json.load(open(os.path.join(os.path.dirname(__file__), "daten", "maps.json"),
                                     encoding="utf-8")).items()}


def zahl(v, fmt):
    if fmt == "d":
        return str(int(round(v)))
    if fmt == "f1":
        return f"{v:.1f}"
    # C++-Standardformat: 6 signifikante Stellen, ohne Nachkommanullen
    s = f"{v:.6g}"
    return "0" if s == "-0" else s


def stepround(v, prec):
    """base_converter::stepround."""
    sgn = (v > 0) - (v < 0)
    r = v + sgn * prec / 2.0
    mod = math.fmod(r, prec)
    sgn_r = (r > 0) - (r < 0)
    return r - sgn_r * mod


def _hl(raw):
    return (raw >> 8) & 0xFF, raw & 0xFF


def _vorzeichen(hi, lo):
    return (hi * 256 + lo) if hi < 128 else -((256 - hi) * 256 - lo)


def conv_temp(raw, div, acc):
    hi, lo = _hl(raw)
    if (lo == 24 and hi == 252) or hi == 128:
        return NV
    v = _vorzeichen(hi, lo) / div
    return zahl(v, "g" if acc == 1.0 else "f1")


def conv_temp2(raw, div):
    """conv_temp2: vorzeichenbehaftet, 0x80xx = n/v, Ausgabe immer im Standardformat (30 -> "3", 25 -> "2.5")."""
    hi, lo = _hl(raw)
    if hi == 128:
        return NV
    return zahl(_vorzeichen(hi, lo) / div, "g")


def conv_calc2(raw, div, mul, acc):
    hi, lo = _hl(raw)
    if (lo == 246 and hi == 255) or hi == 128:
        return NV
    v = (lo + hi * 256) * mul / div
    return zahl(v, "g") if acc == 1 else zahl(stepround(v, acc), "f1")


def conv_map(raw, karte):
    code = raw & 0xFF
    return KARTEN[karte].get(code, f"Code {code}")


def conv_bool(bit):
    return "ON" if bit else "OFF"


def conv_date(tag, monat, jahr):
    if not (1 <= tag <= 31 and 1 <= monat <= 12):
        return NV
    return f"{tag:02d}.{monat:02d}.{2000 + jahr}"


def conv_time(stunde, minute):
    if stunde > 23 or minute > 59:
        return NV
    return f"{stunde:02d}:{minute:02d}"


def _viertel(q):
    return f"{q // 4:02d}:{q % 4 * 15:02d}"


def conv_timeprogram(regs):
    """Drei Register je Tag; je Register lo = Ende, hi = Beginn in Viertelstunden, 0x80 = frei.
    Belegt 23.11.2026: 0x1834 -> 06:00-13:00, 0x3c58 -> 15:00-22:00 (= wcm/ZP1-MO/value)."""
    out = []
    for raw in regs:
        hi, lo = _hl(raw)
        if hi == 0x80 or lo == 0x80:
            continue
        out.append({"from": _viertel(hi), "to": _viertel(lo)})
    return json.dumps(out, separators=(",", ":"))
