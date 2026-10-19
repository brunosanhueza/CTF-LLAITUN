# -*- coding: utf-8 -*-
"""
DAEMON RTU - Sector 3 (CTF Aguas del Valle)
Gestion de hardware local (Sensores I2C VL53L0X, Bombas, Luces, Semaforos)
y comunicacion Modbus TCP con el PLC Siemens (10.10.30.103).


ARQUITECTURA DE RESILIENCIA (OPCIONES B & C):
 - Opcion C: Hilo independiente de lectura I2C (HiloLectorSensores) con cache en RAM.
   El bucle de Modbus y control NUNCA toca el hardware I2C directamente; jamas se congela.
 - Opcion B: Auto-recuperacion por hardware con GPIO 17 (Reset MUX TCA9548A).
   Si el bus I2C sufre un cuelgue por ruido electrico de los reles, el hilo secundario
   pulsa el pin GPIO 17, destraba las lineas SDA/SCL y reanuda la medicion de forma transparente.
"""

import time
import threading
import logging
import os
import math
import sys
try:
    from pyModbusTCP.client import ModbusClient
except ImportError:
    class ModbusClient:
        def __init__(self, *args, **kwargs):
            self.is_open = False
        def open(self): return False
        def close(self): pass
        def write_multiple_registers(self, *a, **kw): return False
        def write_single_register(self, *a, **kw): return False
        def read_holding_registers(self, *a, **kw): return None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ============================================================================
# MAPA DE HARDWARE
# ============================================================================
# Cada bomba usa DOS reles a la vez (polo +12V y retorno GND) para cerrar el circuito.
RELES_BOMBAS = {
    0: [4, 5],     # P1 (Estanque 1 - Canales 1 y 2 de reles)
    1: [6, 7],     # P2 (Estanque 2 - Canales 3 y 4 de reles)
    2: [27, 19],   # P3 (Estanque 3 - Canales 5 y 6 de reles)
    3: [26, 12]    # P4 (Estanque 4 - Canales 7 y 8 de reles)
}
LUMINARIAS = [9, 11]
SEMAFORO_1 = {"rojo": 22, "amarillo": 23, "verde": 24}
SEMAFORO_2 = {"rojo": 16, "amarillo": 20, "verde": 21}

MUX_ADDRESS = 0x70
MUX_RST_PIN = 17
CANALES_SENSORES = [0, 1, 2, 3]

DIST_VACIO_MM = 50
DIST_LLENO_MM = 20

# Geometría real por estanque según mediciones físicas (distancia sensor a fondo vs nivel alto)
# Canal 0: Estanque 2 (J18, Bomba P2) - Vacío medido: ~128 mm, Lleno: 20 mm
# Canal 1: Estanque 4 (J19, Bomba P4) - Vacío medido: ~82 mm,  Lleno: 15 mm
# Canal 2: Estanque 1 (J20, Bomba P1 - Sensor físico defectuoso / Bypass)
# Canal 3: Estanque 3 (J21, Bomba P3) - Vacío medido: ~65 mm,  Lleno: 20 mm
GEOMETRIA_ESTANQUES = {
    0: {"vacio": 128, "lleno": 20},  # Canal 0: Estanque 2
    1: {"vacio": 82,  "lleno": 15},  # Canal 1: Estanque 4
    2: {"vacio": 150, "lleno": 20},  # Canal 2: Estanque 1 (Bypass)
    3: {"vacio": 65,  "lleno": 20},  # Canal 3: Estanque 3
}

def calcular_pct_canal(canal, mm, dist_base=None):
    if mm is None or mm >= 8000 or mm <= 0:
        return 0.0
    geom = GEOMETRIA_ESTANQUES.get(canal, {"vacio": DIST_VACIO_MM, "lleno": DIST_LLENO_MM})
    vacio = dist_base if dist_base is not None else geom["vacio"]
    lleno = geom["lleno"]
    if vacio <= lleno:
        return 0.0
    # Zona muerta de 2 mm contra ruido/vibraciones en reposo
    if mm >= (vacio - 2):
        return 0.0
    if mm <= lleno:
        return 100.0
    pct = (vacio - mm) / (vacio - lleno) * 100.0
    return max(0.0, min(100.0, round(pct, 1)))

MAPA_SENSORES_INFO = {
    0: {
        "estanque": "Estanque 2",
        "bornera": "J18",
        "bomba": "P2",
        "reles_gpio": RELES_BOMBAS[1],
        "hr_raw": 23,
        "hr_pct": 24,
        "bit_alto": 10,
        "bit_bomba": 11,
    },
    1: {
        "estanque": "Estanque 4",
        "bornera": "J19",
        "bomba": "P4",
        "reles_gpio": RELES_BOMBAS[3],
        "hr_raw": 27,
        "hr_pct": 28,
        "bit_alto": 14,
        "bit_bomba": 15,
    },
    2: {
        "estanque": "Estanque 1",
        "bornera": "J20",
        "bomba": "P1",
        "reles_gpio": RELES_BOMBAS[0],
        "hr_raw": 21,
        "hr_pct": 22,
        "bit_alto": 8,
        "bit_bomba": 9,
    },
    3: {
        "estanque": "Estanque 3",
        "bornera": "J21",
        "bomba": "P3",
        "reles_gpio": RELES_BOMBAS[2],
        "hr_raw": 25,
        "hr_pct": 26,
        "bit_alto": 12,
        "bit_bomba": 13,
    },
}

