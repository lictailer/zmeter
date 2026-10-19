from __future__ import annotations

import inspect
import json
import math
import os
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from devices.attodry.attodry_hardware import AttoDryHardware
from devices.attodry.attodry_logic import AttoDryLogic
from devices.attodry.attodry_main import AttoDry


class FakeSample:
    def __init__(self) -> None:
        self.temperature = 4.2
        self.setpoint = 4.2
        self.control_calls = 0

    def getTemperature(self):
        return self.temperature

    def setSetPoint(self, value):
        self.setpoint = value

    def startTempControl(self):
        self.control_calls += 1


class FakeMagnet:
    def __init__(self) -> None:
        self.field = 0.0
        self.setpoint = 0.0
        self.state = "Holding"
        self.quenched = False
        self.control_active = False
        self.control_calls = 0

    def getH(self, channel):
        assert channel == 0
        return self.field

    def getHState(self, channel):
        assert channel == 0
        return self.state

    def getFieldControl(self, channel):
        assert channel == 0
        return self.control_active

    def getIsInQuenchState(self):
        return self.quenched

    def getNumberOfMagnetChannels(self):
        return 1

    def setHSetPoint(self, channel, value):
        assert channel == 0
        self.setpoint = value

    def startFieldControl(self, channel):
        assert channel == 0
        self.control_calls += 1


class FakeDevice:
    def __init__(self, address):
        self.address = address
        self.sample = FakeSample()
        self.magnet = FakeMagnet()
        self.open = False

    def connect(self):
        self.open = True

    def close(self):
        self.open = False


class AttoDryHardwareTests(unittest.TestCase):
    def setUp(self):
        self.device = None

        def factory(address):
            self.device = FakeDevice(address)
            return self.device

        self.hardware = AttoDryHardware(factory)
        self.assertTrue(self.hardware.connect("192.0.2.20"))

    def tearDown(self):
        self.hardware.disconnect()

    def test_connect_reads_and_disconnect_are_repeatable(self):
        self.assertTrue(self.hardware.connected)
        self.assertEqual(self.hardware.address, "192.0.2.20")
        self.assertEqual(self.hardware.magnet_channels, 1)
        self.assertEqual(self.hardware.read_temperature_k(), 4.2)
        self.assertEqual(self.hardware.read_field_t(), 0.0)
        self.assertTrue(self.hardware.disconnect())
        self.assertTrue(self.hardware.disconnect())
        self.assertFalse(self.hardware.connected)

    def test_setters_validate_limits_and_start_controller_control(self):
        self.assertEqual(self.hardware.set_temperature_k(10), 10.0)
        self.assertEqual(self.device.sample.setpoint, 10.0)
        self.assertEqual(self.device.sample.control_calls, 1)
        self.assertEqual(self.hardware.set_field_t(-1.25), -1.25)
        self.assertEqual(self.device.magnet.setpoint, -1.25)
        self.assertEqual(self.device.magnet.control_calls, 1)

        for invalid in (math.nan, math.inf, 1.79, 300.01):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.hardware.set_temperature_k(invalid)
        for invalid in (math.nan, math.inf, -9.01, 9.01):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.hardware.set_field_t(invalid)

    def test_quench_refuses_field_write_before_setpoint(self):
        self.device.magnet.quenched = True
        with self.assertRaisesRegex(RuntimeError, "quench"):
            self.hardware.set_field_t(1.0)
        self.assertEqual(self.device.magnet.setpoint, 0.0)
        self.assertEqual(self.device.magnet.control_calls, 0)


