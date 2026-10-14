# -*- coding: utf-8 -*-
"""
TEST DAEMON (Modo Diagnostico) - Sector 3 (CTF Aguas del Valle)
Gestion de hardware local (Sensores I2C VL53L0X, Bombas, Luces, Semaforos)
y comunicacion Modbus TCP con el PLC Siemens (10.10.30.100).
 (Canal 2 / Estanque 1 en Bypass por defecto)

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
from pyModbusTCP.client import ModbusClient

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
    OPCION C: Hilo en segundo plano exclusivo para interrogar sensores I2C.
    Mantiene una cache en memoria de las ultimas lecturas validas.
    OPCION B: Incorpora vigilancia de congelamiento de bus y auto-reset por GPIO 17.
    """
    def __init__(self, hw):
        super().__init__(daemon=True)
        self.hw = hw
        self.corriendo = True
        self.lock = threading.Lock()
        self.bus_freeze_count = 0

    def _medir_con_timeout(self, sensor, timeout_s=0.35):
        """Lectura con timeout estricto para evitar bloqueos del driver de Adafruit."""
        resultado = [None]
        error = [None]

        def _worker():
            try:
                resultado[0] = sensor.range
            except Exception as e:
                error[0] = e

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        t.join(timeout_s)

        if t.is_alive():
            raise TimeoutError(f"TIMEOUT > {timeout_s}s en bus I2C")
        if error[0]:
            raise error[0]
        return resultado[0]

    def _calcular_pct(self, mm):
        vacio = DIST_VACIO_MM
        lleno = DIST_LLENO_MM
        if mm > 8000: return 0.0
        if vacio == lleno: return 0.0
        pct = (vacio - mm) / (vacio - lleno) * 100.0
        return max(0.0, min(100.0, pct))

    def run(self):
        while self.corriendo:
            if self.hw.skip_sensores or not HARDWARE_REAL:
                # Actualizar cache con datos de la simulacion
                with self.lock:
                    for i in range(4):
                        pct = self.hw.niveles_simulados[i]
                        mm = int(DIST_VACIO_MM - (pct / 100.0) * (DIST_VACIO_MM - DIST_LLENO_MM))
                        self.hw._cache_distancias_mm[i] = max(15, min(60, mm))
                        self.hw._cache_pct[i] = pct
                time.sleep(0.2)
                continue

            # Modo Hardware Real: barrido de sensores I2C
            lecturas_validas = 0
            sensores_habilitados = 0

            for c in CANALES_SENSORES:
                if not self.corriendo: break

                if c in self.hw.bypass_canales:
                    with self.lock:
                        self.hw._cache_distancias_mm[c] = 8190
                        self.hw._cache_pct[c] = 0.0
                        self.hw.estado_sensores[c] = "BYPASS (Omitido)"
                    continue

                sensor = self.hw.sensores[c]
                if sensor is None:
                    with self.lock:
                        self.hw._cache_distancias_mm[c] = 8190
                        self.hw._cache_pct[c] = 0.0
                    continue

                sensores_habilitados += 1

                try:
                    dist = self._medir_con_timeout(sensor, timeout_s=0.35)
                    if dist > 8000:
                        with self.lock:
                            self.hw._cache_distancias_mm[c] = 8190
                            self.hw._cache_pct[c] = 0.0
                            self.hw.estado_sensores[c] = f"FUERA DE RANGO ({dist} mm)"
                    else:
                        pct = self._calcular_pct(dist)
                        with self.lock:
                            self.hw._cache_distancias_mm[c] = dist
                            self.hw._cache_pct[c] = pct
                            self.hw.estado_sensores[c] = f"MIDIENDO OK ({dist} mm)"
                        lecturas_validas += 1

                except TimeoutError:
                    with self.lock:
                        self.hw._cache_distancias_mm[c] = 8190
                        self.hw._cache_pct[c] = 0.0
                        self.hw.estado_sensores[c] = "TIMEOUT EN LECTURA (>0.35s)"
                except Exception as e:
                    with self.lock:
                        self.hw._cache_distancias_mm[c] = 8190
                        self.hw._cache_pct[c] = 0.0
                        self.hw.estado_sensores[c] = f"ERROR LECTURA ({e})"

            # ================================================================
            # OPCION B: DETECCION DE BUS CONGELADO Y AUTO-RECUPERACION GPIO 17
            # ================================================================
            if sensores_habilitados > 0 and lecturas_validas == 0:
                self.bus_freeze_count += 1
                if self.bus_freeze_count >= 3:
                    logger.warning("[AUTO-RECUPERACION] Bus I2C congelado detectado. Aplicando pulso de Reset fisico en GPIO 17...")
                    self.hw.reiniciar_bus_hardware()
                    self.bus_freeze_count = 0
            else:
                self.bus_freeze_count = 0

            time.sleep(0.15)


