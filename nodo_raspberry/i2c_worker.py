"""Proceso exclusivo de sensores. No importa el daemon ni controla cargas."""
import collections
from importlib import import_module
import json
import os
import signal
import sys
import threading
import time

SAMPLE_PERIOD_S = 0.5  # Igual que C3-PLC; el nivel del agua cambia lentamente.


def emit(kind, **values):
    print(json.dumps({"kind": kind, **values}), flush=True)


class SensorNoDetectadoError(RuntimeError):
    """No hay un VL53L0X con direccion 0x29 visible en el canal del mux."""


class BancoI2C:
    def __init__(self):
        import RPi.GPIO as GPIO
        import board
        import busio
        import adafruit_tca9548a
        from adafruit_vl53l0x import VL53L0X
        self.gpio, self.board, self.busio = GPIO, board, busio
        self.mux_class, self.sensor_class = adafruit_tca9548a.TCA9548A, VL53L0X
        self.sensor_modules = import_module("sensores-tof").SENSORES
        self.i2c = self.mux = None
        self.sensors = {}
        self._progress_callback = None
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

    def set_progress_callback(self, callback):
        """Permite informar al supervisor qué operación I2C está activa."""
        self._progress_callback = callback

    def _progress(self, channel, stage):
        if self._progress_callback is not None:
            self._progress_callback(channel, stage)

    def reset(self):
        # RST aisla los canales; no corta la alimentacion de los sensores.
        self.sensors.clear()
        old_i2c, self.i2c = self.i2c, None
        self.mux = None
        if old_i2c is not None:
            # Un deinit fallido no debe impedir recrear el bus y pulsar RST.
            try:
                old_i2c.deinit()
            except Exception:
                pass
        self.gpio.setup(17, self.gpio.OUT, initial=self.gpio.HIGH)
        self.gpio.output(17, self.gpio.LOW)
        time.sleep(0.03)
        self.gpio.output(17, self.gpio.HIGH)
        time.sleep(0.08)
        self.i2c = self.busio.I2C(self.board.SCL, self.board.SDA)
        self.mux = self.mux_class(self.i2c, address=0x70)

    def _sensor_presente(self, channel):
        """Busca 0x29 detras del canal antes de inicializar el sensor."""
        channel_bus = self.mux[channel]
        if not channel_bus.try_lock():
            # No iniciar otra transaccion si no se pudo tomar el bus: el
            # constructor volveria a consultar los mismos registros y
            # puede dejar bloqueado al unico propietario del I2C.
            raise OSError("No se pudo bloquear el bus I2C en CH%d" % channel)
        try:
            try:
                addresses = channel_bus.scan()
            except AttributeError:
                # Compatibilidad con versiones antiguas de TCA9548A.
                addresses = self.i2c.scan()
            return 0x29 in addresses
        finally:
            try:
                channel_bus.unlock()
            except Exception:
                pass

    def read(self, channel):
        if channel not in self.sensors:
            self._progress(channel, "escaneo_direccion")
            presente = self._sensor_presente(channel)
            if presente is False:
                raise SensorNoDetectadoError(
                    "No se detecto 0x29 en el canal %d del TCA9548A" % channel
                )
            self._progress(channel, "inicializacion_sensor")
            sensor = self.sensor_modules[channel].crear_sensor(
                self.sensor_class, self.mux
            )
            self.sensors[channel] = sensor
        self._progress(channel, "lectura_rango")
        distance = int(self.sensors[channel].range)
        if not 0 < distance < 8000:
            raise ValueError("Distancia fuera de rango: %s" % distance)
        return distance

    def close(self):
        i2c, self.i2c = self.i2c, None
        self.mux = None
        if i2c is not None:
            try:
                i2c.deinit()
            except Exception:
                pass
        # Solo RST pertenece a este proceso, nunca GPIO.cleanup() global.
        self.gpio.cleanup(17)


