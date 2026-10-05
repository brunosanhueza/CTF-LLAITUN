"""
Controlador del cuadrante 3: la pieza que arma y coordina todo lo demas.

QUE HACE ESTE ARCHIVO
    Es el "director de orquesta". Construye el hardware (o su simulacion),
    los actuadores, los sensores, el estado compartido y los parametros; lanza
    los cuatro hilos de trabajo; y expone hacia arriba un puñado de ordenes en
    lenguaje llano: iniciar, detener, apagar una bomba, cambiar un tiempo,
    parada de emergencia, cerrar.

POR QUE EXISTE
    Para que la interfaz no tenga que saber nada de hardware. El dashboard
    llama a controlador.alternar_bomba("P2") y se despreocupa de reles, niveles
    logicos e hilos. El mismo controlador lo usa prueba_consola.py, que no tiene
    interfaz grafica: por eso ninguna de estas clases importa PyQt.

EL MAPA COMPLETO DEL PROYECTO
                    config.py          (pines, tiempos iniciales, limites)
                    parametros.py      (lo que se ajusta en caliente)
                          |
    hal.py  ------------->|            (GPIO, sensores y tiras; real o simulado)
      |                   |
      v                   v
    actuadores.py --> CONTROLADOR <-- estado.py   (la pizarra compartida)
                          |
                          v
              secuencia.py / plc_bridge.py   (quien decide: la demo local
                          |                    o el PLC por Modbus)
                          v
              dashboard.py / prueba_consola.py    (lo que ve el operador)

ORDEN DE CONSTRUCCION, QUE NO ES CASUAL
    Los actuadores se crean ANTES que nada porque su constructor deja reles y
    semaforos en estado seguro. Si algo fallara mas adelante, las bombas ya
    quedaron apagadas.
"""

from __future__ import annotations

import logging

import config
import hal
from actuadores import BancoReles, BancoSemaforos
from estado import EstadoCompartido
from parametros import Parametros
from plc_bridge import HiloPLC
from secuencia import HiloSecuencia, HiloSemaforos, HiloSensores, HiloTiras

log = logging.getLogger(__name__)


