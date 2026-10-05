"""
Actuadores del cuadrante 3: bancos de reles (bombas, luminarias) y semaforos.

QUE HACE ESTE ARCHIVO
    Traduce ordenes en lenguaje humano ("enciende la bomba P1", "pon el
    semaforo TL1 en verde") a niveles logicos en los pines del conector GPIO.
    Es la capa mas baja del proyecto despues del HAL.

    BancoReles es generico: se instancia una vez con config.RELES (las cuatro
    bombas, que mueve la secuencia) y otra con config.LUMINARIAS (las luces
    exteriores, que enciende el operador a mano).

DONDE ENCAJA
    hal.crear_gpio()  ->  objeto GPIO (real o simulado)
                              |
                              v
                      BancoReles / BancoSemaforos     <-- ESTE ARCHIVO
                              |
                              v
                  secuencia.py (los hilos que deciden que encender)

    Como reciben el objeto GPIO ya construido, estas clases funcionan igual
    contra la Raspberry Pi que contra el simulador del PC. No importan
    RPi.GPIO ni saben si existe.

LA IDEA CENTRAL: "ACTIVO EN BAJO"
    Los modulos de rele de la maqueta son optoacoplados y se activan cuando el
    GPIO baja a 0 V, al reves de lo que uno esperaria. Los semaforos pueden
    estar cableados de una forma o de la otra segun como se conecte el comun.

    En vez de repartir esa inversion por todo el codigo, cada clase calcula UNA
    VEZ en el constructor que nivel significa "encendido" y cual "apagado", y
    de ahi en adelante el resto del programa solo habla de encender y apagar.
    Cambiar la polaridad es tocar una constante en config.py.
"""

from __future__ import annotations

import logging
import threading
import time

import config

log = logging.getLogger(__name__)


