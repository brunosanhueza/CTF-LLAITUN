"""
Configuracion del CUADRANTE 3 - sistema hidraulico.

Todos los pines siguen el mapa de la tarjeta de control de cuadrante v1.0.0
(ver informe_tarjeta_maqueta.pdf, seccion "Resumen de pines del conector GPIO").
La numeracion es BCM, es decir el numero de GPIO, no el numero de pin fisico.

Este archivo es el UNICO lugar donde deberian tocarse pines, direcciones y
tiempos. El resto de los modulos lo importa.
"""

# =============================================================================
#  RELES  -  4 bombas de 12 V, DOS canales por bomba
# =============================================================================
# La tarjeta expone ocho canales de rele, repartidos de a dos por bornera:
#
#   canal 1  GPIO 4    J7      canal 5  GPIO 27   J13
#   canal 2  GPIO 5    J7      canal 6  GPIO 19   J13
#   canal 3  GPIO 6    J10     canal 7  GPIO 26   J16
#   canal 4  GPIO 7    J10     canal 8  GPIO 12   J16
#
# Cada bomba usa LOS DOS canales de su bornera: uno conmuta el polo de +12 V y
# el otro el retorno (GND), de modo que la bomba queda totalmente desconectada
# cuando esta apagada, sin corrientes de fuga por el retorno comun. Los dos
# canales se mueven SIEMPRE juntos; moverlos por separado dejaria la bomba a
# medio conectar, con un polo vivo y el otro no.
#
# Con eso las cuatro bombas ocupan los ocho canales y no queda ninguno libre en
# la tarjeta: las luminarias van aparte, como LED directos al GPIO (ver mas
# abajo).
#
# Los modulos comerciales son OPTOACOPLADOS Y ACTIVOS EN BAJO:
#   GPIO en LOW  -> rele activado (carga encendida)
#   GPIO en HIGH -> rele apagado  (estado seguro)

RELE_ACTIVO_EN_BAJO = True

# "pines" es una LISTA a proposito, aunque casi siempre tenga dos elementos: es
# lo que permite que BancoReles maneje igual una bomba de dos canales y una
# luminaria de un solo pin, sin ramas ni casos especiales.
RELES = {
    "P1": {"pines": [4, 5],   "canales": [1, 2], "bornera": "J7",
           "etiqueta": "Bomba 1"},
    "P2": {"pines": [6, 7],   "canales": [3, 4], "bornera": "J10",
           "etiqueta": "Bomba 2"},
    "P3": {"pines": [27, 19], "canales": [5, 6], "bornera": "J13",
           "etiqueta": "Bomba 3"},
    "P4": {"pines": [26, 12], "canales": [7, 8], "bornera": "J16",
           "etiqueta": "Bomba 4"},
}

# =============================================================================
#  LUMINARIAS  -  dos LED directos al GPIO, encendido manual
# =============================================================================
# No participan de la secuencia de bombas: se encienden y se apagan a mano
# desde la interfaz, cada una con su boton, y se quedan como las dejaron.
#
# Como los ocho canales de rele de la tarjeta se los llevan las bombas, las
# luminarias son LED SENCILLOS cableados directamente a dos lineas del header
# del SPI0 (con su resistencia serie; un GPIO entrega hasta ~16 mA):
#
#   L1  GPIO9   pin fisico 21   (MISO del diseno)
#   L2  GPIO11  pin fisico 23   (SCLK del diseno)
#
# RESPECTO AL DISENO DE LA PLACA
#   El informe tecnico reserva el header U$5 como puerto de expansion SPI. Este
#   cuadrante no usa SPI, asi que dos de sus lineas se reutilizan como GPIO
#   corrientes para los LED. (Antes hubo UNA luminaria en un rele suelto en
#   GPIO10/MOSI; se recableo a esto.)
#
# OJO - EL SPI TIENE QUE ESTAR DESHABILITADO
#   GPIO9 y GPIO11 son las lineas MISO y SCLK de SPI0. Si "dtparam=spi=on" esta
#   en /boot/firmware/config.txt, el driver del kernel toma esos pines y
#   RPi.GPIO no los puede manejar: los LED no encienden y NO aparece ningun
#   mensaje de error. Comprobar con:  ls /dev/spidev*  (no debe existir ninguno)

