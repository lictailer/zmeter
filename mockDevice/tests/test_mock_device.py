import inspect
import math
import os
import threading
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from mockDevice.mock_device_hardware import MockDeviceHardware
from mockDevice.mock_device_logic import MockDeviceLogic
from mockDevice.mock_device_main import MockDevice
from mockDevice.mock_device_simulator import (
    MockDeviceCommandError,
    MockDeviceConnectionError,
    MockDeviceRangeError,
    MockDeviceSimulator,
)


class MockDeviceSimulatorTests(unittest.TestCase):
    def setUp(self):
        self.simulator = MockDeviceSimulator(random_seed=100)
        self.simulator.connect("MOCK::TEST")

    def tearDown(self):
        self.simulator.disconnect()

    def test_connection_lifecycle_and_disconnected_error(self):
        self.assertTrue(self.simulator.connected)
        self.simulator.disconnect()
        self.assertFalse(self.simulator.connected)
        with self.assertRaises(MockDeviceConnectionError):
            self.simulator.read_channel("A")

        self.simulator.connect("MOCK::SECOND")
        self.assertTrue(self.simulator.connected)
        self.assertEqual(self.simulator.address, "MOCK::SECOND")

    def test_direct_set_and_noisy_read(self):
        self.assertEqual(self.simulator.set_channel("A", 2.5), 2.5)

        measured = self.simulator.read_channel("A")

        self.assertNotEqual(measured, 2.5)
        self.assertLess(abs(measured - 2.5), 0.01)

    def test_random_channel_is_reproducible(self):
        other = MockDeviceSimulator(random_seed=100)
        other.connect("MOCK::OTHER")
        try:
            self.assertEqual(
                self.simulator.read_random_channel(),
                other.read_random_channel(),
            )
        finally:
            other.disconnect()

    def test_ramp_uses_fixed_rate_and_lands_exactly_on_target(self):
        self.assertEqual(self.simulator.RAMP_STEP, 0.01)
        self.assertEqual(self.simulator.RAMP_INTERVAL_SECONDS, 0.001)

        progress_values = []
        log_length_before_ramp = len(self.simulator.command_log)
        value, aborted = self.simulator.ramp_channel(
            "A", 0.025, progress_values.append
        )
        reverse_value, reverse_aborted = self.simulator.ramp_channel("A", -0.014)

        self.assertFalse(aborted)
        self.assertFalse(reverse_aborted)
        self.assertEqual(value, 0.025)
        self.assertEqual(reverse_value, -0.014)
        self.assertEqual(progress_values, [0.01, 0.02, 0.025])
        self.assertEqual(len(self.simulator.command_log) - log_length_before_ramp, 4)

    def test_emergency_stop_preserves_last_completed_ramp_step(self):
        result = {}
        progress_values = []
        first_step_completed = threading.Event()

        def report_progress(value):
            progress_values.append(value)
            first_step_completed.set()

        def run_ramp():
            result["value"], result["aborted"] = self.simulator.ramp_channel(
                "A", 2.0, report_progress
            )

        worker = threading.Thread(target=run_ramp)
        worker.start()
        self.assertTrue(first_step_completed.wait(timeout=0.5))

        self.assertTrue(self.simulator.force_stop())
        worker.join(timeout=1.0)

        self.assertFalse(worker.is_alive())
        self.assertTrue(result["aborted"])
        self.assertGreaterEqual(result["value"], 0.0)
        self.assertLess(result["value"], 2.0)
        self.assertEqual(result["value"], progress_values[-1])

    def test_start_scan_clears_an_old_ramp_stop_request(self):
        self.simulator._ramp_stop.set()
        self.simulator.start_scan()

        value, aborted = self.simulator.ramp_channel("A", 0.02)

        self.assertFalse(aborted)
        self.assertEqual(value, 0.02)

    def test_fail_after_n_is_one_shot(self):
        self.simulator.activate_fail_after(3)
        self.simulator.set_channel("A", 1.0)
        self.simulator.read_channel("A")

        with self.assertRaises(MockDeviceCommandError):
            self.simulator.read_random_channel()

        self.assertIsInstance(self.simulator.read_random_channel(), float)

    def test_random_failure_can_be_enabled_and_stopped(self):
        self.simulator.activate_random_failure(1.0)
        with self.assertRaises(MockDeviceCommandError):
            self.simulator.read_channel("A")

        self.simulator.stop_random_failure()
        self.assertIsInstance(self.simulator.read_channel("A"), float)

    def test_range_rejection_and_invalid_numbers_do_not_change_state(self):
        self.simulator.set_channel("A", 1.0)
        self.simulator.activate_range_rejection()

        with self.assertRaises(MockDeviceRangeError):
            self.simulator.set_channel("A", 11.0)
        self.simulator.stop_range_rejection()
        self.assertLess(abs(self.simulator.read_channel("A") - 1.0), 0.01)

        for invalid_value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(MockDeviceRangeError):
                self.simulator.set_channel("A", invalid_value)

    def test_range_rejection_can_be_disabled(self):
        self.simulator.activate_range_rejection()
        self.simulator.stop_range_rejection()

        self.assertEqual(self.simulator.set_channel("B", 25.0), 25.0)

    def test_reset_restores_values_faults_and_log(self):
        self.simulator.set_channel("A", 3.0)
        self.simulator.activate_fail_after(1)
        self.simulator.activate_random_failure(1.0)
        self.simulator.activate_range_rejection()

        self.simulator.reset()

        self.assertEqual(len(self.simulator.command_log), 1)
        self.assertIn("RESET completed", self.simulator.command_log[0])
        self.assertLess(abs(self.simulator.read_channel("A")), 0.01)
        self.assertEqual(self.simulator.set_channel("B", 20.0), 20.0)

    def test_command_log_is_bounded(self):
        for _ in range(self.simulator.MAX_LOG_ENTRIES + 20):
            self.simulator.read_random_channel()

        self.assertEqual(
            len(self.simulator.command_log), self.simulator.MAX_LOG_ENTRIES
        )


