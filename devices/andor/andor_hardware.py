"""pylablib wrappers for an Andor SDK2 camera and a Shamrock spectrograph.

Ported from the bench-tested Mfork ``Andor/andor_hardware_new.py``.  Changes
for this ZMeter:

* pylablib is imported lazily, when a device is opened, so ZMeter starts and
  the device package imports on machines without pylablib or the Andor SDK;
* ``snap_image`` takes its timeout from the caller (acquisition timings) and is
  never retried: a retried snap would expose the detector again;
* ``abort_acquisition`` only aborts the running exposure (used by force stop);
* the connect-time temperature argument defaults to ``None`` (leave the cooler
  as it is) instead of ``"off"``, so reconnecting never switches cooling off.

All units are pylablib's SI units (seconds, metres, degrees Celsius); the logic
layer converts wavelengths to nanometres for scans.
"""

from __future__ import annotations

import time
from typing import Any


def _andor_module():
    """Import ``pylablib.devices.Andor`` on first use with a clear error."""
    try:
        from pylablib.devices import Andor  # noqa: PLC0415 - optional dependency
    except Exception as exc:  # noqa: BLE001 - ImportError or SDK load failure
        raise RuntimeError(
            "pylablib (with the Andor SDK2 and Shamrock DLLs) is required for the "
            f"Andor device: {type(exc).__name__}: {exc}"
        ) from exc
    return Andor


def camera_count() -> int:
    return int(_andor_module().get_cameras_number_SDK2())


def spectrograph_count() -> int:
    spectrographs = _andor_module().list_shamrock_spectrographs()
    return len(spectrographs) if spectrographs is not None else 0


