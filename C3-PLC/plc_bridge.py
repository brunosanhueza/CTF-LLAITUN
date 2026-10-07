"""
Puente Modbus TCP entre esta Raspberry Pi y el PLC del Sector 3.

QUE HACE ESTE ARCHIVO
    Agrega un quinto hilo de trabajo, del mismo tipo que los cuatro de
    secuencia.py (HiloSecuencia, HiloSemaforos, HiloSensores, HiloTiras), pero
    en vez de decidir por su cuenta, obedece lo que dice el PLC:

        HiloPLC  (este archivo)
          1. Lee HR_ESTADO del PLC y traduce Comando_BombaN en el estado real
             de los reles P1-P4: el PLC manda, la Raspberry Pi ejecuta.
          2. Lee Color_LED_Flag4 y, si es distinto de cero, enciende las
             luminarias de "fiesta" - el efecto fisico de la Flag 4.
          3. Escribe en Escalamiento_Sensores la distancia RAW en mm que
             acaban de medir los cuatro VL53L0X, para que el PLC calcule su
             propio porcentaje y sus propias alarmas (FB3 "ScaleSensores").
          4. Escribe un contador creciente en Watchdog_Comms: es la unica
             forma que tiene el PLC de saber que este puente sigue vivo, en
             vez de ver los registros "congelados" en el ultimo valor bueno.

POR QUE NO DECIDE NADA POR SU CUENTA
    Toda la logica de seguridad del CTF (interlocks, override, las 4 flags)
    tiene que vivir DENTRO del PLC. Si esta Raspberry Pi tambien tuviera
    reglas propias sobre cuando encender una bomba, un participante podria
    ganar atacando el software de aqui en vez del PLC, y el reto dejaria de
    ser lo que se diseno. Por eso este archivo es deliberadamente "tonto":
    lee lo que el PLC dice y lo ejecuta, punto.

QUE PASA SI EL PLC NO RESPONDE
    No se apaga NI se enciende nada a ciegas en la primera falla: se reintenta
    cada config.PLC_PERIODO_RECONEXION_S. Si config.PLC_MODO_FALLO es
    "apagar" (lo recomendado), recien despues de confirmar la caida se
    fuerzan las cuatro bombas a un estado seguro, igual que hace
    Controlador.parada_emergencia(). Con "mantener" no se tocan: sirve para
    pruebas puntuales de banco, no para la maqueta en competencia.

DE DONDE SALEN LAS LECTURAS DE SENSOR
    Este hilo NO vuelve a leer los VL53L0X por su cuenta: toma la ULTIMA
    lectura que ya publico HiloSensores en EstadoCompartido. Son fuentes
    independientes (Modbus y I2C corren a ritmos distintos) y asi se evita
    que dos hilos se turnen el mismo bus I2C.
"""

from __future__ import annotations

import logging
import threading
import time

import config
from actuadores import BancoReles
from estado import EstadoCompartido

log = logging.getLogger(__name__)

try:
    from pyModbusTCP.client import ModbusClient
except ImportError:  # pragma: no cover - se avisa en tiempo de ejecucion
    ModbusClient = None


# =============================================================================
#  Cliente Modbus - envoltorio delgado, sin decisiones propias
# =============================================================================

