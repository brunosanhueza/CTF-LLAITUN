"""
Parametros ajustables en caliente desde la interfaz.

QUE HACE ESTE ARCHIVO
    Guarda todo lo que el operador puede cambiar SIN reiniciar el programa:
    los cuatro tiempos del ciclo de bombas, que bombas estan habilitadas, y el
    largo, color y velocidad de las tiras LED.

COMO FUNCIONA EL AJUSTE EN CALIENTE
    No hay notificaciones ni eventos. Los hilos de trabajo simplemente RELEEN
    el valor en cada paso de su bucle:

        interfaz  --set_sostenido_s(10)-->  Parametros  <--sostenido_s()--  hilo
                                             (lock)                      (cada 0.1 s)

    Por eso bajar el sostenido de 120 s a 10 s se nota de inmediato aunque la
    fase ya este corriendo: el hilo compara el tiempo transcurrido contra el
    valor actual, no contra el que leyo al empezar.

POR QUE UN OBJETO APARTE Y NO VARIABLES SUELTAS
    Porque son datos compartidos entre hilos y necesitan un lock. Tenerlos
    todos en un mismo lugar hace evidente que son mutables y que hay que
    tomarlos con cuidado; repartidos por ahi terminarian leyendose a medio
    escribir.

    Ademas hay una sola fuente de verdad: EstadoCompartido no los copia, los
    consulta aqui al armar cada instantanea.

QUE NO ESTA AQUI, Y POR QUE
    * Pines y direcciones: son cableado, cambiarlos en caliente no tiene
      sentido. Viven en config.py.
    * TIRA_N_LEDS_MAX: rpi_ws281x fija el tamano del buffer al construir el
      objeto, asi que el maximo solo se puede cambiar reiniciando. Lo que si se
      ajusta aqui es el largo LOGICO dentro de ese maximo.
"""

from __future__ import annotations

import threading

import config


def _acotar(valor, minimo, maximo):
    """Recorta un valor al rango permitido. Nunca lanza excepcion."""
    return max(minimo, min(maximo, valor))


