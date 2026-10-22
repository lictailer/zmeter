"""Only synthetic maps, fake routed channels and temporary directories."""
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="zmeter-position-mpl-"))

import numpy as np
from scipy.ndimage import gaussian_filter, map_coordinates, shift
from PyQt6 import QtWidgets

from core.measurement_io import Channel, RouterIO
from devices.auto_position.position_engine import (
    MapSettings, PositionSettings, PositionStopped, ReferenceMap, RegistrationSettings, register_maps,
)
from devices.auto_position.position_hardware import MapReader
from devices.auto_position.position_logic import AutoPositionLogic


def template(shape=(51, 51)):
    rng = np.random.default_rng(42)
    image = gaussian_filter(rng.normal(size=shape), 1)
    return image * np.hanning(shape[0])[:, None] * np.hanning(shape[1])[None, :]


class FakeRouter:
    def __init__(self, geometry=MapSettings()):
        self.geometry, self.template, self.shift = geometry, template((geometry.y_points, geometry.x_points)), (0, 0)
        self.values = {geometry.x: 0, geometry.y: 0}
        self.writes, self.requests = [], []
        self.main_window = SimpleNamespace(active_scan_range_limits={})
        self.catalog = {}
        for ref, access in ((geometry.x, "writable"), (geometry.y, "writable"), (geometry.signal, "readable")):
            self.catalog.setdefault(ref.device, {"writable": [], "readable": []})[access].append(ref.channel)
        self.on_write = self.on_read = None

    def route_command(self, request):
        self.requests.append(request)
        action = request["action"]
        ref = Channel(request.get("target_device") or "", request.get("channel") or "")
        value = None
        if action == "write":
            if self.on_write:
                self.on_write(ref, request["value"])
            self.values[ref] = request["value"]
            self.writes.append((ref, request["value"]))
        elif action == "read":
            if self.on_read:
                self.on_read()
            g = self.geometry
            col = (self.values[g.x] - g.x_min) / (g.x_max - g.x_min) * (g.x_points - 1) - self.shift[1]
            row = (self.values[g.y] - g.y_min) / (g.y_max - g.y_min) * (g.y_points - 1) - self.shift[0]
            value = float(map_coordinates(self.template, [[row], [col]], order=1, mode="constant", cval=0)[0])
        return {"ok": True, "catalog": self.catalog, "value": value}