LUMINARIAS = {
    "L1": {"pines": [9],  "gpio": 9,  "pin_fisico": 21, "senal": "SPI0 MISO",
           "bornera": "header U$5", "etiqueta": "Luminaria exterior 1"},
    "L2": {"pines": [11], "gpio": 11, "pin_fisico": 23, "senal": "SPI0 SCLK",
           "bornera": "header U$5", "etiqueta": "Luminaria exterior 2"},
}

# POLARIDAD DE LAS LUMINARIAS, distinta de la de los reles.
#   Los modulos de rele son activos en BAJO, pero estos LED van directos al
#   GPIO con el catodo a tierra: encienden con el pin en ALTO. Por eso tienen
#   su propia constante y no usan RELE_ACTIVO_EN_BAJO.
#   Si se cablearan al reves (anodo al 3.3 V, GPIO como retorno), poner True.
LUMINARIA_ACTIVO_EN_BAJO = False

# Estado con el que arrancan. False = apagadas, que es el estado seguro y el
# que fija el propio setup(initial=...).
LUMINARIA_ENCENDIDA_AL_INICIO = False

# =============================================================================
#  SEMAFOROS  -  2 semaforos de tres luces
# =============================================================================
# OJO: la placa lleva las lineas de GPIO directo a la bornera, sin inversor.
# Si el semaforo esta cableado en CATODO COMUN (retorno a GND), enciende con
# el GPIO en HIGH y hay que poner SEMAFORO_ACTIVO_EN_BAJO = False.
# Si esta cableado en ANODO COMUN (retorno a 3.3 V), enciende con el GPIO en
# LOW y corresponde dejarlo en True, como esta ahora.
#
# CONFIRMADO EN LA MAQUETA: los semaforos reales son ACTIVOS EN BAJO. Si algun
# dia la prueba de luces del arranque muestra dos luces encendidas y una
# apagada, alguien cambio el cableado y hay que revisar esto.
SEMAFORO_ACTIVO_EN_BAJO = True

SEMAFOROS = {
    "TL1": {"rojo": 22, "amarillo": 23, "verde": 24, "bornera": "J2",
            "etiqueta": "Semaforo 1"},
    "TL2": {"rojo": 16, "amarillo": 20, "verde": 21, "bornera": "J1",
            "etiqueta": "Semaforo 2"},
}

# Secuencia de calle: verde -> amarillo -> rojo, en bucle infinito.
# La suma de las duraciones es el periodo del ciclo (aqui 16 s).
#
# Para que los dos semaforos formen un cruce coherente, el rojo debe durar lo
# mismo que verde + amarillo (aqui 6 + 2 = 8 s) y el desfase debe ser la mitad
# del ciclo. Con eso nunca hay dos verdes a la vez ni un verde contra un
# amarillo: mientras uno avanza, el otro esta detenido.
SEMAFORO_SECUENCIA = [
    ("verde", 6.0),
    ("amarillo", 2.0),
    ("rojo", 8.0),
]

# Desfase de cada semaforo dentro del ciclo, en segundos.
SEMAFORO_DESFASE_S = {
    "TL1": 0.0,
    "TL2": 8.0,      # medio ciclo
}

SEMAFORO_PERIODO_ACTUALIZACION_S = 0.1   # resolucion del temporizador

# =============================================================================
#  SENSORES  -  4 x VL53L0X detras del multiplexor TCA9548A
# =============================================================================
# Los cuatro VL53L0X salen de fabrica con la MISMA direccion (0x29) y no se
# puede cambiar de forma persistente. Por eso cada uno va en su propio canal
# del TCA9548A: el multiplexor abre un solo canal a la vez, de modo que en el
# bus solo hay un 0x29 visible en cada transaccion.

