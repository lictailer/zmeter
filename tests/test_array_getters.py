"""Array getters: spec, fixed-level sync, engine block reads, plots, Scan UI.

No hardware: arrays come from the mock device logic or from fakes.
"""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core import array_levels as al
from core.array_getters import (
    MAX_ARRAY_DIMS,
    ArrayCatalog,
    ArrayGetter,
    ArrayInfo,
    ArrayShapeError,
    array_getter_specs,
    describe_array_getter,
    validate_array,
)
from core.channel_check import level_problems
from core.channel_value_record import ChannelValueRecord
from core.scan_logic import ScanLogic
from devices.mockDevice.mock_device_logic import MockDeviceLogic


# --------------------------------------------------------------- helpers
class FakeCatalog:
    """Catalog with fixed shapes; ``offline`` channels have no shape."""

    def __init__(self, shapes, offline=()):
        self.shapes = dict(shapes)
        self.offline = set(offline)
        self.info_calls = 0

    def is_array(self, channel):
        return channel in self.shapes

    def info(self, channel):
        self.info_calls += 1
        shape = self.shapes.get(channel)
        if shape is None or channel in self.offline:
            return None
        axes = {1: ("pixel",), 2: ("row", "column"), 3: ("t", "row", "column")}[len(shape)]
        values = tuple(tuple(float(i) * 10 for i in range(n)) for n in shape)
        return ArrayInfo(channel, axes, tuple(shape), values, "counts")


def user_level(getters, points=3, channel="mock_device_1_channel_A"):
    values = [float(i) for i in range(points)]
    return {
        "setters": {
            "setter0": {
                "channel": channel,
                "explicit": True,
                "linear_setting": {},
                "explicit_setting": values,
                "destinations": values,
            }
        },
        "setting_method": "",
        "getters": list(getters),
        "settle_time": 0.0,
        "start_wait_time": 0.0,
        "manual_set_before": [],
        "manual_set_after": [],
        "setting_array": np.array([values]),
    }


CATALOG = FakeCatalog({"cam_spectrum": (5,), "cam_frame": (2, 3), "cam_other": (7,)})


class ArraySpecTests(unittest.TestCase):
    def test_mock_device_declares_spectrum_and_frame(self):
        logic = MockDeviceLogic()
        specs = array_getter_specs(logic)
        self.assertEqual(set(specs), {"spectrum", "frame"})
        spectrum = describe_array_getter(logic, "spectrum", "mock_spectrum")
        self.assertEqual(spectrum.shape, (64,))
        self.assertEqual(spectrum.axes, ("pixel",))
        self.assertAlmostEqual(spectrum.axis_values[0][1], 500.5)
        frame = describe_array_getter(logic, "frame")
        self.assertEqual(frame.shape, (8, 12))
        self.assertEqual(frame.axis_values[0], tuple(float(i) for i in range(8)))
        self.assertIsNone(describe_array_getter(logic, "channel_A"))

    def test_validation(self):
        self.assertEqual(validate_array([[1, 2, 3]], (1, 3)).shape, (1, 3))
        with self.assertRaises(ArrayShapeError):
            validate_array([1, 2], (3,))
        with self.assertRaises(ArrayShapeError):
            validate_array(["a"], (1,))

    def test_more_axes_than_supported_is_rejected(self):
        class Logic:
            ARRAY_GETTERS = {
                "cube": ArrayGetter(axes=tuple(f"a{i}" for i in range(MAX_ARRAY_DIMS + 1)), shape="s")
            }

        with self.assertRaises(ValueError):
            array_getter_specs(Logic())
        # The catalog must not raise for a bad declaration.
        catalog = ArrayCatalog(lambda channel: (Logic(), "cube"))
        self.assertFalse(catalog.is_array("x_cube"))
        self.assertIsNone(catalog.info("x_cube"))

    def test_value_record_keeps_a_scalar_placeholder(self):
        record = ChannelValueRecord()
        record.record_read("mock_spectrum", np.arange(5.0))
        self.assertTrue(np.isnan(record.latest("mock_spectrum").value))
        record.record_read("mock_A", np.array([2.0]))
        self.assertEqual(record.latest("mock_A").value, 2.0)


