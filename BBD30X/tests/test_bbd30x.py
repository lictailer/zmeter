"""Fake-Kinesis and offscreen tests for the BBD30X package."""

from __future__ import annotations

import os
import sys
import threading
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


class FakeVelocityParams:
    def __init__(self, velocity=10.0, acceleration=20.0):
        self.MaxVelocity = velocity
        self.Acceleration = acceleration


class FakeChannel:
    DeviceID = "channel-1"
    MotorDeviceSettings = "motor-settings"

    def __init__(self, events, fallback=False, complete_moves=True):
        self.events = events
        self.fallback = fallback
        self.complete_moves = complete_moves
        self._position = 0.0
        self.TargetPosition = 0.0
        self._position_sequence = []
        self._completion_callback = None
        self.velocity_params = FakeVelocityParams()

    @property
    def Position(self):
        if self._position_sequence:
            self._position = self._position_sequence.pop(0)
            if (
                not self._position_sequence
                and self._completion_callback is not None
                and self.complete_moves
            ):
                callback = self._completion_callback
                self._completion_callback = None
                callback(1)
        return self._position

    def WaitForSettingsInitialized(self, timeout):
        self.events.append(("wait_settings", timeout))

    def LoadMotorConfiguration(self, *args):
        self.events.append(("load_configuration", args))
        if self.fallback and len(args) == 1:
            raise RuntimeError("device settings unavailable")
        return FakeConfiguration(self.events)

    def SetSettings(self, *args):
        self.events.append(("set_settings", args))

    def StartPolling(self, interval):
        self.events.append(("start_polling", interval))

    def EnableDevice(self):
        self.events.append("enable")

    def GetVelocityParams(self):
        self.events.append("get_velocity")
        return FakeVelocityParams(
            self.velocity_params.MaxVelocity,
            self.velocity_params.Acceleration,
        )

    def SetVelocityParams(self, params):
        self.velocity_params = FakeVelocityParams(
            float(params.MaxVelocity),
            float(params.Acceleration),
        )
        self.events.append(
            (
                "set_velocity",
                self.velocity_params.MaxVelocity,
                self.velocity_params.Acceleration,
            )
        )

    def MoveTo(self, position, callback):
        target = float(position)
        self.events.append(("move_to_async", target))
        self.TargetPosition = target
        midpoint = (self._position + target) / 2.0
        self._position_sequence = [midpoint, target]
        self._completion_callback = callback

    def Home(self, timeout):
        self.events.append(("home", timeout))

    def Stop(self, timeout):
        self.events.append(("stop", timeout))
        self._position_sequence = []

    def StopPolling(self):
        self.events.append("stop_polling")


class FakeDevice:
    def __init__(self, events, channel, fail_connect_count=0):
        self.events = events
        self.channel = channel
        self.fail_connect_count = fail_connect_count

    def Connect(self, serial):
        self.events.append(("connect", serial))
        if self.fail_connect_count:
            self.fail_connect_count -= 1
            raise RuntimeError("fake device connection failure")

    def GetChannel(self, number):
        self.events.append(("get_channel", number))
        return self.channel

    def Disconnect(self):
        self.events.append("disconnect")


