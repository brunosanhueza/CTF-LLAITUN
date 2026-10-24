# -*- coding: utf-8 -*-
"""
DAEMON RTU - Sector 3 (CTF Aguas del Valle)
Gestion de hardware local (Sensores I2C VL53L0X, Bombas, Luces, Semaforos)
y comunicacion Modbus TCP con el PLC Siemens (10.10.30.103).


I2C corre en un proceso hijo exclusivo supervisado; el control solo consume RAM.
Los bloqueos del lector se recuperan con presupuesto de reinicios y cuarentena.
"""

import time
import threading
import logging
import os
import sys
from importlib import import_module
import statistics
import signal
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
_CONFIG_SENSORES_TOF = import_module("sensores-tof")
CANALES_SENSORES = list(_CONFIG_SENSORES_TOF.CANALES)
CANALES_BYPASS_TOF = list(_CONFIG_SENSORES_TOF.CANALES_BYPASS)

DIST_VACIO_MM = 60
DIST_LLENO_MM = 46

# Geometría real por estanque rectificada según escala física de la maqueta
# Canal 0: Estanque 2 (J18, Bomba P2) - Vacío: 119 mm, Lleno (100%): 88.0 mm (Delta 31 mm)
# Canal 1: Estanque 4 (J19, Bomba P4) - Vacío: 99 mm,  Lleno (100%): 68.0 mm (Delta 31 mm)
# Canal 2: Estanque 1 (J20, Bomba P1 - Sensor físico defectuoso / Bypass)
# Canal 3: Estanque 3 (J21, Bomba P3) - Vacío: 60 mm,  80%: 42.4 mm, Lleno (100%): 38.0 mm (Delta 22 mm)
GEOMETRIA_ESTANQUES = {
    0: {"vacio": 128.0, "lleno": 94.0},   # Canal 0: Estanque 2 (128 mm = vacío 0% en el PLC)
    1: {"vacio": 99.0,  "lleno": 65.0},   # Canal 1: Estanque 4 (99 mm = vacío 0% en el PLC)
    2: {"vacio": 150.0, "lleno": 116.0},  # Canal 2: Estanque 1 (Bypass)
    3: {"vacio": 71.0,  "lleno": 38.0},   # Canal 3: Estanque 3 (71 mm = vacío 0% en el PLC)
}

CALIB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calibracion_estanques.json")
if os.path.exists(CALIB_FILE):
    try:
        import json
        with open(CALIB_FILE, "r") as f:
            _calib = json.load(f)
            for k, v in _calib.items():
                c = int(k)
                if c in GEOMETRIA_ESTANQUES:
                    if "vacio" in v: GEOMETRIA_ESTANQUES[c]["vacio"] = float(v["vacio"])
                    if "lleno" in v: GEOMETRIA_ESTANQUES[c]["lleno"] = float(v["lleno"])
        logger.info(f"Geometria calibrada cargada desde {CALIB_FILE}")
    except Exception as e:
        logger.warning(f"No se pudo cargar {CALIB_FILE}: {e}")

def calcular_pct_canal(canal, mm, dist_base=None):
    if mm is None or mm >= 8000 or mm <= 0:
        return 0.0
    geom = GEOMETRIA_ESTANQUES.get(canal, {"vacio": DIST_VACIO_MM, "lleno": DIST_LLENO_MM})
    vacio = float(dist_base if dist_base is not None else geom["vacio"])
    lleno = float(geom["lleno"])
    if vacio <= lleno:
        return 0.0
    # Zona muerta de 2 mm contra ruido/vibraciones en reposo (garantiza 0% cuando está libre)
    if mm >= (vacio - 2):
        return 0.0
    # Si la distancia medida es igual o menor a la distancia de lleno (o dedo cerca), salta inmediatamente a 100%
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

from i2c_supervisor import SupervisorI2C

try:
    import RPi.GPIO as GPIO
    HARDWARE_REAL = True
except ImportError:
    HARDWARE_REAL = False
    logger.warning("Simulacion activa (RPi.GPIO no disponible).")

