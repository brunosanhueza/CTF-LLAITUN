"""Proceso exclusivo de sensores. No importa el daemon ni controla cargas."""
import collections
import json
import os
import signal
import sys
import threading
import time


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
        self.i2c = self.mux = None
        self.sensors = {}
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)

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
        try:
            if not channel_bus.try_lock():
                # Como en C3-PLC: si el scan no pudo tomar el bus, probar el
                # constructor del driver, que confirma la presencia por ID.
                return None
        except Exception:
            return None
        try:
            try:
                addresses = channel_bus.scan()
            except AttributeError:
                # Compatibilidad con versiones antiguas de TCA9548A.
                addresses = self.i2c.scan()
            return 0x29 in addresses
        except Exception:
            # El HAL de C3-PLC trata el scan como una pista: si falla, el
            # constructor del VL53L0X sigue siendo la prueba de presencia.
            return None
        finally:
            try:
                channel_bus.unlock()
            except Exception:
                pass

    def read(self, channel):
        if channel not in self.sensors:
            presente = self._sensor_presente(channel)
            if presente is False:
                raise SensorNoDetectadoError(
                    "No se detecto 0x29 en el canal %d del TCA9548A" % channel
                )
            # Mantener la llamada de C3-PLC: pasar solo el canal del TCA y
            # configurar el timeout despues de crear el sensor. El supervisor
            # del proceso hijo limita cualquier bloqueo durante inicializacion.
            sensor = self.sensor_class(self.mux[channel])
            if hasattr(sensor, "io_timeout_s"):
                sensor.io_timeout_s = 0.5
            self.sensors[channel] = sensor
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
                    send("progress", channel=None)
                    try:
                        if bank is None:
                            bank = bank_factory()
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
                send("progress", channel=c)
                try:
                    mm = bank.read(c)
                    send("sample", channel=c, state="OK", mm=mm, timestamp=time.monotonic())
                    failures[c] = 0
                    last_valid = time.monotonic()
                except Exception as exc:
                    if isinstance(exc, SensorNoDetectadoError):
                        # Rebuscar cada 3 s, como hacia C3-PLC con sensores
                        # desconectados. El scan no crea objetos ni carga el bus.
                        retry[c] = time.monotonic() + 3.0
                    else:
                        failures[c] += 1
                        # C3-PLC conserva el objeto ante fallos puntuales y lo
                        # vuelve a crear tras tres lecturas consecutivas fallidas.
                        delay = min(3.0, 0.5 * 2 ** min(failures[c] - 1, 3))
                        if failures[c] >= 3:
                            bank.sensors.pop(c, None)
                            failures[c] = 0
                        retry[c] = time.monotonic() + delay
                    send("sample", channel=c, state="ERROR", error=str(exc)[:200])
            send("heartbeat")
            stop.wait(0.2)
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
