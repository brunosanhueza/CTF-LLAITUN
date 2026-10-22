import time
import logging

logger = logging.getLogger(__name__)

HARDWARE_AVAILABLE = False
_tca = None
_sensores = [None, None, None, None]

PIN_MUX_RESET = 17
CANALES_BYPASS = [2]  # Canal 2 (Estanque 1 / Bornera J20) averiado fisicamente; omitir

GEOMETRIA_ESTANQUES = {
    0: {"vacio_mm": 128.0, "lleno_mm": 94.25, "nombre": "Estanque 2 (Canal 0)"},
    1: {"vacio_mm": 85.0,  "lleno_mm": 51.25, "nombre": "Estanque 4 (Canal 1)"},
    2: {"vacio_mm": 150.0, "lleno_mm": 116.25,"nombre": "Estanque 1 (Canal 2 / BYPASS)"},
    3: {"vacio_mm": 60.0,  "lleno_mm": 38.0,  "nombre": "Estanque 3 (Canal 3)"},
}

def reset_multiplexor():
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)
        GPIO.setup(PIN_MUX_RESET, GPIO.OUT, initial=GPIO.HIGH)
        time.sleep(0.02)
        GPIO.output(PIN_MUX_RESET, GPIO.LOW)
        time.sleep(0.05)
        GPIO.output(PIN_MUX_RESET, GPIO.HIGH)
        time.sleep(0.05)
        logger.info(f"Multiplexor TCA9548A reseteado via GPIO {PIN_MUX_RESET}.")
    except Exception as e:
        logger.warning(f"No se pudo resetear multiplexor por GPIO {PIN_MUX_RESET}: {e}")

try:
    reset_multiplexor()
    import board
    import busio
    import adafruit_vl53l0x
    import adafruit_tca9548a

    i2c = busio.I2C(board.SCL, board.SDA)
    _tca = adafruit_tca9548a.TCA9548A(i2c, address=0x70)

    # Sensores en canales 0, 1, 2 y 3 del multiplexor
    for i in range(4):
        if i in CANALES_BYPASS:
            logger.info(f"Canal {i} en bypass por sensor defectuoso (omitido).")
            continue
        try:
            sensor = adafruit_vl53l0x.VL53L0X(_tca[i])
            sensor.measurement_timing_budget = 33000
            sensor.io_timeout_s = 0.5
            _sensores[i] = sensor
            logger.info(f"Sensor ToF inicializado en canal {i}.")
        except Exception as e:
            logger.error(f"No se encontro sensor en canal {i}: {e}")

    HARDWARE_AVAILABLE = any(s is not None for s in _sensores)
except Exception as e:
    logger.error(f"Error inicializando I2C/TCA9548A: {e}")
    HARDWARE_AVAILABLE = False


class BancoSensoresToF:
    def __init__(self, geometria: dict = None):
        self.geometria = geometria or GEOMETRIA_ESTANQUES
        self._niveles_simulados_pct = [25.0, 25.0, 25.0, 25.0]
        self.es_hardware = HARDWARE_AVAILABLE

    def leer_distancias_mm(self) -> list:
        distancias = [125.0, 45.0, 150.0, 65.0]
        for i in range(4):
            if self.es_hardware and _sensores[i] is not None:
                try:
                    dist = _sensores[i].range
                    if 0 < dist < 2000:
                        distancias[i] = float(dist)
                        continue
                except Exception as e:
                    logger.error(f"Error sensor ToF canal {i}: {e}")

            # Simulacion si falla hardware o esta en bypass
            geom = self.geometria.get(i, {"vacio_mm": 100, "lleno_mm": 20})
            rango = max(1.0, float(geom["vacio_mm"] - geom["lleno_mm"]))
            altura_agua_mm = (self._niveles_simulados_pct[i] / 100.0) * rango
            dist_sim = geom["vacio_mm"] - altura_agua_mm
            distancias[i] = max(float(geom["lleno_mm"]), round(dist_sim, 1))

        return distancias

    def calcular_niveles_porcentaje(self, distancias_mm: list) -> list:
        niveles = []
        for i, dist in enumerate(distancias_mm):
            geom = self.geometria.get(i, {"vacio_mm": 100, "lleno_mm": 20})
            vacio = float(geom["vacio_mm"])
            lleno = float(geom["lleno_mm"])
            rango = vacio - lleno
            if rango <= 0:
                rango = 1.0
            pct = ((vacio - dist) / rango) * 100.0
            pct = max(0.0, min(100.0, pct))
            niveles.append(round(pct, 1))
        return niveles

    def actualizar_simulacion(self, bomba_activa: bool, caudal_llegada: float = 1.5, caudal_salida: float = 0.5):
        for i in range(4):
            if bomba_activa:
                self._niveles_simulados_pct[i] += caudal_llegada
            else:
                if self._niveles_simulados_pct[i] > 5.0:
                    self._niveles_simulados_pct[i] -= caudal_salida
            self._niveles_simulados_pct[i] = min(100.0, max(0.0, self._niveles_simulados_pct[i]))

    def set_niveles_simulados(self, pct: float):
        self._niveles_simulados_pct = [float(pct)] * 4