MUX_DIRECCION = 0x70        # A0/A1/A2 a GND
MUX_RESET_GPIO = 17         # linea RST del mux, con pull-up de 10k en placa
VL53L0X_DIRECCION = 0x29    # direccion de fabrica, igual en los cuatro

# MAPA REAL sensor -> estanque, medido con mapa_sensores.py el 2026-10-01 (mano
# sobre cada sensor). "Estanque N" es el N del PLC: sus datos van a
# Escalamiento_Sensores[2*(N-1)] (raw) y [2*(N-1)+1] (%). Etiqueta y rele deben
# llevar siempre el mismo N. canal -> bornera es fijo por hardware (J18+canal).
SENSORES = [
    {"canal": 0, "bornera": "J18", "etiqueta": "Estanque 2", "rele": "P2"},
    {"canal": 1, "bornera": "J19", "etiqueta": "Estanque 4", "rele": "P4"},
    {"canal": 2, "bornera": "J20", "etiqueta": "Estanque 1", "rele": "P1"},
    {"canal": 3, "bornera": "J21", "etiqueta": "Estanque 3", "rele": "P3"},
]

# Geometria del estanque: que distancia mide el sensor con el estanque vacio y
# con el estanque lleno. De ahi sale el porcentaje que muestra la barra.
#
# Tal como esta ahora, MAS distancia = MAS agua: 0 mm es vacio y 40 mm es lleno.
#
# La formula (ver hal.distancia_a_nivel_pct) funciona en los dos sentidos, asi
# que basta con poner en cada constante lo que el sensor lee de verdad. Si algun
# dia se monta el sensor arriba mirando hacia abajo, donde mas distancia
# significa menos agua, se intercambian los dos numeros y listo:
#   VACIO = 300, LLENO = 50   ->  sensor en la tapa, mide hasta la superficie
DISTANCIA_ESTANQUE_VACIO_MM = 0     # lectura con el estanque vacio
DISTANCIA_ESTANQUE_LLENO_MM = 40    # lectura con el estanque lleno

# Umbrales para colorear la barra de nivel en la interfaz (en % de llenado)
NIVEL_ALERTA_PCT = 80.0    # ambar por sobre este valor
NIVEL_CRITICO_PCT = 95.0   # rojo por sobre este valor (riesgo de rebalse)

PERIODO_MUESTREO_S = 0.5   # cada cuanto se leen los cuatro sensores

# Cada cuanto se vuelve a buscar un sensor que estaba desconectado. Permite
# enchufar un VL53L0X con el software corriendo y que aparezca solo.
PERIODO_REDETECCION_S = 3.0

# Lecturas fallidas seguidas antes de dar un sensor por desconectado. Evita que
# un glitch puntual del bus marque el sensor como ausente.
FALLOS_PARA_DESCONECTAR = 3

# Canales que el SIMULADOR considera conectados. Solo afecta al modo simulacion
# (--simular); en la Raspberry Pi la deteccion es real. Dejarlo en [] permite
# probar en el PC como se ve la interfaz sin ningun sensor enchufado.
SIMULAR_CANALES_CONECTADOS = [0, 1, 2, 3]

# =============================================================================
#  TIRAS LED DIRECCIONABLES  -  2 x WS2812B
# =============================================================================
# La senal sale por PWM0 (GPIO18) y PWM1 (GPIO13) y el SN74AHCT125N la eleva de
# 3.3 V a 5 V. Cada tira se alimenta desde EXT_5V con su condensador de 1000 uF.
#
# El informe de la tarjeta habla de SK6812 porque es lo que se especifico al
# disenar la placa. Las tiras montadas son WS2812B, que es electricamente
# equivalente: misma trama de 800 kHz, mismo nivel de 5 V y mismo orden GRB, asi
# que la placa sirve igual sin ningun cambio.
#
# OJO: la biblioteca rpi_ws281x accede directo a DMA y PWM, asi que el programa
# debe correr como root (sudo). Si no puede, el software cae a tiras simuladas
# y lo avisa en la interfaz; todo lo demas sigue funcionando igual.

