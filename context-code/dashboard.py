"""
Dashboard PyQt5 del cuadrante 3: la ventana que ve el operador.

LA REGLA DE ORO DE ESTE ARCHIVO
    La ventana NO habla con el hardware. Nunca. Solo hace dos cosas:

        LEER   ->  controlador.compartido.instantanea(), 5 veces por segundo
        PEDIR  ->  controlador.alternar_bomba(), .set_sostenido_s(), etc.

    No importa ni RPi.GPIO ni el HAL. Si manana la maqueta cambiara de placa,
    este archivo no se tocaria.

POR QUE UN QTimer Y NO SENALES DESDE LOS HILOS
    Qt exige que solo el hilo principal toque los widgets. Emitir senales desde
    hilos de Python funciona, pero hay que tener cuidado con las conexiones y
    los tipos, y los errores se manifiestan como cuelgues raros e
    irreproducibles. Sondear una foto consistente cada 200 ms es mas simple, se
    entiende de una lectura y no puede fallar de esa manera. A 5 Hz el ojo no
    nota diferencia y la Raspberry Pi ni se despeina.

COMO ESTA ORGANIZADO EL ARCHIVO
    1. Paleta y hoja de estilo   - todos los colores en un solo lugar
    2. Widgets propios           - LED, semaforo y tira, dibujados a mano
    3. Filas                     - una bomba, un sensor
    4. VentanaPrincipal          - arma los paneles y refresca

INSTALACION EN RASPBERRY PI OS
    Conviene PyQt5 por apt y no por pip; el paquete de Debian trae las
    bibliotecas Qt del sistema ya compiladas:
        sudo apt install -y python3-pyqt5
"""

from __future__ import annotations

import logging

from PyQt5 import QtCore, QtGui, QtWidgets

import config
import estado as est

log = logging.getLogger(__name__)


# =============================================================================
#  Paleta
# =============================================================================
# Tema oscuro, estilo panel industrial: en la sala de la maqueta hay poca luz y
# el contraste alto se lee mejor de lejos. Todos los colores estan aqui para
# poder cambiar el aspecto sin buscar valores sueltos por el archivo.
#
# Los pares ON/OFF de cada luz son eso: el mismo tono encendido y una version
# muy oscura del mismo tono para cuando esta apagada. Asi una luz apagada se
# sigue reconociendo como "la roja" aunque no este brillando.
FONDO = "#141821"
PANEL = "#1C222D"
BORDE = "#2B3444"
TEXTO = "#E6EAF0"
TEXTO_TENUE = "#8A94A6"
AZUL = "#1F6FB2"
AZUL_CLARO = "#3D9BE9"

VERDE_ON, VERDE_OFF = QtGui.QColor("#2ECC71"), QtGui.QColor("#1B2E22")
AMARILLO_ON, AMARILLO_OFF = QtGui.QColor("#F1C40F"), QtGui.QColor("#332D14")
ROJO_ON, ROJO_OFF = QtGui.QColor("#E74C3C"), QtGui.QColor("#331F1C")

COLOR_LUZ = {
    "rojo": (ROJO_ON, ROJO_OFF),
    "amarillo": (AMARILLO_ON, AMARILLO_OFF),
    "verde": (VERDE_ON, VERDE_OFF),
}

HOJA_ESTILO = f"""
QWidget {{ background: {FONDO}; color: {TEXTO}; font-size: 11pt; }}
QLabel {{ background: transparent; }}
QFrame#panel {{
    background: {PANEL};
    border: 1px solid {BORDE};
    border-radius: 4px;
}}
QLabel#titulo {{ font-size: 18pt; font-weight: bold; color: {TEXTO}; }}
QLabel#subtitulo {{ font-size: 10pt; color: {TEXTO_TENUE}; }}
QLabel#seccion {{
    font-size: 11pt; font-weight: bold; color: {AZUL_CLARO};
    padding-bottom: 2px;
}}
QLabel#tenue {{ color: {TEXTO_TENUE}; font-size: 9pt; }}
QLabel#dato {{ font-family: "DejaVu Sans Mono", monospace; font-size: 12pt; }}
QPushButton {{
    background: {AZUL}; color: white; border: none;
    padding: 7px 14px; border-radius: 3px; font-weight: bold;
}}
QPushButton:hover {{ background: {AZUL_CLARO}; }}
QPushButton:disabled {{ background: #33404F; color: #6B7686; }}
QPushButton#emergencia {{ background: #B3261E; }}
QPushButton#emergencia:hover {{ background: #D6392F; }}
QProgressBar {{
    background: #10141B; border: 1px solid {BORDE};
    border-radius: 3px; text-align: center; font-size: 9pt; height: 16px;
}}
QProgressBar::chunk {{ background: {AZUL}; border-radius: 2px; }}
QComboBox {{
    background: #10141B; border: 1px solid {BORDE}; border-radius: 3px;
    padding: 5px 8px; color: {TEXTO};
}}
QComboBox::drop-down {{ border: none; width: 18px; }}
QSpinBox, QDoubleSpinBox {{
    background: #10141B; border: 1px solid {BORDE}; border-radius: 3px;
    padding: 4px 6px; color: {TEXTO};
    font-family: "DejaVu Sans Mono", monospace;
}}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background: {AZUL}; border: none; width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {AZUL_CLARO};
}}
QComboBox QAbstractItemView {{
    background: #10141B; color: {TEXTO};
    selection-background-color: {AZUL}; border: 1px solid {BORDE};
}}
QPlainTextEdit {{
    background: #10141B; border: 1px solid {BORDE}; border-radius: 4px;
    font-family: "DejaVu Sans Mono", monospace; font-size: 9pt;
    color: {TEXTO_TENUE};
}}
"""


def _panel(titulo: str) -> tuple[QtWidgets.QFrame, QtWidgets.QVBoxLayout]:
    """Crea un recuadro con titulo de seccion y devuelve (marco, layout).

    Devuelve los dos porque quien llama necesita el marco para colocarlo en la
    ventana y el layout para meterle contenido debajo del titulo.
    """
    marco = QtWidgets.QFrame()
    marco.setObjectName("panel")
    caja = QtWidgets.QVBoxLayout(marco)
    caja.setContentsMargins(12, 10, 12, 10)
    caja.setSpacing(6)
    etiqueta = QtWidgets.QLabel(titulo)
    etiqueta.setObjectName("seccion")
    caja.addWidget(etiqueta)
    return marco, caja


