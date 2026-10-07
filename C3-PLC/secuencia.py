"""
Hilos de trabajo del cuadrante 3: aqui vive la logica que DECIDE.

LOS CUATRO HILOS
    HiloSecuencia : mueve las bombas segun el ciclo de cuatro fases.
    HiloSemaforos : corre la secuencia de calle en los dos semaforos.
    HiloSensores  : lee los cuatro VL53L0X y detecta cuales estan conectados.
    HiloTiras     : anima las dos tiras WS2812B (llenado en fila).

POR QUE CUATRO HILOS Y NO UNO SOLO
    Porque los cuatro bloques van a ritmos completamente distintos: las tiras
    refrescan cada 60 ms, los sensores cada 500 ms, los semaforos cada 100 ms y
    las bombas se quedan quietas dos minutos. Meterlos en un mismo bucle
    obligaria a inventar un planificador; separados, cada uno se escribe como
    si fuera lo unico que existe.

    Son INDEPENDIENTES: ninguno lee el estado de otro. Detener las bombas no
    afecta a los semaforos ni a las tiras. La unica cosa que comparten es la
    pizarra donde publican lo que hacen.

EL PATRON QUE SIGUEN LOS CUATRO

    class HiloX(threading.Thread):
        def __init__(...):
            self._parar = threading.Event()   # la senal de "termina"

        def detener(self):
            self._parar.set()

        def run(self):
            try:
                while not self._parar.is_set():
                    ...hacer el trabajo...
                    if self._parar.wait(intervalo):   # <- la clave
                        return
            finally:
                ...dejar el hardware en estado seguro...

    LO IMPORTANTE ES ESE Event.wait() EN VEZ DE time.sleep().

    wait() devuelve True apenas alguien llama a detener(), sin esperar a que se
    cumpla el plazo. Con time.sleep(120) en la fase de sostenido, cerrar la
    ventana se quedaria colgado hasta dos minutos. Con wait(120) se corta al
    instante.

    Y el bloque finally es lo que garantiza que las bombas queden apagadas
    aunque el hilo muera por una excepcion inesperada.

DE DONDE SALEN LOS VALORES
    Los hilos releen parametros.Parametros en CADA PASO, no al arrancar. Por
    eso cambiar un tiempo o un color desde la interfaz se nota de inmediato,
    incluso a mitad de una fase.
"""

from __future__ import annotations

import logging
import threading
import time

import config
import estado as est
from actuadores import BancoReles, BancoSemaforos
from estado import EstadoCompartido
from parametros import Parametros

log = logging.getLogger(__name__)


# =============================================================================
#  Bombas
# =============================================================================