# Las dos tiras comparten UNA sola instancia de ws2811 (ver hal.py): PWM0 y PWM1
# son canales de un mismo periferico, y montarlas como dos objetos PixelStrip
# separados hace que la segunda inicializacion deje muda a la primera. Por eso
# aqui solo se declara el canal PWM de cada una; el DMA es uno para las dos.
# PROVISIONAL: n_leds = 200 (el maximo del buffer). Con 100 el llenado se cortaba
# antes del final, asi que las tiras fisicas tienen mas de 100 LED. Cuando se
# sepa el largo real de cada una, poner aqui ese numero (T1 y T2 pueden ser
# distintos): con 200 la animacion sigue "llenando" LED que no existen.
TIRAS = {
    "T1": {"gpio": 18, "canal_pwm": 0, "n_leds": 200,
           "bornera": "J3", "etiqueta": "Estanques"},
    "T2": {"gpio": 13, "canal_pwm": 1, "n_leds": 200,
           "bornera": "J4", "etiqueta": "Edificios"},
}

# Cantidad MAXIMA de LED que se reserva por tira al arrancar.
#
# El numero de LED de cada tira se ajusta desde la interfaz, pero rpi_ws281x fija
# el tamano del buffer al construir el objeto y reinicializar DMA en caliente es
# una fuente conocida de cuelgues. Por eso se reserva el maximo una sola vez y el
# valor de la interfaz actua como longitud LOGICA: los LED que sobran se escriben
# siempre apagados. Cambiar este maximo si exige reiniciar el programa.
TIRA_N_LEDS_MAX = 200

# Orden de bytes de la tira. El WS2812B es GRB, igual que el SK6812.
# Se declara explicitamente en vez de confiar en el valor por omision de
# rpi_ws281x: si los colores salen cambiados (p.ej. el azul se ve rojo), el
# problema esta aqui y no en el cableado. Alternativas usuales:
#   WS2811_STRIP_GRB (WS2812B, SK6812)   WS2811_STRIP_RGB   WS2811_STRIP_BRG
TIRA_TIPO = "WS2811_STRIP_GRB"

TIRA_FRECUENCIA_HZ = 800000
# Canal DMA compartido por las dos tiras. Seguros: 9, 10, 11, 13, 14.
# NO usar 0-4 (los ocupa el sistema) ni el 5, que en algunos modelos comparte
# con la tarjeta SD y puede corromperla.
TIRA_DMA = 10
TIRA_BRILLO = 128          # 0 a 255. Subirlo exige mas de la fuente de 5 V.
TIRA_INVERTIR = False

# Animacion: los LED se van encendiendo en fila hasta llenar la tira, luego se
# apaga y vuelve a empezar.
TIRA_COLOR_INICIAL = (0, 0, 255)     # azul
TIRA_VELOCIDAD_INICIAL_MS = 60       # milisegundos por LED
TIRA_VELOCIDAD_MIN_MS = 10           # mas rapido
TIRA_VELOCIDAD_MAX_MS = 300          # mas lento
TIRA_PASO_VELOCIDAD_MS = 10
TIRA_PAUSA_LLENA_MS = 400            # cuanto queda llena antes de reiniciar

# Colores que ofrece el boton de la interfaz, en orden.
TIRA_COLORES = [
    ("Azul",     (0, 0, 255)),
    ("Cian",     (0, 200, 255)),
    ("Blanco",   (255, 255, 255)),
    ("Verde",    (0, 255, 0)),
    ("Ambar",    (255, 140, 0)),
    ("Rojo",     (255, 0, 0)),
    ("Magenta",  (255, 0, 200)),
]

# =============================================================================
#  SECUENCIA DE PRUEBA
# =============================================================================
# Ciclo infinito de cuatro fases:
#   1. ENCENDIDO  - se activan las bombas de a una, cada T_PASO_ENCENDIDO_S
#   2. SOSTENIDO  - las cuatro quedan encendidas durante T_SOSTENIDO_S
#   3. APAGADO    - se apagan de a una, cada T_PASO_APAGADO_S
#   4. APAGADAS   - las cuatro quedan apagadas durante T_APAGADAS_S
# y vuelve a empezar.

