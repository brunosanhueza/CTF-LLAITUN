"""Entrada de diagnostico: reutiliza el daemon para evitar dos implementaciones."""
import os
from rtu_daemon import main

if __name__ == "__main__":
    os.environ["RTU_TELEMETRIA"] = "1"
    main()
