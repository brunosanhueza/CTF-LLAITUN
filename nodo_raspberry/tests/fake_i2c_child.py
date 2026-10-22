"""Hijo de pruebas: no importa bibliotecas de hardware."""
import json
import os
import signal
import sys
import time

mode, history = sys.argv[1:3]
config = json.loads(sys.argv[3])
with open(history, "a") as f:
    f.write(str(os.getpid()) + "\n")
if mode == "crash":
    sys.exit(7)
if mode == "stall" and not config["quarantine"]:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print(json.dumps({"kind": "progress", "channel": 0}), flush=True)
    while True:
        time.sleep(0.1)
while True:
    print(json.dumps({"kind": "sample", "channel": 1, "state": "OK", "mm": 70}), flush=True)
    time.sleep(0.03)
