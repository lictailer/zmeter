import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core import queue_files
from core.queue_files import QUEUE_FILE, read_queue
from core.scan import _ScanJSONEncoder, read_scan_file
from core.scan_info import ScanInfo
from core.scanlist import ManualSetItem, ScanItem, ScanList
from tests.test_scan_persistence import _PersistenceMainWindow


SETTERS = {"nidaq_0": ["AO0", "AO1"]}
GETTERS = {"nidaq_0": ["AI0", "AI1"]}


def _plain(value):
    """JSON form of a scan value, so arrays and lists compare equal."""
    return json.loads(json.dumps(value, cls=_ScanJSONEncoder))


def _scan_info():
    info = copy.deepcopy(ScanInfo)
    info["comments"] = ""
    info["scan_log"] = []
    info["plots"] = {"line_plots": {}, "image_plots": {}}
    return info


class QueueFileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory(prefix="zmeter_queue_")
        self.addCleanup(self.temp_directory.cleanup)
        self.output_root = Path(self.temp_directory.name)
        self.main_window = _PersistenceMainWindow(self.output_root)
        self.scan_lists = []
        self.addCleanup(self._cleanup_widgets)

    def _cleanup_widgets(self):
        for scan_list in self.scan_lists:
            scan_list.shutdown(timeout_ms=500)
            scan_list.close()
            scan_list.deleteLater()
        self.main_window.close()
        self.main_window.deleteLater()
        self.app.processEvents()

    def _scan_list(self):
        scan_list = ScanList(
            info=_scan_info(),
            setter_equipment_info=SETTERS,
            getter_equipment_info=GETTERS,
            main_window=self.main_window,
        )
        self.scan_lists.append(scan_list)
        return scan_list

    def _queue_with_two_scans_and_a_manual_set(self):
        scan_list = self._scan_list()
        first, second = scan_list.list_available.get_widgets()[:2]
        first.scan.lineEdit.setText("gate sweep")
        first.scan.comments_textEdit.setPlainText("first")
        second.scan.lineEdit.setText("field/sweep")
        second.scan.PlotsPerPage.setCurrentIndex(1)
        scan_list.list_queue.add_item(first)
        scan_list.list_queue.add_item(
            ManualSetItem("nidaq_0_AO0", 0.5, main_window=self.main_window)
        )
        scan_list.list_queue.add_item(second)
        return scan_list

    @staticmethod
    def _queue_widgets(scan_list):
        return [entry.item for entry in scan_list.queue_model.ordered_queue_entries()]

    def test_saved_folder_holds_scan_files_and_queue_order(self):
        scan_list = self._queue_with_two_scans_and_a_manual_set()
        folder = self.output_root / "my_queue"

        self.assertEqual(scan_list.save_queue(str(folder)), str(folder))

        self.assertEqual(
            sorted(p.name for p in folder.iterdir()),
            ["01_gate sweep.json", "03_field_sweep.json", QUEUE_FILE],
        )
        queue = json.loads((folder / QUEUE_FILE).read_text(encoding="utf-8"))
        self.assertEqual(
            queue,
            {
                "format": "zmeter_queue",
                "version": 1,
                "items": [
                    {"scan": "01_gate sweep.json"},
                    {"manual_set": {"channel": "nidaq_0_AO0", "value": 0.5}},
                    {"scan": "03_field_sweep.json"},
                ],
            },
        )
        # Each scan file is a plain scan setting file.
        alone = read_scan_file(folder / "01_gate sweep.json")
        self.assertEqual(alone["name"], "gate sweep")
        self.assertEqual(alone["comments"], "first")
        self.assertEqual(alone["data"], {})
        self.assertEqual(sorted(p.name for p in self.output_root.iterdir()), ["my_queue"])

    def test_load_restores_order_and_settings_after_existing_items(self):
        source = self._queue_with_two_scans_and_a_manual_set()
        folder = self.output_root / "my_queue"
        source.save_queue(str(folder))
        saved_payloads = [
            item.scan.setting_payload()
            for item in self._queue_widgets(source)
            if isinstance(item, ScanItem)
        ]

        target = self._scan_list()
        target.list_queue.add_item(target.list_available.get_widgets()[0])
        self.assertEqual(target.load_queue(str(folder)), 3)

        queue = self._queue_widgets(target)
        self.assertEqual(
            [type(item).__name__ for item in queue],
            ["ScanItem", "ScanItem", "ManualSetItem", "ScanItem"],
        )
        loaded_scans = [queue[1], queue[3]]
        self.assertEqual([item.text() for item in loaded_scans], ["gate sweep", "field/sweep"])
        self.assertEqual(queue[2].text(), "nidaq_0_AO0->0.5")
        for item, saved in zip(loaded_scans, saved_payloads):
            reloaded = _plain(item.scan.setting_payload())
            for key in ("name", "levels", "plots", "comments", "plots_per_page"):
                self.assertEqual(reloaded[key], _plain(saved[key]), key)
            self.assertIsNone(item.scan.last_saved_json_path)

    def test_save_refuses_an_existing_folder_or_an_empty_queue(self):
        scan_list = self._scan_list()
        self.assertIsNone(scan_list.save_queue(str(self.output_root / "empty")))

        scan_list = self._queue_with_two_scans_and_a_manual_set()
        existing = self.output_root / "existing"
        existing.mkdir()
        self.assertIsNone(scan_list.save_queue(str(existing)))
        self.assertEqual(list(existing.iterdir()), [])
        self.assertEqual(sorted(p.name for p in self.output_root.iterdir()), ["existing"])

    def test_failed_save_leaves_nothing_behind(self):
        scan_list = self._queue_with_two_scans_and_a_manual_set()
        with mock.patch.object(
            queue_files, "_write_json_payload", side_effect=OSError("disk full")
        ):
            self.assertIsNone(scan_list.save_queue(str(self.output_root / "q")))
        self.assertEqual(list(self.output_root.iterdir()), [])
        self.assertIn("disk full", scan_list.logStatus_textEdit.toPlainText())

    def test_load_of_a_broken_folder_adds_nothing(self):
        source = self._queue_with_two_scans_and_a_manual_set()
        folder = self.output_root / "my_queue"
        source.save_queue(str(folder))
        (folder / "03_field_sweep.json").unlink()

        target = self._scan_list()
        self.assertEqual(target.load_queue(str(folder)), 0)
        self.assertEqual(self._queue_widgets(target), [])
        self.assertIn("Queue load failed", target.logStatus_textEdit.toPlainText())

        self.assertEqual(target.load_queue(str(self.output_root)), 0)
        with self.assertRaises(FileNotFoundError):
            read_queue(str(self.output_root))

    def test_canceled_dialogs_change_nothing(self):
        scan_list = self._queue_with_two_scans_and_a_manual_set()
        with mock.patch.object(
            QtWidgets.QFileDialog, "getSaveFileName", return_value=("", "")
        ):
            self.assertIsNone(scan_list.when_save_queue_clicked())
        with mock.patch.object(
            QtWidgets.QFileDialog, "getExistingDirectory", return_value=""
        ):
            self.assertEqual(scan_list.when_load_queue_clicked(), 0)
        self.assertEqual(list(self.output_root.iterdir()), [])
        self.assertEqual(len(self._queue_widgets(scan_list)), 3)


if __name__ == "__main__":
    unittest.main()