class BancoReles:
    """Un grupo de salidas de rele. Cada salida puede ocupar uno o mas canales.

    Se usa dos veces con la misma clase y distinta configuracion:

        BancoReles(gpio, config.RELES)       las cuatro bombas de 12 V
        BancoReles(gpio, config.LUMINARIAS)  los LED de las luminarias

    LO IMPORTANTE: CADA SALIDA ES UNA LISTA DE PINES
        Una bomba ocupa los DOS canales de su bornera, uno para el polo de
        +12 V y otro para el retorno, y es lo que la deja completamente aislada
        cuando esta apagada. Una luminaria ocupa un solo pin.

        La clase no distingue los dos casos: recibe cfg["pines"] como lista y
        la escribe entera en una sola llamada a gpio.output(). Los dos canales
        de una bomba conmutan asi de forma inseparable, que es justamente lo que
        hace falta: moverlos por separado dejaria la bomba a medio conectar, con
        un polo vivo y el otro no, y la clase directamente no ofrece forma de
        hacerlo.

    La clase tampoco sabe nada de bombas ni de luces: solo enciende y apaga los
    canales que le pasaron. Quien decide cuando hacerlo es secuencia.py, en el
    caso de las bombas, o directamente el operador, en el de las luminarias.
    """

    def __init__(self, gpio, salidas: dict | None = None,
                 nombre_banco: str = "reles",
                 activo_en_bajo: bool | None = None) -> None:
        self._gpio = gpio
        # Copia propia: si alguien modificara el diccionario de config despues,
        # este banco seguiria manejando los pines con los que se construyo.
        self._salidas = dict(salidas if salidas is not None else config.RELES)
        self._nombre_banco = nombre_banco
        # Protege el diccionario de estado y las escrituras al GPIO. Varios
        # hilos (secuencia, interfaz) pueden pedir cambios a la vez.
        self._lock = threading.Lock()
        self._encendido: dict[str, bool] = {n: False for n in self._salidas}

        # Aqui se resuelve de una vez por todas la polaridad. Con relés activos
        # en bajo (lo normal en estos modulos), "apagado" es HIGH.
        # La polaridad puede venir por parametro porque no todos los bancos
        # son iguales: los modulos de rele son activos en bajo, pero las
        # luminarias son LED directos al GPIO y encienden en alto. Sin
        # parametro se usa la polaridad de los reles, que es el caso comun.
        if activo_en_bajo is None:
            activo_en_bajo = config.RELE_ACTIVO_EN_BAJO
        self._nivel_apagado = gpio.HIGH if activo_en_bajo else gpio.LOW
        self._nivel_encendido = gpio.LOW if activo_en_bajo else gpio.HIGH

        gpio.setmode(gpio.BCM)   # numeracion BCM: el numero de GPIO, no de pin
        for nombre, cfg in self._salidas.items():
            # initial= es la parte importante: fija el nivel seguro en el mismo
            # momento en que el pin pasa a ser salida. Si se hiciera despues,
            # con un output() aparte, quedaria una ventana de microsegundos con
            # el pin en un estado indefinido y la carga podria dar un tiron.
            gpio.setup(list(cfg["pines"]), gpio.OUT, initial=self._nivel_apagado)
            log.debug("Rele %s en GPIO%s (canales %s), apagado.",
                      nombre, cfg["pines"], cfg.get("canales", "-"))
        log.info("Banco '%s' inicializado: %d salidas, todas apagadas.",
                 nombre_banco, len(self._salidas))

    # ------------------------------------------------------------------ orden
    def encender(self, nombre: str) -> None:
        """Cierra todos los contactos de esa salida."""
        self._aplicar(nombre, True)

    def apagar(self, nombre: str) -> None:
        """Abre todos los contactos de esa salida."""
        self._aplicar(nombre, False)

    def set(self, nombre: str, encendido: bool) -> None:
        """Deja la salida en el estado pedido, sin importar como estaba."""
        self._aplicar(nombre, bool(encendido))

    def alternar(self, nombre: str) -> bool:
        """Invierte el estado de una salida y devuelve como quedo.

        La lectura se hace bajo el lock y se suelta antes de escribir, porque
        _aplicar() lo vuelve a tomar y threading.Lock no es reentrante. No
        importa que quede esa rendija: el unico que llama a este metodo es la
        interfaz, desde el hilo de Qt, o sea de a un clic por vez.
        """
        with self._lock:
            nuevo = not self._encendido[nombre]
        self._aplicar(nombre, nuevo)
        return nuevo

    def apagar_todos(self) -> None:
        """Estado seguro. Se llama al arrancar, al cerrar y en la emergencia."""
        for nombre in self._salidas:
            self._aplicar(nombre, False)

    def _aplicar(self, nombre: str, encender: bool) -> None:
        """Unico punto donde se escribe al GPIO de los reles."""
        cfg = self._salidas[nombre]
        nivel = self._nivel_encendido if encender else self._nivel_apagado
        with self._lock:
            # Todos los pines de la salida en la MISMA llamada: en una bomba,
            # el polo y el retorno conmutan juntos.
            self._gpio.output(list(cfg["pines"]), nivel)
            self._encendido[nombre] = encender
        log.info("Rele %s (%s) -> %s",
                 nombre, cfg["etiqueta"], "ENCENDIDO" if encender else "apagado")

    # ----------------------------------------------------------------- estado
    def estado(self) -> dict[str, bool]:
        """Copia del estado actual, del tipo {"P1": True, "P2": False, ...}.

        Devuelve una copia y no el diccionario interno para que quien la reciba
        no pueda modificarlo por accidente desde otro hilo.
        """
        with self._lock:
            return dict(self._encendido)

    def cantidad_encendidos(self) -> int:
        return sum(self.estado().values())


