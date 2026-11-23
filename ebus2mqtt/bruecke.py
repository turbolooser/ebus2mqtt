"""ebus2mqtt-Bruecke: liest ueber ebusd, publiziert Topics und Discovery wie wcm2mqtt.

Topics je Reading (Prefix wie wcm2mqtt, Vorgabe "wcm"):
  <p>/<name>/value      Text wie wcm2mqtt, retained, bei jedem gueltigen Lesen
  <p>/<name>/fresh      {"ts": epoch, "iv": soll-s}, retained (fuer Waechter je Wert)
  <p>/<name>/available  online|offline aus der Frische (Alter <= FAKTOR x iv), retained
  <p>/<name>/set        Befehl aus HA; Antwort <p>/<name>/set_status (JSON)
  VERFUEGBAR_TOPIC      "query OK" | "offline" (LWT), retained; Vorgabe <p>/status wie wcm2mqtt, im Mischbetrieb
                        eigenes Topic, weil <p>/status dann wcm2mqtt gehoert
  <p>/_roh/<quelle>     Rohwerte der unbelegten Kandidaten (nicht retained), fuer tools/vergleich.py
Dazu STATUS_TOPIC (Vorgabe ebus2mqtt/status): JSON mit Alter, Fehlern, verlorenen Arbitrierungen.
"""
import heapq
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from . import __version__
from . import katalog as K
from . import quellen as Q
from . import schreiben as S
from .ebusd import EbusdFehler

LOG = logging.getLogger("ebus2mqtt")
# find -V: "wtc Status = daten=01 06 ... [ZZ=fe, lastup=2026-11-23 15:04:29, passive read]"
FIND_BC = re.compile(r"daten=([0-9a-f ]+?)\s*\[.*lastup=([0-9-]+ [0-9:]+)")
BC_ABFRAGE_S = 10
FAKTOR = 3
DATEN = os.path.join(os.path.dirname(__file__), "daten")
GERAET = {"identifiers": ["wcm"], "manufacturer": "Weishaupt", "name": "WCM-COM"}


def wcm_komponenten():
    with open(os.path.join(DATEN, "wcm_komponenten.json"), encoding="utf-8") as f:
        return json.load(f)


def discovery(prefix, readings=None, verfuegbar_topic=None, auslassen=()):
    """Single-Device-Bundle wie wcm2mqtt (homeassistant/device/wcm/config), unique_id = Reading-Name.
    auslassen: Readings, die (noch) wcm2mqtt liefert (Mischbetrieb) - Komponente bleibt, Verfuegbarkeit wie bei
    wcm2mqtt ueber <prefix>/status, das dann allein wcm2mqtt schreibt."""
    vorlage = wcm_komponenten()
    verfuegbar_topic = verfuegbar_topic or f"{prefix}/status"
    comps = {}
    for r in (readings or K.R):
        n = r["name"]
        if r["neu"]:
            c = dict(r["ha"])
            schreibbar = False
        else:
            c = {k: v for k, v in vorlage[n].items() if k != "_schreibbar"}
            schreibbar = vorlage[n]["_schreibbar"]
        c.update(name=n, unique_id=n, state_topic=f"{prefix}/{n}/value", expire_after=1200)
        for k, v in K.DISCOVERY_KORREKTUR.get(n, {}).items():
            if v is None:
                c.pop(k, None)
            else:
                c[k] = v
        if n in auslassen:
            c.update(availability_topic=f"{prefix}/status", payload_available="query OK",
                     payload_not_available="offline")
        else:
            c.update(availability_mode="all",
                     availability=[{"topic": verfuegbar_topic, "payload_available": "query OK",
                                    "payload_not_available": "offline"},
                                   {"topic": f"{prefix}/{n}/available", "payload_available": "online",
                                    "payload_not_available": "offline"}])
        if schreibbar:
            c["command_topic"] = f"{prefix}/{n}/set"
        comps[n] = c
    return {"device": GERAET, "origin": {"name": "ebus2mqtt", "sw": __version__}, "components": comps}


