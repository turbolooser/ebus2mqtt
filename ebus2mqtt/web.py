"""Web-Frontend, nur lesen: GET / (Tabelle aller Werte, Auto-Refresh) und GET /api/werte (JSON).

Keine Set-Knoepfe, keine Schreibwege: der Server kennt nur GET und liest den Zustand der Bruecke.
Werte, die im Mischbetrieb noch wcm2mqtt liefert (AUSLASSEN), zeigt die Seite mit Quelle "WCM-COM".
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from . import katalog as K
from . import schreiben as S


def quelle_text(r):
    q = r["quelle"]
    if q[0] == "slot":
        return f"eBUS Kessel 08 · Slot {q[1]:02x} (50 03)"
    if q[0] == "reg":
        return f"eBUS WCM-FS 35 · infoNr {q[1]} (50 22)"
    if q[0] == "regs":
        return f"eBUS WCM-FS 35 · infoNr {q[1][0]}–{q[1][-1]} (50 22)"
    if q[0] == "bc":
        maske = f" & 0x{q[2]:02x}" if q[2] is not None else ""
        return f"eBUS Broadcast f1→fe 50 0a · Byte {q[1]}{maske}"
    if q[0] == "bcphase":
        return "eBUS Broadcast f1→fe 50 0a · Byte 1"
    return str(q)


def werte(bruecke):
    """Liste aller Readings mit Wert, Einheit, Alter und Quelle."""
    jetzt = bruecke.uhr()
    out = []
    for r in K.R:
        n = r["name"]
        bez, gruppe = K.BEZEICHNUNG.get(n, (n, "Sonstige"))
        komp = bruecke.komps.get(n, {})
        einheit = komp.get("unit_of_measurement", "") if n in K.DISCOVERY_KORREKTUR else (
            komp.get("unit_of_measurement") or K.EINHEIT.get(n, ""))
        iv = K.TAKT[r["takt"]]
        if n in bruecke.auslassen:
            wert, ts = bruecke.fremd.get(n, (None, None))
            quelle = "WCM-COM (wcm2mqtt), eBUS-Zuordnung offen"
        else:
            wert, ts = bruecke.letzter.get(n), bruecke.frisch.get(n)
            quelle = quelle_text(r)
        alter = None if ts is None else round(jetzt - ts)
        if n in K.SCHREIBEN and n not in bruecke.auslassen:
            schreiben = S.beschreibung(n)
        elif "command_topic" in komp:
            schreiben = "über WCM-COM"
        else:
            schreiben = ""
        doku = K.DOKU.get(n, {})
        out.append({"name": n, "bezeichnung": bez, "doku_url": doku.get("url"),
                    "doku": doku.get("quelle") or doku.get("grund", ""), "gruppe": gruppe, "wert": wert, "einheit": einheit,
                    "alter_s": alter, "soll_s": iv, "frisch": alter is not None and alter <= 3 * iv,
                    "quelle": quelle, "schreiben": schreiben, "neu": r["neu"], "belegt": r["belegt"]})
    return out


def api(bruecke):
    st = bruecke.status()
    return {"ts": st["ts"], "version": __version__, "gesund": st["gesund"], "ebusd": st["ebusd"],
            "lesungen": st["lesungen"], "fehler": st["fehler"], "arbitrierung_verloren": st["arbitrierung_verloren"],
            "lesedauer_ms": st["lesedauer_ms"], "werte": werte(bruecke)}


SEITE = """<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>eBUS-Werte</title>
<style>
:root{--bg:#f7f7f5;--fg:#1d1d1b;--mut:#6b6b66;--rand:#dcdcd6;--ok:#1d7a3a;--alt:#b25b00;--kopf:#ecece6}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecece8;--mut:#9a9a94;--rand:#33332f;--ok:#5fc27e;
--alt:#f0a050;--kopf:#22221f}}
body{background:var(--bg);color:var(--fg);font:14px/1.4 system-ui,sans-serif;margin:0 16px 32px}
h1{font-size:20px;margin:16px 0 4px}#kopf{color:var(--mut);margin-bottom:12px}
table{border-collapse:collapse;width:100%;max-width:1200px}th,td{text-align:left;padding:4px 8px;
border-bottom:1px solid var(--rand);vertical-align:top}th{position:sticky;top:0;background:var(--kopf)}
td.w{font-variant-numeric:tabular-nums;font-weight:600;white-space:nowrap}td.q,td.s{color:var(--mut);font-size:12px}
tr.g td{background:var(--kopf);font-weight:600;padding-top:10px}.ok{color:var(--ok)}.alt{color:var(--alt)}
.tabelle{overflow-x:auto}a{color:inherit}
</style></head><body>
<h1>eBUS-Werte · Weishaupt WTC-25-A</h1><div id="kopf">lade …</div>
<div class="tabelle"><table><thead><tr><th>Bezeichnung</th><th>Wert</th><th>Alter</th><th>Quelle</th>
<th>Name (Topic) · Doku</th></tr></thead><tbody id="t"></tbody></table></div>
<script>
function e(s){return String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]))}
function alter(s){if(s==null)return"–";if(s<120)return s+" s";if(s<7200)return Math.round(s/60)+" min";
return Math.round(s/3600)+" h"}
async function laden(){
 try{const d=await (await fetch("api/werte",{cache:"no-store"})).json();
  const frisch=d.werte.filter(w=>w.frisch).length;
  document.getElementById("kopf").innerHTML=`<span class="${d.gesund?"ok":"alt"}">${d.gesund?"gesund":"NICHT gesund"}</span>
   · ebusd ${e(d.ebusd.signal)} · ${frisch}/${d.werte.length} frisch · ${d.lesungen} Lesungen ·
   Fehler ${Object.values(d.fehler).reduce((a,b)=>a+b,0)} · Lesedauer ${e(d.lesedauer_ms.median)} ms ·
   ebus2mqtt ${e(d.version)} · ${new Date(d.ts*1000).toLocaleTimeString("de-DE")} · nur lesen`;
  let h="",g="";
  for(const w of d.werte){
   if(w.gruppe!==g){g=w.gruppe;h+=`<tr class="g"><td colspan="5">${e(g)}</td></tr>`}
   h+=`<tr><td>${e(w.bezeichnung)}</td><td class="w">${e(w.wert==null?"–":w.wert)} ${e(w.einheit)}</td>
   <td class="${w.frisch?"ok":"alt"}">${alter(w.alter_s)}</td><td class="q">${e(w.quelle)}${w.schreiben?
   " · schreibbar "+e(w.schreiben):""}</td><td class="s">${w.doku_url?`<a href="${e(w.doku_url)}" target="_blank" rel="noopener" title="${e(w.doku)}">${e(w.name)}</a>`:`<span title="${e(w.doku)}">${e(w.name)}</span>`}</td></tr>`}
  document.getElementById("t").innerHTML=h;
 }catch(x){document.getElementById("kopf").textContent="Fehler beim Laden: "+x}}