try:
    import RPi.GPIO as GPIO
    import board
    import busio
    import adafruit_tca9548a
    from adafruit_vl53l0x import VL53L0X
    HARDWARE_REAL = True
except ImportError:
    HARDWARE_REAL = False
    logger.warning("Simulacion activa (RPi.GPIO / I2C no disponible).")

try:
    from rpi_ws281x import ws
    HAY_TIRAS = True
except ImportError:
    HAY_TIRAS = False


class HiloLectorSensores(threading.Thread):
    """
    OPCION C: Hilo en segundo plano exclusivo para interrogar sensores I2C de forma secuencial.
    Mantiene una cache en memoria de las ultimas lecturas validas para no bloquear Modbus.
    OPCION B: Incorpora vigilancia de congelamiento de bus y auto-reset por GPIO 17 con debounce.
    """
    def __init__(self, hw):
        super().__init__(daemon=True)
        self.hw = hw
        self.corriendo = True
        self.lock = threading.Lock()
        self.fallos_consecutivos = {0: 0, 1: 0, 2: 0, 3: 0}
        self.bus_freeze_count = 0

    def _calcular_pct(self, canal, mm):
        base = self.hw.distancias_base.get(canal, None)
        return calcular_pct_canal(canal, mm, dist_base=base)

    def run(self):
        while self.corriendo:
            if self.hw.skip_sensores or not HARDWARE_REAL:
                # Actualizar cache con datos de la simulacion
                with self.lock:
                    for i in range(4):
                        pct = self.hw.niveles_simulados[i]
                        geom = GEOMETRIA_ESTANQUES.get(i, {"vacio": 50, "lleno": 20})
                        vacio, lleno = geom["vacio"], geom["lleno"]
                        mm = int(vacio - (pct / 100.0) * (vacio - lleno))
                        self.hw._cache_distancias_mm[i] = max(lleno - 5, min(vacio + 10, mm))
                        self.hw._cache_pct[i] = pct
                time.sleep(0.2)
                continue

            # Modo Hardware Real: barrido secuencial síncrono en este hilo (evita hilos huérfanos y colisiones en I2C)
            lecturas_validas = 0
            sensores_habilitados = 0

            for c in CANALES_SENSORES:
                if not self.corriendo:
                    break

                if c in self.hw.bypass_canales:
                    base = self.hw.distancias_base.get(c, 150)
                    with self.lock:
                        self.hw._cache_distancias_mm[c] = base
                        self.hw._cache_pct[c] = 0.0
                        self.hw.estado_sensores[c] = "BYPASS (Omitido)"
                    continue

                sensor = self.hw.sensores[c]
                if sensor is None:
                    continue

                sensores_habilitados += 1

                try:
                    # Lectura directa y síncrona en este hilo secundario
                    dist = sensor.range
                    base = self.hw.distancias_base.get(c, None)
                    if 0 < dist < 8000:
                        pct = calcular_pct_canal(c, dist, dist_base=base)
                        with self.lock:
                            self.hw._cache_distancias_mm[c] = dist
                            self.hw._cache_pct[c] = pct
                            self.hw.estado_sensores[c] = f"MIDIENDO OK ({dist} mm)"
                        self.fallos_consecutivos[c] = 0
                        lecturas_validas += 1
                    else:
                        # Fuera de rango (estanque vacío o sin objetivo en rango)
                        self.fallos_consecutivos[c] += 1
                        fallback_mm = base if base is not None else GEOMETRIA_ESTANQUES.get(c, {}).get("vacio", 150)
                        with self.lock:
                            self.hw._cache_distancias_mm[c] = fallback_mm
                            self.hw._cache_pct[c] = 0.0
                            self.hw.estado_sensores[c] = f"FUERA DE RANGO ({dist} mm)"

                except Exception as e:
                    self.fallos_consecutivos[c] += 1
                    base = self.hw.distancias_base.get(c, 150)
                    with self.lock:
                        self.hw._cache_distancias_mm[c] = base
                        self.hw._cache_pct[c] = 0.0
                        self.hw.estado_sensores[c] = f"ERROR LECTURA ({e})"

                    # Auto-recuperación individual del canal si falla 3 veces seguidas
                    if self.fallos_consecutivos[c] >= 3:
                        try:
                            sensor_recup = VL53L0X(self.hw.mux[c], io_timeout_s=0.5)
                            if hasattr(sensor_recup, "measurement_timing_budget"):
                                sensor_recup.measurement_timing_budget = 33000
                            self.hw.sensores[c] = sensor_recup
                            self.fallos_consecutivos[c] = 0
                            logger.info(f"[AUTO-RECUPERACION] Sensor en canal {c} recuperado.")
                        except Exception:
                            pass

            # Vigilancia de congelamiento de bus (Opción B)
            # Solo si hay sensores habilitados pero ninguno logra leer durante varios barridos seguidos (~3-4 seg)
            if sensores_habilitados > 0 and lecturas_validas == 0:
                self.bus_freeze_count += 1
                if self.bus_freeze_count >= 8:
                    logger.warning("[AUTO-RECUPERACION] Pérdida prolongada de lecturas I2C. Reiniciando MUX TCA9548A en GPIO 17...")
                    self.hw.reiniciar_bus_hardware()
                    self.bus_freeze_count = 0
                    for c in CANALES_SENSORES:
                        self.fallos_consecutivos[c] = 0
            else:
                self.bus_freeze_count = 0

            time.sleep(0.12)



