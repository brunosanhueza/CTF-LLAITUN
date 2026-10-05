#!/usr/bin/env python3
"""
Prueba minima de una tira WS2812B. NO usa el resto del proyecto.

Sirve para separar dos causas que se confunden facil cuando "no prende nada":
si este script tampoco funciona, el problema esta en rpi_ws281x, en config.txt
o en el cableado; si funciona, el problema esta en el software del cuadrante.

Uso (necesita root si o si):
    sudo python3 prueba_tira.py               # tira 1, GPIO18, canal PWM 0
    sudo python3 prueba_tira.py --gpio 13     # tira 2, GPIO13, canal PWM 1
    sudo python3 prueba_tira.py --leds 5      # solo los primeros 5 LED
    sudo python3 prueba_tira.py --tipo RGB    # si los colores salen cambiados
"""

import argparse
import os
import sys
import time


def main() -> int:
    p = argparse.ArgumentParser(description="Prueba minima de tira WS2812B")
    p.add_argument("--gpio", type=int, default=18,
                   help="GPIO en numeracion BCM: 18 (PWM0) o 13 (PWM1)")
    p.add_argument("--leds", type=int, default=100, help="cantidad de LED")
    p.add_argument("--brillo", type=int, default=64, help="0 a 255")
    p.add_argument("--tipo", default="GRB",
                   help="orden de bytes: GRB (WS2812B), RGB, BRG...")
    args = p.parse_args()

    if os.geteuid() != 0:
        print("ERROR: rpi_ws281x necesita root. Ejecuta:\n"
              f"    sudo python3 {os.path.basename(__file__)}", file=sys.stderr)
        return 1

    try:
        from rpi_ws281x import PixelStrip, Color, ws
    except ImportError:
        print("ERROR: falta rpi_ws281x. Instalalo con:\n"
              "    sudo pip3 install --break-system-packages rpi_ws281x",
              file=sys.stderr)
        return 1

    # GPIO18 usa el canal PWM 0 y GPIO13 el canal PWM 1. Cruzarlos no funciona.
    canal = 1 if args.gpio in (13, 19, 41, 45) else 0
    tipo = getattr(ws, f"WS2811_STRIP_{args.tipo.upper()}", ws.WS2811_STRIP_GRB)

    print(f"GPIO{args.gpio} (BCM) = pin fisico "
          f"{12 if args.gpio == 18 else 33 if args.gpio == 13 else '?'}"
          f" | canal PWM {canal} | {args.leds} LED | tipo {args.tipo.upper()}")

    tira = PixelStrip(args.leds, args.gpio, 800000, 10, False, args.brillo, canal,
                      tipo)
    tira.begin()

    def pintar(nombre, color, pausa=1.5):
        print(f"  -> todo {nombre}")
        for i in range(args.leds):
            tira.setPixelColor(i, color)
        tira.show()
        time.sleep(pausa)

    try:
        print("Si ves los colores en el orden correcto, el hardware esta bien.")
        pintar("ROJO",  Color(255, 0, 0))
        pintar("VERDE", Color(0, 255, 0))
        pintar("AZUL",  Color(0, 0, 255))

        print("  -> barrido blanco, LED por LED")
        for i in range(args.leds):
            tira.setPixelColor(i, Color(255, 255, 255))
            tira.show()
            time.sleep(0.03)
        time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        for i in range(args.leds):
            tira.setPixelColor(i, Color(0, 0, 0))
        tira.show()
        print("Tira apagada.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
