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
import concurrent.futures
import statistics

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
    0: (128.0, 94.25),   # Estanque 2 (J18, P2) - 101mm = 80.0%, Lleno = 94.25mm
    1: (85.0,  51.25),   # Estanque 4 (J19, P4) - 58mm = 80.0%, Lleno = 51.25mm
    2: (150.0, 116.25),  # Estanque 1 (J20, P1) - Bypass
    3: (60.0,  38.0),    # Estanque 3 (J21, P3) - 42mm = 81.8%, Lleno = 38mm
}

CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibracion_estanques.json")
if os.path.exists(CALIB_FILE):
    try:
        import json
        with open(CALIB_FILE, "r") as f:
            _calib = json.load(f)
            for k, v in _calib.items():
                c = int(k)
                if c in GEOMETRIA_CANALES:
                    vac = float(v.get("vacio", GEOMETRIA_CANALES[c][0]))
                    lle = float(v.get("lleno", GEOMETRIA_CANALES[c][1]))
                    GEOMETRIA_CANALES[c] = (vac, lle)
    except Exception:
        pass

DIST_VACIO_MM = 60   # Fallback generico
DIST_LLENO_MM = 46

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

    # Parche de seguridad para Adafruit VL53L0X:
    # Previene el bucle infinito en _perform_single_ref_calibration
    if hasattr(VL53L0X, "_perform_single_ref_calibration"):
        def _safe_perform_single_ref_calibration(self, vhv_init_byte):
            self._write_u8(0x00, 0x01 | vhv_init_byte)
            t_inicio = time.monotonic()
            while (self._read_u8(0x13) & 0x07) == 0:
                if time.monotonic() - t_inicio > 0.35:
                    raise RuntimeError("Timeout en calibracion interna VL53L0X")
                time.sleep(0.005)
        VL53L0X._perform_single_ref_calibration = _safe_perform_single_ref_calibration

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
            sensor = VL53L0X(mux[c])
            if hasattr(sensor, "io_timeout_s"):
                sensor.io_timeout_s = 0.25
            if hasattr(sensor, "measurement_timing_budget"):
                try:
                    sensor.measurement_timing_budget = 33000
                except Exception:
                    pass
            sensores[c] = sensor
        except Exception:
            sensores[c] = None
            # Si un canal falla, aislarlo inmediatamente reseteando el MUX para no colgar los siguientes canales
            try:
                GPIO.output(17, GPIO.LOW)
                time.sleep(0.02)
                GPIO.output(17, GPIO.HIGH)
                time.sleep(0.05)
                i2c = busio.I2C(board.SCL, board.SDA)
                mux = adafruit_tca9548a.TCA9548A(i2c, address=0x70)
            except Exception:
                pass

    HARDWARE_REAL = True
except Exception:
    HARDWARE_REAL = False


def calcular_pct(dist_mm, canal=None, dist_base=None):
    """Convierte distancia en mm a porcentaje de nivel (0% a 100%) segun geometria del estanque y auto-tara."""
    if dist_mm >= 8000 or dist_mm <= 0:
        return 0.0
    if dist_base is not None:
        vacio = dist_base
        if canal in GEOMETRIA_CANALES:
            _, lleno = GEOMETRIA_CANALES[canal]
        else:
            lleno = DIST_LLENO_MM
    elif canal in GEOMETRIA_CANALES:
        vacio, lleno = GEOMETRIA_CANALES[canal]
    else:
        vacio, lleno = DIST_VACIO_MM, DIST_LLENO_MM

    # Zona muerta de 3 mm contra ruido del sensor en reposo
    if dist_mm >= (vacio - 3):
        return 0.0
    if dist_mm <= lleno:
        return 100.0
    rango = vacio - lleno
    if rango <= 0:
        return 0.0
    return max(0.0, min(100.0, ((vacio - dist_mm) / rango) * 100.0))


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
    print(f"{BOLD}{CYAN}Iniciando Test Visual de Sensores con Auto-Tara de Linea Base...{RESET}")
    time.sleep(0.4)

    # Distancias base de reposo (Auto-Tara al iniciar)
    distancias_base = {
        0: GEOMETRIA_CANALES[0][0],  # 128 mm (Estanque 2)
        1: GEOMETRIA_CANALES[1][0],  # 85 mm  (Estanque 4)
        2: GEOMETRIA_CANALES[2][0],  # 150 mm (Estanque 1 / Bypass)
        3: GEOMETRIA_CANALES[3][0],  # 60 mm  (Estanque 3)
    }

    if HARDWARE_REAL:
        for c, s in sensores.items():
            if s is not None and c != 2:
                try:
                    d = s.range
                    # Solo auto-tarar si la lectura inicial está cerca del vacío nominal (+- 8 mm)
                    if abs(d - GEOMETRIA_CANALES[c][0]) <= 8:
                        distancias_base[c] = d
                except Exception:
                    pass

    distancias_prev = {0: 50, 1: 50, 2: 50, 3: 50}
    sim_dist = {0: 50, 1: 50, 2: 50, 3: 50}
    sim_dir = {0: -2, 1: -1, 2: -3, 3: -2}
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="test_range")

    try:
        while True:
            lineas = []
            ahora = time.strftime("%H:%M:%S")

            lineas.append(f"{BOLD}{WHITE}+=========================================================================================+{RESET}")
            lineas.append(f"{BOLD}{WHITE}|   {CYAN}TEST EN TIEMPO REAL: COMPROBACION FISICA DE SENSORES ToF (VL53L0X)  {WHITE}[{ahora}]  |{RESET}")
            lineas.append(f"{BOLD}{WHITE}|   {YELLOW}Acerca o aleja el dedo para ver como cambian los mm y la barra al instante.         {WHITE}|{RESET}")
            lineas.append(f"{BOLD}{WHITE}+=========================================================================================+{RESET}")

            modo_str = f"{GREEN}[HARDWARE REAL I2C ACTIVO]{RESET}" if HARDWARE_REAL else f"{YELLOW}[MODO DEMO / SIMULACION]{RESET}"
            lineas.append(f" Estado General: {modo_str} | Auto-Tara: Reposo={distancias_base[0]}/{distancias_base[1]}/{distancias_base[3]} mm")
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
                            fut = executor.submit(getattr, sensor, "range")
                            d = fut.result(timeout=0.35)
                            if 0 < d < 2000:
                                dist_mm = d
                            else:
                                dist_mm = 8190
                                estado_str = f"{YELLOW}[!] FUERA DE RANGO{RESET}"
                        except concurrent.futures.TimeoutError:
                            dist_mm = 8190
                            estado_str = f"{RED}[X] TIMEOUT I2C{RESET}"
                            try:
                                executor.shutdown(wait=False)
                            except Exception:
                                pass
                            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="test_range")
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
                    pct = calcular_pct(dist_mm, canal=c, dist_base=distancias_base[c])
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

                    # Diagnóstico inmediato del dedo usando la distancia base calibrada
                    base_estanque = distancias_base[c]
                    if dist_mm <= 22:
                        estado_str = f"{RED}{BOLD}[!] DEDO MUY CERCA / TOPE{RESET}"
                    elif dist_mm <= 35:
                        estado_str = f"{GREEN}{BOLD}>>> DEDO DETECTADO!{RESET}"
                    elif dist_mm <= (base_estanque - 6):
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