class Controlador:
    """Arma el sistema completo y expone las ordenes que necesita la interfaz.

    Argumentos:
        forzar_simulacion: ignora el hardware aunque exista. Sirve para
            desarrollar la interfaz en el PC.
        canales_simulados: en simulacion, que canales de sensor fingir
            conectados. Con [] se prueba como se ve todo desconectado.
    """

    def __init__(self, forzar_simulacion: bool = False,
                 canales_simulados=None) -> None:
        # 1. El GPIO. Si RPi.GPIO no esta disponible se devuelve un simulador y
        #    hay_hardware queda en False; de ahi en adelante nadie mas se entera.
        self.gpio, self.hay_hardware = hal.crear_gpio(forzar_simulacion)
        self.gpio.setmode(self.gpio.BCM)

        # 2. Actuadores. Van primero a proposito: sus constructores dejan reles
        #    y semaforos apagados, asi que a partir de esta linea la maqueta ya
        #    esta en estado seguro pase lo que pase despues.
        #
        #    Son dos bancos de reles de la misma clase pero con distinto dueno:
        #    las bombas las mueve la secuencia, las luminarias el operador.
        self.reles = BancoReles(self.gpio, config.RELES, "bombas")
        self.luminarias = BancoReles(
            self.gpio, config.LUMINARIAS, "luminarias",
            # Polaridad propia: son LED directos al GPIO, encienden en ALTO
            # (los reles de las bombas encienden en bajo).
            activo_en_bajo=config.LUMINARIA_ACTIVO_EN_BAJO,
        )
        self.semaforos = BancoSemaforos(self.gpio)

        # Las luminarias parten apagadas salvo que se pida lo contrario en
        # config. Se aplica DESPUES del constructor, que ya dejo el rele en su
        # nivel seguro: asi el encendido inicial, si lo hay, es explicito.
        if config.LUMINARIA_ENCENDIDA_AL_INICIO:
            for nombre in config.LUMINARIAS:
                self.luminarias.encender(nombre)

        # 3. Sensores. Se le pasa self.reles.estado (la funcion, no el
        #    resultado) porque el simulador la usa para su modelo hidraulico:
        #    sube el nivel del estanque cuyo rele esta encendido.
        self.sensores = hal.crear_banco_sensores(
            self.gpio, self.hay_hardware, self.reles.estado,
            canales_simulados=canales_simulados,
        )
        self.sensores_reales = isinstance(self.sensores, hal.BancoSensoresVL53L0X)

        # 4. Tiras LED. Puede quedar en simulacion aunque el resto sea real,
        #    tipicamente por falta de sudo.
        self.tiras, self.tiras_reales = hal.crear_banco_tiras(self.hay_hardware)

        # 5. Parametros ajustables y pizarra compartida.
        self.parametros = Parametros()
        self.compartido = EstadoCompartido(
            self.hay_hardware, self.sensores_reales, self.tiras_reales,
            parametros=self.parametros,
        )
        self.compartido.set_reles(self.reles.estado())
        self.compartido.set_luminarias(self.luminarias.estado())
        self.compartido.set_semaforos(self.semaforos.estado_por_luz())
        self.compartido.set_tiras(self.tiras.pixeles())
        self.compartido.registrar(
            f"{config.NOMBRE_CUADRANTE} - "
            f"{'hardware real' if self.hay_hardware else 'simulacion'}"
        )
        # Se informa el motivo REAL de cada tira que no arranco, en vez de
        # atribuirlo siempre a la falta de sudo.
        for nombre, motivo in getattr(self.tiras, "errores", {}).items():
            etiqueta = "Tiras LED" if nombre == "*" else f"Tira {nombre}"
            self.compartido.registrar(f"{etiqueta} sin iniciar: {motivo}")
        if self.tiras_reales:
            activas = sorted(self.tiras.activas())
            self.compartido.registrar(
                f"Tiras activas: {', '.join(activas) if activas else 'ninguna'}"
            )

        # Bandera de cierre. cerrar() se llama desde DOS lados: el closeEvent de
        # la ventana y el finally de main.py. Los dos son necesarios (el segundo
        # cubre el caso de que la interfaz reviente antes de cerrarse), asi que
        # el metodo tiene que tolerar que lo llamen de nuevo.
        self._cerrado = False

        # 6. Los hilos, todavia sin arrancar. Quien construye el controlador
        #    decide cuales lanzar con los metodos iniciar_*.
        self._hilo_secuencia: HiloSecuencia | None = None
        self._hilo_semaforos: HiloSemaforos | None = None
        self._hilo_sensores: HiloSensores | None = None
        self._hilo_tiras: HiloTiras | None = None
        self._hilo_plc: HiloPLC | None = None

    # ------------------------------------------------------------ verificacion
    def prueba_de_luces(self, pausa_s: float = 0.4) -> None:
        """Enciende las tres luces de los dos semaforos, una por una.

        Es la comprobacion de cableado del arranque: si una luz no prende, el
        problema esta en la bornera o en la resistencia limitadora, no en el
        software. Se ejecuta de forma SINCRONA y antes de lanzar los hilos,
        para que nadie mas este manejando los semaforos mientras tanto.
        """
        self.compartido.registrar("Prueba de luces de los semaforos")
        self.semaforos.prueba_de_luces(pausa_s=pausa_s)
        self.compartido.set_semaforos(self.semaforos.estado_por_luz())

    # ---------------------------------------------------------------- sensores
    # Los cuatro metodos iniciar_* comparten la misma forma: si el hilo ya esta
    # vivo no hacen nada, asi que llamarlos dos veces es inofensivo.
    def iniciar_sensores(self) -> None:
        if self._hilo_sensores is not None and self._hilo_sensores.is_alive():
            return
        self._hilo_sensores = HiloSensores(self.sensores, self.compartido)
        self._hilo_sensores.start()
        self.compartido.registrar(
            f"Muestreo de sensores cada {config.PERIODO_MUESTREO_S:.1f} s"
        )

    # --------------------------------------------------------------- semaforos
    def iniciar_semaforos(self) -> None:
        """Arranca la secuencia de calle. Corre para siempre, en paralelo."""
        if self._hilo_semaforos is not None and self._hilo_semaforos.is_alive():
            return
        self._hilo_semaforos = HiloSemaforos(self.semaforos, self.compartido)
        self._hilo_semaforos.start()

    # ------------------------------------------------------------------- tiras
    def iniciar_tiras(self) -> None:
        if self._hilo_tiras is not None and self._hilo_tiras.is_alive():
            return
        self._hilo_tiras = HiloTiras(self.tiras, self.compartido, self.parametros)
        self._hilo_tiras.start()

    def tira_velocidad_ms(self) -> int:
        return self.parametros.velocidad_ms()

    def acelerar_tiras(self) -> None:
        """Menos milisegundos por LED = animacion mas rapida."""
        self._ajustar_velocidad(-config.TIRA_PASO_VELOCIDAD_MS)

    def frenar_tiras(self) -> None:
        self._ajustar_velocidad(+config.TIRA_PASO_VELOCIDAD_MS)

    def _ajustar_velocidad(self, delta_ms: int) -> None:
        nueva = self.parametros.set_velocidad_ms(
            self.parametros.velocidad_ms() + delta_ms
        )
        self.compartido.registrar(f"Velocidad de las tiras: {nueva} ms por LED")

    def set_color_tira(self, tira: str, nombre: str, rgb) -> None:
        """Cambia el color de UNA tira. Cada una tiene su propio desplegable."""
        self.parametros.set_color(tira, nombre, rgb)
        self.compartido.registrar(f"Tira {tira}: color {nombre}")

    def color_nombre_tira(self, tira: str) -> str:
        return self.parametros.color_nombre(tira)

    def set_n_leds(self, tira: str, cantidad: int) -> int:
        """Cambia el largo de una tira. Los LED que sobran quedan apagados."""
        nueva = self.parametros.set_n_leds(tira, cantidad)
        self.compartido.registrar(f"Tira {tira}: {nueva} LED")
        return nueva

    def n_leds(self, tira: str) -> int:
        return self.parametros.n_leds(tira)

    # ------------------------------------------------------- control de bombas
    def tiempos_bombas(self) -> tuple[float, float, float, float]:
        """(paso encendido, sostenido, paso apagado, apagadas) en segundos."""
        return self.parametros.tiempos_bombas()

    def bombas_habilitadas(self) -> dict[str, bool]:
        return self.parametros.habilitadas()

    def alternar_bomba(self, nombre: str) -> bool:
        """Habilita o deshabilita una bomba, al margen de la secuencia.

        Deshabilitarla la apaga en el acto y hace que la secuencia la salte en
        los ciclos siguientes. Volver a habilitarla la enciende de inmediato si
        la secuencia esta en la fase de sostenido; si no, entra en el proximo
        ciclo.
        """
        habilitada = self.parametros.alternar_habilitada(nombre)
        etiqueta = config.RELES[nombre]["etiqueta"]
        if not habilitada:
            # Se apaga aqui mismo para que el clic se sienta instantaneo. La
            # bandera es lo que impide que la secuencia la vuelva a encender:
            # sin ella, el proximo ciclo la prenderia y el clic no serviria.
            self.reles.apagar(nombre)
            self.compartido.registrar(f"{nombre} ({etiqueta}) apagada a mano")
        else:
            # Al habilitarla no se enciende aqui: de eso se encarga la fase de
            # sostenido, que reaplica el estado de cada bomba en cada vuelta.
            self.compartido.registrar(f"{nombre} ({etiqueta}) habilitada")
        self.compartido.set_reles(self.reles.estado())
        return habilitada

    # Los cuatro set_* siguientes ajustan los tiempos del ciclo en caliente.
    # Solo escriben en Parametros y dejan constancia en el registro; los hilos
    # releen el valor en cada paso, asi que el cambio surte efecto solo.
    def set_paso_encendido_s(self, segundos: float) -> float:
        valor = self.parametros.set_paso_encendido_s(segundos)
        self.compartido.registrar(f"Paso de encendido: {valor:.1f} s por bomba")
        return valor

    def set_sostenido_s(self, segundos: float) -> float:
        valor = self.parametros.set_sostenido_s(segundos)
        self.compartido.registrar(f"Tiempo encendidas: {valor:.0f} s")
        return valor

    def set_paso_apagado_s(self, segundos: float) -> float:
        valor = self.parametros.set_paso_apagado_s(segundos)
        self.compartido.registrar(f"Paso de apagado: {valor:.1f} s por bomba")
        return valor

    def set_apagadas_s(self, segundos: float) -> float:
        valor = self.parametros.set_apagadas_s(segundos)
        self.compartido.registrar(f"Tiempo apagadas: {valor:.0f} s")
        return valor

    # -------------------------------------------------------------- luminarias
    # Las luminarias exteriores no tienen ciclo ni hilo propio: son LED que
    # el operador enciende y apaga desde la interfaz y que se queda como lo
    # dejaron. Por eso aqui no hay nada que "iniciar", solo estas tres ordenes.
    def luminarias_estado(self) -> dict[str, bool]:
        return self.luminarias.estado()

    def luminaria_encendida(self, nombre: str) -> bool:
        return self.luminarias.estado().get(nombre, False)

    def alternar_luminaria(self, nombre: str) -> bool:
        """Enciende o apaga una luminaria. Devuelve como quedo."""
        encendida = self.luminarias.alternar(nombre)
        etiqueta = config.LUMINARIAS[nombre]["etiqueta"]
        self.compartido.registrar(
            f"{nombre} ({etiqueta}) {'encendidas' if encendida else 'apagadas'}"
        )
        self.compartido.set_luminarias(self.luminarias.estado())
        return encendida

    def set_luminaria(self, nombre: str, encendida: bool) -> None:
        """Deja la luminaria en el estado pedido, venga de donde venga."""
        self.luminarias.set(nombre, encendida)
        self.compartido.set_luminarias(self.luminarias.estado())

    # --------------------------------------------------------------- secuencia
    def secuencia_activa(self) -> bool:
        return self._hilo_secuencia is not None and self._hilo_secuencia.is_alive()

    def iniciar_secuencia(self) -> None:
        if self.secuencia_activa():
            return
        self._hilo_secuencia = HiloSecuencia(
            self.reles, self.compartido, self.parametros
        )
        self._hilo_secuencia.start()
        self.compartido.registrar("Secuencia de bombas iniciada")

    def detener_secuencia(self, espera_s: float = 3.0) -> None:
        """Pide al hilo que termine y espera a que lo haga.

        El join() importa: el bloque finally del hilo es el que apaga las
        bombas, asi que hay que darle tiempo de ejecutarse antes de seguir.
        Como el hilo espera con Event.wait() y no con sleep(), reacciona al
        instante y el timeout casi nunca se agota.
        """
        if self._hilo_secuencia is None:
            return
        self._hilo_secuencia.detener()
        self._hilo_secuencia.join(timeout=espera_s)
        self._hilo_secuencia = None

    # ------------------------------------------------------------ puente PLC
    def puente_plc_activo(self) -> bool:
        return self._hilo_plc is not None and self._hilo_plc.is_alive()

    def iniciar_puente_plc(self) -> None:
        """Arranca el puente Modbus con el PLC.

        A partir de este momento las cuatro bombas dejan de moverlas la
        secuencia local (si estaba corriendo, se detiene aqui mismo, porque
        los dos hilos escriben sobre los mismos reles y competirian entre
        si): las mueve lo que el PLC mande por Modbus. Es el modo pensado
        para la maqueta en competencia; la secuencia local sigue existiendo
        para probar el hardware en el banco sin el PLC conectado.
        """
        if self.puente_plc_activo():
            return
        if self.secuencia_activa():
            self.compartido.registrar(
                "Secuencia local detenida: el puente PLC toma el control "
                "de las bombas"
            )
            self.detener_secuencia()
        self._hilo_plc = HiloPLC(self.reles, self.luminarias, self.compartido,
                                 self.parametros)
        self._hilo_plc.start()

    def detener_puente_plc(self, espera_s: float = 3.0) -> None:
        if self._hilo_plc is None:
            return
        self._hilo_plc.detener()
        self._hilo_plc.join(timeout=espera_s)
        self._hilo_plc = None

    def parada_emergencia(self) -> None:
        """Corta bombas y luminarias y las deja en estado seguro.

        Las luminarias se apagan tambien: consumen poco (son LED), pero una
        parada de emergencia debe dejar el cuadrante entero en reposo.

        Los semaforos y las tiras siguen corriendo: consumen unos pocos mA y
        sirven para ver de un vistazo que el software no se colgo.
        """
        log.warning("PARADA DE EMERGENCIA solicitada.")
        self.compartido.registrar("PARADA DE EMERGENCIA")
        self.detener_secuencia()
        self.reles.apagar_todos()
        self.luminarias.apagar_todos()
        self.compartido.set_reles(self.reles.estado())
        self.compartido.set_luminarias(self.luminarias.estado())

    # ------------------------------------------------------------------ cierre
    def cerrar(self) -> None:
        """Apaga todo y libera el GPIO. Es seguro llamarlo mas de una vez.

        El orden es deliberado: primero se paran los hilos, para que nadie
        vuelva a encender algo despues de apagarlo; recien entonces se apagan
        las salidas y se sueltan los recursos.

        Cada paso va en su propio try/except porque un fallo tardio (una tira
        que no responde, por ejemplo) no debe impedir que se apaguen las
        bombas, que es lo unico que mueve potencia de verdad.

        LA SEGUNDA LLAMADA TIENE QUE SER UN NO-OP, NO UN INTENTO MAS
            Lo llaman el closeEvent de la ventana y el finally de main.py, en
            ese orden. Sin la bandera, la segunda pasada encuentra el GPIO ya
            liberado por cleanup() y RPi.GPIO lanza "Please set pin numbering
            mode".
        """
        if self._cerrado:
            return
        self._cerrado = True
        log.info("Cerrando el controlador...")

        # 1. Parar los hilos.
        self.detener_secuencia()
        self.detener_puente_plc()
        for atributo in ("_hilo_semaforos", "_hilo_sensores", "_hilo_tiras"):
            hilo = getattr(self, atributo)
            if hilo is not None:
                hilo.detener()
                hilo.join(timeout=2.0)
                setattr(self, atributo, None)

        # 2. Estado seguro. Lo mas importante de todo el metodo.
        try:
            self.reles.apagar_todos()
            self.luminarias.apagar_todos()
            self.semaforos.apagar_todos()
        except Exception:
            log.exception("Fallo al apagar las salidas durante el cierre.")

        # 3. Soltar buses y buffers (I2C, DMA de las tiras).
        for recurso in (self.sensores, self.tiras):
            try:
                recurso.cerrar()
            except Exception:
                pass

        # 4. Liberar el GPIO. Sin esto, RPi.GPIO avisa de pines "en uso" en la
        #    proxima ejecucion.
        try:
            self.gpio.cleanup()
        except Exception:
            pass
        log.info("Salidas apagadas y GPIO liberado.")