class HiloSecuencia(threading.Thread):
    """El ciclo de las bombas, en cuatro fases que se repiten para siempre.

        1. ENCENDIENDO  se encienden de a una, cada N segundos
        2. SOSTENIDO    quedan encendidas (fase larga)
        3. APAGANDO     se apagan de a una, cada N segundos
        4. APAGADAS     reposo antes de volver a empezar (fase larga)

    Las bombas deshabilitadas a mano desde la interfaz se saltan en la fase 1 y
    se mantienen apagadas durante la 2.

    Es el unico hilo que se puede detener y volver a arrancar desde la interfaz;
    los otros tres corren desde el inicio hasta que se cierra el programa.
    """

    def __init__(self, reles: BancoReles, compartido: EstadoCompartido,
                 parametros: Parametros) -> None:
        # daemon=True: si el programa principal muere sin cerrar bien, este hilo
        # no impide que el proceso termine.
        super().__init__(name="secuencia", daemon=True)
        self._reles = reles
        self._estado = compartido
        self._param = parametros
        self._parar = threading.Event()

    def detener(self) -> None:
        """Pide al hilo que termine. No bloquea; usar join() para esperarlo."""
        self._parar.set()

    def _esperar(self, segundos: float) -> bool:
        """Espera interrumpible. Devuelve True si hay que SEGUIR corriendo.

        Ojo con el sentido: Event.wait() devuelve True cuando hay que PARAR, y
        aqui se invierte para que en el codigo se lea
        `if not self._esperar(...): return`, que es mas natural.
        """
        return not self._parar.wait(segundos)

    def _publicar(self) -> None:
        """Deja el estado de los reles en la pizarra para que lo vea la GUI."""
        self._estado.set_reles(self._reles.estado())

    def _fase(self, fase: str, duracion_s: float, ciclo: int | None = None) -> None:
        """Anuncia una fase nueva: la publica y la deja en el registro."""
        self._estado.set_fase(fase, duracion_s, ciclo)
        self._estado.registrar(est.DESCRIPCION_FASE[fase])

    def _fase_larga(self, fase: str, ciclo: int, leer_objetivo,
                    reasignar_bombas: bool) -> bool:
        """Fase de duracion larga, sensible a cambios mientras corre.

        En vez de una sola espera larga, se espera en tramos cortos y se compara
        el tiempo transcurrido contra el valor ACTUAL del parametro. Asi, si el
        operador baja el sostenido de 120 s a 10 s con las bombas ya encendidas,
        el cambio se aplica de inmediato en vez de esperar los dos minutos.

        Con reasignar_bombas=True, ademas se reaplica en cada vuelta el estado
        que corresponde a cada bomba segun este habilitada o no. Es lo que hace
        que apagar una bomba con un clic surta efecto al instante, aunque la
        secuencia este a la mitad de la fase.

        Devuelve False si hay que terminar el hilo.
        """
        objetivo = leer_objetivo()
        self._fase(fase, objetivo, ciclo)

        # time.monotonic() y no time.time(): es un reloj que solo avanza y no
        # da saltos si alguien cambia la hora del sistema o entra un ajuste NTP.
        inicio = time.monotonic()
        anterior = objetivo
        while not self._parar.is_set():
            # El objetivo se relee EN CADA VUELTA. Ese es todo el truco: la
            # condicion de salida se compara siempre contra el valor actual.
            objetivo = leer_objetivo()
            transcurrido = time.monotonic() - inicio
            if transcurrido >= objetivo:
                return True

            if objetivo != anterior:
                # Cambio el tiempo a mitad de fase: hay que corregir tambien la
                # barra de progreso, o seguiria avanzando sobre el total viejo.
                self._estado.ajustar_fase(objetivo, objetivo - transcurrido)
                self._estado.registrar(f"Duracion de la fase: {objetivo:.0f} s")
                anterior = objetivo

            if reasignar_bombas and self._sincronizar_habilitadas():
                self._publicar()

            # Tramos de 100 ms como maximo, para reaccionar rapido a los
            # cambios. El min() evita pasarse del objetivo en el ultimo tramo.
            if self._parar.wait(min(0.1, objetivo - transcurrido)):
                return False
        return False

    def _sincronizar_habilitadas(self) -> bool:
        """Pone cada bomba en el estado que le toca segun su habilitacion.

        Es lo que hace que el clic en la luz de una bomba surta efecto de
        inmediato: la interfaz solo levanta o baja una bandera, y este metodo,
        que corre diez veces por segundo durante la fase de sostenido, la
        traduce en encender o apagar el rele.

        Devuelve True si hubo algun cambio, para no publicar en vano.
        """
        habilitadas = self._param.habilitadas()
        actual = self._reles.estado()
        hubo_cambio = False
        for nombre, habilitada in habilitadas.items():
            if actual.get(nombre, False) != habilitada:
                if habilitada:
                    self._reles.encender(nombre)
                else:
                    self._reles.apagar(nombre)
                hubo_cambio = True
        return hubo_cambio

    def run(self) -> None:
        ciclo = 0
        try:
            while not self._parar.is_set():
                ciclo += 1

                # --- Fase 1: encendido escalonado -------------------------
                paso = self._param.paso_encendido_s()
                self._fase(est.FASE_ENCENDIENDO,
                           len(config.ORDEN_ENCENDIDO) * paso, ciclo)
                for nombre in config.ORDEN_ENCENDIDO:
                    if self._param.habilitada(nombre):
                        self._reles.encender(nombre)
                        self._estado.registrar(
                            f"{nombre} ({config.RELES[nombre]['etiqueta']}) encendida"
                        )
                    else:
                        self._estado.registrar(
                            f"{nombre} deshabilitada, se salta"
                        )
                    self._publicar()
                    # Se relee en cada paso: si el operador mueve el control a
                    # mitad de la rampa, el resto de las bombas ya usa el valor
                    # nuevo.
                    if not self._esperar(self._param.paso_encendido_s()):
                        return

                # --- Fase 2: sostenido ------------------------------------
                self._estado.registrar(
                    f"Bombas habilitadas encendidas por "
                    f"{self._param.sostenido_s():.0f} s"
                )
                if not self._fase_larga(est.FASE_SOSTENIDO, ciclo,
                                        self._param.sostenido_s,
                                        reasignar_bombas=True):
                    return

                # --- Fase 3: apagado escalonado ---------------------------
                paso = self._param.paso_apagado_s()
                self._fase(est.FASE_APAGANDO,
                           len(config.ORDEN_APAGADO) * paso, ciclo)
                for nombre in config.ORDEN_APAGADO:
                    self._reles.apagar(nombre)
                    self._estado.registrar(
                        f"{nombre} ({config.RELES[nombre]['etiqueta']}) apagada"
                    )
                    self._publicar()
                    if not self._esperar(self._param.paso_apagado_s()):
                        return

                # --- Fase 4: reposo con todas apagadas --------------------
                if self._param.apagadas_s() > 0:
                    self._estado.registrar(
                        f"Todas apagadas por {self._param.apagadas_s():.0f} s"
                    )
                    if not self._fase_larga(est.FASE_APAGADAS, ciclo,
                                            self._param.apagadas_s,
                                            reasignar_bombas=False):
                        return

                self._estado.registrar(f"Ciclo {ciclo} completo")
        except Exception:
            log.exception("Error en el hilo de secuencia; se apaga todo.")
            self._estado.registrar("ERROR en la secuencia, ver el log")
        finally:
            # Pase lo que pase, las bombas quedan apagadas.
            self._reles.apagar_todos()
            self._publicar()
            self._estado.set_fase(est.FASE_DETENIDA, 0.0)
            self._estado.registrar("Secuencia detenida, bombas en estado seguro")


