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
        if self.i2c is not None:
            self.i2c.deinit()
            self.i2c = self.mux = None
        self.gpio.setup(17, self.gpio.OUT, initial=self.gpio.HIGH)
        self.gpio.output(17, self.gpio.LOW)
        time.sleep(0.03)
        self.gpio.output(17, self.gpio.HIGH)
        time.sleep(0.08)
        self.i2c = self.busio.I2C(self.board.SCL, self.board.SDA)
        self.mux = self.mux_class(self.i2c, address=0x70)

    def read(self, channel):
        if channel not in self.sensors:
            # El timeout debe estar activo DURANTE el constructor.
            sensor = self.sensor_class(self.mux[channel], io_timeout_s=0.5)
            sensor.measurement_timing_budget = 33000
            self.sensors[channel] = sensor
        distance = int(self.sensors[channel].range)
        if not 0 < distance < 8000:
            raise ValueError("Distancia fuera de rango: %s" % distance)
        return distance

    def close(self):
        if self.i2c is not None:
            self.i2c.deinit()
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
                    failures[c] += 1
                    retry[c] = time.monotonic() + min(60, 2.5 * 2 ** min(failures[c] - 1, 5))
                    bank.sensors.pop(c, None)
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