class HardwareManager:
    def __init__(self, skip_sensores: bool = False, bypass_canales: list = None):
        self.skip_sensores = skip_sensores
        # Por omision se omite el Canal 2 (J20 / Estanque 1) por sensor defectuoso en placa
        self.bypass_canales = [2] if bypass_canales is None else list(bypass_canales)
        self.sensores = [None, None, None, None]
        self.estado_sensores = {}
        self.leds = None
        self.canales_ws = []
        self.n_leds_tira = 120
        
        self.modo_manual_bombas = False
        self.estado_bombas = [False, False, False, False]
        self.niveles_simulados = [25.0, 25.0, 25.0, 25.0]

        # Distancias base de reposo (Auto-tara / Linea base)
        # Se calibran automaticamente al inicio con la primera lectura valida de cada estanque
        self.distancias_base = {
            0: GEOMETRIA_ESTANQUES[0]["vacio"],  # ~128 mm (Estanque 2)
            1: GEOMETRIA_ESTANQUES[1]["vacio"],  # ~82 mm  (Estanque 4)
            2: GEOMETRIA_ESTANQUES[2]["vacio"],  # 150 mm  (Estanque 1 / Bypass)
            3: GEOMETRIA_ESTANQUES[3]["vacio"],  # ~65 mm  (Estanque 3)
        }

        # Cache compartida de lecturas en RAM (Opcion C)
        self._cache_distancias_mm = [
            self.distancias_base[0],
            self.distancias_base[1],
            self.distancias_base[2],
            self.distancias_base[3]
        ]
        self._cache_pct = [0.0, 0.0, 0.0, 0.0]

        if HAY_TIRAS:
            try:
                self.leds = ws.new_ws2811_t()
                ws.ws2811_t_freq_set(self.leds, 800000)
                ws.ws2811_t_dmanum_set(self.leds, 10)
                
                ch0 = ws.ws2811_channel_get(self.leds, 0)
                ws.ws2811_channel_t_count_set(ch0, self.n_leds_tira)
                ws.ws2811_channel_t_gpionum_set(ch0, 18)
                ws.ws2811_channel_t_invert_set(ch0, 0)
                ws.ws2811_channel_t_brightness_set(ch0, 128)
                ws.ws2811_channel_t_strip_type_set(ch0, ws.WS2811_STRIP_GRB)
                self.canales_ws.append(ch0)
                
                ch1 = ws.ws2811_channel_get(self.leds, 1)
                ws.ws2811_channel_t_count_set(ch1, self.n_leds_tira)
                ws.ws2811_channel_t_gpionum_set(ch1, 13)
                ws.ws2811_channel_t_invert_set(ch1, 0)
                ws.ws2811_channel_t_brightness_set(ch1, 128)
                ws.ws2811_channel_t_strip_type_set(ch1, ws.WS2811_STRIP_GRB)
                self.canales_ws.append(ch1)
                
                ws.ws2811_init(self.leds)
            except Exception as e:
                logger.error(f"Error WS2811: {e}")

        if HARDWARE_REAL:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            for par_pines in RELES_BOMBAS.values():
                for pin in par_pines:
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
            for pin in LUMINARIAS:
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
            for sem in [SEMAFORO_1, SEMAFORO_2]:
                for pin in sem.values():
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)

            if self.skip_sensores:
                print("\n" + "="*85)
                print("  [!] MODO SIN SENSORES ACTIVADO (--sin-sensores)")
                print("  [*] Se omite la conexion y busqueda de sensores fisicos I2C.")
                print("  [*] Bus I2C liberado. Bombas (P1-P4) y luces operaran normalmente.")
                print("  [*] Se usara telemetria simulada para mantener el SCADA y PLC.")
                print("="*85 + "\n")
                for c in CANALES_SENSORES:
                    self.estado_sensores[c] = "OMITIDO (--sin-sensores)"
            else:
                try:
                    # Reset inicial de hardware del multiplexor TCA9548A por GPIO 17
                    GPIO.setup(MUX_RST_PIN, GPIO.OUT, initial=GPIO.HIGH)
                    GPIO.output(MUX_RST_PIN, GPIO.LOW)
                    time.sleep(0.02)
                    GPIO.output(MUX_RST_PIN, GPIO.HIGH)
                    time.sleep(0.05)
                    
                    self.i2c = busio.I2C(board.SCL, board.SDA)
                    self.mux = adafruit_tca9548a.TCA9548A(self.i2c, address=MUX_ADDRESS)
                    
                    print("\n" + "="*85)
                    print("         DIAGNOSTICO DE HARDWARE: ESCANEO DE SENSORES I2C (TCA9548A @ 0x70)         ")
                    print(" Bus I2C: SDA (GPIO 2, Pin 3) | SCL (GPIO 3, Pin 5) | Reset MUX: GPIO 17 (Pin 11)   ")
                    print("="*85)

                    for canal in CANALES_SENSORES:
                        info = MAPA_SENSORES_INFO.get(canal, {})
                        est = info.get("estanque", f"Estanque {canal}")
                        born = info.get("bornera", "J??")
                        bomba = info.get("bomba", "P?")
                        gpios = info.get("reles_gpio", [])
                        hr_info = f"HR {info.get('hr_raw')} (RAW), HR {info.get('hr_pct')} (%)"

                        print(f" [Canal {canal}] Bornera {born} -> {est} (Bomba {bomba}, GPIO {gpios}) | {hr_info}")

                        if canal in self.bypass_canales:
                            self.sensores[canal] = None
                            self.estado_sensores[canal] = "BYPASS (Deshabilitado intencionalmente / Defectuoso)"
                            print(f"   [-] ESTADO: BYPASS / OMITIDO (Sensor defectuoso)\n")
                            continue

                        print(f"   -> Verificando comunicacion I2C...", end="", flush=True)

                        try:
                            try:
                                sensor = VL53L0X(self.mux[canal], io_timeout_s=0.5)
                            except TypeError:
                                sensor = VL53L0X(self.mux[canal])
                                if hasattr(sensor, "io_timeout_s"):
                                    sensor.io_timeout_s = 0.5
                            
                            if hasattr(sensor, "measurement_timing_budget"):
                                try:
                                    sensor.measurement_timing_budget = 40000
                                except Exception:
                                    pass

                            dist_test = sensor.range
                            if dist_test > 8000:
                                self.estado_sensores[canal] = f"CONECTADO PERO FUERA DE RANGO ({dist_test} mm)"
                                print(f"\r   [!] ADVERTENCIA: Responde I2C pero lectura fuera de rango ({dist_test} mm)\n")
                            else:
                                self.distancias_base[canal] = dist_test
                                self.estado_sensores[canal] = f"OPERATIVO (Calibrado Base: {dist_test} mm)"
                                print(f"\r   [+] OPERATIVO: Sensor OK | Medida base calibrada: {dist_test} mm\n")
                                self._cache_distancias_mm[canal] = dist_test
                                self._cache_pct[canal] = calcular_pct_canal(canal, dist_test, dist_base=dist_test)

                            self.sensores[canal] = sensor
                        except Exception as e:
                            self.sensores[canal] = None
                            self.estado_sensores[canal] = f"FALLO CRITICO: Error I2C ({e})"
                            print(f"\r   [X] FALLO CRITICO: Error I2C ({e}). Sensor inoperativo en bornera {born}.\n")

                    print("="*85)
                    print(" RESUMEN DIAGNOSTICO DE SENSORES:")
                    for c in CANALES_SENSORES:
                        inf = MAPA_SENSORES_INFO[c]
                        print(f"  * {inf['estanque']} [Canal {c}, Bornera {inf['bornera']}]: {self.estado_sensores.get(c, 'DESCONOCIDO')}")
                    print("="*85 + "\n")

                except Exception as e:
                    logger.error(f"Error general inicializando bus I2C / multiplexor: {e}")
                    for c in CANALES_SENSORES:
                        self.estado_sensores[c] = f"ERROR GENERAL MUX ({e})"
        else:
            for c in CANALES_SENSORES:
                self.estado_sensores[c] = "SIMULADO (PC sin GPIO)"

        # Instanciar el hilo lector independiente (Opcion C)
        self.hilo_sensores = HiloLectorSensores(self)

    def iniciar(self):
        """Inicia el worker thread independiente de lectura I2C."""
        self.hilo_sensores.start()

    def reiniciar_bus_hardware(self):
        """
        OPCION B: Pulsa el pin RST del TCA9548A en GPIO 17 para destrabar el bus I2C
        y re-instanciar los sensores sin reiniciar el programa.
        """
        if not HARDWARE_REAL or self.skip_sensores: return
        try:
            GPIO.output(MUX_RST_PIN, GPIO.LOW)
            time.sleep(0.02)
            GPIO.output(MUX_RST_PIN, GPIO.HIGH)
            time.sleep(0.08)
            
            try:
                self.mux = adafruit_tca9548a.TCA9548A(self.i2c, address=MUX_ADDRESS)
            except Exception:
                try:
                    self.i2c.deinit()
                except Exception:
                    pass
                self.i2c = busio.I2C(board.SCL, board.SDA)
                self.mux = adafruit_tca9548a.TCA9548A(self.i2c, address=MUX_ADDRESS)

            for c in CANALES_SENSORES:
                if c not in self.bypass_canales:
                    try:
                        try:
                            sensor = VL53L0X(self.mux[c], io_timeout_s=0.5)
                        except TypeError:
                            sensor = VL53L0X(self.mux[c])
                            if hasattr(sensor, "io_timeout_s"):
                                sensor.io_timeout_s = 0.5
                        if hasattr(sensor, "measurement_timing_budget"):
                            try:
                                sensor.measurement_timing_budget = 40000
                            except Exception:
                                pass
                        self.sensores[c] = sensor
                        self.estado_sensores[c] = "RECONECTADO (Post-Reset)"
                    except Exception as err:
                        self.sensores[c] = None
                        self.estado_sensores[c] = f"ERROR POST-RESET ({err})"
            logger.info("[AUTO-RECUPERACION] Multiplexor TCA9548A re-inicializado correctamente por GPIO 17.")
        except Exception as e:
            logger.error(f"[AUTO-RECUPERACION ERROR] Error reiniciando hardware MUX: {e}")

    def set_bomba(self, indice: int, activa: bool):
        self.estado_bombas[indice] = activa
        if HARDWARE_REAL:
            nivel = GPIO.LOW if activa else GPIO.HIGH
            for pin in RELES_BOMBAS[indice]:
                GPIO.output(pin, nivel)

    def set_bombas(self, activas: bool):
        if not self.modo_manual_bombas:
            for i in range(4):
                self.set_bomba(i, activas)

    def set_luminarias(self, activas: bool):
        if HARDWARE_REAL:
            nivel = GPIO.HIGH if activas else GPIO.LOW
            for pin in LUMINARIAS:
                GPIO.output(pin, nivel)

    def set_semaforo(self, id_sem: int, color: str):
        if HARDWARE_REAL:
            sem = SEMAFORO_1 if id_sem == 1 else SEMAFORO_2
            for c, pin in sem.items():
                nivel = GPIO.LOW if c == color else GPIO.HIGH
                GPIO.output(pin, nivel)

    def apagar_semaforos(self):
        if HARDWARE_REAL:
            for sem in [SEMAFORO_1, SEMAFORO_2]:
                for pin in sem.values():
                    GPIO.output(pin, GPIO.HIGH)

    def pintar_pixeles(self, encendidos: int, color_t1, color_t2):
        if HAY_TIRAS and self.leds:
            try:
                c1 = (int(color_t1[0]) << 16) | (int(color_t1[1]) << 8) | int(color_t1[2])
                c2 = (int(color_t2[0]) << 16) | (int(color_t2[1]) << 8) | int(color_t2[2])
                apagado = 0
                
                if len(self.canales_ws) > 0:
                    for i in range(self.n_leds_tira):
                        if (i % 30) >= 25:
                            ws.ws2811_led_set(self.canales_ws[0], i, apagado)
                        else:
                            ws.ws2811_led_set(self.canales_ws[0], i, c1 if i < encendidos else apagado)
                if len(self.canales_ws) > 1:
                    for i in range(self.n_leds_tira):
                        ws.ws2811_led_set(self.canales_ws[1], i, c2 if i < encendidos else apagado)
                        
                ws.ws2811_render(self.leds)
            except Exception:
                pass

    def leer_niveles_pct(self):
        """Retorna instantaneamente los porcentajes desde la cache en RAM (Cero bloqueo I2C)."""
        if getattr(self, 'override_niveles', None) is not None:
            return self.override_niveles
        with self.hilo_sensores.lock:
            return list(self._cache_pct)

    def leer_distancias_mm(self):
        """Retorna instantaneamente las distancias desde la cache en RAM (Cero bloqueo I2C)."""
        with self.hilo_sensores.lock:
            return list(self._cache_distancias_mm)

    def actualizar_simulacion(self, bombas_activas):
        if not HARDWARE_REAL or self.skip_sensores:
            if getattr(self, 'override_niveles', None) is not None:
                self.niveles_simulados = self.override_niveles.copy()
            else:
                tasa = 1.6 if bombas_activas else -0.5
                for i in range(4):
                    self.niveles_simulados[i] = max(0.0, min(105.0, self.niveles_simulados[i] + tasa))

    def limpiar(self):
        self.hilo_sensores.corriendo = False
        if HARDWARE_REAL:
            self.set_bombas(False)
            self.set_luminarias(False)
            self.set_semaforo(1, "rojo")
            self.set_semaforo(2, "rojo")
            GPIO.cleanup()
        if HAY_TIRAS and self.leds:
            try:
                self.pintar_pixeles(0, (0,0,0), (0,0,0))
                ws.ws2811_fini(self.leds)
                ws.delete_ws2811_t(self.leds)
            except Exception:
                pass