class FixedLevelSyncTests(unittest.TestCase):
    def test_pick_then_remove_round_trip(self):
        levels = {
            "level0": user_level(["lock_X", "cam_spectrum"]),
            "level1": user_level(["level0_average_lock_X"]),
        }
        picked = al.sync_fixed_levels(levels, CATALOG)
        self.assertTrue(picked.changed)
        self.assertEqual(picked.mapping, {0: 1, 1: 2})
        self.assertEqual(len(picked.levels), 3)
        fixed = picked.levels["level0"]
        self.assertEqual(fixed["getters"], ["cam_spectrum"])
        self.assertEqual(fixed["fixed_axis"]["name"], "pixel")
        self.assertEqual(fixed["setting_array"].shape, (1, 5))
        self.assertEqual(picked.levels["level1"]["getters"], ["lock_X"])
        self.assertEqual(picked.levels["level2"]["getters"], ["level1_average_lock_X"])

        picked.levels["level0"]["getters"] = ["none"]
        removed = al.sync_fixed_levels(picked.levels, CATALOG)
        self.assertTrue(removed.changed)
        self.assertEqual(removed.mapping, {0: None, 1: 0, 2: 1})
        self.assertEqual(len(removed.levels), 2)
        self.assertFalse(any(al.is_fixed_level(level) for level in removed.levels.values()))
        self.assertEqual(removed.levels["level1"]["getters"], ["level0_average_lock_X"])

    def test_sync_is_idempotent(self):
        first = al.sync_fixed_levels({"level0": user_level(["cam_frame"])}, CATALOG)
        second = al.sync_fixed_levels(first.levels, CATALOG)
        self.assertFalse(second.changed)
        self.assertFalse(second.renumbered)
        # Reload from JSON (lists instead of arrays) is still a no-op.
        reloaded = json.loads(json.dumps(first.levels, default=lambda o: o.tolist()))
        self.assertFalse(al.sync_fixed_levels(reloaded, CATALOG).changed)

    def test_two_axis_frame_inserts_two_fixed_levels(self):
        result = al.sync_fixed_levels({"level0": user_level(["cam_frame"])}, CATALOG)
        self.assertEqual(al.fixed_level_count(result.levels), 2)
        self.assertEqual(result.levels["level0"]["fixed_axis"]["name"], "column")
        self.assertEqual(result.levels["level1"]["fixed_axis"]["name"], "row")
        self.assertEqual(result.levels["level1"]["getters"], ["none"])
        self.assertEqual(al.fixed_block_shape(result.levels), (2, 3))
        self.assertEqual(al.user_point_count(result.levels), 3)

    def test_three_axis_getter_uses_the_same_generic_path(self):
        catalog = FakeCatalog({"cube": (2, 3, 4)})
        result = al.sync_fixed_levels({"level0": user_level(["cube"])}, catalog)
        self.assertEqual(al.fixed_level_count(result.levels), 3)
        self.assertEqual(al.fixed_block_shape(result.levels), (2, 3, 4))
        self.assertFalse(al.sync_fixed_levels(result.levels, catalog).changed)

    def test_shape_mismatch_is_refused(self):
        first = al.sync_fixed_levels({"level0": user_level(["cam_spectrum"])}, CATALOG)
        first.levels["level1"]["getters"] = ["cam_other"]
        result = al.sync_fixed_levels(first.levels, CATALOG)
        self.assertEqual(result.levels["level0"]["getters"], ["cam_spectrum"])
        self.assertEqual(result.levels["level1"]["getters"], ["none"])
        self.assertTrue(any("same shape" in warning for warning in result.warnings))

    def test_array_getter_on_outer_level_is_removed(self):
        levels = {"level0": user_level(["lock_X"]), "level1": user_level(["cam_spectrum"])}
        result = al.sync_fixed_levels(levels, CATALOG)
        self.assertEqual(len(result.levels), 2)
        self.assertEqual(result.levels["level1"]["getters"], ["none"])
        self.assertTrue(result.warnings)

    def test_offline_device_keeps_saved_fixed_levels(self):
        saved = al.sync_fixed_levels({"level0": user_level(["cam_spectrum"])}, CATALOG).levels
        offline = FakeCatalog({"cam_spectrum": (5,)}, offline={"cam_spectrum"})
        self.assertFalse(al.sync_fixed_levels(saved, offline).changed)
        fresh = al.sync_fixed_levels({"level0": user_level(["cam_spectrum"])}, offline)
        self.assertFalse(fresh.changed)
        self.assertEqual(fresh.levels["level0"]["getters"], ["cam_spectrum"])

    def test_refresh_updates_axis_values(self):
        levels = al.sync_fixed_levels({"level0": user_level(["cam_spectrum"])}, CATALOG).levels
        levels["level0"]["setters"]["setter0"]["destinations"] = [9.0] * 5
        self.assertFalse(al.sync_fixed_levels(levels, CATALOG).changed)
        refreshed = al.sync_fixed_levels(levels, CATALOG, refresh=True)
        self.assertTrue(refreshed.changed)
        self.assertEqual(
            refreshed.levels["level0"]["setters"]["setter0"]["destinations"],
            [0.0, 10.0, 20.0, 30.0, 40.0],
        )

    def test_plot_tokens_follow_the_renumbering(self):
        levels = {
            "level0": user_level(["cam_spectrum", "lock_X"]),
            "level1": user_level(["level0_average_lock_X"]),
        }
        result = al.sync_fixed_levels(levels, CATALOG)
        plots = {
            "line_plots": {"0": {"x": "L0S0_mock_device_1_channel_A", "y": "L0G1_lock_X"}},
            "image_plots": {
                "0": {"x": "level0", "y": "level1", "z": "L0G1_lock_X"},
                "1": {"x": "level1", "z": "L1G0_level0_average_lock_X"},
            },
        }
        remapped = al.remap_plots(plots, result.mapping, result.levels)
        self.assertEqual(remapped["line_plots"]["0"], {"x": "L1S0_mock_device_1_channel_A", "y": "L1G0_lock_X"})
        self.assertEqual(remapped["image_plots"]["0"], {"x": "level1", "y": "level2", "z": "L1G0_lock_X"})
        self.assertEqual(
            remapped["image_plots"]["1"],
            {"x": "level2", "z": "L2G0_level1_average_lock_X"},
        )
        # A token pointing at a removed fixed level is dropped.
        self.assertEqual(al.remap_plot_token("level0", {0: None}), "")

    def test_queue_check_allows_fixed_levels_and_flags_huge_arrays(self):
        levels = al.sync_fixed_levels({"level0": user_level(["cam_spectrum"])}, CATALOG).levels
        self.assertEqual(level_problems({"levels": levels}), [])
        big = copy.deepcopy(levels)
        big["level1"]["setting_array"] = np.zeros((1, 30_000_000))
        problems = level_problems({"levels": big})
        self.assertTrue(any("array getters would store" in text for _place, text in problems))


