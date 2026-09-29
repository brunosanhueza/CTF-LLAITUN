import time
import threading
import logging
import os
import math
from pyModbusTCP.client import ModbusClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ============================================================================
# MAPA DE HARDWARE (Basado en el nuevo Cuadrante 3)
# ============================================================================

RELES_BOMBAS = [4, 6, 27, 26] # P1, P2, P3, P4
SEMAFORO_1 = {"rojo": 22, "amarillo": 23, "verde": 24}
SEMAFORO_2 = {"rojo": 16, "amarillo": 20, "verde": 21}

MUX_ADDRESS = 0x70
MUX_RST_PIN = 17
CANALES_SENSORES = [0, 1, 2, 3]

DIST_VACIO_MM = 300
DIST_LLENO_MM = 50

try:
    import RPi.GPIO as GPIO
    import board
    import busio
    import adafruit_tca9548a
    from adafruit_vl53l0x import VL53L0X
    HARDWARE_REAL = True
except ImportError:
    HARDWARE_REAL = False
    logger.warning("Librerías de Raspberry no detectadas. Corriendo en SIMULACIÓN.")

try:
    from rpi_ws281x import PixelStrip, Color
    HAY_TIRAS = True
except ImportError:
    HAY_TIRAS = False
    logger.warning("rpi_ws281x no encontrado. Las tiras LED no se iluminarán.")

class HardwareManager:
    def __init__(self):
        self.sensores = []
        self.tiras = []
        
        # --- INIT TIRAS LED ---
        if HAY_TIRAS:
            try:
                # Tira 1: GPIO 18, PWM 0, 30 LEDs
                t1 = PixelStrip(30, 18, 800000, 10, False, 128, 0)
                t1.begin()
                self.tiras.append(t1)
                # Tira 2: GPIO 13, PWM 1, 30 LEDs
                t2 = PixelStrip(30, 13, 800000, 10, False, 128, 1)
                t2.begin()
                self.tiras.append(t2)
            except Exception as e:
                logger.error(f"Error iniciando tiras LED (Requiere sudo): {e}")

        if HARDWARE_REAL:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            for pin in RELES_BOMBAS:
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
                
            for sem in [SEMAFORO_1, SEMAFORO_2]:
                for pin in sem.values():
                    GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
            
            try:
                GPIO.setup(MUX_RST_PIN, GPIO.OUT, initial=GPIO.HIGH)
                GPIO.output(MUX_RST_PIN, GPIO.LOW)
                time.sleep(0.01)
                GPIO.output(MUX_RST_PIN, GPIO.HIGH)
                time.sleep(0.05)
                
                self.i2c = busio.I2C(board.SCL, board.SDA)
                self.mux = adafruit_tca9548a.TCA9548A(self.i2c, address=MUX_ADDRESS)
                
                for canal in CANALES_SENSORES:
                    try:
                        sensor = VL53L0X(self.mux[canal])
                        self.sensores.append(sensor)
                    except Exception as e:
                        logger.error(f"Fallo al detectar sensor en canal {canal}: {e}")
                        self.sensores.append(None)
            except Exception as e:
                logger.error(f"Error crítico iniciando I2C: {e}")
        else:
            self.niveles_simulados = [25.0, 25.0, 25.0, 25.0]

    def set_bombas(self, activas: bool):
        if HARDWARE_REAL:
            nivel = GPIO.LOW if activas else GPIO.HIGH
            for pin in RELES_BOMBAS:
                GPIO.output(pin, nivel)

    def set_semaforos(self, color):
        if HARDWARE_REAL:
            for sem in [SEMAFORO_1, SEMAFORO_2]:
                for c, pin in sem.items():
                    nivel = GPIO.LOW if c == color else GPIO.HIGH
                    GPIO.output(pin, nivel)

    def set_color_tiras(self, r, g, b):
        if HAY_TIRAS:
            try:
                c = Color(r, g, b)
                for tira in self.tiras:
                    for i in range(tira.numPixels()):
                        tira.setPixelColor(i, c)
                    tira.show()
            except Exception:
                pass

    def leer_niveles_pct(self):
        if getattr(self, 'override_niveles', None) is not None:
            return self.override_niveles
            
        if HARDWARE_REAL:
            niveles = []
            for sensor in self.sensores:
                if sensor:
                    try:
                        dist = sensor.range
                        pct = (DIST_VACIO_MM - dist) / (DIST_VACIO_MM - DIST_LLENO_MM) * 100.0
                        niveles.append(max(0.0, min(100.0, pct)))
                    except Exception:
                        niveles.append(0.0)
                else:
                    niveles.append(0.0)
            return niveles
        else:
            return self.niveles_simulados

    def actualizar_simulacion(self, bombas_activas):
        if not HARDWARE_REAL:
            if getattr(self, 'override_niveles', None) is not None:
                self.niveles_simulados = self.override_niveles.copy()
            else:
                tasa = 1.6 if bombas_activas else -0.5
                for i in range(4):
                    self.niveles_simulados[i] = max(0.0, min(105.0, self.niveles_simulados[i] + tasa))

    def limpiar(self):
        if HARDWARE_REAL:
            GPIO.cleanup()


