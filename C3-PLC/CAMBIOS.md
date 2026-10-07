# Cambios del cuadrante 3 (C3-PLC) - 1 de octubre de 2026

Sesion de depuracion Raspberry Pi <-> PLC. Este archivo esta en la Pi
(`~/Desktop/C3-PLC/CAMBIOS.md`) y en la copia local; son identicos.

## Problema y causa raiz

Al forzar `Comando_BombaN` en TIA Portal las bombas no se movian. El programa
antiguo (`~/Desktop/cuadrante-3`) "funcionaba" solo porque no tenia nada de
Modbus: la secuencia local de demostracion encendia las bombas sola.

La causa era el **mapeo de bits de HR0**. S7 es big-endian: el byte 0 del DB
(`DBX0.n`) llega por Modbus como el **byte alto** del registro, o sea el bit
`8+n`. `config.py` buscaba los bits 1/3/5/7 en vez de 9/11/13/15, asi que el
puente veia siempre las bombas apagadas. Se verifico forzando `Comando_Bomba2`
en TIA: HR0 paso de `0x4600` a `0x4E00` (bit 11).

## Archivos modificados o nuevos

| Archivo | Cambio |
|---|---|
| `config.py` | Bits de HR0 corregidos; `PLC_IP`; tiras con nombre de zona y `n_leds` provisional; tablas de color por PLC |
| `plc_bridge.py` | Color de tiras segun registros del PLC, por zona |
| `controlador.py` | Le pasa `Parametros` al hilo del PLC |
| `dashboard.py` | La fila de cada tira muestra su zona |
| `solo_tiras.py` (nuevo) | Solo las tiras LED, modo `--regla` para contar LED y RGB dinamico en Edificios |
| `mapa_sensores.py` (nuevo) | Descubre en que estanque esta cada sensor |
| `CAMBIOS.md` (nuevo) | Este archivo |

`actuadores.py`, `hal.py`, `secuencia.py`, `estado.py`, `parametros.py`,
`main.py` y los `prueba_*.py` NO se tocaron.

**Antes de tocar la maqueta leer `PRECAUCIONES.md`** (advertencias de los
documentos originales y de esta sesion, para no quemar ni romper nada).

## Detalle de los cambios

### 1. Bits de HR0 (`config.py`)
```python
PLC_BIT_SENSOR_ALTO   = {"P1": 8,  "P2": 10, "P3": 12, "P4": 14}   # antes 0/2/4/6
PLC_BIT_COMANDO_BOMBA = {"P1": 9,  "P2": 11, "P3": 13, "P4": 15}   # antes 1/3/5/7
```
El comentario del archivo se corrigio (decia "bits 0-7 confirmados"; se habia
confirmado contra la tabla del DB, no contra lo que viaja por Modbus).

### 2. IP del PLC (`config.py`)
`PLC_IP = "10.10.30.100"`. La Pi ya la tenia asi; la copia local tenia la
antigua `10.10.70.100`.

### 3. Color de las tiras desde el PLC (`plc_bridge.py`, `config.py`)
El puente lee un registro de color por tira y la pinta. Antes `Color_LED_Flag4`
solo encendia las luminarias L1 y L2 (eso se mantiene: cualquier valor distinto
de 0 las enciende).

| Valor | Color |
|---|---|
| 0 | el PLC suelta la tira: vuelve al color local |
| 1 | Rojo |
| 2 | Verde |
| 3 | Azul |
| 4 | Ambar |
| 5 | Cian |
| 6 | Magenta |
| 7 | Blanco |
| otro | sin color asignado: no cambia, queda en el log (hoy el PLC tiene 144) |

- Solo actua cuando el valor CAMBIA (no pisa un cambio hecho a mano en el
  dashboard cada 0,3 s ni llena el log).
- Cada tira guarda su propio color local para restaurarlo al llegar a 0.
- Zonas, confirmadas mirando la maqueta con `--regla`:
  **T1 = Estanques** (GPIO18, J3, azul/blanco) y
  **T2 = Edificios** (GPIO13, J4, verde/amarillo).
- `PLC_HR_COLOR_TIRAS = {"T1": 10, "T2": 10}`: hoy las dos leen HR10
  (`Color_LED_Flag4`, Int, offset 20) y se pintan juntas. Para separarlas se crea
  un tag por zona en el DB4 y se cambia ese numero. HR ocupados: 0, 10, 11,
  21-28, 39-41.

### 4. Largo de las tiras (`config.py`)
`n_leds` de T1 y T2 pasaron de 100 a **200, de forma PROVISIONAL**. Con 100 el
llenado se cortaba antes del final: las tiras fisicas tienen mas de 100 LED
(con `solo_tiras.py --leds 200` llenaban completo). Hay que reemplazarlo por el
largo real de cada tira (pueden ser distintos). Con 200 la animacion sigue
"llenando" LED que no existen.

