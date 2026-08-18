from __future__ import annotations

import math
import threading
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any

from PyQt6 import QtCore

try:
    from .BBD30X_hardware import BBD30x_hardware
except ImportError:
    from BBD30X_hardware import BBD30x_hardware


class BBD30X_Logic(QtCore.QThread):
    LIGHT_SPEED_MM_PER_PS = 0.299792458

    sig_current_pos = QtCore.pyqtSignal(object)
    sig_target_pos = QtCore.pyqtSignal(object)
    sig_velocity_params = QtCore.pyqtSignal(object)
    sig_connect = QtCore.pyqtSignal(bool)
    sig_t0_changed = QtCore.pyqtSignal(object)
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)
    sig_log = QtCore.pyqtSignal(object)

    def __init__(self, hardware=None):
        super().__init__()
        self.hw = hardware if hardware is not None else BBD30x_hardware()
        self.hardware = self.hw
        self.is_connected = False
        self.serial = ""
        self.t0_mm: float | None = None
        self._operation_lock = threading.RLock()
        self._state_lock = threading.Lock()
        self._job_lock = threading.Lock()
        self._pending_job: tuple[Callable[..., Any], tuple[Any, ...]] | None = None
        self._operation_active = False
        self._cancel_event = threading.Event()

    def _emit_log(self, message: str, level: str = "INFO") -> None:
        self.sig_log.emit((str(level).upper(), str(message)))

    @contextmanager
    def _operation(self):
        with self._operation_lock:
            with self._state_lock:
                self._operation_active = True
            try:
                yield
            finally:
                with self._state_lock:
                    self._operation_active = False

    def _require_connected(self) -> None:
        if not self.is_connected:
            raise RuntimeError("BBD30X is not connected")

    def _clear_t0(self) -> None:
        self.t0_mm = None
        self.sig_t0_changed.emit(None)

    def connect(self, serial: str) -> bool:
        serial = str(serial).strip()
        if not serial:
            raise ValueError("Enter a BBD30X serial number")
        if self.is_connected:
            return True

        with self._operation():
            self.serial = serial
            self.sig_status.emit(f"Connecting to BBD30X {serial}")
            self._emit_log(f"Connecting to BBD30X {serial}.")
            try:
                velocity, acceleration = self.hw.connect(serial)
            except Exception as exc:
                self.is_connected = False
                self._clear_t0()
                self.sig_connect.emit(False)
                self.sig_status.emit("Connection failed")
                self._emit_log(
                    f"Connection failed for {serial}: {type(exc).__name__}: {exc}",
                    level="ERROR",
                )
                raise

            self.is_connected = True
            self._cancel_event.clear()
            self._clear_t0()
            self.sig_connect.emit(True)
            self.sig_velocity_params.emit((velocity, acceleration))
            self.sig_status.emit(f"Connected to BBD30X {serial}")
            self._emit_log(
                "Connected; applied motion parameters "
                f"{velocity:g} mm/s and {acceleration:g} mm/s^2."
            )
            return True

    def disconnect(self) -> None:
        with self._operation():
            self._cancel_event.set()
            try:
                self.hw.disconnect()
            finally:
                self.is_connected = False
                self._clear_t0()
                self.sig_connect.emit(False)
                self.sig_status.emit("Disconnected")
                self._emit_log("BBD30X disconnected.")

    @staticmethod
    def _finite(value: object, name: str) -> float:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError(f"{name} must be finite")
        return numeric

    @classmethod
    def mm_to_um(cls, position_mm: object) -> float:
        return cls._finite(position_mm, "Position") * 1000.0

    @classmethod
    def um_to_mm(cls, position_um: object) -> float:
        return cls._finite(position_um, "Position") / 1000.0

    def _require_t0(self) -> float:
        if self.t0_mm is None:
            raise RuntimeError("Set BBD30X T0 before using the delay_ps channel")
        return self.t0_mm

    def mm_to_delay_ps(self, position_mm: object) -> float:
        position = self._finite(position_mm, "Position")
        t0_mm = self._require_t0()
        return 2.0 * (position - t0_mm) / self.LIGHT_SPEED_MM_PER_PS

    def delay_ps_to_mm(self, delay_ps: object) -> float:
        delay = self._finite(delay_ps, "Delay")
        t0_mm = self._require_t0()
        return t0_mm + delay * self.LIGHT_SPEED_MM_PER_PS / 2.0

    def _move_to_mm(self, position_mm: object) -> float:
        self._require_connected()
        with self._operation():
            self._cancel_event.clear()
            target_mm = self.hw.validate_position_mm(position_mm)
            self.sig_target_pos.emit(target_mm)
            self.sig_status.emit(f"Moving to {target_mm:.4f} mm")
            self._emit_log(f"Move started: target {target_mm:.4f} mm.")
            try:
                final_mm = self.hw.move(
                    target_mm,
                    position_callback=self.sig_current_pos.emit,
                    cancel_event=self._cancel_event,
                )
            except Exception as exc:
                self.sig_status.emit("Move failed")
                self._emit_log(
                    f"Move to {target_mm:.4f} mm failed: "
                    f"{type(exc).__name__}: {exc}",
                    level="ERROR",
                )
                raise
            self.sig_current_pos.emit(final_mm)
            self.sig_target_pos.emit(target_mm)
            self.sig_status.emit(f"Move completed at {final_mm:.4f} mm")
            self._emit_log(f"Move completed at {final_mm:.4f} mm.")
            return final_mm

    # Scan-visible API. Keep these as the only get_*/set_* position methods.
    def set_pos_mm(self, position_mm):
        return self._move_to_mm(position_mm)

    def get_pos_mm(self):
        self._require_connected()
        with self._operation():
            return self.hw.get_position_mm()

    def set_pos_um(self, position_um):
        return self._move_to_mm(self.um_to_mm(position_um))

    def get_pos_um(self):
        return self.mm_to_um(self.get_pos_mm())

    def set_delay_ps(self, delay_ps):
        return self._move_to_mm(self.delay_ps_to_mm(delay_ps))

    def get_delay_ps(self):
        return self.mm_to_delay_ps(self.get_pos_mm())

    def read_position_from_ui(self) -> tuple[float, float]:
        self._require_connected()
        with self._operation():
            current_mm = self.hw.get_position_mm()
            target_mm = self.hw.get_target_position_mm()
            self.sig_current_pos.emit(current_mm)
            self.sig_target_pos.emit(target_mm)
            self.sig_status.emit(f"Position read: {current_mm:.4f} mm")
            self._emit_log(
                f"Position read: current {current_mm:.4f} mm, "
                f"target {target_mm:.4f} mm."
            )
            return current_mm, target_mm

    def set_t0_from_current_position(self) -> float:
        self._require_connected()
        with self._operation():
            current_mm = self.hw.get_position_mm()
            target_mm = self.hw.get_target_position_mm()
            self.t0_mm = current_mm
            self.sig_t0_changed.emit(current_mm)
            self.sig_current_pos.emit(current_mm)
            self.sig_target_pos.emit(target_mm)
            self.sig_status.emit(f"T0 set at {current_mm:.4f} mm")
            self._emit_log(f"T0 set from position readback: {current_mm:.4f} mm.")
            return current_mm

    def set_velocity_params(
        self, velocity: object | None = None, acceleration: object | None = None
    ) -> tuple[float, float]:
        self._require_connected()
        with self._operation():
            values = self.hw.set_velocity_params(velocity, acceleration)
            self.sig_velocity_params.emit(values)
            self.sig_status.emit("Motion parameters updated")
            self._emit_log(
                f"Motion parameters read back: {values[0]:g} mm/s, "
                f"{values[1]:g} mm/s^2."
            )
            return values

    def home(self) -> None:
        self._require_connected()
        with self._operation():
            self._emit_log("Home requested.", level="WARNING")
            self.hw.home()
            self.sig_status.emit("Home completed")
            self._emit_log("Home completed.")

    def submit_ui_job(self, operation: Callable[..., Any], *args: Any) -> bool:
        with self._job_lock:
            with self._state_lock:
                busy = self._operation_active
            if self.isRunning() or self._pending_job is not None or busy:
                message = "BBD30X is busy"
                self.sig_error.emit(message)
                self.sig_status.emit(message)
                self._emit_log(message, level="WARNING")
                return False
            self._cancel_event.clear()
            self._pending_job = (operation, args)
            self.start()
            return True

    def run(self) -> None:
        with self._job_lock:
            job = self._pending_job
            self._pending_job = None
        if job is None:
            return

        operation, args = job
        try:
            operation(*args)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            self.sig_error.emit(message)
            self.sig_status.emit(message)
            # Operation methods log contextual errors; this guarantees coverage
            # for validation and other failures before an operation begins.
            self._emit_log(message, level="ERROR")

    def start_scan(self) -> bool:
        self._cancel_event.clear()
        return True

    def stop_scan(self) -> bool:
        # MainWindow calls this before scan execution to stop device monitors.
        # BBD30X has no monitor and scan moves remain enabled.
        return True

    def force_stop(self) -> bool:
        with self._state_lock:
            active = self._operation_active
        self._cancel_event.set()
        if active:
            self.sig_status.emit("BBD30X stop requested")
            self._emit_log("Stop requested; the active move will issue Kinesis Stop.")
        return active

    def terminate_dev(self) -> bool:
        self.force_stop()
        if self.isRunning() and not self.wait(2000):
            self._emit_log(
                "Termination deferred because an operation is still active.",
                level="WARNING",
            )
            return False
        self.disconnect()
        return True
