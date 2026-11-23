"""TCP-Client fuer ebusd (Port 8888, Zeilenprotokoll: Anfrage = eine Zeile, Antwort endet mit Leerzeile).

Zwei Verbindungen: `Befehl` fuer read/info (synchron, eine Anfrage zur Zeit) und `Lauscher` im Modus
`listen`, der jede Aktualisierung als "<circuit> <name> = <werte>" liefert (Broadcasts, fremde Abfragen).
"""
import re
import socket
import threading
import time

ZEILE_LISTEN = re.compile(r"^(\S+) (\S+) = (.*)$")


class EbusdFehler(Exception):
    pass


class Befehl:
    def __init__(self, host, port, timeout=15.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._sock = None
        self._buf = b""
        self._lock = threading.Lock()

    def _verbinden(self):
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._buf = b""

    def schliessen(self):
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def _antwort(self):
        """Liest bis zur Leerzeile; liefert die Zeilen davor."""
        while b"\n\n" not in self._buf:
            teil = self._sock.recv(4096)
            if not teil:
                raise OSError("ebusd hat die Verbindung geschlossen")
            self._buf += teil
        roh, self._buf = self._buf.split(b"\n\n", 1)
        return roh.decode("utf-8", "replace").split("\n")

    def anfrage(self, zeile):
        with self._lock:
            for versuch in (1, 2):
                try:
                    if self._sock is None:
                        self._verbinden()
                    self._sock.sendall(zeile.encode() + b"\n")
                    return self._antwort()
                except OSError:
                    self.schliessen()
                    if versuch == 2:
                        raise

    def lesen(self, circuit, name, feld=None, frisch=True):
        """read [-f] -c circuit name [feld] -> Text. ERR-Antwort -> EbusdFehler(text)."""
        z = f"read {'-f ' if frisch else ''}-c {circuit} {name}" + (f" {feld}" if feld else "")
        t0 = time.monotonic()
        zeilen = self.anfrage(z)
        dauer = time.monotonic() - t0
        text = zeilen[0].strip() if zeilen else ""
        if text.startswith("ERR:") or not text:
            raise EbusdFehler(text or "ERR: leere Antwort")
        return text, dauer

    def info(self):
        """info -> dict der 'schluessel: wert'-Zeilen (signal, reconnects, masters, ...)."""
        out = {}
        for z in self.anfrage("info"):
            if ": " in z:
                k, v = z.split(": ", 1)
                out.setdefault(k.strip(), v.strip())
        return out


class Lauscher(threading.Thread):
    """Haelt eine listen-Verbindung offen und ruft rueckruf(circuit, name, werte, zeitpunkt) je Zeile."""

    def __init__(self, host, port, rueckruf, stop_ereignis):
        super().__init__(daemon=True, name="ebusd-listen")
        self.host, self.port, self.rueckruf, self.stop = host, port, rueckruf, stop_ereignis
        self.verbunden = False
        self.neuverbindungen = 0

    def run(self):
        while not self.stop.is_set():
            try:
                with socket.create_connection((self.host, self.port), timeout=30) as s:
                    s.sendall(b"listen\n")
                    self.verbunden = True
                    buf = b""
                    s.settimeout(120)
                    while not self.stop.is_set():
                        teil = s.recv(4096)
                        if not teil:
                            break
                        buf += teil
                        while b"\n" in buf:
                            zeile, buf = buf.split(b"\n", 1)
                            m = ZEILE_LISTEN.match(zeile.decode("utf-8", "replace").strip())
                            if m:
                                self.rueckruf(m.group(1), m.group(2), m.group(3), time.time())
            except OSError:
                pass
            self.verbunden = False
            self.neuverbindungen += 1
            self.stop.wait(5)
