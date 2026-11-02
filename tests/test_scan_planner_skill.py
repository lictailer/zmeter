"""The scan planner skill's build script against ZMeter's own file code.

skills/zmeter-scan-planner/scripts/build_plan.py copies ZMeter's scan setting
and queue formats instead of importing them, because the skill is installed
outside this repository. These tests load its output with ZMeter's loaders so a
format change in ZMeter shows up here.
"""

import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.brakets import Brakets
from core.channel_check import catalog_names, find_unresolved, level_problems
from core.queue_files import read_queue
from core.scan import Scan, read_scan_file
from core.scan_info import ScanInfo
from core.setup_capture import system_export
from tests.test_scan_persistence import _PersistenceMainWindow
from tests.test_system_export import fake_main_window

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "skills" / "zmeter-scan-planner" / "scripts" / "build_plan.py"

_spec = importlib.util.spec_from_file_location("zmeter_build_plan", SCRIPT)
build_plan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_plan)


def nlh_scan(name="NLH_gate_3p4K"):
    return {
        "type": "scan",
        "name": name,
        "comments": "Second-harmonic Hall voltage vs back gate.",
        "estimated_minutes": 12,
        "levels": [
            {
                "setters": [
                    {"channel": "Keithley_bg_V", "start": -1.0, "end": 1.0, "points": 5},
                    {"channel": "SR860_0_frequency", "values": [17.0, 17.0, 17.0, 17.0, 17.0]},
                    {"channel": "default_wait", "values": [0.1]},
                ],
                "setting_method": "A+B,C",
                "getters": ["SR860_0_X", "SR860_0_Y"],
                "settle_time": 0.3,
                "start_wait_time": 2.0,
                "manual_set_before": [{"channel": "SR860_0_ampl", "value": 0.5}],
                "manual_set_after": [{"channel": "Keithley_bg_V", "value": 0.0}],
            },
            {
                "setters": [{"channel": "SR860_0_ampl", "start": 0.1, "end": 0.4, "points": 4}],
                "getters": ["level0_average_SR860_0_X"],
            },
        ],
        "plots": [
            {"type": "line", "level": 0, "x": "Keithley_bg_V", "y": "SR860_0_Y"},
            {"type": "line", "level": 1, "x": "level", "y": "level0_average_SR860_0_X"},
            {"type": "image", "level": 0, "z": "SR860_0_X"},
        ],
    }


class BuildPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory(prefix="zmeter_planner_")
        self.addCleanup(self.temp_directory.cleanup)
        self.root = Path(self.temp_directory.name)
        self.main_window = fake_main_window(str(self.root))
        info = system_export.system_info(self.main_window)
        self.export_path = self.root / "zmeter_system.md"
        self.export_path.write_text(
            system_export.export_markdown(info, {}, [], "# Lab\n```json\n{\"not\": 1}\n```"),
            encoding="utf-8",
        )
        self.system = build_plan.read_system(str(self.export_path))

    def _scan_window(self):
        persistence_window = _PersistenceMainWindow(self.root)
        info = copy.deepcopy(ScanInfo)
        info["plots"] = {"line_plots": {}, "image_plots": {}}
        scan = Scan(
            name="probe",
            info=info,
            setter_equipment_info=self.main_window.setter_equipment_info,
            getter_equipment_info=self.main_window.getter_equipment_info,
            main_window=persistence_window,
        )

        def cleanup():
            scan.close()
            scan.deleteLater()
            persistence_window.deleteLater()
            self.app.processEvents()

        self.addCleanup(cleanup)
        return scan

    def test_export_json_block_is_read_past_other_json_blocks(self):
        self.assertEqual(self.system["format"], "zmeter_system")
        self.assertIn("Keithley_bg_V", self.system["setter_channels"]["Keithley_bg"])

    def test_setting_array_matches_zmeter_brakets(self):
        destinations = {"A": [1.0, 2.0, 3.0], "B": [10.0], "C": [5.0, 6.0]}
        for method in ("", "A,B,C", "A+B,C", "A+C,B", "a + b , c"):
            with self.subTest(method=method):
                expected = Brakets(
                    method, destinations, personalized_input=bool(method)
                ).output
                actual = np.array(build_plan.setting_array(method.replace(" ", ""), destinations))
                np.testing.assert_array_equal(actual, expected)

    def test_one_scan_writes_a_setting_file_that_loads_like_save_setting(self):
        plan = {"items": [nlh_scan()]}
        self.assertEqual(build_plan.check_plan(plan, self.system), [])
        path = build_plan.write_plan(plan, str(self.root))
        self.assertEqual(Path(path).name, "scan_setting_NLH_gate_3p4K.json")

        written = read_scan_file(path)
        self.assertEqual(
            find_unresolved(
                written,
                catalog_names(self.main_window.setter_equipment_info),
                catalog_names(self.main_window.getter_equipment_info),
            ),
            [],
        )
        self.assertEqual(level_problems(written), [])

        scan = self._scan_window()
        scan.load_info(read_scan_file(path), path)
        self.assertIsNone(scan.last_saved_json_path)
        self.assertEqual(scan.lineEdit.text(), "NLH_gate_3p4K")
        self.assertIn("about 12 min", scan.comments_textEdit.toPlainText())
        level0 = scan.info["levels"]["level0"]
        self.assertEqual(level0["setting_method"], "A+B,C")
        self.assertEqual(level0["manual_set_before"], [{"SR860_0_ampl": 0.5}])
        self.assertEqual(scan.info["levels"]["level1"]["getters"], ["level0_average_SR860_0_X"])

        saved = scan.setting_payload()
        self.assertEqual(set(saved) - {"questionnaire"}, set(written))
        for level in ("level0", "level1"):
            np.testing.assert_allclose(
                np.asarray(saved["levels"][level]["setting_array"], dtype=float),
                np.asarray(written["levels"][level]["setting_array"], dtype=float),
            )
            self.assertEqual(
                [s["channel"] for s in saved["levels"][level]["setters"].values()],
                [s["channel"] for s in written["levels"][level]["setters"].values()],
            )
        self.assertEqual(
            saved["plots"],
            {
                "line_plots": {
                    "0": {"x": "L0S0_Keithley_bg_V", "y": "L0G1_SR860_0_Y"},
                    "1": {"x": "level1", "y": "L1G0_level0_average_SR860_0_X"},
                },
                "image_plots": {"0": {"x": "level0", "y": "level1", "z": "L0G0_SR860_0_X"}},
            },
        )

    def test_queue_folder_reads_back_in_order_with_zmeter(self):
        plan = {
            "name": "gate series",
            "items": [
                {"type": "manual_set", "channel": "Keithley_bg_V", "value": 0},
                nlh_scan("first"),
                {"type": "manual_set", "channel": "SR860_0_ampl", "value": 0.2},
                nlh_scan("second"),
            ],
        }
        self.assertEqual(build_plan.check_plan(plan, self.system), [])
        folder = build_plan.write_plan(plan, str(self.root))
        self.assertEqual(Path(folder).name, "queue_gate series")

        items = read_queue(folder)
        self.assertEqual(
            [item.get("manual_set") or item["scan"]["name"] for item in items],
            [
                {"channel": "Keithley_bg_V", "value": 0.0},
                "first",
                {"channel": "SR860_0_ampl", "value": 0.2},
                "second",
            ],
        )
        self.assertEqual(Path(items[1]["path"]).name, "02_first.json")

        scan = self._scan_window()
        scan.load_info(items[3]["scan"], items[3]["path"])
        self.assertEqual(scan.lineEdit.text(), "second")

    def test_problems_stop_the_plan_and_write_nothing(self):
        cases = {
            "unknown setter": ({"channel": "SR830_2_V", "start": 0, "end": 1, "points": 3}, "not a setter channel"),
            "outside limit": ({"channel": "Keithley_bg_V", "start": 0, "end": 6, "points": 3}, "outside the range limit"),
            "no points": ({"channel": "Keithley_bg_V", "start": 0, "end": 1, "points": 0}, "points must be"),
        }
        for label, (setter, message) in cases.items():
            with self.subTest(label):
                scan = nlh_scan()
                scan["levels"][0]["setters"][0] = setter
                problems = build_plan.check_plan({"items": [scan]}, self.system)
                self.assertTrue(any(message in problem for problem in problems), problems)

        scan = nlh_scan()
        scan["levels"][0]["setting_method"] = "A+D"
        scan["levels"][0]["getters"] = ["SR860_0_R"]
        scan["levels"][1]["setters"] = []
        scan["plots"].append({"type": "image", "level": 1, "z": "level0_average_SR860_0_X"})
        problems = "\n".join(build_plan.check_plan({"items": [scan]}, self.system))
        for message in (
            "names setter(s) D",
            "getter 'SR860_0_R' is not a getter channel",
            "needs at least one setter",
            "needs SR860_0_X as a getter of a lower level0",
            "an image plot needs a level above level1",
        ):
            self.assertIn(message, problems)

        manual = {"type": "manual_set", "channel": "Keithley_bg_V", "value": -9}
        self.assertIn("outside the range limit", build_plan.check_plan({"items": [manual]}, self.system)[0])

        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps({"items": [manual]}), encoding="utf-8")
        out = self.root / "out"
        out.mkdir()
        self.assertEqual(
            build_plan.main([str(plan_path), "--system", str(self.export_path), "--out", str(out)]), 1
        )
        self.assertEqual(list(out.iterdir()), [])

    def test_cli_writes_into_the_export_data_folder_and_never_overwrites(self):
        plan_path = self.root / "plan.json"
        plan_path.write_text(json.dumps({"items": [nlh_scan()]}), encoding="utf-8")
        args = [str(plan_path), "--system", str(self.export_path)]

        self.assertEqual(build_plan.main(args + ["--check"]), 0)
        self.assertFalse((self.root / "scan_setting_NLH_gate_3p4K.json").exists())
        self.assertEqual(build_plan.main(args), 0)
        self.assertTrue((self.root / "scan_setting_NLH_gate_3p4K.json").exists())
        with self.assertRaises(FileExistsError):
            build_plan.main(args)


if __name__ == "__main__":
    unittest.main()
