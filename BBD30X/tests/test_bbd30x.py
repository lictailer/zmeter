"""Fake-Kinesis and offscreen tests for the BBD30X package."""

from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from BBD30X.BBD30X_hardware import BBD30x_hardware
from BBD30X.BBD30X_logic import BBD30X_Logic
from BBD30X.BBD30X_main import BBD30X
from core.mainWindow import MainWindow


class FakeDecimal:
    def __new__(cls, value):
        return float(value)

    @staticmethod
    def ToDouble(value):
        return float(value)


class FakeConvert:
    @staticmethod
    def ToDecimal(value):
        return float(value)


class FakeConfiguration:
    def __init__(self, events):
        self.events = events
        self.DeviceSettingsName = None

    def UpdateCurrentConfiguration(self):
        self.events.append("update_configuration")


class FakeChannel:
    DeviceID = "channel-1"
    MotorDeviceSettings = "motor-settings"

    def __init__(self, events, fallback=False):
        self.events = events
        self.fallback = fallback
        self.Position = 0.0
        self.configuration = FakeConfiguration(events)

    def WaitForSettingsInitialized(self, timeout):
        self.events.append(("wait_settings", timeout))

    def LoadMotorConfiguration(self, *args):
        self.events.append(("load_configuration", args))
        if self.fallback and len(args) == 1:
            raise RuntimeError("device settings unavailable")
        return self.configuration

    def SetSettings(self, *args):
        self.events.append(("set_settings", args))

    def StartPolling(self, interval):
        self.events.append(("start_polling", interval))

    def EnableDevice(self):
        self.events.append("enable")

    def MoveTo(self, position, timeout):
        self.events.append(("move_to", float(position), timeout))
        self.Position = float(position)

    def StopPolling(self):
        self.events.append("stop_polling")


class FakeDevice:
    def __init__(self, events, channel):
        self.events = events
        self.channel = channel

    def Connect(self, serial):
        self.events.append(("connect", serial))

    def GetChannel(self, number):
        self.events.append(("get_channel", number))
        return self.channel

    def Disconnect(self):
        self.events.append("disconnect")


def make_bindings(fallback=False):
    events = []
    channel = FakeChannel(events, fallback=fallback)
    device = FakeDevice(events, channel)

    class DeviceManagerCLI:
        @staticmethod
        def BuildDeviceList():
            events.append("build_device_list")

        @staticmethod
        def GetDeviceList():
            events.append("get_device_list")
            return ["fake-serial"]

    class BenchtopBrushlessMotor:
        @staticmethod
        def CreateBenchtopBrushlessMotor(serial):
            events.append(("create_device", serial))
            return device

    dm = SimpleNamespace(DeviceManagerCLI=DeviceManagerCLI)
    bm = SimpleNamespace(BenchtopBrushlessMotor=BenchtopBrushlessMotor)
    gm = SimpleNamespace(
        DeviceConfiguration=SimpleNamespace(
            DeviceSettingsUseOptionType=SimpleNamespace(UseFileSettings="file-settings")
        ),
        Settings=SimpleNamespace(
            HomeSettings=SimpleNamespace(
                HomeDirection=SimpleNamespace(CounterClockwise="counter-clockwise")
            )
        ),
    )
    return (dm, gm, bm, FakeConvert, FakeDecimal), events, channel


class FakeHardware:
    def __init__(self):
        self.connect_calls = []
        self.moves = []
        self.position = 0.012
        self.disconnect_calls = 0

    def connect(self, serial):
        self.connect_calls.append(serial)

    def disconnect(self):
        self.disconnect_calls += 1

    def move(self, position):
        self.moves.append(position)
        self.position = position

    def get_position_mm(self):
        return self.position

    def home(self):
        pass

    def set_velocity_params(self, velocity, acceleration):
        pass


class FakeLease:
    def __init__(self):
        self.closed = 0

    def close(self):
        self.closed += 1


class FakeKinesisRuntime:
    def __init__(self, bindings=None, load_error=None):
        self.bindings = bindings
        self.load_error = load_error
        self.leases = []
        self.load_calls = []
        self.initialize_calls = 0

    def acquire(self, _owner):
        lease = FakeLease()
        self.leases.append(lease)
        return lease

    def load_managed(self, component):
        self.load_calls.append(component)
        if self.load_error is not None:
            raise self.load_error
        return self.bindings

    def initialize_device_manager(self, callback):
        self.initialize_calls += 1
        return callback()


class ScanDiscoveryHarness:
    make_variables_dictionary = MainWindow.make_variables_dictionary
    _is_valid_getter = MainWindow._is_valid_getter
    _is_valid_setter = MainWindow._is_valid_setter
    _safe_signature = MainWindow._safe_signature
    filter_scan_channels = MainWindow.filter_scan_channels

    def __init__(self):
        self.equips_set_channels = {}
        self.equips_get_channels = {}


