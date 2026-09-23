import time
import threading
import logging
import os
from pyModbusTCP.client import ModbusClient
from servicios.sensor_tof import BancoSensoresToF
from servicios.control_rele import servicio_rele
from comandos_gpio.luces import actualizar_luces

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RtuHardwareGateway:
    def __init__(self):
        # Conexión al PLC Físico Real (donde atacan los hackers)
        self.plc_ip = os.environ.get("PLC_HOST", "192.168.60.10")
        self.plc_port = int(os.environ.get("PLC_PORT", 502))
        
        self.cliente = ModbusClient(host=self.plc_ip, port=self.plc_port, auto_open=True, timeout=2.0)
        self.banco_sensores = BancoSensoresToF()
        
        # Lógica de autogestión de la Raspberry
        self.limite_seguridad_pct = 85.0
        self.bomba_activa = True
        self.estado = "NORMAL"
        
        self.corriendo = False

    def iniciar(self):
        if not self.corriendo:
            self.corriendo = True
            logger.info(f"Iniciando Lógica de Control (Raspi -> PLC en {self.plc_ip}:{self.plc_port})...")
            servicio_rele.iniciar()
            threading.Thread(target=self._bucle_control, daemon=True).start()

    def _bucle_control(self):
        while self.corriendo:
            try:
                # 1. Leer Sensores Físicos
                if not self.banco_sensores.es_hardware:
                    caudal_llegada = 1.6 if self.bomba_activa else 0.0
                    caudal_salida = 0.4
                    self.banco_sensores.actualizar_simulacion(self.bomba_activa, caudal_llegada, caudal_salida)
                    
                distancias_mm = self.banco_sensores.leer_distancias_mm()
                niveles_pct = self.banco_sensores.calcular_niveles_porcentaje(distancias_mm)
                nivel_maximo = max(niveles_pct)

                if self.cliente.is_open:
                    # 2. Provisionar telemetría al PLC real (Registros 17-20)
                    self.cliente.write_multiple_registers(17, [
                        int(niveles_pct[0] * 10),
                        int(niveles_pct[1] * 10),
                        int(niveles_pct[2] * 10),
                        int(niveles_pct[3] * 10)
                    ])

                    # 3. Leer la orden de Bypass (Registro 0) desde el PLC real
                    # (Aquí es donde el atacante inserta 768 / 0x0300 al atacar el PLC)
                    regs = self.cliente.read_holding_registers(0, 1)
                    sensor_bypassed = (regs and regs[0] == 768)

                    # 4. Lógica de Autogestión Interna (Raspberry manda sobre sí misma)
                    if self.bomba_activa:
                        if not sensor_bypassed:
                            # Operación Normal: Respetar límite del 85%
                            if nivel_maximo >= self.limite_seguridad_pct:
                                if hasattr(self, '_tiempo_inundacion'): del self._tiempo_inundacion
                                self.bomba_activa = False
                                self.estado = "LIMITE_ALCANZADO"
                            else:
                                if hasattr(self, '_tiempo_inundacion'): del self._tiempo_inundacion
                                self.estado = "LLENANDO"
                        else:
                            # ATAQUE CTF: Bypass Activo, ignorar 85% y forzar agua
                            if nivel_maximo >= 100.0:
                                self.estado = "INUNDACION_CRITICA"
                                if not hasattr(self, '_tiempo_inundacion'):
                                    self._tiempo_inundacion = time.time()
                                elif time.time() - self._tiempo_inundacion >= 10.0:
                                    # Auto-reset después de 10 segundos inundado
                                    logger.info("Auto-restableciendo: Limpiando Registro 0 del PLC...")
                                    self.cliente.write_single_register(0, 0) # Borrar bypass en PLC
                                    self.bomba_activa = True
                                    if not self.banco_sensores.es_hardware:
                                        self.banco_sensores.set_niveles_simulados(25.0)
                                    del self._tiempo_inundacion
                            elif nivel_maximo >= 98.0:
                                if hasattr(self, '_tiempo_inundacion'): del self._tiempo_inundacion
                                self.estado = "INUNDACION_CRITICA"
                            else:
                                if hasattr(self, '_tiempo_inundacion'): del self._tiempo_inundacion
                                self.estado = "OVERRIDE_ACTIVO"
                    else:
                        # Bomba inactiva
                        if hasattr(self, '_tiempo_inundacion'):
                            del self._tiempo_inundacion
                            
                        if nivel_maximo < (self.limite_seguridad_pct - 15.0) and not sensor_bypassed:
                            self.bomba_activa = True
                            self.estado = "LLENANDO"
                        elif self.estado != "INUNDACION_CRITICA":
                            if nivel_maximo >= self.limite_seguridad_pct:
                                self.estado = "LIMITE_ALCANZADO"
                            else:
                                self.estado = "NORMAL"

                    # 5. Ejecutar la acción en los relés físicos
                    servicio_rele.conmutar_manual(self.bomba_activa)

                    # 6. Actualizar luces locales
                    actualizar_luces(self.estado)

                    # 7. Escribir el estado de la bomba (Reg 21) en el PLC para que la Web lo sepa
                    self.cliente.write_single_register(21, 1 if self.bomba_activa else 0)

                else:
                    logger.warning("No hay conexión con el PLC Físico. Intentando reconectar...")
                    # Fallback de seguridad si se pierde la red con el PLC
                    servicio_rele.conmutar_manual(False)
                    actualizar_luces("INUNDACION_CRITICA")

            except Exception as e:
                logger.error(f"Error en bucle lógico de Raspberry: {e}")
                
            time.sleep(0.5)

    def detener(self):
        self.corriendo = False
        if self.cliente.is_open:
            self.cliente.close()
        servicio_rele.detener()

if __name__ == "__main__":
    gateway = RtuHardwareGateway()
    try:
        gateway.iniciar()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        gateway.detener()