class AnimadorTiras(threading.Thread):
    def __init__(self, hw):
        super().__init__(daemon=True)
        self.hw = hw
        self.corriendo = True
        self.color_t1 = (0, 150, 255)
        self.color_t2 = (0, 150, 255)
        self.velocidad_ms = 60
        self.modo_parpadeo = False
        
    def run(self):
        while self.corriendo:
            if getattr(self, 'modo_parpadeo', False):
                self.hw.pintar_pixeles(self.hw.n_leds_tira, self.color_t1, self.color_t2)
                time.sleep(0.2)
                self.hw.pintar_pixeles(0, (0, 0, 0), (0, 0, 0))
                time.sleep(0.2)
                continue

            n_leds = self.hw.n_leds_tira
            for i in range(n_leds + 1):
                if not self.corriendo or getattr(self, 'modo_parpadeo', False): break
                self.hw.pintar_pixeles(i, self.color_t1, self.color_t2)
                time.sleep(max(10, self.velocidad_ms) / 1000.0)
                
            time.sleep(0.4)
            self.hw.pintar_pixeles(0, self.color_t1, self.color_t2)
            time.sleep(0.2)


class AnimadorSemaforos(threading.Thread):
    def __init__(self, hw):
        super().__init__(daemon=True)
        self.hw = hw
        self.corriendo = True
        self.secuencia = [("verde", 6.0), ("amarillo", 2.0), ("rojo", 8.0)]
        self.periodo = sum(d for c, d in self.secuencia)
        self.desfases = {1: 0.0, 2: 8.0}
        
    def _color_en(self, t):
        pos = t % self.periodo
        acumulado = 0.0
        for color, duracion in self.secuencia:
            acumulado += duracion
            if pos < acumulado:
                return color
        return "rojo"

    def run(self):
        t0 = time.monotonic()
        while self.corriendo:
            t = time.monotonic() - t0
            c1 = self._color_en(t + self.desfases[1])
            c2 = self._color_en(t + self.desfases[2])
            self.hw.set_semaforo(1, c1)
            self.hw.set_semaforo(2, c2)
            time.sleep(0.1)


