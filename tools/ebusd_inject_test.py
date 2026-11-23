"""Prueft im echten ebusd-Image, dass die CSV die Telegramme vom 23.11.2026 so dekodiert, wie die Bruecke
sie erwartet. Ohne Bus: ebusd mit totem Geraet, Telegramme per --inject als "schon gesehen".
Aufruf: python3 tools/ebusd_inject_test.py <image>   (Exit 1 bei Abweichung)
"""
import subprocess
import sys
import time

# Telegramm (Master/Slave, wie im Mitschnitt) -> (circuit, name, feld, erwartete ebusd-Ausgabe)
FAELLE = [
    ("31085003011e/063629171f0808", "wtc", "P30", "wert", "41"),
    ("310850030114/0637ff1115fcfc", "wtc", "P20", "wert", "-1"),
    ("31085003012a/06353c292b1414", "wtc", "P42", "wert", "60"),
    ("3108500301aa/0560e601292b", "wtc", "I42", "wert", "486"),
    ("31085003018c/05b603000b0d", "wtc", "S8c", "wert", "3"),
    ("ff35502203700500/02c300", "hk1", "R5", "wert", "195"),
    ("ff35502203091201/020d00", "hk1", "R274", "wert", "13"),
    ("ff35502203a41014/023418", "hk1", "R5136", "wert", "6196"),
    ("f1fe500a0d01067f522252ffff000302032d/", "wtc", "Status", "daten", "01 06 7f 52 22 52 ff ff 00 03 02 03 2d"),
]


def main(image):
    name = "ebusd-inject-test"
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    subprocess.run(["docker", "run", "-d", "--name", name, "--entrypoint", "ebusd", image, "-f",
                    "-d", "tcp:127.0.0.1:9", "-p", "8888", "--configpath=/etc/ebusd/wtc25", "--pollinterval=0",
                    "--log=all:notice", "--inject"] + [f[0] for f in FAELLE], check=True, capture_output=True)
    time.sleep(4)
    fehler = 0
    try:
        for tel, circ, msg, feld, soll in FAELLE:
            r = subprocess.run(["docker", "exec", name, "ebusctl", "-p", "8888", "read", "-c", circ, msg, feld],
                               capture_output=True, text=True)
            ist = r.stdout.strip()
            ok = ist == soll
            fehler += not ok
            print(f"{'ok ' if ok else 'FEHLER'} {circ} {msg} {feld}: {ist!r} (soll {soll!r})")
    finally:
        log = subprocess.run(["docker", "logs", name], capture_output=True, text=True)
        if fehler:
            print(log.stdout[-3000:], log.stderr[-3000:])
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
