"""Parallel-Probe: wcm2mqtt (wcm/) gegen ebus2mqtt (Probe-Prefix) mitschneiden und auswerten.

  vergleich.py aufzeichnen <datei.jsonl> --sekunden 86400 [--probe ebustest] [--status ebus2mqtt-test/status]
      schneidet per mosquitto_sub mit (MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASSWORD aus der Umgebung)
  vergleich.py auswerten <datei.jsonl> <ausgabe.md> [--probe ebustest]
      Gleichheit je Reading (Stichprobe alle 60 s), Frische (Abstand der Updates), Latenz (Wertwechsel
      WCM -> eBUS), und fuer die unbelegten Readings die Rohkandidaten mit der besten Uebereinstimmung.
"""
import argparse
import bisect
import json
import os
import statistics
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ebus2mqtt import katalog as K  # noqa: E402

UNBELEGT = [r["name"] for r in K.R if not r["belegt"] and not r["neu"]]


# ---------------------------------------------------------------- Aufzeichnen
def aufzeichnen(datei, sekunden, probe, status):
    cmd = ["mosquitto_sub", "-h", os.environ["MQTT_HOST"], "-p", os.environ.get("MQTT_PORT", "1883"),
           "-u", os.environ["MQTT_USER"], "-P", os.environ["MQTT_PASSWORD"], "-F", "%U\t%t\t%p", "-t", "wcm/+/value", "-t", f"{probe}/+/value", "-t", f"{probe}/_roh/#", "-t", f"{probe}/+/available",
           "-t", f"{probe}/status", "-t", status]
    ende = time.time() + sekunden
    with open(datei, "a", encoding="utf-8") as out:
        while time.time() < ende:
            rest = str(max(1, int(ende - time.time())))
            p = subprocess.Popen(cmd + ["-W", rest], stdout=subprocess.PIPE, text=True, errors="replace")
            for zeile in p.stdout:
                teile = zeile.rstrip("\n").split("\t", 2)
                if len(teile) == 3:
                    out.write(json.dumps({"ts": float(teile[0]), "t": teile[1], "p": teile[2]}) + "\n")
                    out.flush()
                if time.time() >= ende:
                    p.terminate()
                    break
            p.wait()
            time.sleep(5)  # Broker kurz weg (HA-Neustart) -> neu verbinden


# ---------------------------------------------------------------- Auswerten
def laden(datei):
    reihen = {}
    with open(datei, encoding="utf-8") as f:
        for z in f:
            try:
                e = json.loads(z)
            except ValueError:
                continue
            reihen.setdefault(e["t"], []).append((e["ts"], e["p"]))
    for v in reihen.values():
        v.sort()
    return reihen


class Reihe:
    """Zeitreihe [(ts, wert)] mit vorberechneten Zeitstempeln fuer bisect."""

    def __init__(self, paare):
        self.paare = paare
        self.ts = [x[0] for x in paare]


def wert_bei(reihe, t, max_alter):
    if not isinstance(reihe, Reihe):
        reihe = Reihe(reihe)
    if not reihe.paare:
        return None
    i = bisect.bisect_right(reihe.ts, t) - 1
    if i < 0 or t - reihe.ts[i] > max_alter:
        return None
    return reihe.paare[i][1]


