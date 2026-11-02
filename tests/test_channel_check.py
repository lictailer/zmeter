import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core import queue_files
from core.channel_check import (
    ChannelUse,
    catalog_names,
    find_unresolved,
    level_problems,
    replace_channels,
)
from core.scan import Scan
from core.scan_info import ScanInfo
from core.scanlist import ChannelFixDialog, ManualSetItem, ScanList
from tests.test_scan_persistence import _PersistenceMainWindow


SETTERS = {"nidaq_0": ["AO0", "AO1"]}
GETTERS = {"nidaq_0": ["AI0", "AI1"]}


def _info(name="gate_sweep"):
    """A scan using SR860_0 channels, which the test catalog does not have."""
    info = copy.deepcopy(ScanInfo)
    info["name"] = name
    info["comments"] = ""
    info["scan_log"] = []
    level0, level1 = info["levels"]["level0"], info["levels"]["level1"]
    level0["setters"]["setter0"]["channel"] = "SR860_0_X"
    level0["getters"] = ["nidaq_0_AI0", "SR860_0_R"]
    level1["getters"] = ["level0_average_SR860_0_R"]
    level1["manual_set_before"] = [{"SR860_0_ampl": 0.5}]
    info["plots"] = {"line_plots": {}, "image_plots": {}}
    return info


def _clean_info(name="clean"):
    info = copy.deepcopy(ScanInfo)
    info["name"] = name
    info["comments"] = ""
    info["scan_log"] = []
    info["plots"] = {"line_plots": {}, "image_plots": {}}
    return info


class ChannelCheckFunctionTests(unittest.TestCase):
    def test_catalog_names_match_the_menu_names(self):
        self.assertEqual(
            catalog_names({"nidaq_0": ["AO0"], "TLPM": 1, "lockin": [{"X": 1}]}),
            {"nidaq_0_AO0", "TLPM", "lockin_X"},
        )

    def test_find_unresolved_lists_setters_getters_and_manual_sets(self):
        info = _info()
        info["levels"]["level0"]["setters"]["setter1"] = {"channel": "none"}
        info["levels"]["level0"]["setters"]["setter2"] = {"channel": "SR860_0_Y"}
        info["levels"]["level1"]["getters"].append("level0_average_nidaq_0_AI1")
        info["levels"]["level1"]["manual_set_after"] = [{"nidaq_0_AO0": 1.0}]

        uses = find_unresolved(info, catalog_names(SETTERS), catalog_names(GETTERS))

        self.assertEqual(
            uses,
            [
                ChannelUse("setter", "SR860_0_X", "level0 setter A"),
                ChannelUse("setter", "SR860_0_Y", "level0 setter C"),
                ChannelUse("getter", "SR860_0_R", "level0 getter"),
                # AI1 is in the catalog but is not a level0 getter, so the
                # level1 getter menu does not offer its average.
                ChannelUse("getter", "level0_average_nidaq_0_AI1", "level1 getter"),
                ChannelUse("setter", "SR860_0_ampl", "level1 manual set before"),
            ],
        )

    def test_replace_channels_covers_every_place_a_channel_is_named(self):
        info = _info()
        info["levels"]["level0"]["manual_set_after"] = [{"SR860_0_X": 1.0, "nidaq_0_AO0": 2.0}]
        info["plots"] = {
            "line_plots": {"0": {"x": "L0S0_SR860_0_X", "y": "L0G1_SR860_0_R"}},
            "image_plots": {
                "0": {"x": "level0", "y": "level1", "z": "L1G0_level0_average_SR860_0_R"}
            },
        }

        replace_channels(
            info,
            {"SR860_0_X": "nidaq_0_AO1", "SR860_0_ampl": "nidaq_0_AO0"},
            {"SR860_0_R": "nidaq_0_AI1"},
        )

        level0, level1 = info["levels"]["level0"], info["levels"]["level1"]
        self.assertEqual(level0["setters"]["setter0"]["channel"], "nidaq_0_AO1")
        self.assertEqual(level0["getters"], ["nidaq_0_AI0", "nidaq_0_AI1"])
        self.assertEqual(level0["manual_set_after"], [{"nidaq_0_AO1": 1.0, "nidaq_0_AO0": 2.0}])
        self.assertEqual(level1["getters"], ["level0_average_nidaq_0_AI1"])
        self.assertEqual(level1["manual_set_before"], [{"nidaq_0_AO0": 0.5}])
        self.assertEqual(
            info["plots"],
            {
                "line_plots": {"0": {"x": "L0S0_nidaq_0_AO1", "y": "L0G1_nidaq_0_AI1"}},
                "image_plots": {
                    "0": {"x": "level0", "y": "level1", "z": "L1G0_level0_average_nidaq_0_AI1"}
                },
            },
        )

    def test_level_problems(self):
        info = _clean_info()
        for level in info["levels"].values():
            level["setting_array"] = np.zeros((1, 3))
        self.assertEqual(level_problems(info), [])

        info["levels"]["level0"]["setters"]["setter0"]["channel"] = "none"
        info["levels"]["level1"]["setting_array"] = np.zeros((1, 0))
        self.assertEqual(
            level_problems(info),
            [("level0", "no setter channel"), ("level1", "setting array is empty")],
        )
        self.assertEqual(level_problems({"levels": {}}), [("scan", "has no levels")])