class HardwareManager:
    def __init__(self, skip_sensores: bool = False, bypass_canales: list = None):
        self.skip_sensores = skip_sensores
        self.bypass_canales = bypass_canales or []
        self.sensores = [None, None, None, None]
        self.estado_sensores = {}
        self.leds = None
        self.canales_ws = []
        self.n_leds_tira = 120
        
        self.modo_manual_bombas = False
        self.estado_bombas = [False, False, False, False]
        self.niveles_simulados = [25.0, 25.0, 25.0, 25.0]

        # Cache compartida de lecturas en RAM (Opcion C)
        self._cache_distancias_mm = [50, 50, 50, 50]
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
                    GPIO.setup(MUX_RST_PIN, GPIO.OUT, initial=GPIO.HIGH)
                    GPIO.output(MUX_RST_PIN, GPIO.LOW)
                    time.sleep(0.01)
                    GPIO.output(MUX_RST_PIN, GPIO.HIGH)
                    time.sleep(0.05)
                    
                    self.i2c = busio.I2C(board.SCL, board.SDA)
                    self.mux = adafruit_tca9548a.TCA9548A(self.i2c, address=MUX_ADDRESS)
                    
                    print("\n" + "="*85)
                    print("         DIAGNOSTICO DE HARDWARE: ESCANEO DE SENSORES I2C (TCA9548A @ 0x70)         ")
                    print(" Bus I2C: SDA (GPIO 2, Pin 3) | SCL (GPIO 3, Pin 5) | Reset MUX: GPIO 17 (Pin 11)   ")
                    print("="*85)
                    
                    def init_sensor_con_timeout(c):
                        res = [None]
                        exc = [None]
                        def _worker():
                            try:
                                res[0] = VL53L0X(self.mux[c])
                            except Exception as err:
                                exc[0] = err
                        t = threading.Thread(target=_worker, daemon=True)
                        t.start()
                        t.join(10.0)
                        if t.is_alive():
                            raise TimeoutError("TIMEOUT > 10s (Sensor congelado / Falla de bus)")
                        if exc[0]:
                            raise exc[0]
                        return res[0]

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
                            self.estado_sensores[canal] = "BYPASS (Deshabilitado intencionalmente)"
                            print(f"   [-] ESTADO: BYPASS / OMITIDO POR CONFIGURACION\n")
                            continue

                        print(f"   -> Verificando comunicacion I2C (espera max 10s)...", end="", flush=True)

                        try:
                            sensor = init_sensor_con_timeout(canal)
                            dist_test = sensor.range
                            if dist_test > 8000:
                                self.estado_sensores[canal] = f"CONECTADO PERO FUERA DE RANGO ({dist_test} mm)"
                                print(f"\r   [!] ADVERTENCIA: Responde I2C pero lectura fuera de rango ({dist_test} mm)\n")
                            else:
                                self.estado_sensores[canal] = f"OPERATIVO (Midiendo {dist_test} mm)"
                                print(f"\r   [+] OPERATIVO: Sensor OK | Medida inicial: {dist_test} mm\n")
                            self.sensores[canal] = sensor
                        except TimeoutError:
                            self.sensores[canal] = None
                            self.estado_sensores[canal] = "FALLO CRITICO: TIMEOUT > 10s"
                            print(f"\r   [X] FALLO CRITICO: TIMEOUT > 10s. Sensor no responde en bornera {born}.\n")
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
        if not HARDWARE_REAL: return
        try:
            GPIO.output(MUX_RST_PIN, GPIO.LOW)
            time.sleep(0.02)
            GPIO.output(MUX_RST_PIN, GPIO.HIGH)
            time.sleep(0.05)
            
            self.mux = adafruit_tca9548a.TCA9548A(self.i2c, address=MUX_ADDRESS)
            for c in CANALES_SENSORES:
                if c not in self.bypass_canales:
                    try:
                        self.sensores[c] = VL53L0X(self.mux[c])
                        self.estado_sensores[c] = "RECONECTADO (Post-Reset)"
                    except Exception:
                        self.sensores[c] = None
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
        self.plc_ip = os.environ.get("PLC_HOST", "10.10.30.100")
        self.plc_port = int(os.environ.get("PLC_PORT", 502))
        
        self.cliente = ModbusClient(host=self.plc_ip, port=self.plc_port, auto_open=True, timeout=2.0)
        self.hw = HardwareManager(skip_sensores=skip_sensores, bypass_canales=bypass_canales)
        self.animador_tiras = AnimadorTiras(self.hw)
        self.animador_semaforos = AnimadorSemaforos(self.hw)
        
        self.corriendo = False
        self._contador_watchdog = 0
        self._estado_bombas_local = False

        self.historial_distancias = {0: [], 1: [], 2: [], 3: []}
        self.max_muestras = 5
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
        vacio = DIST_VACIO_MM
        lleno = DIST_LLENO_MM
        if mm > 8000: return 0.0
        if vacio == lleno: return 0.0
        pct = (vacio - mm) / (vacio - lleno) * 100.0
        return max(0.0, pct)

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
                for i in range(4):
                    dist_cruda = distancias_crudas[i]
                    if dist_cruda < 8000:
                        self.historial_distancias[i].append(dist_cruda)
                        if len(self.historial_distancias[i]) > self.max_muestras:
                            self.historial_distancias[i].pop(0)
                    
                    if len(self.historial_distancias[i]) > 0:
                        promedio = int(sum(self.historial_distancias[i]) / len(self.historial_distancias[i]))
                    else:
                        promedio = 50 if not self.hw.skip_sensores else dist_cruda
                        
                    distancias_suavizadas.append(promedio)

                    pct = self._calcular_pct_local(promedio)
                    if pct > max_pct_calculado:
                        max_pct_calculado = pct

                    if pct >= 100.0:
                        self.segundos_desbordados[i] += 1
                    else:
                        self.segundos_desbordados[i] = 0

                    if self.segundos_desbordados[i] >= 10:
                        bits_alto_sensores |= (1 << self.map_alto[i])

                pct_p1 = int(self._calcular_pct_local(distancias_suavizadas[2]))
                pct_p2 = int(self._calcular_pct_local(distancias_suavizadas[0]))
                pct_p3 = int(self._calcular_pct_local(distancias_suavizadas[3]))
                pct_p4 = int(self._calcular_pct_local(distancias_suavizadas[1]))

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

                # Reporte por consola en el primer ciclo y luego cada 5 segundos
                loop_counter += 1
                if loop_counter == 1 or loop_counter % 5 == 0:
                    ahora = time.strftime("%H:%M:%S")
                    print("\n" + "="*88)
                    print(f"[*] DIAGNOSTICO Y TELEMETRIA EN TIEMPO REAL [{ahora}]")
                    print("="*88)

                    orden_diagnostico = [
                        (2, "Estanque 1", "J20", "P1", [4, 5], distancias_suavizadas[2], pct_p1, b1),
                        (0, "Estanque 2", "J18", "P2", [6, 7], distancias_suavizadas[0], pct_p2, b2),
                        (3, "Estanque 3", "J21", "P3", [27, 19], distancias_suavizadas[3], pct_p3, b3),
                        (1, "Estanque 4", "J19", "P4", [26, 12], distancias_suavizadas[1], pct_p4, b4),
                    ]

                    for ch, est, born, p, gpios, d, p_pct, b_st in orden_diagnostico:
                        bomba_txt = "ENCENDIDA (ON)" if b_st else "APAGADA (OFF)"
                        if self.hw.skip_sensores:
                            est_txt = f"SIMULADO        | {d:4d} mm -> {p_pct:5.1f}%"
                        elif self.hw.sensores[ch] is None or d >= 8000:
                            est_txt = f"FALLO / NO MIDE | {d:4d} mm -> {0.0:5.1f}% [I2C Ch{ch} DAÑADO]"
                        else:
                            est_txt = f"MIDIENDO OK     | {d:4d} mm -> {p_pct:5.1f}% [I2C Ch{ch} ACTIVO]"
                        
                        print(f" * {est} [Bornera {born} | Bomba {p} GPIO {gpios}]: {est_txt} | Bomba: {bomba_txt}")

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
    bypass = [2]
    
    for arg in sys.argv[1:]:
        if arg in ("--con-todos", "--enable-all"):
            bypass = []

    print("==================================================")
    print("  INICIANDO TEST DAEMON (MODO DIAGNOSTICO) - AGUAS DEL VALLE S.A.  ")
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