### 5. `solo_tiras.py` (nuevo)
Arranca unicamente el hilo de tiras: sin bombas, luminarias, semaforos,
sensores, PLC ni ventana. Sirve por SSH. Necesita root y `main.py` cerrado.
```bash
cd ~/Desktop/C3-PLC && sudo python3 solo_tiras.py                    # animacion de llenado
sudo python3 solo_tiras.py --color Verde --velocidad 30 --leds 60
sudo python3 solo_tiras.py --regla                                   # para contar LED
```
`--regla`: todos los LED en tenue, marca cada 10 y rojo cada 50.
T1 = azul con marcas blancas; T2 = verde con marcas amarillas.

**Modo fiesta (SOLO PARA TESTEAR, solo en este script):** `--fiesta` hace flashear
las dos tiras completas con colores vivos al azar (HSV, tono aleatorio por tira,
saturacion y brillo al maximo), cada una por su lado, cambiando cada
`--periodo-fiesta` ms (150 por omision, minimo 20). Bypasea HiloTiras/Parametros
por completo: no toca main.py ni el puente PLC. Backup previo:
`solo_tiras.py.pre-fiesta` en la Pi.
```bash
sudo python3 solo_tiras.py --fiesta
sudo python3 solo_tiras.py --fiesta --periodo-fiesta 80   # mas rapido
```

**RGB dinamico de Edificios (solo en este script):** Estanques (T1) usa el color
de config y Edificios (T2) gira de tono sin parar mientras se llena
(`_rgb_dinamico`, un hilo que actualiza el color en `Parametros`; `HiloTiras` lo
relee en cada paso). No afecta a `main.py` ni al puente PLC.
```bash
sudo python3 solo_tiras.py --periodo-rgb 3     # vuelta de color cada 3 s (por omision 8)
sudo python3 solo_tiras.py --sin-rgb           # Edificios con color fijo
```
`--color X` aplica a Estanques; a Edificios solo si se usa `--sin-rgb`.

### 6. Mapa de sensores a estanques (`mapa_sensores.py`, nuevo)
Problema: en TIA, `Escalamiento_Sensores[0],[1]` deberian ser del estanque 1,
`[2],[3]` del 2, `[4],[5]` del 3 y `[6],[7]` del 4, pero los datos llegaban
cruzados. El puente NO tiene un bug: escribe exactamente lo que dice
`config.SENSORES` + `PLC_INDICE_RAW` (se comprobo: TIA `[0]=39`, `[2]=68`,
`[4]=131`, `[6]=151` calzaba con canal 1, 3, 0 y 2 leidos en ese momento). Lo
que falta es saber en que estanque esta realmente cada sensor.

- La Pi tiene un `SENSORES` editado a mano (despues de los backups de esta
  sesion; el backup `C3-PLC_final_*` mas reciente ya lo incluye): canal 0 ->
  P3, canal 1 -> P1, canal 2 -> P4, canal 3 -> P2, pero con la etiqueta en el
  orden original ("Estanque 1" para el canal 0) y las borneras en otro orden. Eso
  hace que el dashboard diga "Estanque 1" mientras el PLC lo recibe como tanque 3.
  Etiqueta y `rele` tienen que ser el mismo N (Estanque N <-> PN).
- `canal -> bornera` es fijo por hardware: 0=J18, 1=J19, 2=J20, 3=J21.
- Para averiguarlo, en la Pi y SIN `main.py` abierto:
  ```bash
  cd ~/Desktop/C3-PLC && python3 mapa_sensores.py
  ```
  Pide poner la mano sobre el sensor del estanque 1, 2, 3 y 4 y al final imprime
  el bloque `SENSORES` listo para pegar. NO modifica `config.py`. Con `--vivo`
  muestra las 4 lecturas en tiempo real.
- **Resultado (corrido en la maqueta, 2026-10-01) y tabla aplicada en `config.py`:**

  | Estanque | Canal (bornera) | Bomba | Registro PLC |
  |---|---|---|---|
  | 1 | 2 (J20) | P1 | `[0]` raw / `[1]` % (HR21) |
  | 2 | 0 (J18) | P2 | `[2]` / `[3]` (HR23) |
  | 3 | 3 (J21) | P3 | `[4]` / `[5]` (HR25) |
  | 4 | 1 (J19) | P4 | `[6]` / `[7]` (HR27) |

  Lecturas de reposo tras el cambio: Estanque 1 = 151 mm, 2 = 123, 3 = 61,
  4 = 39. Backups previos: `~/backups/C3-PLC_pre-sensores_20261001-135015.tar.gz`
  y `C3-PLC/config.py.pre-sensores` en la Pi.
