"""Sensor del Estanque 3: canal CH3, bornera J21."""
from . import construir_sensor

CANAL = 3
NUMERO_ESTANQUE = 3
ESTANQUE = "Estanque 3"
BORNERA = "J21"
BOMBA = "P3"
BYPASS = False
RECREAR_TRAS_FALLOS = 3
REINTENTO_ERROR_INICIAL_S = 1.5
REINTENTO_ERROR_MAX_S = 30.0
REINTENTO_AUSENTE_INICIAL_S = 3.0
REINTENTO_AUSENTE_MAX_S = 10.0


def crear_sensor(sensor_class, mux):
    return construir_sensor(sensor_class, mux, CANAL)

