"""Schreibt ebusd/csv/wtc25.csv aus dem Katalog. Aufruf: python3 tools/gen_csv.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from ebus2mqtt.csvgen import text  # noqa: E402

ZIEL = os.path.join(os.path.dirname(__file__), "..", "ebusd", "csv", "wtc25.csv")
with open(ZIEL, "w", encoding="utf-8") as f:
    f.write(text())
print(ZIEL)