# ----------------------------------------------------------------- engine
class _NoArtificial:
    artificial_channels = ()

    def __init__(self, skip_values=()):
        self.skip_values = set(skip_values)
        self.skip = False

    def consume_skip_read_for_scan(self):
        skip, self.skip = self.skip, False
        return skip

    @staticmethod
    def has_artificial_channel(_channel):
        return False

    @staticmethod
    def reset_skip_next_scan_read():
        return None


class MockArrayMainWindow:
    """Routes ``mock_*`` channels to a real MockDeviceLogic (simulator)."""

    def __init__(self, skip_values=()):
        self.logic = MockDeviceLogic()
        self.logic.connect_device("SIM")
        self.equips = {"mock": SimpleNamespace(logic=self.logic)}
        self.artificial_channel_logic = _NoArtificial(skip_values)
        self.reads = []
        self.on_read = None

    def write_info(self, value, channel):
        if value in self.artificial_channel_logic.skip_values:
            self.artificial_channel_logic.skip = True
        getattr(self.logic, f"set_{channel[len('mock_'):]}")(value)

    def read_info(self, channel):
        self.reads.append(channel)
        if self.on_read is not None:
            self.on_read(channel)
        return getattr(self.logic, f"get_{channel[len('mock_'):]}")()


def mock_catalog(main_window):
    return ArrayCatalog(
        lambda channel: (main_window.logic, channel[len("mock_"):])
        if channel.startswith("mock_")
        else None
    )