class MockDeviceLogicTests(unittest.TestCase):
    def setUp(self):
        self.logic = MockDeviceLogic(MockDeviceHardware(MockDeviceSimulator(200)))
        self.logic.connect_device("MOCK::LOGIC")

    def tearDown(self):
        self.logic.close()

    def test_scan_discovery_exposes_exact_requested_methods(self):
        scan_methods = {
            name
            for name in dir(self.logic)
            if name.startswith(("get_", "set_"))
            and callable(getattr(self.logic, name))
            and self._has_scan_signature(getattr(self.logic, name), name)
        }

        self.assertEqual(
            scan_methods,
            {
                "set_channel_A",
                "set_channel_B",
                "get_channel_A",
                "get_channel_B",
                "get_random_channel",
                "set_ramp_channel_A",
                "set_ramp_channel_B",
            },
        )

    def test_end_to_end_logic_hardware_simulator_flow(self):
        self.logic.set_channel_A(1.25)
        self.logic.set_channel_B(-0.75)

        self.assertLess(abs(self.logic.get_channel_A() - 1.25), 0.01)
        self.assertLess(abs(self.logic.get_channel_B() + 0.75), 0.01)
        self.assertIsInstance(self.logic.get_random_channel(), float)
        self.assertEqual(self.logic.set_ramp_channel_A(1.27), 1.27)

    def test_ramp_emits_each_step_and_the_final_actual_value(self):
        emitted_values = []
        self.logic.sig_last_set_A.connect(emitted_values.append)

        result = self.logic.set_ramp_channel_A(0.025)

        self.assertEqual(result, 0.025)
        self.assertEqual(emitted_values, [0.01, 0.02, 0.025])

    @staticmethod
    def _has_scan_signature(method, name):
        positional = [
            parameter
            for parameter in inspect.signature(method).parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        return len(positional) == (0 if name.startswith("get_") else 1)


class MockDeviceWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_widget_loads_and_provides_mainwindow_lifecycle(self):
        widget = MockDevice()
        try:
            self.assertEqual(widget.connect("MOCK::WIDGET"), "MOCK::WIDGET")
            widget.start_scan()
            widget.stop_scan()
            self.assertFalse(widget.force_stop())
            self.assertTrue(widget.logic.hardware.connected)
        finally:
            widget.terminate_dev()

        self.assertFalse(widget.logic.hardware.connected)

    def test_closing_window_preserves_connection_and_state(self):
        widget = MockDevice()
        try:
            widget.connect("MOCK::WINDOW")
            widget.logic.set_channel_A(1.25)
            log_before_close = widget.logic.hardware.command_log

            widget.show()
            self.app.processEvents()
            widget.close()
            self.app.processEvents()

            self.assertFalse(widget.isVisible())
            self.assertTrue(widget.logic.hardware.connected)
            self.assertEqual(widget.logic.hardware.command_log, log_before_close)

            widget.show()
            self.app.processEvents()
            self.assertTrue(widget.isVisible())
            self.assertTrue(widget.logic.hardware.connected)
            self.assertEqual(widget.last_set_A_label.text(), "1.25")

            widget.disconnect()
            self.assertFalse(widget.logic.hardware.connected)
        finally:
            widget.terminate_dev()

    def test_terminate_device_disconnects_after_window_close(self):
        widget = MockDevice()
        widget.connect("MOCK::SHUTDOWN")

        widget.close()
        self.assertTrue(widget.logic.hardware.connected)

        widget.terminate_dev()
        self.assertFalse(widget.logic.hardware.connected)


if __name__ == "__main__":
    unittest.main()
