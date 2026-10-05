#!/usr/bin/env python3
"""
prueba_plc.py — Diagnóstico Modbus aislado, Sector 3 (Planta de Tratamiento de Agua)

No toca GPIO ni hilos: sirve exclusivamente para validar la conexión Modbus
contra el PLC físico ANTES de correr main.py --plc en la Raspberry Pi.

Uso:
    python3 prueba_plc.py --continuo              # polling de lectura de todos los HR relevantes
    python3 prueba_plc.py --escribir-raw 1 500     # escribe 500mm en el raw del tanque 1 (HR21)
    python3 prueba_plc.py --latir                  # solo prueba el heartbeat (HR40)
    python3 prueba_plc.py --continuo --intervalo 0.5
"""

import argparse
import sys
import time

from pyModbusTCP.client import ModbusClient

# --- Config: ajustar aquí si cambia la IP del PLC ---
PLC_IP = "10.10.30.100"
PLC_PORT = 502

# --- Mapa de registros (DB4 "CTF_ModBus") ---
HR_ESTADO = 0  # Sensor_Nivel_Alto / Comando_BombaN (bits empaquetados)
HR_OVERRIDE = 11  # Override_Seguridad
HR_RAW_TANQUES = {1: 21, 2: 23, 3: 25, 4: 27}  # raw mm, índices pares de Escalamiento_Sensores
HR_PCT_TANQUES = {1: 22, 2: 24, 3: 26, 4: 28}  # % escalado, índices impares (solo lectura, recalculado por el PLC)
HR_COLOR_LED = 10  # Color_LED_Flag4
HR_WATCHDOG = 40  # Watchdog_Comms — heartbeat de la RPi hacia el PLC


def conectar() -> ModbusClient:
    cliente = ModbusClient(host=PLC_IP, port=PLC_PORT, auto_open=True, timeout=3)
    if not cliente.open():
        print(f"[!] No se pudo conectar a {PLC_IP}:{PLC_PORT}")
        sys.exit(1)
    print(f"[+] Conectado a {PLC_IP}:{PLC_PORT}")
    return cliente


def modo_continuo(cliente: ModbusClient, intervalo: float) -> None:
    print("[*] Modo continuo — solo lectura, Ctrl+C para salir.\n")
    try:
        while True:
            hr0 = cliente.read_holding_registers(HR_ESTADO, 1)
            override = cliente.read_holding_registers(HR_OVERRIDE, 1)
            led = cliente.read_holding_registers(HR_COLOR_LED, 1)
            raws = cliente.read_holding_registers(HR_RAW_TANQUES[1], 8)  # HR21-28, cubre raw+% de los 4 tanques

            ts = time.strftime("%H:%M:%S")
            if hr0 is None or raws is None:
                print(f"[{ts}] [!] Lectura fallida — revisa conexión/IP.")
            else:
                print(f"[{ts}] HR0(estado)={hr0[0]:>5} | Override={override[0] if override else '?':>5} | "
                      f"LED={led[0] if led else '?':>3} | RAW T1-4={raws[0]},{raws[2]},{raws[4]},{raws[6]} | "
                      f"%   T1-4={raws[1]},{raws[3]},{raws[5]},{raws[7]}")
            time.sleep(intervalo)
    except KeyboardInterrupt:
        print("\n[*] Detenido por el usuario.")


def escribir_raw(cliente: ModbusClient, tanque: int, mm: int) -> None:
    if tanque not in HR_RAW_TANQUES:
        print(f"[!] Tanque inválido: {tanque}. Debe ser 1-4.")
        sys.exit(1)

    hr = HR_RAW_TANQUES[tanque]
    print(f"[*] Escribiendo {mm}mm en HR{hr} (raw tanque {tanque})...")
    ok = cliente.write_single_register(hr, mm)
    if not ok:
        print("[!] Escritura fallida.")
        sys.exit(1)

    time.sleep(0.3)
    hr_pct = HR_PCT_TANQUES[tanque]
    pct = cliente.read_holding_registers(hr_pct, 1)
    print(f"[+] Escritura OK. % recalculado por el PLC en HR{hr_pct}: {pct[0] if pct else '(no se pudo leer)'}")
    print("    Verifica en TIA (watch table) que el valor coincide.")


def latir(cliente: ModbusClient, veces: int, intervalo: float) -> None:
    print(f"[*] Probando heartbeat en HR{HR_WATCHDOG} — {veces} escrituras cada {intervalo}s.")
    print("    Ten la watch table de TIA abierta mirando Watchdog_Comms.\n")
    for i in range(1, veces + 1):
        ok = cliente.write_single_register(HR_WATCHDOG, i)
        estado = "OK" if ok else "FALLO"
        print(f"  [{i}/{veces}] [{estado}] Watchdog_Comms = {i}")
        time.sleep(intervalo)
    print("\n[+] Prueba de heartbeat terminada. Confirma en TIA que el valor subió en vivo.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnóstico Modbus aislado — Sector 3")
    grupo = parser.add_mutually_exclusive_group(required=True)
    grupo.add_argument("--continuo", action="store_true", help="Polling de lectura de HR relevantes")
    grupo.add_argument("--escribir-raw", nargs=2, metavar=("TANQUE", "MM"), type=int,
                        help="Escribe un valor raw (mm) en el tanque indicado (1-4)")
    grupo.add_argument("--latir", action="store_true", help="Prueba el heartbeat (Watchdog_Comms)")
    parser.add_argument("--intervalo", type=float, default=1.0, help="Segundos entre lecturas/latidos (default 1.0)")
    parser.add_argument("--veces", type=int, default=10, help="Cantidad de latidos a enviar con --latir (default 10)")

    args = parser.parse_args()
    cliente = conectar()

    try:
        if args.continuo:
            modo_continuo(cliente, args.intervalo)
        elif args.escribir_raw:
            tanque, mm = args.escribir_raw
            escribir_raw(cliente, tanque, mm)
        elif args.latir:
            latir(cliente, args.veces, args.intervalo)
    finally:
        cliente.close()


if __name__ == "__main__":
    main()
