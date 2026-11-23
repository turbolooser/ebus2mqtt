"""Auswertung der Parallel-Probe mit erfundener, aber bekannter Zeitreihe."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))
import vergleich as V  # noqa: E402


def test_auswertung_gleichheit_latenz_und_kandidat(tmp_path):
    t0 = 1_795_400_000
    ev = []
    for i in range(0, 4 * 3600, 60):
        t = t0 + i
        an = (i // 1200) % 2 == 1            # alle 20 min Brenner an/aus
        ev.append({"ts": t, "t": "wcm/Flamme/value", "p": "ON" if an else "OFF"})
        ev.append({"ts": t + 20, "t": "ebustest/Flamme/value", "p": "ON" if an else "OFF"})
        ev.append({"ts": t, "t": "wcm/P30-Min-VL-Soll/value", "p": "41.0"})
        ev.append({"ts": t + 5, "t": "ebustest/P30-Min-VL-Soll/value", "p": "41.0"})
        bc = [1, 6 if an else 0, 0x7f if an else 0x47, 0x52 if an else 0x12, 30, 80, 255, 255, 0, 3, 2, 3, 45]
        ev.append({"ts": t + 10, "t": "ebustest/_roh/bc_f1fe500a", "p": json.dumps({"ts": t, "wert": bc})})
    d = tmp_path / "m.jsonl"
    d.write_text("\n".join(json.dumps(e) for e in ev))
    daten = V.auswerten(str(d), str(tmp_path / "b.md"), "ebustest")
    assert daten["readings"]["P30-Min-VL-Soll"]["gleich"] == 1.0
    fl = daten["readings"]["Flamme"]
    assert fl["gleich"] > 0.95 and fl["latenz_median"] == 20
    best = daten["kandidaten"]["Flamme"][0]
    assert best[0] == 1.0 and best[1].startswith("bc_f1fe500a[")
    assert "Parallel-Probe" in (tmp_path / "b.md").read_text()
