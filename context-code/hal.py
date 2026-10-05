"""
Capa de abstraccion de hardware (HAL) del cuadrante 3.

Permite ejecutar exactamente el mismo codigo en dos escenarios:

  * En la Raspberry Pi, contra el hardware real (RPi.GPIO + Adafruit Blinka).
  * En un PC de escritorio, contra un simulador, para desarrollar y probar la
    interfaz sin la maqueta al lado.

La eleccion es automatica: si las bibliotecas de la Raspberry Pi no estan
disponibles se cae al simulador y se avisa por log. Se puede forzar el
simulador con el argumento --simular de main.py.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import config

log = logging.getLogger(__name__)


# =============================================================================
#  GPIO
# =============================================================================

class GPIOSimulado:
    """Reimplementacion minima de la API de RPi.GPIO que usa este proyecto.

    Solo guarda el estado de cada pin en memoria. Los modulos de actuadores no
    notan la diferencia porque usan unicamente setmode/setup/output/cleanup.
    """

    BCM = "BCM"
    BOARD = "BOARD"
    OUT = "OUT"
    IN = "IN"
    HIGH = 1
    LOW = 0
    PUD_UP = "PUD_UP"
    PUD_DOWN = "PUD_DOWN"

    def __init__(self) -> None:
        self._pines: dict[int, int] = {}
        self._lock = threading.Lock()

    def setmode(self, modo) -> None:
        log.debug("GPIO simulado: setmode(%s)", modo)

    def setwarnings(self, activar) -> None:
        pass

    def setup(self, pines, direccion, initial=None, pull_up_down=None) -> None:
        if isinstance(pines, int):
            pines = [pines]
        valor = self.HIGH if initial is None else initial
        with self._lock:
            for pin in pines:
                self._pines[pin] = valor

    def output(self, pines, valor) -> None:
        if isinstance(pines, int):
            pines = [pines]
        with self._lock:
            for pin in pines:
                self._pines[pin] = valor

    def input(self, pin) -> int:
        with self._lock:
            return self._pines.get(pin, self.HIGH)

    def cleanup(self, pines=None) -> None:
        with self._lock:
            self._pines.clear()


def crear_gpio(forzar_simulacion: bool = False):
    """Devuelve (objeto_gpio, es_hardware_real)."""
    if not forzar_simulacion:
        try:
            import RPi.GPIO as GPIO  # type: ignore
            GPIO.setwarnings(False)
            log.info("GPIO real detectado (RPi.GPIO).")
            return GPIO, True
        except Exception as exc:  # ImportError en PC, RuntimeError fuera de RPi
            log.warning("RPi.GPIO no disponible (%s). Se usa GPIO simulado.", exc)
    else:
        log.info("Simulacion forzada por linea de comandos.")
    return GPIOSimulado(), False


# =============================================================================
#  SENSORES VL53L0X
# =============================================================================

ESTADO_OK = "ok"
ESTADO_DESCONECTADO = "desconectado"
ESTADO_ERROR = "error"


@dataclass
class Lectura:
    """Una medicion de un sensor de nivel.

    `estado` distingue tres situaciones que la interfaz muestra distinto:
      ok            - el sensor respondio y la distancia es valida
      desconectado  - no hay ningun VL53L0X en ese canal del multiplexor
      error         - el sensor esta presente pero la lectura fallo
    """

    canal: int
    bornera: str
    etiqueta: str
    estado: str = ESTADO_DESCONECTADO
    distancia_mm: int | None = None
    nivel_pct: float | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.estado == ESTADO_OK

    @property
    def conectado(self) -> bool:
        return self.estado != ESTADO_DESCONECTADO

    def texto_distancia(self) -> str:
        if self.estado == ESTADO_DESCONECTADO:
            return "DESCONECTADO"
        return f"{self.distancia_mm} mm" if self.ok else "sin lectura"

    def texto_nivel(self) -> str:
        return f"{self.nivel_pct:.1f} %" if self.ok else "---"


def distancia_a_nivel_pct(distancia_mm: float) -> float:
    """Convierte la distancia sensor-agua en porcentaje de llenado (0 a 100).

    El sensor mira hacia abajo desde la tapa del estanque, de modo que mas
    distancia significa menos agua. El resultado se recorta a [0, 100] porque
    el VL53L0X puede entregar valores fuera del rango util del estanque.
    """
    vacio = config.DISTANCIA_ESTANQUE_VACIO_MM
    lleno = config.DISTANCIA_ESTANQUE_LLENO_MM
    if vacio == lleno:
        return 0.0
    pct = (vacio - distancia_mm) / (vacio - lleno) * 100.0
    return max(0.0, min(100.0, pct))


class BancoSensoresVL53L0X:
    """Los cuatro VL53L0X, cada uno en su canal del TCA9548A.

    Los cuatro comparten la direccion 0x29. La biblioteca adafruit_tca9548a
    entrega un objeto de bus por canal (tca[0] .. tca[7]) que abre el canal
    correspondiente antes de cada transaccion y lo cierra despues, de modo que
    en el bus nunca hay dos 0x29 visibles a la vez.

    La deteccion es REAL: antes de crear el objeto del sensor se escanea el
    canal buscando la direccion 0x29. Si no esta, el canal queda marcado como
    DESCONECTADO y se reintenta cada PERIODO_REDETECCION_S, de modo que se
    puede enchufar un sensor con el software ya corriendo.
    """

    def __init__(self, gpio) -> None:
        import board  # type: ignore
        import busio  # type: ignore
        import adafruit_tca9548a  # type: ignore
        from adafruit_vl53l0x import VL53L0X  # type: ignore

        self._VL53L0X = VL53L0X
        self._gpio = gpio
        self.resetear_mux()

        self._i2c = busio.I2C(board.SCL, board.SDA)
        self._mux = adafruit_tca9548a.TCA9548A(
            self._i2c, address=config.MUX_DIRECCION
        )

        self._sensores: dict[int, object] = {}
        self._fallos: dict[int, int] = {}
        self._ultima_deteccion = 0.0
        # Cola de mensajes para la interfaz. El log de Python va al terminal, y
        # si la aplicacion se lanza desde el escritorio nadie lo ve nunca.
        self._diagnosticos: list[str] = []
        self._primera_deteccion = True
        self._detectar()

    def _diag(self, mensaje: str, *args) -> None:
        texto = mensaje % args if args else mensaje
        log.info(texto)
        self._diagnosticos.append(texto)

    def diagnosticos(self) -> list[str]:
        """Devuelve los mensajes pendientes y vacia la cola."""
        pendientes, self._diagnosticos = self._diagnosticos, []
        return pendientes

    # ------------------------------------------------------------- deteccion
    def _hay_sensor_en(self, canal: int) -> bool | None:
        """Escanea ese canal del mux buscando la direccion del VL53L0X.

        Devuelve True/False si el escaneo funciono, y None si el escaneo mismo
        no se pudo hacer. Ese tercer caso importa: antes se devolvia False y el
        canal quedaba como DESCONECTADO aunque el sensor estuviera ahi, sin
        dejar rastro de por que.
        """
        bus = self._mux[canal]
        try:
            if not bus.try_lock():
                self._diag("Canal %d: no se pudo tomar el bus I2C.", canal)
                return None
        except Exception as exc:
            self._diag("Canal %d: fallo try_lock (%s: %s).",
                       canal, type(exc).__name__, exc)
            return None
        try:
            try:
                direcciones = bus.scan()
            except AttributeError:
                # Versiones antiguas de adafruit_tca9548a no exponen scan() en
                # el canal. El bus ya quedo conmutado por try_lock(), asi que
                # el escaneo del bus padre sirve igual.
                direcciones = self._i2c.scan()
            if self._primera_deteccion:
                otros = [d for d in direcciones if d != config.MUX_DIRECCION]
                self._diag("Canal %d: %s", canal,
                           ", ".join(f"0x{d:02X}" for d in otros) or "vacio")
            return config.VL53L0X_DIRECCION in direcciones
        except Exception as exc:
            self._diag("Canal %d: fallo el escaneo (%s: %s).",
                       canal, type(exc).__name__, exc)
            return None
        finally:
            try:
                bus.unlock()
            except Exception:
                pass

    def _detectar(self) -> None:
        """Intenta inicializar los canales que todavia no tienen sensor vivo."""
        self._ultima_deteccion = time.monotonic()
        for cfg in config.SENSORES:
            canal = cfg["canal"]
            if canal in self._sensores:
                continue

            presente = self._hay_sensor_en(canal)
            if presente is False:
                continue        # el canal esta vacio de verdad
            # Con presente None el escaneo no sirvio: se intenta construir el
            # sensor igual, que es la prueba definitiva de si esta o no.

            try:
                self._sensores[canal] = self._VL53L0X(self._mux[canal])
                self._fallos[canal] = 0
                self._diag("VL53L0X abierto en canal %d (%s, %s).",
                           canal, cfg["bornera"], cfg["etiqueta"])
            except Exception as exc:
                if presente or self._primera_deteccion:
                    self._diag("Canal %d (%s): no se pudo abrir el VL53L0X "
                               "(%s: %s).", canal, cfg["bornera"],
                               type(exc).__name__, exc)
                else:
                    log.debug("Canal %d vacio: %s", canal, exc)

        if self._primera_deteccion:
            self._diag("Sensores detectados: %d de %d.",
                       len(self._sensores), len(config.SENSORES))
            self._primera_deteccion = False

    def resetear_mux(self) -> None:
        """Pulso en la linea RST del TCA9548A.

        Sirve para recuperar el bus si un sensor dejo colgada la linea SDA,
        sin necesidad de reiniciar la Raspberry Pi.
        """
        pin = config.MUX_RESET_GPIO
        self._gpio.setup(pin, self._gpio.OUT, initial=self._gpio.HIGH)
        self._gpio.output(pin, self._gpio.LOW)
        time.sleep(0.01)
        self._gpio.output(pin, self._gpio.HIGH)
        time.sleep(0.05)

    # ---------------------------------------------------------------- lectura
    def leer_todos(self) -> list[Lectura]:
        if (time.monotonic() - self._ultima_deteccion
                >= config.PERIODO_REDETECCION_S):
            self._detectar()

        lecturas: list[Lectura] = []
        for cfg in config.SENSORES:
            canal = cfg["canal"]
            base = dict(canal=canal, bornera=cfg["bornera"],
                        etiqueta=cfg["etiqueta"])
            sensor = self._sensores.get(canal)

            if sensor is None:
                lecturas.append(Lectura(**base, estado=ESTADO_DESCONECTADO))
                continue

            try:
                distancia = int(sensor.range)  # type: ignore[attr-defined]
                self._fallos[canal] = 0
                lecturas.append(Lectura(
                    **base, estado=ESTADO_OK, distancia_mm=distancia,
                    nivel_pct=distancia_a_nivel_pct(distancia),
                ))
            except Exception as exc:
                # Varios fallos seguidos = lo desenchufaron. Se suelta el objeto
                # para que la redeteccion lo recupere si lo vuelven a conectar.
                self._fallos[canal] = self._fallos.get(canal, 0) + 1
                if self._fallos[canal] >= config.FALLOS_PARA_DESCONECTAR:
                    self._sensores.pop(canal, None)
                    log.warning("Canal %d (%s) dado por desconectado tras %d "
                                "lecturas fallidas.", canal, cfg["bornera"],
                                self._fallos[canal])
                    lecturas.append(Lectura(**base, estado=ESTADO_DESCONECTADO))
                else:
                    lecturas.append(Lectura(**base, estado=ESTADO_ERROR,
                                            error=str(exc)))
        return lecturas

    def cerrar(self) -> None:
        try:
            self._i2c.deinit()
        except Exception:
            pass


class BancoSensoresSimulado:
    """Simulador con un modelo hidraulico muy simple.

    Cada estanque sube de nivel mientras su bomba esta encendida y baja
    lentamente cuando esta apagada, para poder probar la interfaz sin maqueta.

    Solo simula los canales de config.SIMULAR_CANALES_CONECTADOS; el resto se
    reporta como DESCONECTADO, igual que lo haria el hardware real.
    """

    TASA_LLENADO_PCT_S = 1.6
    TASA_VACIADO_PCT_S = 0.5
    RUIDO_MM = 3

    def __init__(self, estado_reles: Callable[[], dict[str, bool]],
                 canales_conectados=None, motivo: str = "") -> None:
        self._estado_reles = estado_reles
        if canales_conectados is None:
            canales_conectados = config.SIMULAR_CANALES_CONECTADOS
        self._conectados = set(canales_conectados)
        # Si el banco real no pudo abrirse, aqui queda el motivo para que la
        # interfaz lo muestre en vez de limitarse a decir DESCONECTADO.
        self._diagnosticos = [motivo] if motivo else []
        self._nivel = {cfg["canal"]: random.uniform(20.0, 45.0)
                       for cfg in config.SENSORES}
        self._t_anterior = time.monotonic()
        self._lock = threading.Lock()
        log.info("Sensores simulados: %d de %d canales conectados.",
                 len(self._conectados), len(config.SENSORES))

    def diagnosticos(self) -> list[str]:
        pendientes, self._diagnosticos = self._diagnosticos, []
        return pendientes

    def resetear_mux(self) -> None:
        log.debug("Reset de mux simulado.")

    def _avanzar_modelo(self) -> None:
        ahora = time.monotonic()
        dt = ahora - self._t_anterior
        self._t_anterior = ahora
        reles = self._estado_reles()
        for cfg in config.SENSORES:
            canal = cfg["canal"]
            encendida = reles.get(cfg["rele"], False)
            tasa = self.TASA_LLENADO_PCT_S if encendida else -self.TASA_VACIADO_PCT_S
            nivel = self._nivel[canal] + tasa * dt
            self._nivel[canal] = max(0.0, min(100.0, nivel))

    def leer_todos(self) -> list[Lectura]:
        with self._lock:
            self._avanzar_modelo()
            niveles = dict(self._nivel)

        vacio = config.DISTANCIA_ESTANQUE_VACIO_MM
        lleno = config.DISTANCIA_ESTANQUE_LLENO_MM
        lecturas: list[Lectura] = []
        for cfg in config.SENSORES:
            canal = cfg["canal"]
            base = dict(canal=canal, bornera=cfg["bornera"],
                        etiqueta=cfg["etiqueta"])
            if canal not in self._conectados:
                lecturas.append(Lectura(**base, estado=ESTADO_DESCONECTADO))
                continue
            distancia = vacio - niveles[canal] / 100.0 * (vacio - lleno)
            distancia += random.uniform(-self.RUIDO_MM, self.RUIDO_MM)
            distancia = int(max(0, distancia))
            lecturas.append(Lectura(
                **base, estado=ESTADO_OK, distancia_mm=distancia,
                nivel_pct=distancia_a_nivel_pct(distancia),
            ))
        return lecturas

    def cerrar(self) -> None:
        pass


def crear_banco_sensores(gpio, hay_hardware: bool,
                         estado_reles: Callable[[], dict[str, bool]],
                         canales_simulados=None):
    """Devuelve el banco de sensores adecuado al entorno.

    En hardware real NUNCA se cae al simulador: si el bus I2C no abre, se
    devuelve un banco que reporta todos los canales como DESCONECTADO. Mostrar
    distancias inventadas en la maqueta seria peor que no mostrar nada.
    """
    if hay_hardware:
        try:
            return BancoSensoresVL53L0X(gpio)
        except Exception as exc:
            motivo = (f"No se pudo abrir el bus I2C ni el multiplexor "
                      f"({type(exc).__name__}: {exc}). Revisar dtparam=i2c_arm=on "
                      f"y que 'i2cdetect -y 1' muestre "
                      f"0x{config.MUX_DIRECCION:02X}.")
            log.error("%s Los sensores se reportaran como DESCONECTADOS.", motivo)
            return BancoSensoresSimulado(estado_reles, canales_conectados=[],
                                         motivo=motivo)
    return BancoSensoresSimulado(estado_reles, canales_conectados=canales_simulados)


# =============================================================================
#  TIRAS LED DIRECCIONABLES  (WS2812B)
# =============================================================================

class BancoTirasWS281x:
    """Las dos tiras WS2812B, en PWM0 (GPIO18) y PWM1 (GPIO13).

    IMPORTANTE - por que no se usa PixelStrip:

    Cada objeto PixelStrip crea su propia estructura ws2811_t y llama a
    ws2811_init(), que reprograma el periferico PWM completo. Con dos objetos,
    la segunda inicializacion deja sin configurar el canal de la primera y no
    prende ninguna de las dos. Cambiarles el canal DMA no lo arregla: el
    conflicto es del PWM, no del DMA.

    La forma correcta de manejar los dos canales es UNA sola ws2811_t con los
    dos canales configurados y un unico ws2811_init(), que es exactamente lo que
    hace esta clase con la API de bajo nivel (modulo `ws`). ws2811_render()
    refresca ambos canales de una vez.

    rpi_ws281x accede directo a DMA y PWM, asi que el proceso debe correr como
    root. Si no puede, crear_banco_tiras() cae a la version simulada.

    El buffer se reserva UNA VEZ con TIRA_N_LEDS_MAX y el largo que se ajusta
    desde la interfaz es una longitud LOGICA: los LED que sobran se escriben
    siempre apagados.
    """

    def __init__(self, solo: list[str] | None = None) -> None:
        from rpi_ws281x import ws  # type: ignore

        self._ws = ws
        self._leds = None
        self._canales: dict[str, object] = {}
        self._pixeles: dict[str, list[tuple[int, int, int]]] = {}
        self._n_fisico = int(config.TIRA_N_LEDS_MAX)
        self._lock = threading.Lock()
        self.errores: dict[str, str] = {}

        # El orden de bytes se declara explicitamente en vez de depender del
        # valor por omision de la biblioteca: si sale mal, el sintoma son los
        # colores cambiados y no un error, que es dificil de diagnosticar.
        tipo = getattr(ws, config.TIRA_TIPO, None)
        if tipo is None:
            log.warning("Tipo de tira '%s' desconocido; se usa WS2811_STRIP_GRB.",
                        config.TIRA_TIPO)
            tipo = ws.WS2811_STRIP_GRB

        pedidas = {n: c for n, c in config.TIRAS.items()
                   if solo is None or n in solo}

        self._leds = ws.new_ws2811_t()
        ws.ws2811_t_freq_set(self._leds, config.TIRA_FRECUENCIA_HZ)
        ws.ws2811_t_dmanum_set(self._leds, config.TIRA_DMA)

        # Los dos canales se dejan primero en cero: los que no se usen deben
        # quedar con count=0 o ws2811_init reserva memoria para nada.
        for indice in range(2):
            canal = ws.ws2811_channel_get(self._leds, indice)
            ws.ws2811_channel_t_count_set(canal, 0)
            ws.ws2811_channel_t_gpionum_set(canal, 0)
            ws.ws2811_channel_t_invert_set(canal, 0)
            ws.ws2811_channel_t_brightness_set(canal, 0)

        for nombre, cfg in pedidas.items():
            canal = ws.ws2811_channel_get(self._leds, cfg["canal_pwm"])
            ws.ws2811_channel_t_count_set(canal, self._n_fisico)
            ws.ws2811_channel_t_gpionum_set(canal, cfg["gpio"])
            ws.ws2811_channel_t_invert_set(canal, int(config.TIRA_INVERTIR))
            ws.ws2811_channel_t_brightness_set(canal, config.TIRA_BRILLO)
            ws.ws2811_channel_t_strip_type_set(canal, tipo)
            self._canales[nombre] = canal
            self._pixeles[nombre] = [(0, 0, 0)] * cfg["n_leds"]

        respuesta = ws.ws2811_init(self._leds)
        if respuesta != ws.WS2811_SUCCESS:
            motivo = ws.ws2811_get_return_t_str(respuesta)
            self._liberar()
            raise RuntimeError(f"ws2811_init fallo ({respuesta}): {motivo}")

        for nombre, cfg in pedidas.items():
            log.info("Tira %s lista: GPIO%d, PWM%d, %s, %d LED de %d reservados.",
                     nombre, cfg["gpio"], cfg["canal_pwm"], config.TIRA_TIPO,
                     cfg["n_leds"], self._n_fisico)
        log.info("ws2811 inicializado: DMA %d, %d canal(es) en una sola instancia.",
                 config.TIRA_DMA, len(self._canales))

    # ------------------------------------------------------------------ estado
    def activas(self) -> set[str]:
        """Nombres de las tiras que si quedaron funcionando."""
        return set(self._canales)

    # ----------------------------------------------------------------- escribir
    def set_pixeles(self, nombre, colores) -> None:
        """Carga los colores en el buffer del canal. No refresca todavia.

        El refresco lo hace mostrar(), porque ws2811_render() manda los dos
        canales juntos y no tiene sentido llamarlo una vez por tira.
        """
        canal = self._canales.get(nombre)
        if canal is None:
            return          # tira que no inicializo: se ignora en silencio
        colores = list(colores)
        with self._lock:
            for i in range(self._n_fisico):
                if i < len(colores):
                    r, g, b = colores[i]
                    valor = (int(r) << 16) | (int(g) << 8) | int(b)
                else:
                    valor = 0
                self._ws.ws2811_led_set(canal, i, valor)
            self._pixeles[nombre] = colores

    def mostrar(self) -> None:
        """Refresca las dos tiras de una sola pasada."""
        if self._leds is None:
            return
        with self._lock:
            respuesta = self._ws.ws2811_render(self._leds)
            if respuesta != self._ws.WS2811_SUCCESS:
                log.error("ws2811_render fallo (%s): %s", respuesta,
                          self._ws.ws2811_get_return_t_str(respuesta))

    def apagar_todas(self) -> None:
        for nombre, cfg in config.TIRAS.items():
            self.set_pixeles(nombre, [])
        self.mostrar()

    def pixeles(self) -> dict[str, list[tuple[int, int, int]]]:
        with self._lock:
            return {k: list(v) for k, v in self._pixeles.items()}

    # ------------------------------------------------------------------ cierre
    def _liberar(self) -> None:
        if self._leds is None:
            return
        try:
            self._ws.delete_ws2811_t(self._leds)
        except Exception:
            pass
        self._leds = None

    def cerrar(self) -> None:
        try:
            self.apagar_todas()
        except Exception:
            log.exception("No se pudieron apagar las tiras al cerrar.")
        if self._leds is not None:
            try:
                self._ws.ws2811_fini(self._leds)
            except Exception:
                pass
            self._liberar()


class BancoTirasSimulado:
    """Guarda el estado de los pixeles en memoria para que la interfaz lo pinte."""

    def __init__(self, errores: dict[str, str] | None = None) -> None:
        self._pixeles = {nombre: [(0, 0, 0)] * cfg["n_leds"]
                         for nombre, cfg in config.TIRAS.items()}
        self._lock = threading.Lock()
        self.errores = dict(errores or {})
        log.info("Tiras simuladas: %d.", len(self._pixeles))

    def activas(self) -> set[str]:
        return set()

    def set_pixeles(self, nombre, colores) -> None:
        with self._lock:
            self._pixeles[nombre] = list(colores)

    def mostrar(self) -> None:
        pass        # el simulador no tiene nada que refrescar

    def apagar_todas(self) -> None:
        for nombre in config.TIRAS:
            self.set_pixeles(nombre, [])

    def pixeles(self) -> dict[str, list[tuple[int, int, int]]]:
        with self._lock:
            return {k: list(v) for k, v in self._pixeles.items()}

    def cerrar(self) -> None:
        pass


def crear_banco_tiras(hay_hardware: bool):
    """Devuelve (banco_de_tiras, son_reales).

    Solo cae a simulacion si NINGUNA tira pudo abrirse. Si una si y otra no, se
    devuelve el banco real y el detalle queda en banco.errores, para que la
    interfaz pueda decir cual fallo y por que.
    """
    if not hay_hardware:
        return BancoTirasSimulado(), False

    # Se comprueba antes de intentar, porque el error que devuelve la biblioteca
    # en este caso es "-9: Failed to create mailbox device", que no dice nada
    # sobre permisos y manda a buscar el problema donde no esta.
    if hasattr(os, "geteuid") and os.geteuid() != 0:
        motivo = ("hay que ejecutar con sudo. rpi_ws281x necesita /dev/vcio y "
                  "/dev/mem, que piden root; los reles y semaforos funcionan sin "
                  "el porque RPi.GPIO usa /dev/gpiomem. Probar: "
                  "sudo -E python3 main.py")
        log.warning("Tiras simuladas: %s", motivo)
        return BancoTirasSimulado({"*": motivo}), False

    try:
        return BancoTirasWS281x(), True
    except ImportError as exc:
        motivo = (f"rpi_ws281x no esta instalado ({exc}). Instalar con: "
                  f"sudo pip3 install --break-system-packages rpi_ws281x")
        log.warning("%s Tiras simuladas.", motivo)
        return BancoTirasSimulado({"*": motivo}), False
    except PermissionError as exc:
        motivo = f"sin permisos para DMA/PWM ({exc}). Hay que ejecutar con sudo."
        log.warning("%s Tiras simuladas.", motivo)
        return BancoTirasSimulado({"*": motivo}), False
    except Exception as exc:
        motivo_ambas = str(exc)
        log.warning("No se pudieron abrir las dos tiras a la vez: %s", motivo_ambas)

    # Segundo intento con una sola tira. Si la Raspberry Pi no puede con los dos
    # canales PWM, es preferible dejar una funcionando que ninguna.
    primera = next(iter(config.TIRAS), None)
    if primera is not None:
        try:
            banco = BancoTirasWS281x(solo=[primera])
            banco.errores = {
                n: f"no se pudo usar el segundo canal PWM: {motivo_ambas}"
                for n in config.TIRAS if n != primera
            }
            log.warning("Solo la tira %s quedo activa.", primera)
            return banco, True
        except Exception as exc:
            motivo_ambas = f"{motivo_ambas}; con una sola tira: {exc}"

    log.warning("Tiras simuladas. Verificar que se ejecuta con sudo y que "
                "dtparam=audio=off esta en config.txt.")
    return BancoTirasSimulado({"*": motivo_ambas}), False
