#!/usr/bin/env python3
"""Diagnostico de bajo nivel del VL53L0X en canal 2 (J20, Estanque 1).

NO usa adafruit_vl53l0x (ese driver tiene el loop sin timeout que cuelga
main.py). Habla directo por I2C a traves del mux, con timeout duro en cada
operacion via signal.alarm, para no poder quedar colgado como el main.

Lee el MODEL_ID (deberia ser 0xEE), lee RESULT_INTERRUPT_STATUS varias
veces para ver que valor real trae, e intenta un reset por software
(registro SOFT_RESET) para ver si destraba el sensor sin tocar nada fisico.
"""
import signal
import sys
import time

import board
import busio
import adafruit_tca9548a

ADDR = 0x29
REG_MODEL_ID = 0xC0
REG_INTERRUPT_STATUS = 0x13
REG_SOFT_RESET = 0xBF


class Timeout(Exception):
    pass


def _handler(signum, frame):
    raise Timeout()


signal.signal(signal.SIGALRM, _handler)


def leer(bus, reg, n=1, timeout_s=2):
    buf = bytearray(n)
    signal.alarm(timeout_s)
    try:
        bus.writeto(ADDR, bytes([reg]))
        bus.readfrom_into(ADDR, buf)
    finally:
        signal.alarm(0)
    return buf


def escribir(bus, reg, val, timeout_s=2):
    signal.alarm(timeout_s)
    try:
        bus.writeto(ADDR, bytes([reg, val]))
    finally:
        signal.alarm(0)


def main():
    i2c = busio.I2C(board.SCL, board.SDA)
    mux = adafruit_tca9548a.TCA9548A(i2c, address=0x70)
    bus = mux[2]

    while not bus.try_lock():
        pass
    try:
        print("=== Lectura directa, sin el driver completo ===")
        try:
            model = leer(bus, REG_MODEL_ID)
            print(f"MODEL_ID (0xC0) = 0x{model[0]:02X}  (esperado 0xEE)")
        except Timeout:
            print("TIMEOUT leyendo MODEL_ID -- no contesta ni a esto.")
            return 1
        except Exception as exc:
            print(f"ERROR leyendo MODEL_ID: {type(exc).__name__}: {exc}")
            return 1

        print("\n=== RESULT_INTERRUPT_STATUS, 5 lecturas seguidas ===")
        try:
            for i in range(5):
                status = leer(bus, REG_INTERRUPT_STATUS)
                print(f"  intento {i}: 0x{status[0]:02X}  "
                      f"(bits 0x07 = {status[0] & 0x07})")
                time.sleep(0.2)
        except Timeout:
            print("TIMEOUT leyendo RESULT_INTERRUPT_STATUS.")
        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}")

        print("\n=== Reset por software (SOFT_RESET, 0xBF) ===")
        try:
            escribir(bus, REG_SOFT_RESET, 0x00)
            time.sleep(0.1)
            escribir(bus, REG_SOFT_RESET, 0x01)
            time.sleep(0.1)
            print("Reset enviado OK.")
        except Timeout:
            print("TIMEOUT enviando el reset.")
            return 1
        except Exception as exc:
            print(f"ERROR en el reset: {type(exc).__name__}: {exc}")
            return 1

        print("\n=== Releyendo MODEL_ID e INTERRUPT_STATUS tras el reset ===")
        try:
            model = leer(bus, REG_MODEL_ID)
            print(f"MODEL_ID tras reset = 0x{model[0]:02X}")
            for i in range(5):
                status = leer(bus, REG_INTERRUPT_STATUS)
                print(f"  intento {i}: 0x{status[0]:02X}")
                time.sleep(0.2)
        except Timeout:
            print("TIMEOUT tras el reset.")
            return 1
        except Exception as exc:
            print(f"ERROR tras reset: {type(exc).__name__}: {exc}")
            return 1
    finally:
        try:
            bus.unlock()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
