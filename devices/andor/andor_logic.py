"""Scan-facing logic for an Andor SDK2 camera with a Shamrock spectrograph.

Ported from the bench-tested Mfork ``Andor/andor_logic.py`` and reviewed
against ``documents/device_contract.md``.  What changed and why:

* every SDK call runs under one re-entrant lock, so panel jobs, the monitor
  and scan reads never talk to the camera at the same time;
* ``get_spectrum`` returns a 1-D array (counts per pixel column) and
  ``get_image`` a 2-D frame.  Both are array getters (``ARRAY_GETTERS``): the
  scan adds fixed levels for their axes, so the old ``2 x N`` return and the
  ``get_spectrum_mean`` / ``get_spectrum_sum`` helpers are gone (use a level
  average of the spectrum for a scalar);
* the wavelength calibration is cached and only re-read when the centre
  wavelength, grating, read mode or connection changes;
* centre wavelength is in nanometres for scans (pylablib uses metres);
* setters take one positional value and check it is finite and in range;
* a snap's timeout comes from the camera's acquisition timings and is never
  retried; ``abort_exposure`` (force stop) only aborts the exposure and keeps
  the camera connected;
* panel jobs are refused while a scan owns the device.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any

import numpy as np
from PyQt6 import QtCore

from core.array_getters import ArrayGetter

from . import andor_hardware
from .andor_hardware import AndorCameraHardware, ShamrockSpectrogramHardware


def parse_address(address) -> tuple[int, int | None]:
    """``"<camera>[,<spectrograph>|none]"`` -> indexes; empty means ``0,0``."""
    text = str(address or "").strip()
    if not text:
        return 0, 0
    parts = [part.strip() for part in text.replace(";", ",").split(",")]
    try:
        camera = int(parts[0])
    except ValueError as exc:
        raise ValueError(f"Andor address {address!r}: camera index must be an integer") from exc
    if camera < 0:
        raise ValueError(f"Andor address {address!r}: camera index must be >= 0")
    if len(parts) < 2 or parts[1] == "":
        return camera, 0
    if parts[1].lower() in {"none", "-", "no"}:
        return camera, None
    try:
        spectrograph = int(parts[1])
    except ValueError as exc:
        raise ValueError(
            f"Andor address {address!r}: spectrograph index must be an integer or 'none'"
        ) from exc
    if spectrograph < 0:
        raise ValueError(f"Andor address {address!r}: spectrograph index must be >= 0")
    return camera, spectrograph


def _finite(value, name) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


class AndorCameraLogic(QtCore.QThread):
    """pylablib camera/spectrograph controller for the Andor widget."""

    # Array getters: the scan turns each axis into a fixed level.
    ARRAY_GETTERS = {
        "spectrum": ArrayGetter(
            axes=("pixel",),
            shape="spectrum_shape",
            axis_values="spectrum_axis",
            units="counts",
        ),
        "image": ArrayGetter(axes=("row", "column"), shape="image_shape", units="counts"),
    }

    # Read-only getters recorded by setup capture at scan start and end.
    SNAPSHOT_GETTERS = ("temperature", "exposure_time", "center_wavelength")

    TEMPERATURE_RANGE_C = (-120.0, 30.0)
    EXPOSURE_RANGE_S = (1e-6, 3600.0)
    CENTER_WAVELENGTH_RANGE_NM = (1.0, 30000.0)
    SNAP_TIMEOUT_MARGIN_S = 10.0
    # Shutting the SDK down below this leaves the sensor to warm up unguided.
    SAFE_SHUTDOWN_TEMPERATURE_C = -20.0
    # How long a UI-thread shape/axis query waits for the SDK lock.
    QUERY_LOCK_TIMEOUT_S = 0.5

    sig_acquisition_mode = QtCore.pyqtSignal(object)
    sig_exposure_time = QtCore.pyqtSignal(object)
    sig_temperature = QtCore.pyqtSignal(object)
    sig_read_mode = QtCore.pyqtSignal(object)
    sig_detector_size = QtCore.pyqtSignal(object)
    sig_device_info = QtCore.pyqtSignal(object)

    sig_image_acquired = QtCore.pyqtSignal(object)
    sig_acquisition_started = QtCore.pyqtSignal(object)
    sig_acquisition_stopped = QtCore.pyqtSignal(object)
    sig_frame_ready = QtCore.pyqtSignal(object)
    sig_acquisition_timings = QtCore.pyqtSignal(object)
    sig_cooler = QtCore.pyqtSignal(object)
    sig_accum_frame_num = QtCore.pyqtSignal(object)
    sig_accum_cycle_time = QtCore.pyqtSignal(object)

    sig_camera_count = QtCore.pyqtSignal(object)
    sig_spectrometer_count = QtCore.pyqtSignal(object)
    sig_spectrometer_info = QtCore.pyqtSignal(object)

    sig_connected = QtCore.pyqtSignal(object)
    sig_spectrometer_connected = QtCore.pyqtSignal(object)
    # (level, message) for the device log.
    sig_log = QtCore.pyqtSignal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._sdk_lock = threading.RLock()
        self._connect_guard = threading.Lock()

        self.job = ""
        self.scan_admission_closed = False

        self.setpoint_camera_index = 0
        self.setpoint_spectrometer_index = 0
        self.setpoint_acquisition_mode = "single"
        self.setpoint_exposure_time = 0.1
        self.setpoint_temperature = -80
        self.setpoint_read_mode = "fvb"
        self.setpoint_cooler = False

        self.setpoint_accum_num_frames = 10
        self.setpoint_accum_cycle_time = 0.0
        self.setpoint_cont_cycle_time = 0.0
        self.setpoint_kinetic_num_cycle = 10
        self.setpoint_kinetic_cycle_time = 0.0
        self.setpoint_kinetic_num_acc = 1
        self.setpoint_kinetic_cycle_time_acc = 0.0
        self.setpoint_kinetic_num_prescan = 0

        self.connected = False
        self.spectrometer_connected = False
        self.acquiring = False
        self._abort_requested = False
        self._last_monitor_error = None

        self.device_info: Any = None
        self.spectrometer_info: Any = None
        self.last_spectrum = None
        self.hardware: AndorCameraHardware | None = None
        self.spectrometer_hardware: ShamrockSpectrogramHardware | None = None

        self._data_dimensions: tuple[int, int] | None = None
        self._calibration_nm: tuple[float, ...] | None = None
        self._calibration_valid = False

    # ------------------------------------------------------------------ log
    def _log(self, level: str, message: str):
        self.sig_log.emit(str(level), str(message))

    # ------------------------------------------------------------ helpers
    def _camera(self) -> AndorCameraHardware:
        if self.hardware is None:
            raise RuntimeError("Andor camera is not connected")
        return self.hardware

    def _spectrograph(self) -> ShamrockSpectrogramHardware:
        if self.spectrometer_hardware is None:
            raise RuntimeError("Shamrock spectrograph is not connected")
        return self.spectrometer_hardware

    def _invalidate_calibration(self):
        self._calibration_valid = False
        self._calibration_nm = None

    def _refresh_dimensions(self):
        with self._sdk_lock:
            rows, columns = (int(n) for n in self._camera().get_data_dimensions())
        if rows < 1 or columns < 1:
            raise RuntimeError(f"Andor camera reported data dimensions {rows} x {columns}")
        if self._data_dimensions != (rows, columns):
            self._data_dimensions = (rows, columns)
            self._invalidate_calibration()
        return self._data_dimensions

    # --------------------------------------------------------- connection
    def query_camera_count(self):
        try:
            count = andor_hardware.camera_count()
        except Exception as exc:  # noqa: BLE001
            count = 0
            self._log("WARNING", f"Could not query Andor camera count: {exc}")
        self.sig_camera_count.emit(count)
        return count

    def query_spectrometer_count(self):
        try:
            count = andor_hardware.spectrograph_count()
        except Exception as exc:  # noqa: BLE001
            count = 0
            self._log("WARNING", f"Could not query Shamrock spectrograph count: {exc}")
        self.sig_spectrometer_count.emit(count)
        return count

    def refresh_device_counts(self):
        with self._sdk_lock:
            return self.query_camera_count(), self.query_spectrometer_count()

    def connect_camera(self, camera_index: int | None = None) -> bool:
        if camera_index is not None:
            self.setpoint_camera_index = int(camera_index)
        with self._sdk_lock:
            if self.connected:
                return True
            self.query_camera_count()
            self._close_camera_hardware()
            self.device_info = None
            try:
                self.hardware = AndorCameraHardware(self.setpoint_camera_index)
                self.device_info = self.hardware.get_device_info()
                self._refresh_dimensions()
                self.connected = True
            except Exception as exc:  # noqa: BLE001
                self._close_camera_hardware()
                self.connected = False
                self.sig_connected.emit("camera connection failed")
                self._log("ERROR", f"Camera {self.setpoint_camera_index} connection failed: {exc}")
                return False
        self.sig_device_info.emit(self.device_info)
        self.sig_detector_size.emit(self._data_dimensions)
        self.sig_connected.emit(f"connected to camera {self.setpoint_camera_index}")
        self._log("INFO", f"Camera {self.setpoint_camera_index} connected")
        return True

    def connect_spectrometer(self, spectrometer_index: int | None = None) -> bool:
        if spectrometer_index is not None:
            self.setpoint_spectrometer_index = int(spectrometer_index)
        with self._sdk_lock:
            if self.spectrometer_connected:
                return True
            self.query_spectrometer_count()
            self._close_spectrometer_hardware()
            self.spectrometer_info = None
            try:
                self.spectrometer_hardware = ShamrockSpectrogramHardware(
                    idx=self.setpoint_spectrometer_index
                )
                self.spectrometer_info = self.query_spectrometer_device_info()
                self.spectrometer_connected = True
                self._invalidate_calibration()
            except Exception as exc:  # noqa: BLE001
                self._close_spectrometer_hardware()
                self.spectrometer_connected = False
                self.sig_spectrometer_connected.emit("spectrometer connection failed")
                self._log(
                    "ERROR",
                    f"Spectrograph {self.setpoint_spectrometer_index} connection failed: {exc}",
                )
                return False
        self.sig_spectrometer_connected.emit(
            f"connected to spectrometer {self.setpoint_spectrometer_index}"
        )
        self._log("INFO", f"Spectrograph {self.setpoint_spectrometer_index} connected")
        return True

    def connect_devices(self, camera_index: int, spectrometer_index: int | None) -> bool:
        """Connect the camera (required) and the spectrograph (optional)."""
        if not self.connect_camera(camera_index):
            return False
        if spectrometer_index is not None and not self.connect_spectrometer(spectrometer_index):
            self._log("WARNING", "Camera connected without the spectrograph; spectra use pixel index.")
        return True

    def connect_with_timeout(
        self, camera_index: int, spectrometer_index: int | None, timeout_ms: int
    ) -> bool:
        """Bounded connect for the device manager; literal True on success.

        The vendor call cannot be killed, so on timeout the attempt is
        abandoned: if it later succeeds it disconnects again.
        """
        if self.isRunning():
            self._log("WARNING", "Connect refused: an Andor panel job is still running.")
            return False
        result = {"ok": False}
        abandoned = threading.Event()
        done = threading.Event()

        def work():
            try:
                ok = self.connect_devices(camera_index, spectrometer_index)
            except Exception as exc:  # noqa: BLE001
                ok = False
                self._log("ERROR", f"Connect failed: {exc}")
            with self._connect_guard:
                if ok and abandoned.is_set():
                    self.disconnect_all()
                    ok = False
                result["ok"] = ok
                done.set()

        thread = threading.Thread(target=work, name="andor-connect", daemon=True)
        thread.start()
        done.wait(max(int(timeout_ms), 1) / 1000.0)
        with self._connect_guard:
            if not done.is_set():
                abandoned.set()
                self._log("ERROR", f"Connect did not finish within {int(timeout_ms)} ms.")
                return False
        return result["ok"] is True

    def _close_camera_hardware(self):
        if self.hardware is None:
            return
        try:
            if self.acquiring:
                self.hardware.stop_acquisition()
                self.acquiring = False
            self.hardware.disconnect()
        except Exception as exc:  # noqa: BLE001
            self._log("WARNING", f"Camera close warning: {exc}")
        finally:
            self.hardware = None
            self._data_dimensions = None
            self._invalidate_calibration()

    def _close_spectrometer_hardware(self):
        if self.spectrometer_hardware is None:
            return
        try:
            self.spectrometer_hardware.disconnect()
        except Exception as exc:  # noqa: BLE001
            self._log("WARNING", f"Spectrograph close warning: {exc}")
        finally:
            self.spectrometer_hardware = None
            self._invalidate_calibration()

    def disconnect_camera(self):
        with self._sdk_lock:
            if self.hardware is not None:
                try:
                    temperature = float(self.hardware.temperature(read=True))
                except Exception:  # noqa: BLE001
                    temperature = None
                if temperature is not None and temperature < self.SAFE_SHUTDOWN_TEMPERATURE_C:
                    self._log(
                        "WARNING",
                        f"Camera disconnected at {temperature:.1f} C; Andor recommends "
                        f"warming above {self.SAFE_SHUTDOWN_TEMPERATURE_C:.0f} C first.",
                    )
            was_connected = self.connected
            self._close_camera_hardware()
            self.connected = False
            self.device_info = None
        if was_connected:
            self.sig_connected.emit("camera disconnected")
            self._log("INFO", "Camera disconnected")

    def disconnect_spectrometer(self):
        with self._sdk_lock:
            was_connected = self.spectrometer_connected
            self._close_spectrometer_hardware()
            self.spectrometer_connected = False
            self.spectrometer_info = None
        if was_connected:
            self.sig_spectrometer_connected.emit("spectrometer disconnected")
            self._log("INFO", "Spectrograph disconnected")

    def disconnect_all(self):
        self.disconnect_camera()
        self.disconnect_spectrometer()
        return True

    def disconnect(self):
        return self.disconnect_all()

    # -------------------------------------------------------- scan getters
    def get_temperature(self):
        with self._sdk_lock:
            value = float(self._camera().temperature(read=True))
        self.sig_temperature.emit(value)
        return value

    def get_exposure_time(self):
        with self._sdk_lock:
            value = float(self._camera().exposure_time(read=True))
        self.sig_exposure_time.emit(value)
        return value

    def get_center_wavelength(self):
        """Centre wavelength in nm."""
        with self._sdk_lock:
            metres = float(self._spectrograph().center_wavelength(read=True))
        return metres * 1e9

    def get_spectrum(self):
        """One exposure as counts per pixel column (1-D, length = spectrum_shape)."""
        image = self._snap()
        spectrum = self._to_spectrum(image)
        expected = self.spectrum_shape()
        if spectrum.shape != expected:
            raise RuntimeError(
                f"Andor spectrum has {spectrum.shape}, expected {expected}; "
                "did the read mode change during the scan?"
            )
        self.last_spectrum = spectrum
        return spectrum

    def get_image(self):
        """One exposure as a 2-D frame (rows x columns of the read mode)."""
        frame = np.asarray(self._snap(), dtype=float)
        if frame.ndim == 1:
            frame = frame.reshape(1, -1)
        expected = self.image_shape()
        if frame.shape != expected:
            raise RuntimeError(
                f"Andor frame has {frame.shape}, expected {expected}; "
                "did the read mode change during the scan?"
            )
        return frame

    @staticmethod
    def _to_spectrum(image) -> np.ndarray:
        """FVB / single track give one row; image and tracks are summed over rows."""
        array = np.asarray(image, dtype=float)
        if array.ndim == 1:
            return array
        if array.ndim == 2:
            return array.sum(axis=0)
        raise RuntimeError(f"Andor returned a {array.ndim}-D image")

    # ------------------------------------------- array getter shape / axis
    def spectrum_shape(self) -> tuple[int]:
        if self._data_dimensions is None:
            raise RuntimeError("Andor camera is not connected")
        return (int(self._data_dimensions[1]),)

    def image_shape(self) -> tuple[int, int]:
        if self._data_dimensions is None:
            raise RuntimeError("Andor camera is not connected")
        return (int(self._data_dimensions[0]), int(self._data_dimensions[1]))

    def spectrum_axis(self):
        """Wavelength (nm) of each pixel column, or ``None`` (pixel index)."""
        if self._calibration_valid:
            return self._calibration_nm
        if self.spectrometer_hardware is None or self.hardware is None:
            return None
        if not self._sdk_lock.acquire(timeout=self.QUERY_LOCK_TIMEOUT_S):
            return self._calibration_nm
        try:
            self._calibration_nm = self._read_calibration_nm()
            self._calibration_valid = True
        except Exception as exc:  # noqa: BLE001
            self._calibration_nm = None
            self._calibration_valid = True
            self._log("WARNING", f"Using the pixel axis: wavelength calibration failed ({exc})")
        finally:
            self._sdk_lock.release()
        return self._calibration_nm

    def _read_calibration_nm(self):
        spectrograph = self._spectrograph()
        spectrograph.setup_pixels_from_camera(self._camera())
        calibration = np.asarray(spectrograph.get_calibration(), dtype=float).ravel()
        columns = self.spectrum_shape()[0]
        if calibration.size != columns or not np.all(np.isfinite(calibration)):
            raise RuntimeError(
                f"calibration has {calibration.size} points for {columns} pixel columns"
            )
        if np.nanmax(np.abs(calibration)) < 1e-3:
            calibration = calibration * 1e9  # pylablib returns metres
        return tuple(float(v) for v in calibration)

    # ------------------------------------------------------------- setters
    def set_temperature(self, value):
        """Cooler target in degrees C (does not wait for the sensor to settle)."""
        target = _finite(value, "Andor temperature")
        low, high = self.TEMPERATURE_RANGE_C
        if not low <= target <= high:
            raise ValueError(f"Andor temperature {target} C is outside {low}..{high} C")
        with self._sdk_lock:
            self._camera().temperature(int(round(target)), write=True)
        self.setpoint_temperature = int(round(target))
        self.sig_temperature.emit(self.setpoint_temperature)
        return self.setpoint_temperature

    def set_exposure_time(self, value):
        """Exposure time in seconds."""
        exposure = _finite(value, "Andor exposure time")
        low, high = self.EXPOSURE_RANGE_S
        if not low <= exposure <= high:
            raise ValueError(f"Andor exposure time {exposure} s is outside {low}..{high} s")
        with self._sdk_lock:
            self._camera().exposure_time(exposure, write=True)
        self.setpoint_exposure_time = exposure
        self.sig_exposure_time.emit(exposure)
        return exposure

    def set_center_wavelength(self, value):
        """Spectrograph centre wavelength in nm."""
        nm = _finite(value, "Shamrock centre wavelength")
        low, high = self.CENTER_WAVELENGTH_RANGE_NM
        if not low <= nm <= high:
            raise ValueError(f"Shamrock centre wavelength {nm} nm is outside {low}..{high} nm")
        with self._sdk_lock:
            self._spectrograph().center_wavelength(nm * 1e-9, write=True)
            self._invalidate_calibration()
        return nm

    # ------------------------------------------------------------- snap
    def _snap_timeout(self) -> float:
        camera = self._camera()
        values = []
        try:
            timings = camera.get_acquisition_timings()
            for item in np.ravel(np.asarray(timings, dtype=float)):
                if math.isfinite(item) and item > 0:
                    values.append(float(item))
        except Exception:  # noqa: BLE001 - fall back to the exposure
            pass
        if not values:
            try:
                values.append(float(camera.exposure_time(read=True)))
            except Exception:  # noqa: BLE001
                values.append(float(self.setpoint_exposure_time))
        frames = 1
        if self.setpoint_acquisition_mode in ("accum", "accumulate"):
            frames = max(1, int(self.setpoint_accum_num_frames))
        return self.SNAP_TIMEOUT_MARGIN_S + max(values) * frames

    def _snap(self):
        with self._sdk_lock:
            camera = self._camera()
            self._abort_requested = False
            timeout = self._snap_timeout()
            try:
                return camera.snap_image(timeout)
            except Exception as exc:
                if self._abort_requested:
                    raise RuntimeError("Andor exposure aborted by force stop") from exc
                raise

    def abort_exposure(self) -> bool:
        """Force stop: abort the running exposure only (no lock: it may be held)."""
        self._abort_requested = True
        hardware = self.hardware
        if hardware is None:
            return False
        try:
            hardware.abort_acquisition()
        except Exception as exc:  # noqa: BLE001
            self._log("WARNING", f"Abort acquisition failed: {exc}")
            return False
        self.acquiring = False
        return True

    # ------------------------------------------------------- panel queries
    def query_device_info(self):
        with self._sdk_lock:
            value = self._camera().get_device_info()
        self.sig_device_info.emit(value)
        return value

    def query_spectrometer_device_info(self):
        spectrograph = self._spectrograph()
        info = {
            "device_info": spectrograph.get_device_info(),
            "optical_parameters": self._read_optional(spectrograph.get_optical_parameters),
            "status": self._read_optional(spectrograph.get_status),
        }
        self.sig_spectrometer_info.emit(info)
        return info

    @staticmethod
    def _read_optional(reader):
        try:
            return reader()
        except Exception:  # noqa: BLE001
            return None

    def query_acquisition_mode(self):
        with self._sdk_lock:
            value = self._camera().acquisition_mode(read=True)
        self.sig_acquisition_mode.emit(value)
        return value

    def query_read_mode(self):
        with self._sdk_lock:
            value = self._camera().read_mode(read=True)
        self.sig_read_mode.emit(value)
        return value

    def query_detector_size(self):
        with self._sdk_lock:
            value = self._camera().get_detector_size()
        self.sig_detector_size.emit(value)
        return value

    def query_acquisition_timings(self):
        with self._sdk_lock:
            value = self._camera().get_acquisition_timings()
        self.sig_acquisition_timings.emit(value)
        return value

    def query_accum_settings(self):
        with self._sdk_lock:
            frame_num, cycle_time = self._camera().setup_accumulation_mode(read=True)
        self.sig_accum_frame_num.emit(frame_num)
        self.sig_accum_cycle_time.emit(cycle_time)
        return frame_num, cycle_time

    def query_all(self):
        with self._sdk_lock:
            self.query_acquisition_mode()
            self.get_exposure_time()
            self.get_temperature()
            self.query_read_mode()
            self.query_acquisition_timings()
            self.query_accum_settings()

    # ---------------------------------------------------------- panel jobs
    def apply_temperature_setpoint(self):
        self.set_temperature(self.setpoint_temperature)
        self._log("INFO", f"Temperature target set to {self.setpoint_temperature} C")

    def setup_cooler(self):
        with self._sdk_lock:
            self._camera().cooler(self.setpoint_cooler, write=True)
        self.sig_cooler.emit(self.setpoint_cooler)
        self._log("INFO", f"Cooler {'on' if self.setpoint_cooler else 'off'}")

    def setup_exposure_time(self):
        self.set_exposure_time(self.setpoint_exposure_time)

    def setup_acquisition_mode(self):
        with self._sdk_lock:
            self._camera().acquisition_mode(self.setpoint_acquisition_mode, write=True)
        self.sig_acquisition_mode.emit(self.setpoint_acquisition_mode)
        self._log("INFO", f"Acquisition mode set to {self.setpoint_acquisition_mode}")

    def setup_read_mode(self):
        with self._sdk_lock:
            self._camera().read_mode(self.setpoint_read_mode, write=True)
            dimensions = self._refresh_dimensions()
        self.sig_read_mode.emit(self.setpoint_read_mode)
        self.sig_detector_size.emit(dimensions)
        self._log(
            "INFO",
            f"Read mode set to {self.setpoint_read_mode} ({dimensions[0]} x {dimensions[1]})",
        )

    def setup_accumulation_mode(self):
        with self._sdk_lock:
            self._camera().setup_accumulation_mode(
                int(self.setpoint_accum_num_frames),
                float(self.setpoint_accum_cycle_time),
                write=True,
            )
        self._log(
            "INFO",
            f"Accumulation: {int(self.setpoint_accum_num_frames)} frames, "
            f"cycle time {self.setpoint_accum_cycle_time} s",
        )

    def start_acquisition(self):
        with self._sdk_lock:
            self._camera().start_acquisition()
        self.acquiring = True
        self.sig_acquisition_started.emit("acquisition started")

    def stop_acquisition(self):
        with self._sdk_lock:
            self._camera().stop_acquisition()
        self.acquiring = False
        self.sig_acquisition_stopped.emit("acquisition stopped")

    def snap_image(self):
        image = self._snap()
        self.sig_image_acquired.emit(np.asarray(image))
        return image

    def monitor_poll(self):
        """Monitor job: log a failure once, not every poll."""
        try:
            self.query_all()
            self._last_monitor_error = None
        except Exception as exc:  # noqa: BLE001
            message = f"Monitor read failed: {exc}"
            if message != self._last_monitor_error:
                self._log("WARNING", message)
            self._last_monitor_error = message

    def connect_camera_job(self):
        self.connect_camera()

    def connect_spectrometer_job(self):
        self.connect_spectrometer()

    PANEL_JOBS = frozenset(
        {
            "connect_camera_job",
            "connect_spectrometer_job",
            "apply_temperature_setpoint",
            "setup_cooler",
            "setup_exposure_time",
            "setup_acquisition_mode",
            "setup_read_mode",
            "setup_accumulation_mode",
            "start_acquisition",
            "stop_acquisition",
            "snap_image",
            "monitor_poll",
        }
    )

    def run(self):
        current_job = self.job
        try:
            if self.scan_admission_closed or not current_job:
                return
            if current_job not in self.PANEL_JOBS:
                self._log("ERROR", f"Unknown Andor job {current_job!r}")
                return
            getattr(self, current_job)()
        except Exception as exc:  # noqa: BLE001
            self._log("ERROR", f"{current_job} failed: {exc}")
        finally:
            self.job = ""

    # ------------------------------------------------- scan lifecycle
    def prepare_scan(self, timeout_ms: int) -> bool:
        """Close panel-job admission and wait (bounded) for a running job."""
        self.scan_admission_closed = True
        return not self.isRunning() or self.wait(int(timeout_ms))

    def resume_scan(self) -> bool:
        self.scan_admission_closed = False
        return True

    def lifecycle_busy(self) -> bool:
        return self.isRunning()

    def shutdown(self, timeout_ms: int = 10_000) -> bool:
        self.scan_admission_closed = True
        self.abort_exposure()
        finished = not self.isRunning() or self.wait(int(timeout_ms))
        self.disconnect_all()
        return bool(finished)