class ClientePLC:
    """Envoltorio sobre pyModbusTCP con reconexion automatica.

    No lanza excepciones hacia afuera: toda falla de red se traduce en
    devolver None (lectura) o False (escritura), y quien llama decide que
    hacer. Es la misma filosofia que hal.py ya usa para el hardware local: un
    fallo de comunicacion no debe tumbar el programa, solo dejar constancia.
    """

    def __init__(self, ip: str, puerto: int, timeout_s: float) -> None:
        if ModbusClient is None:
            raise RuntimeError(
                "pyModbusTCP no esta instalado. Agregalo con: "
                "pip install pyModbusTCP"
            )
        self._cliente = ModbusClient(
            host=ip, port=puerto, timeout=timeout_s,
            auto_open=True, auto_close=False,
        )
        self._conectado = False

    @property
    def conectado(self) -> bool:
        return self._conectado

    def _marcar(self, ok: bool) -> None:
        self._conectado = ok

    def leer(self, direccion: int, cantidad: int = 1) -> list[int] | None:
        valores = self._cliente.read_holding_registers(direccion, cantidad)
        self._marcar(valores is not None)
        return valores

    def escribir(self, direccion: int, valor: int) -> bool:
        ok = self._cliente.write_single_register(direccion, int(valor) & 0xFFFF)
        self._marcar(bool(ok))
        return bool(ok)

    def cerrar(self) -> None:
        try:
            self._cliente.close()
        except Exception:
            pass


def _bit_activo(valor: int, bit: int) -> bool:
    """Extrae un bit de un Word Modbus (0 = bit menos significativo)."""
    return bool((valor >> bit) & 1)


# =============================================================================
#  El hilo
# =============================================================================

