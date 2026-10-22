import importlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sensores_tof = importlib.import_module("sensores-tof")


class SensorToFModuleTests(unittest.TestCase):
    def test_each_tank_has_its_hardware_channel_and_bypass_state(self):
        self.assertEqual(sensores_tof.CANALES, (0, 1, 2, 3))
        self.assertEqual(sensores_tof.CANALES_BYPASS, (2,))
        self.assertEqual(
            {
                channel: (module.ESTANQUE, module.BORNERA, module.BOMBA)
                for channel, module in sensores_tof.SENSORES.items()
            },
            {
                0: ("Estanque 2", "J18", "P2"),
                1: ("Estanque 4", "J19", "P4"),
                2: ("Estanque 1", "J20", "P1"),
                3: ("Estanque 3", "J21", "P3"),
            },
        )

    def test_sensor_factory_uses_its_channel_and_common_timeout(self):
        class FakeSensor:
            def __init__(self, channel_bus):
                self.channel_bus = channel_bus
                self.io_timeout_s = None

        mux = [object() for _ in range(4)]
        for channel, module in sensores_tof.SENSORES.items():
            with self.subTest(channel=channel):
                sensor = module.crear_sensor(FakeSensor, mux)
                self.assertIs(sensor.channel_bus, mux[channel])
                self.assertEqual(sensor.io_timeout_s, sensores_tof.IO_TIMEOUT_S)


if __name__ == "__main__":
    unittest.main()
