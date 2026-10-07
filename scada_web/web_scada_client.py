import time
import threading
import os
from pyModbusTCP.client import ModbusClient

class WebScadaClient:
    def __init__(self, socketio, target_ip=None, target_port=502):
        self.socketio = socketio
        self.target_ip = target_ip or os.environ.get("PLC_HOST", "10.10.30.100")
        self.target_port = target_port
        self.cliente = ModbusClient(host=self.target_ip, port=self.target_port, auto_open=True, timeout=2.0)
        self.corriendo = False
        self._thread = None
        
        # Buffer para el Promedio Móvil (Suavizado de sensores en vivo)
        self.historial_niveles = {0: [], 1: [], 2: [], 3: []}
        self.max_muestras = 5  # Promediar las últimas 5 lecturas
        
        self._telemetria = {
            "estanques": [25.0, 25.0, 25.0, 25.0],
            "bomba_activa": True,
            "sensor_bypassed": False,
            "estado": "NORMAL",
            "mensaje": "Conectando al PLC...",
            "rele": {"estado": False}
        }

    def iniciar(self):
        if not self.corriendo:
            self.corriendo = True
            self.socketio.start_background_task(target=self._bucle_lectura)

    def _bucle_lectura(self):
        while self.corriendo:
            try:
                # Leer registros del nuevo mapa TIA Portal (DB4): 
                # HR 0: Comandos y Estado de Bombas (Bit 9 = Bomba 1)
                # HR 21-24: Escalamiento_Sensores (Niveles estanques 1-4)
                regs_estado = self.cliente.read_holding_registers(0, 1)
                regs_niveles = self.cliente.read_holding_registers(21, 8)
                
                if regs_estado is not None and regs_niveles is not None:
                    # Extraer el estado de la bomba del Bit 9 (512)
                    self._telemetria["bomba_activa"] = bool((regs_estado[0] >> 9) & 1)
                    
                    # Calcular el Promedio Móvil para dar efecto de telemetría "En Vivo" sin saltos bruscos
                    for i in range(4):
                        pct_values = [regs_niveles[1], regs_niveles[3], regs_niveles[5], regs_niveles[7]]
                        val_crudo = pct_values[i] / 10.0
                        self.historial_niveles[i].append(val_crudo)
                        
                        # Mantener el buffer en el tamaño máximo
                        if len(self.historial_niveles[i]) > self.max_muestras:
                            self.historial_niveles[i].pop(0)
                            
                        # Calcular promedio y redondear a 1 decimal
                        promedio = sum(self.historial_niveles[i]) / len(self.historial_niveles[i])
                        self._telemetria["estanques"][i] = round(promedio, 1)
                    
                    # Podemos usar el valor crudo del registro 0 para detectar si hay anomalias
                    self._telemetria["sensor_bypassed"] = (regs_estado[0] != 0)
                    
                    if self._telemetria["sensor_bypassed"]:
                        self._telemetria["estado"] = "OVERRIDE_ACTIVO"
                        self._telemetria["mensaje"] = "Modo Forzado activo va Modbus."
                    else:
                        self._telemetria["estado"] = "NORMAL"
                        self._telemetria["mensaje"] = "Lecturas nominales."
                else:
                    self._telemetria["estado"] = "ERROR"
                    self._telemetria["mensaje"] = "Sin conexión al PLC Modbus."
                    self._telemetria["estanques"] = [0.0, 0.0, 0.0, 0.0]
                    self._telemetria["bomba_activa"] = False

                self.socketio.emit("telemetria", self._telemetria)
            except Exception as e:
                print(f"Error SCADA Client: {e}")
            
            time.sleep(1.0)
            
    def obtener_telemetria(self):
        return self._telemetria