class BancoSemaforos:
    """Los dos semaforos de tres luces (TL1 en J2 y TL2 en J1).

    Cada semaforo se maneja POR COLOR, no por luz: pedir verde apaga
    automaticamente el rojo y el amarillo, que es como funciona un semaforo de
    verdad. Asi es imposible dejar dos luces encendidas por un descuido.

    color(nombre, None) apaga las tres.
    """

    COLORES = ("rojo", "amarillo", "verde")

    def __init__(self, gpio) -> None:
        self._gpio = gpio
        self._lock = threading.Lock()
        # Color actual de cada semaforo, o None si esta apagado.
        self._color: dict[str, str | None] = {n: None for n in config.SEMAFOROS}

        # Misma resolucion de polaridad que en los reles. Ojo: la de los
        # semaforos depende de como este cableado el comun (anodo o catodo) y
        # hay que confirmarla en la maqueta; ver el README.
        self._nivel_apagado = gpio.HIGH if config.SEMAFORO_ACTIVO_EN_BAJO else gpio.LOW
        self._nivel_encendido = gpio.LOW if config.SEMAFORO_ACTIVO_EN_BAJO else gpio.HIGH

        gpio.setmode(gpio.BCM)
        for nombre, cfg in config.SEMAFOROS.items():
            pines = [cfg[c] for c in self.COLORES]
            gpio.setup(pines, gpio.OUT, initial=self._nivel_apagado)
            log.debug("Semaforo %s en GPIO%s, apagado.", nombre, pines)
        log.info("Semaforos inicializados: %d unidades, apagadas. "
                 "Logica activa en %s.",
                 len(config.SEMAFOROS),
                 "BAJO" if config.SEMAFORO_ACTIVO_EN_BAJO else "ALTO")

    def color(self, semaforo: str, color: str | None) -> None:
        """Enciende un solo color del semaforo indicado (o lo apaga con None).

        Es idempotente: si el semaforo ya esta en ese color no escribe nada al
        GPIO. Importa porque el hilo de semaforos llama a este metodo diez
        veces por segundo, y sin ese corte estaria reescribiendo los mismos
        pines todo el tiempo y llenando el log de ruido.
        """
        if color is not None and color not in self.COLORES:
            raise ValueError(f"Color desconocido: {color!r}")
        cfg = config.SEMAFOROS[semaforo]
        with self._lock:
            if self._color[semaforo] == color:
                return                      # ya esta asi, no hay nada que hacer
            for c in self.COLORES:
                # Enciende el pedido y apaga los otros dos, en la misma pasada.
                nivel = self._nivel_encendido if c == color else self._nivel_apagado
                self._gpio.output(cfg[c], nivel)
            self._color[semaforo] = color
        log.info("Semaforo %s -> %s", semaforo, color or "apagado")

    def apagar_todos(self) -> None:
        for nombre in config.SEMAFOROS:
            self.color(nombre, None)

    def prueba_de_luces(self, pausa_s: float = 0.4, cancelar=None) -> None:
        """Enciende las tres luces de cada semaforo, una por una.

        Es la comprobacion de cableado del arranque: si una luz no prende, el
        problema esta en la bornera o en la resistencia limitadora, no en el
        software. Tambien delata una polaridad mal configurada, porque en ese
        caso se verian dos luces encendidas y una apagada en vez de una sola.

        Se ejecuta de forma SINCRONA desde el controlador, antes de lanzar los
        hilos, para que nadie mas este tocando los semaforos mientras corre.

        cancelar: Event opcional; si se activa, la prueba se interrumpe. Sirve
                  para que cerrar la aplicacion no tenga que esperar a que
                  termine.
        """
        for color in self.COLORES:
            for nombre in config.SEMAFOROS:
                self.color(nombre, color)
            if cancelar is not None:
                # Event.wait() devuelve True si lo activaron: hay que salir.
                if cancelar.wait(pausa_s):
                    self.apagar_todos()
                    return
            else:
                time.sleep(pausa_s)
        self.apagar_todos()

    def estado(self) -> dict[str, str | None]:
        """{"TL1": "verde", "TL2": None}"""
        with self._lock:
            return dict(self._color)

    def estado_por_luz(self) -> dict[str, dict[str, bool]]:
        """Lo mismo pero como {"TL1": {"rojo": False, "verde": True, ...}}.

        Es el formato que le sirve a la interfaz, que dibuja las tres luces por
        separado y necesita saber cual encender.
        """
        actual = self.estado()
        return {
            nombre: {c: (actual[nombre] == c) for c in self.COLORES}
            for nombre in config.SEMAFOROS
        }