def engine_config(main_window, getters, outer_points=(0.0, 1.0, 2.0)):
    levels = {"level0": user_level(getters, len(outer_points), "mock_channel_A")}
    levels["level0"]["setting_array"] = np.array([list(outer_points)])
    synced = al.sync_fixed_levels(levels, mock_catalog(main_window)).levels
    return {"levels": copy.deepcopy(synced)}


class ArrayEngineTests(unittest.TestCase):
    def run_scan(self, main_window, config):
        logic = ScanLogic(main_window=main_window)
        emitted = []
        logic.sig_new_data.connect(lambda payload: emitted.append(copy.deepcopy(payload[2])))
        errors = []
        logic.sig_scan_error.connect(errors.append)
        logic.initialize_scan_data(config)
        logic.scan()
        return logic, emitted, errors

    def test_one_dimensional_spectrum_scan(self):
        window = MockArrayMainWindow()
        config = engine_config(window, ["mock_spectrum", "mock_channel_A"])
        logic, emitted, errors = self.run_scan(window, config)
        self.assertEqual(errors, [])
        self.assertEqual(logic.fixed_level_count, 1)
        self.assertEqual(logic.array_block_shape, (64,))
        data = logic.level_data_arrays[0]
        self.assertEqual(data.shape, (1, 3, 64))
        self.assertFalse(np.isnan(data).any())
        # The peak follows channel A (1 nm per unit, 0.5 nm pixels).
        peaks = [int(np.argmax(data[0, i])) for i in range(3)]
        self.assertEqual(peaks, [32, 34, 36])
        # One read per outer point, never per pixel.
        self.assertEqual(window.reads.count("mock_spectrum"), 3)
        # Progress counts user levels only: the remaining-time estimate stays right.
        self.assertEqual(logic.total_points, 3)
        self.assertEqual(logic.completed_points, 3)
        phases = [item["phase"] for item in emitted]
        self.assertEqual(phases.count("block"), 3)
        block = [item for item in emitted if item["phase"] == "block"][0]
        self.assertEqual(block["fixed_levels"], 1)
        self.assertEqual(block["source_level"], 0)

    def test_two_dimensional_frame_scan_with_average(self):
        window = MockArrayMainWindow()
        config = engine_config(window, ["mock_frame"], outer_points=(0.0, 1.0))
        config["levels"]["level2"]["getters"] = ["level0_average_mock_frame"]
        logic, emitted, errors = self.run_scan(window, config)
        self.assertEqual(errors, [])
        self.assertEqual(logic.fixed_level_count, 2)
        self.assertEqual(logic.level_data_arrays[0].shape, (1, 2, 8, 12))
        self.assertEqual(logic.total_points, 2)
        averages = logic.level_data_arrays[2][0]
        expected = logic.level_data_arrays[0][0].reshape(2, -1).mean(axis=1)
        np.testing.assert_allclose(averages, expected)

    def test_wrong_shape_stops_the_scan_with_an_error(self):
        window = MockArrayMainWindow()
        config = engine_config(window, ["mock_spectrum"])
        window.logic.hardware.simulator.SPECTRUM_PIXELS = 10
        _logic, _emitted, errors = self.run_scan(window, config)
        self.assertEqual(len(errors), 1)
        self.assertIn("array_read", errors[0])
        self.assertIn("expected (64,)", errors[0])

    def test_stop_during_a_block_stores_nothing(self):
        window = MockArrayMainWindow()
        config = engine_config(window, ["mock_spectrum"])
        logic = ScanLogic(main_window=window)
        logic.initialize_scan_data(config)

        def stop_on_second(channel):
            if window.reads.count(channel) == 2:
                logic.request_stop()

        window.on_read = stop_on_second
        logic.scan()
        data = logic.level_data_arrays[0][0]
        self.assertFalse(np.isnan(data[0]).any())
        self.assertTrue(np.isnan(data[1]).all())
        self.assertTrue(np.isnan(data[2]).all())

    def test_artificial_skip_leaves_the_slice_nan(self):
        window = MockArrayMainWindow(skip_values={1.0})
        config = engine_config(window, ["mock_spectrum"])
        window.artificial_channel_logic.artificial_channels = ()
        logic, _emitted, errors = self.run_scan(window, config)
        self.assertEqual(errors, [])
        data = logic.level_data_arrays[0][0]
        self.assertTrue(np.isnan(data[1]).all())
        self.assertFalse(np.isnan(data[0]).any())
        self.assertFalse(np.isnan(data[2]).any())

    def test_scalar_scan_point_count_is_unchanged(self):
        window = MockArrayMainWindow()
        config = {
            "levels": {
                "level0": user_level(["mock_channel_A"], 4, "mock_channel_A"),
                "level1": user_level(["none"], 3, "mock_channel_B"),
            }
        }
        logic, _emitted, _errors = self.run_scan(window, config)
        self.assertEqual(logic.fixed_level_count, 0)
        self.assertEqual(logic.total_points, 4 * 3 + 3)
        self.assertEqual(logic.completed_points, logic.total_points)