def run(config, stop, bank_factory=BancoI2C, send=emit):
    enabled = [c for c in range(4) if c not in config.get("bypass", [])]
    retry = {c: float(config.get("quarantine", {}).get(str(c), 0)) for c in enabled}
    failures = {c: 0 for c in enabled}
    bank = None
    reset_times = collections.deque()
    last_valid = time.monotonic()
    next_reset = 0.0
    needs_reset = True
    active_stage = {}

    def report_progress(channel, stage):
        if channel is not None:
            active_stage[channel] = stage
        send("progress", channel=channel, stage=stage)

    try:
        while not stop.is_set():
            if not enabled:
                send("heartbeat")
                stop.wait(0.5)
                continue
            now = time.monotonic()
            while reset_times and now - reset_times[0] >= 300:
                reset_times.popleft()
            if needs_reset or (enabled and now - last_valid > 15):
                if now >= next_reset and len(reset_times) < 3:
                    reset_times.append(now)
                    next_reset = now + min(60, 5 * 3 ** (len(reset_times) - 1))
                    report_progress(None, "reinicio_bus")
                    try:
                        if bank is None:
                            bank = bank_factory()
                            set_progress = getattr(bank, "set_progress_callback", None)
                            if set_progress is not None:
                                set_progress(report_progress)
                        bank.reset()
                        needs_reset = False
                    except Exception as exc:
                        send("bus_error", error=str(exc)[:200])
                        needs_reset = True
                if needs_reset:
                    send("heartbeat")
                    stop.wait(0.5)
                    continue
            for c in enabled:
                if stop.is_set():
                    break
                if time.monotonic() < retry[c]:
                    continue
                active_stage[c] = "lectura_sensor"
                report_progress(c, "lectura_sensor")
                try:
                    mm = bank.read(c)
                    send("sample", channel=c, state="OK", mm=mm, timestamp=time.monotonic())
                    failures[c] = 0
                    last_valid = time.monotonic()
                except Exception as exc:
                    failures[c] += 1
                    sensor_config = getattr(bank, "sensor_modules", {}).get(c)
                    # Las pruebas y bancos alternativos pueden no exponer
                    # modulos; en hardware se toma siempre la politica del canal.
                    retry_initial = getattr(
                        sensor_config, "REINTENTO_ERROR_INICIAL_S", 1.5
                    )
                    retry_max = getattr(sensor_config, "REINTENTO_ERROR_MAX_S", 30.0)
                    retry_absent_initial = getattr(
                        sensor_config, "REINTENTO_AUSENTE_INICIAL_S", 3.0
                    )
                    retry_absent_max = getattr(
                        sensor_config, "REINTENTO_AUSENTE_MAX_S", 10.0
                    )
                    if isinstance(exc, SensorNoDetectadoError):
                        # Rebuscar con backoff: un canal ausente no debe
                        # monopolizar el bus mientras los otros siguen midiendo.
                        delay = min(retry_absent_max,
                                    retry_absent_initial * 2 ** min(failures[c] - 1, 10))
                    else:
                        # Cada canal acumula su propia espera. Al superar el
                        # umbral se descarta solo su objeto; no se toca el bus
                        # compartido mientras otro sensor entregue datos.
                        delay = min(retry_max,
                                    retry_initial * 3 ** min(failures[c] - 1, 10))
                        recreate_after = getattr(sensor_config,
                                                 "RECREAR_TRAS_FALLOS", 3)
                        # Un Remote I/O suele dejar el objeto del driver en un
                        # estado incierto. Descartarlo ahora evita repetir
                        # lecturas sobre ese objeto; el resto de canales sigue
                        # usando su instancia sin reiniciar el bus.
                        if isinstance(exc, OSError) or failures[c] >= recreate_after:
                            bank.sensors.pop(c, None)
                    retry[c] = time.monotonic() + delay
                    detalle = "%s: %s" % (active_stage.get(c, "lectura_sensor"), exc)
                    send("sample", channel=c, state="ERROR", error=detalle[:200])
            send("heartbeat")
            stop.wait(SAMPLE_PERIOD_S)
    finally:
        if bank is not None:
            bank.close()


def main():
    config = json.loads(sys.argv[1])
    # Linux: si el padre termina abruptamente, no dejar un lector huerfano,
    # incluso si este esta bloqueado dentro del driver.
    if sys.platform.startswith("linux"):
        import ctypes
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError("No se pudo configurar la terminacion con el padre")
        if os.getppid() != config["parent_pid"]:
            return 1
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    try:
        run(config, stop)
    except Exception as exc:
        emit("bus_error", error=str(exc)[:200])
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
