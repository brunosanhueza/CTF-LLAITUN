import time
import logging

logger = logging.getLogger(__name__)

HARDWARE_AVAILABLE = False
_tca = None
_sensores = [None, None, None, None]

try:
    import board
    import busio
    import adafruit_vl53l0x
    import adafruit_tca9548a
    
    i2c = busio.I2C(board.SCL, board.SDA)
    _tca = adafruit_tca9548a.TCA9548A(i2c, address=0x70)
    
    # Asumimos que los sensores estn en los canales 0, 1, 2 y 3 del multiplexor
    for i in range(4):
        try:
            _sensores[i] = adafruit_vl53l0x.VL53L0X(_tca[i])
        except Exception as e:
            logger.error(f"No se encontr sensor en canal {i}: {e}")
            
    HARDWARE_AVAILABLE = True
except Exception as e:
    logger.error(f"Error inicializando I2C/TCA9548A: {e}")
    HARDWARE_AVAILABLE = False

class BancoSensoresToF:
    def __init__(self, altura_estanque_mm=200, distancia_sensor_tope_mm=20):
        self.altura_estanque = altura_estanque_mm
        self.distancia_tope = distancia_sensor_tope_mm
        self.distancia_fondo = self.altura_estanque + self.distancia_tope
        self._niveles_simulados_pct = [25.0, 25.0, 25.0, 25.0]
        self.es_hardware = HARDWARE_AVAILABLE
        
    def leer_distancias_mm(self) -> list:
        distancias = [170.0, 170.0, 170.0, 170.0]
        for i in range(4):
            if self.es_hardware and _sensores[i] is not None:
                try:
                    dist = _sensores[i].range
                    if 0 < dist < 2000:
                        distancias[i] = float(dist)
                        continue
                except Exception as e:
                    logger.error(f"Error sensor ToF canal {i}: {e}")
            
            # Simulacin si falla hardware o no hay
            altura_agua_mm = (self._niveles_simulados_pct[i] / 100.0) * self.altura_estanque
            dist_sim = self.distancia_fondo - altura_agua_mm
            distancias[i] = max(5.0, round(dist_sim, 1))
            
        return distancias

    def calcular_niveles_porcentaje(self, distancias_mm: list) -> list:
        niveles = []
        for dist in distancias_mm:
            altura_actual_mm = self.distancia_fondo - dist
            porcentaje = (altura_actual_mm / self.altura_estanque) * 100.0
            niveles.append(round(max(0.0, porcentaje), 1))
        return niveles

    def actualizar_simulacion(self, bomba_activa: bool, caudal_llegada: float = 1.5, caudal_salida: float = 0.5):
        for i in range(4):
            if bomba_activa:
                self._niveles_simulados_pct[i] += caudal_llegada
            else:
                if self._niveles_simulados_pct[i] > 5.0:
                    self._niveles_simulados_pct[i] -= caudal_salida
            self._niveles_simulados_pct[i] = min(120.0, max(0.0, self._niveles_simulados_pct[i]))

    def set_niveles_simulados(self, pct: float):
        self._niveles_simulados_pct = [float(pct)] * 4
