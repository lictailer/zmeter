"""Worker, scan trigger and explicit persistence for reference-map positioning."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import threading

import numpy as np
from PyQt6 import QtCore

from core.measurement_io import RouterIO, finite
from core.measurement_records import RunRecord, new_run_key
from .position_engine import PositionSettings, PositionStopped, ReferenceMap, checkpoint, register_maps
from .position_hardware import MapReader


class AutoPositionLogic(QtCore.QThread):
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)
    sig_busy = QtCore.pyqtSignal(bool)
    sig_map = QtCore.pyqtSignal(object)
    sig_reference = QtCore.pyqtSignal(object)
    sig_result = QtCore.pyqtSignal(object)
    sig_settings = QtCore.pyqtSignal(object)

    def __init__(self, reader_factory=MapReader):
        super().__init__()
        self.settings = PositionSettings()
        self.reader_factory = reader_factory
        self.router, self.device_label = None, "auto_position"
        self.reference, self.result, self.reader = None, None, None
        self.applied = False
        self.last_outcome, self.last_error, self.last_output_directory = "idle", None, None
        self.last_run_key = None
        self.stop_event = threading.Event()
        self._operation_lock, self._job_lock = threading.Lock(), threading.Lock()
        self._job = None

    @property
    def connected(self):
        return self.reference is not None and self.router is not None

    def is_busy(self):
        return self.isRunning() or self._operation_lock.locked()

    def apply_settings(self, settings):
        settings.validate()
        if self.is_busy():
            raise RuntimeError("Wait for the active auto-position operation")
        self.settings = settings

    def configure_command_router(self, router, source_device=None):
        if self.is_busy():
            raise RuntimeError("Cannot change routing during auto-position")
        self.router = router
        if source_device:
            self.device_label = source_device

    def detach_command_router(self):
        self.configure_command_router(None)

    def check_ready(self):
        if self.reference is None:
            raise RuntimeError("Acquire or load a reference map first")
        if self.router is None:
            raise RuntimeError("Auto-position needs ZMeter's command router")
        self.settings.validate()
        if self.settings.map != self.reference.geometry or tuple(self.settings.point) != tuple(self.reference.point):
            raise ValueError("Map geometry/channels or reference point changed: acquire a new reference, or explicitly save the edited point")
        return True

    def _persist(self, record, kind, status, error=None):
        image = self.reader.image if self.reader is not None else None
        data = {
            "schema_version": 1, "kind": kind, "status": status, "error": error,
            "settings": self.settings.to_dict(),
            "reference_id": self.reference.reference_id if self.reference else None,
            "reference_point": list(self.reference.point) if self.reference else None,
            "registration": asdict(self.result) if self.result else None,
            "point_commands_completed": self.applied,
            "last_completed_output_commands": self.reader.last_commands if self.reader else {},
            "completed_pixels": self.reader.completed_points if self.reader else 0,
            "image": [[float(v) if np.isfinite(v) else None for v in row] for row in image] if image is not None else None,
        }
        record.json("run.json", data)
        if image is not None:
            point = self.result.point if self.result else self.settings.point
            g = self.settings.map
            record.map("map.png", image, g.xs, g.ys, point,
                       title=f"{kind}: {status}; point {'commanded' if self.applied else 'not applied'}",
                       units=(f"X ({g.x_unit})", f"Y ({g.y_unit})"))

    def _run_map(self, kind):
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("An auto-position operation is already active")
        record = None
        self.sig_busy.emit(True)
        try:
            self.settings.validate()
            if kind == "position":
                self.check_ready()
            checkpoint(self.stop_event)
            self.result, self.reader, self.applied = None, None, False
            self.last_outcome, self.last_error = "running", None
            self.last_output_directory = None
            if kind == "position":
                self.last_run_key = new_run_key()
            # Reserve/write before acquisition: invalid or unwritable paths must
            # fail before any scan output is changed.
            record = RunRecord(self.settings.directory, "reference" if kind == "reference" else "auto-position",
                               run_key=self.last_run_key if kind == "position" else None)
            self.last_output_directory = str(record.path)
            self.reader = self.reader_factory(self.settings.map, RouterIO(self.router, self.device_label))
            self.reader.prepare(self.stop_event)
            self._persist(record, kind, "scanning")
            image = self.reader.acquire(self.stop_event, lambda data, row: self.sig_map.emit((data, row)))
            checkpoint(self.stop_event)
            if kind == "reference":
                reference = ReferenceMap(self.settings.map, tuple(self.settings.point), image.copy())
                reference.validate()
                reference.image.setflags(write=False)
                record.json("reference.json", reference.to_dict())
                # The button explicitly promises to return to the selected POI.
                self.reader.move(reference.point, self.stop_event)
                self.applied = True
                self.reference = reference
                self.sig_reference.emit(reference)
            else:
                self.result = register_maps(self.reference, image, self.settings.registration, self.stop_event)
                self._persist(record, kind, "ready_to_move")
                checkpoint(self.stop_event)
                self.reader.move(self.result.point, self.stop_event)
                self.applied = True
                self.sig_result.emit(self.result)
                def comparison(figure):
                    for ax, values, point, title in zip(figure.subplots(1, 2),
                            (self.reference.image, image), (self.reference.point, self.result.point),
                            ("Reference + original point", "New map + corrected point")):
                        g = self.settings.map
                        ax.pcolormesh(g.xs, g.ys, values, shading="nearest")
                        ax.plot(*point, "r+", markersize=10)
                        ax.set(title=title, xlabel=f"X ({g.x_unit})", ylabel=f"Y ({g.y_unit})")
                record.figure("comparison.png", comparison)
            self.last_outcome = "complete"
            self._persist(record, kind, "complete")
            self.sig_status.emit(f"{'Reference acquired' if kind == 'reference' else 'Auto-position done'}; saved: {record.path}")
            return 1.0
        except Exception as exc:
            self.last_outcome = "stopped" if isinstance(exc, PositionStopped) else "error"
            self.last_error = str(exc)
            if record is not None:
                try:
                    self._persist(record, kind, self.last_outcome, self.last_error)
                except Exception as save_error:
                    self.last_error += f"; saving also failed: {save_error}"
                    self.sig_error.emit(self.last_error)
            raise
        finally:
            self._operation_lock.release()
            self.sig_busy.emit(False)

    def acquire_reference(self):
        return self._run_map("reference")

    def set_position(self, trigger):
        """One finite numeric trigger runs map registration and final positioning."""
        finite(trigger, "Auto-position trigger")
        return self._run_map("position")

    def _value(self, name):
        if self.result is None or not self.applied or self.last_outcome != "complete":
            raise RuntimeError("No successfully applied auto-position result")
        return getattr(self.result, name)

    def get_x(self): return self._value("point")[0]
    def get_y(self): return self._value("point")[1]
    def get_shift_x(self): return self._value("shift_x")
    def get_shift_y(self): return self._value("shift_y")
    def get_correlation(self): return self._value("correlation")

    def get_run_key(self):
        """Latest positioning attempt's key, not the reference acquisition's key."""
        return self.last_run_key if self.last_run_key is not None else float("nan")

    def load_reference(self, path):
        with self._operation_lock:
            path = Path(path)
            if path.stat().st_size > 30_000_000:
                raise ValueError("Reference file exceeds 30 MB")
            with path.open(encoding="utf-8") as stream:
                reference = ReferenceMap.from_dict(json.load(stream))
            self.settings = replace(self.settings, map=reference.geometry, point=reference.point,
                                    directory=self.settings.directory.strip() or str(path.parent))
            self.reference, self.result, self.applied = reference, None, False
        self.sig_settings.emit(self.settings)
        self.sig_reference.emit(reference)
        self.sig_status.emit("Reference loaded without motion; review channels, units, registration bounds and results directory")

    def load_setup(self, path):
        with self._operation_lock:
            if Path(path).stat().st_size > 1_000_000:
                raise ValueError("Setup file exceeds 1 MB")
            with open(path, encoding="utf-8") as stream:
                settings = PositionSettings.from_dict(json.load(stream))
            self.settings = settings
        self.sig_settings.emit(settings)
        self.sig_status.emit("Setup loaded without motion; the existing reference is not replaced")

    def save_edited_point(self):
        with self._operation_lock:
            if self.reference is None or self.reference.geometry != self.settings.map:
                raise ValueError("Acquire/load a matching reference map first")
            reference = ReferenceMap(self.settings.map, self.settings.map.point(self.settings.point), self.reference.image)
            record = RunRecord(self.settings.directory, "reference")
            self.last_output_directory = str(record.path)
            record.json("reference.json", reference.to_dict())
            g = reference.geometry
            record.map("map.png", reference.image, g.xs, g.ys, reference.point, "Reference with edited point",
                       (f"X ({g.x_unit})", f"Y ({g.y_unit})"))
            record.json("run.json", {"status": "reference_point_edited", "motion": False, "settings": self.settings.to_dict()})
            self.reference = reference
            self.result, self.applied = None, False
        self.sig_reference.emit(reference)
        self.sig_status.emit(f"Reference point saved without motion: {record.path}")

    def disconnect(self):
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError("Wait for the active operation before releasing the reference")
        try:
            self.reference, self.result, self.applied = None, None, False
        finally:
            self._operation_lock.release()
        self.sig_reference.emit(None)

    def submit(self, operation, *args):
        with self._job_lock:
            if self.is_busy() or self._job is not None:
                self.sig_error.emit("Auto-position is busy")
                return False
            self.stop_event.clear()
            self._job = (operation, args)
            self.sig_busy.emit(True)
            self.start()
            return True

    def run(self):
        try:
            operation, args = self._job
            operation(*args)
        except PositionStopped as exc:
            self.sig_status.emit(str(exc))
        except Exception as exc:
            self.sig_error.emit(str(exc))
        finally:
            with self._job_lock:
                self._job = None
            self.sig_busy.emit(False)

    def force_stop(self):
        self.stop_event.set()
        self.sig_status.emit("Stop requested; current device command may still need to finish")
        return True

    def stop_scan(self):
        if self.is_busy():
            raise RuntimeError("Auto-position is genuinely active; let it finish or stop it")
        self.stop_event.clear()

    def start_scan(self):
        self.stop_event.clear()

    def terminate_dev(self, wait_ms=3000):
        self.stop_event.set()
        if self.isRunning() and not self.wait(wait_ms):
            return False
        if not self._operation_lock.acquire(timeout=wait_ms / 1000):
            return False
        try:
            self.router = None  # Owns no actuator/input connection; no cleanup move.
        finally:
            self._operation_lock.release()
        return True

    def find_catalog_references(self, *, removed_setters=(), removed_getters=(), removed_device_labels=()):
        geometries = [self.settings.map] + ([self.reference.geometry] if self.reference else [])
        refs = set()
        for g in geometries:
            for ref, removed in ((g.x, removed_setters), (g.y, removed_setters), (g.signal, removed_getters)):
                if ref.device in removed_device_labels or f"{ref.device}_{ref.channel}" in removed:
                    refs.add(f"auto-position uses {ref.device}/{ref.channel}")
        return tuple(sorted(refs))
