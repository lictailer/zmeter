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

from core.all_level import IndividualLevel
from core.scan import Scan, scan_setting_payload
from core.scan_info import ScanInfo
from tests.test_scan_persistence import _PersistenceMainWindow


SETTERS = {"nidaq_0": ["AO0", "AO1"]}
GETTERS = {"nidaq_0": ["AI0", "AI1"]}


def _setting_info():
    info = copy.deepcopy(ScanInfo)
    info["name"] = "gate_sweep"
    level0 = info["levels"]["level0"]
    level0["setters"]["setter0"]["channel"] = "SR860_0_X"
    level0["getters"] = ["nidaq_0_AI0", "SR860_0_R"]
    level0["manual_set_before"] = [{"SR860_0_ampl": 0.5}, {"nidaq_0_AO1": 1.0}]
    info["plots"] = {
        "line_plots": {"0": {"x": "level0", "y": "L0G1_SR860_0_R"}},
        "image_plots": {},
    }
    return info


def _level_widget(scan, index=0):
    return scan.all_level_setting.verticalLayout.itemAt(index).widget()


class ScanSettingFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory(prefix="zmeter_setting_")
        self.addCleanup(self.temp_directory.cleanup)
        self.output_root = Path(self.temp_directory.name)
        self.main_window = _PersistenceMainWindow(self.output_root)
        info = copy.deepcopy(ScanInfo)
        info["plots"] = {"line_plots": {}, "image_plots": {}}
        self.scan = Scan(
            name="setting_probe",
            info=info,
            setter_equipment_info=SETTERS,
            getter_equipment_info=GETTERS,
            main_window=self.main_window,
        )
        self.addCleanup(self._cleanup_widgets)

    def _cleanup_widgets(self):
        self.scan.close()
        self.scan.deleteLater()
        self.main_window.close()
        self.main_window.deleteLater()
        self.app.processEvents()

    def _load(self, path):
        with mock.patch(
            "core.scan.QFileDialog.getOpenFileName",
            return_value=(str(path), ""),
        ):
            self.scan.when_load_clicked()

    def _save_setting(self, path):
        with mock.patch(
            "core.scan.QFileDialog.getSaveFileName",
            return_value=(str(path), ""),
        ) as dialog:
            result = self.scan.when_save_setting_clicked()
        return result, dialog

    def _write(self, name, info):
        path = self.output_root / name
        path.write_text(json.dumps(info, default=list), encoding="utf-8")
        return path

    def test_setting_without_data_key_or_with_empty_data_loads(self):
        for name, data in (("no_data.json", None), ("empty_data.json", {})):
            with self.subTest(name=name):
                info = _setting_info()
                if data is None:
                    info.pop("data", None)
                else:
                    info["data"] = data
                path = self._write(name, info)
                self._load(path)

                self.assertEqual(self.scan.info["data"], {})
                self.assertIsNone(self.scan.last_saved_json_path)
                self.assertEqual(self.scan.lineEdit.text(), "gate_sweep")
                setter = self.scan.info["levels"]["level0"]["setters"]["setter0"]
                self.assertEqual(setter["channel"], "SR860_0_X")
                self.assertEqual(
                    self.scan.info["plots"]["line_plots"]["0"]["y"], "L0G1_SR860_0_R"
                )
                self.assertIn("Loaded scan setting", self.scan._display_log_history[-1])

    def test_missing_channels_are_marked_unresolved_without_rewriting_info(self):
        self._load(self._write("setting.json", _setting_info()))
        level = _level_widget(self.scan)
        setter = level.verticalLayout.itemAt(0).widget()

        self.assertEqual(setter.nested_menu.button.text(), "Unresolved: SR860_0_X")
        self.assertEqual(
            level.record_label.text(),
            "Record: nidaq_0_AI0, SR860_0_R (unresolved)",
        )
        self.assertEqual(
            level.manual_set_before_label.text(),
            "1. SR860_0_ampl (unresolved)->0.5 | 2. nidaq_0_AO1->1.0",
        )
        level0 = self.scan.info["levels"]["level0"]
        self.assertEqual(level0["getters"], ["nidaq_0_AI0", "SR860_0_R"])
        self.assertEqual(list(level0["manual_set_before"][0]), ["SR860_0_ampl"])

        self.scan.all_level_setting.refresh_catalog_choices(
            {**SETTERS, "SR860_0": ["X", "ampl"]},
            {**GETTERS, "SR860_0": ["R"]},
        )
        self.assertEqual(setter.nested_menu.button.text(), "SR860_0_X")
        self.assertEqual(level.record_label.text(), "Record: nidaq_0_AI0, SR860_0_R")
        self.assertEqual(
            level.manual_set_before_label.text(),
            "1. SR860_0_ampl->0.5 | 2. nidaq_0_AO1->1.0",
        )

    def test_average_getter_is_resolved_from_lower_level(self):
        info = _setting_info()
        info["levels"]["level1"]["getters"] = ["level0_average_nidaq_0_AI0"]
        self._load(self._write("setting.json", info))
        self.assertEqual(
            _level_widget(self.scan, 1).record_label.text(),
            "Record: level0_average_nidaq_0_AI0",
        )

    def test_save_setting_round_trip_keeps_settings_and_drops_run_data(self):
        self.main_window.scanlist.serial.setValue(7)
        self.scan.lineEdit.setText("gate_sweep")
        self.scan.info["name"] = "gate_sweep"
        self.scan.info["data"] = {"level0_result": np.array([1.0, np.nan])}
        self.scan.info["setup"] = {"snapshot_start": {"devices": {}}}
        self.scan.info["format_version"] = 2
        self.scan.comments_textEdit.setPlainText("reuse me")
        self.scan._replace_current_scan_log(["old run log"])
        self.scan.questionnaire_tab.enabled_checkBox.setChecked(True)
        levels_before = json.loads(json.dumps(self.scan.info["levels"], default=list))

        target = self.output_root / "scan_setting_gate_sweep.json"
        result, dialog = self._save_setting(target)

        self.assertEqual(result, str(target))
        default_path = dialog.call_args.args[2]
        self.assertEqual(
            default_path, os.path.join(str(self.output_root), "scan_setting_gate_sweep.json")
        )
        saved = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(saved["data"], {})
        self.assertEqual(saved["scan_log"], [])
        self.assertNotIn("setup", saved)
        self.assertEqual(saved["questionnaire"], {"enabled": True, "record": None})
        self.assertEqual(saved["comments"], "reuse me")
        self.assertEqual(saved["name"], "gate_sweep")
        self.assertEqual(saved["levels"].keys(), levels_before.keys())
        self.assertEqual(
            saved["levels"]["level0"]["setters"], levels_before["level0"]["setters"]
        )
        # The in-memory scan keeps its data, and no sidecar or recovery file is made.
        self.assertIn("level0_result", self.scan.info["data"])
        self.assertEqual(sorted(p.name for p in self.output_root.iterdir()), [target.name])
        self.assertEqual(self.main_window.scanlist.serial.value(), 7)

        other_target = self.output_root / "copy"
        self._load(target)
        result, _dialog = self._save_setting(other_target)
        self.assertEqual(result, str(other_target) + ".json")
        resaved = json.loads(Path(result).read_text(encoding="utf-8"))
        self.assertEqual(resaved["levels"], saved["levels"])
        self.assertEqual(resaved["plots"], saved["plots"])

    def test_canceled_setting_save_writes_nothing(self):
        result, _dialog = self._save_setting("")
        self.assertIsNone(result)
        self.assertEqual(list(self.output_root.iterdir()), [])

    def test_payload_without_questionnaire_use_has_no_questionnaire_key(self):
        info = _setting_info()
        info["questionnaire"] = {"enabled": False, "record": {"items": []}}
        self.assertNotIn("questionnaire", scan_setting_payload(info))
        self.assertIn("questionnaire", info)

    def test_data_file_load_is_unchanged(self):
        info = _setting_info()
        info["plots"] = {"line_plots": {}, "image_plots": {}}
        info["data"] = [[[1.0, "NaN"], [2.0, 3.0]]]
        path = self._write("0001_gate_sweep.json", info)
        self._load(path)
        self.assertEqual(self.scan.last_saved_json_path, str(path))
        self.assertTrue(np.isnan(self.scan.info["data"][0][0][1]))
        self.assertIn("Loaded scan JSON", self.scan._display_log_history[-1])


if __name__ == "__main__":
    unittest.main()
