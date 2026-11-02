"""Offscreen tests of the Shift Compensation window and set files."""

from __future__ import annotations

import json
import os
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6 import QtWidgets

from core.shift_compensation.persistence import (
    SET_FORMAT,
    MappingSetError,
    load_set,
    mappings_from_set_payload,
    save_set,
)
from core.shift_compensation.window import ShiftCompensationWindow
from tests.shift_compensation_fixture import FakeLab, g_x


class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.lab = FakeLab()
        self.changes = []
        self.refuse = None
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

        def apply_change(mutate):
            if self.refuse is not None:
                raise self.refuse
            self.changes.append(mutate)
            return mutate()

        self.busy = ""
        self.window = ShiftCompensationWindow(
            logic=self.lab.logic,
            apply_change=apply_change,
            value_record=self.lab.channel_value_record,
            busy_reason=lambda: self.busy,
            default_folder=lambda: self.folder.name,
        )
        self.window.refresh_channel_choices(
            {"rot": ["angle"], "daq": ["AO0", "AO1"]},
            {"rot": ["angle"], "daq": ["AI0", "AI1"]},
        )

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def _csv(self):
        path = os.path.join(self.folder.name, "qwp_to_ao0.csv")
        angles = np.arange(0.0, 360.0, 15.0)
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("angle_deg,add_to_AO0_V\n")
            for angle, value in zip(angles, g_x(angles)):
                stream.write(f"{angle},{value}\n")
        return path

    def _ready_block(self):
        mapping = self.window.add_mapping()
        block = self.window.block(mapping.mapping_id)
        self.assertTrue(block.load_csv(self._csv()))
        block.source_set_menu.set_chosen_one("rot_angle")
        block.source_read_menu.set_chosen_one("rot_angle")
        block.target_set_menu.set_chosen_one("daq_AO0")
        block.target_read_menu.set_chosen_one("daq_AI0")
        block.period_edit.setText("180")
        block.fit_button.click()
        return mapping, block

    def test_block_edits_reach_the_logic(self):
        mapping, block = self._ready_block()
        current = self.lab.logic.get(mapping.mapping_id)
        self.assertEqual(current.channels, ("rot_angle", "rot_angle", "daq_AO0", "daq_AI0"))
        self.assertEqual(len(current.source_values), 24)
        self.assertIsNotNone(current.fit)
        self.assertAlmostEqual(current.fit.params["P"], 180.0)
        self.assertIn("rms", block.result_label.text())
        self.assertEqual(block.x_ref_edit.placeholderText(), "0")

        block.polynomial_radio.setChecked(True)
        self.assertEqual(self.lab.logic.get(mapping.mapping_id).model, "polynomial")
        self.assertTrue(block.polynomial_options.isVisibleTo(block))
        self.assertFalse(block.cosine_options.isVisibleTo(block))
        block.order_spin.setValue(4)
        self.assertEqual(self.lab.logic.get(mapping.mapping_id).options["order"], 4)

        block.x_ref_edit.setText("30")
        block.x_ref_edit.editingFinished.emit()
        self.assertEqual(self.lab.logic.get(mapping.mapping_id).x_ref, 30.0)

    def test_activate_locks_the_block_and_deactivate_unlocks(self):
        mapping, block = self._ready_block()
        block.active_check.click()
        self.assertTrue(self.lab.logic.get(mapping.mapping_id).active)
        self.assertEqual(len(self.changes), 1)
        for widget in (block.fit_button, block.csv_button, block.source_set_menu, block.period_edit):
            self.assertFalse(widget.isEnabled())
        self.assertTrue(block.plot_button.isEnabled())
        self.assertIn("[active]", block.title())

        block.active_check.click()
        self.assertFalse(self.lab.logic.get(mapping.mapping_id).active)
        self.assertTrue(block.fit_button.isEnabled())

    def test_refused_activation_is_reported_and_unchecked(self):
        mapping = self.window.add_mapping()
        block = self.window.block(mapping.mapping_id)
        self.assertFalse(block.active_check.isEnabled())  # no fit yet

        unfit = self.window.add_mapping()
        self.lab.logic.set_points(unfit.mapping_id, [0, 1, 2], [0, 1, 0])
        self.lab.logic.fit(unfit.mapping_id, model="polynomial", options={"order": 1})
        unfit_block = self.window.block(unfit.mapping_id)
        unfit_block.active_check.click()
        self.assertFalse(unfit_block.active_check.isChecked())
        self.assertIn("Not activated", self.window.status_label.text())
        self.assertIn("channel not chosen", self.window.status_label.text())

        mapping, block = self._ready_block()
        self.refuse = RuntimeError("queue thread")
        block.active_check.click()
        self.assertFalse(self.lab.logic.get(mapping.mapping_id).active)
        self.assertFalse(block.active_check.isChecked())
        self.assertIn("queue thread", self.window.status_label.text())

    def test_bad_csv_is_reported(self):
        mapping = self.window.add_mapping()
        path = os.path.join(self.folder.name, "bad.csv")
        with open(path, "w", encoding="utf-8") as stream:
            stream.write("a,b\n1,2\nx,y\n")
        self.assertFalse(self.window.block(mapping.mapping_id).load_csv(path))
        self.assertIn("CSV not loaded", self.window.status_label.text())

    def test_plot_and_value_record_windows_open(self):
        _mapping, block = self._ready_block()
        block.plot_button.click()
        self.assertIsNotNone(block._plot_window)
        self.assertEqual(len(block._plot_window.points.getData()[0]), 24)
        self.assertEqual(len(block._plot_window.residuals.getData()[0]), 24)
        self.lab.write_info(3.0, "rot_angle")
        self.window.record_button.click()
        table = self.window._record_window.table
        self.assertEqual(table.rowCount(), 1)
        self.assertEqual(table.item(0, 0).text(), "rot_angle")

    def test_delete_active_goes_through_apply_change(self):
        mapping, block = self._ready_block()
        block.active_check.click()
        self.assertTrue(self.window.delete_mapping(mapping.mapping_id))
        self.assertEqual(self.lab.logic.mappings(), [])
        self.assertEqual(len(self.changes), 2)
        self.assertEqual(self.window.blocks(), [])

    def test_save_and_load_set(self):
        mapping, block = self._ready_block()
        block.active_check.click()
        path = os.path.join(self.folder.name, "sets", "qwp.json")
        self.assertTrue(self.window.save_set(path))
        with open(path, encoding="utf-8") as stream:
            payload = json.load(stream)
        self.assertEqual(payload["format"], SET_FORMAT)
        self.assertTrue(payload["mappings"][0]["active"])

        changes_before = len(self.changes)
        self.assertTrue(self.window.load_set(path))
        loaded = self.lab.logic.mappings()
        self.assertEqual(len(loaded), 1)
        self.assertTrue(loaded[0].active)
        self.assertEqual(len(self.changes), changes_before + 1)
        self.assertEqual(loaded[0].channels, mapping.channels)
        self.assertAlmostEqual(loaded[0].correction(0, 40), mapping.correction(0, 40))
        self.assertIn("1 active", self.window.status_label.text())

        # A saved active mapping whose channel is gone loads inactive.
        self.lab.logic.set_available_channels(["rot_angle"], FakeLab.GETTERS)
        self.assertTrue(self.window.load_set(path))
        loaded = self.lab.logic.mappings()[0]
        self.assertFalse(loaded.active)
        self.assertIn("loaded inactive", loaded.note)
        self.assertIn("Not activated", self.window.status_label.text())
        self.assertTrue(self.window.block(loaded.mapping_id).note_label.isVisibleTo(self.window))

    def test_editing_is_locked_while_busy(self):
        mapping, block = self._ready_block()
        self.busy = "queue thread"
        self.window.update_busy()
        self.assertFalse(block.fit_button.isEnabled())
        self.assertFalse(block.active_check.isEnabled())
        self.assertFalse(self.window.add_button.isEnabled())
        self.assertFalse(self.window.load_button.isEnabled())
        self.assertIn("queue thread", self.window.busy_label.text())
        self.busy = ""
        self.window.update_busy()
        self.assertTrue(block.fit_button.isEnabled())
        self.assertTrue(block.active_check.isEnabled())

    def test_published_channels_are_listed(self):
        self.assertIn("none", self.window.published_label.text())
        _mapping, block = self._ready_block()
        block.active_check.click()
        self.assertIn("compensated_target_daq_AO0", self.window.published_label.text())
        self.assertIn("compensated_source_rot_angle", self.window.published_label.text())


