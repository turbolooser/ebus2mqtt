# ebus2mqtt

eBUS → MQTT / Home Assistant bridge for **Weishaupt WTC 15-A / 25-A** gas condensing boilers with a **WCM-FS**
heating circuit controller. It reads the boiler and the heating circuit directly on the eBUS (via an eBUS adapter and
[ebusd](https://github.com/john30/ebusd)) and publishes the same topics, unique IDs and Home Assistant discovery as
[WcmToMqtt](https://git.uli-eckhardt.de/WcmToMqtt), so it can replace a WCM-COM gateway without changing your
Home Assistant entities.

> **Not affiliated with Weishaupt.** Product names are used only to describe compatibility. Use at your own risk:
> writing to a heating appliance can damage it or make it unsafe. Read [Writing](#writing) before enabling it.

## What you get

- 58 values compatible with WcmToMqtt (burner phase, flame, gas valve, pump, flow/flue/outdoor temperatures, load,
  heating-circuit settings, time programs …) plus 23 extra read-only values (installer parameters P10–P72 including
  pump speed P42/P43, correctly scaled burner counters).
- Per-value freshness (`<prefix>/<name>/fresh`, `…/available`), a JSON status topic, optional Uptime Kuma push.
- A small read-only **web page** with every value, its unit, age, eBUS source and a link to its documentation.
- Writes with **read-back verification**: a set only reports success when the device reports the new value.

## Hardware

- eBUS adapter with the TCP "enhanced" protocol, e.g. the eBUS Adapter Shield (v5), used as `ens:<ip>:9999`.
- Tested on a Weishaupt **WTC 25-A** (burner control *Kromschröder W 0315 / 0301*) with a **WCM-FS** heating circuit
  controller, November 2026. Other WTC models may use other slots: read before you write.
- Exactly **one** ebusd may use the adapter.

## Quickstart (Docker)

```sh
cp .env.example .env                 # set EBUS_DEVICE, MQTT_HOST, MQTT_USER, MQTT_PASSWORD
docker compose -f docker-compose.example.yml up -d
# web page: http://<docker-host>:8097/
```

Images (built by CI, tagged `sha-<commit>`): `ghcr.io/turbolooser/ebus2mqtt-ebusd` (official `john30/ebusd` v26.1
plus the CSV in `ebusd/csv/`) and `ghcr.io/turbolooser/ebus2mqtt-bridge`.

## Configuration (environment)

| Variable | Default | Meaning |
|---|---|---|
| `EBUS_DEVICE` | – | ebusd device, e.g. `ens:192.0.2.10:9999` |
| `EBUS_ADRESSE` | `31` | ebusd master address (`ff` only after removing a WCM-COM, see Writing) |
| `MQTT_HOST`, `MQTT_PORT`, `MQTT_USER`, `MQTT_PASSWORD` | –, `1883` | broker |
| `MQTT_PREFIX` | `wcm` | topic prefix (same as WcmToMqtt) |
| `HA_DISCOVERY_PREFIX` | `homeassistant` | discovery prefix; any other value hides the entities from HA |
| `VERFUEGBAR_TOPIC` | `<prefix>/status` | availability topic of this bridge |
| `AUSLASSEN` | – | comma list of values another bridge still publishes (mixed operation) |
| `STATUS_TOPIC` | `ebus2mqtt/status` | JSON status: health, ebusd signal, errors, lost arbitrations, read latency |
| `SET_AKTIV` | `1` | `0` = do not subscribe to any set topic |
| `WEB_PORT` | `8097` | read-only web page; empty = off |
| `KUMA_PUSH_URL` | – | Uptime Kuma push URL |

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

## Web page

`/`: table of all values (plain name, value, unit, age, source, write path, documentation link), refreshed every
10 s. `/api/werte`: JSON. `/status`: 200/503. GET only, no buttons.

## Writing

Sent via ebusd `hex` (ebusd runs with `--enablehex`; keep its port 8888 inside the Docker network).

| Kind | Telegram | Values | from address 31 |
|---|---|---|---|
| boiler parameter | `03 50 04 02 <slot> <value>` | P18, P20, P23, P30–P32, P34, P37, P42, P43 | accepted |
| heating circuit (WCM-FS) | `35 50 23 05 <crc> <addr> <value>` | 111, 113, 413, 117, summer/winter, frost, 501, control mode, time programs | acknowledged but **not** taken; needs `ff` |

`ff` is the address of the WCM-COM. **Set `EBUS_ADRESSE=ff` only after the WCM-COM is disconnected from the eBUS**,
otherwise two masters collide. With address 31 the bridge subscribes only to P30/P31/P42/P43.

## Development

```sh
pip install -r requirements.txt pytest
python3 -m pytest                                  # conversions checked against real bus data
python3 tools/ebusd_inject_test.py <ebusd-image>   # the CSV decodes in real ebusd (runs in CI)
```

## Credits and license

GPL-3.0-or-later, see `LICENSE` and `NOTICE`. Built on the work of
[aghulas/weishaupt-ebus](https://github.com/aghulas/weishaupt-ebus) (register CRC, write format, evidence),
[jdanion/ebusd-configuration-weishaupt](https://github.com/jdanion/ebusd-configuration-weishaupt) (broadcast layout),
[WcmToMqtt](https://git.uli-eckhardt.de/WcmToMqtt) (topic layout, value formats, maps) and
[ebusd](https://github.com/john30/ebusd).

## Deutsch (kurz)

eBUS-Brücke für Weishaupt WTC 15-A/25-A mit WCM-FS: liest Kessel und Heizkreis direkt am eBUS und publiziert dieselben
MQTT-Topics und HA-Entitäten wie WcmToMqtt; ein WCM-COM wird überflüssig. Web-Seite (nur lesen) mit allen Werten,
Einheit, Alter, Quelle und Link in die Weishaupt-Anleitung. Schreiben mit Rücklesen; Heizkreis-Werte nur mit
Master-Adresse `ff`, und die erst, wenn das WCM-COM vom Bus getrennt ist. Kein Produkt von Weishaupt; Nutzung auf
eigenes Risiko.
