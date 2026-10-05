import time
import threading
import logging
import os
import math
from pyModbusTCP.client import ModbusClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ============================================================================
# MAPA DE HARDWARE
# ============================================================================
# Cada bomba usa DOS relés a la vez (polo +12V y retorno GND) para cerrar el circuito.
RELES_BOMBAS = {
    0: [4, 5],     # P1 (Canales 1 y 2)
    1: [6, 7],     # P2 (Canales 3 y 4)
    2: [27, 19],   # P3 (Canales 5 y 6)
    3: [26, 12]    # P4 (Canales 7 y 8)
}
LUMINARIAS = [9, 11]
SEMAFORO_1 = {"rojo": 22, "amarillo": 23, "verde": 24}
SEMAFORO_2 = {"rojo": 16, "amarillo": 20, "verde": 21}

MUX_ADDRESS = 0x70
MUX_RST_PIN = 17
CANALES_SENSORES = [0, 1, 2, 3]

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
    logger.warning("Simulación activa.")

try:
    from rpi_ws281x import ws
    HAY_TIRAS = True
except ImportError:
    HAY_TIRAS = False


class HardwareManager:
    def __init__(self):
        self.sensores = []
        self.leds = None
        self.canales_ws = []
        self.n_leds_tira = 100
        
        self.modo_manual_bombas = False
        self.estado_bombas = [False, False, False, False]
        
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
                    except Exception:
                        self.sensores.append(None)
            except Exception:
                pass
        else:
            self.niveles_simulados = [25.0, 25.0, 25.0, 25.0]

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
                        ws.ws2811_led_set(self.canales_ws[0], i, c1 if i < encendidos else apagado)
                if len(self.canales_ws) > 1:
                    for i in range(self.n_leds_tira):
                        ws.ws2811_led_set(self.canales_ws[1], i, c2 if i < encendidos else apagado)
                        
                ws.ws2811_render(self.leds)
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
                        if dist > 8000:
                            pct = 0.0
                        else:
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
            self.set_semaforos("rojo")
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
        self.color_t1 = (0, 0, 255)
        self.color_t2 = (255, 255, 255)
        self.velocidad_ms = 60
        
    def run(self):
        while self.corriendo:
            n_leds = self.hw.n_leds_tira
            
            # Llenado gradual
            for i in range(n_leds + 1):
                if not self.corriendo: return
                self.hw.pintar_pixeles(i, self.color_t1, self.color_t2)
                time.sleep(max(10, self.velocidad_ms) / 1000.0)
                
            # Pausa llena
            time.sleep(0.4)
            
            # Apagar y pausa
            self.hw.pintar_pixeles(0, self.color_t1, self.color_t2)
            time.sleep(0.2)


class AnimadorSemaforos(threading.Thread):
    def __init__(self, hw):
        super().__init__(daemon=True)
        self.hw = hw
        self.corriendo = True
        self.secuencia = [("verde", 6.0), ("amarillo", 2.0), ("rojo", 8.0)]
        self.periodo = sum(d for c, d in self.secuencia)
        self.desfases = {1: 0.0, 2: 8.0} # 1=TL1, 2=TL2
        
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
    def __init__(self):
        self.plc_ip = os.environ.get("PLC_HOST", "192.168.60.10")
        self.plc_port = int(os.environ.get("PLC_PORT", 502))
        
        self.cliente = ModbusClient(host=self.plc_ip, port=self.plc_port, auto_open=True, timeout=2.0)
        self.hw = HardwareManager()
        self.animador_tiras = AnimadorTiras(self.hw)
        self.animador_semaforos = AnimadorSemaforos(self.hw)
        
        self.limite_seguridad_pct = 85.0
        self.bombas_activas = True
        self.estado = "NORMAL"
        self.corriendo = False

    def iniciar(self):
        if not self.corriendo:
            self.corriendo = True
            self.animador_tiras.start()
            self.animador_semaforos.start()
            threading.Thread(target=self._bucle_control, daemon=True).start()

    def _actualizar_luces_estado(self, nivel_maximo):
        # 1. Tira 1 (Lógica de Agua/CTF)
        color_t1 = getattr(self, 'color_tira1_override', (0, 0, 255)) 
        if nivel_maximo >= 100.0 or self.estado in ["INUNDACION_CRITICA", "PARADA_FORZADA"]:
            color_t1 = (255, 0, 0)
        elif nivel_maximo >= self.limite_seguridad_pct or self.estado == "LIMITE_ALCANZADO":
            color_t1 = (255, 140, 0)
            
        # 2. Tira 2 (Edificios/Casas, completamente libre)
        color_t2 = getattr(self, 'color_tira2_override', (255, 255, 255))
        
        self.animador_tiras.color_t1 = color_t1
        self.animador_tiras.color_t2 = color_t2
        self.animador_tiras.velocidad_ms = getattr(self, 'velocidad_tiras_override', 60)

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
                    self.hw.set_bombas(False)
                    # En fallback, forzamos animación a rojo
                    self.animador_tiras.color_t1 = (255, 0, 0)
                    self.animador_tiras.color_t2 = (255, 0, 0)

            except Exception as e:
                pass
                
            time.sleep(0.5)

    def detener(self):
        self.corriendo = False
        
        self.animador_tiras.corriendo = False
        self.animador_semaforos.corriendo = False
        
        self.animador_tiras.join(timeout=1.0)
        self.animador_semaforos.join(timeout=1.0)
        
        if self.cliente.is_open:
            self.cliente.close()
        self.hw.limpiar()
        self.hw.apagar_semaforos()

if __name__ == "__main__":
    gateway = RtuHardwareGateway()
    try:
        gateway.iniciar()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        gateway.detener()