class RtuHardwareGateway:
    def __init__(self, skip_sensores: bool = False, bypass_canales: list = None):
        self.plc_ip = os.environ.get("PLC_HOST", "10.10.30.103")
        self.plc_port = int(os.environ.get("PLC_PORT", 502))
        
        # Canal 2 (J20 / Estanque 1) en bypass por defecto si no se especifica
        if bypass_canales is None:
            bypass_canales = [2]

        self.cliente = ModbusClient(host=self.plc_ip, port=self.plc_port, auto_open=True, timeout=2.0)
        self.hw = HardwareManager(skip_sensores=skip_sensores, bypass_canales=bypass_canales)
        self.animador_tiras = AnimadorTiras(self.hw)
        self.animador_semaforos = AnimadorSemaforos(self.hw)
        
        self.corriendo = False
        self._contador_watchdog = 0
        self._estado_bombas_local = False

        self.historial_distancias = {0: [], 1: [], 2: [], 3: []}
        self.max_muestras = 3
        self.segundos_desbordados = {0: 0, 1: 0, 2: 0, 3: 0}
        self.map_alto = {0: 10, 1: 14, 2: 8, 3: 12}

        self.mapa_colores = {
            1: (255, 0, 0),     # Rojo
            2: (0, 255, 0),     # Verde
            3: (0, 0, 255),     # Azul
            4: (255, 140, 0),   # Ambar
            5: (0, 200, 255),   # Cian
            6: (255, 0, 200),   # Magenta
            7: (255, 255, 255)  # Blanco
        }

    def iniciar(self):
        if not self.corriendo:
            self.corriendo = True
            # Iniciar hilo de sensores en background (Opcion C)
            self.hw.iniciar()
            self.animador_tiras.start()
            self.animador_semaforos.start()
            threading.Thread(target=self._bucle_control, daemon=True).start()

    def _calcular_pct_local(self, mm):
        return calcular_pct_canal(0, mm)

    def _actualizar_luces(self, color_plc, max_pct_local):
        if color_plc == 0:
            if max_pct_local >= 100.0:
                self.animador_tiras.color_t1 = (255, 100, 0)
                self.animador_tiras.color_t2 = (255, 100, 0)
                self.animador_tiras.modo_parpadeo = True
            elif max_pct_local >= 85.0:
                self.animador_tiras.color_t1 = (255, 255, 0)
                self.animador_tiras.color_t2 = (255, 255, 0)
                self.animador_tiras.modo_parpadeo = False
                self.animador_tiras.velocidad_ms = 40
            else:
                self.animador_tiras.color_t1 = (0, 150, 255)
                self.animador_tiras.color_t2 = (0, 150, 255)
                self.animador_tiras.modo_parpadeo = False
                self.animador_tiras.velocidad_ms = 60
        else:
            self.animador_tiras.modo_parpadeo = False
            color_rgb = self.mapa_colores.get(color_plc, (255, 255, 255))
            self.animador_tiras.color_t1 = color_rgb
            self.animador_tiras.color_t2 = color_rgb
            self.animador_tiras.velocidad_ms = 20

    def _bucle_control(self):
        """
        Bucle Modbus y control de planta. Corre a reloj fijo de 1.0s.
        NUNCA se congela porque lee distancias desde la memoria RAM.
        """
        loop_counter = 0
        while self.corriendo:
            try:
                self.hw.actualizar_simulacion(self._estado_bombas_local)
                
                # Leemos distancias instantaneamente de la cache en RAM (0.0001 ms)
                distancias_crudas = self.hw.leer_distancias_mm()
                max_pct_calculado = 0.0
                bits_alto_sensores = 0

                distancias_suavizadas = []
                porcentajes_calculados = []
                for i in range(4):
                    dist_cruda = distancias_crudas[i]
                    geom = GEOMETRIA_ESTANQUES.get(i, {"vacio": 50, "lleno": 20})
                    base_vacio = self.hw.distancias_base.get(i, geom["vacio"])

                    if i in self.hw.bypass_canales:
                        self.historial_distancias[i].clear()
                        promedio = base_vacio
                        pct = 0.0
                    elif dist_cruda < 8000:
                        self.historial_distancias[i].append(dist_cruda)
                        if len(self.historial_distancias[i]) > self.max_muestras:
                            self.historial_distancias[i].pop(0)
                        promedio = int(sum(self.historial_distancias[i]) / len(self.historial_distancias[i]))
                        pct = calcular_pct_canal(i, promedio, dist_base=base_vacio)
                    else:
                        # Fuera de rango o lectura inválida: limpiar historial para que el obstáculo no quede pegado
                        self.historial_distancias[i].clear()
                        promedio = base_vacio if not self.hw.skip_sensores else dist_cruda
                        pct = 0.0

                    distancias_suavizadas.append(promedio)
                    porcentajes_calculados.append(pct)

                    if pct > max_pct_calculado:
                        max_pct_calculado = pct

                    if pct >= 95.0:
                        self.segundos_desbordados[i] += 1
                    else:
                        self.segundos_desbordados[i] = 0

                    if self.segundos_desbordados[i] >= 10:
                        bits_alto_sensores |= (1 << self.map_alto[i])

                pct_p1 = int(porcentajes_calculados[2])  # Estanque 1 (Canal 2)
                pct_p2 = int(porcentajes_calculados[0])  # Estanque 2 (Canal 0)
                pct_p3 = int(porcentajes_calculados[3])  # Estanque 3 (Canal 3)
                pct_p4 = int(porcentajes_calculados[1])  # Estanque 4 (Canal 1)

                # Intentar conectar con el PLC si no esta abierto
                if not self.cliente.is_open:
                    self.cliente.open()

                hr_color = 0
                b1 = b2 = b3 = b4 = False

                if self.cliente.is_open:
                    registros_sensores = [
                        distancias_suavizadas[2], pct_p1,  # HR 21 (RAW), HR 22 (PCT)
                        distancias_suavizadas[0], pct_p2,  # HR 23 (RAW), HR 24 (PCT)
                        distancias_suavizadas[3], pct_p3,  # HR 25 (RAW), HR 26 (PCT)
                        distancias_suavizadas[1], pct_p4   # HR 27 (RAW), HR 28 (PCT)
                    ]
                    self.cliente.write_multiple_registers(21, registros_sensores)
                    self.cliente.write_single_register(41, 0)

                    # Watchdog
                    self._contador_watchdog = (self._contador_watchdog + 1) & 0xFFFF
                    self.cliente.write_single_register(40, self._contador_watchdog)

                    # Leer comandos del PLC
                    regs_bombas = self.cliente.read_holding_registers(0, 1)
                    regs_color = self.cliente.read_holding_registers(10, 1)

                    if regs_bombas and regs_color:
                        hr_bombas = regs_bombas[0]
                        hr_color = regs_color[0]

                        nuevo_hr0 = (hr_bombas & ~0x5500) | bits_alto_sensores
                        if nuevo_hr0 != hr_bombas:
                            self.cliente.write_single_register(0, nuevo_hr0)

                        b1 = bool((hr_bombas >> 9) & 1)
                        b2 = bool((hr_bombas >> 11) & 1)
                        b3 = bool((hr_bombas >> 13) & 1)
                        b4 = bool((hr_bombas >> 15) & 1)

                        self.hw.set_bomba(0, b1)
                        self.hw.set_bomba(1, b2)
                        self.hw.set_bomba(2, b3)
                        self.hw.set_bomba(3, b4)
                        
                        self._estado_bombas_local = b1 or b2 or b3 or b4
                        self.hw.set_luminarias(hr_color != 0)
                        self._actualizar_luces(hr_color, max_pct_calculado)
                else:
                    self.hw.set_bombas(False)
                    self._estado_bombas_local = False
                    self.hw.set_luminarias(False)
                    self.animador_tiras.modo_parpadeo = False
                    self.animador_tiras.color_t1 = (255, 0, 255)
                    self.animador_tiras.color_t2 = (255, 0, 255)

                # Reporte por consola mas entendible y frecuente con barras de progreso
                loop_counter += 1
                if loop_counter == 1 or loop_counter % 2 == 0:
                    ahora = time.strftime("%H:%M:%S")
                    print("\n" + "="*88)
                    print(f"[*] TELEMETRIA Y PRUEBA DE SENSORES EN TIEMPO REAL [{ahora}]")
                    print("="*88)

                    orden_diagnostico = [
                        (2, "Estanque 1", "J20", "P1", [4, 5], distancias_suavizadas[2], pct_p1, b1),
                        (0, "Estanque 2", "J18", "P2", [6, 7], distancias_suavizadas[0], pct_p2, b2),
                        (3, "Estanque 3", "J21", "P3", [27, 19], distancias_suavizadas[3], pct_p3, b3),
                        (1, "Estanque 4", "J19", "P4", [26, 12], distancias_suavizadas[1], pct_p4, b4),
                    ]

                    for ch, est, born, p, gpios, d, p_pct, b_st in orden_diagnostico:
                        bomba_txt = "ON " if b_st else "OFF"
                        llenos = max(0, min(10, int(round((p_pct / 100.0) * 10))))
                        barra_ascii = "#" * llenos + "." * (10 - llenos)
                        
                        base_d = self.hw.distancias_base.get(ch, 100)
                        if p_pct >= 75:
                            dedo_tag = ">>> [DEDO MUY CERCA / TOPE]"
                        elif p_pct >= 20 or (ch not in self.hw.bypass_canales and d < (base_d - 6)):
                            dedo_tag = "    [OBSTACULO DETECTADO]"
                        else:
                            dedo_tag = "    [LIBRE / SIN DEDO]"

                        if self.hw.skip_sensores:
                            est_txt = f"SIMULADO  [{barra_ascii}] {p_pct:5.1f}% ({d:2d} mm) {dedo_tag}"
                        elif ch in self.hw.bypass_canales:
                            est_txt = f"BYPASS    [..........]   0.0% (--- mm) [DEFECTUOSO / OMITIDO]"
                        elif self.hw.sensores[ch] is None or d >= 8000:
                            est_txt = f"FALLO I2C [..........]   0.0% (--- mm) [DESCONECTADO / CH{ch}]"
                        else:
                            est_txt = f"MIDIENDO  [{barra_ascii}] {p_pct:5.1f}% ({d:2d} mm) {dedo_tag}"
                        
                        print(f" * {est:<11} ({born}|{p}): {est_txt} | Bomba: {bomba_txt}")

                    print("-"*88)
                    plc_status_str = "CONECTADO OK" if self.cliente.is_open else "DESCONECTADO (Reintentando...)"
                    print(f" Enlace PLC Modbus ({self.plc_ip}:{self.plc_port}): {plc_status_str} | Watchdog: {self._contador_watchdog} | Flag 4: {hr_color}")
                    print("="*88 + "\n")

            except Exception as e:
                import traceback
                traceback.print_exc()

            time.sleep(1.0)

    def detener(self):
        self.corriendo = False
        self.animador_tiras.corriendo = False
        self.animador_semaforos.corriendo = False
        self.animador_tiras.join(timeout=1.0)
        self.animador_semaforos.join(timeout=1.0)
        if self.cliente.is_open:
            self.cliente.close()
        self.hw.limpiar()


