#!/usr/bin/env python3
"""
Solo las tiras LED del cuadrante 3: la animacion de llenado progresivo.

QUE HACE ESTE ARCHIVO
    Arranca UNICAMENTE el hilo de tiras (secuencia.HiloTiras) con el mismo
    codigo y la misma configuracion que main.py. No toca bombas, luminarias,
    semaforos, sensores ni el PLC, y no abre ninguna ventana: sirve por SSH.

    Es la prueba intermedia entre prueba_tira.py (una tira, colores fijos, no
    usa el proyecto) y main.py (todo junto): si aqui las tiras se ven bien y en
    main.py no, el problema es de la interaccion entre hilos; si fallan aqui
    tambien, es de la config, del hardware o del cableado.

    Estanques (T1) usa el color de config; Edificios (T2) va en RGB DINAMICO:
    el tono gira sin parar mientras la tira se llena. Solo aplica a este
    script; main.py y el puente PLC no lo usan.

USO (necesita root, igual que main.py)
    sudo python3 solo_tiras.py
    sudo python3 solo_tiras.py --color Verde --velocidad 30   # color de Estanques
    sudo python3 solo_tiras.py --leds 60          # las dos tiras con 60 LED
    sudo python3 solo_tiras.py --periodo-rgb 3    # RGB de Edificios mas rapido
    sudo python3 solo_tiras.py --sin-rgb          # Edificios con color fijo
    sudo python3 solo_tiras.py --fiesta           # SOLO PARA TESTEAR: flash de
                                                   # colores en las dos tiras
    sudo python3 solo_tiras.py --fiesta --periodo-fiesta 80   # flash mas rapido

    Cerrar main.py antes: las dos tiras comparten PWM/DMA y no pueden usarlas
    dos procesos a la vez. Ctrl+C apaga las tiras y sale.
"""

from __future__ import annotations

import argparse
import colorsys
import logging
import random
import sys
import threading
import time

import config
import hal
from estado import EstadoCompartido
from parametros import Parametros
from secuencia import HiloTiras


def _rgb_dinamico(parametros: Parametros, tira: str, periodo_s: float,
                  parar: threading.Event) -> None:
    """Hace girar el tono del color de una tira: RGB dinamico (arcoiris).

    Solo cambia el color en Parametros; HiloTiras lo relee en cada paso de la
    animacion, asi que el color de toda la tira va rotando mientras se llena.
    Es exclusivo de este script: main.py y el puente PLC no usan esto.
    """
    t0 = time.monotonic()
    while not parar.wait(0.03):
        tono = ((time.monotonic() - t0) / periodo_s) % 1.0
        r, g, b = colorsys.hsv_to_rgb(tono, 1.0, 1.0)
        parametros.set_color(tira, "RGB", (int(r * 255), int(g * 255), int(b * 255)))


def _regla(tiras, log) -> int:
    """Enciende TODOS los LED posibles con marcas, para contar el largo real.

    El WS2812B no devuelve datos, asi que el largo solo se puede contar mirando.
    Cada LED va en azul tenue (se ve hasta donde llega la tira fisica), el
    numero 10, 20, 30... en blanco, y el 50, 100, 150, 200 en rojo. El ultimo
    LED encendido de cada tira es su largo; las marcas ayudan a no perder la
    cuenta.
    """
    # Cada tira lleva su propio color para distinguir T1 de T2 a simple vista:
    #   T1: base AZUL tenue, marca cada 10 BLANCA
    #   T2: base VERDE tenue, marca cada 10 AMARILLA
    # El rojo cada 50 es igual en las dos.
    estilo = {"T1": ((0, 0, 40), (255, 255, 255)),
              "T2": ((0, 40, 0), (255, 200, 0))}
    for nombre in config.TIRAS:
        base, marca = estilo.get(nombre, ((0, 0, 40), (255, 255, 255)))
        colores = []
        for k in range(1, config.TIRA_N_LEDS_MAX + 1):
            if k % 50 == 0:
                colores.append((255, 0, 0))
            elif k % 10 == 0:
                colores.append(marca)
            else:
                colores.append(base)
        tiras.set_pixeles(nombre, colores)
    tiras.mostrar()
    log.info("Regla encendida en %s (T1 azul/blanco, T2 verde/amarillo, rojo "
             "cada 50, hasta %d). Ctrl+C para salir.",
             ", ".join(sorted(tiras.activas())), config.TIRA_N_LEDS_MAX)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    finally:
        tiras.cerrar()
        print("Tiras apagadas.")
    return 0