class AttoDryLogicTests(unittest.TestCase):
    def setUp(self):
        device = FakeDevice("fake")
        self.hardware = AttoDryHardware(lambda _address: device)
        self.logic = AttoDryLogic(self.hardware)
        self.logic.connect_device("fake")

    def tearDown(self):
        self.logic.close()

    def test_exact_scan_channel_signatures(self):
        discovered = {
            name: len(inspect.signature(getattr(self.logic, name)).parameters)
            for name in dir(self.logic)
            if name.startswith(("get_", "set_"))
        }
        self.assertEqual(
            discovered,
            {
                "get_B": 0,
                "get_T": 0,
                "set_B": 1,
                "set_B_stable": 1,
                "set_T": 1,
                "set_T_stable": 1,
            },
        )

    def test_stable_wait_requires_consecutive_in_tolerance_samples(self):
        readings = iter([9.0, 9.96, 10.02, 10.01])
        self.logic.configure_temperature_stability(0.05, 3, 0.5)
        with (
            mock.patch.object(self.logic, "get_T", side_effect=lambda: next(readings)),
            mock.patch.object(self.logic._stop_requested, "wait", return_value=False),
        ):
            result = self.logic.set_T_stable(10.0)
        self.assertEqual(result, 10.01)

    def test_temperature_stability_settings_are_session_configurable(self):
        self.assertEqual(
            (
                self.logic.temperature_stability.tolerance,
                self.logic.temperature_stability.stable_samples,
                self.logic.temperature_stability.poll_interval_s,
            ),
            (0.05, 5, 2.0),
        )
        accepted = self.logic.configure_temperature_stability(0.25, 2, 0.5)
        self.assertEqual(
            (accepted.tolerance, accepted.stable_samples, accepted.poll_interval_s),
            (0.25, 2, 0.5),
        )
        readings = iter([9.0, 9.8, 9.8])
        with (
            mock.patch.object(self.logic, "get_T", side_effect=lambda: next(readings)),
            mock.patch.object(self.logic._stop_requested, "wait", return_value=False),
        ):
            result = self.logic.set_T_stable(10.0)
        self.assertEqual(result, 9.8)

    def test_stability_settings_reject_invalid_values(self):
        for invalid in (math.nan, math.inf, 0, 0.0009, 5.001):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.logic.configure_temperature_stability(invalid, 5, 2)
        for invalid in (0, 1, 101, 1.5, True):
            with self.subTest(stable_samples=invalid):
                with self.assertRaises(ValueError):
                    self.logic.configure_temperature_stability(0.05, invalid, 2)
        for invalid in (math.nan, math.inf, 0, 0.49, 60.1):
            with self.subTest(poll_interval_s=invalid):
                with self.assertRaises(ValueError):
                    self.logic.configure_temperature_stability(0.05, 5, invalid)
        for invalid in (math.nan, 0, 0.000009, 0.101):
            with self.subTest(field_tolerance=invalid):
                with self.assertRaises(ValueError):
                    self.logic.configure_field_stability(invalid, 5, 2)
        self.assertEqual(self.logic.temperature_stability.tolerance, 0.05)
        self.assertEqual(self.logic.field_stability.tolerance, 0.001)

    def test_temperature_wait_snapshots_settings_before_starting_control(self):
        def change_settings(_target):
            self.logic.configure_temperature_stability(0.5, 2, 0.5)
            return 10.0

        with (
            mock.patch.object(self.logic, "set_T", side_effect=change_settings),
            mock.patch.object(
                self.logic, "_wait_for_stability", return_value=10.0
            ) as wait_for_stability,
        ):
            self.logic.set_T_stable(10.0)
        self.assertEqual(wait_for_stability.call_args.kwargs["tolerance"], 0.05)
        self.assertEqual(wait_for_stability.call_args.kwargs["stable_samples"], 5)
        self.assertEqual(wait_for_stability.call_args.kwargs["poll_interval_s"], 2)
        self.assertEqual(self.logic.temperature_stability.tolerance, 0.5)

    def test_stop_interrupts_wait_without_stopping_controller(self):
        self.logic.request_stop()
        with mock.patch.object(self.logic, "get_T", return_value=5.0):
            result = self.logic._wait_for_stability(
                quantity="temperature",
                target=10.0,
                tolerance=0.01,
                stable_samples=5,
                poll_interval_s=0.5,
                timeout_s=1,
                reader=self.logic.get_T,
                unit="K",
            )
        self.assertEqual(result, 5.0)
        self.assertEqual(self.hardware._device.sample.control_calls, 0)

    def test_field_stable_wait_requires_controller_sequence_to_finish(self):
        readings = iter([0.5, 1.0, 1.0, 1.0])
        controller_active = iter([True, False, False])
        accepted = self.logic.configure_field_stability(0.001, 2, 0.5)
        self.assertEqual(
            (accepted.tolerance, accepted.stable_samples, accepted.poll_interval_s),
            (0.001, 2, 0.5),
        )
        with (
            mock.patch.object(
                self.logic,
                "_read_field_with_state",
                side_effect=lambda: next(readings),
            ),
            mock.patch.object(
                self.hardware,
                "field_control_active",
                side_effect=lambda: next(controller_active),
            ),
            mock.patch.object(self.logic._stop_requested, "wait", return_value=False),
        ):
            result = self.logic.set_B_stable(1.0)
        self.assertEqual(result, 1.0)

    def test_field_wait_snapshots_settings_before_starting_control(self):
        def change_settings(_target):
            self.logic.configure_field_stability(0.1, 2, 0.5)
            return 1.0

        with (
            mock.patch.object(self.logic, "set_B", side_effect=change_settings),
            mock.patch.object(
                self.logic, "_wait_for_stability", return_value=1.0
            ) as wait_for_stability,
        ):
            self.logic.set_B_stable(1.0)
        self.assertEqual(wait_for_stability.call_args.kwargs["tolerance"], 0.001)
        self.assertEqual(wait_for_stability.call_args.kwargs["stable_samples"], 5)
        self.assertEqual(wait_for_stability.call_args.kwargs["poll_interval_s"], 2)
        self.assertEqual(self.logic.field_stability.tolerance, 0.1)

    def test_scan_lifecycle_suspends_then_resumes_monitoring(self):
        self.logic.stop_scan()
        self.assertFalse(self.logic.monitor_enabled)
        self.logic.request_stop()
        self.logic.start_scan()
        self.assertTrue(self.logic.monitor_enabled)
        self.assertFalse(self.logic._stop_requested.is_set())