try:
    from rpi_ws281x import ws
    HAY_TIRAS = True
except ImportError:
    HAY_TIRAS = False


class HardwareManager:
    def __init__(self, skip_sensores: bool = False, bypass_canales: list = None):
        self.skip_sensores = skip_sensores
        # Por omision se omite el Canal 2 (J20 / Estanque 1) por sensor defectuoso en placa
        self.bypass_canales = (list(CANALES_BYPASS_TOF) if bypass_canales is None
                               else list(bypass_canales))
        self._sensor_lock = threading.Lock()
        self.supervisor_i2c = None
        self.estado_sensores = {}
        self.leds = None
        self.canales_ws = []
        self.n_leds_tira = 120
        
        self.modo_manual_bombas = False
        self.estado_bombas = [False, False, False, False]
        self.niveles_simulados = [0.0, 0.0, 0.0, 0.0]
        self.ultimo_latido_sensores = time.monotonic()

        # Distancias base de reposo (Auto-tara / Linea base)
        # Se calibran automaticamente al inicio con la primera lectura valida de cada estanque
        self.distancias_base = {
            0: GEOMETRIA_ESTANQUES[0]["vacio"],  # ~119 mm (Estanque 2)
            1: GEOMETRIA_ESTANQUES[1]["vacio"],  # ~99 mm  (Estanque 4)
            2: GEOMETRIA_ESTANQUES[2]["vacio"],  # 150 mm  (Estanque 1 / Bypass)
            3: GEOMETRIA_ESTANQUES[3]["vacio"],  # ~60 mm  (Estanque 3)
        }

        # Cache compartida de lecturas en RAM (Opcion C)
        self._cache_distancias_mm = [
            self.distancias_base[0],
            self.distancias_base[1],
            self.distancias_base[2],
            self.distancias_base[3]
        ]
        self._cache_pct = [0.0, 0.0, 0.0, 0.0]
        self._snapshot_sensores = {}
        self._salidas_lock = threading.Lock()
        self._estado_luminarias = False
        self._estado_semaforos = {}
        self._cerrando = False

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

        if HARDWARE_REAL and not self.skip_sensores:
            self.supervisor_i2c = SupervisorI2C(self.bypass_canales)
        self.leer_instantanea_sensores()

    def iniciar(self):
        if self.supervisor_i2c is not None:
            self.supervisor_i2c.start()

    def reiniciar_bus_hardware(self):
        """Compatibilidad: pedir recuperacion; nunca abrir I2C en el padre."""
        if self.supervisor_i2c is not None:
            self.supervisor_i2c.request_restart()

    def reiniciar_hilo_sensores(self):
        self.reiniciar_bus_hardware()

    def leer_instantanea_sensores(self):
        if self.supervisor_i2c is not None:
            snapshot = self.supervisor_i2c.snapshot()
        else:
            snapshot = {}
            for c, pct in enumerate(self.niveles_simulados):
                geom = GEOMETRIA_ESTANQUES[c]
                mm = int(geom["vacio"] - pct / 100.0 * (geom["vacio"] - geom["lleno"]))
                snapshot[c] = {"state": "BYPASS" if c in self.bypass_canales else "OK",
                               "mm": mm, "timestamp": time.monotonic(), "error": ""}
        with self._sensor_lock:
            for c, sample in snapshot.items():
                if sample["state"] == "BYPASS":
                    self._cache_distancias_mm[c] = self.distancias_base[c]
                    self._cache_pct[c] = 0.0
                elif sample["mm"] is not None:
                    self._cache_distancias_mm[c] = sample["mm"]
                    self._cache_pct[c] = calcular_pct_canal(c, sample["mm"], self.distancias_base[c])
                self.estado_sensores[c] = sample["state"]
            self._snapshot_sensores = snapshot
        return snapshot

    def set_bomba(self, indice: int, activa: bool, forzar=False):
        with self._salidas_lock:
            if self._cerrando and activa:
                return
            if self.estado_bombas[indice] == activa and not (forzar and self._cerrando):
                return
            if HARDWARE_REAL:
                GPIO.output(RELES_BOMBAS[indice], GPIO.LOW if activa else GPIO.HIGH)
            self.estado_bombas[indice] = activa

    def set_bombas(self, activas: bool, forzar=False):
        if forzar or not self.modo_manual_bombas:
            for i in range(4):
                self.set_bomba(i, activas, forzar=forzar)

    def set_luminarias(self, activas: bool):
        with self._salidas_lock:
            if self._cerrando and activas:
                return
            if self._estado_luminarias == activas:
                return
            if HARDWARE_REAL:
                GPIO.output(LUMINARIAS, GPIO.HIGH if activas else GPIO.LOW)
            self._estado_luminarias = activas

    def set_semaforo(self, id_sem: int, color: str):
        with self._salidas_lock:
            if self._estado_semaforos.get(id_sem) == color:
                return
            if HARDWARE_REAL:
                sem = SEMAFORO_1 if id_sem == 1 else SEMAFORO_2
                # Primero apagar, para no dejar dos colores durante el cambio.
                GPIO.output(list(sem.values()), GPIO.HIGH)
                GPIO.output(sem[color], GPIO.LOW)
            self._estado_semaforos[id_sem] = color

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
        if getattr(self, 'override_niveles', None) is not None:
            return list(self.override_niveles)
        snapshot = self.leer_instantanea_sensores()
        with self._sensor_lock:
            return [self._cache_pct[c] if snapshot[c]["state"] == "OK" else 0.0
                    for c in range(4)]

    def leer_distancias_mm(self):
        snapshot = self.leer_instantanea_sensores()
        with self._sensor_lock:
            return [self._cache_distancias_mm[c] if snapshot[c]["state"] in ("OK", "BYPASS")
                    else 8190 for c in range(4)]

    def actualizar_simulacion(self, bombas_activas):
        if not HARDWARE_REAL or self.skip_sensores:
            ahora = time.monotonic()
            dt = ahora - getattr(self, '_ultimo_tiempo_sim', ahora)
            self._ultimo_tiempo_sim = ahora
            if dt <= 0 or dt > 5.0:
                dt = 1.0

            if getattr(self, 'override_niveles', None) is not None:
                self.niveles_simulados = self.override_niveles.copy()
            else:
                # Dinámica de fluidos real calibrada:
                # - 18 segundos de 0% a 100% -> 100.0 / 18.0 = 5.556% por segundo con bomba activa
                # - Drenaje gradual cuando la bomba se apaga: ~3.33% por segundo (vaciado en ~30s)
                # - Límite de seguridad estimado: 75% (a los 13.5 segundos de llenado continuo)
                TASA_LLENADO_S = 100.0 / 18.0
                TASA_DRENAJE_S = 100.0 / 30.0

                # Mapeo de canal I2C al índice de bomba en self.estado_bombas:
                # Canal 0 (Estanque 2) -> Bomba P2 (idx 1)
                # Canal 1 (Estanque 4) -> Bomba P4 (idx 3)
                # Canal 2 (Estanque 1) -> Bomba P1 (idx 0)
                # Canal 3 (Estanque 3) -> Bomba P3 (idx 2)
                mapa_canal_bomba = {0: 1, 1: 3, 2: 0, 3: 2}

                for c in range(4):
                    if c in self.bypass_canales:
                        self.niveles_simulados[c] = 0.0
                        continue
                    idx_bomba = mapa_canal_bomba.get(c, c)
                    bomba_on = self.estado_bombas[idx_bomba] if idx_bomba < len(self.estado_bombas) else False

                    if bomba_on:
                        delta = TASA_LLENADO_S * dt
                    else:
                        delta = -TASA_DRENAJE_S * dt

                    self.niveles_simulados[c] = max(0.0, min(100.0, round(self.niveles_simulados[c] + delta, 2)))

    def limpiar(self):
        if self.supervisor_i2c is not None:
            self.supervisor_i2c.stop()
            if self.supervisor_i2c.ident is not None:
                self.supervisor_i2c.join(timeout=3.0)
                if self.supervisor_i2c.is_alive():
                    logger.error("Supervisor I2C no termino durante el cierre")
        if HARDWARE_REAL:
            self.set_bombas(False, forzar=True)
            self.set_luminarias(False)
            self.set_semaforo(1, "rojo")
            self.set_semaforo(2, "rojo")
            pines = [p for pins in RELES_BOMBAS.values() for p in pins]
            GPIO.cleanup(pines + LUMINARIAS + list(SEMAFORO_1.values()) + list(SEMAFORO_2.values()))
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
        self._parar_control = threading.Event()
        self._hilo_control = None
        self._detenido = False
        self._ultimo_error_control = 0.0

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
            if self._detenido:
                raise RuntimeError("Un gateway detenido no se puede volver a iniciar")
            self.corriendo = True
            # El supervisor arranca el proceso exclusivo I2C.
            self.hw.iniciar()
            self.animador_tiras.start()
            self.animador_semaforos.start()
            self._hilo_control = threading.Thread(target=self._bucle_control, name="control-modbus", daemon=True)
            self._hilo_control.start()

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
        Bucle Modbus y control. Espera 1s entre ciclos; la red tiene su timeout.
        Nunca abre I2C ni espera la recuperacion del proceso lector.
        """
        loop_counter = 0
        ultima_telemetria = 0.0
        telemetria_config = os.environ.get("RTU_TELEMETRIA")
        if telemetria_config is None:
            intervalo_telemetria = 10.0
        elif telemetria_config.strip().lower() in ("", "0", "false", "no", "off"):
            intervalo_telemetria = None
        elif telemetria_config.strip().lower() in ("1", "true", "yes", "on"):
            intervalo_telemetria = 2.0
        else:
            try:
                intervalo_telemetria = max(1.0, float(telemetria_config))
            except ValueError:
                intervalo_telemetria = 10.0
        while self.corriendo:
            try:
                self.hw.actualizar_simulacion(self._estado_bombas_local)

                # Solo copiar RAM. El supervisor recupera al hijo por su cuenta.
                snapshot = self.hw.leer_instantanea_sensores()
                distancias_crudas = [snapshot[c]["mm"] if snapshot[c]["state"] == "OK"
                                     else 8190 for c in range(4)]
                canales_validos = {c for c in range(4) if snapshot[c]["state"] in ("OK", "BYPASS")}
                max_pct_calculado = 0.0
                bits_alto_sensores = 0

                distancias_suavizadas = []
                porcentajes_calculados = []
                for i in range(4):
                    dist_cruda = distancias_crudas[i]
                    geom = GEOMETRIA_ESTANQUES.get(i, {"vacio": DIST_VACIO_MM, "lleno": DIST_LLENO_MM})
                    base_vacio = self.hw.distancias_base.get(i, geom["vacio"])

                    if i in self.hw.bypass_canales:
                        self.historial_distancias[i].clear()
                        promedio = base_vacio
                        pct = 0.0
                    elif dist_cruda < 8000:
                        self.historial_distancias[i].append(dist_cruda)
                        if len(self.historial_distancias[i]) > self.max_muestras:
                            self.historial_distancias[i].pop(0)
                        # Filtro de mediana móvil: descarta picos espurios y anomalías
                        promedio = int(round(statistics.median(self.historial_distancias[i])))
                        pct = calcular_pct_canal(i, promedio, dist_base=base_vacio)
                    else:
                        # Fuera de rango o lectura inválida: limpiar historial para que el obstáculo no quede pegado
                        self.historial_distancias[i].clear()
                        promedio = 8190
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
                    # Conversión estricta a enteros de 16 bits para pyModbusTCP en Python 3.13
                    registros_sensores = [max(0, min(65535, int(round(x)))) for x in registros_sensores]
                    # No presentar fallos como estanque vacio. Conservar en el PLC
                    # el ultimo dato, avisando su invalidez mediante HR41 != 0.
                    escritura_ok = True
                    if len(canales_validos) == 4:
                        escritura_ok = self.cliente.write_multiple_registers(21, registros_sensores)
                    else:
                        for indice, canal in enumerate((2, 0, 3, 1)):
                            if canal in canales_validos:
                                ok = self.cliente.write_multiple_registers(21 + 2 * indice,
                                                                          registros_sensores[2 * indice:2 * indice + 2])
                                escritura_ok = bool(ok) and escritura_ok
                    hay_error_sensor = any(c not in canales_validos for c in range(4))
                    self.cliente.write_single_register(41, int(hay_error_sensor or not escritura_ok))

                    # Watchdog
                    self._contador_watchdog = (self._contador_watchdog + 1) & 0xFFFF
                    self.cliente.write_single_register(40, self._contador_watchdog)

                    # Leer comandos del PLC
                    regs_bombas = self.cliente.read_holding_registers(0, 1)
                    regs_color = self.cliente.read_holding_registers(10, 1)

                    if regs_bombas and regs_color:
                        hr_bombas = regs_bombas[0]
                        hr_color = regs_color[0]

                        mascara_valida = sum(1 << self.map_alto[c] for c in canales_validos)
                        nuevo_hr0 = (hr_bombas & ~mascara_valida) | bits_alto_sensores
                        if nuevo_hr0 != hr_bombas:
                            self.cliente.write_single_register(0, nuevo_hr0)

                        b1 = bool((hr_bombas >> 9) & 1)
                        b2 = bool((hr_bombas >> 11) & 1)
                        b3 = bool((hr_bombas >> 13) & 1)
                        b4 = bool((hr_bombas >> 15) & 1)

                        if self._parar_control.is_set():
                            break
                        self.hw.set_bomba(0, b1)
                        self.hw.set_bomba(1, b2)
                        self.hw.set_bomba(2, b3)
                        self.hw.set_bomba(3, b4)
                        
                        self._estado_bombas_local = b1 or b2 or b3 or b4
                        self.hw.set_luminarias(hr_color != 0)
                        self._actualizar_luces(hr_color, max_pct_calculado)
                    else:
                        self.hw.set_bombas(False, forzar=True)
                        self._estado_bombas_local = False
                else:
                    self.hw.set_bombas(False, forzar=True)
                    self._estado_bombas_local = False
                    self.hw.set_luminarias(False)
                    self.animador_tiras.modo_parpadeo = False
                    self.animador_tiras.color_t1 = (255, 0, 255)
                    self.animador_tiras.color_t2 = (255, 0, 255)

                # Reporte por consola mas entendible y frecuente con barras de progreso
                loop_counter += 1
                if loop_counter == 1 or loop_counter % 30 == 0:
                    logger.info("Control activo: PLC=%s; sensores validos=%d/4 (incluye bypass)",
                                self.cliente.is_open, len(canales_validos))
                ahora_monotonic = time.monotonic()
                if (intervalo_telemetria is not None and
                        (loop_counter == 1 or ahora_monotonic - ultima_telemetria >= intervalo_telemetria)):
                    ultima_telemetria = ahora_monotonic
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
                            est_txt = f"SIMULADO  [{barra_ascii}] {p_pct:5.1f}% ({int(round(d)):2d} mm) {dedo_tag}"
                        elif ch in self.hw.bypass_canales:
                            est_txt = f"BYPASS    [..........]   0.0% (--- mm) [DEFECTUOSO / OMITIDO]"
                        elif snapshot[ch]["state"] != "OK":
                            est_txt = f"SIN DATO  [..........]    ---  (--- mm) [{snapshot[ch]['state']} / CH{ch}]"
                        else:
                            est_txt = f"MIDIENDO  [{barra_ascii}] {p_pct:5.1f}% ({int(round(d)):2d} mm) {dedo_tag}"
                        
                        print(f" * {est:<11} ({born}|{p}): {est_txt} | Bomba: {bomba_txt}")
                        if (not self.hw.skip_sensores
                                and snapshot[ch]["state"] == "ERROR"
                                and snapshot[ch].get("error")):
                            detalle_i2c = " ".join(str(snapshot[ch]["error"]).split())[:160]
                            print(f"     Diagnostico I2C CH{ch}: {detalle_i2c}")

                    print("-"*88)
                    plc_status_str = "CONECTADO OK" if self.cliente.is_open else "DESCONECTADO (Reintentando...)"
                    print(f" Enlace PLC Modbus ({self.plc_ip}:{self.plc_port}): {plc_status_str} | Watchdog: {self._contador_watchdog} | Flag 4: {hr_color}")
                    print("="*88 + "\n")

            except Exception as e:
                self.hw.set_bombas(False, forzar=True)
                self._estado_bombas_local = False
                if time.monotonic() - self._ultimo_error_control >= 30.0:
                    logger.exception("Error en control Modbus; bombas apagadas")
                    self._ultimo_error_control = time.monotonic()

            self._parar_control.wait(1.0)

    def detener(self):
        if self._detenido:
            return
        self._detenido = True
        self.corriendo = False
        self._parar_control.set()
        with self.hw._salidas_lock:
            self.hw._cerrando = True
        self.hw.set_bombas(False, forzar=True)
        self.hw.set_luminarias(False)
        if self.hw.supervisor_i2c is not None:
            self.hw.supervisor_i2c.stop()
            if self.hw.supervisor_i2c.ident is not None:
                self.hw.supervisor_i2c.join(timeout=3.0)
        self.animador_tiras.corriendo = False
        self.animador_semaforos.corriendo = False
        # Un cliente puede seguir dentro de una operacion de red: esperar antes
        # de liberar GPIO/DMA evita escrituras sobre recursos ya cerrados.
        if self._hilo_control is not None:
            self._hilo_control.join(timeout=15.0)
            if self._hilo_control.is_alive():
                self.hw.set_bombas(False, forzar=True)
                logger.error("Control no termino: se conservan recursos hasta salir")
                return
        for hilo in (self.animador_tiras, self.animador_semaforos):
            if hilo.ident is not None:
                hilo.join(timeout=2.0)
                if hilo.is_alive():
                    self.hw.set_bombas(False, forzar=True)
                    logger.error("Animador no termino: se conservan recursos hasta salir")
                    return
        self.cliente.close()
        self.hw.limpiar()


def resolver_modo_sensores():
    """
    Permite saltearse los sensores I2C por CLI (--virtual, --sin-sensores, --skip-sensors, -s, -v),
    por variable de entorno (SKIP_SENSORES=1 o VIRTUAL=1), o interactivamente al arrancar.
    """
    if os.environ.get("SKIP_SENSORES", "0").lower() in ("1", "true", "yes", "s") or \
       os.environ.get("VIRTUAL", "0").lower() in ("1", "true", "yes", "s"):
        return True
    for arg in sys.argv[1:]:
        if arg in ("--virtual", "-v", "--sin-sensores", "--skip-sensors", "-s"):
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


def main():
    skip = resolver_modo_sensores()
    bypass = [2]  # Por omision se omite el Canal 2 (J20 / Estanque 1) por sensor defectuoso (igual que en moar_contexto)
    
    for arg in sys.argv[1:]:
        if arg in ("--con-todos", "--enable-all"):
            bypass = []

    print("==================================================")
    print("  INICIANDO DAEMON RTU - AGUAS DEL VALLE S.A.  ")
    print("==================================================")
    
    gateway = RtuHardwareGateway(skip_sensores=skip, bypass_canales=bypass)
    salida = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: salida.set())
    try:
        gateway.iniciar()
        print("[INFO] Daemon iniciado correctamente. Presiona CTRL+C para detener.")
        while not salida.wait(1.0):
            if gateway._hilo_control is not None and not gateway._hilo_control.is_alive():
                raise RuntimeError("El hilo de control termino inesperadamente")
    finally:
        gateway.detener()


if __name__ == "__main__":
    main()