class _QtTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory(prefix="zmeter_channels_")
        self.addCleanup(self.temp_directory.cleanup)
        self.output_root = Path(self.temp_directory.name)
        self.main_window = _PersistenceMainWindow(self.output_root)
        self.widgets = []
        self.addCleanup(self._cleanup_widgets)

    def _cleanup_widgets(self):
        for widget in self.widgets:
            if isinstance(widget, ScanList):
                widget.shutdown(timeout_ms=500)
            widget.close()
            widget.deleteLater()
        self.main_window.close()
        self.main_window.deleteLater()
        self.app.processEvents()


class ScanLoadLogTests(_QtTestCase):
    def _load(self, info):
        scan = Scan(
            name="probe",
            info=_clean_info(),
            setter_equipment_info=SETTERS,
            getter_equipment_info=GETTERS,
            main_window=self.main_window,
        )
        self.widgets.append(scan)
        path = self.output_root / "gate_sweep.json"
        path.write_text(json.dumps(info, default=list), encoding="utf-8")
        with mock.patch(
            "core.scan.QFileDialog.getOpenFileName", return_value=(str(path), "")
        ):
            scan.when_load_clicked()
        return scan

    def test_unresolved_channels_are_logged_once_without_changing_the_scan(self):
        scan = self._load(_info())

        history = scan._display_log_history
        start = next(i for i, line in enumerate(history) if "unresolved" in line)
        self.assertIn("[WARNING] 3 unresolved channels in gate_sweep.json:", history[start])
        self.assertEqual(
            history[start + 1 :],
            [
                "  level0 setter A: SR860_0_X",
                "  level0 getter: SR860_0_R",
                "  level1 manual set before: SR860_0_ampl",
            ],
        )
        self.assertEqual(scan.info["scan_log"], [])
        self.assertEqual(scan.info["levels"]["level0"]["setters"]["setter0"]["channel"], "SR860_0_X")

    def test_nothing_is_logged_when_every_channel_resolves(self):
        scan = self._load(_clean_info())
        self.assertNotIn("unresolved", "\n".join(scan._display_log_history))


