"""Supervision sin acceso a GPIO/I2C. Solo este hilo crea y recoge al hijo."""
import collections
import json
import logging
import math
import os
from pathlib import Path
import select
import subprocess
import sys
import threading
import time

log = logging.getLogger(__name__)


class SupervisorI2C(threading.Thread):
    def __init__(self, bypass=(), *, command=None, timeout=8.0, stale=4.0,
                 restart_window=300.0, max_starts=3, backoff=2.0):
        super().__init__(name="supervisor-i2c", daemon=True)
        self.bypass = set(bypass)
        self.command = command or [sys.executable, "-u", str(Path(__file__).with_name("i2c_worker.py"))]
        self.timeout, self.stale = timeout, stale
        self.restart_window, self.max_starts, self.backoff = restart_window, max_starts, backoff
        self._stop_event = threading.Event()
        self._restart = threading.Event()
        self._lock = threading.Lock()
        self._samples = {c: {"state": "BYPASS" if c in self.bypass else "INICIANDO",
                             "mm": None, "timestamp": 0.0, "error": ""} for c in range(4)}
        self.process = None
        self._starts = collections.deque()
        self._quarantine = {}
        self._active_channel = None
        self.starts = 0

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            result = {c: dict(s) for c, s in self._samples.items()}
        for s in result.values():
            if s["state"] == "OK" and now - s["timestamp"] > self.stale:
                s["state"] = "OBSOLETO"
        return result

    def request_restart(self):
        self._restart.set()

    def stop(self):
        self._stop_event.set()

    def _invalidate(self, state, error=""):
        with self._lock:
            for c, s in self._samples.items():
                if c not in self.bypass:
                    s.update(state=state, error=error)

    def _message(self, message):
        kind = message.get("kind")
        if kind == "progress":
            channel = message.get("channel")
            if channel is not None and (type(channel) is not int or channel not in range(4)):
                raise ValueError("Canal I2C desconocido")
            self._active_channel = channel
        elif kind == "sample":
            c = int(message["channel"])
            if c not in self._samples or c in self.bypass:
                return
            state = message["state"]
            if state not in {"OK", "ERROR", "CUARENTENA"}:
                raise ValueError("Estado I2C desconocido")
            mm = message.get("mm")
            timestamp = float(message.get("timestamp", time.monotonic()))
            if not math.isfinite(timestamp) or timestamp > time.monotonic() + 1:
                raise ValueError("Timestamp I2C invalido")
            if state == "OK" and (type(mm) is not int or not 0 < mm < 8000):
                raise ValueError("Distancia I2C invalida")
            with self._lock:
                s = self._samples[c]
                previous = s["state"]
                s.update(state=state, error=str(message.get("error", ""))[:200])
                if state == "OK":
                    s.update(mm=mm, timestamp=timestamp)
            if state != previous:
                log.info("Sensor CH%d: %s%s", c, state,
                         (" (%s)" % s["error"]) if s["error"] else "")
        elif kind == "bus_error":
            self._invalidate("ERROR", str(message.get("error", ""))[:200])
        elif kind != "heartbeat":
            raise ValueError("Mensaje I2C desconocido")

    def _collect(self):
        """No reemplazar un hijo que siga vivo, incluso si SIGKILL no termina."""
        p = self.process
        if p is None:
            return True
        if p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                p.kill()
                try:
                    p.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    return False
        p.wait()
        p.stdout.close()
        self.process = None
        return True

    def _monitor(self):
        p = self.process
        os.set_blocking(p.stdout.fileno(), False)
        buffer = b""
        last_message = time.monotonic()
        self._active_channel = None
        while not self._stop_event.is_set() and not self._restart.is_set():
            if p.poll() is not None:
                raise RuntimeError("lector terminado (codigo %s)" % p.returncode)
            if time.monotonic() - last_message > self.timeout:
                if self._active_channel is not None:
                    self._quarantine[self._active_channel] = time.monotonic() + 60.0
                raise TimeoutError("lector I2C sin progreso")
            ready, _, _ = select.select([p.stdout], [], [], 0.1)
            if not ready:
                continue
            data = os.read(p.stdout.fileno(), 8192)
            if not data:
                raise RuntimeError("canal del lector I2C cerrado")
            buffer += data
            if len(buffer) > 65536:
                raise ValueError("mensaje del lector demasiado grande")
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                self._message(json.loads(line))
                last_message = time.monotonic()

    def run(self):
        limited = False
        try:
            while not self._stop_event.is_set():
                if not self._collect():
                    self._invalidate("BLOQUEADO", "El proceso anterior no termina")
                    if not limited:
                        log.error("I2C: el hijo no termina; no se creara otro lector")
                        limited = True
                    self._stop_event.wait(2.0)
                    continue
                now = time.monotonic()
                while self._starts and now - self._starts[0] >= self.restart_window:
                    self._starts.popleft()
                if len(self._starts) >= self.max_starts:
                    self._invalidate("ESPERA", "Limite de reinicios alcanzado")
                    if not limited:
                        log.warning("I2C: limite de reinicios; esperando antes de reintentar")
                        limited = True
                    self._stop_event.wait(min(1.0, self.restart_window - (now - self._starts[0])))
                    continue
                limited = False
                self._restart.clear()
                self._starts.append(now)  # Los fallos de Popen tambien consumen presupuesto.
                self._invalidate("INICIANDO")
                config = {"bypass": sorted(self.bypass), "quarantine": self._quarantine,
                          "parent_pid": os.getpid()}
                with self._lock:
                    for c, until in self._quarantine.items():
                        if until > now and c not in self.bypass:
                            self._samples[c]["state"] = "CUARENTENA"
                try:
                    self.process = subprocess.Popen(
                        [*self.command, json.dumps(config)], stdin=subprocess.DEVNULL,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, close_fds=True,
                    )
                    self.starts += 1
                    log.info("I2C: lector iniciado (PID %d)", self.process.pid)
                    self._monitor()
                except Exception as exc:
                    self._invalidate("ERROR", str(exc))
                    log.warning("I2C: %s", exc)
                if not self._collect():
                    continue
                self._invalidate("RECUPERANDO")
                self._stop_event.wait(min(60.0, self.backoff * 2 ** (len(self._starts) - 1)))
        finally:
            self._invalidate("DETENIDO")
            if not self._collect():
                log.error("I2C: proceso pendiente de terminacion por el kernel")