# =============================================================================
#  Semaforos
# =============================================================================

class HiloSemaforos(threading.Thread):
    """Secuencia de calle en bucle infinito, con desfase entre semaforos.

    En vez de recorrer los colores paso a paso, se calcula el color a partir del
    reloj: para cada semaforo se toma (t + desfase) modulo el periodo del ciclo
    y se busca en que tramo cae. Asi los dos semaforos mantienen su desfase
    relativo exacto para siempre, sin acumular deriva.
    """

    def __init__(self, semaforos: BancoSemaforos,
                 compartido: EstadoCompartido) -> None:
        super().__init__(name="semaforos", daemon=True)
        self._semaforos = semaforos
        self._estado = compartido
        self._parar = threading.Event()
        self._periodo = sum(dur for _, dur in config.SEMAFORO_SECUENCIA)
        if self._periodo <= 0:
            raise ValueError("config.SEMAFORO_SECUENCIA no puede sumar 0 s")

    def detener(self) -> None:
        self._parar.set()

    def _color_en(self, t: float) -> str:
        """Color que corresponde al instante t dentro del ciclo."""
        pos = t % self._periodo
        acumulado = 0.0
        for color, duracion in config.SEMAFORO_SECUENCIA:
            acumulado += duracion
            if pos < acumulado:
                return color
        return config.SEMAFORO_SECUENCIA[-1][0]

    def run(self) -> None:
        secuencia = " -> ".join(
            f"{c} {d:.0f}s" for c, d in config.SEMAFORO_SECUENCIA
        )
        self._estado.registrar(
            f"Semaforos en secuencia de calle: {secuencia} "
            f"(ciclo de {self._periodo:.0f} s)"
        )
        for nombre, desfase in config.SEMAFORO_DESFASE_S.items():
            if desfase:
                self._estado.registrar(f"{nombre} desfasado {desfase:.0f} s")

        t0 = time.monotonic()
        try:
            while not self._parar.is_set():
                t = time.monotonic() - t0
                for nombre in config.SEMAFOROS:
                    desfase = config.SEMAFORO_DESFASE_S.get(nombre, 0.0)
                    self._semaforos.color(nombre, self._color_en(t + desfase))
                self._estado.set_semaforos(self._semaforos.estado_por_luz())
                if self._parar.wait(config.SEMAFORO_PERIODO_ACTUALIZACION_S):
                    return
        except Exception:
            log.exception("Error en el hilo de semaforos.")
            self._estado.registrar("ERROR en los semaforos, ver el log")
        finally:
            self._semaforos.apagar_todos()
            self._estado.set_semaforos(self._semaforos.estado_por_luz())


# =============================================================================
#  Sensores
# =============================================================================

