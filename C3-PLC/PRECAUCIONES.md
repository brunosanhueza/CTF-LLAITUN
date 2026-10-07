# Precauciones y advertencias - Cuadrante 3

Recopilado el 2026-10-01 de `README.md` e `INSTALACION.md` (originales, en
`~/Desktop/cuadrante-3/`), los comentarios de `config.py`, `hal.py`,
`actuadores.py`, `controlador.py` y `main.py`, y lo que se aprendio en la
sesion de depuracion con el PLC. Lo marcado **[ESTIMADO]** es un calculo mio,
no un dato del proyecto. Antes de tocar la maqueta, leer esto.

## A. Para no quemar nada (hardware)

1. **Bombas: los dos canales de cada bomba SIEMPRE juntos.** Un canal conmuta
   +12 V y el otro el retorno. Moverlos por separado deja la bomba "a medio
   conectar" (un polo vivo). El software lo impide (`BancoReles` escribe el par
   en una sola llamada); **no manejar un pin de bomba suelto** con `pinctrl set`,
   `raspi-gpio`, un script de GPIO ni a mano.
2. **Los reles son activos en BAJO**: GPIO en LOW = bomba encendida; HIGH = apagada
   (estado seguro). Por eso los pines se configuran con `initial=HIGH` en el mismo
   `setup`, para que no haya un instante con la carga activa.
3. **Bombas en seco y rebalse.** La Pi NO limita el tiempo de bombeo ni tiene
   histeresis (el README lo deja pendiente: "agregar histeresis y tiempo maximo de
   bombeo si pasa de demostracion a operacion"). Las protecciones (nivel alto,
   `Override_Seguridad`, alarmas) viven en el PLC. No dejar una bomba encendida sin
   agua; el umbral critico del dashboard es 95 % (riesgo de rebalse). Con
   `Override_Seguridad` en TRUE el PLC puede saltarse sus interlocks.
4. **Tiras LED (WS2812B, 5 V).**
   - Tierra comun entre la Pi y la fuente de 5 V; cada tira lleva su condensador de
     1000 uF.
   - Conectar a J3 (T1) / J4 (T2): ya traen el nivel convertido a 5 V (SN74AHCT125N)
     y la resistencia serie de 330 ohm. **No agregar otra resistencia.**
   - `TIRA_BRILLO = 128`; el propio `config.py` avisa: "subirlo exige mas de la
     fuente de 5 V".
   - Consumo **[ESTIMADO]**: un WS2812B a blanco pleno pide hasta ~60 mA. Con
     `n_leds = 200` y brillo 128, **blanco puede pedir ~6 A por tira** (azul solo,
     ~2 A). No usar blanco ni mezclas a tira completa hasta conocer la capacidad de la
     fuente de 5 V. Ojo: el valor 7 de la tabla del PLC (`PLC_COLOR_TIRAS`) es Blanco.
5. **Luminarias L1/L2**: LED directos al GPIO con resistencia serie. Un GPIO entrega
   hasta ~16 mA; no conectar nada mas pesado. Encienden en ALTO (al reves que los
   reles).
6. **Semaforos**: activos en BAJO, confirmado en la maqueta. Si la prueba de luces
   muestra dos luces encendidas y una apagada, alguien cambio el cableado: revisar
   `SEMAFORO_ACTIVO_EN_BAJO` antes de conectar cargas.
7. **Pines que no se tocan**: GPIO 0 y 1 (EEPROM de HAT), GPIO 14/15 (consola serial).
   En I2C, `/dev/i2c-1` es el bueno; `i2c-20` e `i2c-21` son el DDC del HDMI.
8. **Canales DMA de las tiras**: solo 9, 10, 11, 13 o 14 (`TIRA_DMA = 10`). **Nunca
   0-4 ni 5**: el 5 comparte con la tarjeta SD en algunos modelos y puede
   corromperla.
9. **Pendiente de seguridad del informe de la tarjeta (paso 7)**: reiniciar la Pi y
   comprobar que **ningun rele se activa durante el arranque**. No se ha hecho.

## B. Para no romper el software ni el sistema

1. **Ejecutar con `sudo -E`**: sin `sudo` las tiras quedan simuladas
   (`ws2811_init fallo (-9): Failed to create mailbox device` = falta de permisos);
   sin `-E` no abre la ventana. Las bibliotecas se instalan con `sudo pip3` (la app
   corre como root).
2. **`/boot/firmware/config.txt`**: `dtparam=i2c_arm=on` y `dtparam=audio=off` son
   obligatorios (sin el segundo las tiras no encienden y no hay ningun error).