def _fiesta(tiras, log, periodo_ms: float, n_leds: dict[str, int]) -> int:
    """Efecto 'fiesta': flash de colores vivos e independientes en las dos tiras.

    SOLO PARA TESTEAR, EXCLUSIVO DE ESTE SCRIPT: cada tira recibe un color al
    azar (tono aleatorio, saturacion y brillo al maximo via HSV) en TODOS sus
    LED, y cambia cada `periodo_ms`. Las dos tiras se sortean por separado, asi
    que no quedan sincronizadas entre si.

    Mismo espiritu que Color_LED_Flag4 != 0 ("modo fiesta" de plc_bridge.py,
    que enciende las luminarias), pero aqui sobre las tiras y bypaseando
    HiloTiras/Parametros: no toca main.py ni el puente PLC para nada.
    """
    rng = random.Random()
    log.info("Modo fiesta en %s: cambia de color cada %.0f ms. Ctrl+C para salir.",
             ", ".join(sorted(tiras.activas())), periodo_ms)
    try:
        while True:
            for nombre in config.TIRAS:
                n = n_leds.get(nombre, config.TIRAS[nombre]["n_leds"])
                r, g, b = colorsys.hsv_to_rgb(rng.random(), 1.0, 1.0)
                color = (int(r * 255), int(g * 255), int(b * 255))
                tiras.set_pixeles(nombre, [color] * n)
            tiras.mostrar()
            time.sleep(periodo_ms / 1000.0)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    finally:
        tiras.cerrar()
        print("Tiras apagadas.")
    return 0


def main() -> int:
    nombres_color = [n for n, _ in config.TIRA_COLORES]

    parser = argparse.ArgumentParser(description="Solo las tiras LED del cuadrante 3")
    parser.add_argument("--color", choices=nombres_color, default=None,
                        help="color fijo de Estanques (y de Edificios solo con "
                             "--sin-rgb); por omision, el de config")
    parser.add_argument("--sin-rgb", action="store_true",
                        help="Edificios con color fijo en vez de RGB dinamico")
    parser.add_argument("--periodo-rgb", type=float, default=8.0, metavar="S",
                        help="segundos que tarda Edificios en dar una vuelta "
                             "completa de color (por omision, 8)")
    parser.add_argument("--velocidad", type=int, default=None, metavar="MS",
                        help="milisegundos por LED (por omision, el de config)")
    parser.add_argument("--leds", type=int, default=None, metavar="N",
                        help="largo logico de las dos tiras (por omision, el de config)")
    parser.add_argument("--regla", action="store_true",
                        help="enciende todos los LED con marcas (blanco cada 10, "
                             "rojo cada 50) para contar el largo real de la tira")
    parser.add_argument("--fiesta", action="store_true",
                        help="SOLO PARA TESTEAR: flash de colores vivos e "
                             "independientes en las dos tiras, sin el llenado "
                             "progresivo")
    parser.add_argument("--periodo-fiesta", type=float, default=150.0, metavar="MS",
                        help="milisegundos entre cada cambio de color en modo "
                             "fiesta (por omision, 150)")
    parser.add_argument("-v", "--verboso", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verboso else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-12s %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("solo_tiras")

    # hay_hardware=True: es solo para que el banco intente abrir las tiras
    # reales. No se crea ningun objeto GPIO, asi que los reles no se tocan.
    tiras, reales = hal.crear_banco_tiras(True)
    if not reales:
        for nombre, motivo in getattr(tiras, "errores", {}).items():
            log.error("Tiras sin iniciar (%s): %s", nombre, motivo)
        log.error("Las tiras quedaron SIMULADAS: no se vera nada en la maqueta. "
                  "Ejecutar con sudo y sin main.py abierto.")
        return 1

    if args.regla:
        return _regla(tiras, log)

    if args.fiesta:
        n_leds = {n: (args.leds if args.leds is not None else c["n_leds"])
                 for n, c in config.TIRAS.items()}
        return _fiesta(tiras, log, max(20.0, args.periodo_fiesta), n_leds)

    parametros = Parametros()
    if args.velocidad is not None:
        parametros.set_velocidad_ms(args.velocidad)
    if args.leds is not None:
        for nombre in config.TIRAS:
            parametros.set_n_leds(nombre, args.leds)
    # La tira de Edificios (T2 en config) va en RGB dinamico salvo con --sin-rgb.
    tira_rgb = None
    if not args.sin_rgb:
        tira_rgb = next((n for n, c in config.TIRAS.items()
                         if c["etiqueta"] == "Edificios"), None)

    if args.color is not None:
        rgb = dict(config.TIRA_COLORES)[args.color]
        for nombre in config.TIRAS:
            if nombre != tira_rgb:
                parametros.set_color(nombre, args.color, rgb)

    compartido = EstadoCompartido(True, False, True, parametros=parametros)
    hilo = HiloTiras(tiras, compartido, parametros)
    hilo.start()

    parar_rgb = threading.Event()
    if tira_rgb is not None:
        threading.Thread(
            target=_rgb_dinamico, name="rgb-dinamico", daemon=True,
            args=(parametros, tira_rgb, max(0.5, args.periodo_rgb), parar_rgb),
        ).start()
        log.info("%s (%s) en RGB dinamico: una vuelta de color cada %.1f s.",
                 config.TIRAS[tira_rgb]["etiqueta"], tira_rgb,
                 max(0.5, args.periodo_rgb))
    log.info("Tiras activas: %s | %d ms/LED | Ctrl+C para salir.",
             ", ".join(sorted(tiras.activas())), parametros.velocidad_ms())

    try:
        while hilo.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    finally:
        parar_rgb.set()
        hilo.detener()
        hilo.join(timeout=2.0)
        tiras.cerrar()          # apaga los LED y libera DMA/PWM
        print("Tiras apagadas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