class HiloPLC(threading.Thread):
    """Ciclo de lectura/escritura contra los holding registers del PLC.

    Igual que los otros hilos de secuencia.py: Event.wait() en vez de
    time.sleep() para que detener() corte al instante, y un finally que deja
    el hardware en estado seguro pase lo que pase.
    """

    def __init__(self, reles: BancoReles, luminarias: BancoReles,
                 compartido: EstadoCompartido, parametros=None) -> None:
        super().__init__(name="puente-plc", daemon=True)
        self._reles = reles
        self._luminarias = luminarias
        self._estado = compartido
        # Parametros se usa solo para pintar las tiras (Flag 4). Con None el
        # puente sigue funcionando y simplemente no toca las tiras.
        self._param = parametros
        # Estado por tira: ultimo valor de color visto en su registro y el color
        # local que tenia antes de que el PLC le diera una orden.
        self._color_visto: dict[str, int | None] = {t: None for t in config.TIRAS}
        self._colores_previos: dict[str, tuple] = {}
        self._parar = threading.Event()
        self._cliente: ClientePLC | None = None
        self._contador_watchdog = 0

        # Mapa canal-de-sensor -> nombre de rele, para no recorrer
        # config.SENSORES en cada vuelta.
        self._rele_por_canal = {s["canal"]: s["rele"] for s in config.SENSORES}

        # Se recuerda el ultimo estado de fallo aplicado para no registrar
        # "PLC caido" en el log cincuenta veces por segundo mientras dura la
        # caida - solo en la transicion.
        self._estaba_conectado: bool | None = None

    def detener(self) -> None:
        self._parar.set()

    # --------------------------------------------------------------- ciclo
    def _conectar(self) -> bool:
        if self._cliente is None:
            try:
                self._cliente = ClientePLC(
                    config.PLC_IP, config.PLC_PUERTO, config.PLC_TIMEOUT_S,
                )
            except RuntimeError as exc:
                self._estado.registrar(f"Puente PLC: {exc}")
                return False
        return True

    def _avisar_transicion(self, conectado: bool) -> None:
        if conectado == self._estaba_conectado:
            return
        self._estaba_conectado = conectado
        if conectado:
            self._estado.registrar(
                f"Puente PLC: conectado a {config.PLC_IP}:{config.PLC_PUERTO}"
            )
        else:
            self._estado.registrar(
                f"Puente PLC: SIN RESPUESTA de {config.PLC_IP} "
                f"({config.PLC_MODO_FALLO})"
            )
            if config.PLC_MODO_FALLO == "apagar":
                self._reles.apagar_todos()
                self._estado.set_reles(self._reles.estado())

    # ------------------------------------------------------- pasos del ciclo
    def _aplicar_comandos_bomba(self, valor_hr_estado: int) -> None:
        """Traduce HR_ESTADO en el estado real de los cuatro reles."""
        cambios = []
        for nombre, bit in config.PLC_BIT_COMANDO_BOMBA.items():
            encender = _bit_activo(valor_hr_estado, bit)
            if self._reles.estado().get(nombre) != encender:
                cambios.append((nombre, encender))
        for nombre, encender in cambios:
            self._reles.set(nombre, encender)
        if cambios:
            self._estado.set_reles(self._reles.estado())
            for nombre, encendido in cambios:
                self._estado.registrar(
                    f"{nombre}: comando del PLC -> "
                    f"{'ENCENDIDA' if encendido else 'apagada'}"
                )

    def _aplicar_color_flag4(self, valor_color: int) -> None:
        """Efecto fisico de la Flag 4: enciende las luminarias de fiesta."""
        encender = valor_color != 0
        for nombre in config.PLC_LUMINARIAS_FIESTA:
            if self._luminarias.estado().get(nombre) != encender:
                self._luminarias.set(nombre, encender)
        self._estado.set_luminarias(self._luminarias.estado())
        self._aplicar_color_tiras(config.PLC_HR_COLOR_LED_FLAG4, valor_color)

    def _aplicar_color_tiras(self, registro: int, valor_color: int) -> None:
        """Pinta las tiras que leen de ese registro (config.PLC_HR_COLOR_TIRAS).

        Cada tira se maneja POR SEPARADO: tiene su propio ultimo valor visto y
        su propio color local guardado, aunque dos tiras compartan registro.

        Solo actua cuando el valor CAMBIA, no en cada vuelta del ciclo: asi el
        operador puede cambiar el color desde el dashboard sin que el puente se
        lo pise cada 0.3 s, y el log no se llena de lineas repetidas.

        Valor 0 = el PLC suelta la tira y vuelve el color que tenia antes de la
        primera orden. HiloTiras relee el color en cada paso, asi que el cambio
        se ve de inmediato, incluso con la animacion corriendo.
        """
        if self._param is None:
            return
        for tira, hr in config.PLC_HR_COLOR_TIRAS.items():
            if hr != registro or valor_color == self._color_visto.get(tira):
                continue
            self._color_visto[tira] = valor_color
            zona = config.TIRAS[tira]["etiqueta"]

            if valor_color == 0:
                previo = self._colores_previos.pop(tira, None)
                if previo is not None:
                    self._param.set_color(tira, *previo)
                    self._estado.registrar(
                        f"{zona}: color del PLC liberado, vuelve al color local"
                    )
                continue

            nombre = config.PLC_COLOR_TIRAS.get(valor_color)
            rgb = dict(config.TIRA_COLORES).get(nombre) if nombre else None
            if rgb is None:
                self._estado.registrar(
                    f"{zona}: HR{registro} = {valor_color}, sin color "
                    f"asignado, no cambia"
                )
                continue

            if tira not in self._colores_previos:
                self._colores_previos[tira] = (
                    self._param.color_nombre(tira), self._param.color(tira),
                )
            self._param.set_color(tira, nombre, rgb)
            self._estado.registrar(
                f"{zona}: HR{registro} = {valor_color} -> {nombre}"
            )

    def _leer_colores_zonas(self, cliente: ClientePLC) -> None:
        """Lee los registros de color propios de cada zona (distintos del HR10).

        Mientras todas las tiras apunten al HR10 no hay nada que leer aqui.
        """
        extras = (set(config.PLC_HR_COLOR_TIRAS.values())
                  - {config.PLC_HR_COLOR_LED_FLAG4})
        for registro in sorted(extras):
            valor = cliente.leer(registro, 1)
            if valor is not None:
                self._aplicar_color_tiras(registro, valor[0])

    def _publicar_niveles_raw(self, cliente: ClientePLC) -> bool:
        """Escribe en Escalamiento_Sensores el RAW (mm) y el % de cada tanque.

        El % usado es lectura.nivel_pct, ya calculado por hal.py con la
        geometria real de config.GEOMETRIA_ESTANQUES (la misma que usa la
        interfaz local), en vez de dejar que lo calcule solo el PLC en FB3
        "ScaleSensores". Si FB3 sigue recalculando ese registro cada ciclo,
        este valor se pisa casi de inmediato; confirmar en TIA que no compita
        con esta escritura.

        Solo se envian los tanques con sensor conectado: un tanque sin sensor
        no debe pisar el registro del PLC con un cero que se leeria como
        "estanque vacio" cuando en realidad no hay dato.
        """
        lecturas = self._estado.lecturas()
        ok_total = True
        for lectura in lecturas:
            nombre_rele = self._rele_por_canal.get(lectura.canal)
            if nombre_rele is None or not lectura.ok:
                continue
            indice_raw = config.PLC_INDICE_RAW.get(nombre_rele)
            indice_pct = config.PLC_INDICE_PCT.get(nombre_rele)
            if indice_raw is None or indice_pct is None:
                continue
            pct = round(lectura.nivel_pct or 0.0)
            if not cliente.escribir(config.PLC_HR_ESCALAMIENTO + indice_raw,
                                    lectura.distancia_mm):
                ok_total = False
            if not cliente.escribir(config.PLC_HR_ESCALAMIENTO + indice_pct,
                                    pct):
                ok_total = False
        return ok_total

    def _latir(self, cliente: ClientePLC) -> None:
        """Heartbeat: un contador que sube en cada vuelta exitosa.

        Al PLC le sirve para distinguir "el registro vale 0 porque de verdad
        no hay agua" de "el puente Modbus murio y el registro quedo pegado".
        Se recorta a 16 bits porque un HR de Modbus es un Word.
        """
        self._contador_watchdog = (self._contador_watchdog + 1) & 0xFFFF
        cliente.escribir(config.PLC_HR_WATCHDOG_COMMS, self._contador_watchdog)

    # ------------------------------------------------------------------ run
    def run(self) -> None:
        self._estado.registrar(
            f"Puente PLC iniciado: {config.PLC_IP}:{config.PLC_PUERTO}, "
            f"ciclo cada {config.PLC_PERIODO_S:.1f} s"
        )
        try:
            while not self._parar.is_set():
                if not self._conectar():
                    if self._parar.wait(config.PLC_PERIODO_RECONEXION_S):
                        return
                    continue

                cliente = self._cliente
                assert cliente is not None

                estado_hr = cliente.leer(config.PLC_HR_ESTADO, 1)
                color_flag4 = cliente.leer(config.PLC_HR_COLOR_LED_FLAG4, 1)
                sensores_ok = self._publicar_niveles_raw(cliente)
                self._latir(cliente)

                conectado = cliente.conectado and estado_hr is not None
                self._avisar_transicion(conectado)

                if conectado:
                    self._aplicar_comandos_bomba(estado_hr[0])
                    if color_flag4 is not None:
                        self._aplicar_color_flag4(color_flag4[0])
                    self._leer_colores_zonas(cliente)
                    if not sensores_ok:
                        cliente.escribir(config.PLC_HR_WATCHDOG_ERRCODE, 1)
                    else:
                        cliente.escribir(config.PLC_HR_WATCHDOG_ERRCODE, 0)

                periodo = (config.PLC_PERIODO_S if conectado
                           else config.PLC_PERIODO_RECONEXION_S)
                if self._parar.wait(periodo):
                    return
        except Exception:
            log.exception("Error en el puente PLC.")
            self._estado.registrar("ERROR en el puente PLC, ver el log")
        finally:
            if config.PLC_MODO_FALLO == "apagar":
                try:
                    self._reles.apagar_todos()
                    self._estado.set_reles(self._reles.estado())
                except Exception:
                    log.exception("No se pudieron apagar las bombas al "
                                   "cerrar el puente PLC.")
            if self._cliente is not None:
                self._cliente.cerrar()