def zahl(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def gleich(a, b, toleranz):
    if a == b:
        return True
    fa, fb = zahl(a), zahl(b)
    return fa is not None and fb is not None and abs(fa - fb) <= toleranz


def abstaende(reihe):
    ts = [x[0] for x in reihe]
    return [b - a for a, b in zip(ts, ts[1:])]


def latenzen(wcm, ebus):
    """Fuer jeden Wertwechsel im WCM: wann zeigte eBUS denselben neuen Wert (+-10 min)? s, positiv = eBUS spaeter."""
    out, offen = [], 0
    for (t0, a), (t1, b) in zip(wcm, wcm[1:]):
        if a == b:
            continue
        kand = [t for t, v in ebus if v == b and abs(t - t1) <= 600]
        if kand:
            # der eBUS-Wechsel, der dem WCM-Wechsel am naechsten liegt
            out.append(min(kand, key=lambda t: abs(t - t1)) - t1)
        else:
            offen += 1
    return out, offen


def roh_reihen(reihen, probe):
    """_roh-Topics -> {kandidat: [(ts, wert)]}; Broadcast in Byte- und Bit-Kandidaten zerlegt."""
    out = {}
    for t, rs in reihen.items():
        if not t.startswith(f"{probe}/_roh/"):
            continue
        q = t.rsplit("/", 1)[1]
        for ts, p in rs:
            try:
                w = json.loads(p)["wert"]
            except (ValueError, KeyError):
                continue
            if isinstance(w, list):
                for i, b in enumerate(w):
                    out.setdefault(f"{q}[{i}]", []).append((ts, str(b)))
                    for bit in range(8):
                        out.setdefault(f"{q}[{i}]&{1 << bit:#04x}", []).append(
                            (ts, "ON" if b & (1 << bit) else "OFF"))
            else:
                out.setdefault(q, []).append((ts, str(w)))
    return out


def kandidaten_bewerten(ziel, roh, start, ende):
    """Uebereinstimmung je Kandidat (beste Verschiebung -180..+180 s). -> [(anteil, kandidat, lag, n, wechsel)]."""
    ergebnis = []
    wechsel_ziel = sum(1 for a, b in zip(ziel, ziel[1:]) if a[1] != b[1])
    ziel = Reihe(ziel)
    for k, paare in roh.items():
        reihe = Reihe(paare)
        best = None
        for lag in range(-180, 181, 30):
            n = treffer = 0
            t = start
            while t < ende:
                a = wert_bei(ziel, t, 900)
                b = wert_bei(reihe, t + lag, 900)
                if a is not None and b is not None:
                    n += 1
                    treffer += gleich(a, b, 0.0)
                t += 60
            if n and (best is None or treffer / n > best[0]):
                best = (treffer / n, k, lag, n)
        if best:
            ergebnis.append(best + (wechsel_ziel,))
    ergebnis.sort(key=lambda x: (-x[0], abs(x[2])))
    return ergebnis[:3]


def auswerten(datei, ausgabe, probe):
    reihen = laden(datei)
    alle_ts = [x[0] for v in reihen.values() for x in v]
    if not alle_ts:
        sys.exit("keine Daten")
    start, ende = min(alle_ts), max(alle_ts)
    zeilen, daten = [], {"start": start, "ende": ende, "readings": {}, "kandidaten": {}}
    zeilen.append(f"# Parallel-Probe wcm2mqtt gegen ebus2mqtt\n\nFenster: {time.strftime('%d.%m. %H:%M', time.localtime(start))}"
                  f" bis {time.strftime('%d.%m. %H:%M', time.localtime(ende))} ({(ende - start) / 3600:.1f} h)\n")
    zeilen.append("| Reading | gleich | ±Toleranz | WCM Updates / max. Luecke | eBUS Updates / max. Luecke "
                  "| Latenz Median (n) | belegt |\n|---|---|---|---|---|---|---|")
    for r in K.R:
        if r["neu"]:
            continue
        n_ = r["name"]
        wcm, ebus = reihen.get(f"wcm/{n_}/value", []), reihen.get(f"{probe}/{n_}/value", [])
        rw, re_ = Reihe(wcm), Reihe(ebus)
        iv = K.TAKT[r["takt"]]
        n = g = tol = 0
        t = start
        while t < ende:
            a, b = wert_bei(rw, t, 1200), wert_bei(re_, t, 3 * iv)
            if a is not None and b is not None:
                n += 1
                g += a == b
                tol += gleich(a, b, 1.0)
            t += 60
        lw, le = abstaende(wcm), abstaende(ebus)
        lat, offen = latenzen(wcm, ebus)
        d = {"n": n, "gleich": g / n if n else None, "toleranz": tol / n if n else None,
             "wcm_updates": len(wcm), "ebus_updates": len(ebus), "wcm_max_luecke": max(lw) if lw else None,
             "ebus_max_luecke": max(le) if le else None, "latenz_median": statistics.median(lat) if lat else None,
             "latenz_n": len(lat), "latenz_offen": offen}
        daten["readings"][n_] = d

        def pz(x):
            return "–" if x is None else f"{100 * x:.0f} %"

        def s(x):
            return "–" if x is None else f"{x:.0f} s"
        zeilen.append(f"| {n_} | {pz(d['gleich'])} | {pz(d['toleranz'])} | {len(wcm)} / {s(d['wcm_max_luecke'])} | "
                      f"{len(ebus)} / {s(d['ebus_max_luecke'])} | {s(d['latenz_median'])} ({len(lat)}, offen {offen}) | "
                      f"{'ja' if r['belegt'] else 'Kandidat'} |")
    roh = roh_reihen(reihen, probe)
    zeilen.append("\n## Unbelegte Readings: beste Rohkandidaten\n")
    zeilen.append("| Reading | Wechsel im WCM | Kandidat 1 | Kandidat 2 | Kandidat 3 |\n|---|---|---|---|---|")
    for n_ in UNBELEGT:
        ziel = reihen.get(f"wcm/{n_}/value", [])
        best = kandidaten_bewerten(ziel, roh, start, ende) if ziel else []
        daten["kandidaten"][n_] = best
        zellen = [f"{k} {100 * a:.0f} % (lag {lag:+d} s, n {n})" for a, k, lag, n, _ in best]
        w = best[0][4] if best else 0
        zeilen.append(f"| {n_} | {w} | " + " | ".join(zellen + ["–"] * (3 - len(zellen))) + " |")
    with open(ausgabe, "w", encoding="utf-8") as f:
        f.write("\n".join(zeilen) + "\n")
    with open(os.path.splitext(ausgabe)[0] + ".json", "w", encoding="utf-8") as f:
        json.dump(daten, f, ensure_ascii=False, indent=1)
    return daten


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("aufzeichnen")
    a.add_argument("datei")
    a.add_argument("--sekunden", type=int, default=86400)
    a.add_argument("--probe", default="ebustest")
    a.add_argument("--status", default="ebus2mqtt-test/status")
    b = sub.add_parser("auswerten")
    b.add_argument("datei")
    b.add_argument("ausgabe")
    b.add_argument("--probe", default="ebustest")
    x = ap.parse_args()
    if x.cmd == "aufzeichnen":
        aufzeichnen(x.datei, x.sekunden, x.probe, x.status)
    else:
        auswerten(x.datei, x.ausgabe, x.probe)


if __name__ == "__main__":
    main()
