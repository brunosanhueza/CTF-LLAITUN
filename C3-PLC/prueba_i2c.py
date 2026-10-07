#!/usr/bin/env python3
"""
Diagnostico del bus I2C: multiplexor TCA9548A y sensores VL53L0X.

NO usa el resto del proyecto, para separar un problema de cableado de uno del
software del cuadrante. Escanea el bus principal, abre los ocho canales del
multiplexor uno por uno y dice que encuentra en cada uno.

Uso:
    python3 prueba_i2c.py              # escanea los 8 canales
    python3 prueba_i2c.py --canal 0    # solo el canal 0, e intenta leer
    python3 prueba_i2c.py --leer       # intenta leer distancia en los que haya
"""

import argparse
import sys

MUX = 0x70
VL53L0X = 0x29


def nombre_conocido(direccion: int) -> str:
    return {
        0x70: "TCA9548A (el multiplexor)",
        0x29: "VL53L0X",
    }.get(direccion, "")


def main() -> int:
    p = argparse.ArgumentParser(description="Diagnostico I2C del cuadrante 3")
    p.add_argument("--canal", type=int, default=None,
                   help="revisar un solo canal (0 a 7)")
    p.add_argument("--mux", type=lambda x: int(x, 0), default=MUX,
                   help="direccion del multiplexor (por defecto 0x70)")
    p.add_argument("--leer", action="store_true",
                   help="intenta leer distancia de cada VL53L0X encontrado")
    args = p.parse_args()

    try:
        import board
        import busio
        import adafruit_tca9548a
    except ImportError as exc:
        print(f"ERROR: falta una biblioteca ({exc}).\n"
              "  sudo pip3 install --break-system-packages adafruit-blinka "
              "adafruit-circuitpython-tca9548a adafruit-circuitpython-vl53l0x",
              file=sys.stderr)
        return 1

    print("=" * 62)
    print("1. BUS I2C1 (GPIO2/GPIO3), sin tocar el multiplexor")
    print("=" * 62)
    i2c = busio.I2C(board.SCL, board.SDA)
    while not i2c.try_lock():
        pass
    try:
        encontrados = i2c.scan()
    finally:
        i2c.unlock()

    if not encontrados:
        print("  NADA. No responde ni el multiplexor.")
        print("  Revisar: dtparam=i2c_arm=on en config.txt, el cableado de")
        print("  SDA/SCL, la alimentacion de 3.3 V del modulo y GND comun.")
        return 1

    for direccion in encontrados:
        print(f"  0x{direccion:02X}  {nombre_conocido(direccion)}")

    if args.mux not in encontrados:
        print(f"\n  El multiplexor NO esta en 0x{args.mux:02X}.")
        print("  Revisar que A0/A1/A2 esten a GND, o pasar --mux con la")
        print("  direccion que si aparecio en la lista de arriba.")
        return 1

    print()
    print("=" * 62)
    print("2. CANALES DEL MULTIPLEXOR")
    print("=" * 62)
    tca = adafruit_tca9548a.TCA9548A(i2c, address=args.mux)
    borneras = {0: "J18", 1: "J19", 2: "J20", 3: "J21",
                4: "J22", 5: "J23", 6: "J24", 7: "J25"}
    canales = [args.canal] if args.canal is not None else range(8)

    hallados = []
    for canal in canales:
        bus = tca[canal]
        etiqueta = f"  canal {canal} ({borneras.get(canal, '?')})"
        try:
            if not bus.try_lock():
                print(f"{etiqueta}: no se pudo tomar el bus")
                continue
            try:
                try:
                    direcciones = bus.scan()
                except AttributeError:
                    # Versiones antiguas de adafruit_tca9548a no tienen scan()
                    # en el canal; el bus ya esta conmutado, asi que sirve el
                    # scan del bus padre.
                    direcciones = i2c.scan()
            finally:
                bus.unlock()
        except Exception as exc:
            print(f"{etiqueta}: ERROR {type(exc).__name__}: {exc}")
            continue

        otros = [d for d in direcciones if d != args.mux]
        if not otros:
            print(f"{etiqueta}: vacio")
            continue
        detalle = ", ".join(f"0x{d:02X} {nombre_conocido(d)}".strip()
                            for d in otros)
        print(f"{etiqueta}: {detalle}")
        if VL53L0X in otros:
            hallados.append(canal)

    print()
    if not hallados:
        print("No se encontro ningun VL53L0X (0x29) en ningun canal.")
        print("Revisar en la bornera: el orden es GND, SCL, SDA, 3V3.")
        print("Si el modulo trae pin XSHUT, debe estar en alto (o sin conectar,")
        print("porque casi todos traen pull-up); en bajo el sensor queda dormido.")
        return 1

    print(f"VL53L0X encontrado(s) en el/los canal(es): {hallados}")

    if args.leer:
        print()
        print("=" * 62)
        print("3. LECTURA DE DISTANCIA")
        print("=" * 62)
        try:
            from adafruit_vl53l0x import VL53L0X as Sensor
        except ImportError as exc:
            print(f"  falta adafruit-circuitpython-vl53l0x ({exc})")
            return 1
        for canal in hallados:
            try:
                sensor = Sensor(tca[canal])
                print(f"  canal {canal}: {sensor.range} mm")
            except Exception as exc:
                print(f"  canal {canal}: ERROR {type(exc).__name__}: {exc}")
    else:
        print("Para leer distancias:  python3 prueba_i2c.py --leer")
    return 0


if __name__ == "__main__":
    sys.exit(main())