class QueueChannelTests(_QtTestCase):
    def _scan_list(self):
        scan_list = ScanList(
            info=_clean_info(),
            setter_equipment_info=SETTERS,
            getter_equipment_info=GETTERS,
            main_window=self.main_window,
        )
        self.widgets.append(scan_list)
        return scan_list

    def _saved_queue(self):
        folder = self.output_root / "queue"
        queue_files.save_queue(
            str(folder),
            [
                {"scan": _info("gate_sweep")},
                {"manual_set": {"channel": "SR860_0_ampl", "value": 1.0}},
                {"scan": _info("field_sweep")},
            ],
        )
        return str(folder)

    def _queue_items(self, scan_list):
        return [entry.item for entry in scan_list.queue_model.ordered_queue_entries()]

    def _queue_with_existing_unresolved_scan(self):
        scan_list = self._scan_list()
        existing = scan_list._item_from_saved({"scan": _info("existing"), "path": "existing.json"})
        scan_list.list_queue.add_item(existing)
        return scan_list, existing

    def _choose(self, choices, result=QtWidgets.QDialog.DialogCode.Accepted):
        """Patch the fix window's exec to pick choices and return result."""
        shown = []

        def exec_dialog(dialog):
            shown.append(
                [
                    (dialog.table.cellWidget(row, 0).text(), dialog.table.item(row, 1).text())
                    for row in range(dialog.table.rowCount())
                ]
            )
            for _kind, channel, menu in dialog.rows:
                if channel in choices:
                    menu.set_chosen_one(choices[channel])
            return result

        return shown, mock.patch.object(ChannelFixDialog, "exec", exec_dialog)

    def test_fix_window_lists_each_missing_channel_once_with_queue_positions(self):
        scan_list, _existing = self._queue_with_existing_unresolved_scan()
        shown, patch = self._choose({})
        with patch:
            self.assertEqual(scan_list.load_queue(self._saved_queue()), 3)

        self.assertEqual(
            shown,
            [
                [
                    (
                        "<b>Setter</b>: SR860_0_X",
                        "#2 gate_sweep, level0 setter A; #4 field_sweep, level0 setter A",
                    ),
                    (
                        "<b>Getter</b>: SR860_0_R",
                        "#2 gate_sweep, level0 getter; #4 field_sweep, level0 getter",
                    ),
                    (
                        "<b>Setter</b>: SR860_0_ampl",
                        "#2 gate_sweep, level1 manual set before; #3 manual set; "
                        "#4 field_sweep, level1 manual set before",
                    ),
                ]
            ],
        )

    def test_confirmed_replacements_apply_to_loaded_items_only(self):
        scan_list, existing = self._queue_with_existing_unresolved_scan()
        _shown, patch = self._choose(
            {"SR860_0_X": "nidaq_0_AO1", "SR860_0_R": "nidaq_0_AI1"}
        )
        with patch:
            scan_list.load_queue(self._saved_queue())

        queue = self._queue_items(scan_list)
        self.assertIs(queue[0], existing)
        self.assertEqual(
            existing.scan.info["levels"]["level0"]["setters"]["setter0"]["channel"],
            "SR860_0_X",
        )
        for item in (queue[1], queue[3]):
            levels = item.scan.info["levels"]
            self.assertEqual(levels["level0"]["setters"]["setter0"]["channel"], "nidaq_0_AO1")
            self.assertEqual(levels["level0"]["getters"], ["nidaq_0_AI0", "nidaq_0_AI1"])
            self.assertEqual(levels["level1"]["getters"], ["level0_average_nidaq_0_AI1"])
            self.assertEqual(levels["level1"]["manual_set_before"], [{"SR860_0_ampl": 0.5}])
            self.assertIn(
                "  level1 manual set before: SR860_0_ampl",
                item.scan._display_log_history,
            )
        self.assertEqual(queue[2].channel_name, "SR860_0_ampl")

        log = scan_list.logStatus_textEdit.toPlainText()
        self.assertIn("[WARNING] 3 channels still unresolved after queue load:", log)
        self.assertIn('#2 "gate_sweep" level1 manual set before: SR860_0_ampl', log)
        self.assertIn("#3 manual set: SR860_0_ampl", log)
        self.assertIn('#4 "field_sweep" level1 manual set before: SR860_0_ampl', log)
        self.assertNotIn("SR860_0_X", log)

    def test_canceled_fix_window_leaves_channels_and_still_loads(self):
        scan_list = self._scan_list()
        _shown, patch = self._choose(
            {"SR860_0_X": "nidaq_0_AO1"}, QtWidgets.QDialog.DialogCode.Rejected
        )
        with patch:
            self.assertEqual(scan_list.load_queue(self._saved_queue()), 3)

        first = self._queue_items(scan_list)[0]
        self.assertEqual(
            first.scan.info["levels"]["level0"]["setters"]["setter0"]["channel"],
            "SR860_0_X",
        )
        self.assertIn(
            "7 channels still unresolved", scan_list.logStatus_textEdit.toPlainText()
        )

    def test_resolved_queue_shows_no_fix_window(self):
        scan_list = self._scan_list()
        folder = self.output_root / "clean"
        queue_files.save_queue(str(folder), [{"scan": _clean_info()}])
        with mock.patch.object(ChannelFixDialog, "exec") as exec_dialog:
            self.assertEqual(scan_list.load_queue(str(folder)), 1)
        exec_dialog.assert_not_called()
        self.assertNotIn("unresolved", scan_list.logStatus_textEdit.toPlainText())

    def test_fix_window_replacements(self):
        groups = {
            ("setter", "SR860_0_X"): ["#1 a, level0 setter A"],
            ("getter", "SR860_0_R"): ["#1 a, level0 getter"],
        }
        dialog = ChannelFixDialog(groups, SETTERS, GETTERS)
        self.widgets.append(dialog)
        self.assertEqual(dialog.rows[0][2].button.text(), "leave as is")
        header = dialog.table.horizontalHeader()
        self.assertEqual(
            header.sectionResizeMode(1), QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.assertEqual(dialog.table.columnWidth(2), ChannelFixDialog.MENU_COLUMN_WIDTH)
        self.assertEqual(dialog.rows[0][2].choice_names, {"nidaq_0_AO0", "nidaq_0_AO1"})
        self.assertEqual(dialog.rows[1][2].choice_names, {"nidaq_0_AI0", "nidaq_0_AI1"})
        self.assertEqual(dialog.replacements(), ({}, {}))
        dialog.rows[1][2].set_chosen_one("nidaq_0_AI0")
        self.assertEqual(dialog.replacements(), ({}, {"SR860_0_R": "nidaq_0_AI0"}))

    def _start(self, scan_list):
        with mock.patch.object(QtWidgets.QMessageBox, "warning") as warning, mock.patch.object(
            scan_list.logic, "start"
        ) as start:
            scan_list.start_queue()
        return warning, start

    def test_pre_start_check_blocks_missing_channels(self):
        scan_list = self._scan_list()
        scan_list.list_queue.add_item(
            scan_list._item_from_saved({"scan": _info(), "path": "gate_sweep.json"})
        )
        scan_list.list_queue.add_item(
            ManualSetItem("SR860_0_ampl", 1.0, main_window=self.main_window)
        )

        warning, start = self._start(scan_list)

        start.assert_not_called()
        self.assertFalse(scan_list.queue_model.is_run_active)
        message = warning.call_args.args[2]
        for line in (
            '#1 "gate_sweep" level0 setter A: SR860_0_X is not in the device catalog',
            '#1 "gate_sweep" level0 getter: SR860_0_R is not in the device catalog',
            '#1 "gate_sweep" level1 manual set before: SR860_0_ampl is not in the device catalog',
            "#2 manual set: SR860_0_ampl is not in the device catalog",
        ):
            self.assertIn(line, message)
            self.assertIn(line, scan_list.logStatus_textEdit.toPlainText())
        self.assertIn("Queue not started: 4 problems", scan_list.logStatus_textEdit.toPlainText())

    def test_pre_start_check_blocks_bad_settings(self):
        scan_list = self._scan_list()
        info = _clean_info("repeat")
        info["levels"]["level0"]["setters"]["setter0"]["channel"] = "none"
        scan_list.list_queue.add_item(
            scan_list._item_from_saved({"scan": info, "path": "repeat.json"})
        )
        empty = scan_list._item_from_saved({"scan": _clean_info("empty"), "path": "empty.json"})
        level1 = empty.scan.all_level_setting.verticalLayout.itemAt(1).widget()
        level1.enable_setting_method_checkBox.setChecked(True)
        level1.setting_method_le.setText("Z")
        scan_list.list_queue.add_item(empty)

        warning, start = self._start(scan_list)

        start.assert_not_called()
        message = warning.call_args.args[2]
        self.assertIn('#1 "repeat" level0: no setter channel', message)
        self.assertIn('#2 "empty" level1: setting array is empty', message)
        self.assertNotIn("not in the device catalog", message)

    def test_clean_queue_starts(self):
        scan_list = self._scan_list()
        scan_list.list_queue.add_item(
            scan_list._item_from_saved({"scan": _clean_info(), "path": "clean.json"})
        )
        scan_list.list_queue.add_item(
            ManualSetItem("nidaq_0_AO0", 1.0, main_window=self.main_window)
        )

        warning, start = self._start(scan_list)

        warning.assert_not_called()
        start.assert_called_once_with()
        # Undo the run the patched thread never started, as start_queue does on failure.
        scan_list.queue_model.request_stop_now()
        scan_list.queue_model.claim_next()
        scan_list._queue_completion_delivered = True


if __name__ == "__main__":
    unittest.main()
