#!/usr/bin/env python3
"""
Punto de entrada del cuadrante 3, con interfaz grafica (dashboard PyQt5).

QUE HACE ESTE ARCHIVO
    Es el arranque, y nada mas: lee los argumentos, arma el controlador, lanza
    los cuatro hilos de trabajo, abre la ventana y se asegura de que al salir
    todo quede apagado. La logica de verdad esta en los otros modulos.

    Si buscas COMO funciona algo, este no es el archivo: mira controlador.py
    (que orquesta) o secuencia.py (que decide).

ORDEN DE ARRANQUE, Y POR QUE ES ESE
    1. Controlador()        -> abre el hardware y deja TODO en estado seguro
    2. prueba_de_luces()    -> comprobacion de cableado, sincrona y antes de
                               que ningun hilo empiece a tocar los semaforos
    3. iniciar_*()          -> recien ahora arrancan los hilos
    4. Ventana + app.exec_()-> la interfaz toma el hilo principal
    5. controlador.cerrar() -> en un finally, pase lo que pase

USO
    python3 main.py                  # detecta el hardware automaticamente
    sudo -E python3 main.py          # en la Raspberry Pi, para las tiras LED
    python3 main.py --simular        # fuerza el simulador (desarrollo en PC)
    python3 main.py --sin-arranque   # abre la ventana sin mover las bombas
    python3 main.py --plc            # las bombas obedecen al PLC por Modbus,
                                      # no a la secuencia local de demostracion

POR QUE sudo -E EN LA RASPBERRY PI
    rpi_ws281x accede directo a DMA y PWM y necesita root. Los reles y los
    semaforos NO lo necesitan, porque RPi.GPIO entra por /dev/gpiomem: por eso
    sin sudo parece que "todo anda menos las tiras". El -E conserva DISPLAY y
    XAUTHORITY; sin el, sudo no logra abrir la ventana en el escritorio.

    Para probar sin interfaz grafica (por SSH):  python3 prueba_consola.py
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys

import config


def configurar_log(verboso: bool) -> None:
    """Log a la terminal. Ojo: la ventana tiene su propio registro de eventos.

    Los mensajes importantes para el operador se mandan ademas a la interfaz
    con EstadoCompartido.registrar(), porque si la aplicacion se lanza desde el
    escritorio nadie ve nunca esta salida.
    """
    logging.basicConfig(
        level=logging.DEBUG if verboso else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(name)-12s %(message)s",
        datefmt="%H:%M:%S",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=config.NOMBRE_CUADRANTE)
    parser.add_argument("--simular", action="store_true",
                        help="fuerza el simulador aunque haya hardware")
    parser.add_argument("--sin-arranque", action="store_true",
                        help="no lanza la secuencia al abrir la ventana")
    parser.add_argument("--plc", action="store_true",
                        help="las bombas obedecen al PLC por Modbus TCP "
                             "(config.PLC_IP) en vez de la secuencia local "
                             "de demostracion; para la maqueta en el CTF")
    parser.add_argument("--sin-prueba-luces", action="store_true",
                        help="omite la comprobacion inicial de los semaforos")
    parser.add_argument("--sin-sensores", action="store_true",
                        help="en simulacion, reporta los 4 canales como "
                             "desconectados (para probar la interfaz)")
    parser.add_argument("-v", "--verboso", action="store_true",
                        help="log de nivel DEBUG")
    args = parser.parse_args()

    configurar_log(args.verboso)
    log = logging.getLogger("main")

    # PyQt5 se importa aqui y no arriba para poder dar un mensaje util si falta,
    # en vez de un ImportError crudo apenas se ejecuta el archivo.
    try:
        from PyQt5 import QtCore, QtWidgets
    except ImportError:
        print(
            "PyQt5 no esta instalado.\n"
            "  Raspberry Pi OS / Debian:  sudo apt install -y python3-pyqt5\n"
            "  Otros:                     pip install PyQt5\n"
            "Para probar sin interfaz grafica:  python3 prueba_consola.py",
            file=sys.stderr,
        )
        return 1

    # Estos dos tambien se importan tarde, porque arrastran el HAL y este toca
    # hardware. Asi --help funciona sin abrir nada.
    from controlador import Controlador
    from dashboard import VentanaPrincipal

    # Construir el controlador ya deja reles y semaforos apagados.
    controlador = Controlador(
        forzar_simulacion=args.simular,
        canales_simulados=[] if args.sin_sensores else None,
    )

    # La prueba de luces va ANTES de los hilos, a proposito: si corriera despues,
    # el hilo de semaforos estaria peleando por las mismas salidas.
    if not args.sin_prueba_luces:
        controlador.prueba_de_luces()

    controlador.iniciar_sensores()
    controlador.iniciar_semaforos()   # secuencia de calle, corre para siempre
    controlador.iniciar_tiras()       # animacion de llenado
    if args.plc:
        controlador.iniciar_puente_plc()  # las bombas obedecen al PLC
    elif not args.sin_arranque:
        controlador.iniciar_secuencia()   # ciclo de demostracion local

    app = QtWidgets.QApplication(sys.argv)
    ventana = VentanaPrincipal(controlador)
    ventana.show()

    # Ctrl+C en la terminal cierra la ventana de forma ordenada.
    #
    # Hace falta el temporizador en vacio: mientras Qt esta dentro de exec_(),
    # el interprete de Python no ejecuta nada propio y las senales del sistema
    # quedan encoladas sin atenderse. Un QTimer que dispara cada 250 ms le
    # devuelve el control a Python lo suficiente para que vea el SIGINT.
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    latido = QtCore.QTimer()
    latido.timeout.connect(lambda: None)
    latido.start(250)

    try:
        codigo = app.exec_()          # bloquea hasta que se cierra la ventana
    finally:
        # En un finally para que las bombas queden apagadas incluso si la
        # interfaz revienta con una excepcion.
        controlador.cerrar()
    log.info("Aplicacion cerrada.")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
