import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core import queue_settings
from core.scan import read_scan_json
from core.scan_info import ScanInfo
from core.scanlist import ManualSetItem, ScanItem, ScanList
from tests.test_scan_persistence import _PersistenceMainWindow


SETTERS = {"nidaq_0": ["AO0", "AO1"]}
GETTERS = {"nidaq_0": ["AI0", "AI1"]}


def _scan_info():
    info = copy.deepcopy(ScanInfo)
    info["comments"] = ""
    info["scan_log"] = []
    info["plots"] = {"line_plots": {}, "image_plots": {}}
    return info


class QueueSettingFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory(prefix="zmeter_queue_")
        self.addCleanup(self.temp_directory.cleanup)
        self.root = Path(self.temp_directory.name)
        self.main_window = _PersistenceMainWindow(self.root)
        self.addCleanup(self.main_window.deleteLater)

    def _scan_list(self):
        scan_list = ScanList(
            info=_scan_info(),
            setter_equipment_info=SETTERS,
            main_window=self.main_window,
            getter_equipment_info=GETTERS,
        )

        def cleanup():
            scan_list.shutdown(timeout_ms=500)
            scan_list.close()
            scan_list.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup)
        return scan_list

    def _queue_scan(self, scan_list, name):
        item = ScanItem(
            name=name,
            info=_scan_info(),
            setter_equipment_info=SETTERS,
            main_window=self.main_window,
            getter_equipment_info=GETTERS,
        )
        item.scan.lineEdit.setText(name)
        self.assertTrue(scan_list.list_queue.add_item(item))
        return item

    def _save(self, scan_list, folder):
        with mock.patch(
            "core.scanlist.QtWidgets.QFileDialog.getSaveFileName",
            return_value=(str(folder), ""),
        ) as dialog:
            result = scan_list.when_save_queue_setting_clicked()
        return result, dialog

    def _load(self, scan_list, folder):
        with mock.patch(
            "core.scanlist.QtWidgets.QFileDialog.getExistingDirectory",
            return_value=str(folder),
        ):
            return scan_list.when_load_queue_setting_clicked()

    def _queue_summary(self, scan_list):
        summary = []
        for item in scan_list.list_queue.get_widgets():
            if isinstance(item, ManualSetItem):
                summary.append(("manual_set", item.channel_name, item.parsed_value()))
            else:
                summary.append(("scan", item.scan.info["name"], item.text()))
        return summary

    def test_save_writes_numbered_setting_files_in_queue_order(self):
        scan_list = self._scan_list()
        first = self._queue_scan(scan_list, "first")
        first.scan.info["data"] = [[[1.0, 2.0]]]
        scan_list.list_queue.add_item(
            ManualSetItem("nidaq_0_AO1", 0.25, main_window=self.main_window)
        )
        self._queue_scan(scan_list, "second/odd:name")

        folder = self.root / "scan_queue_test"
        result, dialog = self._save(scan_list, folder)

        self.assertEqual(result, str(folder))
        self.assertTrue(
            os.path.basename(dialog.call_args.args[2]).startswith("scan_queue_")
        )
        self.assertEqual(
            sorted(os.listdir(folder)),
            [
                "01_scan_setting_first.json",
                "02_manual_set_nidaq_0_AO1.json",
                "03_scan_setting_second_odd_name.json",
            ],
        )
        first_file = read_scan_json(folder / "01_scan_setting_first.json")
        self.assertEqual(first_file["name"], "first")
        self.assertEqual(first_file["data"], {})
        self.assertEqual(first_file["scan_log"], [])
        manual = json.loads((folder / "02_manual_set_nidaq_0_AO1.json").read_text())
        self.assertEqual(manual, {"manual_set": {"channel": "nidaq_0_AO1", "value": 0.25}})
        # Saving never changes the running scan's data.
        self.assertEqual(first.scan.info["data"], [[[1.0, 2.0]]])

    def test_load_appends_items_in_saved_order(self):
        source = self._scan_list()
        self._queue_scan(source, "first")
        source.list_queue.add_item(
            ManualSetItem("nidaq_0_AO1", 0.25, main_window=self.main_window)
        )
        self._queue_scan(source, "second")
        folder = self.root / "saved_queue"
        self._save(source, folder)

        target = self._scan_list()
        self._queue_scan(target, "already_queued")
        self.assertEqual(self._load(target, folder), 3)

        self.assertEqual(
            self._queue_summary(target),
            [
                ("scan", "already_queued", "already_queued"),
                ("scan", "first", "first"),
                ("manual_set", "nidaq_0_AO1", 0.25),
                ("scan", "second", "second"),
            ],
        )
        self.assertEqual(len(target.queue_model.ordered_queue_entries()), 4)

    def test_order_uses_the_number_not_text_sorting(self):
        folder = self.root / "numbers"
        folder.mkdir()
        info = _scan_info()
        info["levels"]["level0"]["setters"]["setter0"]["destinations"] = [0, 1]
        info["levels"]["level0"]["setters"]["setter0"]["linear_setting"]["destinations"] = [0, 1]
        info["levels"]["level1"]["setters"]["setter0"]["linear_setting"]["destinations"] = [0, 1]
        for number, name in ((10, "ten"), (2, "two")):
            info["name"] = name
            path = folder / f"{number}_scan_setting_{name}.json"
            path.write_text(json.dumps(info, default=list), encoding="utf-8")
        (folder / "notes.txt").write_text("ignored", encoding="utf-8")

        entries = queue_settings.read_queue_folder(folder)

        self.assertEqual([content["name"] for _kind, _path, content in entries], ["two", "ten"])

    def test_missing_device_channels_load_as_unresolved(self):
        source = self._scan_list()
        item = self._queue_scan(source, "uses_sr860")
        item.scan.info["levels"]["level0"]["getters"] = ["SR860_0_R"]
        folder = self.root / "missing_device"
        self._save(source, folder)

        target = self._scan_list()
        self._load(target, folder)

        loaded = target.list_queue.get_widgets()[0]
        level = loaded.scan.all_level_setting.verticalLayout.itemAt(0).widget()
        self.assertEqual(level.record_label.text(), "Record: SR860_0_R (unresolved)")
        self.assertEqual(loaded.scan.info["levels"]["level0"]["getters"], ["SR860_0_R"])

    def test_save_refuses_a_folder_that_is_not_empty(self):
        scan_list = self._scan_list()
        self._queue_scan(scan_list, "first")
        folder = self.root / "used"
        folder.mkdir()
        (folder / "keep.txt").write_text("keep", encoding="utf-8")

        result, _dialog = self._save(scan_list, folder)

        self.assertIsNone(result)
        self.assertEqual(os.listdir(folder), ["keep.txt"])

    def test_empty_queue_or_canceled_dialog_writes_nothing(self):
        scan_list = self._scan_list()
        result, dialog = self._save(scan_list, self.root / "empty")
        self.assertIsNone(result)
        dialog.assert_not_called()

        self._queue_scan(scan_list, "first")
        result, _dialog = self._save(scan_list, "")
        self.assertIsNone(result)
        self.assertEqual(os.listdir(self.root), [])

    def test_one_bad_file_loads_nothing(self):
        source = self._scan_list()
        self._queue_scan(source, "first")
        self._queue_scan(source, "second")
        folder = self.root / "broken"
        self._save(source, folder)
        (folder / "02_scan_setting_second.json").write_text("{not json", encoding="utf-8")

        target = self._scan_list()
        self.assertEqual(self._load(target, folder), 0)
        self.assertEqual(target.list_queue.get_widgets(), [])
        self.assertIn("Queue setting load failed", target.logStatus_textEdit.toPlainText())


if __name__ == "__main__":
    unittest.main()
