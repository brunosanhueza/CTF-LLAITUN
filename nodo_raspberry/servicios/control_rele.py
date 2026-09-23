import time
import threading
import logging

logger = logging.getLogger(__name__)

GPIO_REAL_DISPONIBLE = False
_gpio_module = None
_pin_rele_device = None

try:
    import RPi.GPIO as GPIO
    _gpio_module = GPIO
    _gpio_module.setmode(_gpio_module.BCM)
    _gpio_module.setwarnings(False)
    GPIO_REAL_DISPONIBLE = True
except Exception:
    try:
        from gpiozero import OutputDevice
        _gpio_module = "gpiozero"
        GPIO_REAL_DISPONIBLE = True
    except Exception:
        GPIO_REAL_DISPONIBLE = False

PYMODBUS_DISPONIBLE = False
try:
    from pymodbus.client import ModbusTcpClient
    PYMODBUS_DISPONIBLE = True
except Exception:
    try:
        from pyModbusTCP.client import ModbusClient as PyModbusTcpClient
    except Exception:
        pass


class RelayMonitorService:
    def __init__(self, plc_ip="10.10.10.4", port=502, registro=9, pin_rele=4, slave_id=1, intervalo=0.5):
        self.plc_ip = plc_ip
        self.port = int(port)
        self.registro = int(registro)
        self.pin_rele = int(pin_rele)
        self.slave_id = int(slave_id)
        self.intervalo = float(intervalo)

        self.corriendo = False
        self.conectado_plc = False
        self.rele_activo = False
        self.ultimo_valor_registro = 0
        self.ultimo_error = None
        self.total_lecturas = 0
        self.modo_hardware = GPIO_REAL_DISPONIBLE

        self._thread = None
        self._lock = threading.Lock()
        self._inicializar_gpio()

    def _inicializar_gpio(self):
        global _pin_rele_device
        if not self.modo_hardware:
            return

        try:
            if _gpio_module == "gpiozero":
                from gpiozero import OutputDevice
                _pin_rele_device = OutputDevice(self.pin_rele, active_high=True, initial_value=False)
            elif _gpio_module is not None:
                _gpio_module.setup(self.pin_rele, _gpio_module.OUT)
                _gpio_module.output(self.pin_rele, _gpio_module.LOW)
        except Exception:
            self.modo_hardware = False

    def _conmutar_hardware_rele(self, estado: bool):
        self.rele_activo = estado
        if not self.modo_hardware:
            return

        try:
            if _gpio_module == "gpiozero" and _pin_rele_device is not None:
                if estado:
                    _pin_rele_device.on()
                else:
                    _pin_rele_device.off()
            elif _gpio_module is not None:
                nivel = _gpio_module.HIGH if estado else _gpio_module.LOW
                _gpio_module.output(self.pin_rele, nivel)
        except Exception as e:
            logger.error(f"Error GPIO: {e}")

    def iniciar(self):
        with self._lock:
            if self.corriendo:
                return
            self.corriendo = True
            self._thread = threading.Thread(target=self._bucle_monitoreo, daemon=True)
            self._thread.start()

    def detener(self):
        with self._lock:
            self.corriendo = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._conmutar_hardware_rele(False)
        self.conectado_plc = False

    def _conectar_cliente_modbus(self):
        if PYMODBUS_DISPONIBLE:
            try:
                from pymodbus.client import ModbusTcpClient
                cliente = ModbusTcpClient(self.plc_ip, port=self.port, timeout=2.0)
                if cliente.connect():
                    return cliente, "pymodbus"
            except Exception as e:
                self.ultimo_error = str(e)
                return None, None
        else:
            try:
                from pyModbusTCP.client import ModbusClient as PyModbusTcpClient
                cliente = PyModbusTcpClient(host=self.plc_ip, port=self.port, timeout=2.0, auto_open=False)
                if cliente.open():
                    return cliente, "pyModbusTCP"
            except Exception as e:
                self.ultimo_error = str(e)
                return None, None
        return None, None

    def _leer_registro(self, cliente, tipo_driver):
        if tipo_driver == "pymodbus":
            try:
                respuesta = cliente.read_holding_registers(address=self.registro, count=1, slave=self.slave_id)
                if not respuesta.isError():
                    return respuesta.registers[0], None
                return None, "Error lectura Modbus"
            except Exception as e:
                return None, str(e)
        elif tipo_driver == "pyModbusTCP":
            try:
                regs = cliente.read_holding_registers(self.registro, 1)
                if regs is not None and len(regs) > 0:
                    return regs[0], None
                return None, "Error lectura Modbus"
            except Exception as e:
                return None, str(e)
        return None, "Driver no disponible"

    def _bucle_monitoreo(self):
        cliente = None
        tipo_driver = None

        while self.corriendo:
            try:
                if cliente is None:
                    cliente, tipo_driver = self._conectar_cliente_modbus()
                    if cliente:
                        self.conectado_plc = True
                        self.ultimo_error = None
                    else:
                        self.conectado_plc = False
                        time.sleep(2.0)
                        continue

                valor, error = self._leer_registro(cliente, tipo_driver)
                self.total_lecturas += 1

                if error is None and valor is not None:
                    self.conectado_plc = True
                    self.ultimo_valor_registro = valor
                    self.ultimo_error = None

                    if valor > 0:
                        if not self.rele_activo:
                            self._conmutar_hardware_rele(True)
                    else:
                        if self.rele_activo:
                            self._conmutar_hardware_rele(False)
                else:
                    self.ultimo_error = error
                    try:
                        cliente.close()
                    except Exception:
                        pass
                    cliente = None
                    self.conectado_plc = False

            except Exception as e:
                self.ultimo_error = str(e)
                self.conectado_plc = False
                cliente = None

            time.sleep(self.intervalo)

        if cliente:
            try:
                cliente.close()
            except Exception:
                pass
        self.conectado_plc = False

    def conmutar_manual(self, forzar_estado=None) -> bool:
        nuevo_estado = not self.rele_activo if forzar_estado is None else bool(forzar_estado)
        self._conmutar_hardware_rele(nuevo_estado)
        return self.rele_activo

    def reconfigurar(self, plc_ip=None, port=None, registro=None, pin_rele=None, intervalo=None):
        estaba_corriendo = self.corriendo
        if estaba_corriendo:
            self.detener()

        if plc_ip: self.plc_ip = str(plc_ip).strip()
        if port: self.port = int(port)
        if registro is not None: self.registro = int(registro)
        if pin_rele is not None:
            self.pin_rele = int(pin_rele)
            self._inicializar_gpio()
        if intervalo is not None: self.intervalo = float(intervalo)

        if estaba_corriendo:
            self.iniciar()

    def obtener_estado(self) -> dict:
        return {
            "corriendo": self.corriendo,
            "conectado_plc": self.conectado_plc,
            "rele_activo": self.rele_activo,
            "ultimo_valor_registro": self.ultimo_valor_registro,
            "ultimo_error": self.ultimo_error,
            "total_lecturas": self.total_lecturas,
            "modo_hardware": self.modo_hardware,
            "config": {
                "plc_ip": self.plc_ip,
                "port": self.port,
                "registro": self.registro,
                "pin_rele": self.pin_rele,
                "intervalo": self.intervalo
            }
        }


servicio_rele = RelayMonitorService()
