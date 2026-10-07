# -*- coding: utf-8 -*-
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
# Cada bomba usa DOS relÃ©s a la vez (polo +12V y retorno GND) para cerrar el circuito.
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
    logger.warning("SimulaciÃ³n activa.")

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
        self.n_leds_tira = 120
        
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
                
                # CODIGO MODIFICADO: EL SENSOR DEL ESTANQUE 1 ESTA MALO Y CUELGA EL I2C. LO SALTAMOS
                # for canal in CANALES_SENSORES:
                #     try:
                #         sensor = VL53L0X(self.mux[canal])
                #         self.sensores.append(sensor)
                #     except Exception:
                #         self.sensores.append(None)
                
                # CODIGO MODIFICADO Y ADAPTADO DESDE C3-PLC: 
                # El sensor del Estanque 1 (Canal 2, bornera J20) esta malo fisicamente y cuelga el I2C.
                # Lo inicializaremos como None.
                logger.info("Iniciando escaneo de sensores I2C con timeout de 10s (Modo Test - Bypass Canal 2)...")
                
                def init_sensor_con_timeout(c):
                    res = [None]
                    exc = [None]
                    def _worker():
                        try:
                            res[0] = VL53L0X(self.mux[c])
                        except Exception as err:
                            exc[0] = err
                    t = threading.Thread(target=_worker)
                    t.daemon = True
                    t.start()
                    t.join(10.0)
                    if t.is_alive():
                        raise TimeoutError("TIMEOUT > 10s (Colgado)")
                    if exc[0]:
                        raise exc[0]
                    return res[0]

                for canal in [0, 1, 2, 3]:
                    if canal == 2:  # Estanque 1 roto
                        self.sensores.append(None)
                        logger.warning(f"[-] Canal {canal} IGNORADO intencionalmente por bypass.")
                    else:
                        try:
                            sensor = init_sensor_con_timeout(canal)
                            self.sensores.append(sensor)
                            logger.info(f"[+] Sensor en Canal {canal} INICIALIZADO correctamente.")
                        except Exception as e:
                            self.sensores.append(None)
                            logger.error(f"[X] FALLO CRITICO: El sensor en Canal {canal} se salto por error o timeout ({e})")
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
                        # Separadores visuales: Bloques de 30 (25 LEDs encendidos, 5 apagados)
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

    def leer_distancias_mm(self):
        if HARDWARE_REAL:
            distancias = []
            for sensor in self.sensores:
                if sensor:
                    try:
                        dist = sensor.range
                        # Si da más de 8000, asumimos fuera de rango
                        distancias.append(dist if dist <= 8000 else 8190)
                    except Exception:
                        # Si hay un error, 8190 evita que crea que está a 0mm (Lleno al 166%)
                        distancias.append(8190)
                else:
                    distancias.append(8190)
            return distancias
        else:
            return [50, 50, 50, 50]

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
        self.color_t1 = (0, 150, 255) # Celeste agua
        self.color_t2 = (0, 150, 255) # Celeste agua
        self.velocidad_ms = 60
        self.modo_parpadeo = False
        
    def run(self):
        while self.corriendo:
            if getattr(self, 'modo_parpadeo', False):
                # Efecto estroboscÃ³pico de alerta
                self.hw.pintar_pixeles(self.hw.n_leds_tira, self.color_t1, self.color_t2)
                time.sleep(0.2)
                self.hw.pintar_pixeles(0, (0, 0, 0), (0, 0, 0))
                time.sleep(0.2)
                continue

            n_leds = self.hw.n_leds_tira
            
            # Llenado gradual
            for i in range(n_leds + 1):
                if not self.corriendo or getattr(self, 'modo_parpadeo', False): break
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
        self.plc_ip = os.environ.get("PLC_HOST", "10.10.30.100")
        self.plc_port = int(os.environ.get("PLC_PORT", 502))
        
        self.cliente = ModbusClient(host=self.plc_ip, port=self.plc_port, auto_open=True, timeout=2.0)
        self.hw = HardwareManager()
        self.animador_tiras = AnimadorTiras(self.hw)
        self.animador_semaforos = AnimadorSemaforos(self.hw)
        
        self.corriendo = False
        self._contador_watchdog = 0
        self._estado_bombas_local = False

        # Buffer para Promedio MÃ³vil (Suavizado de Sensores)
        self.historial_distancias = {0: [], 1: [], 2: [], 3: []}
        self.max_muestras = 5

        # Control de desbordamiento (10 segundos)
        self.segundos_desbordados = {0: 0, 1: 0, 2: 0, 3: 0}
        # Mapeo de canal I2C al bit Sensor_Nivel_Alto del PLC
        # I2C 0 (P2)->Bit 10, I2C 1 (P4)->Bit 14, I2C 2 (P1)->Bit 8, I2C 3 (P3)->Bit 12
        self.map_alto = {0: 10, 1: 14, 2: 8, 3: 12}

        # Mapa de colores del PLC (Flag 4)
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
            self.animador_tiras.start()
            self.animador_semaforos.start()
            threading.Thread(target=self._bucle_control, daemon=True).start()

    def _calcular_pct_local(self, mm):
        vacio = 50 # DIST_VACIO_MM
        lleno = 20 # DIST_LLENO_MM
        if mm > 8000: return 0.0
        if vacio == lleno: return 0.0
        pct = (vacio - mm) / (vacio - lleno) * 100.0
        return max(0.0, pct)

    def _actualizar_luces(self, color_plc, max_pct_local):
        if color_plc == 0:
            # LÃ³gica local: depende del nivel de los estanques
            if max_pct_local >= 100.0:
                self.animador_tiras.color_t1 = (255, 100, 0) # Naranjo
                self.animador_tiras.color_t2 = (255, 100, 0)
                self.animador_tiras.modo_parpadeo = True
            elif max_pct_local >= 85.0:
                self.animador_tiras.color_t1 = (255, 255, 0) # Amarillo
                self.animador_tiras.color_t2 = (255, 255, 0)
                self.animador_tiras.modo_parpadeo = False
                self.animador_tiras.velocidad_ms = 40
            else:
                self.animador_tiras.color_t1 = (0, 150, 255) # Celeste agua
                self.animador_tiras.color_t2 = (0, 150, 255) # Celeste agua
                self.animador_tiras.modo_parpadeo = False
                self.animador_tiras.velocidad_ms = 60
        else:
            # Override del PLC (Modo fiesta o Flag)
            self.animador_tiras.modo_parpadeo = False
            color_rgb = self.mapa_colores.get(color_plc, (255, 255, 255))
            self.animador_tiras.color_t1 = color_rgb
            self.animador_tiras.color_t2 = color_rgb
            self.animador_tiras.velocidad_ms = 20

    def _bucle_control(self):
        loop_counter = 0
        while self.corriendo:
            try:
                self.hw.actualizar_simulacion(self._estado_bombas_local)
                
                if not self.cliente.is_open:
                    logger.warning("Intentando conectar al PLC Modbus en %s:%s...", self.plc_ip, self.plc_port)
                    self.cliente.open()

                if self.cliente.is_open:
                    loop_counter += 1
                    if loop_counter % 5 == 0:  # Imprimir cada 5 segundos para no saturar la pantalla
                        logger.info("Conectado al PLC. Enviando telemetria y leyendo comandos...")
                    # 1. ENVIAR LECTURAS CRUDAS (Con Promedio Movil)
                    distancias_crudas = self.hw.leer_distancias_mm()
                    max_pct_calculado = 0.0
                    bits_alto_sensores = 0

                    if len(distancias_crudas) == 4:
                        distancias_suavizadas = []
                        for i in range(4):
                            dist_cruda = distancias_crudas[i]
                            # Ignorar lecturas de error (8190) para no arruinar el promedio
                            if dist_cruda < 8000:
                                self.historial_distancias[i].append(dist_cruda)
                                if len(self.historial_distancias[i]) > self.max_muestras:
                                    self.historial_distancias[i].pop(0)
                            
                            if len(self.historial_distancias[i]) > 0:
                                promedio = int(sum(self.historial_distancias[i]) / len(self.historial_distancias[i]))
                            else:
                                promedio = 50 # Vacio por defecto
                                
                            distancias_suavizadas.append(promedio)

                            # Calculamos el % solo para ver si alertamos con luces
                            pct = self._calcular_pct_local(promedio)
                            if pct > max_pct_calculado:
                                max_pct_calculado = pct

                            # Control de tiempo en desbordamiento (10s)
                            if pct >= 100.0:
                                self.segundos_desbordados[i] += 1
                            else:
                                self.segundos_desbordados[i] = 0

                            if self.segundos_desbordados[i] >= 10:
                                bits_alto_sensores |= (1 << self.map_alto[i])

                        # HR 21 (P1)=ch2, HR 23 (P2)=ch0, HR 25 (P3)=ch3, HR 27 (P4)=ch1
                        # Mapeo segun mapa_sensores.py del cuadrante 3
                        # Escribir lecturas a Modbus (RAW y PCT contiguos en un solo request, tal como exige C3-PLC)
                        pct_p1 = int(self._calcular_pct_local(distancias_suavizadas[2]))
                        pct_p2 = int(self._calcular_pct_local(distancias_suavizadas[0]))
                        pct_p3 = int(self._calcular_pct_local(distancias_suavizadas[3]))
                        pct_p4 = int(self._calcular_pct_local(distancias_suavizadas[1]))
                        
                        registros_sensores = [
                            distancias_suavizadas[2], pct_p1,  # HR 21 (RAW), HR 22 (PCT)
                            distancias_suavizadas[0], pct_p2,  # HR 23 (RAW), HR 24 (PCT)
                            distancias_suavizadas[3], pct_p3,  # HR 25 (RAW), HR 26 (PCT)
                            distancias_suavizadas[1], pct_p4   # HR 27 (RAW), HR 28 (PCT)
                        ]
                        self.cliente.write_multiple_registers(21, registros_sensores)
                        self.cliente.write_single_register(41, 0)
                    else:
                        self.cliente.write_single_register(41, 1)

                    # Watchdog
                    self._contador_watchdog = (self._contador_watchdog + 1) & 0xFFFF
                    self.cliente.write_single_register(40, self._contador_watchdog)

                    # 2. LEER COMANDOS DEL PLC
                    regs_bombas = self.cliente.read_holding_registers(0, 1)
                    regs_color = self.cliente.read_holding_registers(10, 1)

                    if regs_bombas and regs_color:
                        hr_bombas = regs_bombas[0]
                        hr_color = regs_color[0]

                        # --- OVERRIDE DE DESBORDAMIENTO AL PLC ---
                        # Inyectamos Sensor_Nivel_Alto (Bits 8,10,12,14) en HR 0. 
                        # El PLC lo lee y bloquea el bombeo por seguridad.
                        nuevo_hr0 = (hr_bombas & ~0x5500) | bits_alto_sensores
                        if nuevo_hr0 != hr_bombas:
                            self.cliente.write_single_register(0, nuevo_hr0)

                        # Extraemos bits de comando
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
                        
                        # Actualizar luces con el color del PLC o la alerta de nivel
                        self._actualizar_luces(hr_color, max_pct_calculado)

                else:
                    # FAILSAFE: PLC caido o desconectado
                    self.hw.set_bombas(False)
                    self._estado_bombas_local = False
                    self.hw.set_luminarias(False)
                    self.animador_tiras.modo_parpadeo = False
                    self.animador_tiras.color_t1 = (255, 0, 255)
                    self.animador_tiras.color_t2 = (255, 0, 255)

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

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
    print("==================================================")
    print("  INICIANDO DAEMON RTU - AGUAS DEL VALLE S.A.  ")
    print("==================================================")
    gateway = RtuHardwareGateway()
    try:
        gateway.iniciar()
        print("[INFO] Daemon iniciado correctamente. Presiona CTRL+C para detener.")
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Deteniendo el demonio de hardware...")
        gateway.detener()
        print("[INFO] Apagado completo.")