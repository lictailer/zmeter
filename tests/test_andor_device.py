"""Andor camera + Shamrock driver against a fake pylablib (no hardware, no SDK)."""

import inspect
import os
import sys
import threading
import time
import types
import unittest
from types import SimpleNamespace

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.array_getters import describe_array_getter


class FakeCamera:
    instances = []
    open_delay_s = 0.0
    snap_error = None

    def __init__(self, idx=0, temperature=None, fan_mode="full"):
        if FakeCamera.open_delay_s:
            time.sleep(FakeCamera.open_delay_s)
        self.idx = idx
        self.temperature_arg = temperature
        self.exposure = 0.1
        self.temperature = 20.0
        self.read_mode = "fvb"
        self.acquisition_mode = "single"
        self.snap_calls = []
        self.stop_calls = 0
        self.closed = False
        FakeCamera.instances.append(self)

    def get_device_info(self):
        return {"head_model": "FAKE-DU401", "serial_number": 1}

    def set_exposure(self, value):
        self.exposure = value

    def get_exposure(self):
        return self.exposure

    def set_temperature(self, value):
        self.target = value

    def get_temperature(self):
        return self.temperature

    def set_cooler(self, on):
        self.cooler = on

    def is_cooler_on(self):
        return getattr(self, "cooler", False)

    def set_read_mode(self, mode):
        self.read_mode = mode

    def get_read_mode(self):
        return self.read_mode

    def set_acquisition_mode(self, mode):
        self.acquisition_mode = mode

    def get_acquisition_mode(self):
        return self.acquisition_mode

    def setup_accum_mode(self, num, cycle):
        self.accum = (num, cycle)

    def get_accum_mode_parameters(self):
        return getattr(self, "accum", (1, 0.0))

    def get_cycle_timings(self):
        return (self.exposure, 0.0, 0.0)

    def get_detector_size(self):
        return (8, 16)

    def get_data_dimensions(self):
        return (1, 16) if self.read_mode in ("fvb", "single_track") else (8, 16)

    def snap(self, timeout=None):
        self.snap_calls.append(timeout)
        if FakeCamera.snap_error is not None:
            raise FakeCamera.snap_error
        rows, columns = self.get_data_dimensions()
        return np.tile(np.arange(columns, dtype=float), (rows, 1))

    def start_acquisition(self):
        pass

    def stop_acquisition(self):
        self.stop_calls += 1

    def close(self):
        self.closed = True


class FakeShamrock:
    def __init__(self, idx=0):
        self.idx = idx
        self.wavelength_m = 600e-9
        self.calibration_calls = 0
        self.closed = False

    def get_device_info(self):
        return {"serial": "SR-FAKE"}

    def get_optical_parameters(self):
        return {}

    def get_status(self):
        return "ok"

    def set_wavelength(self, value):
        self.wavelength_m = value

    def get_wavelength(self):
        return self.wavelength_m

    def setup_pixels_from_camera(self, camera):
        self.camera = camera

    def get_calibration(self):
        self.calibration_calls += 1
        return self.wavelength_m + (np.arange(16) - 8) * 1e-10

    def close(self):
        self.closed = True


def install_fake_pylablib():
    andor = types.ModuleType("pylablib.devices.Andor")
    andor.AndorSDK2Camera = FakeCamera
    andor.ShamrockSpectrograph = FakeShamrock
    andor.get_cameras_number_SDK2 = lambda: 1
    andor.list_shamrock_spectrographs = lambda: ["SR-FAKE"]
    devices = types.ModuleType("pylablib.devices")
    devices.Andor = andor
    root = types.ModuleType("pylablib")
    root.devices = devices
    saved = {name: sys.modules.get(name) for name in ("pylablib", "pylablib.devices", "pylablib.devices.Andor")}
    sys.modules.update({"pylablib": root, "pylablib.devices": devices, "pylablib.devices.Andor": andor})

    def restore():
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    return restore


def scan_signature_ok(method, name):
    parameters = [
        p
        for p in inspect.signature(method).parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
    ]
    required = [p for p in parameters if p.default is p.empty]
    if name.startswith("get_"):
        return len(required) == 0
    return len(required) == 1