class AndorCameraHardware:
    """Thin pylablib wrapper for Andor SDK2 cameras."""

    _acq_mode_map = {
        "single": "single",
        "continuous": "cont",
        "cont": "cont",
        "kinetic": "kinetic",
        "accumulate": "accum",
        "accum": "accum",
    }
    _read_modes = {"fvb", "single_track", "multi_track", "random_track", "image"}

    def __init__(
        self,
        camera_index: int = 0,
        temperature: Any = None,
        fan_mode: str = "full",
    ):
        self._camera_index = int(camera_index)
        self._camera = _andor_module().AndorSDK2Camera(
            idx=self._camera_index,
            temperature=temperature,
            fan_mode=fan_mode,
        )
        self._exposure_time = 0.0

    def _require_camera(self):
        if self._camera is None:
            raise RuntimeError("Camera is not connected")
        return self._camera

    def _safe_get(self, func, *args, **kwargs):
        """Parameter reads only: retried, because they have no side effect."""
        last_exc = None
        for _attempt in range(3):
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - vendor error types vary
                last_exc = exc
                time.sleep(0.05)
        raise RuntimeError(f"Camera is not responding: {last_exc}") from last_exc

    def _safe_set(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Camera set operation failed: {exc}") from exc

    def get_device_info(self):
        return self._safe_get(self._require_camera().get_device_info)

    def acquisition_mode(self, mode=None, *, write=False, read=False):
        camera = self._require_camera()
        if write:
            if mode not in self._acq_mode_map:
                raise ValueError(f"mode must be one of {sorted(self._acq_mode_map)}")
            self._safe_set(camera.set_acquisition_mode, self._acq_mode_map[mode])
            return None
        if read:
            raw_mode = self._safe_get(camera.get_acquisition_mode)
            for public_name, pylablib_name in self._acq_mode_map.items():
                if pylablib_name == raw_mode and public_name not in ("cont", "accum"):
                    return public_name
            return raw_mode
        raise ValueError("Either write or read must be True")

    def exposure_time(self, time_s: float | None = None, *, write=False, read=False):
        camera = self._require_camera()
        if write:
            if time_s is None or float(time_s) <= 0:
                raise ValueError("exposure time must be positive")
            self._safe_set(camera.set_exposure, float(time_s))
            self._exposure_time = float(time_s)
            return None
        if read:
            self._exposure_time = float(self._safe_get(camera.get_exposure))
            return self._exposure_time
        raise ValueError("Either write or read must be True")

    def temperature(self, temp_c: int | None = None, *, write=False, read=False):
        camera = self._require_camera()
        if write:
            if temp_c is None:
                raise ValueError("temperature value is required")
            self._safe_set(camera.set_temperature, int(temp_c))
            return None
        if read:
            return self._safe_get(camera.get_temperature)
        raise ValueError("Either write or read must be True")

    def cooler(self, cooler: bool | None = None, *, write=False, read=False):
        camera = self._require_camera()
        if write:
            if cooler is None:
                raise ValueError("cooler value is required")
            self._safe_set(camera.set_cooler, bool(cooler))
            return None
        if read:
            if hasattr(camera, "is_cooler_on"):
                return self._safe_get(camera.is_cooler_on)
            return None
        raise ValueError("Either write or read must be True")

    def read_mode(self, mode: str | None = None, *, write=False, read=False):
        camera = self._require_camera()
        if write:
            if mode not in self._read_modes:
                raise ValueError(f"mode must be one of {sorted(self._read_modes)}")
            self._safe_set(camera.set_read_mode, mode)
            return None
        if read:
            return self._safe_get(camera.get_read_mode)
        raise ValueError("Either write or read must be True")

    def setup_accumulation_mode(
        self,
        num_acc: int = 1,
        cycle_time_acc: float = 0.0,
        *,
        write=False,
        read=False,
    ):
        camera = self._require_camera()
        if write:
            self._safe_set(camera.setup_accum_mode, int(num_acc), float(cycle_time_acc))
            return None
        if read:
            return self._safe_get(camera.get_accum_mode_parameters)
        raise ValueError("Either write or read must be True")

    def setup_continuous_mode(self, cycle_time: float = 0.0, *, write=False, read=False):
        camera = self._require_camera()
        if write:
            self._safe_set(camera.setup_cont_mode, float(cycle_time))
            return None
        if read:
            return self._safe_get(camera.get_cont_mode_parameters)
        raise ValueError("Either write or read must be True")

    def setup_kinetic_mode(
        self,
        num_cycle: int,
        cycle_time: float = 0.0,
        num_acc: int = 1,
        cycle_time_acc: float = 0.0,
        num_prescan: int = 0,
        *,
        write=False,
        read=False,
    ):
        camera = self._require_camera()
        if write:
            self._safe_set(
                camera.setup_kinetic_mode,
                int(num_cycle),
                float(cycle_time),
                int(num_acc),
                float(cycle_time_acc),
                int(num_prescan),
            )
            return None
        if read:
            return self._safe_get(camera.get_kinetic_mode_parameters)
        raise ValueError("Either write or read must be True")

    def start_acquisition(self):
        self._safe_set(self._require_camera().start_acquisition)

    def stop_acquisition(self):
        self._safe_set(self._require_camera().stop_acquisition)

    def abort_acquisition(self) -> bool:
        """Abort a running exposure; returns whether a camera was there."""
        camera = self._camera
        if camera is None:
            return False
        camera.stop_acquisition()
        return True

    def wait_for_frame(self, timeout: float | None = None):
        camera = self._require_camera()
        if timeout is None:
            return self._safe_set(camera.wait_for_frame)
        return self._safe_set(camera.wait_for_frame, timeout=timeout)

    def read_oldest_image(self):
        return self._safe_get(self._require_camera().read_oldest_image)

    def read_newest_image(self):
        return self._safe_get(self._require_camera().read_newest_image)

    def get_acquisition_timings(self):
        return self._safe_get(self._require_camera().get_cycle_timings)

    def get_frame_period(self):
        return self._safe_get(self._require_camera().get_frame_period)

    def get_frames_status(self):
        return self._safe_get(self._require_camera().get_frames_status)

    def clear_acquisition(self):
        self._safe_set(self._require_camera().clear_acquisition)

    def snap_image(self, timeout: float):
        """One exposure; never retried (a retry would expose the detector again)."""
        camera = self._require_camera()
        try:
            return camera.snap(timeout=float(timeout))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Camera snap failed: {exc}") from exc

    def get_detector_size(self):
        return self._safe_get(self._require_camera().get_detector_size)

    def get_data_dimensions(self):
        """(rows, columns) of one frame in the current read mode and ROI."""
        return self._safe_get(self._require_camera().get_data_dimensions)

    def get_camera(self):
        return self._camera

    def get_minimum_shutter_time(self):
        return self._safe_get(self._require_camera().get_min_shutter_times)

    def disconnect(self):
        camera = getattr(self, "_camera", None)
        if camera is None:
            return
        try:
            camera.close()
        finally:
            self._camera = None

    close = disconnect


class ShamrockSpectrogramHardware:
    """Thin pylablib wrapper for Andor Shamrock spectrographs."""

    _grating_map = {
        "grating_1": 1,
        "grating_2": 2,
        "grating_3": 3,
    }
    _slit_map = {
        "input_slit": "input",
        "output_slit": "output",
        "side_slit": "side",
    }
    _flipper_map = {
        "direct": "direct",
        "side": "side",
    }

    def __init__(self, idx: int = 0):
        self._idx = int(idx)
        self._spectrograph = _andor_module().ShamrockSpectrograph(idx=self._idx)

    def _require(self):
        if self._spectrograph is None:
            raise RuntimeError("Spectrograph is not connected")
        return self._spectrograph

    def _safe_get(self, func, *args, **kwargs):
        last_exc = None
        for _attempt in range(3):
            try:
                return func(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                time.sleep(0.05)
        raise RuntimeError(f"Spectrograph is not responding: {last_exc}") from last_exc

    def _safe_set(self, func, *args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Spectrograph set operation failed: {exc}") from exc

    def get_device_info(self):
        return self._safe_get(self._require().get_device_info)

    def get_optical_parameters(self):
        return self._safe_get(self._require().get_optical_parameters)

    def center_wavelength(self, wavelength_m: float | None = None, *, write=False, read=False):
        """Centre wavelength in metres (pylablib units)."""
        spectrograph = self._require()
        if write:
            if wavelength_m is None or float(wavelength_m) <= 0:
                raise ValueError("wavelength must be positive")
            self._safe_set(spectrograph.set_wavelength, float(wavelength_m))
            return None
        if read:
            return self._safe_get(spectrograph.get_wavelength)
        raise ValueError("Either write or read must be True")

    def wavelength_range(self, read=False):
        if read:
            return self._safe_get(self._require().get_wavelength_range)
        raise ValueError("read must be True for wavelength_range")

    def grating(self, grating_num: str | int | None = None, *, write=False, read=False):
        spectrograph = self._require()
        if write:
            if grating_num in self._grating_map:
                value = self._grating_map[grating_num]
            elif isinstance(grating_num, int) and grating_num in self._grating_map.values():
                value = grating_num
            else:
                raise ValueError("invalid grating")
            self._safe_set(spectrograph.set_grating, value)
            return None
        if read:
            grating_idx = self._safe_get(spectrograph.get_grating)
            for key, value in self._grating_map.items():
                if value == grating_idx:
                    return key
            return grating_idx
        raise ValueError("Either write or read must be True")

    def grating_info(self, grating_num: int | None = None):
        spectrograph = self._require()
        if grating_num is None:
            return self._safe_get(spectrograph.get_all_grating_info)
        return self._safe_get(spectrograph.get_grating_info, int(grating_num))

    def slit_width(
        self,
        slit_type: str,
        width: float | None = None,
        *,
        write=False,
        read=False,
    ):
        spectrograph = self._require()
        if slit_type not in self._slit_map:
            raise ValueError("invalid slit type")
        slit_name = self._slit_map[slit_type]
        if write:
            if width is None or float(width) <= 0:
                raise ValueError("slit width must be positive")
            self._safe_set(spectrograph.set_slit_width, slit_name, float(width))
            return None
        if read:
            return self._safe_get(spectrograph.get_slit_width, slit_name)
        raise ValueError("Either write or read must be True")

    def slit_width_range(self, slit_type: str):
        if slit_type not in self._slit_map:
            raise ValueError("invalid slit type")
        return self._safe_get(
            self._require().get_slit_width_range,
            self._slit_map[slit_type],
        )

    def flipper_mirror(self, position: str | None = None, *, write=False, read=False):
        spectrograph = self._require()
        if write:
            if position not in self._flipper_map:
                raise ValueError("invalid flipper position")
            self._safe_set(spectrograph.set_flipper_mirror, position)
            return None
        if read:
            return self._safe_get(spectrograph.get_flipper_mirror)
        raise ValueError("Either write or read must be True")

    def pixel_to_wavelength(self, pixel_array):
        return self._safe_get(self._require().pixel_to_wavelength, pixel_array)

    def wavelength_to_pixel(self, wavelength_array):
        return self._safe_get(self._require().wavelength_to_pixel, wavelength_array)

    def setup_pixels_from_camera(self, camera_hardware: AndorCameraHardware):
        camera = camera_hardware.get_camera()
        setup = getattr(self._require(), "setup_pixels_from_camera", None)
        if setup is None:
            raise RuntimeError("Shamrock driver does not expose setup_pixels_from_camera")
        self._safe_set(setup, camera)

    def get_calibration(self):
        """Wavelength of every camera pixel column, in metres."""
        spectrograph = self._require()
        get_calibration = getattr(spectrograph, "get_calibration", None)
        if get_calibration is not None:
            return self._safe_get(get_calibration)
        return self._safe_get(spectrograph.get_wavelength_calibration)

    def filter_position(self, position: int | None = None, *, write=False, read=False):
        spectrograph = self._require()
        if write:
            if position is None or int(position) < 1:
                raise ValueError("filter position must be a positive integer")
            self._safe_set(spectrograph.set_filter, int(position))
            return None
        if read:
            return self._safe_get(spectrograph.get_filter)
        raise ValueError("Either write or read must be True")

    def filter_info(self):
        return self._safe_get(self._require().get_filter_info)

    def detector_offset(self, offset: float | None = None, *, write=False, read=False):
        spectrograph = self._require()
        if write:
            if offset is None:
                raise ValueError("detector offset is required")
            self._safe_set(spectrograph.set_detector_offset, float(offset))
            return None
        if read:
            return self._safe_get(spectrograph.get_detector_offset)
        raise ValueError("Either write or read must be True")

    def is_calibrated(self):
        return self._safe_get(self._require().is_calibrated)

    def get_status(self):
        return self._safe_get(self._require().get_status)

    def home_grating(self):
        self._safe_set(self._require().home_grating)

    def reset_spectrograph(self):
        self._safe_set(self._require().reset)

    def disconnect(self):
        spectrograph = getattr(self, "_spectrograph", None)
        if spectrograph is None:
            return
        try:
            spectrograph.close()
        finally:
            self._spectrograph = None

    close = disconnect
