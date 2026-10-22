import contextlib
import io
import importlib
import logging
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from i2c_supervisor import SupervisorI2C
import i2c_worker
import rtu_daemon as rtu

SENSORES_TOF = importlib.import_module("sensores-tof").SENSORES


def wait_until(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("Se agoto la espera")


class SupervisorTests(unittest.TestCase):
    def launch(self, mode, **kwargs):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        history = Path(folder.name) / "pids"
        command = [sys.executable, str(Path(__file__).with_name("fake_i2c_child.py")), mode, str(history)]
        supervisor = SupervisorI2C([2], command=command, timeout=0.15,
                                  backoff=0.01, **kwargs)
        supervisor.start()

        def close():
            supervisor.stop()
            supervisor.join(3)
            self.assertFalse(supervisor.is_alive())
            self.assertIsNone(supervisor.process)
        self.addCleanup(close)
        return supervisor, history

    def test_stalled_child_is_reaped_before_replacement(self):
        supervisor, history = self.launch("stall")
        wait_until(lambda: supervisor.snapshot()[1]["state"] == "OK")
        pids = history.read_text().splitlines()
        self.assertEqual(len(pids), 2)
        self.assertFalse(Path("/proc", pids[0]).exists())
        self.assertTrue(Path("/proc", pids[1]).exists())
        self.assertEqual(supervisor.snapshot()[0]["state"], "CUARENTENA")
        self.assertEqual(supervisor.snapshot()[2]["state"], "BYPASS")

    def test_crashes_obey_budget_without_busy_loop(self):
        supervisor, history = self.launch("crash", max_starts=2, restart_window=10)
        wait_until(lambda: supervisor.snapshot()[0]["state"] == "ESPERA")
        time.sleep(0.2)
        self.assertEqual(supervisor.starts, 2)
        self.assertEqual(len(history.read_text().splitlines()), 2)

    def test_stale_measurement_preserves_value_but_is_invalid(self):
        supervisor = SupervisorI2C(stale=0.01)
        supervisor._message({"kind": "sample", "channel": 0, "state": "OK", "mm": 100})
        time.sleep(0.02)
        self.assertEqual(supervisor.snapshot()[0]["state"], "OBSOLETO")
        self.assertEqual(supervisor.snapshot()[0]["mm"], 100)

    def test_unreapable_child_is_never_replaced(self):
        supervisor = SupervisorI2C(backoff=0)
        def collect():
            supervisor.stop()
            return False
        with patch.object(supervisor, "_collect", side_effect=collect), patch("i2c_supervisor.subprocess.Popen") as popen:
            supervisor.run()
        popen.assert_not_called()

    def test_invalid_distance_rejected(self):
        supervisor = SupervisorI2C()
        with self.assertRaises(ValueError):
            supervisor._message({"kind": "sample", "channel": 0, "state": "OK", "mm": 8190})

    def test_progress_records_channel_and_operation_stage(self):
        supervisor = SupervisorI2C()
        supervisor._message({"kind": "progress", "channel": 3,
                             "stage": "lectura_rango"})
        self.assertEqual(supervisor._active_channel, 3)
        self.assertEqual(supervisor._active_stage, "lectura_rango")
        supervisor._message({"kind": "heartbeat"})
        self.assertIsNone(supervisor._active_channel)
        self.assertIsNone(supervisor._active_stage)

    def test_delayed_message_does_not_refresh_old_sample(self):
        supervisor = SupervisorI2C(stale=1)
        supervisor._message({"kind": "sample", "channel": 0, "state": "OK",
                             "mm": 100, "timestamp": time.monotonic() - 10})
        self.assertEqual(supervisor.snapshot()[0]["state"], "OBSOLETO")


class WorkerTests(unittest.TestCase):
    def exercise(self, duration, broken):
        class ClockStop:
            now = 0.0
            def is_set(self):
                return self.now >= duration
            def wait(self, seconds):
                self.now += seconds
                return self.is_set()
        clock = ClockStop()
        class Bank:
            sensors = {}
            sensor_modules = SENSORES_TOF
            resets = 0
            closed = False
            attempts = [0] * 4
            def reset(self):
                self.resets += 1
            def read(self, c):
                self.attempts[c] += 1
                if c in broken:
                    raise OSError("fallo simulado")
                return 100
            def close(self):
                self.closed = True
        bank = Bank()
        messages = []
        with patch.object(i2c_worker.time, "monotonic", side_effect=lambda: clock.now):
            i2c_worker.run({"bypass": [2]}, clock, bank_factory=lambda: bank,
                           send=lambda kind, **kw: messages.append({"kind": kind, **kw}))
        self.assertTrue(bank.closed)
        self.assertEqual(bank.attempts[2], 0)
        return bank, messages

    def test_all_absent_still_recovers_bus_with_reset_budget(self):
        bank, messages = self.exercise(290, {0, 1, 3})
        self.assertEqual(bank.resets, 3)
        self.assertLess(bank.attempts[0], 15)
        self.assertTrue(any(m.get("state") == "ERROR" for m in messages))

    def test_bad_channel_does_not_reset_healthy_channels(self):
        bank, messages = self.exercise(20, {0})
        self.assertEqual(bank.resets, 1)
        self.assertLess(bank.attempts[0], 5)
        # Dos canales sanos a 0,5 s por ronda producen hasta ~40 lecturas
        # durante los 20 s del reloj virtual; el canal averiado no los bloquea.
        self.assertGreater(bank.attempts[1], 30)

    def test_bus_recovery_resumes_after_budget_window(self):
        bank, _ = self.exercise(310, {0, 1, 3})
        self.assertEqual(bank.resets, 4)

    def test_initial_bus_failure_is_retried_with_budget_and_heartbeat(self):
        class ClockStop:
            now = 0.0
            def is_set(self): return self.now >= 290
            def wait(self, seconds): self.now += seconds
        clock = ClockStop()
        messages = []
        factory = unittest.mock.Mock(side_effect=OSError("MUX ausente"))
        with patch.object(i2c_worker.time, "monotonic", side_effect=lambda: clock.now):
            i2c_worker.run({"bypass": [2]}, clock, bank_factory=factory,
                           send=lambda kind, **kw: messages.append(kind))
        self.assertEqual(factory.call_count, 3)
        self.assertIn("heartbeat", messages)

    def test_i2c_scan_error_does_not_fall_through_to_sensor_constructor(self):
        class Channel:
            unlocked = False
            def try_lock(self): return True
            def scan(self): raise OSError(121, "Remote I/O error")
            def unlock(self): self.unlocked = True

        channel = Channel()
        class SensorModule:
            @staticmethod
            def crear_sensor(*_args):
                raise AssertionError("No se debe reintentar el constructor tras fallar scan")

        bank = object.__new__(i2c_worker.BancoI2C)
        bank.mux = [channel]
        bank.i2c = object()
        bank.sensors = {}
        bank.sensor_modules = {0: SensorModule}
        bank.sensor_class = object
        stages = []
        bank._progress_callback = lambda channel, stage: stages.append((channel, stage))
        with self.assertRaisesRegex(OSError, "Remote I/O error"):
            bank.read(0)
        self.assertTrue(channel.unlocked)
        self.assertEqual(stages, [(0, "escaneo_direccion")])

    def test_remote_io_discards_only_the_failed_sensor_object(self):
        class ClockStop:
            now = 0.0
            def is_set(self): return self.now >= 0.1
            def wait(self, seconds): self.now += seconds

        class Bank:
            sensor_modules = SENSORES_TOF
            def __init__(self):
                self.sensors = {0: object(), 1: object(), 3: object()}
            def reset(self): pass
            def read(self, channel):
                if channel == 0:
                    raise OSError(121, "Remote I/O error")
                return 100
            def close(self): pass

        bank = Bank()
        messages = []
        i2c_worker.run(
            {"bypass": [2]}, ClockStop(), bank_factory=lambda: bank,
            send=lambda kind, **kw: messages.append({"kind": kind, **kw}),
        )
        self.assertNotIn(0, bank.sensors)
        self.assertIn(1, bank.sensors)
        self.assertIn(3, bank.sensors)
        self.assertTrue(any(m.get("state") == "ERROR" and
                            "Remote I/O error" in m.get("error", "")
                            for m in messages))


class GPIO:
    BCM, OUT, HIGH, LOW = "BCM", "OUT", 1, 0
    def __init__(self):
        self.writes = []
        self.cleaned = []
    def setmode(self, *a): pass
    def setwarnings(self, *a): pass
    def setup(self, *a, **kw): pass
    def output(self, pins, value): self.writes.append((pins, value))
    def cleanup(self, pins): self.cleaned.extend(pins)


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.patches = [patch.object(rtu, "HARDWARE_REAL", False), patch.object(rtu, "HAY_TIRAS", False)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def gateway(self, snapshot, commands=0):
        g = rtu.RtuHardwareGateway(skip_sensores=True)
        g.hw.skip_sensores = False
        g.hw.leer_instantanea_sensores = lambda: snapshot
        g.hw.actualizar_simulacion = lambda *a: None
        class Client:
            is_open = True
            def __init__(self): self.writes = []
            def write_multiple_registers(self, addr, values):
                self.writes.append((addr, values)); return True
            def write_single_register(self, addr, value):
                self.writes.append((addr, value)); return True
            def read_holding_registers(self, addr, count):
                return [commands if addr == 0 else 0]
            def close(self): self.is_open = False
        g.cliente = Client()
        return g

    def test_sensor_errors_keep_modbus_alive_without_publishing_empty_tanks(self):
        snapshot = {c: {"state": "BYPASS" if c == 2 else "ERROR", "mm": None} for c in range(4)}
        g = self.gateway(snapshot, commands=0x5500)
        class OneCycle:
            def is_set(self): return False
            def wait(self, seconds): g.corriendo = False
        g._parar_control = OneCycle()
        g.corriendo = True
        output = io.StringIO()
        with patch.dict("os.environ", {"RTU_TELEMETRIA": "1"}), contextlib.redirect_stdout(output):
            g._bucle_control()
        self.assertIn((41, 1), g.cliente.writes)
        self.assertIn((40, 1), g.cliente.writes)
        # Solo se publica P1 (bypass explicito), nunca los sensores averiados.
        self.assertEqual([a for a, v in g.cliente.writes if isinstance(v, list)], [21])
        self.assertNotIn("MIDIENDO", output.getvalue())
        self.assertEqual(output.getvalue().count("SIN DATO"), 3)
        self.assertEqual([v for a, v in g.cliente.writes if a == 0], [0x5400])

    def test_output_changes_are_idempotent_and_pumps_use_both_pins(self):
        gpio = GPIO()
        with patch.object(rtu, "HARDWARE_REAL", True), patch.object(rtu, "GPIO", gpio, create=True):
            hw = rtu.HardwareManager(skip_sensores=True)
            hw.set_bomba(0, True)
            hw.set_bomba(0, True)
            self.assertEqual(gpio.writes, [([4, 5], 0)])
            hw._cerrando = True
            hw.modo_manual_bombas = True
            hw.set_bombas(False, forzar=True)
            hw.set_bomba(0, True)
            self.assertFalse(any(hw.estado_bombas))
            hw.limpiar()
            self.assertNotIn(17, gpio.cleaned)

    def test_stop_is_idempotent_and_joins_control(self):
        g = rtu.RtuHardwareGateway(skip_sensores=True)
        g.iniciar()
        g.detener()
        g.detener()
        self.assertFalse(g._hilo_control.is_alive())
        self.assertFalse(g.animador_tiras.is_alive())
        self.assertFalse(g.animador_semaforos.is_alive())

    def test_modbus_advances_while_sensor_child_is_stalled_and_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            command = [sys.executable, str(Path(__file__).with_name("fake_i2c_child.py")),
                       "stall", str(Path(folder) / "pids")]
            supervisor = SupervisorI2C([2], command=command, timeout=0.15, backoff=0.01)
            g = self.gateway(supervisor.snapshot())
            g.hw.supervisor_i2c = supervisor
            g.hw.leer_instantanea_sensores = supervisor.snapshot
            g.iniciar()
            try:
                wait_until(lambda: supervisor.starts >= 2 and g._contador_watchdog >= 2)
                self.assertTrue(g._hilo_control.is_alive())
                self.assertEqual(supervisor.snapshot()[1]["state"], "OK")
            finally:
                g.detener()
            self.assertIsNone(supervisor.process)

    def test_failed_modbus_reads_turn_off_even_manual_pumps(self):
        snapshot = {c: {"state": "OK", "mm": 100} for c in range(4)}
        g = self.gateway(snapshot)
        g.hw.modo_manual_bombas = True
        g.hw.estado_bombas = [True] * 4
        g.cliente.read_holding_registers = lambda *a: None
        class OneCycle:
            def is_set(self): return False
            def wait(self, seconds): g.corriendo = False
        g._parar_control = OneCycle()
        g.corriendo = True
        g._bucle_control()
        self.assertFalse(any(g.hw.estado_bombas))

    def test_cli_handles_sigterm_without_hardware_or_network(self):
        code = """
import runpy, sys
from pathlib import Path
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
for name in ('RPi', 'rpi_ws281x', 'pyModbusTCP'):
    sys.modules[name] = None
sys.argv = [str(root / 'rtu_daemon.py'), '--sin-sensores']
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        p = subprocess.Popen([sys.executable, "-u", "-c", code,
                              str(Path(rtu.__file__).parent)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        try:
            # readline esta acotado por un lector auxiliar y una espera del test.
            started = threading.Event()
            def read():
                for line in p.stdout:
                    if b"Daemon iniciado correctamente" in line:
                        started.set()
            reader = threading.Thread(target=read, daemon=True)
            reader.start()
            self.assertTrue(started.wait(3))
            p.send_signal(signal.SIGTERM)
            self.assertEqual(p.wait(timeout=3), 0)
            reader.join(1)
        finally:
            if p.poll() is None:
                p.kill()
                p.wait()
            p.stdout.close()


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