# =============================================================================
#  Widgets propios
# =============================================================================
# Los tres widgets de esta seccion se dibujan a mano en paintEvent() en vez de
# armarse con widgets estandar de Qt. Es mas codigo, pero permite el aspecto de
# panel real (halos, luces con brillo, LED redondos) que con QLabel y hojas de
# estilo saldria pesado y feo.
#
# Todos siguen el mismo patron:
#   1. Un metodo set_*() que recibe el estado nuevo.
#   2. Ese metodo compara con lo que ya tenia y, SOLO si cambio, llama a
#      update(), que le pide a Qt que vuelva a dibujar.
#   3. paintEvent() dibuja a partir del estado guardado.
#
# La comparacion del paso 2 es importante: el refresco corre 5 veces por
# segundo y sin ella se estaria repintando todo continuamente sin necesidad.

class LedIndicador(QtWidgets.QWidget):
    """Circulo que se enciende o se apaga, y responde al clic.

    Es la luz de cada bomba. Al hacer clic emite `clicado`, que la ventana
    traduce en habilitar o deshabilitar esa bomba.

    Tres estados visuales:
        encendida      - verde brillante con halo
        apagada        - verde muy oscuro
        deshabilitada  - ademas, borde rojo y una barra diagonal encima
    """

    # Senal de Qt. La ventana la conecta para enterarse del clic sin que este
    # widget tenga que saber que existe un controlador.
    clicado = QtCore.pyqtSignal()

    def __init__(self, encendido_color=VERDE_ON, apagado_color=VERDE_OFF,
                 diametro: int = 22, parent=None) -> None:
        super().__init__(parent)
        self._on = False
        self._deshabilitado = False
        self._color_on = encendido_color
        self._color_off = apagado_color
        self._d = diametro
        # +4 px de margen para que quepa el halo sin quedar recortado.
        self.setFixedSize(diametro + 4, diametro + 4)
        # El cursor de mano es la unica pista visual de que esto se puede
        # clicar; sin el, nadie lo descubriria.
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def set_encendido(self, encendido: bool, deshabilitado: bool = False) -> None:
        """Actualiza el estado y repinta solo si algo cambio."""
        if (encendido, deshabilitado) != (self._on, self._deshabilitado):
            self._on = encendido
            self._deshabilitado = deshabilitado
            self.update()

    def mousePressEvent(self, evento) -> None:
        """Qt llama a esto al pulsar sobre el widget."""
        if evento.button() == QtCore.Qt.LeftButton:
            self.clicado.emit()
        super().mousePressEvent(evento)

    def paintEvent(self, evento) -> None:
        """Qt llama a esto cada vez que hay que redibujar."""
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)   # bordes suaves
        color = self._color_on if self._on else self._color_off

        if self._on:
            # Halo: el mismo color pero casi transparente y un poco mas grande.
            # Da la sensacion de que la luz "brilla" en vez de ser un circulo.
            halo = QtGui.QColor(color)
            halo.setAlpha(70)
            p.setBrush(halo)
            p.setPen(QtCore.Qt.NoPen)
            p.drawEllipse(0, 0, self._d + 4, self._d + 4)

        p.setBrush(color)
        borde = QtGui.QColor(ROJO_ON) if self._deshabilitado else QtGui.QColor(BORDE)
        p.setPen(QtGui.QPen(borde, 2 if self._deshabilitado else 1))
        p.drawEllipse(2, 2, self._d, self._d)

        if self._deshabilitado:
            # Barra diagonal: se ve de lejos que esa bomba esta fuera de juego.
            p.setPen(QtGui.QPen(QtGui.QColor(ROJO_ON), 2))
            m = 5
            p.drawLine(m, self._d + 4 - m, self._d + 4 - m, m)


