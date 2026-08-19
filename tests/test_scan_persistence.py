import copy
import json
import math
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.mainWindow import MainWindow
from core.scan import Scan
from core.scan_info import ScanInfo


class _PersistenceMainWindow(QtWidgets.QWidget):
    _serial_regex = MainWindow._serial_regex
    _serial_folder = MainWindow._serial_folder
    update_serial_counter = MainWindow.update_serial_counter

    def __init__(self, output_root):
        super().__init__()
        self.save_path = str(output_root)
        self.backup_bool = False
        self.save_info_path = QtWidgets.QPlainTextEdit(self.save_path, self)
        self.ppt_path = QtWidgets.QPlainTextEdit(
            str(output_root / "must-not-be-created.pptx"), self
        )
        self.backup_path = QtWidgets.QPlainTextEdit("", self)
        self.backup_Path = self.backup_path
        self.scanlist = SimpleNamespace(serial=QtWidgets.QSpinBox(self))
        self.scanlist.serial.setRange(0, 9999)


class ScanPersistenceCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory(prefix="zmeter_gate_f_")
        self.addCleanup(self.temp_directory.cleanup)
        self.output_root = Path(self.temp_directory.name)
        self.main_window = _PersistenceMainWindow(self.output_root)

        info = copy.deepcopy(ScanInfo)
        info["plots"] = {"line_plots": {}, "image_plots": {}}
        self.scan = Scan(
            name="scalar_probe",
            info=info,
            setter_equipment_info={},
            getter_equipment_info={},
            main_window=self.main_window,
        )
        self.addCleanup(self._cleanup_widgets)

    def _cleanup_widgets(self):
        self.scan.close()
        self.scan.deleteLater()
        self.main_window.close()
        self.main_window.deleteLater()
        self.app.processEvents()

    @contextmanager
    def _blocked_external_outputs(self):
        real_exists = os.path.exists
        z_checks = []

        def isolated_exists(path):
            if str(path).upper().startswith("Z:"):
                z_checks.append(str(path))
                return False
            return real_exists(path)

        with (
            mock.patch("core.scan.os.path.exists", side_effect=isolated_exists),
            mock.patch("core.scan.shutil.copy2") as copy_backup,
            mock.patch("core.scan.add_slide_with_qpixmap") as add_slide,
            mock.patch("core.scan.Presentation") as presentation,
            mock.patch(
                "core.append_to_ppt.win32com.client.Dispatch", create=True
            ) as dispatch,
            mock.patch(
                "core.scan.QFileDialog.getSaveFileName",
                side_effect=AssertionError("unexpected save dialog"),
            ),
        ):
            yield SimpleNamespace(
                z_checks=z_checks,
                copy_backup=copy_backup,
                add_slide=add_slide,
                presentation=presentation,
                dispatch=dispatch,
            )

        copy_backup.assert_not_called()
        add_slide.assert_not_called()
        presentation.assert_not_called()
        dispatch.assert_not_called()
        self.assertFalse((self.output_root / "must-not-be-created.pptx").exists())

    def _set_name(self, name):
        self.scan.lineEdit.setText(name)
        self.scan.info["name"] = name

    def _load(self, path):
        with mock.patch(
            "core.scan.QFileDialog.getOpenFileName",
            return_value=(str(path), ""),
        ):
            self.scan.when_load_clicked()

    def test_populated_scalar_round_trip_preserves_schema_order_nan_and_metadata(self):
        self.main_window.scanlist.serial.setValue(0)
        self._set_name("scalar_probe")
        self.scan.info["data"] = {
            "level0_result": np.array([1.25, np.nan], dtype=np.float64),
            "empty_result": np.array([], dtype=np.float64),
        }
        self.scan.info["plots"] = {"line_plots": {}, "image_plots": {}}
        self.scan.comments_textEdit.setPlainText("gate-f scalar comment")
        self.scan._replace_current_scan_log(["baseline scalar log"])
        plots_per_page_index = self.scan.PlotsPerPage.findText("2")
        if plots_per_page_index >= 0:
            self.scan.PlotsPerPage.setCurrentIndex(plots_per_page_index)

        (self.output_root / "0000_scalar_probe.json").write_text(
            "{}", encoding="utf-8"
        )
        (self.output_root / "0000_scalar_probe_1.json").write_text(
            "{}", encoding="utf-8"
        )

        with self._blocked_external_outputs() as blocked:
            self.scan.when_save_clicked()

        self.assertEqual(blocked.z_checks, [r"Z:\\"])
        saved_path = self.output_root / "0000_scalar_probe_2.json"
        self.assertTrue(saved_path.is_file())
        saved_text = saved_path.read_text(encoding="utf-8")
        saved = json.loads(saved_text)

        self.assertEqual(
            list(saved),
            [
                "levels",
                "data",
                "plots",
                "name",
                "plots_per_page",
                "comments",
                "scan_log",
            ],
        )
        self.assertEqual(saved["name"], "scalar_probe")
        self.assertEqual(saved["comments"], "gate-f scalar comment")
        self.assertEqual(saved["scan_log"], ["baseline scalar log"])
        self.assertEqual(saved["plots"], {"line_plots": {}, "image_plots": {}})
        self.assertIn("setters", saved["levels"]["level0"])
        self.assertIn("getters", saved["levels"]["level0"])
        self.assertEqual(saved["data"]["level0_result"][0], 1.25)
        self.assertTrue(math.isnan(saved["data"]["level0_result"][1]))
        self.assertEqual(saved["data"]["empty_result"], [])
        self.assertIn("NaN", saved_text)
        self.assertNotIn('"NaN"', saved_text)

        self._load(saved_path)
        self.assertEqual(self.scan.info["name"], "scalar_probe")
        self.assertEqual(self.scan.info["comments"], "gate-f scalar comment")
        self.assertEqual(self.scan.info["scan_log"], ["baseline scalar log"])
        self.assertEqual(self.scan.info["plots"], saved["plots"])
        self.assertEqual(list(self.scan.info["levels"]), list(saved["levels"]))
        for level_name, saved_level in saved["levels"].items():
            loaded_level = self.scan.info["levels"][level_name]
            self.assertEqual(list(loaded_level["setters"]), list(saved_level["setters"]))
            self.assertEqual(
                [
                    setter["channel"]
                    for setter in loaded_level["setters"].values()
                ],
                [
                    setter["channel"]
                    for setter in saved_level["setters"].values()
                ],
            )
            self.assertEqual(loaded_level["getters"], saved_level["getters"])
            np.testing.assert_equal(
                np.asarray(loaded_level["setting_array"]),
                np.asarray(saved_level["setting_array"]),
            )
        self.assertEqual(self.scan.info["data"]["level0_result"][0], 1.25)
        self.assertTrue(math.isnan(self.scan.info["data"]["level0_result"][1]))
        self.assertEqual(self.scan.info["data"]["empty_result"], [])

    def test_empty_scalar_round_trip_remains_empty(self):
        self.main_window.scanlist.serial.setValue(5)
        self._set_name("empty_probe")
        self.scan.info["data"] = {}
        self.scan.info["plots"] = {"line_plots": {}, "image_plots": {}}
        self.scan.comments_textEdit.setPlainText("")
        self.scan._replace_current_scan_log([])

        with self._blocked_external_outputs() as blocked:
            self.scan.when_save_clicked()

        self.assertEqual(blocked.z_checks, [r"Z:\\"])
        saved_path = self.output_root / "0005_empty_probe.json"
        saved = json.loads(saved_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["data"], {})
        self._load(saved_path)
        self.assertEqual(self.scan.info["data"], {})

    def test_filename_uniqueness_and_serial_discovery_keep_current_rules(self):
        self.main_window.scanlist.serial.setValue(7)
        self._set_name("collision")
        (self.output_root / "0007_collision.json").write_text("{}", encoding="utf-8")
        (self.output_root / "0007_collision_1.json").write_text(
            "{}", encoding="utf-8"
        )
        self.assertEqual(self.scan._next_unique_data_name(), "0007_collision_2")

        (self.output_root / "0042_data.json").write_text("{}", encoding="utf-8")
        (self.output_root / "0099_any_extension.txt").write_text("", encoding="utf-8")
        (self.output_root / "12345_not_four_digits.json").write_text(
            "{}", encoding="utf-8"
        )
        (self.output_root / "junk.json").write_text("{}", encoding="utf-8")
        self.main_window.update_serial_counter()
        self.assertEqual(self.main_window.scanlist.serial.value(), 100)

        missing = self.output_root / "not-created"
        self.main_window.save_info_path.setPlainText(str(missing))
        self.main_window.update_serial_counter()
        self.assertEqual(self.main_window.scanlist.serial.value(), 0)
        self.assertFalse(missing.exists())

    def test_autosave_is_inert_when_false_then_overwrites_one_canonical_file(self):
        self._set_name("autosave_probe")
        self.scan.info["data"] = {
            "level0_result": np.array([3.5, np.nan], dtype=np.float64)
        }
        self.scan.info["plots"] = {"line_plots": {}, "image_plots": {}}
        self.scan.comments_textEdit.setPlainText("autosave first")
        self.scan._replace_current_scan_log(["before autosave"])
        autosave_path = self.output_root / "autosave.json"

        self.scan.auto_backup(False)
        self.assertFalse(autosave_path.exists())

        with self._blocked_external_outputs() as blocked:
            self.scan.auto_backup(True)
        self.assertEqual(blocked.z_checks, [])
        first = json.loads(autosave_path.read_text(encoding="utf-8"))
        self.assertEqual(first["comments"], "autosave first")
        self.assertEqual(first["data"]["level0_result"][0], 3.5)
        self.assertTrue(math.isnan(first["data"]["level0_result"][1]))
        self.assertIsInstance(first["scan_log"], list)

        self.scan.comments_textEdit.setPlainText("autosave overwrite")
        with self._blocked_external_outputs() as blocked:
            self.scan.auto_backup(True)
        self.assertEqual(blocked.z_checks, [])
        second = json.loads(autosave_path.read_text(encoding="utf-8"))
        self.assertEqual(second["comments"], "autosave overwrite")
        self.assertEqual(
            [path.name for path in self.output_root.glob("autosave*.json")],
            ["autosave.json"],
        )


if __name__ == "__main__":
    unittest.main()