class PersistenceTests(unittest.TestCase):
    def test_round_trip_and_errors(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "set.json")
            save_set(path, lab.logic.mappings())
            self.assertEqual([name for name in os.listdir(folder)], ["set.json"])
            loaded = load_set(path)
            self.assertEqual(len(loaded), 1)
            self.assertTrue(loaded[0].active)  # re-checked by load_mappings
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("{not json")
            with self.assertRaises(MappingSetError):
                load_set(path)
        with self.assertRaises(MappingSetError):
            mappings_from_set_payload({"format": "other", "version": 1, "mappings": []})
        with self.assertRaises(MappingSetError):
            mappings_from_set_payload({"format": SET_FORMAT, "version": 2, "mappings": []})
        with self.assertRaises(MappingSetError):
            mappings_from_set_payload(
                {"format": SET_FORMAT, "version": 1, "mappings": [{"model": "spline"}]}
            )

    def test_duplicate_ids_are_renamed(self):
        lab = FakeLab()
        mapping = lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        item = mapping.to_dict()
        loaded = mappings_from_set_payload(
            {"format": SET_FORMAT, "version": 1, "mappings": [item, item]}
        )
        self.assertNotEqual(loaded[0].mapping_id, loaded[1].mapping_id)


if __name__ == "__main__":
    unittest.main()