class WidgetSemaforo(QtWidgets.QWidget):
    """Semaforo de tres luces dibujado a mano.

    Un cuerpo oscuro con tres circulos: rojo arriba, amarillo al medio, verde
    abajo, como uno de la calle. Se dibuja siempre entero; las luces apagadas
    se pintan en su version oscura en vez de omitirse.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._luces = {"rojo": False, "amarillo": False, "verde": False}
        # Tamano fijo: tres luces de 36 px con sus separaciones. Si se dejara
        # elastico, el layout lo estiraria y los circulos se deformarian.
        self.setFixedSize(62, 152)

    def set_luces(self, luces: dict[str, bool]) -> None:
        """Recibe {"rojo": False, "amarillo": False, "verde": True}."""
        # Se normaliza con .get() por si llega un diccionario incompleto, cosa
        # que pasa en el primer refresco antes de que los hilos publiquen nada.
        nuevo = {c: bool(luces.get(c, False)) for c in self._luces}
        if nuevo != self._luces:
            self._luces = nuevo
            self.update()

    def paintEvent(self, evento) -> None:
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        # Cuerpo del semaforo: rectangulo redondeado casi negro.
        p.setBrush(QtGui.QColor("#0E1219"))
        p.setPen(QtGui.QPen(QtGui.QColor(BORDE), 1))
        p.drawRoundedRect(1, 1, self.width() - 2, self.height() - 2, 8, 8)

        d = 36                          # diametro de cada luz
        x = (self.width() - d) // 2     # centradas horizontalmente
        for i, color in enumerate(("rojo", "amarillo", "verde")):
            y = 10 + i * (d + 8)        # 10 px de margen, 8 px entre luces
            on, off = COLOR_LUZ[color]
            actual = on if self._luces[color] else off

            if self._luces[color]:
                # Mismo truco del halo que en LedIndicador.
                halo = QtGui.QColor(on)
                halo.setAlpha(60)
                p.setBrush(halo)
                p.setPen(QtCore.Qt.NoPen)
                p.drawEllipse(x - 4, y - 4, d + 8, d + 8)

            p.setBrush(actual)
            # Borde negro grueso: imita el reborde de la carcasa y hace que la
            # luz encendida resalte del cuerpo.
            p.setPen(QtGui.QPen(QtGui.QColor("#0A0D12"), 2))
            p.drawEllipse(x, y, d, d)


class WidgetTira(QtWidgets.QWidget):
    """Representacion de una tira direccionable: una fila de LED redondos.

    Refleja pixel por pixel lo que se esta enviando a la tira fisica, lo que
    permite comprobar la animacion sin tener la maqueta delante.

    Se adapta solo a la cantidad de LED (de 1 a 200) y al ancho disponible:
    calcula el paso y el diametro en cada repintado. Con 100 LED los circulos
    quedan chicos, pero la animacion se sigue leyendo perfectamente.
    """

    def __init__(self, n_leds: int, parent=None) -> None:
        super().__init__(parent)
        self._pixeles = [(0, 0, 0)] * n_leds
        self.setMinimumHeight(26)
        # Ancho elastico, alto fijo: ocupa lo que sobre en su fila.
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                           QtWidgets.QSizePolicy.Fixed)

    def set_pixeles(self, pixeles) -> None:
        """Recibe la lista completa de colores: [(r,g,b), (r,g,b), ...]."""
        if list(pixeles) != self._pixeles:
            self._pixeles = list(pixeles)
            self.update()

    def paintEvent(self, evento) -> None:
        n = len(self._pixeles)
        if n == 0:
            return      # tira sin LED (o que no inicializo): no se dibuja nada

        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing)

        # Geometria adaptativa:
        #   paso = cuanto espacio horizontal le toca a cada LED
        #   d    = diametro, limitado por el paso, por el alto y por un minimo
        #          de 6 px para que con 200 LED no queden invisibles
        paso = self.width() / n
        d = max(6.0, min(paso - 2.0, self.height() - 6.0))
        y = (self.height() - d) / 2.0      # centrado vertical

        for i, (r, g, b) in enumerate(self._pixeles):
            x = i * paso + (paso - d) / 2.0     # centrado dentro de su hueco
            encendido = (r or g or b)           # negro puro = apagado
            if encendido:
                halo = QtGui.QColor(r, g, b)
                halo.setAlpha(70)
                p.setBrush(halo)
                p.setPen(QtCore.Qt.NoPen)
                p.drawEllipse(QtCore.QRectF(x - 2, y - 2, d + 4, d + 4))
                p.setBrush(QtGui.QColor(r, g, b))
                p.setPen(QtGui.QPen(QtGui.QColor("#0A0D12"), 1))
            else:
                p.setBrush(QtGui.QColor("#161C26"))
                p.setPen(QtGui.QPen(QtGui.QColor(BORDE), 1))
            p.drawEllipse(QtCore.QRectF(x, y, d, d))


class FilaBomba(QtWidgets.QWidget):
    """Una salida de potencia: LED clicable, nombre, GPIO y estado en texto.

    Reenvia el clic del LED como la senal `clicado` llevando el nombre de la
    bomba ("P1", "P2"...), para que la ventana no tenga que ir averiguando cual
    de las cuatro filas lo emitio.
    """

    clicado = QtCore.pyqtSignal(str)    # lleva el nombre de la bomba

    def __init__(self, nombre: str, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._nombre = nombre
        caja = QtWidgets.QHBoxLayout(self)
        caja.setContentsMargins(0, 2, 0, 2)
        caja.setSpacing(10)

        self.led = LedIndicador()
        self.led.setToolTip(
            f"Clic para apagar o volver a encender {nombre}.\n"
            "Queda fuera de la secuencia hasta que se vuelva a habilitar."
        )
        self.led.clicado.connect(lambda: self.clicado.emit(self._nombre))
        caja.addWidget(self.led)

        textos = QtWidgets.QVBoxLayout()
        textos.setSpacing(0)
        titulo = QtWidgets.QLabel(f"{nombre} · {cfg['etiqueta']}")
        titulo.setStyleSheet("font-weight: bold;")
        # Los dos canales van juntos en la etiqueta porque van juntos en el
        # hardware: es el polo de +12 V y el retorno de la misma bomba.
        pines = "/".join(f"GPIO{p}" for p in cfg["pines"])
        canales = "/".join(str(c) for c in cfg["canales"])
        detalle = QtWidgets.QLabel(
            f"{pines} · canales {canales} → bornera {cfg['bornera']}"
        )
        detalle.setObjectName("tenue")
        textos.addWidget(titulo)
        textos.addWidget(detalle)
        caja.addLayout(textos)
        caja.addStretch(1)

        self.estado = QtWidgets.QLabel("APAGADA")
        self.estado.setObjectName("dato")
        self.estado.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.estado.setMinimumWidth(96)
        caja.addWidget(self.estado)

    def actualizar(self, encendida: bool, habilitada: bool = True) -> None:
        self.led.set_encendido(encendida, deshabilitado=not habilitada)
        if not habilitada:
            self.estado.setText("DESHABILITADA")
            self.estado.setStyleSheet(
                f"color: {ROJO_ON.name()}; font-weight: bold; font-size: 10pt;"
            )
            return
        self.estado.setText("ENCENDIDA" if encendida else "APAGADA")
        color = VERDE_ON.name() if encendida else TEXTO_TENUE
        self.estado.setStyleSheet(f"color: {color}; font-weight: bold;")


class FilaLuminaria(QtWidgets.QWidget):
    """Una salida de iluminacion: luz clicable, datos y boton de encendido.

    Se parece a FilaBomba pero significa otra cosa, y por eso se dibuja
    distinto:

        BOMBA      la enciende la SECUENCIA. El clic solo la deja fuera del
                   ciclo (deshabilitada), no la maneja directamente.
        LUMINARIA  la enciende el OPERADOR. No hay secuencia detras: queda
                   como la dejaron hasta el proximo clic.

    Como no hay nada automatico que la vuelva a mover, se le pone un boton con
    texto ademas de la luz: un interruptor tiene que verse como un interruptor.
    Ambos hacen lo mismo, alternar la salida.

    El color ambar (y no el verde de las bombas) refuerza de un vistazo que es
    otra cosa: no es caudal, es luz.
    """

    clicado = QtCore.pyqtSignal(str)    # lleva el nombre de la luminaria

    def __init__(self, nombre: str, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        self._nombre = nombre
        caja = QtWidgets.QHBoxLayout(self)
        caja.setContentsMargins(0, 2, 0, 2)
        caja.setSpacing(10)

        self.led = LedIndicador(AMARILLO_ON, AMARILLO_OFF)
        self.led.setToolTip(f"Clic para encender o apagar: {cfg['etiqueta']}")
        self.led.clicado.connect(lambda: self.clicado.emit(self._nombre))
        caja.addWidget(self.led)

        textos = QtWidgets.QVBoxLayout()
        textos.setSpacing(0)
        titulo = QtWidgets.QLabel(cfg["etiqueta"])
        titulo.setStyleSheet("font-weight: bold;")
        # Aqui se nombra el pin fisico y la senal ademas del GPIO: el LED no
        # esta en la tarjeta sino cableado a mano al header, asi que quien lo
        # conecte necesita saber a que pin del conector va.
        detalle = QtWidgets.QLabel(
            f"GPIO{cfg['gpio']} · pin {cfg['pin_fisico']} ({cfg['senal']}) "
            f"→ LED directo"
        )
        detalle.setObjectName("tenue")
        detalle.setToolTip(
            "LED cableado directo al GPIO (con su resistencia serie), fuera\n"
            "de los 8 canales de relé: esos se los llevan las bombas.\n"
            "Enciende con el pin en ALTO (LUMINARIA_ACTIVO_EN_BAJO = False).\n\n"
            "El SPI debe estar DESHABILITADO: si dtparam=spi=on está en\n"
            "config.txt, el kernel toma GPIO 9 y 11 y los LED no encienden,\n"
            "sin ningún mensaje de error."
        )
        textos.addWidget(titulo)
        textos.addWidget(detalle)
        caja.addLayout(textos)
        caja.addStretch(1)

        self.boton = QtWidgets.QPushButton("Encender")
        self.boton.setFixedWidth(104)
        self.boton.clicked.connect(lambda: self.clicado.emit(self._nombre))
        caja.addWidget(self.boton)

    def actualizar(self, encendida: bool) -> None:
        self.led.set_encendido(encendida)
        # El boton dice lo que VA A HACER, no el estado en que esta. Un boton
        # que dijera "ENCENDIDA" se leeria como un indicador y nadie lo tocaria.
        self.boton.setText("Apagar" if encendida else "Encender")
        if encendida:
            self.boton.setStyleSheet(
                f"background: {AMARILLO_ON.name()}; color: #141821;"
            )
        else:
            self.boton.setStyleSheet("")    # vuelve al azul de la hoja de estilo


class FilaSensor(QtWidgets.QWidget):
    """Un VL53L0X: distancia medida arriba y barra de llenado abajo.

    Tiene tres aspectos segun el estado de la lectura:
        conectado y midiendo -> distancia en mm y barra con el porcentaje
        conectado pero fallo -> "sin lectura" en rojo
        sin sensor           -> "DESCONECTADO" en gris, barra vacia

    La distincion importa: mostrar una distancia inventada cuando no hay sensor
    seria peor que no mostrar nada.
    """

    def __init__(self, cfg: dict, parent=None) -> None:
        super().__init__(parent)
        caja = QtWidgets.QVBoxLayout(self)
        caja.setContentsMargins(0, 3, 0, 3)
        caja.setSpacing(2)

        cabecera = QtWidgets.QHBoxLayout()
        cabecera.setSpacing(8)
        titulo = QtWidgets.QLabel(cfg["etiqueta"])
        titulo.setStyleSheet("font-weight: bold;")
        canal = QtWidgets.QLabel(
            f"canal {cfg['canal']} · {cfg['bornera']} · 0x29"
        )
        canal.setObjectName("tenue")
        cabecera.addWidget(titulo)
        cabecera.addWidget(canal)
        cabecera.addStretch(1)
        self.valor = QtWidgets.QLabel("--- mm")
        self.valor.setObjectName("dato")
        cabecera.addWidget(self.valor)
        caja.addLayout(cabecera)

        self.barra = QtWidgets.QProgressBar()
        self.barra.setRange(0, 100)
        self.barra.setValue(0)
        self.barra.setFormat("%p %")
        caja.addWidget(self.barra)

    def actualizar(self, lectura) -> None:
        if not lectura.conectado:
            # Sin sensor en ese canal del multiplexor. Se dice explicitamente,
            # en vez de mostrar una distancia que no existe.
            self.valor.setText("DESCONECTADO")
            self.valor.setStyleSheet(
                f"color: {TEXTO_TENUE}; font-weight: bold; font-size: 10pt;"
            )
            self.barra.setValue(0)
            self.barra.setFormat("sin sensor")
            self.barra.setStyleSheet(
                f"QProgressBar {{ color: {TEXTO_TENUE}; }}"
                f"QProgressBar::chunk {{ background: {BORDE}; }}"
            )
            self.barra.setToolTip(
                "No hay ningun VL53L0X respondiendo en 0x29 en este canal.\n"
                "Se reintenta la deteccion automaticamente."
            )
            return

        if not lectura.ok:
            self.valor.setText("sin lectura")
            self.valor.setStyleSheet(f"color: {ROJO_ON.name()}; font-weight: bold;")
            self.barra.setValue(0)
            self.barra.setFormat("error")
            self.barra.setToolTip(lectura.error)
            return

        pct = lectura.nivel_pct or 0.0
        self.valor.setText(f"{lectura.distancia_mm} mm")
        self.valor.setStyleSheet(f"color: {TEXTO};")
        self.barra.setValue(int(round(pct)))
        self.barra.setFormat(f"{pct:.1f} % de llenado")
        self.barra.setToolTip("")

        if pct >= config.NIVEL_CRITICO_PCT:
            relleno = ROJO_ON.name()
        elif pct >= config.NIVEL_ALERTA_PCT:
            relleno = AMARILLO_ON.name()
        else:
            relleno = AZUL
        self.barra.setStyleSheet(
            f"QProgressBar::chunk {{ background: {relleno}; border-radius: 2px; }}"
        )


# =============================================================================
#  Ventana principal
# =============================================================================

class VentanaPrincipal(QtWidgets.QMainWindow):
    """La ventana del dashboard.

    DISTRIBUCION
        +--------------------------------------------------------------+
        |  Cabecera: nombre del cuadrante y modo (real o simulacion)    |
        +--------------------------------------------------------------+
        |  Fase actual + barra de progreso + cuenta regresiva + ciclo   |
        +----------------+---------------+-----------------------------+
        |  Bombas        |  Semaforos    |  Nivel de estanques         |
        |  (4 filas +    |  (2 luces     |  (4 filas con distancia y   |
        |   4 tiempos)   |   dibujadas)  |   barra de llenado)         |
        |                +---------------+                             |
        |                |  Luminarias   |                             |
        |                |  exteriores   |                             |
        +----------------+---------------+-----------------------------+
        |  Tiras LED: 2 filas de pixeles + velocidad y color           |
        +--------------------------------------------------------------+
        |  Registro de eventos                                          |
        +--------------------------------------------------------------+
        |  Iniciar | Detener            PARADA DE EMERGENCIA | Salir    |
        +--------------------------------------------------------------+

    Cada panel se arma en su propio metodo _construir_*, que guarda en
    atributos los widgets que despues hay que actualizar. Todo el refresco pasa
    por _refrescar(), que es el unico metodo que lee el estado.
    """

    def __init__(self, controlador) -> None:
        super().__init__()
        # Unico punto de contacto con el resto del sistema. La ventana no
        # conoce el hardware; solo este objeto.
        self._ctrl = controlador
        self._estado = controlador.compartido
        # Cantidad de lineas del registro dibujadas la ultima vez, para no
        # reescribir el cuadro de texto entero en cada refresco.
        self._ultimo_log = 0

        self.setWindowTitle(f"Maqueta · {config.NOMBRE_CUADRANTE}")
        self.resize(1180, 720)
        self.setStyleSheet(HOJA_ESTILO)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        raiz = QtWidgets.QVBoxLayout(central)
        raiz.setContentsMargins(14, 12, 14, 12)
        raiz.setSpacing(10)

        raiz.addWidget(self._construir_cabecera())
        raiz.addWidget(self._construir_fase())

        # Los numeros (4, 3, 5) son proporciones de ancho, no pixeles: los
        # sensores se llevan mas espacio porque llevan barras, y la columna del
        # medio menos porque son dos dibujos angostos y un interruptor.
        columnas = QtWidgets.QHBoxLayout()
        columnas.setSpacing(10)
        columnas.addWidget(self._construir_bombas(), 4)

        # Los semaforos ocupan poco alto, asi que las luminarias se cuelgan
        # debajo en la misma columna en vez de robarle ancho a los sensores.
        # El 1 del semaforo hace que sea el que absorbe el espacio sobrante.
        centro = QtWidgets.QVBoxLayout()
        centro.setSpacing(10)
        centro.addWidget(self._construir_semaforos(), 1)
        centro.addWidget(self._construir_luminarias())
        columnas.addLayout(centro, 3)

        columnas.addWidget(self._construir_sensores(), 5)
        raiz.addLayout(columnas, 1)     # el 1 hace que esta fila absorba el alto

        raiz.addWidget(self._construir_tiras())
        raiz.addWidget(self._construir_log())
        raiz.addLayout(self._construir_botones())

        # El corazon de la interfaz: un temporizador que llama a _refrescar()
        # cinco veces por segundo. No hay ninguna otra forma de actualizacion.
        self._temporizador = QtCore.QTimer(self)
        self._temporizador.timeout.connect(self._refrescar)
        self._temporizador.start(config.REFRESCO_GUI_MS)

    # ------------------------------------------------------------- secciones
    def _construir_cabecera(self) -> QtWidgets.QWidget:
        marco = QtWidgets.QFrame()
        marco.setObjectName("panel")
        caja = QtWidgets.QHBoxLayout(marco)
        caja.setContentsMargins(14, 10, 14, 10)

        textos = QtWidgets.QVBoxLayout()
        textos.setSpacing(0)
        titulo = QtWidgets.QLabel(config.NOMBRE_CUADRANTE)
        titulo.setObjectName("titulo")
        sub = QtWidgets.QLabel(
            "Tarjeta de control de cuadrante v1.0.0 · "
            "4 bombas de 12 V (8 canales) · 2 luminarias LED · "
            "4 sensores VL53L0X tras el TCA9548A"
        )
        sub.setObjectName("subtitulo")
        textos.addWidget(titulo)
        textos.addWidget(sub)
        caja.addLayout(textos)
        caja.addStretch(1)

        self.etq_modo = QtWidgets.QLabel()
        self.etq_modo.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        caja.addWidget(self.etq_modo)
        return marco

    def _construir_fase(self) -> QtWidgets.QWidget:
        marco = QtWidgets.QFrame()
        marco.setObjectName("panel")
        caja = QtWidgets.QHBoxLayout(marco)
        caja.setContentsMargins(14, 8, 14, 8)
        caja.setSpacing(14)

        self.etq_fase = QtWidgets.QLabel("---")
        self.etq_fase.setStyleSheet("font-size: 13pt; font-weight: bold;")
        self.etq_fase.setMinimumWidth(300)
        caja.addWidget(self.etq_fase)

        self.barra_fase = QtWidgets.QProgressBar()
        self.barra_fase.setRange(0, 1000)
        caja.addWidget(self.barra_fase, 1)

        self.etq_restante = QtWidgets.QLabel("--")
        self.etq_restante.setObjectName("dato")
        self.etq_restante.setMinimumWidth(120)
        self.etq_restante.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        caja.addWidget(self.etq_restante)

        self.etq_ciclo = QtWidgets.QLabel("ciclo 0")
        self.etq_ciclo.setObjectName("tenue")
        self.etq_ciclo.setMinimumWidth(70)
        caja.addWidget(self.etq_ciclo)
        return marco

    def _construir_bombas(self) -> QtWidgets.QWidget:
        marco, caja = _panel("Bombas de 12 V (2 canales cada una, activos en bajo)")
        self.filas_bomba: dict[str, FilaBomba] = {}
        for nombre, cfg in config.RELES.items():
            fila = FilaBomba(nombre, cfg)
            fila.clicado.connect(self._ctrl.alternar_bomba)
            self.filas_bomba[nombre] = fila
            caja.addWidget(fila)

        pista = QtWidgets.QLabel("Clic en la luz para apagar esa bomba")
        pista.setObjectName("tenue")
        caja.addWidget(pista)
        caja.addStretch(1)

        # --- Tiempos de la secuencia, ajustables en caliente ---
        separador = QtWidgets.QFrame()
        separador.setFrameShape(QtWidgets.QFrame.HLine)
        separador.setStyleSheet(f"color: {BORDE};")
        caja.addWidget(separador)

        etq = QtWidgets.QLabel("Tiempos de la secuencia")
        etq.setObjectName("tenue")
        caja.addWidget(etq)

        p_enc, p_sos, p_apa, p_off = self._ctrl.tiempos_bombas()
        rejilla = QtWidgets.QGridLayout()
        rejilla.setSpacing(6)

        self.spin_encendido = self._spin_tiempo(
            p_enc, config.T_PASO_MIN_S, config.T_PASO_MAX_S, 0.1, 1,
            self._ctrl.set_paso_encendido_s,
            "Segundos entre el encendido de una bomba y la siguiente",
        )
        self.spin_sostenido = self._spin_tiempo(
            p_sos, config.T_SOSTENIDO_MIN_S, config.T_SOSTENIDO_MAX_S, 5.0, 0,
            self._ctrl.set_sostenido_s,
            "Cuánto quedan las cuatro bombas encendidas.\n"
            "El cambio se aplica de inmediato, incluso a mitad de la fase.",
        )
        self.spin_apagado = self._spin_tiempo(
            p_apa, config.T_PASO_MIN_S, config.T_PASO_MAX_S, 0.1, 1,
            self._ctrl.set_paso_apagado_s,
            "Segundos entre el apagado de una bomba y la siguiente",
        )
        self.spin_apagadas = self._spin_tiempo(
            p_off, config.T_APAGADAS_MIN_S, config.T_APAGADAS_MAX_S, 5.0, 0,
            self._ctrl.set_apagadas_s,
            "Reposo con las cuatro bombas apagadas antes de reiniciar el ciclo.\n"
            "En 0 s el ciclo vuelve a empezar de inmediato.",
        )

        for fila, (texto, spin) in enumerate((
            ("Encender de a una cada", self.spin_encendido),
            ("Mantener encendidas", self.spin_sostenido),
            ("Apagar de a una cada", self.spin_apagado),
            ("Mantener apagadas", self.spin_apagadas),
        )):
            etiqueta = QtWidgets.QLabel(texto)
            etiqueta.setObjectName("tenue")
            rejilla.addWidget(etiqueta, fila, 0)
            rejilla.addWidget(spin, fila, 1)
        rejilla.setColumnStretch(0, 1)
        caja.addLayout(rejilla)

        self.etq_resumen_bombas = QtWidgets.QLabel("0 de 4 encendidas")
        self.etq_resumen_bombas.setObjectName("tenue")
        caja.addWidget(self.etq_resumen_bombas)
        return marco

    def _spin_tiempo(self, valor, minimo, maximo, paso, decimales,
                     al_cambiar, ayuda) -> QtWidgets.QDoubleSpinBox:
        spin = QtWidgets.QDoubleSpinBox()
        spin.setRange(minimo, maximo)
        spin.setSingleStep(paso)
        spin.setDecimals(decimales)
        spin.setValue(valor)
        spin.setSuffix(" s")
        spin.setFixedWidth(105)
        spin.setToolTip(ayuda)
        spin.setKeyboardTracking(False)   # no dispara a cada tecla
        spin.valueChanged.connect(al_cambiar)
        return spin

    def _construir_semaforos(self) -> QtWidgets.QWidget:
        marco, caja = _panel("Semáforos")
        fila = QtWidgets.QHBoxLayout()
        fila.setSpacing(12)
        self.widgets_semaforo: dict[str, WidgetSemaforo] = {}
        for nombre, cfg in config.SEMAFOROS.items():
            columna = QtWidgets.QVBoxLayout()
            columna.setSpacing(3)
            etiqueta = QtWidgets.QLabel(f"{nombre} · {cfg['bornera']}")
            etiqueta.setAlignment(QtCore.Qt.AlignCenter)
            etiqueta.setStyleSheet("font-weight: bold;")
            widget = WidgetSemaforo()
            self.widgets_semaforo[nombre] = widget
            uso = QtWidgets.QLabel(cfg["etiqueta"])
            uso.setObjectName("tenue")
            uso.setAlignment(QtCore.Qt.AlignCenter)
            uso.setWordWrap(True)
            columna.addWidget(etiqueta)
            columna.addWidget(widget, 0, QtCore.Qt.AlignCenter)
            columna.addWidget(uso)
            fila.addLayout(columna)
        caja.addLayout(fila)
        caja.addStretch(1)
        return marco

    def _construir_luminarias(self) -> QtWidgets.QWidget:
        marco, caja = _panel("Luminarias exteriores")
        self.filas_luminaria: dict[str, FilaLuminaria] = {}
        for nombre, cfg in config.LUMINARIAS.items():
            fila = FilaLuminaria(nombre, cfg)
            fila.clicado.connect(self._ctrl.alternar_luminaria)
            self.filas_luminaria[nombre] = fila
            caja.addWidget(fila)

        pista = QtWidgets.QLabel(
            "Encendido manual: LED directos al GPIO, fuera de la secuencia de bombas"
        )
        pista.setObjectName("tenue")
        pista.setWordWrap(True)
        caja.addWidget(pista)
        return marco

    def _construir_sensores(self) -> QtWidgets.QWidget:
        marco, caja = _panel("Nivel de estanques (VL53L0X, los 4 en 0x29)")
        self.filas_sensor: dict[int, FilaSensor] = {}
        for cfg in config.SENSORES:
            fila = FilaSensor(cfg)
            self.filas_sensor[cfg["canal"]] = fila
            caja.addWidget(fila)
        caja.addStretch(1)
        nota = QtWidgets.QLabel(
            f"Vacío = {config.DISTANCIA_ESTANQUE_VACIO_MM} mm · "
            f"lleno = {config.DISTANCIA_ESTANQUE_LLENO_MM} mm · "
            f"alerta {config.NIVEL_ALERTA_PCT:.0f} % · "
            f"crítico {config.NIVEL_CRITICO_PCT:.0f} %"
        )
        nota.setObjectName("tenue")
        nota.setWordWrap(True)
        caja.addWidget(nota)
        return marco

    def _construir_tiras(self) -> QtWidgets.QWidget:
        marco, caja = _panel("Tiras LED direccionables WS2812B")

        self.widgets_tira: dict[str, WidgetTira] = {}
        self.spins_n_leds: dict[str, QtWidgets.QSpinBox] = {}
        self.combos_color: dict[str, QtWidgets.QComboBox] = {}
        self.muestras_color: dict[str, QtWidgets.QLabel] = {}
        for nombre, cfg in config.TIRAS.items():
            fila = QtWidgets.QHBoxLayout()
            fila.setSpacing(10)

            etiqueta = QtWidgets.QLabel(
                f"{cfg['etiqueta']} ({nombre}) · GPIO{cfg['gpio']} "
                f"(PWM{cfg['canal_pwm']}) · {cfg['bornera']}"
            )
            etiqueta.setObjectName("tenue")
            etiqueta.setMinimumWidth(260)
            fila.addWidget(etiqueta)

            spin = QtWidgets.QSpinBox()
            spin.setRange(1, config.TIRA_N_LEDS_MAX)
            spin.setValue(self._ctrl.n_leds(nombre))
            spin.setSuffix(" LED")
            spin.setFixedWidth(92)
            spin.setKeyboardTracking(False)
            spin.setToolTip(
                f"Cantidad de LED de la tira {nombre}.\n"
                f"Máximo {config.TIRA_N_LEDS_MAX} (reservado al arrancar; para "
                f"subirlo hay que cambiar TIRA_N_LEDS_MAX en config.py y "
                f"reiniciar)."
            )
            # El nombre de la tira se fija en el lambda para no capturar la
            # variable del bucle, que al terminar valdria siempre la ultima.
            spin.valueChanged.connect(
                lambda valor, t=nombre: self._ctrl.set_n_leds(t, valor)
            )
            self.spins_n_leds[nombre] = spin
            fila.addWidget(spin)

            # Cada tira tiene su propio desplegable de color: T1 y T2 pueden ir
            # de colores distintos. El combo vive en la fila de su tira para
            # que no haya duda de a cual afecta.
            combo = QtWidgets.QComboBox()
            for nombre_color, rgb in config.TIRA_COLORES:
                combo.addItem(nombre_color, rgb)
            combo.setFixedWidth(110)
            indice = combo.findText(self._ctrl.color_nombre_tira(nombre))
            if indice >= 0:
                combo.setCurrentIndex(indice)
            combo.setToolTip(f"Color de la tira {nombre}. No afecta a la otra.")
            # El nombre se fija en el lambda por lo mismo que en el spin de
            # arriba: no capturar la variable del bucle.
            combo.currentIndexChanged.connect(
                lambda idx, t=nombre: self._al_cambiar_color(t, idx)
            )
            self.combos_color[nombre] = combo
            fila.addWidget(combo)

            muestra = QtWidgets.QLabel()
            muestra.setFixedSize(26, 20)
            self.muestras_color[nombre] = muestra
            fila.addWidget(muestra)

            widget = WidgetTira(cfg["n_leds"])
            self.widgets_tira[nombre] = widget
            fila.addWidget(widget, 1)
            caja.addLayout(fila)

        controles = QtWidgets.QHBoxLayout()
        controles.setSpacing(8)

        controles.addWidget(QtWidgets.QLabel("Velocidad:"))
        btn_lento = QtWidgets.QPushButton("−")
        btn_lento.setFixedWidth(38)
        btn_lento.setToolTip("Más lento")
        btn_lento.clicked.connect(self._ctrl.frenar_tiras)
        btn_rapido = QtWidgets.QPushButton("+")
        btn_rapido.setFixedWidth(38)
        btn_rapido.setToolTip("Más rápido")
        btn_rapido.clicked.connect(self._ctrl.acelerar_tiras)
        self.etq_velocidad = QtWidgets.QLabel("-- ms/LED")
        self.etq_velocidad.setObjectName("dato")
        self.etq_velocidad.setMinimumWidth(110)
        controles.addWidget(btn_lento)
        controles.addWidget(btn_rapido)
        controles.addWidget(self.etq_velocidad)

        controles.addStretch(1)
        self.etq_tiras_modo = QtWidgets.QLabel()
        self.etq_tiras_modo.setObjectName("tenue")
        controles.addWidget(self.etq_tiras_modo)

        caja.addLayout(controles)
        return marco

    def _al_cambiar_color(self, tira: str, indice: int) -> None:
        combo = self.combos_color[tira]
        nombre = combo.itemText(indice)
        rgb = combo.itemData(indice)
        self._ctrl.set_color_tira(tira, nombre, rgb)

    def _construir_log(self) -> QtWidgets.QWidget:
        marco, caja = _panel("Registro de eventos")
        self.vista_log = QtWidgets.QPlainTextEdit()
        self.vista_log.setReadOnly(True)
        self.vista_log.setMaximumHeight(96)
        caja.addWidget(self.vista_log)
        return marco

    def _construir_botones(self) -> QtWidgets.QHBoxLayout:
        caja = QtWidgets.QHBoxLayout()
        caja.setSpacing(8)

        self.btn_iniciar = QtWidgets.QPushButton("Iniciar secuencia")
        self.btn_iniciar.clicked.connect(self._al_iniciar)
        self.btn_detener = QtWidgets.QPushButton("Detener secuencia")
        self.btn_detener.clicked.connect(self._al_detener)

        btn_emergencia = QtWidgets.QPushButton("PARADA DE EMERGENCIA")
        btn_emergencia.setObjectName("emergencia")
        btn_emergencia.clicked.connect(self._al_emergencia)

        btn_salir = QtWidgets.QPushButton("Salir")
        btn_salir.clicked.connect(self.close)

        caja.addWidget(self.btn_iniciar)
        caja.addWidget(self.btn_detener)
        caja.addStretch(1)
        caja.addWidget(btn_emergencia)
        caja.addWidget(btn_salir)
        return caja

    # --------------------------------------------------------------- acciones
    def _al_iniciar(self) -> None:
        self._ctrl.iniciar_secuencia()

    def _al_detener(self) -> None:
        self._ctrl.detener_secuencia()

    def _al_emergencia(self) -> None:
        self._ctrl.parada_emergencia()
        QtWidgets.QMessageBox.warning(
            self, "Parada de emergencia",
            "Secuencia detenida.\n\nLas cuatro bombas y las luminarias "
            "exteriores quedaron apagadas (relés en estado seguro).\n"
            "Los semáforos y las tiras siguen corriendo.",
        )

    # -------------------------------------------------------------- refresco
    def _refrescar(self) -> None:
        """Redibuja la ventana entera. Lo llama el QTimer 5 veces por segundo.

        Este es el UNICO metodo que lee el estado del sistema, y lo hace de una
        sola vez con instantanea(). Todo lo que se pinta a continuacion
        corresponde al mismo instante, sin mezclar momentos distintos.

        No hace falta optimizar mucho: son unas decenas de widgets y Qt ignora
        los setText() que no cambian nada. Las dos excepciones, que si valen la
        pena, estan marcadas mas abajo (el registro y los widgets dibujados a
        mano, que llevan su propia comparacion antes de repintar).
        """
        s = self._estado.instantanea()

        # --- Cabecera: en que modo se esta corriendo ---
        # Solo dos estados. El detalle de que parte del hardware falta se avisa
        # en su propio panel (p.ej. "tiras simuladas") y no en la cabecera.
        if s.hay_hardware:
            texto, color = "HARDWARE REAL", VERDE_ON.name()
        else:
            texto, color = "SIMULACIÓN", AMARILLO_ON.name()
        self.etq_modo.setText(
            f"<span style='color:{color}; font-weight:bold; font-size:12pt'>"
            f"{texto}</span>"
        )

        # --- Fase del ciclo y barra de progreso ---
        self.etq_fase.setText(est.DESCRIPCION_FASE.get(s.fase, s.fase))
        if s.duracion_s > 0:
            # La barra va de 0 a 1000 y no de 0 a 100: con fases de dos minutos,
            # una resolucion de 1 % daria saltos visibles de mas de un segundo.
            avance = 1.0 - s.restante_s / s.duracion_s
            self.barra_fase.setValue(int(max(0.0, min(1.0, avance)) * 1000))
        else:
            self.barra_fase.setValue(0)     # fase sin duracion (detenida)
        self.etq_restante.setText(f"{s.restante_s:5.1f} s")
        self.etq_ciclo.setText(f"ciclo {s.ciclo}")

        # --- Bombas ---
        encendidas = 0
        deshabilitadas = 0
        for nombre, fila in self.filas_bomba.items():
            on = s.reles.get(nombre, False)
            habilitada = s.bombas_habilitadas.get(nombre, True)
            fila.actualizar(on, habilitada)
            encendidas += int(on)
            deshabilitadas += int(not habilitada)
        resumen = f"{encendidas} de {len(self.filas_bomba)} encendidas"
        if deshabilitadas:
            resumen += f" · {deshabilitadas} deshabilitada"
            if deshabilitadas > 1:
                resumen += "s"
        self.etq_resumen_bombas.setText(resumen)

        # --- Luminarias exteriores ---
        for nombre, fila in self.filas_luminaria.items():
            fila.actualizar(s.luminarias.get(nombre, False))

        # --- Semaforos ---
        for nombre, widget in self.widgets_semaforo.items():
            widget.set_luces(s.semaforos.get(nombre, {}))

        # --- Sensores de nivel ---
        # Se recorren las lecturas y no las filas, porque la lectura trae el
        # canal y con el se ubica la fila que le corresponde.
        for lectura in s.lecturas:
            fila = self.filas_sensor.get(lectura.canal)
            if fila is not None:
                fila.actualizar(lectura)

        # --- Tiras LED ---
        for nombre, widget in self.widgets_tira.items():
            widget.set_pixeles(s.tiras.get(nombre, []))

        velocidad = self._ctrl.tira_velocidad_ms()
        self.etq_velocidad.setText(f"{velocidad:3d} ms/LED")
        for nombre, muestra in self.muestras_color.items():
            r, g, b = s.tira_color.get(nombre, (0, 0, 0))
            muestra.setStyleSheet(
                f"background: rgb({r},{g},{b}); border: 1px solid {BORDE};"
                f" border-radius: 3px;"
            )
        if s.tiras_reales:
            fallidas = sorted(getattr(self._ctrl.tiras, "errores", {}))
            aviso = (f"sin iniciar: {', '.join(fallidas)} · ver el registro"
                     if fallidas else "")
        else:
            aviso = "tiras simuladas · ver el registro de eventos"
        self.etq_tiras_modo.setText(aviso)
        if aviso:
            self.etq_tiras_modo.setStyleSheet(f"color: {AMARILLO_ON.name()};")

        # --- Registro de eventos ---
        # Solo se reescribe si hay lineas nuevas. Sin esta comprobacion, cada
        # refresco reemplazaria el texto completo y la barra de desplazamiento
        # saltaria sin parar, haciendo imposible leer nada.
        if len(s.log) != self._ultimo_log:
            self.vista_log.setPlainText("\n".join(s.log))
            # Auto-desplazamiento al final, para que siempre se vea lo ultimo.
            self.vista_log.verticalScrollBar().setValue(
                self.vista_log.verticalScrollBar().maximum()
            )
            self._ultimo_log = len(s.log)

        # --- Botones: solo uno de los dos tiene sentido a la vez ---
        corriendo = self._ctrl.secuencia_activa()
        self.btn_iniciar.setEnabled(not corriendo)
        self.btn_detener.setEnabled(corriendo)

    # ----------------------------------------------------------------- cierre
    def closeEvent(self, evento) -> None:
        """Qt llama a esto al cerrar la ventana. Es la ultima oportunidad.

        Primero se para el temporizador y despues se cierra el controlador. Al
        reves, un refresco podria dispararse mientras los hilos se estan
        deteniendo y leer un estado a medio desarmar.
        """
        self._temporizador.stop()
        self._ctrl.cerrar()     # apaga bombas y semaforos, libera el GPIO
        evento.accept()
