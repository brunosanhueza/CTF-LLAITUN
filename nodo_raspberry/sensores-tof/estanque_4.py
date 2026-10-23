"""Sensor del Estanque 4: canal CH1, bornera J19."""
from . import construir_sensor

CANAL = 1
NUMERO_ESTANQUE = 4
ESTANQUE = "Estanque 4"
BORNERA = "J19"
BOMBA = "P4"
BYPASS = False
RECREAR_TRAS_FALLOS = 3
REINTENTO_ERROR_INICIAL_S = 1.5
REINTENTO_ERROR_MAX_S = 30.0
REINTENTO_AUSENTE_INICIAL_S = 3.0
REINTENTO_AUSENTE_MAX_S = 10.0


def crear_sensor(sensor_class, mux):
    return construir_sensor(sensor_class, mux, CANAL)

