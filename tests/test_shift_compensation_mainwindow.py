"""Shift Compensation wired into a real MainWindow with two mock devices."""

from __future__ import annotations

import copy
import os
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6 import QtWidgets

import start_zmeter
from core.device_catalog import DeviceCatalogBusyError
from core.device_management import DeviceSnapshot
from core.mainWindow import MainWindow
from core.scan import Scan
from core.scan_info import ScanInfo
from core.shared_runtime import RuntimeServices
from tests.excel_config_fixture import write_test_device_config

SOURCE = "mock_device_1_channel_A"
TARGET = "mock_device_2_channel_B"


def shift(x):
    return 0.1 * np.cos(2 * np.pi * np.asarray(x, dtype=float) / 360.0)


class ShiftCompensationMainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.services = RuntimeServices()
        config_path = write_test_device_config(
            Path(self.temp_directory.name) / "mock.xlsx"
        )
        _profile, self.manager = start_zmeter.create_profile_session(
            self.services, config_path
        )
        self.window = MainWindow(
            info=copy.deepcopy(ScanInfo),
            save_path=self.temp_directory.name,
            backup_main_path=None,
            device_manager=self.manager,
        )
        self.logic = self.window.shift_compensation_logic
        for label in ("mock_device_1", "mock_device_2"):
            hardware = self.window.equips[label].logic.hardware
            if not hardware.connected:
                hardware.connect(f"MOCK::{label}")

    def tearDown(self):
        if not self.window._session_shutdown_complete:
            self.window.shutdown_session()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.services.shutdown()
        self.temp_directory.cleanup()

    def _fitted_mapping(self):
        mapping = self.logic.add_mapping()
        x = np.arange(0.0, 360.0, 20.0)
        self.logic.set_points(mapping.mapping_id, x, shift(x))
        self.logic.update_mapping(
            mapping.mapping_id,
            source_set=SOURCE,
            source_read=SOURCE,
            target_set=TARGET,
            target_read=TARGET,
        )
        self.logic.fit(mapping.mapping_id, model="cosine", options={"period": 360.0})
        return mapping

    def _activate(self, mapping):
        return self.window.apply_shift_compensation_change(
            lambda: self.logic.activate(mapping.mapping_id)
        )

    def test_activation_publishes_and_deactivation_removes_channels(self):
        self.assertNotIn("compensated_source", self.window.setter_equipment_info)
        mapping = self._fitted_mapping()
        self._activate(mapping)
        self.assertEqual(self.window.setter_equipment_info["compensated_source"], [SOURCE])
        self.assertEqual(self.window.setter_equipment_info["compensated_target"], [TARGET])
        self.assertEqual(self.window.getter_equipment_info["compensated_target"], [TARGET])
        self.assertIn("compensated_target", self.window.get_device_channel_catalog())

        self.window.write_info(0.0, SOURCE)
        self.window.write_info(0.5, TARGET)
        self.assertTrue(self.window.write_info(90.0, f"compensated_source_{SOURCE}"))
        # The mock devices add a little readback noise.
        self.assertAlmostEqual(self.window.read_info(SOURCE), 90.0, delta=0.01)
        self.assertAlmostEqual(
            self.window.read_info(f"compensated_target_{TARGET}"),
            0.5 + float(shift(90.0) - shift(0.0)),
            delta=0.01,
        )

        self.window.apply_shift_compensation_change(
            lambda: self.logic.deactivate(mapping.mapping_id)
        )
        self.assertNotIn("compensated_source", self.window.setter_equipment_info)
        self.assertNotIn("compensated_target", self.window.get_device_channel_catalog())

    def test_refused_change_restores_the_mapping_state(self):
        mapping = self._fitted_mapping()
        with mock.patch.object(
            self.window,
            "_ensure_catalog_mutation_idle",
            side_effect=DeviceCatalogBusyError(("queue thread",)),
        ):
            with self.assertRaises(DeviceCatalogBusyError):
                self._activate(mapping)
        self.assertFalse(self.logic.get(mapping.mapping_id).active)
        self.assertNotIn("compensated_source", self.window.setter_equipment_info)

    def test_removed_device_deactivates_instead_of_blocking(self):
        mapping = self._fitted_mapping()
        self._activate(mapping)
        self.assertEqual(self.window.find_channel_references({TARGET}), ())
        base = self.manager.snapshot()
        kept = ("mock_device_1",)
        snapshot = DeviceSnapshot(
            profile_name="shift-test",
            records=(),
            equipment={label: base.equipment[label] for label in kept},
            setter_filters={label: base.setter_filters.get(label) for label in kept},
            getter_filters={label: base.getter_filters.get(label) for label in kept},
        )
        self.window._apply_device_snapshot_for_testing_or_legacy(snapshot)
        current = self.logic.get(mapping.mapping_id)
        self.assertFalse(current.active)
        self.assertIn("not available", current.note)
        self.assertNotIn("compensated_target", self.window.setter_equipment_info)

    def test_busy_reason_names_the_blocker(self):
        self.assertEqual(self.window._shift_compensation_busy_reason(), "")
        with mock.patch.object(
            self.window,
            "_ensure_catalog_mutation_idle",
            side_effect=DeviceCatalogBusyError(("queue thread",)),
        ):
            self.assertEqual(self.window._shift_compensation_busy_reason(), "queue thread")

    def test_write_and_read_are_recorded(self):
        record = self.window.channel_value_record
        self.assertTrue(self.window.write_info(1.25, SOURCE))
        self.assertEqual(record.latest_write(SOURCE).value, 1.25)
        value = self.window.read_info(TARGET)
        self.assertEqual(record.latest_reading(TARGET).value, float(value))
        self.assertFalse(self.window.write_info(float("nan"), SOURCE))

    def test_scan_range_denial_returns_false_and_is_not_recorded(self):
        self.window.active_scan_range_limits = {("mock_device_1", "channel_A"): (0.0, 1.0)}
        self.assertFalse(self.window.write_info(5.0, SOURCE))
        self.assertIsNone(self.window.channel_value_record.latest_write(SOURCE))

    def test_window_lists_raw_channels_only(self):
        mapping = self._fitted_mapping()
        self._activate(mapping)
        self.window.open_shift_compensation_window()
        window = self.window.shift_compensation_window
        self.assertIsNotNone(window)
        labels = {next(iter(choice)) for choice in window._setter_choices}
        self.assertIn("mock_device_1", labels)
        self.assertNotIn("compensated_source", labels)
        self.assertNotIn("default", labels)
        block = window.block(mapping.mapping_id)
        self.assertTrue(block.active_check.isChecked())
        self.assertFalse(block.fit_button.isEnabled())
        window.close()

    def test_scan_record_and_participating_devices(self):
        mapping = self._fitted_mapping()
        self._activate(mapping)
        fake_scan = types.SimpleNamespace(
            main_window=self.window,
            info={"name": "qwp_map"},
        )
        lines = Scan._begin_shift_compensation_record(fake_scan)
        self.assertEqual(len(lines), 1)
        record = fake_scan._shift_compensation_record
        self.assertEqual(record["scan"]["name"], "qwp_map")
        self.assertEqual(len(record["active"]), 1)

        reference = types.SimpleNamespace(
            kind="setter", channel=f"compensated_target_{TARGET}", access="set"
        )
        fake_scan.channel_references = lambda: [reference]
        self.assertEqual(
            Scan._resolve_participating_device_ids(fake_scan),
            ("mock_device_1", "mock_device_2"),
        )

        payload = Scan._add_shift_compensation_record(fake_scan, {"name": "qwp_map"})
        self.assertEqual(payload["shift_compensation"]["scan"]["name"], "qwp_map")
        self.assertIsNot(payload["shift_compensation"], record)
        self.assertNotIn("shift_compensation", fake_scan.info)

    def test_record_without_active_mappings_is_empty(self):
        fake_scan = types.SimpleNamespace(main_window=self.window, info={})
        self.assertEqual(Scan._begin_shift_compensation_record(fake_scan), [])
        payload = Scan._add_shift_compensation_record(fake_scan, {})
        self.assertEqual(payload["shift_compensation"]["active"], [])
        self.assertIn("recorded_at", payload["shift_compensation"])


if __name__ == "__main__":
    unittest.main()
