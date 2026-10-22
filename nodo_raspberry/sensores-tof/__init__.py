"""Registro de sensores ToF conectados al TCA9548A.

Cada estanque declara su canal y su identidad en un modulo propio. Este
paquete no abre el bus: el proceso i2c_worker sigue siendo su unico propietario.
"""
from importlib import import_module


IO_TIMEOUT_S = 0.5
_MODULOS = ("estanque_1", "estanque_2", "estanque_3", "estanque_4")


def construir_sensor(sensor_class, mux, canal):
    """Crea un VL53L0X sobre el canal asignado y conserva el timeout comun."""
    sensor = sensor_class(mux[canal])
    if hasattr(sensor, "io_timeout_s"):
        sensor.io_timeout_s = IO_TIMEOUT_S
    return sensor


def _cargar_sensores():
    sensores = {}
    for nombre_modulo in _MODULOS:
        modulo = import_module(".%s" % nombre_modulo, __name__)
        canal = modulo.CANAL
        if type(canal) is not int or canal not in range(4):
            raise ValueError("Canal ToF invalido en %s" % nombre_modulo)
        if canal in sensores:
            raise ValueError("Canal ToF duplicado: %d" % canal)
        sensores[canal] = modulo
    if set(sensores) != set(range(4)):
        raise ValueError("El registro ToF debe declarar los canales 0, 1, 2 y 3")
    return sensores


SENSORES = _cargar_sensores()
CANALES = tuple(sorted(SENSORES))
CANALES_BYPASS = tuple(c for c in CANALES if SENSORES[c].BYPASS)