class Parametros:
    """Valores que la interfaz puede cambiar mientras el software corre.

    Todos los set_* ACOTAN al rango de config.py y devuelven el valor que
    quedo, que puede no ser el que se pidio. Recortar en silencio es
    deliberado: esto lo llama una interfaz grafica, y una excepcion a mitad de
    un evento de Qt es mucho peor que un valor ajustado al limite.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # --- Bombas ---
        self._paso_encendido_s = float(config.T_PASO_ENCENDIDO_S)
        self._sostenido_s = float(config.T_SOSTENIDO_S)
        self._paso_apagado_s = float(config.T_PASO_APAGADO_S)
        self._apagadas_s = float(config.T_APAGADAS_S)

        # Bomba deshabilitada a mano desde la interfaz: la secuencia la salta y
        # queda apagada aunque el ciclo siga corriendo.
        self._habilitada = {n: True for n in config.RELES}

        # --- Tiras LED ---
        self._n_leds = {n: int(cfg["n_leds"]) for n, cfg in config.TIRAS.items()}
        # Color POR TIRA: T1 y T2 pueden ir de colores distintos. Diccionarios
        # y no valores sueltos, por lo mismo que _n_leds.
        self._color = {n: tuple(config.TIRA_COLOR_INICIAL)
                       for n in config.TIRAS}
        self._color_nombre = {n: config.TIRA_COLORES[0][0]
                              for n in config.TIRAS}
        self._velocidad_ms = int(config.TIRA_VELOCIDAD_INICIAL_MS)

    # ======================================================== bombas: lectura
    def paso_encendido_s(self) -> float:
        with self._lock:
            return self._paso_encendido_s

    def sostenido_s(self) -> float:
        with self._lock:
            return self._sostenido_s

    def paso_apagado_s(self) -> float:
        with self._lock:
            return self._paso_apagado_s

    def apagadas_s(self) -> float:
        with self._lock:
            return self._apagadas_s

    def tiempos_bombas(self) -> tuple[float, float, float, float]:
        """(paso encendido, sostenido, paso apagado, apagadas) en segundos."""
        with self._lock:
            return (self._paso_encendido_s, self._sostenido_s,
                    self._paso_apagado_s, self._apagadas_s)

    def habilitada(self, bomba: str) -> bool:
        with self._lock:
            return self._habilitada[bomba]

    def habilitadas(self) -> dict[str, bool]:
        with self._lock:
            return dict(self._habilitada)

    # ====================================================== bombas: escritura
    def set_paso_encendido_s(self, segundos: float) -> float:
        valor = _acotar(float(segundos), config.T_PASO_MIN_S, config.T_PASO_MAX_S)
        with self._lock:
            self._paso_encendido_s = valor
        return valor

    def set_sostenido_s(self, segundos: float) -> float:
        valor = _acotar(float(segundos), config.T_SOSTENIDO_MIN_S,
                        config.T_SOSTENIDO_MAX_S)
        with self._lock:
            self._sostenido_s = valor
        return valor

    def set_paso_apagado_s(self, segundos: float) -> float:
        valor = _acotar(float(segundos), config.T_PASO_MIN_S, config.T_PASO_MAX_S)
        with self._lock:
            self._paso_apagado_s = valor
        return valor

    def set_apagadas_s(self, segundos: float) -> float:
        valor = _acotar(float(segundos), config.T_APAGADAS_MIN_S,
                        config.T_APAGADAS_MAX_S)
        with self._lock:
            self._apagadas_s = valor
        return valor

    def set_habilitada(self, bomba: str, habilitada: bool) -> bool:
        with self._lock:
            self._habilitada[bomba] = bool(habilitada)
            return self._habilitada[bomba]

    def alternar_habilitada(self, bomba: str) -> bool:
        with self._lock:
            self._habilitada[bomba] = not self._habilitada[bomba]
            return self._habilitada[bomba]

    # ========================================================= tiras: lectura
    def n_leds(self, tira: str) -> int:
        with self._lock:
            return self._n_leds[tira]

    def n_leds_todas(self) -> dict[str, int]:
        with self._lock:
            return dict(self._n_leds)

    def color(self, tira: str) -> tuple[int, int, int]:
        with self._lock:
            return self._color[tira]

    def color_nombre(self, tira: str) -> str:
        with self._lock:
            return self._color_nombre[tira]

    def colores(self) -> dict[str, tuple[int, int, int]]:
        with self._lock:
            return dict(self._color)

    def colores_nombre(self) -> dict[str, str]:
        with self._lock:
            return dict(self._color_nombre)

    def velocidad_ms(self) -> int:
        with self._lock:
            return self._velocidad_ms

    def animacion(self) -> tuple[dict, int, dict[str, int]]:
        """Todo lo que necesita el hilo de tiras, en una sola toma del lock.

        Devuelve ({tira: color}, velocidad, {tira: n_leds}). El hilo llama a
        esto en cada LED de la animacion, o sea hasta cien veces por barrido.
        Pedir los tres valores juntos evita tomar y soltar el lock tres veces
        seguidas, y de paso garantiza que colores, velocidad y largos
        correspondan al mismo instante.
        """
        with self._lock:
            return dict(self._color), self._velocidad_ms, dict(self._n_leds)

    # ======================================================= tiras: escritura
    def set_n_leds(self, tira: str, cantidad: int) -> int:
        """Largo LOGICO de una tira, entre 1 y TIRA_N_LEDS_MAX.

        No reconfigura el hardware: el buffer fisico se reservo al arrancar con
        el maximo, y los LED que sobran se escriben apagados. Reinicializar DMA
        cada vez que alguien mueve el control seria una fuente de cuelgues.
        """
        valor = int(_acotar(int(cantidad), 1, config.TIRA_N_LEDS_MAX))
        with self._lock:
            self._n_leds[tira] = valor
        return valor

    def set_color(self, tira: str, nombre: str, rgb) -> None:
        """Cambia el color de UNA tira; la otra no se entera."""
        with self._lock:
            self._color_nombre[tira] = nombre
            self._color[tira] = tuple(rgb)

    def set_velocidad_ms(self, ms: int) -> int:
        valor = int(_acotar(int(ms), config.TIRA_VELOCIDAD_MIN_MS,
                            config.TIRA_VELOCIDAD_MAX_MS))
        with self._lock:
            self._velocidad_ms = valor
        return valor