3. **El SPI debe estar deshabilitado.** El INSTALACION.md dice que no deben estar ni
   `dtparam=spi=on` ni `dtoverlay=spi0-1cs`: el kernel puede tomar GPIO 9 y 11 (las
   luminarias) y GPIO 7 (un canal de la bomba 2) y la salida **no conmuta, sin
   ningun error**. **Estado actual de la Pi: `dtoverlay=spi0-1cs` esta en la seccion
   `[all]` y existe `/dev/spidev0.0`.** `nospi10` esta en `[pi5]` y no aplica a esta
   Pi 4. Observacion: `pinctrl` muestra GPIO 7, 9 y 11 como salida, asi que RPi.GPIO
   si los tomo; falta probar fisicamente las luminarias. Quitar el overlay implica
   editar `config.txt` y reiniciar: lo decide y lo hace quien administra la Pi.
4. **Largo de las tiras**: `TIRA_N_LEDS_MAX = 200` se reserva una sola vez al
   arrancar; `n_leds` es el largo logico (1-200). No reinicializar DMA en caliente
   (causa cuelgues); subir de 200 exige reiniciar el programa.
5. **Las dos tiras comparten UNA sola instancia `ws2811_t`**. No volver a montar dos
   objetos `PixelStrip`: la segunda inicializacion deja muda a la primera.
6. **Semaforos**: el rojo debe durar lo mismo que verde + amarillo y el desfase debe
   ser medio ciclo, o los dos daran paso a la vez.
7. **Sensores**: en hardware real nunca se cae al simulador; sin calibrar
   `DISTANCIA_ESTANQUE_VACIO_MM` / `LLENO_MM` la barra queda siempre llena o vacia.
8. **Cierre seguro**: `Controlador.cerrar()` es idempotente y apaga bombas y
   luminarias en un `finally`. No cambiar el orden (parar hilos -> apagar salidas ->
   liberar GPIO).
9. **Copiar el proyecto**: `scp -r` sobrescribe pero **no borra** archivos viejos, y
   copiar `cuadrante-3` encima de `C3-PLC` borraria el puente PLC y los cambios de la
   sesion. Antes, backup (ver `CAMBIOS.md`).
10. **Solo un proceso a la vez** usa las tiras (`main.py` o `solo_tiras.py`) y solo uno
    usa el bus I2C (`main.py` o `mapa_sensores.py`).

## C. Con el PLC (Modbus)

1. **El PLC admite UNA sola conexion Modbus.** Con `main.py` corriendo, otros clientes
   (scripts de prueba, otra consola) son rechazados, y abrir una segunda conexion puede
   cortar el puente. Si el puente pierde al PLC y `PLC_MODO_FALLO = "apagar"`, las 4
   bombas se apagan hasta reconectar (es el comportamiento seguro, no un error).
2. **`PLC_MODO_FALLO = "mantener"` solo para pruebas de banco**: deja las bombas como
   estaban si se cae el PLC.
3. **La Pi solo escribe** `HR21...` (raw de los estanques), `HR40` (watchdog) y `HR41`
   (codigo de error). No escribir otros registros desde scripts: `prueba_plc.py
   --escribir-raw` / `--latir` escriben en el PLC; no usarlos durante una prueba o
   competencia.
4. **Toda la logica de seguridad vive en el PLC** (interlocks, override, alarmas, las
   4 flags). La Pi es deliberadamente "tonta": ejecuta lo que el PLC manda.
5. **Bits de HR0 en el byte alto** (bombas 9/11/13/15, sensores 8/10/12/14). Si el DB4
   cambia, este es el unico lugar que hay que actualizar (`config.py`).
6. **Calibracion por tanque (FB3 `ScaleSensores`)**: el mapa sensor-estanque se corrigio
   el 2026-10-01; confirmar en TIA que la escala de cada tanque coincide con el nuevo
   orden (ver `CAMBIOS.md`).

## D. Como trabaja Claude en esta maqueta (reglas acordadas)

- Backup antes de editar; registro en `CAMBIOS.md`.
- Modbus **solo lectura**, una conexion a la vez y solo con `main.py` cerrado.
- Nunca escribe en los GPIO de bombas o reles; solo lee estados (`pinctrl get`).
- No modifica `config.txt`, el arranque ni credenciales; eso lo hace el usuario.
- Lo fisico (tiras, luces, bombas) lo lanza el usuario mirando la maqueta.
