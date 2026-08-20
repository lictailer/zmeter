from __future__ import annotations

import unittest

from core.shared_runtime.visa import VisaRuntime
from devices.demoDevice.demoDevice_hardware import DemoDeviceHardware
from devices.demoDevice.dummy_visa import DummyResourceManager
from devices.hp34401a.hp34401a_hardware import HP34401A_Hardware
from devices.keithley24xx.keithley24xx_hardware import Keithly24xxHardware
from devices.sr830.sr830_hardware import SR830_Hardware
from devices.sr860.sr860_hardware import SR860_Hardware


class FakeInstrument:
    def __init__(self, address):
        self.address = address
        self.writes = []
        self.closed = 0
        self.cleared = 0
        self.timeout = None
        self.read_termination = None
        self.write_termination = None

    def write(self, command):
        self.writes.append(command)

    def query(self, command):
        if command == "*IDN?":
            return "HEWLETT-PACKARD,34401A,FAKE,1.0"
        if command == "READ?":
            return "0.0"
        return "0"

    def clear(self):
        self.cleared += 1

    def close(self):
        self.closed += 1


class FakeManager:
    def __init__(self):
        self.instruments = {}
        self.open_calls = []
        self.close_calls = 0

    def open_resource(self, address, **kwargs):
        self.open_calls.append((address, kwargs))
        instrument = FakeInstrument(address)
        self.instruments[address] = instrument
        return instrument

    def list_resources(self, _query="?*::INSTR"):
        return tuple(self.instruments)

    def close(self):
        self.close_calls += 1


class MigratedVisaDeviceTests(unittest.TestCase):
    def test_all_maintained_hardware_layers_use_shared_runtime_leases(self):
        manager = FakeManager()
        runtime = VisaRuntime(manager_factory=lambda: manager)

        hp = HP34401A_Hardware("GPIB0::1::INSTR", visa_runtime=runtime)
        keithley = Keithly24xxHardware(runtime)
        keithley.initialize("GPIB0::2::INSTR")
        sr830 = SR830_Hardware("GPIB0::3::INSTR", visa_runtime=runtime)
        sr860 = SR860_Hardware("GPIB0::4::INSTR", visa_runtime=runtime)

        self.assertEqual(len(manager.open_calls), 4)
        hp.disconnect()
        self.assertEqual(manager.instruments["GPIB0::1::INSTR"].closed, 1)
        self.assertEqual(manager.instruments["GPIB0::2::INSTR"].closed, 0)
        self.assertEqual(manager.close_calls, 0)

        keithley.close()
        sr830.disconnect()
        sr860.disconnect()
        self.assertEqual(manager.close_calls, 0)
        runtime.shutdown()
        self.assertEqual(manager.close_calls, 1)

    def test_demo_device_uses_injected_fake_without_global_patch(self):
        runtime = VisaRuntime(manager_factory=DummyResourceManager)
        device = DemoDeviceHardware("DUMMY::INSTR", runtime)
        self.assertIn("DemoDevice", device.idn())
        device.disconnect()
        runtime.shutdown()


if __name__ == "__main__":
    unittest.main()