class AttoDryConfigurationTests(unittest.TestCase):
    def test_global_scan_limits_match_device_limits(self):
        repository_root = Path(__file__).resolve().parents[3]
        with (repository_root / "scan_range_limits.json").open(
            encoding="utf-8"
        ) as stream:
            payload = json.load(stream)
        limits = {
            (item["device_name"], item["channel"]): (
                item["low_limit"],
                item["high_limit"],
            )
            for item in payload["limits"]
        }
        self.assertEqual(limits[("attodry", "T")], (1.8, 300.0))
        self.assertEqual(limits[("attodry", "T_stable")], (1.8, 300.0))
        self.assertEqual(limits[("attodry", "B")], (-9.0, 9.0))
        self.assertEqual(limits[("attodry", "B_stable")], (-9.0, 9.0))


class AttoDryWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_widget_constructs_without_importing_or_connecting_vendor_api(self):
        hardware = AttoDryHardware(
            lambda _address: (_ for _ in ()).throw(
                AssertionError("unexpected hardware construction")
            )
        )
        widget = AttoDry(AttoDryLogic(hardware))
        self.assertEqual(widget.connection_label.text(), "Disconnected")
        self.assertEqual(widget.temperature_spinBox.minimum(), 1.8)
        self.assertEqual(widget.temperature_tolerance_spinBox.value(), 0.05)
        self.assertEqual(widget.temperature_tolerance_spinBox.maximum(), 5.0)
        self.assertEqual(widget.temperature_stable_samples_spinBox.value(), 5)
        self.assertEqual(widget.temperature_poll_interval_spinBox.value(), 2.0)
        self.assertEqual(widget.field_spinBox.maximum(), 9.0)
        self.assertEqual(widget.field_tolerance_spinBox.value(), 0.001)
        self.assertEqual(widget.field_stable_samples_spinBox.value(), 5)
        self.assertEqual(widget.field_poll_interval_spinBox.value(), 2.0)
        widget.temperature_tolerance_spinBox.setValue(0.2)
        widget.temperature_stable_samples_spinBox.setValue(3)
        widget.temperature_poll_interval_spinBox.setValue(4.0)
        widget._configure_temperature_stability()
        self.assertEqual(widget.logic.temperature_stability.tolerance, 0.2)
        self.assertEqual(widget.logic.temperature_stability.stable_samples, 3)
        self.assertEqual(widget.logic.temperature_stability.poll_interval_s, 4.0)
        widget.field_tolerance_spinBox.setValue(0.01)
        widget.field_stable_samples_spinBox.setValue(4)
        widget.field_poll_interval_spinBox.setValue(3.0)
        widget._configure_field_stability()
        self.assertEqual(widget.logic.field_stability.tolerance, 0.01)
        self.assertEqual(widget.logic.field_stability.stable_samples, 4)
        self.assertEqual(widget.logic.field_stability.poll_interval_s, 3.0)
        widget._set_waiting(True, "temperature")
        self.assertFalse(widget.temperature_tolerance_spinBox.isEnabled())
        self.assertTrue(widget.field_tolerance_spinBox.isEnabled())
        widget._set_waiting(False, "temperature")
        self.assertTrue(widget.temperature_tolerance_spinBox.isEnabled())
        widget._set_waiting(True, "field")
        self.assertFalse(widget.field_tolerance_spinBox.isEnabled())
        self.assertTrue(widget.temperature_tolerance_spinBox.isEnabled())
        widget._set_waiting(False, "field")
        self.assertTrue(widget.field_tolerance_spinBox.isEnabled())
        widget.close()


if __name__ == "__main__":
    unittest.main()
