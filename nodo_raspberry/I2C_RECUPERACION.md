# Recuperacion del lector I2C

`rtu_daemon.py` inicia automaticamente `i2c_worker.py` mediante
`i2c_supervisor.py`. Hay un unico proceso lector. No hay que instalar ni
ejecutar un segundo servicio. Copiar los tres archivos juntos a la Raspberry,
ademas de la calibracion y las dependencias del proyecto.

El hijo importa las bibliotecas I2C y posee el bus, el TCA9548A y GPIO17 (RST).
El padre conserva bombas, luminarias, semaforos, DMA de las tiras y Modbus.
El hijo nunca ejecuta `GPIO.cleanup()` global. En Linux termina tambien si
muere el padre, mediante `PR_SET_PDEATHSIG`.

## Comportamiento

- Se conservan el mapa de sensores, la calibracion y el bypass de CH2/J20.
- Cada operacion debe producir progreso en menos de 8 segundos. Al excederlo,
  el supervisor solicita terminar al hijo, espera 0,5 s y escala a SIGKILL con
  otra espera de 0,5 s. Solo crea otro cuando ha recogido al anterior. Si el
  kernel no lo termina, queda degradado sin crear procesos adicionales.
- El canal en el que se bloqueo queda en cuarentena por 60 s. El nuevo hijo
  puede atender a los otros mientras tanto.
- Hay como maximo 3 arranques por ventana movil de 300 s, contando tambien
  intentos de arranque fallidos. Esperas entre intentos: 2, 4 y 8 segundos.
  Agotado el presupuesto, se espera hasta recuperar una plaza en la ventana.
- Antes de crear un sensor se busca su direccion 0x29 en el canal TCA, como en
  `C3-PLC/hal.py`. Si no aparece, ese canal se vuelve a buscar cada 3 s. Si el
  escaneo falla, se intenta igualmente el constructor del driver.
- Un error puntual de lectura se reintenta a los 0,5, 1 y 2 s. El objeto se
  conserva durante los dos primeros fallos y se recrea tras el tercero. Un
  fallo individual con otros sensores operativos no reinicia el bus entero.
- Sin ninguna lectura valida durante 15 s, se intenta resetear el MUX y
  reconstruir el bus; tambien se hace si nunca se pudo inicializar un sensor.
  Maximo 3 intentos de reset por ventana movil de 300 s por proceso lector. El reset inicial
  consume un intento. La espera crece hasta 60 s.
- Una medicion de mas de 4 s se marca OBSOLETO, aunque el hijo siga vivo.
  Se conserva el ultimo valor en memoria para diagnostico, con su timestamp.
- El control no espera al hijo: consume una copia de RAM y sigue enviando
  HR40 durante la recuperacion.

## Datos al PLC

HR21..HR28 mantienen el orden RAW/% por estanque. Un canal con dato invalido
no se escribe: conserva el ultimo valor publicado. HR41 vale 1 si falta algun
sensor habilitado o falla la escritura de telemetria, y 0 cuando todas esas
condiciones son correctas. El bypass intencional conserva su valor nominal.
Los bits de nivel alto de canales invalidos no se borran al actualizar HR0.

El PLC debe interpretar HR41 != 0 como dato de sensores no confiable. HR40
indica vida de comunicaciones, no salud de los sensores. No se ha cambiado la
logica de bombeo por fallo I2C: sigue a cargo del PLC. Verificar en TIA la
reaccion deseada antes de usar el sistema con agua. La web actual no lee HR41;
puede seguir mostrando el ultimo nivel hasta adaptar su telemetria.

Los fallos de lectura Modbus apagan las bombas, incluso en modo manual. El
cierre bloquea nuevas activaciones, detiene trabajadores y luego libera los
recursos. No se reinicializan tiras ni DMA durante una recuperacion I2C.

## Ejecucion y diagnostico

Desde `nodo_raspberry`, con el mismo entorno y permisos usados anteriormente:

```bash
python3 rtu_daemon.py --con-sensores
```

El modo normal muestra la tabla de barras al arrancar y cada 10 s. Para
refrescarla cada 2 s durante el diagnostico:

```bash
RTU_TELEMETRIA=1 python3 rtu_daemon.py --con-sensores
# Equivalente para diagnostico:
python3 test_daemon.py --con-sensores
```

`RTU_TELEMETRIA=0` desactiva esa tabla; un numero distinto de 0 configura el
intervalo en segundos. `--sin-sensores` sigue siendo una simulacion explicita:
no crea un lector.
No ejecutar a la vez `main.py`, calibradores ni otras herramientas I2C sobre
la maqueta. El supervisor evita duplicar sus propios hijos; no coordina con
programas externos.

## Verificacion sin hardware

Desde la raiz del repositorio:

```bash
python3 -m unittest discover -s nodo_raspberry/tests -v
```

Las pruebas usan GPIO/PLC falsos, un reloj virtual y procesos que se bloquean
o terminan deliberadamente. No conectan al PLC ni operan cargas fisicas.
Queda pendiente validar en Raspberry desconexion/reconexion real, RST de la
placa, versiones instaladas y recuperacion ante ruido/alimentacion. RST del
MUX aisla canales, pero no reinicia la alimentacion de los VL53L0X.
