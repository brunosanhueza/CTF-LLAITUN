#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
==============================================================================
 ASISTENTE DE CALIBRACIÓN DE PRECISIÓN: SENSORES ToF (VL53L0X)
 Sector 3 - CTF Aguas del Valle
==============================================================================
 Guía paso a paso para calibrar el rango útil (Vacío y Lleno) de cada estanque.
 - Toma ráfagas de 30 muestras con filtro de mediana para descartar ruido.
 - Muestra la desviación estándar y el ruido óptico en milímetros.
 - Genera/actualiza automáticamente el archivo 'calibracion_estanques.json'.
==============================================================================
"""

import sys
import time
import os
import json
import statistics

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibracion_estanques.json")

# Mapa de estanques según borneras físicas
ESTANQUES = [
    {"canal": 0, "nombre": "Estanque 2", "bornera": "J18", "bomba": "P2", "default_vacio": 128, "default_lleno": 46},
    {"canal": 3, "nombre": "Estanque 3", "bornera": "J21", "bomba": "P3", "default_vacio": 60,  "default_lleno": 46},
    {"canal": 1, "nombre": "Estanque 4", "bornera": "J19", "bomba": "P4", "default_vacio": 85,  "default_lleno": 46},
    {"canal": 2, "nombre": "Estanque 1", "bornera": "J20", "bomba": "P1", "default_vacio": 150, "default_lleno": 46, "bypass": True},
]

# Inicialización de hardware
HARDWARE_REAL = False
sensores = {}
mux = None

try:
    import board
    import busio
    import adafruit_tca9548a
    from adafruit_vl53l0x import VL53L0X
    import RPi.GPIO as GPIO

    # Reset del TCA9548A por GPIO 17
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(17, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.output(17, GPIO.LOW)
    time.sleep(0.02)
    GPIO.output(17, GPIO.HIGH)
    time.sleep(0.05)

    i2c = busio.I2C(board.SCL, board.SDA)
    mux = adafruit_tca9548a.TCA9548A(i2c, address=0x70)

    for item in ESTANQUES:
        c = item["canal"]
        if item.get("bypass"):
            sensores[c] = None
            continue
        try:
            s = VL53L0X(mux[c])
            # High Accuracy: aumentamos el timing budget a 100 ms para máxima precisión (ruido < 1 mm)
            if hasattr(s, "measurement_timing_budget"):
                s.measurement_timing_budget = 100000
            sensores[c] = s
        except Exception:
            sensores[c] = None

    HARDWARE_REAL = True
except Exception:
    HARDWARE_REAL = False


def cargar_calibracion():
    if os.path.exists(CALIB_FILE):
        try:
            with open(CALIB_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # Por defecto
    return {
        "0": {"vacio": 128, "lleno": 46, "estanque": "Estanque 2 (J18)"},
        "1": {"vacio": 85,  "lleno": 46, "estanque": "Estanque 4 (J19)"},
        "2": {"vacio": 150, "lleno": 46, "estanque": "Estanque 1 (J20 - Bypass)"},
        "3": {"vacio": 60,  "lleno": 46, "estanque": "Estanque 3 (J21)"},
    }


def guardar_calibracion(data):
    with open(CALIB_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print(f"\n[+] Calibracion guardada exitosamente en:\n    {CALIB_FILE}\n")


def tomar_rafaga_muestras(canal, n_muestras=30, delay_s=0.08):
    """Toma N muestras consecutivas y devuelve la mediana y desviación estándar."""
    muestras = []
    sensor = sensores.get(canal)

    print(f"    Midiendo {n_muestras} muestras de alta precision", end="", flush=True)
    for _ in range(n_muestras):
        if HARDWARE_REAL and sensor is not None:
            try:
                dist = sensor.range
                if 0 < dist < 8000:
                    muestras.append(dist)
            except Exception:
                pass
        else:
            # Modo Simulación para pruebas
            muestras.append(50)
        print(".", end="", flush=True)
        time.sleep(delay_s)
    print(" OK!")

    if not muestras:
        return None, None, []

    mediana = int(round(statistics.median(muestras)))
    stdev = round(statistics.stdev(muestras), 2) if len(muestras) > 1 else 0.0
    return mediana, stdev, muestras


def calibrar_estanque(item, data_calib):
    c = item["canal"]
    nom = item["nombre"]
    born = item["bornera"]
    p = item["bomba"]

    print("\n" + "="*75)
    print(f"[*] CALIBRANDO {nom} (Canal {c} | Bornera {born} | Bomba {p})")
    print("="*75)

    if item.get("bypass"):
        print(f" [!] Este canal corresponde al sensor defectuoso en hardware (Estanque 1).")
        print(f"     Se mantiene en BYPASS con Vacio=150 mm y Lleno=20 mm de forma virtual.")
        data_calib[str(c)] = {"vacio": 150, "lleno": 20, "estanque": f"{nom} ({born})"}
        input("\nPresiona Enter para continuar...")
        return

    sensor = sensores.get(c)
    if HARDWARE_REAL and sensor is None:
        print(f" [X] Error: El sensor en canal {c} ({born}) no responde por I2C.")
        input("\nPresiona Enter para continuar...")
        return

    # Paso 1: Medir Vacío (Fondo del estanque)
    print("\n[PASO 1: NIVEL VACIO / REPOSO]")
    print(f"  -> Asegurate de que el {nom} este sin agua o con el nivel en reposo.")
    print(f"  -> No coloques ningun obstaculo ni la mano frente al sensor.")
    input("  -> Presiona [ENTER] cuando el estanque este listo para medir reposo...")

    vacio_med, stdev_vacio, m_vacio = tomar_rafaga_muestras(c)
    if vacio_med is None:
        print("  [!] Error: No se recibieron lecturas validas del sensor.")
        return

    print(f"  [+] Medida de Vacío obtenida: {vacio_med} mm (Ruido/Dispersion: ±{stdev_vacio} mm)")

    # Paso 2: Medir Lleno (Nivel máximo / Alarma)
    print("\n[PASO 2: NIVEL LLENO / REBALSE]")
    print(f"  Tienes dos opciones:")
    print(f"    a) Llenar el estanque con agua / colocar el flotador o la mano a la altura maxima deseada.")
    print(f"    b) O escribir manualmente los milímetros de seguridad (Recomendado: 15 a 20 mm).")
    opc = input(f"  ¿Deseas medir con la mano/agua ahora? [s/N]: ").strip().lower()

    if opc in ("s", "si", "y", "yes"):
        input(f"  -> Coloca el objeto/nivel a la altura maxima y presiona [ENTER]...")
        lleno_med, stdev_lleno, _ = tomar_rafaga_muestras(c)
        if lleno_med is None:
            lleno_med = item["default_lleno"]
            print(f"  [!] Falló la medición; usando valor por defecto: {lleno_med} mm")
        else:
            print(f"  [+] Medida de Lleno obtenida: {lleno_med} mm (Ruido: ±{stdev_lleno} mm)")
    else:
        resp = input(f"  Introduce distancia de lleno en mm [Por defecto {item['default_lleno']} mm]: ").strip()
        try:
            lleno_med = int(resp) if resp else item["default_lleno"]
        except ValueError:
            lleno_med = item["default_lleno"]

    # Validación
    if lleno_med >= vacio_med:
        print(f"\n  [!] ADVERTENCIA: Lleno ({lleno_med} mm) debe ser MENOR que Vacío ({vacio_med} mm).")
        print(f"      (El sensor mira hacia abajo: mas agua = menor distancia al sensor).")
        print(f"      Ajustando lleno a 20 mm por seguridad.")
        lleno_med = 20

    rango = vacio_med - lleno_med
    print("\n" + "-"*60)
    print(f"  RESUMEN DE CALIBRACION PARA {nom}:")
    print(f"   * Distancia en Vacio (0.0%):  {vacio_med} mm")
    print(f"   * Distancia en Lleno (100%):  {lleno_med} mm")
    print(f"   * Rango de medicion util:     {rango} mm ({rango/10.0:.1f} cm)")
    print(f"   * Resolucion estimada:        ~{100.0/rango:.2f}% por milimetro")
    print("-"*60)

    data_calib[str(c)] = {
        "vacio": vacio_med,
        "lleno": lleno_med,
        "estanque": f"{nom} ({born})",
        "ruido_stdev_mm": stdev_vacio
    }


def main():
    data_calib = cargar_calibracion()

    while True:
        print("\n" + "="*75)
        print("     ASISTENTE DE CALIBRACION Y PRECISION DE SENSORES ToF (VL53L0X)")
        print("="*75)
        modo_txt = "HARDWARE REAL I2C DETECTADO" if HARDWARE_REAL else "MODO DEMO / SIMULACION (Sin Raspberry)"
        print(f" Estado: [{modo_txt}]")
        print(" Estanques configurados actualmente:")
        for item in ESTANQUES:
            c_str = str(item["canal"])
            cur = data_calib.get(c_str, {"vacio": item["default_vacio"], "lleno": item["default_lleno"]})
            bp = " [BYPASS]" if item.get("bypass") else ""
            print(f"   [{item['canal']}] {item['nombre']} ({item['bornera']}|{item['bomba']}){bp}: Vacio={cur['vacio']} mm | Lleno={cur['lleno']} mm")
        
        print("\n Opciones:")
        print("   [0] Calibrar Estanque 2 (Canal 0, Bornera J18, Bomba P2)")
        print("   [1] Calibrar Estanque 4 (Canal 1, Bornera J19, Bomba P4)")
        print("   [3] Calibrar Estanque 3 (Canal 3, Bornera J21, Bomba P3)")
        print("   [A] Calibrar TODOS los estanques en secuencia guiada")
        print("   [G] Guardar y Salir")
        print("   [Q] Salir sin guardar")
        print("="*75)

        opc = input(" Selecciona una opcion: ").strip().lower()

        if opc in ("q", "salir", "exit"):
            print("Saliendo sin guardar cambios adicionales.")
            break
        elif opc in ("g", "guardar", "save"):
            guardar_calibracion(data_calib)
            break
        elif opc == "a":
            for it in [ESTANQUES[0], ESTANQUES[1], ESTANQUES[2]]:
                calibrar_estanque(it, data_calib)
            guardar_calibracion(data_calib)
            break
        elif opc in ("0", "1", "3"):
            canal_sel = int(opc)
            item_sel = next((it for it in ESTANQUES if it["canal"] == canal_sel), None)
            if item_sel:
                calibrar_estanque(item_sel, data_calib)
                guardar_calibracion(data_calib)
        else:
            print("Opcion no valida.")

if __name__ == "__main__":
    main()