- **ATENCION - calibracion del PLC:** antes del cambio, TIA mostraba raw 39, 68,
  131 y 151 en `[0]`, `[2]`, `[4]` y `[6]` con porcentajes sanos (99, 97, 91, 90).
  Eso sugiere que la calibracion por tanque del PLC (FB3 `ScaleSensores`) se ajusto
  al orden viejo. Con el mapa corregido, el PLC recibe valores en otro orden y sus
  porcentajes (`[1]`, `[3]`, `[5]`, `[7]`) saldran mal hasta recalibrar cada tanque en
  FB3 (inferido de los numeros; confirmar en TIA).
- El dashboard de la Pi usa UNA sola geometria para los cuatro estanques
  (`DISTANCIA_ESTANQUE_VACIO_MM = 0`, `LLENO = 40`), asi que los tanques con
  lecturas de >40 mm se ven al 100 %. Pendiente: geometria por estanque.

## Datos confirmados del sistema

- Pi `10.10.30.102` (usuario `ciberlab-c3`). PLC `10.10.30.100`, puerto 502.
- El PLC admite UNA sola conexion Modbus a la vez: con `main.py` corriendo,
  cualquier otro cliente (scripts, `prueba_plc.py`) es rechazado.
- Registros: HR0 estado/bombas (byte alto), HR10 `Color_LED_Flag4`,
  HR11 `Override_Seguridad`, HR21-28 raw/% de los 4 estanques,
  HR39 `Watchdog_Status` (lo escribe el PLC), HR40 `Watchdog_Comms`
  (contador que escribe la Pi cada ~0,3 s), HR41 `Watchdog_ErrCode`.
- Lanzar el programa completo (necesita escritorio; por SSH no abre ventana):
  `sudo -E DISPLAY=:0 python3 main.py --plc -v` desde la Pi, o por SSH:
  `export XDG_RUNTIME_DIR=/run/user/1000 && sudo -E env QT_QPA_PLATFORM=wayland WAYLAND_DISPLAY=wayland-0 python3 main.py --plc`
- Las bombas son de 12 V con relé todo o nada (sin PWM): el software no tiene
  ni conoce su potencia. Ver la etiqueta de cada bomba o medir en la bornera.

## Backups

En la Pi (`~/backups/`) y en el PC. Los nombres llevan la hora del PC; los
`ls` de la Pi muestran la hora de la Pi, que va ~19 h atrasada (sin NTP).

| Backup | Contenido |
|---|---|
| `~/backups/cuadrante-3_20261001-121617.tar.gz` | Programa antiguo completo (sin Modbus) |
| `~/backups/C3-PLC_20261001-121617.tar.gz` | C3-PLC ANTES de cualquier cambio |
| `~/Desktop/C3-PLC/config.py.bak` | `config.py` antes de corregir los bits |
| `~/backups/C3-PLC_pre-color_20261001-125917.tar.gz` | Con bits corregidos, antes del color por PLC |
| `~/backups/C3-PLC_pre-zonas_20261001-131846.tar.gz` | Antes de separar por zonas |
| `~/backups/C3-PLC_final_*.tar.gz` | Estado final de esta sesion (todo lo de arriba) |
| PC: `C3-PLC_backup_20261001-121617/` | Copia local original, antes de cualquier cambio |
| PC: `C3-PLC_final_*.tar.gz` | Estado final local |

Restaurar uno en la Pi (cambia `<archivo>`):
```bash
cd ~/Desktop && mv C3-PLC C3-PLC_descartado && tar -xzf ~/backups/<archivo>
```

## Pendiente

- Probar en la maqueta (solo se probo en simulacion, sin hardware): relanzar
  `main.py --plc` y poner `Color_LED_Flag4 = 1` en TIA; las tiras deben ponerse
  rojas y con 0 volver al color anterior.
- Largo real de cada tira, para reemplazar `n_leds = 200`.
- Tags de color por zona en el DB4 (offsets) y apuntar `PLC_HR_COLOR_TIRAS`.
- Separar mas fino, por LED de departamentos.
- Luminarias L1 y L2 (GPIO9/11): la Pi tiene SPI habilitado
  (`dtoverlay=spi0-1cs`, existe `/dev/spidev0.0`), que segun `config.py` puede
  impedir que enciendan. No se toco.
- Bomba 4 con flujo debil: el software la comanda igual que las otras (verificado
  con `pinctrl`); medir el voltaje en la bornera J16 con la bomba encendida.
- En TIA: la logica que reaccione si `Watchdog_Comms` deja de cambiar (por
  ejemplo un TON de ~3 s) vive en el PLC, no en la Pi.