class AndorLogicTests(unittest.TestCase):
    def setUp(self):
        FakeCamera.instances = []
        FakeCamera.open_delay_s = 0.0
        FakeCamera.snap_error = None
        self.addCleanup(install_fake_pylablib())
        from devices.andor.andor_logic import AndorCameraLogic

        self.logic = AndorCameraLogic()
        self.logs = []
        self.logic.sig_log.connect(lambda level, message: self.logs.append((level, message)))

    def connect(self):
        self.assertTrue(self.logic.connect_devices(0, 0))
        return FakeCamera.instances[-1], self.logic.spectrometer_hardware._spectrograph

    def test_import_and_failed_connect_without_pylablib(self):
        saved = {name: sys.modules.pop(name, None) for name in ("pylablib", "pylablib.devices", "pylablib.devices.Andor")}
        sys.modules["pylablib"] = None  # import fails like a missing package
        try:
            self.assertFalse(self.logic.connect_camera(0))
            self.assertFalse(self.logic.connected)
            self.assertTrue(any("pylablib" in message for _level, message in self.logs))
        finally:
            sys.modules.pop("pylablib", None)
            for name, module in saved.items():
                if module is not None:
                    sys.modules[name] = module

    def test_scan_channels_are_exactly_the_reviewed_set(self):
        names = {
            name
            for name in dir(self.logic)
            if name.startswith(("get_", "set_"))
            and callable(getattr(self.logic, name))
            and scan_signature_ok(getattr(self.logic, name), name)
        }
        self.assertEqual(
            names,
            {
                "get_temperature", "get_exposure_time", "get_center_wavelength",
                "get_spectrum", "get_image",
                "set_temperature", "set_exposure_time", "set_center_wavelength",
            },
        )
        self.assertEqual(self.logic.SNAPSHOT_GETTERS, ("temperature", "exposure_time", "center_wavelength"))

    def test_spectrum_is_one_dimensional_with_nm_axis(self):
        camera, shamrock = self.connect()
        spectrum = self.logic.get_spectrum()
        self.assertEqual(spectrum.shape, (16,))
        np.testing.assert_allclose(spectrum, np.arange(16.0))
        info = describe_array_getter(self.logic, "spectrum", "andor_0_spectrum")
        self.assertEqual(info.shape, (16,))
        self.assertAlmostEqual(info.axis_values[0][8], 600.0)
        self.assertAlmostEqual(info.axis_values[0][9], 600.1)
        # Calibration is cached until the centre wavelength changes.
        self.logic.spectrum_axis()
        self.assertEqual(shamrock.calibration_calls, 1)
        self.assertEqual(self.logic.set_center_wavelength(650), 650.0)
        self.assertAlmostEqual(shamrock.wavelength_m, 650e-9)
        self.assertAlmostEqual(self.logic.get_center_wavelength(), 650.0)
        self.assertAlmostEqual(self.logic.spectrum_axis()[8], 650.0)
        self.assertEqual(shamrock.calibration_calls, 2)

    def test_image_mode_frame_and_summed_spectrum(self):
        camera, _ = self.connect()
        self.logic.setpoint_read_mode = "image"
        self.logic.setup_read_mode()
        self.assertEqual(self.logic.image_shape(), (8, 16))
        self.assertEqual(self.logic.get_image().shape, (8, 16))
        np.testing.assert_allclose(self.logic.get_spectrum(), 8 * np.arange(16.0))
        frame = describe_array_getter(self.logic, "image")
        self.assertEqual(frame.axes, ("row", "column"))
        self.assertEqual(frame.shape, (8, 16))

    def test_snap_timeout_from_timings_and_no_retry(self):
        camera, _ = self.connect()
        self.logic.set_exposure_time(2.0)
        self.logic.get_spectrum()
        self.assertEqual(camera.snap_calls, [12.0])
        FakeCamera.snap_error = RuntimeError("timeout")
        with self.assertRaises(RuntimeError):
            self.logic.get_spectrum()
        self.assertEqual(len(camera.snap_calls), 2)

    def test_setters_check_values(self):
        self.connect()
        for bad in (float("nan"), float("inf"), "abc", None):
            with self.assertRaises((TypeError, ValueError)):
                self.logic.set_exposure_time(bad)
        with self.assertRaises(ValueError):
            self.logic.set_temperature(-200)
        with self.assertRaises(ValueError):
            self.logic.set_center_wavelength(0)
        self.assertEqual(self.logic.set_temperature(-60.4), -60)

    def test_force_stop_aborts_without_disconnecting(self):
        camera, _ = self.connect()
        self.assertTrue(self.logic.abort_exposure())
        self.assertEqual(camera.stop_calls, 1)
        self.assertTrue(self.logic.connected)
        self.assertFalse(camera.closed)

    def test_shapes_require_a_connection(self):
        with self.assertRaises(RuntimeError):
            self.logic.spectrum_shape()
        self.assertIsNone(self.logic.spectrum_axis())

    def test_bounded_connect_abandons_a_slow_open(self):
        FakeCamera.open_delay_s = 0.3
        self.assertFalse(self.logic.connect_with_timeout(0, None, 50))
        deadline = time.time() + 3
        while time.time() < deadline and not FakeCamera.instances:
            time.sleep(0.02)
        deadline = time.time() + 3
        while time.time() < deadline and not FakeCamera.instances[-1].closed:
            time.sleep(0.02)
        self.assertTrue(FakeCamera.instances[-1].closed)
        self.assertFalse(self.logic.connected)

    def test_bounded_connect_success_is_literal_true(self):
        self.assertIs(self.logic.connect_with_timeout(0, None, 2000), True)
        self.assertTrue(self.logic.connected)
        self.assertFalse(self.logic.spectrometer_connected)

    def test_parse_address(self):
        from devices.andor.andor_logic import parse_address

        self.assertEqual(parse_address(""), (0, 0))
        self.assertEqual(parse_address("1"), (1, 0))
        self.assertEqual(parse_address("0, 2"), (0, 2))
        self.assertEqual(parse_address("0,none"), (0, None))
        with self.assertRaises(ValueError):
            parse_address("cam")


class AndorWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        FakeCamera.instances = []
        FakeCamera.open_delay_s = 0.0
        FakeCamera.snap_error = None
        self.addCleanup(install_fake_pylablib())
        self.counts = []
        andor_module = sys.modules["pylablib.devices.Andor"]
        andor_module.get_cameras_number_SDK2 = lambda: self.counts.append("camera") or 1
        from devices.andor.andor_main import Andor

        self.widget = Andor()
        self.addCleanup(self.widget.deleteLater)

    def test_constructor_does_not_enumerate_devices(self):
        self.assertEqual(self.counts, [])

    def test_scan_lifecycle_pauses_panel_and_restores_monitor(self):
        self.assertTrue(self.widget.connect("0,none", 2000))
        self.assertTrue(self.widget.timer.isActive())
        self.assertTrue(self.widget.stop_scan())
        self.assertFalse(self.widget.timer.isActive())
        self.assertFalse(self.widget._start_logic_job("monitor_poll"))
        self.assertTrue(self.widget.start_scan())
        self.assertTrue(self.widget.timer.isActive())
        self.assertFalse(self.widget.logic.scan_admission_closed)

    def test_terminate_disconnects(self):
        self.assertTrue(self.widget.connect("0,0", 2000))
        camera = FakeCamera.instances[-1]
        self.assertTrue(self.widget.terminate_dev())
        self.assertTrue(camera.closed)
        self.assertFalse(self.widget.logic.connected)

    def test_registration(self):
        from core.device_management import build_default_registry
        from core.device_management.registrations import andor_registration

        self.assertIn("andor", build_default_registry().driver_ids)
        registration = andor_registration()
        self.assertTrue(registration.connect(self.widget, {"address": "0,none"}, 2000))
        self.assertTrue(registration.is_connected(self.widget))
        self.assertTrue(registration.force_stop(self.widget))
        self.assertTrue(registration.is_connected(self.widget))
        registration.disconnect(self.widget)
        self.assertFalse(registration.is_connected(self.widget))


if __name__ == "__main__":
    unittest.main()