class RegistrationTests(unittest.TestCase):
    def test_settings_reference_round_trip_and_validation(self):
        settings = PositionSettings()
        self.assertEqual(PositionSettings.from_dict(json.loads(json.dumps(settings.to_dict()))), settings)
        ref = ReferenceMap(settings.map, settings.point, template())
        restored = ReferenceMap.from_dict(json.loads(json.dumps(ref.to_dict())))
        np.testing.assert_array_equal(restored.image, ref.image)
        self.assertFalse(restored.image.flags.writeable)
        self.assertEqual(restored.point, ref.point)
        for bad in (replace(settings.map, x=settings.map.y), replace(settings.map, x_min=1, x_max=0)):
            with self.assertRaises(ValueError): bad.validate()
        with self.assertRaises(ValueError): replace(settings.registration, max_shift_x=0.1).validate(settings.map)
        with self.assertRaises(ValueError): settings.map.point((1, 0))
        with self.assertRaises(ValueError): ReferenceMap.from_dict({"schema_version": 99})

    def test_all_methods_sign_axis_order_and_subpixel_translation(self):
        image = template()
        g = MapSettings()
        reference = ReferenceMap(g, (0, 0), image)
        for method in ("phase", "intensity", "normalized"):
            for displacement in ((2, -3), (-2, 3), (1.4, -2.3), (0, 0)):
                with self.subTest(method=method, displacement=displacement):
                    current = shift(image, displacement, order=1, mode="constant", cval=0)
                    result = register_maps(reference, current, replace(RegistrationSettings(), method=method), threading.Event())
                    self.assertAlmostEqual(result.alignment_y_pixels, -displacement[0], delta=0.3)
                    self.assertAlmostEqual(result.alignment_x_pixels, -displacement[1], delta=0.3)
                    self.assertAlmostEqual(result.point[0], displacement[1] * 0.002, delta=0.0006)
                    self.assertAlmostEqual(result.point[1], displacement[0] * 0.002, delta=0.0006)
                    self.assertGreater(result.correlation, 0.9)

    def test_nonsquare_geometry_uses_independent_native_pixel_scales(self):
        g = replace(MapSettings(), x_points=61, y_points=41, x_min=-0.1, x_max=0.1)
        image = template((41, 61))
        reference = ReferenceMap(g, (0.01, -0.01), image)
        result = register_maps(reference, shift(image, (2, -3), order=1, mode="constant"), RegistrationSettings(), threading.Event())
        self.assertAlmostEqual(result.point[0], 0, delta=0.0005)
        self.assertAlmostEqual(result.point[1], -0.005, delta=0.0005)

    def test_affine_brightness_change_and_gradient_preprocessing(self):
        image = template()
        ref = ReferenceMap(MapSettings(), (0, 0), image)
        for preprocessing in ("intensity", "gradient"):
            current = 3 * shift(image, (2, -3), order=1, mode="constant") + 7
            result = register_maps(ref, current, replace(RegistrationSettings(), preprocessing=preprocessing), threading.Event())
            self.assertAlmostEqual(result.alignment_x_pixels, 3, delta=0.3)

    def test_flat_unrelated_excessive_shift_and_outside_point_are_rejected(self):
        image = template()
        reference = ReferenceMap(MapSettings(), (0, 0), image)
        for current in (np.ones_like(image), np.random.default_rng(8).normal(size=image.shape),
                        shift(image, (0, 15), order=1, mode="constant")):
            with self.assertRaises(ValueError): register_maps(reference, current, RegistrationSettings(), threading.Event())
        near_edge = replace(reference, point=(0.049, 0))
        with self.assertRaisesRegex(ValueError, "point must lie"):
            register_maps(near_edge, shift(image, (0, 3), order=1, mode="constant"), RegistrationSettings(), threading.Event())

    def test_stop_is_checked_before_registration(self):
        stop = threading.Event()
        stop.set()
        image = template()
        with self.assertRaises(PositionStopped):
            register_maps(ReferenceMap(MapSettings(), (0, 0), image), image, RegistrationSettings(), stop)


class PositionWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_logic(self, directory, geometry=None):
        g = geometry or replace(MapSettings(), settle_s=0, sample_interval_s=0)
        logic, router = AutoPositionLogic(), FakeRouter(g)
        logic.configure_command_router(router)
        logic.apply_settings(PositionSettings(g, RegistrationSettings(), (0, 0), str(directory)))
        return logic, router

    def test_reference_then_position_reuses_fixed_reference_without_double_shift(self):
        with tempfile.TemporaryDirectory() as directory:
            logic, router = self.make_logic(directory)
            self.assertTrue(np.isnan(logic.get_run_key()))
            self.assertEqual(logic.acquire_reference(), 1)
            self.assertTrue(np.isnan(logic.get_run_key()))
            reference, original = logic.reference, logic.reference.image.copy()
            self.assertEqual((router.values[logic.settings.map.x], router.values[logic.settings.map.y]), (0, 0))
            reference_file = Path(logic.last_output_directory) / "reference.json"
            raw_reference = reference_file.read_bytes()
            router.shift = (2, -3)
            paths = []
            for trigger in (0, -7):
                self.assertEqual(logic.set_position(trigger), 1)
                paths.append(logic.last_output_directory)
                self.assertAlmostEqual(logic.get_x(), -0.006, delta=0.0002)
                self.assertAlmostEqual(logic.get_y(), 0.004, delta=0.0002)
                self.assertEqual(logic.reference.reference_id, reference.reference_id)
                np.testing.assert_array_equal(logic.reference.image, original)
                output = Path(logic.last_output_directory)
                self.assertTrue((output / "map.png").is_file())
                self.assertTrue((output / "comparison.png").is_file())
                data = json.loads((output / "run.json").read_text())
                self.assertEqual(data["status"], "complete")
                self.assertEqual(data["run_key"], logic.get_run_key())
                self.assertIn(f"auto-position-{data['run_key']}-", output.name)
                self.assertEqual(int(float(logic.get_run_key())), logic.get_run_key())
                self.assertTrue(data["point_commands_completed"])
                self.assertEqual(data["completed_pixels"], 2601)
            self.assertNotEqual(*paths)
            self.assertEqual(reference_file.read_bytes(), raw_reference)
            self.assertTrue(logic.terminate_dev())

    def test_map_reader_serpentine_orientation_and_non_daq_input(self):
        g = replace(MapSettings(), x_points=9, y_points=7, signal=Channel("keithley24xx", "current"), settle_s=0)
        router, stop = FakeRouter(g), threading.Event()
        reader = MapReader(g, RouterIO(router, "auto_position"))
        reader.prepare(stop)
        image = reader.acquire(stop)
        np.testing.assert_allclose(image, router.template, atol=1e-14)
        self.assertEqual(reader.completed_points, 63)
        self.assertTrue(any(r["target_device"] == "keithley24xx" for r in router.requests))

    def test_global_bounds_and_invalid_directory_prevent_output_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            logic, router = self.make_logic(directory)
            g = logic.settings.map
            router.main_window.active_scan_range_limits[(g.x.device, g.x.channel)] = (-0.01, 0.01)
            with self.assertRaisesRegex(ValueError, "global limits"): logic.acquire_reference()
            self.assertEqual(router.writes, [])
            path = Path(directory) / "file-not-directory"
            path.write_text("existing data")
            logic.settings = replace(logic.settings, directory=str(path))
            with self.assertRaises(OSError): logic.acquire_reference()
            self.assertEqual(router.writes, [])
            self.assertEqual(path.read_text(), "existing data")

    def test_registration_failure_does_not_move_to_a_corrected_point(self):
        with tempfile.TemporaryDirectory() as directory:
            logic, router = self.make_logic(directory)
            logic.acquire_reference()
            router.template = np.ones_like(router.template)
            router.shift = (0, 0)
            with self.assertRaisesRegex(ValueError, "flat"): logic.set_position(1)
            self.assertFalse(logic.applied)
            self.assertEqual(router.values[logic.settings.map.x], logic.settings.map.x_max)
            with self.assertRaises(RuntimeError): logic.get_x()
            data = json.loads((Path(logic.last_output_directory) / "run.json").read_text())
            self.assertEqual(data["status"], "error")
            self.assertEqual(data["run_key"], logic.get_run_key())
            self.assertFalse(data["point_commands_completed"])

    def test_stop_keeps_partial_map_and_last_commands_without_return(self):
        with tempfile.TemporaryDirectory() as directory:
            logic, router = self.make_logic(directory)
            reads = []
            def stop_after_five():
                reads.append(1)
                if len(reads) == 5: logic.stop_event.set()
            router.on_read = stop_after_five
            with self.assertRaises(PositionStopped): logic.acquire_reference()
            self.assertEqual(logic.last_outcome, "stopped")
            self.assertIsNone(logic.reference)
            self.assertLess(logic.reader.completed_points, 2601)
            data = json.loads((Path(logic.last_output_directory) / "run.json").read_text())
            self.assertEqual(data["status"], "stopped")
            self.assertTrue(any(v is None for row in data["image"] for v in row))
            self.assertEqual(data["last_completed_output_commands"]["x"], router.values[logic.settings.map.x])

    def test_reference_load_and_point_edit_are_no_motion_and_keep_original(self):
        with tempfile.TemporaryDirectory() as directory:
            logic, router = self.make_logic(directory)
            logic.acquire_reference()
            path = Path(logic.last_output_directory) / "reference.json"
            old = path.read_bytes()
            writes = list(router.writes)
            logic.disconnect()
            logic.load_reference(path)
            self.assertEqual(router.writes, writes)
            logic.apply_settings(replace(logic.settings, point=(0.002, -0.003)))
            logic.save_edited_point()
            self.assertEqual(logic.reference.point, (0.002, -0.003))
            self.assertEqual(router.writes, writes)
            self.assertEqual(path.read_bytes(), old)
            fresh = AutoPositionLogic()
            fresh.load_reference(path)
            self.assertEqual(fresh.settings.directory, str(path.parent))
            self.assertFalse(fresh.connected)

    def test_no_reference_invalid_trigger_and_geometry_change_prevent_scan(self):
        with tempfile.TemporaryDirectory() as directory:
            logic, router = self.make_logic(directory)
            with self.assertRaisesRegex(RuntimeError, "reference"): logic.set_position(1)
            self.assertEqual(router.writes, [])
            for trigger in (True, float("nan"), float("inf")):
                with self.assertRaises(ValueError): logic.set_position(trigger)
            logic.reference = ReferenceMap(logic.settings.map, (0, 0), router.template.copy())
            logic.settings = replace(logic.settings, map=replace(logic.settings.map, x_points=31))
            with self.assertRaisesRegex(ValueError, "geometry"): logic.set_position(1)
            self.assertEqual(router.writes, [])

    def test_ui_construction_selection_profiles_and_laziness_are_side_effect_free(self):
        from devices.auto_position.position_main import AutoPositionMain
        with mock.patch.object(RouterIO, "write", side_effect=AssertionError("hardware forbidden")):
            panel = AutoPositionMain()
        self.addCleanup(panel.close)
        self.assertEqual(panel.read_settings(), PositionSettings())
        router = FakeRouter()
        panel.configure_command_router(router)
        for method in ("phase", "intensity", "normalized"):
            panel.method.setCurrentIndex(panel.method.findData(method))
            settings = panel.read_settings()
            panel.load_controls(settings)
            self.assertEqual(panel.read_settings(), settings)
        self.assertFalse(panel.logic.connected)
        self.assertEqual(router.writes, [])
        refs = panel.find_catalog_references(removed_device_labels=("nidaq",))
        self.assertTrue(refs)
        panel.detach_command_router()
        panel.detach_command_router()
        from core.device_management.registry import build_default_registry
        registry = build_default_registry()
        self.assertIn("auto_position", registry.driver_ids)
        self.assertFalse(registry.registration("auto_position").runtime_mutation_allowed)
        script = "import sys; from core.device_management.registry import build_default_registry; build_default_registry(); assert not any(k == 'devices' or k.startswith('devices.') for k in sys.modules)"
        result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_scan_row_endpoints_update_midpoint_range_and_pixel_spacing(self):
        from devices.auto_position.position_main import AutoPositionMain
        panel = AutoPositionMain()
        self.addCleanup(panel.close)
        router = FakeRouter()
        panel.configure_command_router(router)
        router.requests.clear()  # Ignore the initial, in-memory catalog lookup.
        x, y = panel.map_axes["x"].fields, panel.map_axes["y"].fields
        original_y = {key: field.value() for key, field in y.items()}
        panel.fields["point_x"].setValue(0.4)
        x["end"].setValue(0.6)
        x["start"].setValue(0.2)
        self.assertAlmostEqual(x["mid"].value(), 0.4)
        self.assertAlmostEqual(x["span"].value(), 0.4)
        self.assertAlmostEqual(x["step"].value(), 0.008)
        x["points"].setValue(101)
        self.assertAlmostEqual(x["step"].value(), 0.004)
        self.assertFalse(x["step"].isReadOnly())
        self.assertEqual(panel.read_settings().map.x_points, 101)
        self.assertEqual({key: field.value() for key, field in y.items()}, original_y)
        self.assertEqual(panel.read_settings().point, (0.4, 0))
        self.assertEqual(router.requests, [])

    def test_scan_row_step_selects_whole_point_count_without_changing_endpoints(self):
        from devices.auto_position.position_main import AutoPositionMain
        panel = AutoPositionMain()
        self.addCleanup(panel.close)
        fields = panel.map_axes["x"].fields
        original = (fields["start"].value(), fields["end"].value())
        fields["step"].setValue(0.01)
        self.assertEqual(fields["points"].value(), 11)
        self.assertAlmostEqual(fields["step"].value(), 0.01)
        fields["step"].setValue(0.003)
        self.assertEqual(fields["points"].value(), 34)
        self.assertAlmostEqual(fields["step"].value(), 0.1 / 33, places=11)
        self.assertEqual(panel.read_settings().map.x_points, 34)
        for invalid in (0, -0.003, 0.1, 1e-12):
            fields["step"].setValue(invalid)
            self.assertEqual(fields["points"].value(), 34)
            self.assertAlmostEqual(fields["step"].value(), 0.1 / 33, places=11)
            self.assertIn("point count was not changed", panel.status.text())
        self.assertEqual((fields["start"].value(), fields["end"].value()), original)
        self.assertEqual(panel.read_settings().point, (0, 0))

    def test_scan_row_midpoint_and_range_edits_update_only_that_axis_endpoints(self):
        from PyQt6 import QtCore, QtTest
        from devices.auto_position.position_main import AutoPositionMain
        panel = AutoPositionMain()
        self.addCleanup(panel.close)
        router = FakeRouter()
        panel.configure_command_router(router)
        router.requests.clear()
        for axis, midpoint, span in (("x", 0.02, 0.2), ("y", -0.01, 0.3)):
            fields = panel.map_axes[axis].fields
            # Typed input is committed with Enter, like the main scan editor.
            fields["mid"].lineEdit().setText(str(midpoint))
            QtTest.QTest.keyClick(fields["mid"], QtCore.Qt.Key.Key_Return)
            self.assertAlmostEqual(fields["start"].value(), midpoint - 0.05)
            self.assertAlmostEqual(fields["end"].value(), midpoint + 0.05)
            fields["span"].setValue(span)
            self.assertAlmostEqual(fields["start"].value(), midpoint - span / 2)
            self.assertAlmostEqual(fields["end"].value(), midpoint + span / 2)
            self.assertAlmostEqual(fields["step"].value(), span / 50)
        settings = panel.read_settings()
        self.assertEqual(settings.point, (0, 0))
        self.assertAlmostEqual(settings.map.x_min, -0.08)
        self.assertAlmostEqual(settings.map.y_max, 0.14)
        self.assertEqual(router.requests, [])

    def test_scan_row_loading_retains_canonical_endpoints_and_setup_schema(self):
        from devices.auto_position.position_main import AutoPositionMain
        panel = AutoPositionMain()
        self.addCleanup(panel.close)
        settings = replace(PositionSettings(), map=replace(MapSettings(), x_min=-0.05, x_max=0.100000001,
                           y_min=-0.400000001, y_max=0.2, x_points=73, y_points=37), point=(0.02, -0.03))
        for _ in range(10):
            panel.load_controls(settings)
            restored = panel.read_settings()
            self.assertEqual(restored, settings)
            # The half-nanounit midpoint is representable without rounding endpoints.
            self.assertAlmostEqual(panel.map_axes["x"].fields["mid"].value(), 0.0250000005, places=10)
            data = json.loads(json.dumps(restored.to_dict()))
            self.assertEqual(data["schema_version"], 1)
            self.assertNotIn("mid", data["map"])
            self.assertNotIn("span", data["map"])
            self.assertEqual(PositionSettings.from_dict(data), settings)

    def test_scan_row_preserves_validation_and_rejects_numeric_clipping(self):
        from devices.auto_position.position_main import AutoPositionMain
        panel = AutoPositionMain()
        self.addCleanup(panel.close)
        fields = panel.map_axes["x"].fields
        self.assertEqual((fields["points"].minimum(), fields["points"].maximum()), (7, 512))
        original = (fields["start"].value(), fields["end"].value())
        fields["mid"].setValue(1e9)
        self.assertEqual((fields["start"].value(), fields["end"].value()), original)
        self.assertEqual(fields["mid"].value(), 0)
        self.assertIn("endpoints were not changed", panel.status.text())
        fields["start"].setValue(0.1)
        with self.assertRaises(ValueError): panel.read_settings()
        fields["start"].setValue(-0.05)
        fields["span"].setValue(0)
        with self.assertRaises(ValueError): panel.read_settings()
        panel.load_controls(PositionSettings())
        self.assertEqual(panel.read_settings(), PositionSettings())

    def test_shutdown_waits_for_inflight_route_and_never_owns_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            logic, router = self.make_logic(directory)
            entered, release = threading.Event(), threading.Event()
            def blocked(ref, value):
                entered.set()
                release.wait(2)
            router.on_write = blocked
            self.assertTrue(logic.submit(logic.acquire_reference))
            self.assertTrue(entered.wait(2))
            self.assertFalse(logic.terminate_dev(wait_ms=5))
            self.assertIs(logic.router, router)
            release.set()
            self.assertTrue(logic.wait(5000))
            self.assertTrue(logic.terminate_dev())
            self.assertIsNone(logic.router)

    def test_focus_then_position_blocks_before_inner_measurements(self):
        from core.scan_logic import ScanLogic
        from devices.auto_focus.autofocus_logic import AutofocusLogic
        from devices.auto_focus.tests.test_autofocus import FakeAxis, FakeSource, quick_settings
        with tempfile.TemporaryDirectory() as directory:
            position, router = self.make_logic(directory)
            position.acquire_reference()
            router.shift = (2, -3)
            axis = FakeAxis()
            focus = AutofocusLogic(
                z_factories={"routed": ("Fake Z", lambda settings, io: axis)},
                source_factories={"point": ("Fake signal", lambda settings, io: FakeSource(axis))})
            focus.apply_settings(quick_settings())
            focus.connect_z()
            events = []
            owner = self
            class Window:
                equips = {key: object() for key in ("temperature", "auto_focus", "auto_position", "measurement")}
                artificial_channel_logic = SimpleNamespace(
                    artificial_channels=(), has_artificial_channel=lambda channel: False,
                    consume_skip_read_for_scan=lambda: False)
                def write_info(self, value, channel):
                    if channel == "temperature_stable": events.append("temperature")
                    elif channel == "auto_focus_focus":
                        events.append("focus_start")
                        focus.set_focus(value)
                        events.append("focus_done")
                    elif channel == "auto_position_position":
                        events.append("position_start")
                        position.set_position(value)
                        events.append("position_done")
                    else:
                        owner.assertAlmostEqual(position.get_x(), -0.006, delta=0.0002)
                        events.append("measurement")
                def read_info(self, channel):
                    return {"auto_focus_run_key": focus.get_run_key,
                            "auto_position_run_key": position.get_run_key}[channel]()
            def level(channel, values, getters=()):
                return {"setters": {"setter0": {"channel": channel}}, "getters": list(getters),
                        "setting_array": np.array([values]), "settle_time": 0, "start_wait_time": 0,
                        "manual_set_before": [], "manual_set_after": []}
            scan = ScanLogic(main_window=Window())
            scan.initialize_scan_data({"levels": {
                "level3": level("temperature_stable", [100, 110]),
                "level2": level("auto_focus_focus", [1]),
                "level1": level("auto_position_position", [1]),
                "level0": level("measurement_bias", [1, 2], ["auto_focus_run_key", "auto_position_run_key"])}})
            with mock.patch("devices.auto_focus.autofocus_logic.new_run_key", side_effect=[20261022181250, 20261022181300]), \
                 mock.patch("devices.auto_position.position_logic.new_run_key", side_effect=[20261022181252, 20261022181302]):
                scan.looping(scan.max_level)
            np.testing.assert_array_equal(scan.level_data_arrays[0].reshape(2, -1), [
                [20261022181250, 20261022181250, 20261022181300, 20261022181300],
                [20261022181252, 20261022181252, 20261022181302, 20261022181302]])
            self.assertEqual(events, ["temperature", "focus_start", "focus_done", "position_start", "position_done", "measurement", "measurement"] * 2)
            self.assertTrue(focus.terminate_dev())

    def test_profile_manager_channel_filters_and_construction_never_touch_hardware(self):
        from core.device_management.config import load_profile
        from core.device_management.manager import DeviceManager
        from core.device_management.registry import build_default_registry
        registry = build_default_registry()
        root = Path(__file__).resolve().parents[3]
        profile = load_profile(root / "device_config.xlsx", driver_specs=registry.config_specs, repository_root=root)
        config = next(row for row in profile.devices if row.driver == "auto_position")
        self.assertFalse(config.enabled)
        self.assertFalse(config.connect_on_start)
        self.assertEqual(config.connection["address"], "")
        self.assertEqual(config.scan_channels.setters, ("position",))
        self.assertEqual(config.scan_channels.getters, ("x", "y", "shift_x", "shift_y", "correlation", "run_key"))
        config = replace(config, enabled=True)  # No physical devices enter this fixture.
        with mock.patch.object(RouterIO, "write", side_effect=AssertionError("real output forbidden")) as write:
            manager = DeviceManager(registry, SimpleNamespace())
            snapshot = manager.load_profile(replace(profile, devices=(config,)))
            manager.request_startup_connections()
            self.assertFalse(snapshot.equipment[config.id].logic.connected)
            self.assertTrue(manager.teardown_all().succeeded)
            write.assert_not_called()

    def test_second_axis_failure_and_saving_failure_never_report_success(self):
        with tempfile.TemporaryDirectory() as directory:
            logic, router = self.make_logic(directory)
            logic.acquire_reference()
            router.shift = (2, -3)
            before_move = []
            real_move = MapReader.move
            def fail_final(reader, point, stop):
                if logic.result is not None:
                    before_move.append(point)
                    reader.io.write(reader.geometry.x, point[0])
                    reader.last_commands["x"] = point[0]
                    raise RuntimeError("Y output failed after X completed")
                return real_move(reader, point, stop)
            with mock.patch.object(MapReader, "move", fail_final):
                with self.assertRaisesRegex(RuntimeError, "Y output failed"): logic.set_position(1)
            self.assertEqual(len(before_move), 1)
            self.assertFalse(logic.applied)
            self.assertEqual(logic.last_outcome, "error")
            data = json.loads((Path(logic.last_output_directory) / "run.json").read_text())
            self.assertEqual(data["last_completed_output_commands"]["x"], before_move[0][0])
            self.assertFalse(data["point_commands_completed"])
            from core.measurement_records import RunRecord
            original_json = RunRecord.json
            def fail_complete(record, name, payload):
                if payload.get("status") == "complete": raise OSError("disk full after movement")
                return original_json(record, name, payload)
            with mock.patch.object(RunRecord, "json", fail_complete):
                with self.assertRaisesRegex(OSError, "disk full"): logic.set_position(1)
            self.assertTrue(logic.applied)  # Never pretend the physical command was undone.
            self.assertEqual(logic.last_outcome, "error")
            with self.assertRaises(RuntimeError): logic.get_x()

    def test_worker_is_responsive_during_map_and_reference_signal_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            geometry = replace(MapSettings(), x_points=11, y_points=11, settle_s=0.001)
            logic, router = self.make_logic(directory, geometry)
            signals = []
            logic.sig_reference.connect(signals.append)
            self.assertTrue(logic.submit(logic.acquire_reference))
            ticks, deadline = 0, time.monotonic() + 8
            while logic.isRunning() and time.monotonic() < deadline:
                self.app.processEvents()
                ticks += 1
                time.sleep(0.001)
            self.app.processEvents()
            self.assertFalse(logic.isRunning())
            self.assertGreater(ticks, 5)
            self.assertEqual(len(signals), 1)
            self.assertIsNotNone(signals[0])

    def test_atomic_record_failure_preserves_existing_file_and_cleans_temporary(self):
        from core.measurement_records import RunRecord
        with tempfile.TemporaryDirectory() as directory:
            record = RunRecord(directory, "test")
            record.json("values.json", {"value": 1})
            original = (record.path / "values.json").read_bytes()
            with mock.patch("core.measurement_records.os.replace", side_effect=OSError("simulated commit failure")):
                with self.assertRaises(OSError): record.json("values.json", {"value": 2})
            self.assertEqual((record.path / "values.json").read_bytes(), original)
            self.assertEqual(list(record.path.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
