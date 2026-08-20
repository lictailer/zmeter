"""Scan-facing and asynchronous UI coordination for SP150."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from PyQt6 import QtCore

from .sp150_hardware import SP150Hardware


class SP150MoveTimeout(TimeoutError):
    """Raised when SP150 readback does not reach the requested wavelength."""


class SP150OperationCancelled(RuntimeError):
    """Raised when an SP150 operation is cooperatively cancelled."""


class SP150Logic(QtCore.QThread):
    sig_last_wavelength = QtCore.pyqtSignal(object)
    sig_setting_wavelength = QtCore.pyqtSignal(str)
    sig_connected = QtCore.pyqtSignal(bool)
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)

    def __init__(
        self,
        hardware: SP150Hardware | None = None,
        move_timeout_s: float = 120.0,
        poll_interval_s: float = 0.25,
        completion_tolerance_nm: float = 0.1,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self.hardware = hardware or SP150Hardware()
        self.move_timeout_s = self._positive(move_timeout_s, "move timeout")
        self.poll_interval_s = self._nonnegative(
            poll_interval_s, "poll interval"
        )
        self.completion_tolerance_nm = self._positive(
            completion_tolerance_nm, "completion tolerance"
        )
        self._monotonic = monotonic
        self._operation_lock = threading.RLock()
        self._job_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._job: tuple[Callable[..., Any], tuple[Any, ...]] | None = None
        self._scan_mode = False
        self._terminate_requested = False

    @property
    def connected(self) -> bool:
        return self.hardware.connected

    def connect(
        self,
        address: str,
        timeout_ms: int = 10_000,
        query_delay_s: float = 1.0,
    ) -> bool:
        with self._operation_lock:
            result = self.hardware.connect(
                address,
                timeout_ms=timeout_ms,
                query_delay_s=query_delay_s,
            )
        self.sig_connected.emit(True)
        self.sig_status.emit(f"connected to {address}")
        return result

    def disconnect(self) -> None:
        if self.isRunning():
            raise RuntimeError("Cannot disconnect SP150 while an operation is active")
        with self._operation_lock:
            self.hardware.disconnect()
        self.sig_connected.emit(False)
        self.sig_status.emit("disconnected")

    def set_wavelength(self, wavelength_nm):
        target = self.hardware.validate_wavelength(wavelength_nm)
        with self._operation_lock:
            self._require_scan_ready()
            self.sig_setting_wavelength.emit(f"moving to {target:.2f} nm")
            self.hardware.command_wavelength(target)
            deadline = self._monotonic() + self.move_timeout_s
            while True:
                self._raise_if_cancelled()
                actual = self.hardware.read_wavelength()
                self.sig_last_wavelength.emit(actual)
                if abs(actual - target) <= self.completion_tolerance_nm:
                    return actual
                if self._monotonic() >= deadline:
                    raise SP150MoveTimeout(
                        "SP150 did not reach "
                        f"{target:.2f} nm within {self.move_timeout_s:.2f} s; "
                        f"last readback was {actual:.2f} nm"
                    )
                if self._cancel_event.wait(self.poll_interval_s):
                    raise SP150OperationCancelled("SP150 move cancelled")

    def get_wavelength(self):
        with self._operation_lock:
            self._require_scan_ready()
            value = self.hardware.read_wavelength()
        self.sig_last_wavelength.emit(value)
        return value

    def submit_ui_job(self, operation: Callable[..., Any], *args: Any) -> bool:
        with self._job_lock:
            if self._scan_mode:
                self.sig_error.emit("SP150 UI commands are disabled during a scan")
                return False
            if self.isRunning() or self._job is not None:
                self.sig_error.emit("SP150 is busy")
                return False
            self._cancel_event.clear()
            self._job = (operation, args)
            self.start()
            return True

    def stop_scan(self, wait_ms: int = 2_000) -> bool:
        self._scan_mode = True
        self._cancel_event.set()
        stopped = not self.isRunning() or self.wait(wait_ms)
        if stopped:
            self._cancel_event.clear()
        else:
            self.sig_status.emit("SP150 stop requested; waiting for VISA timeout")
        return stopped

    def start_scan(self) -> bool:
        self._scan_mode = False
        if self.isRunning():
            self.sig_error.emit("SP150 operation is still active")
            return False
        self._cancel_event.clear()
        return True

    def force_stop(self, wait_ms: int = 2_000) -> bool:
        self._cancel_event.set()
        pending = self.isRunning() and not self.wait(wait_ms)
        if pending:
            self.sig_status.emit("SP150 stop requested; waiting for VISA timeout")
        return pending

    def terminate_dev(self, wait_ms: int = 2_000) -> bool:
        self._terminate_requested = True
        pending = self.force_stop(wait_ms)
        if pending:
            return False
        self.disconnect()
        return True

    def run(self) -> None:
        with self._job_lock:
            job = self._job
        if job is None:
            return
        try:
            operation, args = job
            operation(*args)
        except Exception as exc:
            self.sig_error.emit(str(exc))
        finally:
            with self._job_lock:
                self._job = None
            if self._terminate_requested:
                try:
                    with self._operation_lock:
                        self.hardware.disconnect()
                    self.sig_connected.emit(False)
                except Exception as exc:
                    self.sig_error.emit(f"SP150 deferred disconnect failed: {exc}")

    def _require_scan_ready(self) -> None:
        self._raise_if_cancelled()
        if not self.connected:
            raise RuntimeError("SP150 is not connected; call connect(address) first")

    def _raise_if_cancelled(self) -> None:
        if self._cancel_event.is_set():
            raise SP150OperationCancelled("SP150 operation cancelled")

    @staticmethod
    def _positive(value: float, label: str) -> float:
        converted = SP150Hardware._finite_value(value, label)
        if converted <= 0:
            raise ValueError(f"SP150 {label} must be positive")
        return converted

    @staticmethod
    def _nonnegative(value: float, label: str) -> float:
        converted = SP150Hardware._finite_value(value, label)
        if converted < 0:
            raise ValueError(f"SP150 {label} cannot be negative")
        return converted
