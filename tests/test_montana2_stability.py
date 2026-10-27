from __future__ import annotations

import math
import os
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from devices.montana2 import montana2_logic
from devices.montana2.montana2_logic import (
    STABLE_WINDOW_POINTS,
    Montana2Logic,
    is_temperature_stable,
    stability_thresholds,
)


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.sleeps_ms = []

    def time(self):
        return self.now

    def msleep(self, ms):
        self.sleeps_ms.append(ms)
        self.now += ms / 1000.0


class FakeHardware:
    def __init__(self, readings, controller_stable=False):
        self.readings = list(readings)
        self.reads = 0
        self.targets = []
        self.controller_stable = controller_stable
        self.on_read = None

    def set_platform_target_temperature(self, target):
        self.targets.append(target)
        return True

    def get_platform_temperature(self):
        self.reads += 1
        if self.on_read is not None:
            self.on_read(self.reads)
        if self.readings:
            return self.readings.pop(0)
        return float("nan")

    def get_platform_temperature_stable(self):
        return self.controller_stable

    def get_stage1_temperature(self):
        return 42.5


class StabilityRuleTests(unittest.TestCase):
    def test_thresholds_follow_four9_formula(self):
        avg_threshold, std_threshold = stability_thresholds(50.0, 0.5, 1.0)
        base = math.sqrt(150.0) / 50.0
        self.assertAlmostEqual(avg_threshold, 0.5 * base)
        self.assertAlmostEqual(std_threshold, base)

    def test_target_below_3k_is_stable_right_away(self):
        self.assertTrue(is_temperature_stable([], 2.9, 0.5, 1.0))
        self.assertFalse(is_temperature_stable([], 3.0, 0.5, 1.0))

    def test_needs_a_full_window(self):
        readings = [10.0] * (STABLE_WINDOW_POINTS - 1)
        self.assertFalse(is_temperature_stable(readings, 10.0, 0.5, 1.0))
        self.assertTrue(is_temperature_stable(readings + [10.0], 10.0, 0.5, 1.0))

    def test_mean_offset_and_spread_limits(self):
        avg_threshold, std_threshold = stability_thresholds(10.0, 0.5, 1.0)
        offset = [10.0 + 1.2 * avg_threshold] * STABLE_WINDOW_POINTS
        self.assertFalse(is_temperature_stable(offset, 10.0, 0.5, 1.0))
        self.assertTrue(is_temperature_stable(offset, 10.0, 1.0, 1.0))

        # Alternating +-a has population std a and mean equal to target.
        spread = [10.0 + (1.2 * std_threshold) * (-1) ** i for i in range(STABLE_WINDOW_POINTS)]
        self.assertFalse(is_temperature_stable(spread, 10.0, 0.5, 1.0))
        self.assertTrue(is_temperature_stable(spread, 10.0, 0.5, 1.5))

    def test_only_latest_window_counts(self):
        readings = [50.0] * 30 + [10.0] * STABLE_WINDOW_POINTS
        self.assertTrue(is_temperature_stable(readings, 10.0, 0.5, 1.0))


class StableWaitTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        fake_qtcore = SimpleNamespace(QThread=SimpleNamespace(msleep=self.clock.msleep))
        patches = (
            mock.patch.object(montana2_logic, "QtCore", fake_qtcore),
            mock.patch.object(montana2_logic.time, "time", self.clock.time),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def make_logic(self, hardware):
        logic = Montana2Logic()
        logic.hardware = hardware
        logic.is_connected = True
        self.status = []
        self.stable_flags = []
        logic.sig_status.connect(self.status.append)
        logic.sig_platform_temperature_stable_bool.connect(self.stable_flags.append)
        return logic

    def test_defaults(self):
        logic = Montana2Logic()
        self.assertEqual(logic.stable_wait_timeout_s, 60 * 60)
        self.assertEqual(logic.stable_avg_multiplier, 0.5)
        self.assertEqual(logic.stable_std_multiplier, 1.0)

    def test_waits_for_full_window_then_buffer(self):
        hardware = FakeHardware([False, None] + [20.0] * STABLE_WINDOW_POINTS)
        logic = self.make_logic(hardware)

        logic.set_platform_target_temperature_to_stable(20.0)

        self.assertEqual(hardware.targets, [20.0])
        # Two failed reads are skipped, then 60 valid readings fill the window.
        self.assertEqual(hardware.reads, STABLE_WINDOW_POINTS + 2)
        self.assertTrue(self.stable_flags[-1])
        self.assertFalse(any(self.stable_flags[:-1]))
        self.assertEqual(self.clock.sleeps_ms[-1], logic.set_temperature_buffer_time_s * 1000)
        self.assertIn("Buffer time completed.", self.status)

    def test_controller_flag_is_not_used_for_the_wait(self):
        hardware = FakeHardware([25.0] * 5, controller_stable=True)
        hardware.get_platform_temperature_stable = mock.Mock(
            side_effect=AssertionError("controller flag used")
        )
        logic = self.make_logic(hardware)
        logic.stable_wait_timeout_s = 3

        logic.set_platform_target_temperature_to_stable(20.0)

        self.assertTrue(any(message.startswith("Timeout") for message in self.status))
        self.assertNotIn("Buffer time completed.", self.status)

    def test_timeout_reports_window_once_a_minute(self):
        hardware = FakeHardware([30.0] * 200)
        logic = self.make_logic(hardware)
        logic.stable_wait_timeout_s = 150

        logic.set_platform_target_temperature_to_stable(20.0)

        reports = [m for m in self.status if m.startswith("Not stable yet")]
        self.assertEqual(len(reports), 2)
        self.assertTrue(any(m.startswith("Timeout") for m in self.status))
        self.assertNotIn("Buffer time completed.", self.status)

    def test_user_stop_ends_wait(self):
        hardware = FakeHardware([30.0] * 10)
        logic = self.make_logic(hardware)
        hardware.on_read = lambda reads: setattr(logic, "stable_wait_stop", reads == 3 or logic.stable_wait_stop)

        logic.set_platform_target_temperature_to_stable(20.0)

        self.assertEqual(hardware.reads, 3)
        self.assertIn("Wait till stable interrupted by user.", self.status)
        self.assertFalse(logic.stable_wait_stop)

    def test_target_below_3k_is_stable_on_first_reading(self):
        hardware = FakeHardware([4.2])
        logic = self.make_logic(hardware)

        logic.set_platform_target_temperature_to_stable(2.5)

        self.assertEqual(hardware.reads, 1)
        self.assertEqual(self.stable_flags, [True])
        self.assertIn("Buffer time completed.", self.status)

    def test_multiplier_update_applies_to_running_wait(self):
        avg_threshold, _ = stability_thresholds(20.0, 0.5, 1.0)
        hardware = FakeHardware([20.0 + 1.5 * avg_threshold] * 200)
        logic = self.make_logic(hardware)
        hardware.on_read = lambda reads: (
            logic.update_stability_multipliers(1.0, 1.0) if reads == 90 else None
        )

        logic.set_platform_target_temperature_to_stable(20.0)

        self.assertEqual(hardware.reads, 90)
        self.assertTrue(self.stable_flags[-1])

    def test_multiplier_update_rejects_invalid_values(self):
        logic = self.make_logic(FakeHardware([]))
        for avg, std in ((0, 1), (0.5, -1), (float("nan"), 1)):
            with self.subTest(avg=avg, std=std), self.assertRaises(ValueError):
                logic.update_stability_multipliers(avg, std)
        self.assertEqual((logic.stable_avg_multiplier, logic.stable_std_multiplier), (0.5, 1.0))

    def test_multiplier_update_is_not_a_scan_channel(self):
        channels = [name for name in dir(Montana2Logic) if name.startswith(("get_", "set_"))]
        self.assertEqual(
            sorted(channels),
            sorted([
                "get_platform_temperature",
                "get_stage1_temperature",
                "get_platform_target_temperature",
                "get_platform_temperature_stable",
                "set_platform_target_temperature",
                "set_platform_target_temperature_to_stable",
            ]),
        )

    def test_platform_temperature_stable_getter_still_reads_controller(self):
        logic = self.make_logic(FakeHardware([], controller_stable=False))
        self.assertFalse(logic.get_platform_temperature_stable())
        logic.hardware.controller_stable = True
        self.assertTrue(logic.get_platform_temperature_stable())

    def test_stage1_getter_emits_declared_signal(self):
        logic = self.make_logic(FakeHardware([]))
        emitted = []
        logic.sig_stage1_temperature.connect(emitted.append)
        self.assertEqual(logic.get_stage1_temperature(), 42.5)
        self.assertEqual(emitted, [42.5])


class Montana2StabilityUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_ui_defaults(self):
        root = ET.parse(
            Path(__file__).resolve().parents[1] / "devices" / "montana2" / "montana2.ui"
        ).getroot()

        def value(name):
            widget = root.find(f".//widget[@name='{name}']")
            self.assertIsNotNone(widget, name)
            return widget.find("./property[@name='value']/*").text

        self.assertEqual(float(value("stableAvgMultiplier_doubleSpinBox")), 0.5)
        self.assertEqual(float(value("stableStdMultiplier_doubleSpinBox")), 1.0)
        self.assertEqual(int(value("maxStablizingWait_spinBox")), 60)

    def test_update_button_sets_logic_multipliers(self):
        from devices.montana2.montana2_main import Montana2

        with mock.patch(
            "devices.montana2.montana_libs.instrument.requests.get",
            side_effect=AssertionError("Montana network access"),
        ):
            widget = Montana2()
        self.addCleanup(widget.deleteLater)

        widget.stableAvgMultiplier_doubleSpinBox.setValue(0.8)
        widget.stableStdMultiplier_doubleSpinBox.setValue(1.5)
        self.assertEqual(widget.logic.stable_avg_multiplier, 0.5)

        widget.updateStability_pushButton.click()

        self.assertEqual(widget.logic.stable_avg_multiplier, 0.8)
        self.assertEqual(widget.logic.stable_std_multiplier, 1.5)
        self.assertIn("Stability multipliers updated", widget.logStatus_textEdit.toPlainText())


if __name__ == "__main__":
    unittest.main()
