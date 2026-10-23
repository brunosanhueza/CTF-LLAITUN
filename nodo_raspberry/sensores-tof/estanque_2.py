"""Sensor del Estanque 2: canal CH0, bornera J18."""
from . import construir_sensor

CANAL = 0
NUMERO_ESTANQUE = 2
ESTANQUE = "Estanque 2"
BORNERA = "J18"
BOMBA = "P2"
BYPASS = False
RECREAR_TRAS_FALLOS = 3
REINTENTO_ERROR_INICIAL_S = 1.5
REINTENTO_ERROR_MAX_S = 30.0
REINTENTO_AUSENTE_INICIAL_S = 3.0
REINTENTO_AUSENTE_MAX_S = 10.0


def crear_sensor(sensor_class, mux):
    return construir_sensor(sensor_class, mux, CANAL)