T_PASO_ENCENDIDO_S = 1.0
T_SOSTENIDO_S = 120.0          # dos minutos con las cuatro encendidas
T_PASO_APAGADO_S = 1.0
T_APAGADAS_S = 30.0            # reposo con las cuatro apagadas

ORDEN_ENCENDIDO = ["P1", "P2", "P3", "P4"]
ORDEN_APAGADO = ["P1", "P2", "P3", "P4"]

# Rangos que acepta la interfaz para esos tiempos. Los valores de arriba son
# solo el punto de partida: desde el dashboard se pueden cambiar en caliente.
T_PASO_MIN_S, T_PASO_MAX_S = 0.1, 30.0
T_SOSTENIDO_MIN_S, T_SOSTENIDO_MAX_S = 1.0, 900.0
T_APAGADAS_MIN_S, T_APAGADAS_MAX_S = 0.0, 900.0

# =============================================================================
#  PUENTE MODBUS CON EL PLC  (Sector 3 - CTF SmartCity)
# =============================================================================
# La Raspberry Pi es CLIENTE Modbus TCP; el PLC (S7-1215C, bloque MB_SERVER)
# es el que expone el servidor en el puerto 502, sin autenticacion (por
# diseno del CTF). Este puente NO decide nada por cuenta propia: obedece lo
# que el PLC manda en los bits de Comando_BombaN y le informa al PLC lo que
# los sensores reales estan midiendo. Toda la logica de seguridad (interlocks,
# override, alarmas, las 4 flags) vive DENTRO del PLC, nunca aqui - a
# proposito, para que el CTF sea sobre atacar el PLC y no sobre atacar esta
# Raspberry Pi.
#
# Este archivo es el UNICO lugar donde deberian tocarse direcciones de
# registro Modbus. plc_bridge.py lo importa, igual que hal.py hace con los
# pines de GPIO.

PLC_IP = "10.10.30.100"        # Confirmado: responde ping desde la Pi y acepta
                                # Modbus TCP en el 502. (10.10.70.100 era una IP
                                # candidata antigua, ya descartada.)
PLC_PUERTO = 502
PLC_TIMEOUT_S = 2.0            # timeout de cada lectura/escritura Modbus
PLC_PERIODO_S = 0.3            # cada cuanto se hace un ciclo completo
PLC_PERIODO_RECONEXION_S = 3.0 # cada cuanto se reintenta si el PLC no responde

# --- Mapa de registros, DB4 "CTF_ModBus" (offset en bytes / 2 = numero de HR)
# Confirmado contra las propiedades del DB4 en TIA Portal. Si el DB4 cambia,
# este es el UNICO lugar que hay que actualizar de este lado.
PLC_HR_ESTADO = 0               # Word: bits de sensores/bombas 1-4, empaquetados
PLC_HR_COLOR_LED_FLAG4 = 10     # Int: lo escribe el PLC (efecto fisico Flag 4)
PLC_HR_ESCALAMIENTO = 21        # Array[0..8] de Int: raw/pct x 4 tanques + 1 libre
PLC_HR_WATCHDOG_STATUS = 39     # Word: lo escribe el PLC, este puente solo lo lee
PLC_HR_WATCHDOG_COMMS = 40      # Word: contador que este puente incrementa
PLC_HR_WATCHDOG_ERRCODE = 41    # Word: 0 = sin novedad; distinto de 0 = aviso

