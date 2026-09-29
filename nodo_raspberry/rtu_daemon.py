import time
import threading
import logging
import os
import math
from pyModbusTCP.client import ModbusClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ============================================================================
# MAPA DE HARDWARE (Basado en el nuevo Cuadrante 3 - v1.0.0 final)
# ============================================================================

RELES_BOMBAS = [4, 6, 27, 26] # P1, P2, P3, P4 (Activos en BAJO)
LUMINARIAS = [9, 11] # L1, L2 (LEDs en SPI0, Activos en ALTO)
SEMAFORO_1 = {"rojo": 22, "amarillo": 23, "verde": 24} # Activos en BAJO
SEMAFORO_2 = {"rojo": 16, "amarillo": 20, "verde": 21} # Activos en BAJO

MUX_ADDRESS = 0x70
MUX_RST_PIN = 17
CANALES_SENSORES = [0, 1, 2, 3]

# NUEVA CALIBRACIÓN (0 vacío, 40 lleno)
DIST_VACIO_MM = 0
DIST_LLENO_MM = 40

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
    from rpi_ws281x import ws
    HAY_TIRAS = True
except ImportError:
    HAY_TIRAS = False
    logger.warning("rpi_ws281x no encontrado. Las tiras LED no se iluminarán.")

class HardwareManager:
    def __init__(self):
        self.sensores = []
        self.leds = None
        self.canales_ws = []
        self.n_leds_tira = 100
        
        # --- INIT TIRAS LED (Bajo nivel para soportar PWM0 y PWM1 a la vez) ---
        if HAY_TIRAS:
            try:
                self.leds = ws.new_ws2811_t()
                ws.ws2811_t_freq_set(self.leds, 800000)
                ws.ws2811_t_dmanum_set(self.leds, 10)
                
                # Tira 1: GPIO 18, PWM 0
                ch0 = ws.ws2811_channel_get(self.leds, 0)
                ws.ws2811_channel_t_count_set(ch0, self.n_leds_tira)
                ws.ws2811_channel_t_gpionum_set(ch0, 18)
                ws.ws2811_channel_t_invert_set(ch0, 0)
                ws.ws2811_channel_t_brightness_set(ch0, 128)
                ws.ws2811_channel_t_strip_type_set(ch0, ws.WS2811_STRIP_GRB)
                self.canales_ws.append(ch0)
                
                # Tira 2: GPIO 13, PWM 1
                ch1 = ws.ws2811_channel_get(self.leds, 1)
                ws.ws2811_channel_t_count_set(ch1, self.n_leds_tira)
                ws.ws2811_channel_t_gpionum_set(ch1, 13)
                ws.ws2811_channel_t_invert_set(ch1, 0)
                ws.ws2811_channel_t_brightness_set(ch1, 128)
                ws.ws2811_channel_t_strip_type_set(ch1, ws.WS2811_STRIP_GRB)
                self.canales_ws.append(ch1)
                
                resp = ws.ws2811_init(self.leds)
                if resp != ws.WS2811_SUCCESS:
                    logger.error(f"Fallo inicializando WS2811 (Error {resp}). Tiras inactivas.")
                    self.leds = None
            except Exception as e:
                logger.error(f"Error iniciando tiras LED de bajo nivel: {e}")

        if HARDWARE_REAL:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            
            # Relés Bombas (Apagados -> HIGH, activos en bajo)
            for pin in RELES_BOMBAS:
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.HIGH)
                
            # Luminarias (Apagadas -> LOW, activas en alto)
            for pin in LUMINARIAS:
                GPIO.setup(pin, GPIO.OUT, initial=GPIO.LOW)
                
            # Semáforos (Apagados -> HIGH)
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

    def set_luminarias(self, activas: bool):
        if HARDWARE_REAL:
            nivel = GPIO.HIGH if activas else GPIO.LOW
            for pin in LUMINARIAS:
                GPIO.output(pin, nivel)

    def set_semaforos(self, color):
        if HARDWARE_REAL:
            for sem in [SEMAFORO_1, SEMAFORO_2]:
                for c, pin in sem.items():
                    nivel = GPIO.LOW if c == color else GPIO.HIGH
                    GPIO.output(pin, nivel)

    def set_color_tiras(self, r, g, b):
        if HAY_TIRAS and self.leds:
            try:
                valor_color = (int(r) << 16) | (int(g) << 8) | int(b)
                for ch in self.canales_ws:
                    for i in range(self.n_leds_tira):
                        ws.ws2811_led_set(ch, i, valor_color)
                ws.ws2811_render(self.leds)
            except Exception as e:
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
                        # NUEVA MATEMÁTICA INVERTIDA
                        if DIST_VACIO_MM == DIST_LLENO_MM:
                            pct = 0.0
                        else:
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
            self.set_bombas(False)
            self.set_luminarias(False)
            self.set_semaforos("rojo")  # Seguro
            GPIO.cleanup()
        if HAY_TIRAS and self.leds:
            try:
                self.set_color_tiras(0, 0, 0)
                ws.ws2811_fini(self.leds)
                ws.delete_ws2811_t(self.leds)
            except Exception:
                pass


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
        if self.estado in ["NORMAL", "LLENANDO"]:
            self.hw.set_semaforos("verde")
        elif self.estado == "LIMITE_ALCANZADO":
            self.hw.set_semaforos("amarillo")
        elif self.estado in ["OVERRIDE_ACTIVO", "INUNDACION_CRITICA", "PARADA_FORZADA"]:
            self.hw.set_semaforos("rojo")
            
        color_led = getattr(self, 'color_tiras_override', (0, 0, 255)) 
        if nivel_maximo >= 100.0 or self.estado in ["INUNDACION_CRITICA", "PARADA_FORZADA"]:
            color_led = (255, 0, 0)
        elif nivel_maximo >= self.limite_seguridad_pct or self.estado == "LIMITE_ALCANZADO":
            color_led = (255, 140, 0)
            
        self.hw.set_color_tiras(*color_led)

    def _bucle_control(self):
        while self.corriendo:
            try:
                self.hw.actualizar_simulacion(self.bombas_activas)
                niveles_pct = self.hw.leer_niveles_pct()
                nivel_maximo = max(niveles_pct) if niveles_pct else 0.0

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