laden();setInterval(laden,10000);
</script></body></html>
"""

GRUPPEN = ["Brenner", "Kessel", "Heizkreis", "Zeit", "Zeitprogramme", "Zähler", "Display P10–P72", "Sonstige"]


def sortiert(liste):
    return sorted(liste, key=lambda w: (GRUPPEN.index(w["gruppe"]) if w["gruppe"] in GRUPPEN else 99,
                                        w["bezeichnung"]))


def starten(bruecke, port, host="0.0.0.0"):
    class Handler(BaseHTTPRequestHandler):
        def _senden(self, code, typ, daten):
            self.send_response(code)
            self.send_header("Content-Type", typ)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(daten)))
            self.end_headers()
            self.wfile.write(daten)

        def do_GET(self):  # noqa: N802 - http.server-Schnittstelle
            pfad = self.path.split("?", 1)[0]
            if pfad == "/api/werte":
                d = api(bruecke)
                d["werte"] = sortiert(d["werte"])
                self._senden(200, "application/json; charset=utf-8",
                             json.dumps(d, ensure_ascii=False).encode("utf-8"))
            elif pfad in ("/", "/index.html"):
                self._senden(200, "text/html; charset=utf-8", SEITE.encode("utf-8"))
            elif pfad == "/status":
                self._senden(200 if bruecke.gesund() else 503, "text/plain; charset=utf-8",
                             b"ok" if bruecke.gesund() else b"nicht gesund")
            else:
                self._senden(404, "text/plain; charset=utf-8", b"nicht gefunden")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True, name="web").start()
    return server