# Bits de PLC_HR_ESTADO (0 = bit menos significativo del Word).
# CONFIRMADO POR MODBUS contra el PLC fisico (S7-1215C), no solo contra la tabla
# del DB4: S7 es big-endian, asi que el byte 0 del DB (DBX0.0-0.7) llega como el
# BYTE ALTO del HR0, es decir DBX0.n -> bit 8+n. Sensor_Nivel_Alto1-4 en los
# bits 8/10/12/14 y Comando_Bomba1-4 en los 9/11/13/15. Se verifico forzando
# Comando_Bomba2 en TIA: HR0 paso de 0x4600 a 0x4E00 (bit 11).
# Buscar los bits 0-7 (convencion anterior) deja las bombas siempre apagadas.
PLC_BIT_SENSOR_ALTO = {"P1": 8, "P2": 10, "P3": 12, "P4": 14}
PLC_BIT_COMANDO_BOMBA = {"P1": 9, "P2": 11, "P3": 13, "P4": 15}

# Indice, dentro del array Escalamiento_Sensores, del elemento RAW (en mm) de
# cada tanque. El elemento siguiente (indice+1) es el nivel ya escalado a %:
# lo calcula el PLC en FB3 "ScaleSensores" con su propia calibracion, y esta
# Raspberry Pi NUNCA lo escribe ni necesita leerlo (ya tiene su propio % local
# via hal.distancia_a_nivel_pct, para la interfaz). El indice 8 del array
# queda libre/reservado.
PLC_INDICE_RAW = {"P1": 0, "P2": 2, "P3": 4, "P4": 6}

# Que hacer con las bombas si se pierde la conexion Modbus con el PLC:
#   "apagar"    -> failsafe: las cuatro bombas se apagan hasta reconectar
#   "mantener"  -> se quedan como estaban (arriesga que sigan encendidas
#                  a ciegas; NO recomendado salvo para pruebas puntuales)
PLC_MODO_FALLO = "apagar"

# Que luminarias enciende un Color_LED_Flag4 distinto de cero (efecto fisico
# de la Flag 4, "Modo Fiesta"). No se interpreta el numero como un color en
# particular todavia: alcanza con que sea distinto de 0 para encender ambas.
PLC_LUMINARIAS_FIESTA = ["L1", "L2"]

# Color de las TIRAS LED segun Color_LED_Flag4 (HR10, Int, offset 20 del DB4).
# El PLC escribe un numero y el puente pinta las dos tiras de ese color:
#     0            -> sin orden del PLC: las tiras vuelven al color local
#     1 a 7        -> el color de esta tabla
#     cualquier otro -> sin color asignado: las tiras no cambian (queda en el log)
# Los nombres tienen que existir en TIRA_COLORES. Es independiente de
# PLC_LUMINARIAS_FIESTA: cualquier valor distinto de 0 sigue encendiendo L1 y L2.
# Por ahora el color es GLOBAL (las dos tiras iguales); mas adelante se puede
# separar por zona/departamento con un registro por zona.
#
# QUE TIRA ES QUE ZONA (confirmado mirando la maqueta con solo_tiras.py --regla):
#   T1 = Estanques (GPIO18, J3)      T2 = Edificios (GPIO13, J4)
#
# DE QUE REGISTRO TOMA EL COLOR CADA TIRA. Hoy las dos leen el mismo, HR10
# (Color_LED_Flag4), asi que se pintan juntas. Para separarlas, crear un tag
# nuevo por zona en el DB4 y poner aqui su numero de HR (offset en bytes / 2):
# no hay que tocar nada mas. No usar un HR que ya tenga otro dueno (0, 10, 11,
# 21-28, 39-41 estan ocupados).
PLC_HR_COLOR_TIRAS = {
    "T1": 10,     # Estanques
    "T2": 10,     # Edificios
}

PLC_COLOR_TIRAS = {
    1: "Rojo",
    2: "Verde",
    3: "Azul",
    4: "Ambar",
    5: "Cian",
    6: "Magenta",
    7: "Blanco",
}

# =============================================================================
#  INTERFAZ
# =============================================================================
CUADRANTE = 3
NOMBRE_CUADRANTE = "Cuadrante 3 · Sistema hidráulico"
REFRESCO_GUI_MS = 200      # 5 Hz: suficiente y no carga la Raspberry Pi
MAX_LINEAS_LOG = 200