def pruefe_set(komp, text):
    """Wert aus HA gegen Optionen/Grenzen der Discovery pruefen. -> (ok, grund)."""
    if "options" in komp:
        return (text in komp["options"], f"nicht in options: {text}")
    try:
        v = float(text)
    except ValueError:
        return (False, f"keine Zahl: {text}")
    if "min" in komp and v < komp["min"]:
        return (False, f"{v} < min {komp['min']}")
    if "max" in komp and v > komp["max"]:
        return (False, f"{v} > max {komp['max']}")
    return (True, "")


class Bruecke:
    def __init__(self, befehl, mqtt, prefix="wcm", status_topic="ebus2mqtt/status", disc_prefix="homeassistant",
                 roh=True, kuma_url="", herzdatei="/tmp/ebus2mqtt.herz", schreiber=None, uhr=time.time,
                 verfuegbar_topic=None, auslassen=(), ungesund_ende_s=600, lesen_pro_runde=None,
                 set_versuche=4, schlaf=None):
        self.befehl, self.mqtt, self.prefix = befehl, mqtt, prefix
        # Docker startet einen unhealthy Container nicht neu: nach so langer Ungesundheit beendet sich die
        # Bruecke selbst (exit 1), restart: unless-stopped startet sie frisch. 0 = nie beenden.
        self.ungesund_ende_s = ungesund_ende_s
        self.ungesund_seit = None
        # Lesen ohne Bursts: faellige Schluessel in eine Warteschlange (kurzer Takt zuerst), je runde() hoechstens
        # lesen_pro_runde davon (None = alle). Sets laufen einzeln (set_lock) und wiederholen Bus-/Verbindungsfehler.
        self.lesen_pro_runde, self.set_versuche = lesen_pro_runde, set_versuche
        self.schlaf = schlaf or (lambda s: time.sleep(s))
        self._schlange, self._in_schlange, self._nr = [], set(), 0
        self.set_lock = threading.Lock()
        self.status_topic, self.disc_prefix, self.roh_an = status_topic, disc_prefix, roh
        self.kuma_url, self.herzdatei, self.uhr = kuma_url, herzdatei, uhr
        # schreiber(reading, text) -> None, wirft bei Fehler; nur fuer Readings in katalog.SCHREIBEN
        self.schreiber = schreiber
        self.verfuegbar_topic = verfuegbar_topic or f"{prefix}/status"
        self.auslassen = set(auslassen)
        unbekannt = self.auslassen - set(K.READINGS)
        if unbekannt:
            raise ValueError(f"AUSLASSEN unbekannt: {sorted(unbekannt)}")
        self.aktiv = [r for r in K.R if r["name"] not in self.auslassen]
        self.roh = {}          # schluessel -> (rohwert, ts)
        self.frisch = {}       # name -> ts letzter gueltiger Wert
        self.letzter = {}      # name -> Text
        self.verfuegbar = {}   # name -> bool (zuletzt publiziert)
        self.fremd = {}        # name -> (Text, ts) der Werte, die wcm2mqtt liefert (nur Anzeige im Web-Frontend)
        self.faellig = {}      # takt -> naechster Zeitpunkt
        self.fehler = {}       # Fehlertext -> Anzahl
        self.lesungen = 0
        self.dauern = []       # letzte Lesedauern (s)
        self.letztes_ok = 0.0
        self.info = {}
        self.start = self.uhr()
        self.lock = threading.Lock()
        self.komps = discovery(prefix, verfuegbar_topic=self.verfuegbar_topic, auslassen=self.auslassen)["components"]
        self._takte = self._takte_bauen()
        self._roh_kand = set(Q.roh_kandidaten())
        self._bc_lastup = None

    # ---------------------------------------------------------------- Plan
    def _takte_bauen(self):
        """takt -> Liste aktiv zu lesender Quell-Schluessel (Broadcast: broadcast())."""
        plan = {}
        for r in self.aktiv:
            for s in Q.schluessel(r["quelle"]):
                if s[0] != "bc" and s not in plan.setdefault(r["takt"], []):
                    plan[r["takt"]].append(s)
        gesehen = {s for v in plan.values() for s in v}
        for s in Q.roh_kandidaten():
            if s[0] != "bc" and s not in gesehen:
                plan.setdefault("kandidat", []).append(s)
        return plan

    def iv(self, r):
        return K.TAKT[r["takt"]]

    # ---------------------------------------------------------------- Eingang
    def roh_setzen(self, sch, wert, ts):
        with self.lock:
            self.roh[sch] = (wert, ts)
        if self.roh_an and sch in self._roh_kand:
            self.mqtt.publish(f"{self.prefix}/_roh/{Q.roh_name(sch)}", json.dumps({"ts": round(ts, 1), "wert": wert}),
                              retain=False)
        self._readings_von(sch, ts)

    def _readings_von(self, sch, ts):
        for r in self.aktiv:
            if sch not in Q.schluessel(r["quelle"]):
                continue
            teile = Q.schluessel(r["quelle"])
            with self.lock:
                if any(t not in self.roh for t in teile):
                    continue
                # alle Teile eines Mehrregister-Werts aus demselben Durchlauf (<= 1 Takt alt)
                if any(ts - self.roh[t][1] > self.iv(r) for t in teile):
                    continue
                roh = {t: self.roh[t][0] for t in teile}
            try:
                text = Q.wert(r, roh)
            except (ValueError, IndexError, KeyError) as e:
                self._fehler(f"Umrechnung {r['name']}: {e}")
                continue
            if text is None:
                continue
            self._publizieren(r, text, ts)

    def _publizieren(self, r, text, ts):
        n = r["name"]
        self.mqtt.publish(f"{self.prefix}/{n}/value", text, retain=True)
        self.mqtt.publish(f"{self.prefix}/{n}/fresh", json.dumps({"ts": int(ts), "iv": self.iv(r)}), retain=True)
        self.frisch[n], self.letzter[n] = ts, text
        if not self.verfuegbar.get(n):
            self.verfuegbar[n] = True
            self.mqtt.publish(f"{self.prefix}/{n}/available", "online", retain=True)

    def listen_zeile(self, circuit, name, werte, ts):
        """Rueckruf des Lauschers: Broadcasts direkt, fremde Abfragen derselben Slots/Register mitnehmen."""
        if (circuit, name) == K.BC_STATUS[:2]:
            sch = ("bc",)
        else:
            sch = self._sch_aus_name(circuit, name)
            if sch is None:
                return
        try:
            self.roh_setzen(sch, Q.roh_parsen(sch, werte), ts)
        except ValueError:
            pass

    def fremd_wert(self, name, text):
        """wcm/<name>/value eines ausgelassenen Readings (von wcm2mqtt) fuer das Web-Frontend merken."""
        if name in self.auslassen:
            self.fremd[name] = (text, self.uhr())

    def _sch_aus_name(self, circuit, name):
        if circuit == "hk1" and name.startswith("R") and name[1:].isdigit():
            return ("reg", int(name[1:]))
        if circuit == "wtc":
            for s in list(K.SLOTS) + K.KANDIDAT_SLOTS:
                if Q.ebusd_adresse(("slot", s))[1] == name:
                    return ("slot", s)
        return None

    # ---------------------------------------------------------------- Lesen
    def _fehler(self, text):
        kurz = text.split(",")[0][:60]
        self.fehler[kurz] = self.fehler.get(kurz, 0) + 1

    def lese(self, sch):
        circ, name, feld = Q.ebusd_adresse(sch)
        try:
            text, dauer = self.befehl.lesen(circ, name, feld)
        except EbusdFehler as e:
            self._fehler(str(e))
            return False
        except OSError as e:
            self._fehler(f"ebusd nicht erreichbar: {e}")
            return False
        self.lesungen += 1
        self.dauern = (self.dauern + [dauer])[-200:]
        self.letztes_ok = self.uhr()
        self.roh_setzen(sch, Q.roh_parsen(sch, text), self.uhr())
        return True

    def eeprom(self):
        """Fachmann1..5 auffrischen; ebusd publiziert sie selbst (ebusd/wtc/FachmannN fuer das HA-Package)."""
        for n in ("Fachmann1", "Fachmann2", "Fachmann3", "Fachmann4", "Fachmann5"):
            try:
                self.befehl.lesen("wtc", n)
            except (EbusdFehler, OSError) as e:
                self._fehler(str(e))

    def broadcast(self):
        """Broadcast f1 fe 50 0a aus dem ebusd-Cache; neu nur, wenn ebusd ein neues Telegramm gesehen hat (lastup).
        `listen` meldet in ebusd 26.1 nur Aenderungen und taugt darum nicht fuer die Frische (Probe 23.11.2026)."""
        circ, name = K.BC_STATUS[:2]
        try:
            zeilen = self.befehl.anfrage(f"find -V -c {circ} {name}")
        except OSError as e:
            self._fehler(f"ebusd nicht erreichbar: {e}")
            return False
        m = FIND_BC.search(" ".join(zeilen))
        if not m or m.group(2) == self._bc_lastup:
            return False
        self._bc_lastup = m.group(2)
        self.roh_setzen(("bc",), Q.roh_parsen(("bc",), m.group(1)), self.uhr())
        return True

    def runde(self):
        """Alle faelligen Takte einmal abarbeiten."""
        jetzt = self.uhr()
        if self.faellig.get("bc", 0) <= jetzt:
            self.faellig["bc"] = jetzt + BC_ABFRAGE_S
            self.broadcast()
        for takt, liste in self._takte.items():
            if self.faellig.get(takt, 0) > jetzt:
                continue
            self.faellig[takt] = jetzt + K.TAKT[takt]
            for sch in liste:
                if sch not in self._in_schlange:
                    self._in_schlange.add(sch)
                    self._nr += 1
                    heapq.heappush(self._schlange, (K.TAKT[takt], self._nr, sch))
        n = len(self._schlange) if self.lesen_pro_runde is None else self.lesen_pro_runde
        for _ in range(min(n, len(self._schlange))):
            sch = heapq.heappop(self._schlange)[2]
            self._in_schlange.discard(sch)
            self.lese(sch)
        if self.faellig.get("eeprom", 0) <= jetzt:
            self.faellig["eeprom"] = jetzt + K.TAKT["eeprom"]
            self.eeprom()

    # ---------------------------------------------------------------- Zustand
    def verfuegbarkeit(self):
        jetzt = self.uhr()
        for r in self.aktiv:
            n = r["name"]
            # noch nie gelesen: dieselbe Frist ab Start (gedrosseltes Lesen braucht nach dem Start etwas)
            ok = jetzt - self.frisch.get(n, self.start) <= FAKTOR * self.iv(r)
            if self.verfuegbar.get(n) != ok:
                self.verfuegbar[n] = ok
                self.mqtt.publish(f"{self.prefix}/{n}/available", "online" if ok else "offline", retain=True)

    def gesund(self):
        return self.info.get("signal") == "acquired" and self.uhr() - self.letztes_ok < 120

    def status(self):
        jetzt = self.uhr()
        alter = {n: round(jetzt - t) for n, t in self.frisch.items()}
        haengend = sorted(r["name"] for r in self.aktiv if not self.verfuegbar.get(r["name"]))
        d = sorted(self.dauern)
        arb = sum(v for k, v in self.fehler.items() if "arbitration" in k.lower())
        return {
            "ts": int(jetzt), "version": __version__, "laufzeit_s": int(jetzt - self.start),
            "gesund": self.gesund(), "ebusd": {k: self.info.get(k) for k in ("signal", "reconnects", "masters",
                                                                              "device", "version")},
            "lesungen": self.lesungen, "fehler": dict(self.fehler), "arbitrierung_verloren": arb,
            "lesedauer_ms": {"median": round(d[len(d) // 2] * 1000) if d else None,
                             "p95": round(d[int(len(d) * 0.95)] * 1000) if d else None},
            "frisch": len(self.aktiv) - len(haengend), "gesamt": len(self.aktiv), "haengend": haengend,
            "ausgelassen": sorted(self.auslassen),
            "aeltester": max(alter.items(), key=lambda x: x[1]) if alter else None,
            "ungesund_s": int(jetzt - self.ungesund_seit) if self.ungesund_seit is not None else 0,
        }

    def herzschlag(self):
        try:
            self.info = self.befehl.info()
        except OSError as e:
            self._fehler(f"ebusd info: {e}")
            self.info = {}
        self.verfuegbarkeit()
        if self.gesund():
            self.ungesund_seit = None
        elif self.ungesund_seit is None:
            self.ungesund_seit = self.uhr()
        st = self.status()
        self.mqtt.publish(self.verfuegbar_topic, "query OK" if st["gesund"] else "offline", retain=True)
        self.mqtt.publish(self.status_topic, json.dumps(st, ensure_ascii=False), retain=True)
        if st["gesund"]:
            try:
                with open(self.herzdatei, "w") as f:
                    f.write(str(int(self.uhr())))
            except OSError:
                pass
        if self.kuma_url:
            self._kuma(st)
        return st

    def aufgeben(self):
        """True, wenn die Bruecke seit ungesund_ende_s ununterbrochen ungesund ist (Hauptschleife beendet dann)."""
        return bool(self.ungesund_ende_s) and self.ungesund_seit is not None \
            and self.uhr() - self.ungesund_seit >= self.ungesund_ende_s

    def _kuma(self, st):
        q = urllib.parse.urlencode({"status": "up" if st["gesund"] else "down",
                                    "msg": f"{st['frisch']}/{st['gesamt']} frisch, signal {st['ebusd']['signal']}",
                                    "ping": st["lesedauer_ms"]["median"] or ""})
        try:
            urllib.request.urlopen(f"{self.kuma_url}{'&' if '?' in self.kuma_url else '?'}{q}", timeout=10).read()
        except OSError as e:
            self._fehler(f"kuma: {e}")

    # ---------------------------------------------------------------- Schreiben
    def set_befehl(self, name, text):
        """Set aus HA: pruefen, schreiben, ruecklesen. Erfolg erst bei passendem Rueckwert."""
        r = K.READINGS.get(name) if name not in self.auslassen else None
        komp = self.komps.get(name)
        if r is None or komp is None or ("command_topic" not in komp and name not in K.SCHREIBEN):
            return self._set_antwort(name, False, "nicht schreibbar")
        if name not in K.SCHREIBEN:
            return self._set_antwort(name, False, "Schreiben gesperrt: kein belegter eBUS-Schreibweg fuer diesen Wert "
                                                   "(WCM-COM schreibt diesen Wert)")
        ok, grund = pruefe_set(komp, text) if K.SCHREIBEN.get(name, ("",))[0] != "zp" else (True, "")
        if not ok:
            return self._set_antwort(name, False, grund)
        if self.schreiber is None:
            return self._set_antwort(name, False, "Schreiben gesperrt: kein Schreiber konfiguriert")
        with self.set_lock:
            return self._schreiben_und_pruefen(name, r, text)

    def _schreiben_und_pruefen(self, name, r, text):
        warte = 2
        for versuch in range(1, self.set_versuche + 1):
            try:
                self.schreiber(r, text)
                break
            except (S.BusFehler, OSError) as e:
                # Luecke am Bus/Adapter (ERR, Socket weg): warten und wiederholen, kein Set geht verloren
                self._fehler(f"set {name}: {e}")
                if versuch == self.set_versuche:
                    return self._set_antwort(name, False, f"Schreiben fehlgeschlagen nach {versuch} Versuchen: {e}")
                LOG.warning("set %s: Versuch %s fehlgeschlagen (%s), neu in %s s", name, versuch, e, warte)
                self.schlaf(warte)
                warte *= 2
            except Exception as e:  # noqa: BLE001 - jeder andere Fehler des Schreibwegs geht als Antwort raus
                return self._set_antwort(name, False, f"Schreiben fehlgeschlagen: {e}")
        soll = S.soll_text(name, text)
        for _ in range(6):
            for sch in Q.schluessel(r["quelle"]):
                self.lese(sch)
            if self.letzter.get(name) is not None and _gleich(self.letzter[name], soll):
                return self._set_antwort(name, True, f"Rueckwert {self.letzter[name]}")
            self.schlaf(5)
        return self._set_antwort(name, False, f"Rueckwert {self.letzter.get(name)} != {soll}")

    def _set_antwort(self, name, ok, grund):
        LOG.info("set %s: %s %s", name, "ok" if ok else "abgelehnt", grund)
        self.mqtt.publish(f"{self.prefix}/{name}/set_status",
                          json.dumps({"ts": int(self.uhr()), "ok": ok, "grund": grund}, ensure_ascii=False),
                          retain=False)
        return ok

    def discovery_senden(self):
        if self.disc_prefix:
            self.mqtt.publish(f"{self.disc_prefix}/device/wcm/config",
                              json.dumps(discovery(self.prefix, verfuegbar_topic=self.verfuegbar_topic,
                                                   auslassen=self.auslassen), ensure_ascii=False), retain=True)


def _gleich(a, b):
    try:
        return abs(float(a) - float(b)) < 1e-6
    except ValueError:
        return a == b