class BBD30XTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_import_and_widget_construction_do_not_load_pythonnet_or_connect(self):
        fake = FakeHardware()
        before_clr = sys.modules.get("clr")
        widget = BBD30X(hardware=fake)
        self.addCleanup(widget.close)
        self.assertIs(sys.modules.get("clr"), before_clr)
        self.assertEqual(widget.lineEdit.text(), "103529564")
        self.assertEqual(fake.connect_calls, [])

    def test_explicit_serial_overrides_the_widget_default(self):
        fake = FakeHardware()
        widget = BBD30X(hardware=fake)
        self.addCleanup(widget.close)

        widget.connect("876543210")

        self.assertTrue(widget.logic.wait(1000))
        self.assertEqual(widget.lineEdit.text(), "876543210")
        self.assertEqual(fake.connect_calls, ["876543210"])

    def test_current_scanner_discovers_only_pos(self):
        widget = BBD30X(hardware=FakeHardware())
        self.addCleanup(widget.close)
        window = ScanDiscoveryHarness()
        setters, getters = window.make_variables_dictionary(widget, "Delay_Stage")
        self.assertEqual(set(setters), {"pos"})
        self.assertEqual(set(getters), {"pos"})

    def test_connection_sequence_uses_channel_one_and_preserves_polling(self):
        bindings, events, _channel = make_bindings()
        runtime = FakeKinesisRuntime(bindings)
        hardware = BBD30x_hardware(runtime)
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            hardware.connect("12345678")
        self.assertLess(events.index("build_device_list"), events.index(("connect", "12345678")))
        self.assertEqual(runtime.initialize_calls, 1)
        self.assertIn(("get_channel", 1), events)
        self.assertIn(("wait_settings", 5000), events)
        self.assertIn(("start_polling", 50), events)
        self.assertLess(events.index(("start_polling", 50)), events.index("enable"))

    def test_dds220_file_settings_fallback_is_preserved(self):
        bindings, events, channel = make_bindings(fallback=True)
        hardware = BBD30x_hardware(FakeKinesisRuntime(bindings))
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            hardware.connect("12345678")
        self.assertEqual(channel.configuration.DeviceSettingsName, "DDS220")
        self.assertIn("update_configuration", events)
        self.assertIn(("set_settings", ("motor-settings", True, False)), events)

    def test_move_and_position_use_millimeters(self):
        bindings, events, channel = make_bindings()
        hardware = BBD30x_hardware(FakeKinesisRuntime(bindings))
        hardware._ensure_bindings()
        hardware.channel = channel
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            hardware.move(12.5)
        self.assertIn(("move_to", 12.5, 50000), events)
        self.assertEqual(hardware.get_position_mm(), 12.5)

    def test_move_timeout_is_preserved(self):
        bindings, _events, channel = make_bindings()
        hardware = BBD30x_hardware(FakeKinesisRuntime(bindings))
        hardware._ensure_bindings()
        hardware.channel = channel
        with mock.patch.object(hardware, "get_position_mm", return_value=0.0), mock.patch(
            "BBD30X.BBD30X_hardware.time.sleep"
        ):
            with self.assertRaisesRegex(TimeoutError, "1.0 mm"):
                hardware.move(1.0)

    def test_disconnect_stops_polling_and_disconnects_device(self):
        bindings, events, _channel = make_bindings()
        runtime = FakeKinesisRuntime(bindings)
        hardware = BBD30x_hardware(runtime)
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            hardware.connect("12345678")
        hardware.disconnect()
        self.assertEqual(events[-2:], ["stop_polling", "disconnect"])
        self.assertIsNone(hardware.channel)
        self.assertIsNone(hardware.device)
        self.assertEqual(runtime.leases[0].closed, 1)

    def test_shared_runtime_failure_releases_lease(self):
        runtime = FakeKinesisRuntime(load_error=RuntimeError("runtime unavailable"))
        hardware = BBD30x_hardware(runtime)
        with self.assertRaisesRegex(RuntimeError, "runtime unavailable"):
            hardware.connect("12345678")
        self.assertEqual(runtime.leases[0].closed, 1)

    def test_logic_and_ui_preserve_micrometer_to_millimeter_conversion(self):
        fake = FakeHardware()
        widget = BBD30X(hardware=fake)
        self.addCleanup(widget.close)
        widget.pos_to_go_doubleSpinBox.setValue(1250.0)
        widget.set_pos()
        self.assertTrue(widget.logic.wait(1000))
        self.assertEqual(fake.moves, [1.25])
        widget.update_pos(1.25)
        self.assertIn("1250.00 um", widget.last_pos_label.text())

    def test_logic_hardware_injection_preserves_public_methods(self):
        fake = FakeHardware()
        logic = BBD30X_Logic(hardware=fake)
        self.assertTrue(logic.connect("12345678"))
        self.assertEqual(logic.get_pos(), 0.012)
        logic.set_pos(2.0)
        self.assertEqual(fake.moves, [2.0])
        logic.disconnect()
        self.assertEqual(fake.disconnect_calls, 1)


if __name__ == "__main__":
    unittest.main()