# --------------------------------------------------------------- Scan UI
class _ScanMainWindow(QtWidgets.QWidget):
    def __init__(self, root):
        super().__init__()
        self.save_path = str(root)
        self.save_info_path = QtWidgets.QPlainTextEdit(self.save_path, self)
        self.array_catalog = CATALOG


class ArrayScanUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        from core.scan import Scan
        from core.scan_info import ScanInfo

        self.temp = tempfile.TemporaryDirectory(prefix="zmeter_array_")
        self.addCleanup(self.temp.cleanup)
        self.main_window = _ScanMainWindow(Path(self.temp.name))
        info = copy.deepcopy(ScanInfo)
        info["levels"]["level0"]["getters"] = ["lock_X"]
        info["levels"]["level1"]["getters"] = ["level0_average_lock_X"]
        info["plots"] = {
            "line_plots": {"0": {"x": "level0", "y": "L0G0_lock_X"}},
            "image_plots": {},
        }
        self.scan = Scan(
            name="array_probe",
            info=info,
            setter_equipment_info={},
            getter_equipment_info={"cam": ["spectrum", "frame"], "lock": ["X"]},
            main_window=self.main_window,
        )
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        self.scan.close()
        self.scan.deleteLater()
        self.main_window.deleteLater()
        self.app.processEvents()

    def level_widgets(self):
        return [w for _i, w in self.scan.all_level_setting._iter_level_widgets()]

    def choose(self, level_index, channel):
        widget = self.level_widgets()[level_index]
        widget.when_combobox_changed(SimpleNamespace(name=channel))
        self.app.processEvents()

    def test_picking_and_removing_an_array_getter(self):
        self.choose(0, "cam_spectrum")
        levels = self.scan.info["levels"]
        self.assertEqual(len(levels), 3)
        self.assertTrue(al.is_fixed_level(levels["level0"]))
        self.assertEqual(levels["level0"]["getters"], ["cam_spectrum"])
        self.assertEqual(levels["level1"]["getters"], ["lock_X"])
        self.assertEqual(levels["level2"]["getters"], ["level1_average_lock_X"])
        self.assertEqual(self.scan.info["plots"]["line_plots"]["0"], {"x": "level1", "y": "L1G0_lock_X"})
        widgets = self.level_widgets()
        self.assertEqual(len(widgets), 3)
        self.assertTrue(widgets[0].is_fixed)
        self.assertFalse(widgets[0].master_add_one_pb.isEnabled())
        self.assertTrue(widgets[0].record_clean_pb.isEnabled())
        self.assertIn("fixed", widgets[0].groupBox.title())
        # Array getters are offered on the innermost user level only.
        outer_menu = self.scan.all_level_setting._build_getter_menu_for_level(2)
        self.assertNotIn("spectrum", outer_menu["cam"])
        inner_menu = self.scan.all_level_setting._build_getter_menu_for_level(1)
        self.assertIn("spectrum", inner_menu["cam"])
        # The last user level cannot be deleted under fixed levels... but an
        # outer one can, and the fixed levels stay.
        self.scan.all_level_setting.delete_level()
        self.assertEqual(len(self.scan.info["levels"]), 2)
        self.scan.all_level_setting.delete_level()
        self.assertEqual(len(self.scan.info["levels"]), 2)

        # Clean on the fixed level removes the getter and its fixed level.
        self.level_widgets()[0].when_clean_clicked()
        self.app.processEvents()
        levels = self.scan.info["levels"]
        self.assertEqual(len(levels), 1)
        self.assertFalse(al.is_fixed_level(levels["level0"]))
        self.assertEqual(self.scan.info["plots"]["line_plots"]["0"], {"x": "level0", "y": "L0G0_lock_X"})

    def test_block_redraws_the_whole_line_and_image_row(self):
        self.choose(0, "cam_spectrum")
        self.scan.all_plot_setting.when_add_line_clicked()
        self.scan.all_plot_setting.when_add_image_clicked()
        line_widget = self.scan.all_plot_setting.verticalLayout_line.itemAt(1).widget()
        line_widget.set_choices({"x": "L0S0_none", "y": "L0G0_cam_spectrum"})
        image_widget = self.scan.all_plot_setting.verticalLayout_image.itemAt(0).widget()
        image_widget.set_choices({"x": "level0", "y": "level1", "z": "L0G0_cam_spectrum"})
        self.scan.update_all_plots()
        self.assertEqual(
            self.scan.info["plots"]["line_plots"]["1"], {"x": "L0S0_none", "y": "L0G0_cam_spectrum"}
        )

        data = [np.full((1, 3, 3, 5), np.nan), np.full((1, 3, 3), np.nan), np.full((1, 3), np.nan)]
        data[0][0, 0, 1] = np.arange(5.0)
        self.scan.new_data(
            [data, [0, 1, 0], {"source_level": 0, "changed_getter_indices": [0], "phase": "block", "fixed_levels": 1}]
        )
        from core.all_plots import ImagePlot, LinePlot

        widgets = [
            self.scan.graphing_plots[0].plots_layout.itemAt(i).widget()
            for i in range(self.scan.graphing_plots[0].plots_layout.count())
        ]
        spectrum_line = [w for w in widgets if isinstance(w, LinePlot) and w.y_name == "L0G0_cam_spectrum"][0]
        np.testing.assert_allclose(spectrum_line.y_coordinates, np.arange(5.0))
        np.testing.assert_allclose(spectrum_line.x_coordinates, [0.0, 10.0, 20.0, 30.0, 40.0])
        image = [w for w in widgets if isinstance(w, ImagePlot)][0]
        np.testing.assert_allclose(image.data[1], np.arange(5.0))
        self.assertTrue(np.isnan(image.data[0]).all())

    def test_saved_json_is_compact_and_reloads_without_renumbering(self):
        self.choose(0, "cam_spectrum")
        payload = self.scan.setting_payload()
        path = Path(self.temp.name) / "setting.json"
        from core.scan import _write_json_payload, read_scan_file

        _write_json_payload(path, payload)
        text = path.read_text(encoding="utf-8")
        self.assertNotIn("\n", text)
        self.assertNotIn(": ", text)
        loaded = read_scan_file(path)
        self.scan.load_info(loaded, str(path))
        self.assertEqual(len(self.scan.info["levels"]), 3)
        self.assertEqual(self.scan.all_level_setting.last_sync_mapping, {})
        self.assertEqual(self.scan.info["plots"]["line_plots"]["0"], {"x": "level1", "y": "L1G0_lock_X"})

    def test_old_scalar_json_loads_unchanged(self):
        from core.scan_info import ScanInfo

        info = copy.deepcopy(ScanInfo)
        info["plots"] = {"line_plots": {"0": {"x": "level0", "y": "L0G0_lockin_0_X"}}, "image_plots": {}}
        before = copy.deepcopy(info["levels"])
        self.scan.load_info(info, "old.json")
        self.assertEqual(len(self.scan.info["levels"]), len(before))
        self.assertFalse(any(al.is_fixed_level(level) for level in self.scan.info["levels"].values()))


if __name__ == "__main__":
    unittest.main()