def make_bindings(fallback=False, complete_moves=True, fail_connect_count=0):
    events = []
    channel = FakeChannel(
        events,
        fallback=fallback,
        complete_moves=complete_moves,
    )
    device = FakeDevice(
        events,
        channel,
        fail_connect_count=fail_connect_count,
    )

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
    def __init__(self, fail_connect_count=0):
        self.fail_connect_count = fail_connect_count
        self.connect_calls = []
        self.moves = []
        self.position = 0.012
        self.target = 0.012
        self.velocity = 100.0
        self.acceleration = 2000.0
        self.disconnect_calls = 0
        self.stop_calls = 0

    def connect(self, serial):
        self.connect_calls.append(serial)
        if self.fail_connect_count:
            self.fail_connect_count -= 1
            raise RuntimeError("fake connection failure")
        self.velocity = 100.0
        self.acceleration = 2000.0
        return self.velocity, self.acceleration

    def disconnect(self):
        self.disconnect_calls += 1

    @staticmethod
    def validate_position_mm(value):
        return BBD30x_hardware.validate_position_mm(value)

    def move(self, position, position_callback=None, cancel_event=None):
        position = self.validate_position_mm(position)
        self.moves.append(position)
        self.target = position
        midpoint = (self.position + position) / 2.0
        if position_callback is not None:
            position_callback(midpoint)
        if cancel_event is not None and cancel_event.is_set():
            self.stop_motion()
            raise RuntimeError("cancelled")
        self.position = position
        if position_callback is not None:
            position_callback(position)
        return position

    def get_position_mm(self):
        return self.position

    def get_target_position_mm(self):
        return self.target

    def home(self):
        self.position = 0.0

    def set_velocity_params(self, velocity=None, acceleration=None):
        if velocity is not None:
            self.velocity = BBD30x_hardware._validate_positive_finite(
                velocity, "Velocity"
            )
        if acceleration is not None:
            self.acceleration = BBD30x_hardware._validate_positive_finite(
                acceleration, "Acceleration"
            )
        return self.velocity, self.acceleration

    def stop_motion(self):
        self.stop_calls += 1
        return True


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
        self.ensure_calls = 0
        self.refresh_calls = 0
        self.initialized_components = set()

    def acquire(self, _owner):
        lease = FakeLease()
        self.leases.append(lease)
        return lease

    def load_managed(self, component):
        self.load_calls.append(component)
        if self.load_error is not None:
            raise self.load_error
        return self.bindings

    def ensure_device_manager(self, component, callback):
        self.ensure_calls += 1
        if component in self.initialized_components:
            return False
        callback()
        self.initialized_components.add(component)
        return True

    def refresh_device_manager(self, component, callback):
        self.refresh_calls += 1
        result = callback()
        self.initialized_components.add(component)
        return result


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

    def test_import_and_widget_construction_are_lazy_and_show_defaults(self):
        fake = FakeHardware()
        before_clr = sys.modules.get("clr")
        widget = BBD30X(hardware=fake)
        self.addCleanup(widget.close)
        self.assertIs(sys.modules.get("clr"), before_clr)
        self.assertEqual(widget.serial_lineEdit.text(), "103529564")
        self.assertEqual(widget.velocity_lineEdit.text(), "100")
        self.assertEqual(widget.acceleration_lineEdit.text(), "2000")
        self.assertEqual(fake.connect_calls, [])
        widget.show()
        self.app.processEvents()
        visible_lines = (
            widget.log_textEdit.height()
            / widget.log_textEdit.fontMetrics().lineSpacing()
        )
        self.assertGreaterEqual(visible_lines, 8)
        self.assertLessEqual(visible_lines, 10)
        initial_log_height = widget.log_textEdit.height()
        widget.resize(widget.width(), widget.height() + 100)
        self.app.processEvents()
        self.assertGreater(widget.log_textEdit.height(), initial_log_height)

    def test_connection_failure_is_contained_and_retry_succeeds(self):
        fake = FakeHardware(fail_connect_count=1)
        widget = BBD30X(hardware=fake)
        self.addCleanup(widget.close)
        widget.show()

        self.assertTrue(widget.connect("876543210"))
        self.assertTrue(widget.logic.wait(1000))
        self.app.processEvents()
        self.assertFalse(widget.logic.is_connected)
        self.assertTrue(widget.isVisible())
        self.assertIn("connection failure", widget.log_textEdit.toPlainText())
        self.assertEqual(
            widget.log_textEdit.toPlainText().count("Connection for 876543210 failed"),
            1,
        )

        self.assertTrue(widget.connect("876543210"))
        self.assertTrue(widget.logic.wait(1000))
        self.app.processEvents()
        self.assertTrue(widget.logic.is_connected)
        self.assertEqual(fake.connect_calls, ["876543210", "876543210"])

    def test_scanner_discovers_three_unit_explicit_channels(self):
        widget = BBD30X(hardware=FakeHardware())
        self.addCleanup(widget.close)
        window = ScanDiscoveryHarness()
        setters, getters = window.make_variables_dictionary(widget, "delay_stage")
        expected = {"pos_mm", "pos_um", "delay_ps"}
        self.assertEqual(set(setters), expected)
        self.assertEqual(set(getters), expected)

    def test_connection_sequence_applies_default_motion_parameters(self):
        bindings, events, _channel = make_bindings()
        runtime = FakeKinesisRuntime(bindings)
        hardware = BBD30x_hardware(
            runtime,
            completion_callback_factory=lambda callback: callback,
        )
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            values = hardware.connect("12345678")
        self.assertEqual(values, (100.0, 2000.0))
        self.assertIn(("get_channel", 1), events)
        self.assertIn(("start_polling", 50), events)
        self.assertIn(("set_velocity", 100.0, 2000.0), events)

    def test_dds220_file_settings_fallback_is_preserved(self):
        bindings, events, _channel = make_bindings(fallback=True)
        hardware = BBD30x_hardware(
            FakeKinesisRuntime(bindings),
            completion_callback_factory=lambda callback: callback,
        )
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            hardware.connect("12345678")
        self.assertIn("update_configuration", events)
        self.assertIn(("set_settings", ("motor-settings", True, False)), events)

    def test_device_connection_failure_refreshes_once_and_retries_same_serial(self):
        bindings, _events, _channel = make_bindings(fail_connect_count=1)
        runtime = FakeKinesisRuntime(bindings)
        hardware = BBD30x_hardware(
            runtime,
            completion_callback_factory=lambda callback: callback,
        )
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            self.assertEqual(hardware.connect("12345678"), (100.0, 2000.0))
        self.assertEqual(runtime.ensure_calls, 1)
        self.assertEqual(runtime.refresh_calls, 1)
        self.assertEqual(len(runtime.leases), 1)
        self.assertEqual(runtime.leases[0].closed, 0)
        self.assertTrue(hardware.last_connection_refreshed)

    def test_failed_retry_reports_error_and_releases_lease(self):
        bindings, _events, _channel = make_bindings(fail_connect_count=2)
        runtime = FakeKinesisRuntime(bindings)
        hardware = BBD30x_hardware(
            runtime,
            completion_callback_factory=lambda callback: callback,
        )
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "after DeviceManager refresh"):
                hardware.connect("12345678")
        self.assertEqual(runtime.refresh_calls, 1)
        self.assertEqual(runtime.leases[0].closed, 1)

    def test_reconnect_uses_cached_device_manager_without_rebuild(self):
        bindings, events, _channel = make_bindings()
        runtime = FakeKinesisRuntime(bindings)
        hardware = BBD30x_hardware(
            runtime,
            completion_callback_factory=lambda callback: callback,
        )
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            hardware.connect("12345678")
            hardware.disconnect()
            hardware.connect("12345678")
        self.assertEqual(events.count("build_device_list"), 1)
        self.assertNotIn("get_device_list", events)

    def test_async_move_emits_intermediate_and_final_positions(self):
        bindings, events, channel = make_bindings()
        hardware = BBD30x_hardware(
            FakeKinesisRuntime(bindings),
            completion_callback_factory=lambda callback: callback,
            poll_interval_seconds=0.0,
        )
        hardware._ensure_bindings()
        hardware.channel = channel
        positions = []
        result = hardware.move(12.5, position_callback=positions.append)
        self.assertEqual(result, 12.5)
        self.assertEqual(positions, [6.25, 12.5])
        self.assertIn(("move_to_async", 12.5), events)

    def test_move_timeout_requests_controlled_stop(self):
        bindings, events, channel = make_bindings(complete_moves=False)
        hardware = BBD30x_hardware(
            FakeKinesisRuntime(bindings),
            completion_callback_factory=lambda callback: callback,
            move_timeout_seconds=0.001,
            poll_interval_seconds=0.0,
        )
        hardware._ensure_bindings()
        hardware.channel = channel
        with self.assertRaisesRegex(TimeoutError, "1.0 mm"):
            hardware.move(1.0)
        self.assertIn(("stop", 5000), events)

    def test_move_cancellation_requests_controlled_stop(self):
        bindings, events, channel = make_bindings(complete_moves=False)
        hardware = BBD30x_hardware(
            FakeKinesisRuntime(bindings),
            completion_callback_factory=lambda callback: callback,
            poll_interval_seconds=0.0,
        )
        hardware._ensure_bindings()
        hardware.channel = channel
        cancel_event = threading.Event()
        cancel_event.set()
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            hardware.move(1.0, cancel_event=cancel_event)
        self.assertIn(("stop", 5000), events)

    def test_partial_velocity_updates_and_validation(self):
        bindings, _events, channel = make_bindings()
        hardware = BBD30x_hardware(
            FakeKinesisRuntime(bindings),
            completion_callback_factory=lambda callback: callback,
        )
        hardware._ensure_bindings()
        hardware.channel = channel
        self.assertEqual(hardware.set_velocity_params(100.0, 2000.0), (100.0, 2000.0))
        self.assertEqual(hardware.set_velocity_params(None, 2500.0), (100.0, 2500.0))
        self.assertEqual(hardware.set_velocity_params(80.0, None), (80.0, 2500.0))
        self.assertEqual(hardware.set_velocity_params(None, None), (80.0, 2500.0))
        with self.assertRaisesRegex(ValueError, "greater than zero"):
            hardware.set_velocity_params(0.0, None)

    def test_units_t0_and_scan_moves_share_millimeter_path(self):
        fake = FakeHardware()
        logic = BBD30X_Logic(hardware=fake)
        logic.connect("12345678")
        with self.assertRaisesRegex(RuntimeError, "Set BBD30X T0"):
            logic.get_delay_ps()
        logic.set_t0_from_current_position()
        self.assertAlmostEqual(logic.get_delay_ps(), 0.0)

        logic.set_pos_um(1250.0)
        self.assertEqual(fake.moves[-1], 1.25)
        delay = logic.mm_to_delay_ps(2.0)
        logic.set_delay_ps(delay)
        self.assertAlmostEqual(fake.moves[-1], 2.0)
        self.assertAlmostEqual(logic.delay_ps_to_mm(delay), 2.0)

    def test_t0_is_cleared_on_disconnect_and_reconnect(self):
        logic = BBD30X_Logic(hardware=FakeHardware())
        logic.connect("12345678")
        logic.set_t0_from_current_position()
        self.assertIsNotNone(logic.t0_mm)
        logic.disconnect()
        self.assertIsNone(logic.t0_mm)
        logic.connect("12345678")
        self.assertIsNone(logic.t0_mm)

    def test_position_range_is_enforced_for_all_unit_paths(self):
        fake = FakeHardware()
        logic = BBD30X_Logic(hardware=fake)
        logic.connect("12345678")
        logic.set_t0_from_current_position()
        with self.assertRaisesRegex(ValueError, "outside"):
            logic.set_pos_mm(220.0001)
        with self.assertRaisesRegex(ValueError, "outside"):
            logic.set_pos_um(-1.0)
        too_large_delay = logic.mm_to_delay_ps(221.0)
        with self.assertRaisesRegex(ValueError, "outside"):
            logic.set_delay_ps(too_large_delay)

    def test_ui_position_format_uses_mm_and_ps_only(self):
        fake = FakeHardware()
        widget = BBD30X(hardware=fake)
        self.addCleanup(widget.close)
        widget.logic.connect("12345678")
        widget.logic.set_t0_from_current_position()
        widget._update_current_position(1.25)
        widget._update_target_position(2.5)
        self.app.processEvents()
        self.assertIn("1.2500 mm", widget.current_position_label.text())
        self.assertIn("ps", widget.current_position_label.text())
        self.assertNotIn("um", widget.current_position_label.text().lower())
        self.assertIn("2.5000 mm", widget.target_position_label.text())

    def test_routine_move_read_and_parameter_updates_do_not_log(self):
        widget = BBD30X(hardware=FakeHardware())
        self.addCleanup(widget.close)
        widget.logic.connect("12345678")
        self.app.processEvents()
        connection_log = widget.log_textEdit.toPlainText()

        widget.logic.set_pos_mm(1.0)
        widget.logic.read_position_from_ui()
        widget.logic.set_velocity_params(None, None)
        self.app.processEvents()

        self.assertEqual(widget.log_textEdit.toPlainText(), connection_log)
        self.assertTrue(widget.log_textEdit.isReadOnly())
        self.assertEqual(widget.log_textEdit.maximumBlockCount(), 500)

    def test_busy_ui_job_is_rejected_and_logged(self):
        logic = BBD30X_Logic(hardware=FakeHardware())
        messages = []
        logic.sig_error.connect(messages.append)
        with logic._state_lock:
            logic._operation_active = True
        self.assertFalse(logic.submit_ui_job(lambda: None))
        self.assertEqual(messages, ["BBD30X is busy"])

    def test_disconnect_releases_runtime_and_stops_polling(self):
        bindings, events, _channel = make_bindings()
        runtime = FakeKinesisRuntime(bindings)
        hardware = BBD30x_hardware(
            runtime,
            completion_callback_factory=lambda callback: callback,
        )
        with mock.patch("BBD30X.BBD30X_hardware.time.sleep"):
            hardware.connect("12345678")
        hardware.disconnect()
        self.assertEqual(events[-2:], ["stop_polling", "disconnect"])
        self.assertEqual(runtime.leases[0].closed, 1)

    def test_shared_runtime_failure_releases_lease(self):
        runtime = FakeKinesisRuntime(load_error=RuntimeError("runtime unavailable"))
        hardware = BBD30x_hardware(
            runtime,
            completion_callback_factory=lambda callback: callback,
        )
        with self.assertRaisesRegex(RuntimeError, "runtime unavailable"):
            hardware.connect("12345678")
        self.assertEqual(runtime.leases[0].closed, 1)


if __name__ == "__main__":
    unittest.main()
