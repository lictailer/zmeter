"""Qt worker and scan-facing facade for configurable autofocus."""
from __future__ import annotations

import threading
from dataclasses import asdict

import numpy as np

from PyQt6 import QtCore
from core.measurement_records import RunRecord, new_run_key

from .autofocus_engine import AutofocusSettings, FocusStopped, finite, run_focus
from .autofocus_hardware import RouterIO, SOURCE_FACTORIES, Z_FACTORIES


class AutofocusLogic(QtCore.QThread):
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)
    sig_connected = QtCore.pyqtSignal(bool)
    sig_position = QtCore.pyqtSignal(object)
    sig_sample = QtCore.pyqtSignal(object)
    sig_result = QtCore.pyqtSignal(object)
    sig_busy = QtCore.pyqtSignal(bool)

    def __init__(self, *, z_factories=None, source_factories=None):
        super().__init__()
        self.settings = AutofocusSettings()
        self.z_factories = dict(Z_FACTORIES if z_factories is None else z_factories)
        self.source_factories = dict(SOURCE_FACTORIES if source_factories is None else source_factories)
        self.router = None
        self.device_label = "auto_focus"
        self.axis = None
        self.result = None
        self.history = []
        self.run_settings = None
        self.last_outcome = "idle"
        self.last_error = None
        self.last_output_directory = None
        self.last_run_key = None
        self.stop_event = threading.Event()
        self._operation_lock = threading.Lock()
        self._job_lock = threading.Lock()
        self._job = None

    @property
    def connected(self) -> bool:
        return self.axis is not None and self.axis.connected

    def is_busy(self) -> bool:
        return self.isRunning() or self._operation_lock.locked()

    def configure_command_router(self, command_router, source_device=None) -> None:
        if self.is_busy():
            raise RuntimeError("Cannot replace the router during an autofocus operation")
        self.router = command_router
        if source_device:
            self.device_label = source_device

    def detach_command_router(self) -> None:
        self.configure_command_router(None)

    def apply_settings(self, settings: AutofocusSettings) -> None:
        settings.validate()
        if self.is_busy():
            raise RuntimeError("Wait for the current autofocus operation before changing settings")
        if self.connected and settings.z != self.settings.z:
            raise RuntimeError("Disconnect Z before changing its driver, units, channels or limits")
        if settings.z.backend not in self.z_factories or settings.source.mode not in self.source_factories:
            raise ValueError("Unknown Z or acquisition adapter")
        self.settings = settings

    def connect_z(self) -> bool:
        with self._operation_lock:
            if self.connected:
                return True
            self.settings.z.validate()
            factory = self.z_factories[self.settings.z.backend][1]
            axis = factory(self.settings.z, RouterIO(self.router, self.device_label))
            try:
                axis.connect(self.stop_event)
                position = axis.position()
                self.settings.z.validate_target(position)
            except Exception:
                axis.disconnect()
                raise
            self.axis = axis
        self.sig_connected.emit(True)
        self.sig_position.emit(position)
        self.sig_status.emit(f"Z selected; position is in {self.settings.z.unit}")
        return True

    def disconnect(self) -> None:
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("Stop autofocus and wait for its current move before disconnecting")
        try:
            if self.axis is not None:
                self.axis.disconnect()
                self.axis = None
        finally:
            self._operation_lock.release()
        self.sig_connected.emit(False)
        self.sig_position.emit(None)

    def get_z(self):
        with self._operation_lock:
            self._require_connected()
            position = self.axis.position()
        self.sig_position.emit(position)
        return position

    def get_focus_score(self):
        if self.result is not None:
            return self.result.best_score
        if not self.history:
            raise RuntimeError("No focus measurement has been acquired")
        return self.history[-1].score

    def get_run_key(self):
        """Latest autofocus attempt's fixed local timestamp; NaN before any run."""
        return self.last_run_key if self.last_run_key is not None else float("nan")

    def set_focus(self, trigger):
        """Every finite numeric trigger runs autofocus; its magnitude is ignored."""
        finite(trigger, "Autofocus trigger")
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("An autofocus operation is already active")
        self.sig_busy.emit(True)
        record = None
        try:
            self._require_connected()
            self.run_settings = self.settings
            self.last_outcome = "running"
            self.last_error = None
            self.result = None
            self.history = []
            self.last_output_directory = None
            self.last_run_key = new_run_key()
            if self.run_settings.output.enabled:
                record = RunRecord(self.run_settings.output.directory, "autofocus", run_key=self.last_run_key)
                self.last_output_directory = str(record.path)
                record.json("run.json", {"status": "running", "settings": self.run_settings.to_dict()})
            self.sig_sample.emit(None)
            io = RouterIO(self.router, self.device_label)
            source = self.source_factories[self.settings.source.mode][1](self.settings.source, io)
            self.sig_status.emit("Autofocus running")

            def sample_ready(sample, data):
                self.sig_position.emit(sample.position)
                self.sig_sample.emit((sample, data))
                if record is not None and self.run_settings.output.save_frames and np.asarray(data).ndim >= 2:
                    name = f"frame-{len(self.history):04d}"
                    record.array(name + ".npy", data)
                    record.map(name + ".png", data, title=f"Focus image at Z={sample.position:g} {self.run_settings.z.unit}")

            self.result = run_focus(self.axis, source, self.run_settings, self.stop_event,
                                    sample_ready, self.history)
            self.last_outcome = self.result.status
            if record is not None:
                self._save_run_record(record)
            self.sig_result.emit(self.result)
            self.sig_position.emit(self.result.final_position)
            fit = self.result.gaussian_fit
            fit_text = (f"; Gaussian center {fit.center:g}, sigma {fit.sigma:g}, R² {fit.r_squared:.4g}"
                        if fit is not None else "")
            if self.result.fit_error:
                fit_text += "; " + self.result.fit_error
            self.sig_status.emit(
                f"{self.result.status}: measured best Z {self.result.best_position:g}, "
                f"score {self.result.best_score:g}" + fit_text + "; "
                + ("selected position applied" if self.result.applied else "final focus-position move not applied")
                + (f"; saved: {self.last_output_directory}" if record is not None else "")
            )
            return self.result.selected_position if self.result.selected_position is not None else self.result.best_position
        except Exception as exc:
            self.last_outcome = "stopped" if isinstance(exc, FocusStopped) else "error"
            self.last_error = str(exc)
            if record is not None:
                try:
                    self._save_run_record(record)
                except Exception as save_error:
                    self.last_error += f"; saving also failed: {save_error}"
                    self.sig_error.emit(self.last_error)
            last_position = getattr(self.axis, "last_position", None)
            if last_position is not None:
                self.sig_position.emit(last_position)
            raise
        finally:
            self._operation_lock.release()
            self.sig_busy.emit(False)

    def _save_run_record(self, record):
        record.json("run.json", {
            "schema_version": 2, "run_key": self.last_run_key, "settings": self.run_settings.to_dict(),
            "outcome": self.last_outcome, "error": self.last_error,
            "result": self.result.to_dict() if self.result else None,
            "samples": [asdict(sample) for sample in self.history],
        })
        record.curve(self.history, self.run_settings.z.unit,
                     self.result.gaussian_fit if self.result else None)

    def submit(self, operation, *args) -> bool:
        with self._job_lock:
            if self.isRunning() or self._job is not None or self._operation_lock.locked():
                self.sig_error.emit("Autofocus is busy")
                return False
            self.stop_event.clear()  # A new explicit operator operation.
            self._job = (operation, args)
            self.sig_busy.emit(True)
            self.start()
            return True

    def run(self) -> None:
        try:
            operation, args = self._job
            operation(*args)
        except FocusStopped as exc:
            self.sig_status.emit(str(exc))
        except Exception as exc:
            self.sig_error.emit(str(exc))
        finally:
            with self._job_lock:
                self._job = None
            self.sig_busy.emit(False)

    def force_stop(self) -> bool:
        self.stop_event.set()
        self.sig_status.emit("Stop requested; the current hardware command may still be completing")
        return True

    def stop_scan(self) -> None:
        # No background monitor; refuse only a genuinely active autofocus job.
        if self.is_busy():
            raise RuntimeError("Autofocus is still active; stop it or let it finish before starting a scan")
        self.stop_event.clear()

    def start_scan(self) -> None:
        self.stop_event.clear()

    def terminate_dev(self, wait_ms=3000) -> bool:
        self.stop_event.set()
        if self.isRunning() and not self.wait(wait_ms):
            return False
        if not self._operation_lock.acquire(timeout=wait_ms / 1000):
            return False
        try:
            if self.axis is not None:
                self.axis.disconnect()
                self.axis = None
        finally:
            self._operation_lock.release()
        self.sig_connected.emit(False)
        return True

    def find_catalog_references(self, *, removed_setters=(), removed_getters=(), removed_device_labels=()):
        s = self.settings
        refs = []
        if s.z.backend == "routed":
            refs.extend(((s.z.setter, removed_setters), (s.z.getter, removed_getters)))
        if s.source.mode != "camera":
            refs.append((s.source.signal, removed_getters))
        if s.source.mode == "raster" or (s.source.mode == "point" and s.source.position_xy):
            refs.extend(((s.source.x, removed_setters), (s.source.y, removed_setters)))
        return tuple(f"autofocus uses {ref.device}/{ref.channel}" for ref, removed in refs
                     if ref.device in removed_device_labels or f"{ref.device}_{ref.channel}" in removed)

    def _require_connected(self) -> None:
        if not self.connected:
            raise RuntimeError("Select the Z position channels first; connect the actuator in its own panel")
