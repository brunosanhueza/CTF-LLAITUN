#!/usr/bin/env python3
"""
Version sin interfaz grafica del cuadrante 3.

PARA QUE SIRVE
    Probar la tarjeta por SSH, sin escritorio ni X11. Hace EXACTAMENTE lo mismo
    que main.py (mismo controlador, mismos hilos, mismo hardware) pero en vez
    de abrir una ventana redibuja el estado en la terminal dos veces por
    segundo.

    Tambien es la version que conviene dejar como servicio systemd, porque no
    necesita que haya nadie con sesion grafica iniciada.

COMO DIBUJA
    Con secuencias de escape ANSI: una para borrar la pantalla y llevar el
    cursor arriba, y otras para los colores. Se arma la pantalla completa en
    una lista de lineas y se escribe de un golpe, que parpadea mucho menos que
    ir imprimiendo linea por linea.

USO
    python3 prueba_consola.py
    sudo python3 prueba_consola.py              # con sudo para las tiras LED
    python3 prueba_consola.py --simular
    python3 prueba_consola.py --solo-sensores   # no mueve las bombas
    python3 prueba_consola.py --luminarias      # enciende los dos LED al arrancar

Ctrl+C apaga todo y sale.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

import config
import estado as est


# Secuencias de escape ANSI. \033[2J borra la pantalla y \033[H manda el cursor
# arriba a la izquierda; juntas equivalen a un "clear". Los numeros 9x son
# colores de texto y \033[0m vuelve al normal.
LIMPIAR = "\033[2J\033[H"
NEGRITA = "\033[1m"
NORMAL = "\033[0m"
VERDE = "\033[92m"
AMARILLO = "\033[93m"
ROJO = "\033[91m"
GRIS = "\033[90m"


def barra(pct: float, ancho: int = 24) -> str:
    """Barra de progreso en texto: '########................'."""
    llenos = int(round(pct / 100.0 * ancho))
    return "#" * llenos + "." * (ancho - llenos)


def pintar(instantanea) -> None:
    """Dibuja la pantalla completa a partir de una instantanea del estado.

    Es el equivalente de _refrescar() del dashboard: lee el estado y lo
    muestra, sin tocar hardware ni tomar decisiones.
    """
    s = instantanea
    modo = "HARDWARE REAL" if s.hay_hardware else "SIMULACION"

    lineas = [
        LIMPIAR,
        f"{NEGRITA}{config.NOMBRE_CUADRANTE}{NORMAL}   [{modo}]",
        f"{GRIS}Tarjeta de control de cuadrante v1.0.0 - Ctrl+C para salir{NORMAL}",
        "",
        f"  Fase : {NEGRITA}{est.DESCRIPCION_FASE.get(s.fase, s.fase)}{NORMAL}"
        f"   restante {s.restante_s:5.1f} s   ciclo {s.ciclo}",
        "",
        f"  {NEGRITA}BOMBAS{NORMAL} (reles activos en bajo)"
        f"{GRIS}   encender cada {s.tiempos_bombas[0]:.1f}s"
        f" / encendidas {s.tiempos_bombas[1]:.0f}s"
        f" / apagar cada {s.tiempos_bombas[2]:.1f}s"
        f" / apagadas {s.tiempos_bombas[3]:.0f}s{NORMAL}",
    ]

    for nombre, cfg in config.RELES.items():
        on = s.reles.get(nombre, False)
        habilitada = s.bombas_habilitadas.get(nombre, True)
        if not habilitada:
            marca = f"{ROJO}[ X ]{NORMAL}"
        elif on:
            marca = f"{VERDE}[ON ]{NORMAL}"
        else:
            marca = f"{GRIS}[off]{NORMAL}"
        nota = f"  {ROJO}deshabilitada{NORMAL}" if not habilitada else ""
        pines = "/".join(str(p) for p in cfg["pines"])
        canales = "/".join(str(c) for c in cfg["canales"])
        lineas.append(
            f"    {marca} {nombre}  {cfg['etiqueta']:<10}"
            f"  GPIO{pines:<6}  canales {canales:<4}"
            f"  bornera {cfg['bornera']}{nota}"
        )

    lineas += ["", f"  {NEGRITA}LUMINARIAS EXTERIORES{NORMAL}"
                   f"{GRIS}   LED directos al GPIO, encendido manual{NORMAL}"]
    for nombre, cfg in config.LUMINARIAS.items():
        on = s.luminarias.get(nombre, False)
        marca = f"{AMARILLO}[ON ]{NORMAL}" if on else f"{GRIS}[off]{NORMAL}"
        lineas.append(
            f"    {marca} {nombre}  {cfg['etiqueta']:<22}"
            f"  GPIO{cfg['gpio']:<3}  pin {cfg['pin_fisico']}"
            f"  ({cfg['senal']})"
        )

    lineas += ["", f"  {NEGRITA}SEMAFOROS{NORMAL}"]
    for nombre, cfg in config.SEMAFOROS.items():
        luces = s.semaforos.get(nombre, {})
        piezas = []
        for color, tinta in (("rojo", ROJO), ("amarillo", AMARILLO), ("verde", VERDE)):
            if luces.get(color):
                piezas.append(f"{tinta}({color[0].upper()}){NORMAL}")
            else:
                piezas.append(f"{GRIS}( ){NORMAL}")
        lineas.append(
            f"    {nombre} {cfg['bornera']}  {' '.join(piezas)}   "
            f"{GRIS}{cfg['etiqueta']}{NORMAL}"
        )

    lineas += ["", f"  {NEGRITA}NIVEL DE ESTANQUES{NORMAL} (VL53L0X, los 4 en 0x29)"]
    for lectura in s.lecturas:
        prefijo = (f"    ch{lectura.canal} {lectura.bornera:<4} "
                   f"{lectura.etiqueta:<11}")
        if not lectura.conectado:
            lineas.append(f"{prefijo}  {GRIS}DESCONECTADO{NORMAL}")
            continue
        if not lectura.ok:
            lineas.append(
                f"{prefijo}  {ROJO}sin lectura{NORMAL}  {GRIS}{lectura.error}{NORMAL}"
            )
            continue
        pct = lectura.nivel_pct or 0.0
        tinta = VERDE
        if pct >= config.NIVEL_CRITICO_PCT:
            tinta = ROJO
        elif pct >= config.NIVEL_ALERTA_PCT:
            tinta = AMARILLO
        lineas.append(
            f"    ch{lectura.canal} {lectura.bornera:<4} {lectura.etiqueta:<11}"
            f"  {lectura.distancia_mm:>4} mm  {tinta}{barra(pct)}{NORMAL}"
            f" {pct:5.1f} %"
        )

    lineas += ["", f"  {NEGRITA}TIRAS LED{NORMAL} "
                   f"{GRIS}({s.tira_velocidad_ms} ms/LED; cada tira con su "
                   f"color){NORMAL}"]
    for nombre, cfg in config.TIRAS.items():
        pixeles = s.tiras.get(nombre, [])
        dibujo = "".join("#" if any(p) else "." for p in pixeles)
        n = s.tira_n_leds.get(nombre, len(pixeles))
        color = s.tira_color_nombre.get(nombre, "?")
        lineas.append(
            f"    {nombre} GPIO{cfg['gpio']:<2} {cfg['bornera']:<4} "
            f"{n:>3} LED {color:<8} [{dibujo}]"
        )

    lineas += ["", f"  {NEGRITA}ULTIMOS EVENTOS{NORMAL}"]
    for linea in s.log[-6:]:
        lineas.append(f"    {GRIS}{linea}{NORMAL}")

    sys.stdout.write("\n".join(lineas) + "\n")
    sys.stdout.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prueba por consola del cuadrante 3")
    parser.add_argument("--simular", action="store_true")
    parser.add_argument("--solo-sensores", action="store_true",
                        help="lee los sensores sin mover las bombas")
    parser.add_argument("--sin-sensores", action="store_true",
                        help="en simulacion, reporta los 4 canales como "
                             "desconectados")
    parser.add_argument("--luminarias", action="store_true",
                        help="enciende las luminarias exteriores al arrancar "
                             "(sin GUI no hay forma de darles el clic)")
    parser.add_argument("-v", "--verboso", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verboso else logging.WARNING,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    from controlador import Controlador

    controlador = Controlador(
        forzar_simulacion=args.simular,
        canales_simulados=[] if args.sin_sensores else None,
    )
    controlador.prueba_de_luces()
    if args.luminarias:
        for nombre in config.LUMINARIAS:
            controlador.set_luminaria(nombre, True)
    controlador.iniciar_sensores()
    controlador.iniciar_semaforos()
    controlador.iniciar_tiras()
    if not args.solo_sensores:
        controlador.iniciar_secuencia()

    try:
        while True:
            pintar(controlador.compartido.instantanea())
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
    finally:
        controlador.cerrar()
        print("Bombas y semaforos apagados, GPIO liberado.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
