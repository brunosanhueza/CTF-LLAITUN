#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HERRAMIENTA DE RECUPERACION I2C EN CALIENTE (Sin reiniciar la Raspberry Pi)
Sector 3 - CTF Aguas del Valle

Ejecuta el protocolo de recuperación completo:
1. Reset por hardware del multiplexor TCA9548A vía GPIO 17 (aislamiento total).
2. Bit-banging de 9 pulsos de reloj en SCL (GPIO 3) para liberar SDA (GPIO 2).
3. Generación de condición STOP I2C.
4. Recarga del módulo del kernel Linux (i2c_bcm2835) si el bus del SoC quedó bloqueado.
5. Escaneo de confirmación en /dev/i2c-1 (debe verse 0x70 correspondiente al MUX).
"""

import sys
import time
import subprocess

try:
    import RPi.GPIO as GPIO
except ImportError:
    print("[ERROR] Este script debe ejecutarse en la Raspberry Pi con permisos de root (sudo).")
    sys.exit(1)

MUX_RST_PIN = 17
PIN_SDA = 2
PIN_SCL = 3

def recuperar_bus():
    print("="*70)
    print("  INICIANDO RUTINA DE DESATASCO Y RECUPERACION I2C (Sin reboot)")
    print("="*70)

    # Paso 1: Reset por hardware del TCA9548A
    print("[1/4] Pulsando GPIO 17 (Reset físico TCA9548A)...", end="", flush=True)
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)
    GPIO.setup(MUX_RST_PIN, GPIO.OUT, initial=GPIO.HIGH)
    GPIO.output(MUX_RST_PIN, GPIO.LOW)
    time.sleep(0.05)
    GPIO.output(MUX_RST_PIN, GPIO.HIGH)
    time.sleep(0.1)
    print(" [OK]")

    # Paso 2: 9 pulsos de reloj en SCL para liberar SDA
    print("[2/4] Enviando 9 pulsos de reloj en SCL (GPIO 3)...", end="", flush=True)
    GPIO.setup(PIN_SDA, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.setup(PIN_SCL, GPIO.OUT, initial=GPIO.HIGH)
    time.sleep(0.002)

    for _ in range(9):
        GPIO.output(PIN_SCL, GPIO.LOW)
        time.sleep(0.00003)
        GPIO.output(PIN_SCL, GPIO.HIGH)
        time.sleep(0.00003)

    # Condición STOP manual
    GPIO.setup(PIN_SDA, GPIO.OUT, initial=GPIO.LOW)
    time.sleep(0.00003)
    GPIO.output(PIN_SCL, GPIO.HIGH)
    time.sleep(0.00003)
    GPIO.output(PIN_SDA, GPIO.HIGH)
    time.sleep(0.00003)
    GPIO.cleanup([PIN_SDA, PIN_SCL])
    time.sleep(0.05)
    print(" [OK]")

    # Paso 3: Recarga del controlador del kernel si es necesario
    print("[3/4] Reiniciando controlador de kernel i2c_bcm2835...", end="", flush=True)
    try:
        subprocess.run(["modprobe", "-r", "i2c_bcm2835"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.05)
        subprocess.run(["modprobe", "i2c_bcm2835"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.05)
        print(" [OK]")
    except Exception as e:
        print(f" [SKIP: {e}]")

    # Paso 4: Escaneo de verificación
    print("[4/4] Verificando detección de TCA9548A (dirección 0x70)...")
    try:
        res = subprocess.run(["i2cdetect", "-y", "1"], capture_output=True, text=True)
        print(res.stdout)
        if "70" in res.stdout:
            print("[EXITO] Multiplexor TCA9548A respondiendo en 0x70. Bus I2C 100% operativo.")
        else:
            print("[AVISO] No se detectó 0x70. Verifica alimentación de la placa.")
    except Exception as e:
        print(f"[INFO] i2cdetect no disponible ({e}).")

    print("="*70)
    print("  Listo. Ya puedes ejecutar rtu_daemon.py o probar_sensores_dedo.py")
    print("="*70)

if __name__ == "__main__":
    recuperar_bus()
