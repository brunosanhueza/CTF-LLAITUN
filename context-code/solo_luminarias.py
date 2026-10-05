#!/usr/bin/env python3
"""
Solo las luminarias exteriores (L1, L2): las enciende y las deja encendidas.

QUE HACE ESTE ARCHIVO
    Abre el GPIO y enciende UNICAMENTE las luminarias (L1=GPIO9, L2=GPIO11),
    con el mismo codigo del proyecto (actuadores.BancoReles). No toca bombas,
    sensores, semaforos, tiras ni el PLC.

    De paso sirve para probar la advertencia de PRECAUCIONES.md sobre el SPI:
    si las luminarias NO encienden y no aparece ningun error, el SPI esta
    tomando GPIO 9/11 (ver `ls /dev/spidev*` y seccion B.3 de PRECAUCIONES.md).

USO (normalmente sin sudo: los reles usan RPi.GPIO, que entra por /dev/gpiomem)
    python3 solo_luminarias.py             # enciende L1 y L2
    python3 solo_luminarias.py --solo L1   # enciende solo L1
    python3 solo_luminarias.py --apagadas  # no enciende nada (prueba de estado seguro)

    Ctrl+C las apaga y libera el GPIO.
"""

from __future__ import annotations

import argparse
import sys
import time

import config
import hal
from actuadores import BancoReles


def main() -> int:
    parser = argparse.ArgumentParser(description="Solo las luminarias del cuadrante 3")
    parser.add_argument("--solo", choices=list(config.LUMINARIAS), default=None,
                        help="encender solo esta luminaria (por omision, las dos)")
    parser.add_argument("--apagadas", action="store_true",
                        help="no enciende nada: solo deja el estado seguro y espera")
    args = parser.parse_args()

    gpio, hay_hardware = hal.crear_gpio(False)
    if not hay_hardware:
        print("Sin hardware real (RPi.GPIO): este script solo sirve en la Raspberry Pi.",
              file=sys.stderr)
        return 1
    gpio.setmode(gpio.BCM)

    luminarias = BancoReles(
        gpio, config.LUMINARIAS, "luminarias",
        activo_en_bajo=config.LUMINARIA_ACTIVO_EN_BAJO,
    )

    objetivo = [] if args.apagadas else (
        [args.solo] if args.solo else list(config.LUMINARIAS)
    )
    for nombre in objetivo:
        luminarias.encender(nombre)
        cfg = config.LUMINARIAS[nombre]
        print(f"{nombre} ({cfg['etiqueta']}) -> ENCENDIDA  "
              f"(GPIO{cfg['gpio']}, pin fisico {cfg['pin_fisico']})")
    if not objetivo:
        print("Las dos luminarias quedan APAGADAS (estado seguro).")

    print("\nSi no se ve ninguna luz encendida y no hay ningun error arriba, "
          "revisar si el SPI esta activo: ls /dev/spidev*  (ver PRECAUCIONES.md).")
    print("Ctrl+C para apagar y salir.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    finally:
        luminarias.apagar_todos()
        gpio.cleanup()
        print("Luminarias apagadas, GPIO liberado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
