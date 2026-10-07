"""
Estado compartido entre los hilos de trabajo y la interfaz.

EL PROBLEMA QUE RESUELVE
    Hay cuatro hilos moviendo hardware (bombas, semaforos, sensores, tiras) y
    una ventana de Qt que tiene que mostrar lo que pasa. Si esos hilos tocaran
    los widgets directamente, la aplicacion se colgaria de forma aleatoria:
    Qt exige que solo el hilo principal manipule la interfaz.

LA SOLUCION, A PROPOSITO SIMPLE
    Una pizarra compartida protegida por un lock.

        HiloSecuencia  --escribe-->  +-------------------+
        HiloSemaforos  --escribe-->  | EstadoCompartido  |
        HiloSensores   --escribe-->  |     (lock)        |
        HiloTiras      --escribe-->  +-------------------+
                                              |
                                              | instantanea()
                                              v
                                     hilo principal de Qt
                                       (QTimer, 5 veces/s)

    Los hilos nunca saben que existe una interfaz; solo dejan datos aqui. La
    ventana los lee cuando quiere. Es mas simple que usar senales de Qt entre
    hilos y no tiene sus trampas.

DOS TIPOS DE DATO, QUE NO HAY QUE CONFUNDIR
    * Lo que PASA (estado): que reles estan encendidos, que color tiene cada
      semaforo, que miden los sensores. Vive aqui.
    * Lo que se CONFIGURA (parametros): cuantos segundos dura cada fase, de que
      color van las tiras. Vive en parametros.py.

    instantanea() junta los dos en un solo objeto para que la interfaz tenga
    todo lo que necesita pintar en una sola llamada.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field

import config
from hal import Lectura


# --------------------------------------------------------------------- fases
# Las fases del ciclo de bombas. Se usan como identificadores internos; el
# texto que ve el usuario sale del diccionario de abajo.
FASE_INICIO = "INICIO"
FASE_ENCENDIENDO = "ENCENDIENDO"    # se encienden de a una
FASE_SOSTENIDO = "SOSTENIDO"        # todas encendidas, aguantando
FASE_APAGANDO = "APAGANDO"          # se apagan de a una
FASE_APAGADAS = "APAGADAS"          # reposo antes de repetir el ciclo
FASE_DETENIDA = "DETENIDA"          # nadie esta corriendo la secuencia

DESCRIPCION_FASE = {
    FASE_INICIO: "Arranque: todo en estado seguro",
    FASE_ENCENDIENDO: "Encendiendo bombas de a una",
    FASE_SOSTENIDO: "Bombas encendidas",
    FASE_APAGANDO: "Apagando bombas de a una",
    FASE_APAGADAS: "Todas las bombas apagadas",
    FASE_DETENIDA: "Secuencia detenida",
}


@dataclass
class Instantanea:
    """Foto completa del sistema en un instante, para que la GUI la pinte.

    Es un objeto de solo lectura y desechable: se crea uno nuevo en cada
    refresco (5 veces por segundo) y se tira. Como los hilos siguen trabajando
    mientras la interfaz dibuja, esta foto garantiza que todo lo que se pinta
    corresponde al MISMO momento y no a una mezcla de instantes distintos.
    """

    # --- Lo que esta pasando ahora ---
    reles: dict[str, bool] = field(default_factory=dict)
    """{"P1": True, "P2": False, ...} - que bombas estan encendidas."""

    luminarias: dict[str, bool] = field(default_factory=dict)
    """{"L1": True} - que luminarias exteriores estan encendidas.

    Van aparte de `reles` a proposito, aunque fisicamente sean el mismo tipo de
    rele: las bombas las mueve la secuencia y las luminarias el operador, y
    mezclarlas haria que el resumen "n de 4 encendidas" contara luces.
    """

    semaforos: dict[str, dict[str, bool]] = field(default_factory=dict)
    """{"TL1": {"rojo": False, "amarillo": False, "verde": True}, ...}"""

    lecturas: list[Lectura] = field(default_factory=list)
    """Una Lectura por sensor, con distancia, nivel y si esta conectado."""

    tiras: dict[str, list[tuple[int, int, int]]] = field(default_factory=dict)
    """{"T1": [(r,g,b), (r,g,b), ...]} - color actual de cada LED."""

    # --- Lo que esta configurado (viene de parametros.py) ---
    tira_color: dict[str, tuple[int, int, int]] = field(default_factory=dict)
    """{"T1": (r, g, b)} - color configurado de CADA tira, por separado."""
    tira_color_nombre: dict[str, str] = field(default_factory=dict)
    tira_velocidad_ms: int = 60
    tira_n_leds: dict[str, int] = field(default_factory=dict)
    tiempos_bombas: tuple[float, float, float, float] = (1.0, 120.0, 1.0, 30.0)
    """(paso de encendido, sostenido, paso de apagado, apagadas) en segundos."""
    bombas_habilitadas: dict[str, bool] = field(default_factory=dict)
    """Una bomba deshabilitada a mano queda fuera de la secuencia."""

    # --- En que punto del ciclo va ---
    fase: str = FASE_INICIO
    restante_s: float = 0.0
    """Segundos que faltan para terminar la fase actual."""
    duracion_s: float = 0.0
    """Cuanto dura la fase completa. Con restante_s da el % de la barra."""
    ciclo: int = 0

    # --- Con que hardware se esta corriendo de verdad ---
    hay_hardware: bool = False
    sensores_reales: bool = False
    tiras_reales: bool = False

    log: list[str] = field(default_factory=list)
    """Las ultimas lineas del registro de eventos, ya con hora."""


class EstadoCompartido:
    """Pizarra protegida por un lock. Todo lo que cruza hilos pasa por aqui.

    Los metodos set_* los llaman los hilos de trabajo; instantanea() la llama
    la interfaz. El lock es lo unico que evita que la GUI lea un diccionario a
    medio actualizar.
    """

    def __init__(self, hay_hardware: bool, sensores_reales: bool,
                 tiras_reales: bool = False, parametros=None) -> None:
        self._lock = threading.Lock()

        # Los valores ajustables NO se duplican aqui: la instantanea los lee del
        # objeto Parametros, que es la unica fuente de verdad. Tenerlos en dos
        # lados terminaria, tarde o temprano, con los dos desincronizados.
        self._param = parametros

        self._reles: dict[str, bool] = {n: False for n in config.RELES}
        self._luminarias: dict[str, bool] = {n: False for n in config.LUMINARIAS}
        self._semaforos: dict[str, dict[str, bool]] = {}
        self._lecturas: list[Lectura] = []
        self._tiras: dict[str, list[tuple[int, int, int]]] = {}

        self._fase = FASE_INICIO
        # El progreso se guarda como INSTANTE DE TERMINO, no como "segundos
        # restantes". Asi la cuenta regresiva se calcula sola al leerla y no
        # hace falta que nadie la vaya descontando.
        self._fin_fase = time.monotonic()
        self._dur_fase = 0.0
        self._ciclo = 0

        self._hay_hardware = hay_hardware
        self._sensores_reales = sensores_reales
        self._tiras_reales = tiras_reales

        # deque con tope: el registro se autolimita y nunca crece sin control,
        # aunque el programa quede semanas encendido en la maqueta.
        self._log: deque[str] = deque(maxlen=config.MAX_LINEAS_LOG)

    # ------------------------------------------------------------- escritura
    # Todos guardan COPIAS. Si guardaran la referencia que les pasan, el hilo
    # que la envio podria seguir modificandola despues y la interfaz veria
    # datos cambiando bajo sus pies.

    def set_reles(self, estado: dict[str, bool]) -> None:
        with self._lock:
            self._reles = dict(estado)

    def set_luminarias(self, estado: dict[str, bool]) -> None:
        with self._lock:
            self._luminarias = dict(estado)

    def set_semaforos(self, estado: dict[str, dict[str, bool]]) -> None:
        with self._lock:
            self._semaforos = {k: dict(v) for k, v in estado.items()}

    def set_lecturas(self, lecturas: list[Lectura]) -> None:
        with self._lock:
            self._lecturas = list(lecturas)

    def set_tiras(self, pixeles: dict[str, list[tuple[int, int, int]]]) -> None:
        with self._lock:
            self._tiras = {k: list(v) for k, v in pixeles.items()}

    def set_fase(self, fase: str, duracion_s: float, ciclo: int | None = None) -> None:
        """Empieza una fase nueva de `duracion_s` segundos."""
        with self._lock:
            self._fase = fase
            self._fin_fase = time.monotonic() + duracion_s
            self._dur_fase = duracion_s
            if ciclo is not None:
                self._ciclo = ciclo

    def ajustar_fase(self, duracion_s: float, restante_s: float) -> None:
        """Cambia el total y lo que queda de la fase, SIN cambiar de fase.

        Lo usa el hilo de bombas cuando el operador mueve el tiempo de sostenido
        con la fase ya corriendo. Sin esto, bajar el sostenido de 120 s a 10 s
        acortaria la fase de verdad pero la barra de progreso seguiria dibujando
        el avance sobre los 120 s viejos.
        """
        with self._lock:
            self._dur_fase = duracion_s
            self._fin_fase = time.monotonic() + restante_s

    def registrar(self, mensaje: str) -> None:
        """Agrega una linea al registro de eventos que se ve en la ventana."""
        marca = time.strftime("%H:%M:%S")
        with self._lock:
            self._log.append(f"[{marca}] {mensaje}")

    # ---------------------------------------------------------------- lectura
    def instantanea(self) -> Instantanea:
        """Foto consistente de todo el sistema. La llama la GUI a 5 Hz."""

        # Los parametros se leen FUERA del lock propio, a proposito: Parametros
        # tiene su propio lock, y tomar uno teniendo el otro abre la puerta a un
        # interbloqueo si algun dia alguien hace la operacion inversa. Primero
        # se copia todo lo de Parametros, despues se toma el lock de aqui.
        if self._param is not None:
            color = self._param.colores()
            color_nombre = self._param.colores_nombre()
            velocidad = self._param.velocidad_ms()
            n_leds = self._param.n_leds_todas()
            tiempos = self._param.tiempos_bombas()
            habilitadas = self._param.habilitadas()
        else:
            # Sin objeto Parametros se usan los valores iniciales de config.
            # Pasa solo en pruebas: el controlador siempre pasa uno.
            color = {n: tuple(config.TIRA_COLOR_INICIAL)
                     for n in config.TIRAS}
            color_nombre = {n: config.TIRA_COLORES[0][0]
                            for n in config.TIRAS}
            velocidad = config.TIRA_VELOCIDAD_INICIAL_MS
            n_leds = {n: c["n_leds"] for n, c in config.TIRAS.items()}
            tiempos = (config.T_PASO_ENCENDIDO_S, config.T_SOSTENIDO_S,
                       config.T_PASO_APAGADO_S, config.T_APAGADAS_S)
            habilitadas = {n: True for n in config.RELES}

        with self._lock:
            return Instantanea(
                reles=dict(self._reles),
                luminarias=dict(self._luminarias),
                semaforos={k: dict(v) for k, v in self._semaforos.items()},
                lecturas=list(self._lecturas),
                tiras={k: list(v) for k, v in self._tiras.items()},
                tira_color=color,
                tira_color_nombre=color_nombre,
                tira_velocidad_ms=velocidad,
                tira_n_leds=n_leds,
                tiempos_bombas=tiempos,
                bombas_habilitadas=habilitadas,
                fase=self._fase,
                # Aqui se convierte el instante de termino en cuenta regresiva.
                restante_s=max(0.0, self._fin_fase - time.monotonic()),
                duracion_s=self._dur_fase,
                ciclo=self._ciclo,
                hay_hardware=self._hay_hardware,
                sensores_reales=self._sensores_reales,
                tiras_reales=self._tiras_reales,
                log=list(self._log),
            )

    def lecturas(self) -> list[Lectura]:
        """Solo las lecturas de sensores, para quien no necesite la foto entera."""
        with self._lock:
            return list(self._lecturas)
