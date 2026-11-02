import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.device_management.manager import DeviceState
from core.setup_capture import profile, system_export
from core.setup_capture.controller import SetupCaptureController

REPO = Path(__file__).resolve().parents[1]


def fake_main_window(data_folder="C:/data/run"):
    """What the export reads from MainWindow, with no devices behind it."""
    records = (
        SimpleNamespace(device_id="SR860_0", driver_id="sr860", state=DeviceState.CONNECTED),
        SimpleNamespace(device_id="Keithley_bg", driver_id="keithley24xx", state=DeviceState.CONNECTED),
        SimpleNamespace(device_id="montana2_0", driver_id="montana2", state=DeviceState.DISCONNECTED),
    )
    return SimpleNamespace(
        _applied_device_snapshot=SimpleNamespace(profile_name="device_config.xlsx", records=records),
        setter_equipment_info={
            "SR860_0": ["ampl", "frequency"],
            "Keithley_bg": ["V"],
            "default": ["wait", "count"],
            "artificial_channel": [],
        },
        getter_equipment_info={
            "SR860_0": ["X", "Y"],
            "Keithley_bg": ["V", "I"],
            "default": [],
            "artificial_channel": [],
        },
        active_scan_range_limits={
            ("Keithley_bg", "V"): (-5.0, 5.0),
            ("SR860_0", "ampl"): (0.0, float("inf")),
            ("SR860_0", "frequency"): (float("-inf"), float("inf")),
        },
        save_info_path=SimpleNamespace(toPlainText=lambda: data_folder),
    )


def json_block(text):
    return json.loads(re.search(r"```json\n(.*?)\n```", text, re.DOTALL).group(1))


class SystemExportTests(unittest.TestCase):
    def test_system_info_lists_devices_channels_and_finite_limits(self):
        info = system_export.system_info(fake_main_window())

        self.assertEqual(info["format"], "zmeter_system")
        self.assertEqual(info["profile"], "device_config.xlsx")
        self.assertEqual(os.path.normpath("C:/data/run"), info["data_folder"])
        self.assertEqual(
            info["devices"],
            [
                {"id": "SR860_0", "driver": "sr860", "state": "connected"},
                {"id": "Keithley_bg", "driver": "keithley24xx", "state": "connected"},
                {"id": "montana2_0", "driver": "montana2", "state": "disconnected"},
            ],
        )
        self.assertEqual(info["setter_channels"]["SR860_0"], ["SR860_0_ampl", "SR860_0_frequency"])
        self.assertEqual(info["setter_channels"]["default"], ["default_wait", "default_count"])
        self.assertEqual(info["getter_channels"]["Keithley_bg"], ["Keithley_bg_V", "Keithley_bg_I"])
        self.assertEqual(
            info["limits"],
            [
                {"channel": "Keithley_bg_V", "low": -5.0, "high": 5.0},
                {"channel": "SR860_0_ampl", "low": 0.0, "high": None},
            ],
        )

    def test_shift_compensation_channels_are_described_only_when_published(self):
        main_window = fake_main_window()
        text = system_export.export_markdown(system_export.system_info(main_window), {}, [], "")
        self.assertNotIn("| compensated_source |", text)

        main_window.setter_equipment_info["compensated_source"] = ["k10cr1_0_angle"]
        main_window.setter_equipment_info["compensated_target"] = ["ni6423_AO0"]
        info = system_export.system_info(main_window)
        text = system_export.export_markdown(info, {}, [], "")

        self.assertEqual(
            info["setter_channels"]["compensated_target"], ["compensated_target_ni6423_AO0"]
        )
        self.assertIn("| compensated_source | Shift Compensation:", text)
        self.assertIn("| compensated_target | Shift Compensation:", text)
        self.assertIn("`compensated_source_k10cr1_0_angle`", text)

    def test_markdown_holds_every_section_and_a_matching_json_block(self):
        info = system_export.system_info(fake_main_window())
        text = system_export.export_markdown(
            info,
            {"device": "TXT15", "contacts": "Hall bar, contacts 1-6"},
            [
                {"id": "temp", "text": "Sample temperature", "answer": "3.4 K"},
                {"id": "empty", "text": "Unanswered", "answer": None},
            ],
            "# ZMeter lab context  (version 0.5)\nLab notes here.",
        )

        for heading in (
            "## Devices",
            "## Setter channels",
            "## Getter channels",
            "## Scan range limits",
            "## Experiment description",
            "## Remembered questionnaire answers",
            "## Lab context (lab_context/lab_context.md)",
            "## Machine-readable system information",
        ):
            self.assertIn(heading, text)
        self.assertIn("| montana2_0 | montana2 | disconnected |", text)
        self.assertIn("- SR860_0: `SR860_0_ampl`, `SR860_0_frequency`", text)
        self.assertIn("| `SR860_0_ampl` | 0 | none |", text)
        self.assertIn("- Device / sample: TXT15", text)
        self.assertIn("- Pins in use: (empty)", text)
        self.assertIn("- Sample temperature: 3.4 K", text)
        self.assertNotIn("Unanswered", text)
        self.assertIn("Lab notes here.", text)
        self.assertEqual(json_block(text), info)

    def test_dialog_exports_the_description_as_typed(self):
        from core.setup_capture.widgets import SetupCaptureDialog

        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        with tempfile.TemporaryDirectory() as folder:
            keys = profile.ApiKeyStore()
            keys.keyring_available = False
            controller = SetupCaptureController(
                main_window=fake_main_window(folder),
                settings=profile.SetupCaptureSettings(Path(folder) / "settings"),
                keys=keys,
                lab_folder=REPO / "lab_context",
            )
            dialog = SetupCaptureDialog(controller)
            dialog.description_edits["device"].setText("typed, not saved")
            target = os.path.join(folder, "zmeter_system")
            with mock.patch(
                "core.setup_capture.widgets.QtWidgets.QFileDialog.getSaveFileName",
                return_value=(target, ""),
            ) as save_dialog, mock.patch(
                "core.setup_capture.widgets.QtWidgets.QMessageBox.information"
            ):
                path = dialog._export_system_info()

            self.assertEqual(path, target + ".md")
            self.assertTrue(
                save_dialog.call_args.args[2].endswith(system_export.DEFAULT_FILE_NAME)
            )
            text = Path(path).read_text(encoding="utf-8")
            self.assertIn("- Device / sample: typed, not saved", text)
            self.assertIn("ZMeter lab context", text)
            self.assertEqual(json_block(text)["setter_channels"]["Keithley_bg"], ["Keithley_bg_V"])
            self.assertEqual(controller.description["device"], "")
            dialog.deleteLater()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