class RtuHardwareGateway:
    def __init__(self):
        self.plc_ip = os.environ.get("PLC_HOST", "192.168.60.10")
        self.plc_port = int(os.environ.get("PLC_PORT", 502))
        
        self.cliente = ModbusClient(host=self.plc_ip, port=self.plc_port, auto_open=True, timeout=2.0)
        self.hw = HardwareManager()
        
        self.limite_seguridad_pct = 85.0
        self.bombas_activas = True
        self.estado = "NORMAL"
        self.corriendo = False

    def iniciar(self):
        if not self.corriendo:
            self.corriendo = True
            logger.info(f"Iniciando RTU CTF Edge Node (Raspi -> PLC {self.plc_ip}:{self.plc_port})")
            threading.Thread(target=self._bucle_control, daemon=True).start()

    def _actualizar_luces_estado(self, nivel_maximo):
        # 1. Actualizar Semáforos
        if self.estado in ["NORMAL", "LLENANDO"]:
            self.hw.set_semaforos("verde")
        elif self.estado == "LIMITE_ALCANZADO":
            self.hw.set_semaforos("amarillo")
        elif self.estado in ["OVERRIDE_ACTIVO", "INUNDACION_CRITICA", "PARADA_FORZADA"]:
            self.hw.set_semaforos("rojo")
            
        # 2. Actualizar Tiras LED
        color_led = getattr(self, 'color_tiras_override', (0, 0, 255)) # Azul por defecto
        
        # Override de color por estados críticos
        if nivel_maximo >= 100.0 or self.estado in ["INUNDACION_CRITICA", "PARADA_FORZADA"]:
            color_led = (255, 0, 0) # Rojo
        elif nivel_maximo >= self.limite_seguridad_pct or self.estado == "LIMITE_ALCANZADO":
            color_led = (255, 140, 0) # Amarillo / Ambar
            
        self.hw.set_color_tiras(*color_led)

    def _bucle_control(self):
        while self.corriendo:
            try:
                self.hw.actualizar_simulacion(self.bombas_activas)
                niveles_pct = self.hw.leer_niveles_pct()
                nivel_maximo = max(niveles_pct) if niveles_pct else 0.0

                # FLAG inyectado para pruebas sin PLC físico
                ignorar_plc = getattr(self, 'ignorar_plc', False)

                if self.cliente.is_open or ignorar_plc:
                    if self.cliente.is_open and len(niveles_pct) == 4:
                        self.cliente.write_multiple_registers(17, [int(n * 10) for n in niveles_pct])

                    if self.cliente.is_open:
                        regs = self.cliente.read_holding_registers(0, 1)
                        sensor_bypassed = (regs and regs[0] == 768)
                    else:
                        sensor_bypassed = getattr(self, 'ataque_simulado', False)

                    if getattr(self, 'forzar_parada', False):
                        self.bombas_activas = False
                        self.estado = "PARADA_FORZADA"
                    elif self.bombas_activas:
                        if not sensor_bypassed:
                            if nivel_maximo >= self.limite_seguridad_pct:
                                if hasattr(self, '_tiempo_inund'): del self._tiempo_inund
                                self.bombas_activas = False
                                self.estado = "LIMITE_ALCANZADO"
                            else:
                                if hasattr(self, '_tiempo_inund'): del self._tiempo_inund
                                self.estado = "LLENANDO"
                        else:
                            if nivel_maximo >= 100.0:
                                self.estado = "INUNDACION_CRITICA"
                                if not hasattr(self, '_tiempo_inund'):
                                    self._tiempo_inund = time.time()
                                elif time.time() - self._tiempo_inund >= 10.0:
                                    logger.info("Auto-restableciendo CTF...")
                                    if self.cliente.is_open:
                                        self.cliente.write_single_register(0, 0)
                                    else:
                                        self.ataque_simulado = False
                                        
                                    self.bombas_activas = True
                                    if not HARDWARE_REAL:
                                        self.hw.override_niveles = None
                                        self.hw.niveles_simulados = [25.0, 25.0, 25.0, 25.0]
                                    del self._tiempo_inund
                            elif nivel_maximo >= 98.0:
                                self.estado = "INUNDACION_CRITICA"
                            else:
                                self.estado = "OVERRIDE_ACTIVO"
                    else:
                        if hasattr(self, '_tiempo_inund'): del self._tiempo_inund
                        if nivel_maximo < (self.limite_seguridad_pct - 15.0) and not sensor_bypassed:
                            self.bombas_activas = True
                            self.estado = "LLENANDO"
                        elif self.estado != "INUNDACION_CRITICA":
                            if nivel_maximo >= self.limite_seguridad_pct:
                                self.estado = "LIMITE_ALCANZADO"
                            else:
                                self.estado = "NORMAL"

                    self.hw.set_bombas(self.bombas_activas)
                    self._actualizar_luces_estado(nivel_maximo)

                    if self.cliente.is_open:
                        self.cliente.write_single_register(21, 1 if self.bombas_activas else 0)

                else:
                    logger.warning("Sin conexión al PLC Físico. Fallback de seguridad activado.")
                    self.hw.set_bombas(False)
                    self.hw.set_semaforos("rojo")
                    self.hw.set_color_tiras(255, 0, 0)

            except Exception as e:
                logger.error(f"Error en bucle CTF: {e}")
                
            time.sleep(0.5)

    def detener(self):
        self.corriendo = False
        if self.cliente.is_open:
            self.cliente.close()
        self.hw.limpiar()

if __name__ == "__main__":
    gateway = RtuHardwareGateway()
    try:
        gateway.iniciar()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Deteniendo daemon CTF...")
        gateway.detener()
