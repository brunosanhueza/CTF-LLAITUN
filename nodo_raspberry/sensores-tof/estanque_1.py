"""Sensor del Estanque 1: canal CH2, bornera J20, actualmente en bypass."""
from . import construir_sensor

CANAL = 2
NUMERO_ESTANQUE = 1
ESTANQUE = "Estanque 1"
BORNERA = "J20"
BOMBA = "P1"
BYPASS = True
RECREAR_TRAS_FALLOS = 3
REINTENTO_ERROR_INICIAL_S = 1.5
REINTENTO_ERROR_MAX_S = 30.0
REINTENTO_AUSENTE_INICIAL_S = 3.0
REINTENTO_AUSENTE_MAX_S = 10.0


def crear_sensor(sensor_class, mux):
    return construir_sensor(sensor_class, mux, CANAL)

