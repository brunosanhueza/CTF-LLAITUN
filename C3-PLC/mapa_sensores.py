#!/usr/bin/env python3
"""
Mapa guiado de sensores: descubre que sensor (canal del multiplexor) esta en
que estanque, tocandolos uno por uno.

QUE HACE ESTE ARCHIVO
    Lee los cuatro VL53L0X, te pide que pongas la mano sobre el sensor de cada
    estanque (1, 2, 3, 4) y detecta que canal reacciona. Al final imprime la
    tabla SENSORES lista para pegar en config.py, con etiqueta y rele
    coherentes (Estanque N <-> PN), que es lo que hace que el dashboard y la
    posicion en el PLC (Escalamiento_Sensores) cuenten la misma historia.

    No toca bombas, luces, tiras ni el PLC, y NO modifica config.py: solo
    imprime la propuesta.

CONVENCION
    "Estanque N" es el mismo N que usa el PLC: sus datos van a
    Escalamiento_Sensores[2*(N-1)] (raw) y [2*(N-1)+1] (%). Estanque 1 ->
    [0],[1]; Estanque 2 -> [2],[3]; Estanque 3 -> [4],[5]; Estanque 4 -> [6],[7].

USO (sin sudo; cerrar main.py antes: comparte el bus I2C)
    python3 mapa_sensores.py           # guiado: estanque 1, 2, 3, 4
    python3 mapa_sensores.py --vivo    # solo las 4 lecturas en vivo (Ctrl+C)

COMO SE TOCA UN SENSOR
    Pon la mano a unos centimetros por encima del sensor del estanque pedido (o
    tapalo). Hace falta que la lectura cambie al menos UMBRAL_MM. Si no se
    detecta, el script lo dice y sigue; los numeros en vivo ayudan a ver si el
    sensor reacciona.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time

import config
import hal

UMBRAL_MM = 10        # cuanto tiene que cambiar un canal para darlo por "tocado"
RELACION = 1.5        # el ganador debe cambiar 1,5 veces mas que el segundo
MUESTRAS_OK = 6       # lecturas seguidas con el mismo ganador
PERIODO_S = 0.15
TIMEOUT_S = 60        # por estanque
BORNERA = {0: "J18", 1: "J19", 2: "J20", 3: "J21"}   # canal -> bornera (hardware)


def leer(banco) -> dict[int, int | None]:
    """{canal: distancia_mm o None si el sensor no respondio}."""
    return {lec.canal: (lec.distancia_mm if lec.ok else None)
            for lec in banco.leer_todos()}


def medir_base(banco, n: int = 7) -> dict[int, float]:
    """Lectura de reposo de cada canal (mediana de n lecturas)."""
    muestras: dict[int, list[int]] = {}
    for _ in range(n):
        for canal, mm in leer(banco).items():
            if mm is not None:
                muestras.setdefault(canal, []).append(mm)
        time.sleep(PERIODO_S)
    return {canal: statistics.median(v) for canal, v in muestras.items() if v}


def desviaciones(base: dict[int, float], actual: dict[int, int | None]) -> dict[int, float]:
    return {c: abs(actual[c] - base[c])
            for c in base if actual.get(c) is not None}


def _linea(base, actual) -> str:
    partes = []
    for canal in sorted(base):
        mm = actual.get(canal)
        partes.append(f"c{canal}:{'---' if mm is None else mm:>4}")
    return "  " + "  ".join(partes) + "   (mm)"


def esperar_toque(banco, base) -> int | None:
    """Devuelve el canal que reacciona de forma clara, o None si se agota el tiempo."""
    candidato, seguidas = None, 0
    inicio = time.monotonic()
    while time.monotonic() - inicio < TIMEOUT_S:
        actual = leer(banco)
        dev = desviaciones(base, actual)
        print("\r" + _linea(base, actual), end="", flush=True)
        if dev:
            canal, mayor = max(dev.items(), key=lambda kv: kv[1])
            otros = sorted((d for c, d in dev.items() if c != canal), reverse=True)
            segundo = otros[0] if otros else 0.0
            claro = mayor >= UMBRAL_MM and mayor >= RELACION * segundo
            if claro and canal == candidato:
                seguidas += 1
            elif claro:
                candidato, seguidas = canal, 1
            else:
                candidato, seguidas = None, 0
            if seguidas >= MUESTRAS_OK:
                print()
                return candidato
        time.sleep(PERIODO_S)
    print()
    return None


def esperar_reposo(banco, base) -> None:
    """Espera a que todos los canales vuelvan a su lectura de reposo."""
    quietas = 0
    inicio = time.monotonic()
    while time.monotonic() - inicio < 30 and quietas < MUESTRAS_OK:
        dev = desviaciones(base, leer(banco))
        quietas = quietas + 1 if all(d < UMBRAL_MM / 2 for d in dev.values()) else 0
        time.sleep(PERIODO_S)


def modo_vivo(banco) -> None:
    print("Lecturas en vivo, Ctrl+C para salir.\n")
    try:
        while True:
            actual = leer(banco)
            print("\r" + _linea({c: 0 for c in actual}, actual), end="", flush=True)
            time.sleep(PERIODO_S)
    except KeyboardInterrupt:
        print()


def imprimir_resultado(encontrado: dict[int, int | None]) -> None:
    print("\n" + "=" * 62)
    print("RESULTADO")
    print("=" * 62)
    for n in (1, 2, 3, 4):
        canal = encontrado.get(n)
        if canal is None:
            print(f"  Estanque {n}: NO DETECTADO")
        else:
            print(f"  Estanque {n}: canal {canal} ({BORNERA.get(canal, '?')})"
                  f"  ->  PLC Escalamiento_Sensores[{2 * (n - 1)}] y [{2 * (n - 1) + 1}]")

    canales = [c for c in encontrado.values() if c is not None]
    repetidos = {c for c in canales if canales.count(c) > 1}
    if repetidos:
        print(f"\n  ATENCION: el canal {sorted(repetidos)} salio para mas de un "
              f"estanque. Repetir la prueba (mano mas cerca, sin tocar otro sensor).")
    if len(canales) < 4 or repetidos:
        print("\n  No se propone tabla: faltan datos o hay conflicto.")
        return

    por_canal = {canal: n for n, canal in encontrado.items() if canal is not None}
    print("\nPegar en config.py (reemplaza SENSORES):\n")
    print("SENSORES = [")
    for canal in sorted(por_canal):
        n = por_canal[canal]
        print(f'    {{"canal": {canal}, "bornera": "{BORNERA.get(canal, "?")}", '
              f'"etiqueta": "Estanque {n}", "rele": "P{n}"}},')
    print("]")


def main() -> int:
    parser = argparse.ArgumentParser(description="Mapa guiado de sensores del cuadrante 3")
    parser.add_argument("--vivo", action="store_true",
                        help="solo muestra las lecturas en vivo")
    args = parser.parse_args()

    gpio, hay_hardware = hal.crear_gpio(False)
    if not hay_hardware:
        print("Sin hardware real (RPi.GPIO): este script solo sirve en la Raspberry Pi.",
              file=sys.stderr)
        return 1
    gpio.setmode(gpio.BCM)
    try:
        banco = hal.BancoSensoresVL53L0X(gpio)
    except Exception as exc:
        print(f"No se pudo abrir el bus I2C / multiplexor: {exc}\n"
              f"Cerrar main.py y revisar con prueba_i2c.py", file=sys.stderr)
        return 1

    try:
        if args.vivo:
            modo_vivo(banco)
            return 0

        print("No toques ningun sensor: midiendo lecturas de reposo...")
        base = medir_base(banco)
        if len(base) < 4:
            print(f"Solo respondieron {len(base)} de 4 sensores ({sorted(base)}). "
                  f"Revisar con prueba_i2c.py.")
            return 1
        print("Reposo: " + "  ".join(f"canal {c}={int(v)} mm" for c, v in sorted(base.items())))

        encontrado: dict[int, int | None] = {}
        for n in (1, 2, 3, 4):
            print(f"\n>>> ESTANQUE {n}: pon la mano sobre SU sensor (o tapalo) y "
                  f"mantenla un momento...")
            canal = esperar_toque(banco, base)
            encontrado[n] = canal
            if canal is None:
                print(f"  No se detecto ningun canal claro para el estanque {n}.")
                continue
            print(f"  -> detectado: canal {canal} ({BORNERA.get(canal, '?')}). "
                  f"Quita la mano...")
            esperar_reposo(banco, base)

        imprimir_resultado(encontrado)
        return 0
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        return 0
    finally:
        try:
            banco.cerrar()
        finally:
            gpio.cleanup()


if __name__ == "__main__":
    sys.exit(main())
