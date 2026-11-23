"""Pruefsummen am eBUS der WTC-25-A.

Beide folgen ebusd (`Symbol::updateCrc`): crc = T[crc] ^ wert, T = Multiplikation mit x^8 modulo Polynom.
- 0x9B: die genormte eBUS-Telegramm-CRC.
- 0x5C: das Pruefbyte, das Kromschroeder/Weishaupt vor Register- und Speicheradressen erwartet
  (aghulas/weishaupt-ebus evidence/register-crc.md; nachgerechnet an allen IDs der WCM-Mitschnitte 23.11.2026).
"""


def _crc(data, poly):
    c = 0
    for b in data:
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xFF if c & 0x80 else (c << 1) & 0xFF
        c ^= b
    return c


def ebus_crc(data):
    return _crc(data, 0x9B)


def register_crc(data):
    return _crc(data, 0x5C)


def register_id(info_nr):
    """ID-Bytes einer 50-22-Leseanfrage: Pruefbyte, infoNr LE (z. B. 5 -> '700500')."""
    lo, hi = info_nr & 0xFF, info_nr >> 8
    return f"{register_crc([lo, hi]):02x}{lo:02x}{hi:02x}"
