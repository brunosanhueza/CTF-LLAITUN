#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 TEST INTERACTIVO EN TIEMPO REAL: BANCO DE SENSORES ToF (VL53L0X)
 Sector 3 - CTF Aguas del Valle
==============================================================================
 Diseñado específicamente para comprobar físicamente los sensores con la mano/dedo.
 - Tasa de refresco ultra-rápida (10 Hz = cada 100 ms).
 - Sin retrasos de promedio ni lag: respuesta instantánea al movimiento del dedo.
 - Pantalla fija con barras de progreso estilo VU-Meter e indicadores en color.
 - Compatible con Raspberry Pi (I2C Real) y PC (Modo Simulación).
==============================================================================
"""

import sys
import time
import os

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Configuración de Mapeo Físico
CANALES_MAPA = [
    {"ch": 2, "estanque": "Estanque 1", "bornera": "J20", "bomba": "P1"},
    {"ch": 0, "estanque": "Estanque 2", "bornera": "J18", "bomba": "P2"},
    {"ch": 3, "estanque": "Estanque 3", "bornera": "J21", "bomba": "P3"},
    {"ch": 1, "estanque": "Estanque 4", "bornera": "J19", "bomba": "P4"},
]

# Configuración de Geometría por Estanque
GEOMETRIA_CANALES = {
    0: (125, 20),   # Estanque 2 (J18, P2) - Vacio: 125mm, Lleno: 20mm
    1: (45, 15),    # Estanque 4 (J19, P4) - Vacio: 45mm,  Lleno: 15mm
    2: (150, 20),   # Estanque 1 (J20, P1) - Vacio: 150mm, Lleno: 20mm (Sensor dañado)
    3: (65, 20),    # Estanque 3 (J21, P3) - Vacio: 65mm,  Lleno: 20mm
}

DIST_VACIO_MM = 50   # Fallback generico
DIST_LLENO_MM = 20

# Colores ANSI
RESET = "\033[0m"
BOLD = "\033[1m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
GRAY = "\033[90m"
WHITE = "\033[97m"
CLEAR_SCREEN = "\033[2J\033[H"

# Detección de Hardware
HARDWARE_REAL = False
sensores = {0: None, 1: None, 2: None, 3: None}
mux = None

try:
    import board
    import busio
    import adafruit_tca9548a
    from adafruit_vl53l0x import VL53L0X
    import RPi.GPIO as GPIO

    # Reset fisico del multiplexor TCA9548A mediante GPIO 17
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(17, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.output(17, GPIO.LOW)
    time.sleep(0.02)
    GPIO.output(17, GPIO.HIGH)
    time.sleep(0.05)

    i2c = busio.I2C(board.SCL, board.SDA)
    mux = adafruit_tca9548a.TCA9548A(i2c, address=0x70)

    for item in CANALES_MAPA:
        c = item["ch"]
        # El Canal 2 (J20, Estanque 1) se omite porque su sensor cuelga el bus
        if c == 2 and "--con-canal-2" not in sys.argv:
            sensores[c] = None
            continue
        try:
            try:
                sensor = VL53L0X(mux[c], io_timeout_s=0.5)
            except TypeError:
                sensor = VL53L0X(mux[c])
            if hasattr(sensor, "measurement_timing_budget"):
                try:
                    sensor.measurement_timing_budget = 33000
                except Exception:
                    pass
            sensores[c] = sensor
        except Exception:
            sensores[c] = None

    HARDWARE_REAL = True
except Exception:
    HARDWARE_REAL = False


def calcular_pct(dist_mm, canal=None):
    """Convierte distancia en mm a porcentaje de nivel (0% a 100%) segun geometria del estanque."""
    if dist_mm >= 8000 or dist_mm <= 0:
        return 0.0
    if canal in GEOMETRIA_CANALES:
        vacio, lleno = GEOMETRIA_CANALES[canal]
    else:
        vacio, lleno = DIST_VACIO_MM, DIST_LLENO_MM
    if dist_mm >= vacio:
        return 0.0
    if dist_mm <= lleno:
        return 100.0
    return max(0.0, min(100.0, ((vacio - dist_mm) / (vacio - lleno)) * 100.0))


def generar_barra(pct, ancho=22):
    """Genera una barra gráfica ASCII en color según el nivel."""
    llenos = int(round((pct / 100.0) * ancho))
    llenos = max(0, min(ancho, llenos))
    vacios = ancho - llenos

    if pct >= 80:
        color_barra = RED
    elif pct >= 40:
        color_barra = GREEN
    elif pct > 10:
        color_barra = YELLOW
    else:
        color_barra = GRAY

    barra = f"{color_barra}{'#' * llenos}{GRAY}{'.' * vacios}{RESET}"
    return barra


def main():
    print(CLEAR_SCREEN, end="")
    print(f"{BOLD}{CYAN}Iniciando Test Visual de Sensores...{RESET}")
    time.sleep(0.4)

    distancias_prev = {0: 50, 1: 50, 2: 50, 3: 50}
    sim_dist = {0: 50, 1: 50, 2: 50, 3: 50}
    sim_dir = {0: -2, 1: -1, 2: -3, 3: -2}

    try:
        while True:
            lineas = []
            ahora = time.strftime("%H:%M:%S")

            lineas.append(f"{BOLD}{WHITE}+=========================================================================================+{RESET}")
            lineas.append(f"{BOLD}{WHITE}|   {CYAN}TEST EN TIEMPO REAL: COMPROBACION FISICA DE SENSORES ToF (VL53L0X)  {WHITE}[{ahora}]  |{RESET}")
            lineas.append(f"{BOLD}{WHITE}|   {YELLOW}Acerca o aleja el dedo para ver como cambian los mm y la barra al instante.         {WHITE}|{RESET}")
            lineas.append(f"{BOLD}{WHITE}+=========================================================================================+{RESET}")

            modo_str = f"{GREEN}[HARDWARE REAL I2C ACTIVO]{RESET}" if HARDWARE_REAL else f"{YELLOW}[MODO DEMO / SIMULACION]{RESET}"
            lineas.append(f" Estado General: {modo_str} | Calibracion: {DIST_LLENO_MM}mm = 100% (Tope) | {DIST_VACIO_MM}mm = 0% (Libre)")
            lineas.append(f"{GRAY}-----------------------------------------------------------------------------------------{RESET}")
            lineas.append(f"{BOLD}{'CANAL / SENSOR':<22} {'DIST':<8} {'NIVEL':<8} {'GRAFICA EN TIEMPO REAL':<32} {'ESTADO SENSOR'}{RESET}")
            lineas.append(f"{GRAY}-----------------------------------------------------------------------------------------{RESET}")

            for item in CANALES_MAPA:
                c = item["ch"]
                est = item["estanque"]
                born = item["bornera"]
                p = item["bomba"]

                dist_mm = 50
                estado_str = ""

                if HARDWARE_REAL:
                    sensor = sensores.get(c)
                    if sensor is None:
                        dist_mm = 8190
                        if c == 2:
                            estado_str = f"{YELLOW}[~] BYPASS / SENSOR DEFECTUOSO{RESET}"
                        else:
                            estado_str = f"{RED}[X] NO DETECTADO / DANIADO{RESET}"
                    else:
                        try:
                            d = sensor.range
                            if 0 < d < 2000:
                                dist_mm = d
                            else:
                                dist_mm = 8190
                                estado_str = f"{YELLOW}[!] FUERA DE RANGO{RESET}"
                        except Exception:
                            dist_mm = 8190
                            estado_str = f"{RED}[X] ERROR I2C{RESET}"
                else:
                    # En modo simulación variamos automáticamente para mostrar el efecto visual
                    sim_dist[c] += sim_dir[c]
                    if sim_dist[c] <= 18:
                        sim_dist[c] = 18
                        sim_dir[c] = 2
                    elif sim_dist[c] >= 52:
                        sim_dist[c] = 52
                        sim_dir[c] = -2
                    dist_mm = sim_dist[c]

                # Si está midiendo normalmente
                if dist_mm < 8000:
                    pct = calcular_pct(dist_mm, canal=c)
                    barra = generar_barra(pct, ancho=20)

                    # Indicador de tendencia (subiendo o bajando)
                    delta = dist_mm - distancias_prev[c]
                    if delta < -1:
                        flecha = f"{GREEN}(v Acercando){RESET}"
                    elif delta > 1:
                        flecha = f"{CYAN}(^ Alejando) {RESET}"
                    else:
                        flecha = f"{GRAY}(- Estable)  {RESET}"
                    distancias_prev[c] = dist_mm

                    # Diagnóstico inmediato del dedo
                    if dist_mm <= 22:
                        estado_str = f"{RED}{BOLD}[!] DEDO MUY CERCA / TOPE{RESET}"
                    elif dist_mm <= 35:
                        estado_str = f"{GREEN}{BOLD}>>> DEDO DETECTADO!{RESET}"
                    elif dist_mm <= 45:
                        estado_str = f"{YELLOW}[~] Obstaculo cerca{RESET}"
                    else:
                        estado_str = f"{GRAY}[ ] Libre / Sin dedo{RESET}"

                    etiqueta = f"{BOLD}{est}{RESET} ({born}|{p})"
                    lineas.append(f" {etiqueta:<28} {dist_mm:3d} mm   {pct:5.1f}%  [{barra}]  {estado_str} {flecha}")
                else:
                    barra = f"{GRAY}{'.' * 20}{RESET}"
                    etiqueta = f"{BOLD}{est}{RESET} ({born}|{p})"
                    lineas.append(f" {etiqueta:<28}  --- mm    0.0%  [{barra}]  {estado_str}")

            lineas.append(f"{GRAY}-----------------------------------------------------------------------------------------{RESET}")
            lineas.append(f" {BOLD}Consejo practico:{RESET} Coloca la yema de tu dedo a 2 o 3 cm sobre la bornera correspondiente.")
            lineas.append(f" {GRAY}Presiona {BOLD}Ctrl + C{RESET}{GRAY} para detener la prueba.{RESET}")

            # Imprime todo de un solo golpe para evitar parpadeos
            salida = CLEAR_SCREEN + "\n".join(lineas) + "\n"
            sys.stdout.write(salida)
            sys.stdout.flush()

            time.sleep(0.1)  # 10 lecturas por segundo (100 ms) -> Respuesta instantánea

    except KeyboardInterrupt:
        print(f"\n\n{GREEN}[OK] Prueba finalizada correctamente.{RESET}\n")


if __name__ == "__main__":
    main()
