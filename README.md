# ebus2mqtt

> **Dokumentation auf Deutsch und Englisch / Documentation in German and English**
> → [Deutsch](#deutsch) · [English](#english)

---

<a id="deutsch"></a>

# Deutsch

eBUS → MQTT / Home-Assistant-Brücke für **Weishaupt-Gas-Brennwertthermen WTC 15-A / 25-A** mit dem
Heizkreisregler **WCM-FS**. Sie liest Kessel und Heizkreis direkt am eBUS (über einen eBUS-Adapter und
[ebusd](https://github.com/john30/ebusd)) und veröffentlicht dieselben Topics, unique IDs und dieselbe
Home-Assistant-Discovery wie [WcmToMqtt](https://git.uli-eckhardt.de/WcmToMqtt). Damit ersetzt sie ein
WCM-COM-Gateway, ohne dass sich Ihre Home-Assistant-Entitäten ändern.

> **Kein Produkt von Weishaupt.** Produktnamen dienen nur zur Beschreibung der Kompatibilität. Nutzung auf eigenes
> Risiko: Schreiben in ein Heizgerät kann es beschädigen oder unsicher machen. Lesen Sie [Schreiben](#de-schreiben),
> bevor Sie es einschalten.

## Inhalt

[Was und warum](#de-was) · [Hardware und Verkabelung](#de-hardware) · [Adressen und WCM-COM-Ersatz](#de-adressen) ·
[Schnellstart](#de-schnellstart) · [Variablen](#de-variablen) · [Werte und Quellen](#de-werte) ·
[Abfrageplan](#de-abfrage) · [Schreiben](#de-schreiben) · [MQTT-Topics](#de-topics) · [Web-Seite](#de-web) ·
[Gesundheit und Überwachung](#de-gesundheit) · [Fehlersuche](#de-fehlersuche) · [Entwicklung](#de-entwicklung) ·
[Dank und Lizenz](#de-lizenz)

<a id="de-was"></a>
## Was und warum

Das WCM-COM ist ein Netzwerk-Gateway, das am eBUS der Therme hängt und Werte über HTTP anbietet; WcmToMqtt fragt es
ab und macht daraus MQTT. Das WCM-COM antwortet langsam, bedient nur einen Client zur Zeit und ist eine zusätzliche
Fehlerquelle. ebus2mqtt spricht stattdessen selbst mit dem Bus:

- **58 Werte kompatibel zu WcmToMqtt** (Brennerphase, Flamme, Gasventil, Pumpe, Vorlauf-, Abgas- und
  Außentemperaturen, Laststellung, Heizkreis-Einstellungen, Zeitprogramme …) und **23 zusätzliche Nur-Lese-Werte**
  (Fachmann-Parameter P10–P72 einschließlich Pumpenleistung P42/P43, richtig skalierte Brennerzähler).
- **Frische je Wert** (`<prefix>/<name>/fresh`, `…/available`), ein JSON-Status-Topic, optional Uptime-Kuma-Push.
- Eine kleine **Web-Seite** (nur lesen) mit jedem Wert, Einheit, Alter, eBUS-Quelle und Link in die Dokumentation.
- **Schreiben mit Rücklesen**: Ein Set gilt erst als erfolgreich, wenn das Gerät den neuen Wert zurückmeldet.
- **Gleichmäßige Buslast** und **Sets ohne Verlust** bei kurzen Verbindungslücken.

<a id="de-hardware"></a>
## Hardware und Verkabelung

- **eBUS-Adapter** mit dem TCP-Protokoll „enhanced“, z. B. der *eBUS Adapter Shield v5*, in ebusd angesprochen als
  `ens:<ip>:9999`. Der Adapter wird mit seinen zwei eBUS-Klemmen an die eBUS-Leitung der Anlage angeschlossen,
  dort, wo auch WCM-FS bzw. WCM-COM angeschlossen sind; die Klemmenbezeichnung steht in der Installationsanleitung
  Ihrer Therme bzw. des Reglers.
- Getestet an einer Weishaupt **WTC 25-A** (Feuerungsautomat *Kromschröder W 0315 / 0301*) mit Heizkreisregler
  **WCM-FS**, November 2026. Andere WTC-Modelle können andere Slots verwenden: erst lesen, dann schreiben.
- Am Adapter darf **genau ein** ebusd hängen. Ein zweiter Client (ein zweiter ebusd, ein Testcontainer) trennt den
  ersten.
- Ein Docker-Host im selben Netz wie Adapter und MQTT-Broker.

<a id="de-adressen"></a>
## Adressen und WCM-COM-Ersatz

| Teilnehmer | Master | Slave | Bemerkung |
|---|---|---|---|
| Kessel (Feuerungsautomat) | `03` | `08` | Display-Slots `08 50 03 01 <slot>`, Broadcast `f1 fe 50 0a` |
| Heizkreisregler WCM-FS | – | `35` | Register `35 50 22 03 …`, Schreiben `35 50 23 05 …` |
| WCM-COM | `ff` | `04` | wird durch ebus2mqtt ersetzt |
| ebusd (diese Brücke) | `31` oder `ff` | `36` bzw. `04` | Einstellung `EBUS_ADRESSE` |

**Zwei Betriebsarten:**

1. **WCM-COM bleibt am Bus** (`EBUS_ADRESSE=31`, Vorgabe): ebus2mqtt liest alles, schreibt aber nur Kessel-Parameter
   (P30/P31/P42/P43). Der WCM-FS quittiert Schreibtelegramme von `31`, übernimmt sie aber nicht.
2. **WCM-COM ersetzt** (`EBUS_ADRESSE=ff`): Erst das WCM-COM **vom eBUS trennen** (Strom darf bleiben), dann
   `EBUS_ADRESSE=ff` setzen und den Stack neu starten. Jetzt nimmt der WCM-FS auch Heizkreis-Werte an.

> **Nie `ff` setzen, solange das WCM-COM am Bus hängt.** Zwei Master mit derselben Adresse kollidieren, Telegramme
> gehen verloren oder werden falsch zugeordnet. Prüfen, ob das WCM-COM wirklich weg ist: `ebusctl hex 04070400` muss
> mit `read timeout` antworten (`scan 04` liefert nur den Cache).

Mischbetrieb (Übergang): Mit `AUSLASSEN` lässt ebus2mqtt einzelne Werte aus, die WcmToMqtt noch liefert; dann bekommt
ebus2mqtt mit `VERFUEGBAR_TOPIC` ein eigenes Verfügbarkeits-Topic, weil `<prefix>/status` noch WcmToMqtt gehört.

<a id="de-schnellstart"></a>
## Schnellstart (Docker)

```sh
cp .env.example .env                 # EBUS_DEVICE, MQTT_HOST, MQTT_USER, MQTT_PASSWORD eintragen
docker compose -f docker-compose.example.yml up -d
# Web-Seite: http://<docker-host>:8097/
```

Images (von der CI gebaut, Tag `sha-<commit>`): `ghcr.io/turbolooser/ebus2mqtt-ebusd` (offizielles
`john30/ebusd` v26.1 plus die CSV aus `ebusd/csv/`) und `ghcr.io/turbolooser/ebus2mqtt-bridge`. Im Betrieb ein
festes Tag, besser einen Digest pinnen statt `main`.

Abnahme nach dem Start: Web-Seite zeigt alle Werte frisch, `ebus2mqtt/status` meldet `"gesund": true` und
`frisch` = `gesamt`, in Home Assistant sind die Entitäten des Geräts *WCM-COM* verfügbar.

<a id="de-variablen"></a>
## Variablen (Umgebung)

**Brücke**

| Variable | Vorgabe | Bedeutung |
|---|---|---|
| `EBUSD_HOST`, `EBUSD_PORT` | `ebusd`, `8888` | ebusd im selben Compose-Netz |
| `EBUS_ADRESSE` | `31` | Master-Adresse von ebusd; `ff` nur nach Trennen des WCM-COM (siehe oben) |
| `MQTT_HOST`, `MQTT_PORT` | –, `1883` | Broker |
| `MQTT_USER`, `MQTT_PASSWORD` | – | Broker-Konto (Geheimnis, nie ins Git) |
| `MQTT_CLIENT_ID` | `ebus2mqtt` | Client-ID am Broker |
| `MQTT_PREFIX` | `wcm` | Topic-Präfix (wie WcmToMqtt) |
| `HA_DISCOVERY_PREFIX` | `homeassistant` | Discovery-Präfix; leer = keine Discovery (Parallelbetrieb zum Testen) |
| `VERFUEGBAR_TOPIC` | `<prefix>/status` | Verfügbarkeits-Topic der Brücke |
| `AUSLASSEN` | – | Kommaliste der Werte, die eine andere Brücke noch liefert (Mischbetrieb) |
| `STATUS_TOPIC` | `ebus2mqtt/status` | JSON-Status (siehe [Gesundheit](#de-gesundheit)) |
| `SET_AKTIV` | `1` | `0` = keine Set-Topics abonnieren |
| `ROH` | `1` | Rohwerte unbelegter Kandidaten unter `<prefix>/_roh/` veröffentlichen |
| `LESEN_PRO_S` | `2` | höchstens so viele Bus-Lesungen pro Sekunde (`0` = ungedrosselt) |
| `WEB_PORT` | `8097` | Web-Seite; leer = aus |
| `KUMA_PUSH_URL` | – | Push-URL eines Uptime-Kuma-Monitors (enthält das Token: Geheimnis) |
| `UNGESUND_ENDE_S` | `600` | nach so vielen Sekunden ununterbrochener Ungesundheit beenden (Exit 1); `0` = nie |
| `HERZ_S` | `30` | Takt von Status, Verfügbarkeit, Healthcheck-Datei und Kuma-Push |
| `LOG_LEVEL` | `INFO` | Python-Logging |

**ebusd-Container** (das offizielle Image übersetzt `EBUSD_*` in Kommandozeilen-Optionen)

| Variable | Beispiel | Bedeutung |
|---|---|---|
| `EBUSD_DEVICE` | `ens:192.0.2.10:9999` | Adapter |
| `EBUSD_ADDRESS` | `31` | gleiche Adresse wie `EBUS_ADRESSE` der Brücke |
| `EBUSD_MQTTHOST`, `…PORT`, `…USER`, `…PASS` | | optional: ebusd veröffentlicht zusätzlich selbst |
| `EBUSD_MQTTTOPIC` | `ebusd/%circuit/%name` | Topic-Schema von ebusd |

ebusd läuft mit `--pollinterval=0` (die Brücke bestimmt, was wann gelesen wird) und `--enablehex` (für das
Schreiben). Port 8888 bleibt im Compose-Netz und wird nicht nach außen veröffentlicht.

<a id="de-werte"></a>
## Werte und ihre Quellen

`ebus2mqtt/katalog.py` ist die einzige Quelle: jeder Wert mit eBUS-Quelle, Umrechnung, Abfragetakt, Klartextname und
Dokumentationslink (`ebus2mqtt/daten/doku.json`). Die ebusd-CSV wird daraus erzeugt (`python3 tools/gen_csv.py`; ein
Test prüft, dass beide gleich sind).

| Quelle | Telegramm | Beispiele |
|---|---|---|
| Kessel-Slots (Display-Liste) | `08 50 03 01 <slot>` | P10–P72, Vorlauf, Abgas, Last, Zähler |
| WCM-FS-Register | `35 50 22 03 <crc> <info-nr. LE>` | Raumsollwerte, Heizkurve, Betriebsart, Außentemperaturen, Zeitprogramme |
| Kessel-Broadcast | `f1 fe 50 0a` (alle 30 s) | Brennerphase, Flamme, Gasventil, Pumpe, Anforderung |

Das Prüfbyte der Register ist ein CRC-8 mit Polynom 0x5C über die Adressbytes (siehe aghulas unter Dank).
Brennerzähler: Schaltspiele i42 ×1000, Betriebsstunden i43 ×100 h, Zeit seit Wartung i45 ×10 h.

<a id="de-abfrage"></a>
## Abfrageplan und Buslast

| Takt | Intervall | Inhalt |
|---|---|---|
| Broadcast | 10 s aus dem ebusd-Cache | Brennerphase, Flamme, Gasventil, Pumpe (kein eigener Buszugriff) |
| `schnell` | 60 s | Vorlauf, Abgas, Last, Anforderung |
| `param` | 180 s | P30/P31, Außentemperaturen, Zähler, Fehler |
| `hk`, `zeit` | 600 s | Heizkreis-Einstellungen, Zeitprogramme, Datum/Uhrzeit |
| `display`, EEPROM | 900 s | übrige Fachmann-Parameter |
| `kandidat` | 900 s | Rohwerte noch unbelegter Slots (nur Forschung, keine Entität) |

Fällige Werte kommen in eine Warteschlange (kürzester Takt zuerst) und werden mit höchstens `LESEN_PRO_S` pro
Sekunde gelesen: keine Bursts, Live-Werte haben Vorrang. Alle Home-Assistant-Werte kommen öfter als ihr
`expire_after` (1200 s). Mit diesen Takten sind es rund 1170 Bus-Lesungen pro Stunde. Jeder eigene Set liest den
Wert sofort zurück; Einstellwerte müssen darum nicht oft abgefragt werden. Die Buslast zeigt `ebusctl info`
(`symbol rate`, Symbole pro Sekunde; der Bus schafft etwa 240 bei 2400 Baud).

<a id="de-schreiben"></a>
## Schreiben

Gesendet wird über ebusd `hex`.

| Art | Telegramm | Werte | von Adresse 31 |
|---|---|---|---|
| Kessel-Parameter | `03 50 04 02 <slot> <wert>` | P18, P20, P23, P30–P32, P34, P37, P42, P43 | angenommen |
| Heizkreis (WCM-FS) | `35 50 23 05 <crc> <adr> <wert>` | 111, 113, 413, 117, So/Wi, Frost, 501, Regelvariante, Zeitprogramme | quittiert, **nicht** übernommen; braucht `ff` |

- Mit `EBUS_ADRESSE=31` abonniert die Brücke nur P30/P31/P42/P43, mit `ff` alle Werte mit belegtem Schreibweg.
- Jeder Set wird gegen Min/Max/Optionen der Discovery geprüft und danach **zurückgelesen**. Erfolg meldet
  `<prefix>/<name>/set_status` (`{"ok": true, "grund": "Rueckwert …"}`) erst, wenn der Rückwert passt.
- Sets laufen **nacheinander**. Bei einem Bus- oder Verbindungsfehler (`ERR …`, Verbindung weg) wiederholt die Brücke
  bis zu viermal mit 2/4/8 s Abstand; ein Wert außerhalb der Grenzen wird nicht wiederholt.
- Werte ohne belegten Schreibweg (z. B. Datum) werden abgelehnt.

> **Warnung.** Kessel-Parameter wie P37 (Maximalleistung), P34 (Taktsperre) oder P42/P43 (Pumpe) verändern das
> Betriebsverhalten der Therme. Ändern Sie nur Werte, deren Bedeutung Sie aus der Fachmann-Anleitung kennen, und
> notieren Sie den alten Wert. Einen falschen Wert korrigiert man über denselben Weg oder am Gerät.

<a id="de-topics"></a>
## MQTT-Topics

| Topic | Inhalt |
|---|---|
| `<prefix>/<name>/value` | Wert als Text wie WcmToMqtt, retained, bei jedem gültigen Lesen |
| `<prefix>/<name>/fresh` | `{"ts": <epoch>, "iv": <soll-s>}`, retained, für Wächter je Wert |
| `<prefix>/<name>/available` | `online`/`offline` aus der Frische (Alter ≤ 3 × Intervall), retained |
| `<prefix>/<name>/set` → `…/set_status` | Befehl aus Home Assistant, Antwort als JSON |
| `VERFUEGBAR_TOPIC` | `query OK` / `offline` (auch als Last Will), retained |
| `STATUS_TOPIC` | JSON-Status der Brücke, retained, alle `HERZ_S` |
| `<prefix>/_roh/<quelle>` | Rohwerte der Kandidaten (nicht retained), für `tools/vergleich.py` |
| `homeassistant/device/wcm/config` | Discovery (Gerät *WCM-COM*, unique_id = Name wie WcmToMqtt) |

<a id="de-web"></a>
## Web-Seite

`/`: Tabelle aller Werte (Klartextname, Wert, Einheit, Alter, Quelle, Schreibweg, Dokumentationslink), alle 10 s
aktualisiert. `/api/werte`: JSON. `/status`: 200 (gesund) bzw. 503. Nur GET, keine Knöpfe.

<a id="de-gesundheit"></a>
## Gesundheit und Überwachung

Die Brücke ist **gesund**, solange ebusd `signal: acquired` meldet und in den letzten 120 s eine Lesung gelang.
Sichtbar an vier Stellen:

1. **Docker-Healthcheck**: Brücke über die Herzschlag-Datei, ebusd über `ebusctl info` (`signal: acquired`).
2. **`/status`** der Web-Seite (200/503).
3. **`STATUS_TOPIC`** (JSON): `gesund`, `ungesund_s`, `ebusd.signal`, `ebusd.reconnects`, `frisch`/`gesamt`,
   `haengend`, `fehler` je Art, `arbitrierung_verloren`, `lesedauer_ms` (Median/p95), `aeltester`, `laufzeit_s`.
4. **Uptime Kuma** (optional, `KUMA_PUSH_URL`): Push alle 30 s mit `up`/`down`, Text „frisch/gesamt, Signal“ und
   der Lesedauer als Ping.

Docker startet einen nur *unhealthy* Container **nicht** neu. Darum beendet sich die Brücke nach `UNGESUND_ENDE_S`
ununterbrochener Ungesundheit selbst (Exit 1, vorher `offline`), und `restart: unless-stopped` startet sie frisch.
Das löst eine hängende Verbindung auf Seiten der Brücke. ebusd verbindet sich selbst neu mit dem Adapter. Bleiben
Adapter oder Bus weg, startet die Brücke etwa alle 10 min neu und der Status bleibt `offline`; genau darauf sollte
ein Alarm schauen.

**Empfohlener Alarm** (Beispiel): `STATUS_TOPIC` fehlt oder ist älter als 5 min, `gesund` ist `false`, einzelne
`fresh`-Topics älter als 3 × `iv`, und, falls der Adapter eigene Diagnosewerte nach Home Assistant meldet, eBUS-Signal
aus oder häufige Trennungen von ebusd.

<a id="de-fehlersuche"></a>
## Fehlersuche

| Symptom | Ursache und Abhilfe |
|---|---|
| ebusd meldet **jede Minute** `transport closed`, danach `re-opened` nach 5 s; im Adapter-Log (`/api/v1/log`) steht jedes Mal `watch: restarting eBUS` | Der **Watchdog des Adapters** ist eingeschaltet (Einstellung *Watchdog → Interval*, Werkseinstellung *off*, Aktion *restart eBUS I/O*) und hält die Verbindung zeitweise für ungesund. Watchdog auf *off* stellen (`/api/v1/config` zeigt dann `"watchdog": 0`), speichern und den Adapter neu starten (die Oberfläche meldet sonst „Reboot required“). Die Brücke überwacht selbst und startet bei Bedarf neu. |
| `transport closed` unregelmäßig | Zweiter Client am Adapter (zweiter ebusd, Testcontainer), WLAN (RSSI schlechter als etwa −80 dBm), Neustarts des Adapters (`uptime` springt zurück). Im Adapter-Log steht bei jedem neuen Client `wait_host_tcp: accepted: <ip>`. |
| Heizkreis-Set wird quittiert, Wert bleibt | ebusd sendet als `31`; der WCM-FS übernimmt nur von `ff`. Siehe [Adressen](#de-adressen). |
| `ERR: SYN received` / `arbitration lost` gelegentlich | normal bei mehreren Mastern; die Brücke zählt sie im Status. Gehäuft: zweiter Master mit gleicher Adresse. |
| Werte nach einem Neustart kurz `unavailable` | Home Assistant lädt MQTT neu oder die Brücke liest die Werte gedrosselt nach; nach spätestens einem Takt sind sie zurück. |
| HA-Entitäten fehlen | `HA_DISCOVERY_PREFIX` leer oder anders als in Home Assistant; Discovery-Topic `homeassistant/device/wcm/config` prüfen. |

<a id="de-entwicklung"></a>
## Entwicklung

```sh
pip install -r requirements.txt pytest
python3 -m pytest                                  # Umrechnungen gegen echte Busdaten geprüft
python3 tools/ebusd_inject_test.py <ebusd-image>   # die CSV dekodiert im echten ebusd (läuft in der CI)
```

<a id="de-lizenz"></a>
## Dank und Lizenz

GPL-3.0-or-later, siehe `LICENSE` und `NOTICE`. Aufgebaut auf der Arbeit von
[aghulas/weishaupt-ebus](https://github.com/aghulas/weishaupt-ebus) (Register-CRC, Schreibformat, Belege),
[jdanion/ebusd-configuration-weishaupt](https://github.com/jdanion/ebusd-configuration-weishaupt) (Broadcast-Aufbau),
[WcmToMqtt](https://git.uli-eckhardt.de/WcmToMqtt) (Topic-Aufbau, Werteformate, Maps) und
[ebusd](https://github.com/john30/ebusd).

---

<a id="english"></a>

# English

eBUS → MQTT / Home Assistant bridge for **Weishaupt WTC 15-A / 25-A** gas condensing boilers with a **WCM-FS**
heating circuit controller. It reads the boiler and the heating circuit directly on the eBUS (via an eBUS adapter and
[ebusd](https://github.com/john30/ebusd)) and publishes the same topics, unique IDs and Home Assistant discovery as
[WcmToMqtt](https://git.uli-eckhardt.de/WcmToMqtt), so it can replace a WCM-COM gateway without changing your
Home Assistant entities.

> **Not affiliated with Weishaupt.** Product names are used only to describe compatibility. Use at your own risk:
> writing to a heating appliance can damage it or make it unsafe. Read [Writing](#en-writing) before enabling it.

## Contents

[What and why](#en-what) · [Hardware and wiring](#en-hardware) · [Addresses and WCM-COM replacement](#en-addresses) ·
[Quickstart](#en-quickstart) · [Variables](#en-variables) · [Values and sources](#en-values) ·
[Poll plan](#en-poll) · [Writing](#en-writing) · [MQTT topics](#en-topics) · [Web page](#en-web) ·
[Health and monitoring](#en-health) · [Troubleshooting](#en-troubleshooting) · [Development](#en-development) ·
[Credits and license](#en-license)

<a id="en-what"></a>
## What and why

The WCM-COM is a network gateway on the boiler's eBUS that offers values over HTTP; WcmToMqtt polls it and turns
them into MQTT. The WCM-COM answers slowly, serves one client at a time and is one more thing that can fail.
ebus2mqtt talks to the bus itself instead:

- **58 values compatible with WcmToMqtt** (burner phase, flame, gas valve, pump, flow/flue/outdoor temperatures,
  load, heating-circuit settings, time programs …) plus **23 extra read-only values** (installer parameters P10–P72
  including pump speed P42/P43, correctly scaled burner counters).
- **Per-value freshness** (`<prefix>/<name>/fresh`, `…/available`), a JSON status topic, optional Uptime Kuma push.
- A small read-only **web page** with every value, its unit, age, eBUS source and a link to its documentation.
- **Writes with read-back verification**: a set only reports success when the device reports the new value.
- **Even bus load** and **no lost sets** across short connection gaps.

<a id="en-hardware"></a>
## Hardware and wiring

- An **eBUS adapter** with the TCP "enhanced" protocol, e.g. the *eBUS Adapter Shield v5*, used in ebusd as
  `ens:<ip>:9999`. Connect its two eBUS terminals to the system's eBUS line, where the WCM-FS or WCM-COM is
  connected; the terminal names are in the installation manual of your boiler or controller.
- Tested on a Weishaupt **WTC 25-A** (burner control *Kromschröder W 0315 / 0301*) with a **WCM-FS** heating circuit
  controller, November 2026. Other WTC models may use other slots: read before you write.
- Exactly **one** ebusd may use the adapter. A second client (a second ebusd, a test container) disconnects the
  first.
- A Docker host on the same network as the adapter and the MQTT broker.

<a id="en-addresses"></a>
## Addresses and WCM-COM replacement

| Participant | Master | Slave | Note |
|---|---|---|---|
| Boiler (burner control) | `03` | `08` | display slots `08 50 03 01 <slot>`, broadcast `f1 fe 50 0a` |
| Heating circuit controller WCM-FS | – | `35` | registers `35 50 22 03 …`, write `35 50 23 05 …` |
| WCM-COM | `ff` | `04` | replaced by ebus2mqtt |
| ebusd (this bridge) | `31` or `ff` | `36` or `04` | setting `EBUS_ADRESSE` |

**Two modes:**

1. **WCM-COM stays on the bus** (`EBUS_ADRESSE=31`, default): ebus2mqtt reads everything but writes only boiler
   parameters (P30/P31/P42/P43). The WCM-FS acknowledges writes from `31` but does not take them.
2. **WCM-COM replaced** (`EBUS_ADRESSE=ff`): first **disconnect the WCM-COM from the eBUS** (it may stay powered),
   then set `EBUS_ADRESSE=ff` and restart the stack. Now the WCM-FS takes heating-circuit values too.

> **Never set `ff` while the WCM-COM is on the bus.** Two masters with the same address collide; telegrams get lost
> or attributed wrongly. To check that the WCM-COM is really gone: `ebusctl hex 04070400` must answer
> `read timeout` (`scan 04` only returns the cache).

Mixed operation (transition): `AUSLASSEN` makes ebus2mqtt skip values that WcmToMqtt still publishes; give
ebus2mqtt its own availability topic with `VERFUEGBAR_TOPIC`, because `<prefix>/status` still belongs to WcmToMqtt.

<a id="en-quickstart"></a>
## Quickstart (Docker)

```sh
cp .env.example .env                 # set EBUS_DEVICE, MQTT_HOST, MQTT_USER, MQTT_PASSWORD
docker compose -f docker-compose.example.yml up -d
# web page: http://<docker-host>:8097/
```

Images (built by CI, tagged `sha-<commit>`): `ghcr.io/turbolooser/ebus2mqtt-ebusd` (official `john30/ebusd` v26.1
plus the CSV in `ebusd/csv/`) and `ghcr.io/turbolooser/ebus2mqtt-bridge`. In production pin a tag, better a digest,
instead of `main`.

Acceptance after start: the web page shows every value fresh, `ebus2mqtt/status` reports `"gesund": true` and
`frisch` = `gesamt`, and the entities of the *WCM-COM* device are available in Home Assistant.

<a id="en-variables"></a>
## Variables (environment)

**Bridge**

| Variable | Default | Meaning |
|---|---|---|
| `EBUSD_HOST`, `EBUSD_PORT` | `ebusd`, `8888` | ebusd in the same compose network |
| `EBUS_ADRESSE` | `31` | ebusd master address; `ff` only after disconnecting the WCM-COM (see above) |
| `MQTT_HOST`, `MQTT_PORT` | –, `1883` | broker |
| `MQTT_USER`, `MQTT_PASSWORD` | – | broker account (secret, never commit) |
| `MQTT_CLIENT_ID` | `ebus2mqtt` | client ID at the broker |
| `MQTT_PREFIX` | `wcm` | topic prefix (same as WcmToMqtt) |
| `HA_DISCOVERY_PREFIX` | `homeassistant` | discovery prefix; empty = no discovery (side-by-side testing) |
| `VERFUEGBAR_TOPIC` | `<prefix>/status` | availability topic of this bridge |
| `AUSLASSEN` | – | comma list of values another bridge still publishes (mixed operation) |
| `STATUS_TOPIC` | `ebus2mqtt/status` | JSON status (see [Health](#en-health)) |
| `SET_AKTIV` | `1` | `0` = do not subscribe to any set topic |
| `ROH` | `1` | publish raw values of unassigned candidates under `<prefix>/_roh/` |
| `LESEN_PRO_S` | `2` | at most this many bus reads per second (`0` = unthrottled) |
| `WEB_PORT` | `8097` | web page; empty = off |
| `KUMA_PUSH_URL` | – | push URL of an Uptime Kuma monitor (contains the token: secret) |
| `UNGESUND_ENDE_S` | `600` | exit (code 1) after this many seconds of continuous ill health; `0` = never |
| `HERZ_S` | `30` | interval of status, availability, healthcheck file and Kuma push |
| `LOG_LEVEL` | `INFO` | Python logging |

**ebusd container** (the official image turns `EBUSD_*` into command-line options)

| Variable | Example | Meaning |
|---|---|---|
| `EBUSD_DEVICE` | `ens:192.0.2.10:9999` | adapter |
| `EBUSD_ADDRESS` | `31` | same address as the bridge's `EBUS_ADRESSE` |
| `EBUSD_MQTTHOST`, `…PORT`, `…USER`, `…PASS` | | optional: ebusd also publishes by itself |
| `EBUSD_MQTTTOPIC` | `ebusd/%circuit/%name` | ebusd topic scheme |

ebusd runs with `--pollinterval=0` (the bridge decides what is read when) and `--enablehex` (for writing). Port 8888
stays inside the compose network and is not published.

<a id="en-values"></a>
## Values and where they come from

`ebus2mqtt/katalog.py` is the single source: every value with its eBUS source, conversion, poll interval, plain name
and documentation link (`ebus2mqtt/daten/doku.json`). The ebusd CSV is generated from it (`python3 tools/gen_csv.py`;
a test checks that both are in sync).

| Source | Telegram | Examples |
|---|---|---|
| boiler slots (display list) | `08 50 03 01 <slot>` | P10–P72, flow, flue gas, load, counters |
| WCM-FS registers | `35 50 22 03 <crc> <info no. LE>` | room set points, curve, mode, outdoor temps, time programs |
| boiler broadcast | `f1 fe 50 0a` (every 30 s) | burner phase, flame, gas valve, pump, demand |

The register check byte is CRC-8 with polynomial 0x5C over the address bytes (see aghulas under Credits).
Burner counters: starts i42 ×1000, operating hours i43 ×100 h, time since service i45 ×10 h.

<a id="en-poll"></a>
## Poll plan and bus load

| Group | Interval | Content |
|---|---|---|
| broadcast | 10 s from the ebusd cache | burner phase, flame, gas valve, pump (no bus access of its own) |
| `schnell` | 60 s | flow, flue gas, load, demand |
| `param` | 180 s | P30/P31, outdoor temperatures, counters, errors |
| `hk`, `zeit` | 600 s | heating-circuit settings, time programs, date/time |
| `display`, EEPROM | 900 s | remaining installer parameters |
| `kandidat` | 900 s | raw values of unassigned slots (research only, no entity) |

Due values go into a queue (shortest interval first) and are read at no more than `LESEN_PRO_S` per second: no
bursts, live values first. Every Home Assistant value arrives more often than its `expire_after` (1200 s). With
these intervals the bridge makes about 1170 bus reads per hour. Every own set reads the value back at once, so
settings need not be polled often. `ebusctl info` shows the bus load (`symbol rate`, symbols per second; the bus
carries about 240 at 2400 baud).

<a id="en-writing"></a>
## Writing

Sent via ebusd `hex`.

| Kind | Telegram | Values | from address 31 |
|---|---|---|---|
| boiler parameter | `03 50 04 02 <slot> <value>` | P18, P20, P23, P30–P32, P34, P37, P42, P43 | accepted |
| heating circuit (WCM-FS) | `35 50 23 05 <crc> <addr> <value>` | 111, 113, 413, 117, summer/winter, frost, 501, control mode, time programs | acknowledged but **not** taken; needs `ff` |

- With `EBUS_ADRESSE=31` the bridge subscribes only to P30/P31/P42/P43, with `ff` to every value with a known write
  path.
- Every set is checked against the discovery's min/max/options and then **read back**. `<prefix>/<name>/set_status`
  reports success (`{"ok": true, "grund": "Rueckwert …"}`) only when the read-back matches.
- Sets run **one at a time**. On a bus or connection error (`ERR …`, connection lost) the bridge retries up to four
  times, 2/4/8 s apart; a value out of range is not retried.
- Values without a known write path (e.g. the date) are rejected.

> **Warning.** Boiler parameters such as P37 (maximum output), P34 (anti-cycling delay) or P42/P43 (pump) change how
> the boiler operates. Only change values whose meaning you know from the installer manual, and note the old value.
> A wrong value is corrected the same way or on the appliance.

<a id="en-topics"></a>
## MQTT topics

| Topic | Content |
|---|---|
| `<prefix>/<name>/value` | value as text like WcmToMqtt, retained, on every valid read |
| `<prefix>/<name>/fresh` | `{"ts": <epoch>, "iv": <nominal s>}`, retained, for per-value watchdogs |
| `<prefix>/<name>/available` | `online`/`offline` from freshness (age ≤ 3 × interval), retained |
| `<prefix>/<name>/set` → `…/set_status` | command from Home Assistant, answer as JSON |
| `VERFUEGBAR_TOPIC` | `query OK` / `offline` (also last will), retained |
| `STATUS_TOPIC` | JSON status of the bridge, retained, every `HERZ_S` |
| `<prefix>/_roh/<source>` | raw candidate values (not retained), for `tools/vergleich.py` |
| `homeassistant/device/wcm/config` | discovery (device *WCM-COM*, unique_id = name like WcmToMqtt) |

<a id="en-web"></a>
## Web page

`/`: table of all values (plain name, value, unit, age, source, write path, documentation link), refreshed every
10 s. `/api/werte`: JSON. `/status`: 200 (healthy) or 503. GET only, no buttons.

<a id="en-health"></a>
## Health and monitoring

The bridge is *healthy* while ebusd reports `signal: acquired` and a read succeeded within the last 120 s. Health is
visible in four places:

1. **Docker healthcheck**: the bridge via its heartbeat file, ebusd via `ebusctl info` (`signal: acquired`).
2. **`/status`** of the web page (200/503).
3. **`STATUS_TOPIC`** (JSON): `gesund`, `ungesund_s`, `ebusd.signal`, `ebusd.reconnects`, `frisch`/`gesamt`,
   `haengend`, `fehler` per kind, `arbitrierung_verloren`, `lesedauer_ms` (median/p95), `aeltester`, `laufzeit_s`.
4. **Uptime Kuma** (optional, `KUMA_PUSH_URL`): push every 30 s with `up`/`down`, the text "fresh/total, signal"
   and the read latency as ping.

Docker does **not** restart a container that is merely *unhealthy*. So after `UNGESUND_ENDE_S` of continuous ill
health the bridge publishes `offline` and exits with code 1; `restart: unless-stopped` then starts it fresh. This
clears a stuck connection on the bridge side. ebusd reconnects to the adapter by itself; if the adapter or the bus
stays down, the bridge keeps restarting about every 10 minutes and the status stays `offline`, which is what your
alarm should watch.

**Suggested alarm** (example): `STATUS_TOPIC` missing or older than 5 min, `gesund` is `false`, single `fresh`
topics older than 3 × `iv`, and, if your adapter reports its own diagnostics to Home Assistant, eBUS signal off or
frequent ebusd disconnects.

<a id="en-troubleshooting"></a>
## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| ebusd logs `transport closed` **every minute**, then `re-opened` 5 s later; the adapter log (`/api/v1/log`) shows `watch: restarting eBUS` each time | The **adapter's watchdog** is on (setting *Watchdog → Interval*, factory default *off*, action *restart eBUS I/O*) and at times considers the connection unhealthy. Set the watchdog to *off* (`/api/v1/config` then shows `"watchdog": 0`), save and reboot the adapter (otherwise the UI shows "Reboot required"). The bridge does its own health monitoring and restarts when needed. |
| `transport closed` at irregular times | a second client on the adapter (second ebusd, test container), Wi-Fi (RSSI worse than about −80 dBm), adapter reboots (`uptime` jumps back). The adapter log shows `wait_host_tcp: accepted: <ip>` for every new client. |
| heating-circuit set acknowledged, value unchanged | ebusd sends as `31`; the WCM-FS only takes writes from `ff`. See [Addresses](#en-addresses). |
| occasional `ERR: SYN received` / `arbitration lost` | normal with several masters; the bridge counts them in the status. Frequent: a second master with the same address. |
| values briefly `unavailable` after a restart | Home Assistant reloads MQTT, or the bridge re-reads values throttled; they are back within one interval at most. |
| HA entities missing | `HA_DISCOVERY_PREFIX` empty or different from Home Assistant's; check the discovery topic `homeassistant/device/wcm/config`. |

<a id="en-development"></a>
## Development

```sh
pip install -r requirements.txt pytest
python3 -m pytest                                  # conversions checked against real bus data
python3 tools/ebusd_inject_test.py <ebusd-image>   # the CSV decodes in real ebusd (runs in CI)
```

<a id="en-license"></a>
## Credits and license

GPL-3.0-or-later, see `LICENSE` and `NOTICE`. Built on the work of
[aghulas/weishaupt-ebus](https://github.com/aghulas/weishaupt-ebus) (register CRC, write format, evidence),
[jdanion/ebusd-configuration-weishaupt](https://github.com/jdanion/ebusd-configuration-weishaupt) (broadcast layout),
[WcmToMqtt](https://git.uli-eckhardt.de/WcmToMqtt) (topic layout, value formats, maps) and
[ebusd](https://github.com/john30/ebusd).