def resolver_modo_sensores():
    """
    Permite saltearse los sensores I2C por CLI (--sin-sensores, -s),
    por variable de entorno (SKIP_SENSORES=1), o interactivamente al arrancar.
    """
    if os.environ.get("SKIP_SENSORES", "0").lower() in ("1", "true", "yes", "s"):
        return True
    for arg in sys.argv[1:]:
        if arg in ("--sin-sensores", "--skip-sensors", "-s"):
            return True
        if arg in ("--con-sensores", "-c"):
            return False

    if sys.stdin.isatty():
        try:
            import select
            print("\n" + "="*75)
            print("  [?] SELECCION DE MODO DE OPERACION:")
            print("      ¿Deseas SALTARTE la inicializacion de sensores fisicos I2C?")
            print("      -> Presiona 's' + Enter para SALTAR sensores (Modo Simulado)")
            print("      -> Presiona Enter o espera 5s para INICIAR CON SENSORES REALES")
            print("="*75)
            print("  Tu eleccion [s/N] (Auto-continua con sensores en 5s): ", end="", flush=True)
            rlist, _, _ = select.select([sys.stdin], [], [], 5.0)
            if rlist:
                line = sys.stdin.readline().strip().lower()
                if line in ("s", "si", "y", "yes", "1"):
                    print("  >> Opcion elegida: SALTEAR SENSORES I2C.\n")
                    return True
            print("\n  >> Continuando con deteccion de sensores fisicos...\n")
        except Exception:
            pass

    return False


if __name__ == "__main__":
    skip = resolver_modo_sensores()
    bypass = [2]  # Por omision se omite el Canal 2 (J20 / Estanque 1) por sensor defectuoso (igual que en moar_contexto)
    
    for arg in sys.argv[1:]:
        if arg in ("--con-todos", "--enable-all"):
            bypass = []

    print("==================================================")
    print("  INICIANDO DAEMON RTU - AGUAS DEL VALLE S.A.  ")
    print("==================================================")
    
    gateway = RtuHardwareGateway(skip_sensores=skip, bypass_canales=bypass)
    try:
        gateway.iniciar()
        print("[INFO] Daemon iniciado correctamente. Presiona CTRL+C para detener.")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Deteniendo el demonio de hardware...")
        gateway.detener()
        print("[INFO] Apagado completo.")
