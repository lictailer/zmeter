"""Missing scan-limit warning: which written channels have no scan limit.

Fake catalogs only; no device is constructed and nothing is written.
"""

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from core.mainWindow import MainWindow
from core.scan import Scan


def _noop(_value):
    return None


def _catalog_window(setters, limits):
    window = SimpleNamespace(
        setter_equipment_info_for_scanning=setters,
        active_scan_range_limits=limits,
    )
    window._setter_label_for_channel = (
        lambda channel: MainWindow._setter_label_for_channel(window, channel)
    )
    window.get_variable = lambda channel, label: MainWindow.get_variable(
        window, channel, label
    )
    return window


class ChannelsWithoutScanLimitTests(unittest.TestCase):
    def setUp(self):
        self.window = _catalog_window(
            {
                "nidaq_0": {"AO0": _noop, "AO1": _noop},
                "keithley_0": {"voltage": _noop},
                "default": {"wait": _noop, "count": _noop, "slack_notification": _noop},
                "artificial_channel": {"x": _noop},
                "compensated_source": {"nidaq_0_AO0": _noop},
                "compensated_target": {"nidaq_0_AO1": _noop},
            },
            {("nidaq_0", "AO0"): (-1.0, 1.0)},
        )

    def _missing(self, channels):
        return MainWindow.channels_without_scan_limit(self.window, channels)

    def test_lists_exactly_the_unlimited_physical_channels_once_in_order(self):
        self.assertEqual(
            self._missing(
                ["keithley_0_voltage", "nidaq_0_AO0", "nidaq_0_AO1", "keithley_0_voltage"]
            ),
            ["keithley_0_voltage", "nidaq_0_AO1"],
        )

    def test_nothing_when_all_written_channels_have_limits(self):
        self.window.active_scan_range_limits[("nidaq_0", "AO1")] = (0.0, 2.0)
        self.window.active_scan_range_limits[("keithley_0", "voltage")] = (-5.0, 5.0)
        self.assertEqual(
            self._missing(["nidaq_0_AO0", "nidaq_0_AO1", "keithley_0_voltage"]), []
        )

    def test_virtual_channels_are_skipped(self):
        self.assertEqual(
            self._missing(
                [
                    "default_wait",
                    "default_count",
                    "default_slack_notification",
                    "artificial_channel_x",
                    "compensated_source_nidaq_0_AO0",
                    "compensated_target_nidaq_0_AO1",
                ]
            ),
            [],
        )

    def test_channels_missing_from_the_catalog_are_skipped(self):
        self.assertEqual(self._missing(["sr860_0_amplitude", "nidaq_0_AO7"]), [])

    def test_label_is_resolved_with_the_write_info_prefix_rule(self):
        window = _catalog_window(
            {"lockin": {"0_x": _noop}, "lockin_0": {"x": _noop}},
            {("lockin_0", "x"): (-1.0, 1.0)},
        )
        # write_info takes the first matching label: "lockin", channel "0_x".
        self.assertEqual(
            MainWindow.channels_without_scan_limit(window, ["lockin_0_x"]),
            ["lockin_0_x"],
        )


class WriteInfoLabelTests(unittest.TestCase):
    """write_info keeps its label rule and errors after the label helper split."""

    def setUp(self):
        self.calls = []
        self.logged = []
        self.window = _catalog_window(
            {
                "lockin": {"0_x": lambda value: self.calls.append(("lockin", value))},
                "lockin_0": {"x": lambda value: self.calls.append(("lockin_0", value))},
            },
            {("lockin", "0_x"): (-1.0, 1.0)},
        )
        self.window._is_nan_value = lambda value: MainWindow._is_nan_value(
            self.window, value
        )
        self.window._log_scan_range = lambda level, message: self.logged.append(message)
        self.window.mark_skip_next_scan_read_from_global_limit = lambda: None
        self.window.channel_value_record = None

    def _write(self, value, channel):
        return MainWindow.write_info(self.window, value, channel)

    def test_first_matching_label_receives_the_write(self):
        self.assertTrue(self._write(0.5, "lockin_0_x"))
        self.assertEqual(self.calls, [("lockin", 0.5)])

    def test_limit_denies_the_write(self):
        self.assertFalse(self._write(2.0, "lockin_0_x"))
        self.assertEqual(self.calls, [])
        self.assertIn("Denied write 'lockin_0_x'=2.0", self.logged[0])

    def test_nan_is_skipped(self):
        self.assertFalse(self._write(float("nan"), "lockin_0_x"))
        self.assertEqual(self.calls, [])

    def test_unknown_channel_and_variable_raise(self):
        with self.assertRaisesRegex(KeyError, "No equipment found"):
            self._write(0.1, "keithley_0_voltage")
        with self.assertRaisesRegex(KeyError, "not found in equipment 'lockin'"):
            self._write(0.1, "lockin_1_x")


class ScanWarningTests(unittest.TestCase):
    LEVELS = {
        "level0": {
            "setters": {
                "setter0": {"channel": "nidaq_0_AO0"},
                "setter1": {"channel": "none"},
            },
            "getters": ["nidaq_0_AI0"],
            "manual_set_before": [{"keithley_0_voltage": 0.1}],
            "manual_set_after": [{"default_wait": 1.0}],
        },
        "level1": {
            "setters": {"setter0": {"channel": "nidaq_0_AO1"}},
            "getters": ["none"],
            "manual_set_before": [],
            "manual_set_after": [],
        },
    }

    def _warn(self, check):
        warnings = []
        fake = SimpleNamespace(
            main_window=SimpleNamespace(channels_without_scan_limit=check),
            _log_warning=warnings.append,
            channel_references_from_models=Scan.channel_references_from_models,
            _WRITTEN_REFERENCE_KINDS=Scan._WRITTEN_REFERENCE_KINDS,
        )
        Scan._warn_channels_without_scan_limit(fake, self.LEVELS)
        return warnings

    def test_checks_setters_and_manual_sets_but_not_getters(self):
        seen = []

        def check(channels):
            seen.append(list(channels))
            return ["nidaq_0_AO0", "nidaq_0_AO1"]

        warnings = self._warn(check)
        self.assertEqual(
            sorted(seen[0]),
            ["default_wait", "keithley_0_voltage", "nidaq_0_AO0", "nidaq_0_AO1"],
        )
        self.assertEqual(
            warnings,
            [
                "[ScanRange] No scan limit for nidaq_0_AO0, nidaq_0_AO1; "
                "these writes are not range-checked."
            ],
        )

    def test_no_line_when_every_channel_has_a_limit(self):
        self.assertEqual(self._warn(lambda channels: []), [])

    def test_failing_check_is_a_warning_and_never_raises(self):
        def broken(_channels):
            raise RuntimeError("catalog gone")

        warnings = self._warn(broken)
        self.assertEqual(
            warnings,
            ["[ScanRange] Scan-limit check failed: RuntimeError: catalog gone"],
        )

    def test_main_window_without_the_check_logs_nothing(self):
        fake = SimpleNamespace(main_window=SimpleNamespace(), _log_warning=self.fail)
        Scan._warn_channels_without_scan_limit(fake, self.LEVELS)


if __name__ == "__main__":
    unittest.main()
