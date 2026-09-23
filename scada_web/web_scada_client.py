import time
import threading
import os
from pyModbusTCP.client import ModbusClient

class WebScadaClient:
    def __init__(self, socketio, target_ip=None, target_port=502):
        self.socketio = socketio
        self.target_ip = target_ip or os.environ.get("PLC_HOST", "192.168.60.10")
        self.target_port = target_port
        self.cliente = ModbusClient(host=self.target_ip, port=self.target_port, auto_open=True, timeout=2.0)
        self.corriendo = False
        self._thread = None
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
                # Leer registros: 
                # 0: Override
                # 17-20: Niveles estanques 1-4
                # 21: Estado Bomba (1 = activa, 0 = apagada)
                regs_override = self.cliente.read_holding_registers(0, 1)
                regs_niveles = self.cliente.read_holding_registers(17, 5)
                
                if regs_override is not None and regs_niveles is not None:
                    self._telemetria["sensor_bypassed"] = (regs_override[0] == 768)
                    self._telemetria["estanques"] = [
                        regs_niveles[0] / 10.0,
                        regs_niveles[1] / 10.0,
                        regs_niveles[2] / 10.0,
                        regs_niveles[3] / 10.0
                    ]
                    self._telemetria["bomba_activa"] = (regs_niveles[4] == 1)
                    
                    if self._telemetria["sensor_bypassed"]:
                        self._telemetria["estado"] = "OVERRIDE_ACTIVO"
                        self._telemetria["mensaje"] = "Modo Forzado activo va Modbus."
                    else:
                        self._telemetria["estado"] = "NORMAL"
                        self._telemetria["mensaje"] = "Lecturas nominales."
                else:
                    self._telemetria["estado"] = "ERROR"
                    self._telemetria["mensaje"] = "Sin conexin al PLC Modbus."

                self.socketio.emit("telemetria", self._telemetria)
            except Exception as e:
                print(f"Error SCADA Client: {e}")
            
            time.sleep(1.0)
            
    def obtener_telemetria(self):
        return self._telemetria