class HiloSensores(threading.Thread):
    """Muestrea los cuatro VL53L0X y avisa cuando alguno se conecta o se cae."""

    def __init__(self, banco_sensores, compartido: EstadoCompartido) -> None:
        super().__init__(name="sensores", daemon=True)
        self._sensores = banco_sensores
        self._estado = compartido
        self._parar = threading.Event()
        self._conectado_antes: dict[int, bool] = {}

    def detener(self) -> None:
        self._parar.set()

    def _avisar_cambios(self, lecturas) -> None:
        """Registra solo las transiciones conectado <-> desconectado."""
        for lectura in lecturas:
            ahora = lectura.conectado
            antes = self._conectado_antes.get(lectura.canal)
            if antes is None:
                if not ahora:
                    self._estado.registrar(
                        f"Canal {lectura.canal} ({lectura.bornera}, "
                        f"{lectura.etiqueta}): sin sensor"
                    )
            elif ahora != antes:
                texto = "conectado" if ahora else "DESCONECTADO"
                self._estado.registrar(
                    f"Canal {lectura.canal} ({lectura.bornera}, "
                    f"{lectura.etiqueta}): {texto}"
                )
            self._conectado_antes[lectura.canal] = ahora

    def _volcar_diagnosticos(self) -> None:
        """Pasa al registro de la interfaz lo que el banco tenga que decir.

        Sin esto, los mensajes del HAL se quedan en el log de Python, que nadie
        ve si la aplicacion se lanzo desde el escritorio en vez del terminal.
        """
        obtener = getattr(self._sensores, "diagnosticos", None)
        if obtener is None:
            return
        for mensaje in obtener():
            self._estado.registrar(mensaje)

    def run(self) -> None:
        try:
            self._volcar_diagnosticos()
            while not self._parar.is_set():
                lecturas = self._sensores.leer_todos()
                self._estado.set_lecturas(lecturas)
                self._avisar_cambios(lecturas)
                self._volcar_diagnosticos()
                if self._parar.wait(config.PERIODO_MUESTREO_S):
                    return
        except Exception:
            log.exception("Error en el hilo de sensores.")
            self._estado.registrar("ERROR en la lectura de sensores, ver el log")


# =============================================================================
#  Tiras LED
# =============================================================================

class HiloTiras(threading.Thread):
    """Animacion de llenado: los LED se encienden en fila hasta llenar la tira.

    El color y la velocidad se cambian en caliente desde la interfaz; el hilo
    los lee en cada paso, asi que el cambio se ve de inmediato sin cortar la
    animacion ni reiniciarla.
    """

    def __init__(self, banco_tiras, compartido: EstadoCompartido,
                 parametros: Parametros) -> None:
        super().__init__(name="tiras", daemon=True)
        self._tiras = banco_tiras
        self._estado = compartido
        self._param = parametros
        self._parar = threading.Event()

    def detener(self) -> None:
        self._parar.set()

    # ----------------------------------------------------------------- animar
    def _pintar(self, encendidos: int, colores: dict, n_leds: dict[str, int]) -> None:
        """Enciende los primeros `encendidos` LED de cada tira, CADA UNA con
        su propio color: T1 y T2 se configuran por separado desde la interfaz.

        Se cargan las dos tiras y recien despues se refresca: ws2811_render()
        manda los dos canales juntos, asi que llamarlo una vez por tira seria
        el doble de trabajo para el mismo resultado.
        """
        for nombre in config.TIRAS:
            n = n_leds.get(nombre, 0)
            color = colores.get(nombre, (0, 0, 0))
            pixeles = [color if i < encendidos else (0, 0, 0) for i in range(n)]
            self._tiras.set_pixeles(nombre, pixeles)
        self._tiras.mostrar()
        self._estado.set_tiras(self._tiras.pixeles())

    def run(self) -> None:
        self._estado.registrar("Tiras en animacion de llenado")
        try:
            while not self._parar.is_set():
                # El largo se relee al inicio de cada barrido y tambien dentro,
                # para que acortar una tira desde la interfaz se note enseguida.
                _, _, n_leds = self._param.animacion()
                n_max = max(n_leds.values()) if n_leds else 0

                i = 1
                while i <= n_max and not self._parar.is_set():
                    colores, velocidad_ms, n_leds = self._param.animacion()
                    n_max = max(n_leds.values()) if n_leds else 0
                    if i > n_max:
                        break
                    self._pintar(i, colores, n_leds)
                    if self._parar.wait(velocidad_ms / 1000.0):
                        return
                    i += 1

                # Queda llena un instante, se apaga y vuelve a empezar.
                if self._parar.wait(config.TIRA_PAUSA_LLENA_MS / 1000.0):
                    return
                self._pintar(0, {}, self._param.n_leds_todas())
                if self._parar.wait(config.TIRA_PAUSA_LLENA_MS / 2000.0):
                    return
        except Exception:
            log.exception("Error en el hilo de tiras.")
            self._estado.registrar("ERROR en las tiras LED, ver el log")
        finally:
            try:
                self._tiras.apagar_todas()
                self._estado.set_tiras(self._tiras.pixeles())
            except Exception:
                log.exception("No se pudieron apagar las tiras al salir.")
