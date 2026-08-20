"""Scan-facing and asynchronous UI coordination for PEM100."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PyQt6 import QtCore

from .pem100_hardware import PEM100Hardware


class PEM100Logic(QtCore.QThread):
    sig_last_retardance = QtCore.pyqtSignal(object)
    sig_last_wavelength = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(bool)
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)

    def __init__(self, hardware: PEM100Hardware | None = None) -> None:
        super().__init__()
        self.hardware = hardware or PEM100Hardware()
        self._operation_lock = threading.RLock()
        self._job_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._job: tuple[Callable[..., Any], tuple[Any, ...]] | None = None
        self._scan_mode = False
        self._terminate_requested = False

    @property
    def connected(self) -> bool:
        return self.hardware.connected

    def connect(self, address: str, timeout_ms: int = 20_000) -> bool:
        with self._operation_lock:
            result = self.hardware.connect(address, timeout_ms=timeout_ms)
        self.sig_connected.emit(True)
        self.sig_status.emit(f"connected to {address}")
        return result

    def disconnect(self) -> None:
        if self.isRunning():
            raise RuntimeError("Cannot disconnect PEM100 while an operation is active")
        with self._operation_lock:
            self.hardware.disconnect()
        self.sig_connected.emit(False)
        self.sig_status.emit("disconnected")

    def set_wavelength(self, wavelength_nm):
        with self._operation_lock:
            self._require_scan_ready()
            self.hardware.set_wavelength(wavelength_nm, self._cancel_event)
            value = self.hardware.get_wavelength(self._cancel_event)
        self.sig_last_wavelength.emit(value)
        return value

    def get_wavelength(self):
        with self._operation_lock:
            self._require_scan_ready()
            value = self.hardware.get_wavelength(self._cancel_event)
        self.sig_last_wavelength.emit(value)
        return value

    def set_retardance(self, retardance_lambda):
        with self._operation_lock:
            self._require_scan_ready()
            self.hardware.set_retardance(retardance_lambda, self._cancel_event)
            value = self.hardware.get_retardance(self._cancel_event)
        self.sig_last_retardance.emit(value)
        return value

    def get_retardance(self):
        with self._operation_lock:
            self._require_scan_ready()
            value = self.hardware.get_retardance(self._cancel_event)
        self.sig_last_retardance.emit(value)
        return value

    def submit_ui_job(self, operation: Callable[..., Any], *args: Any) -> bool:
        with self._job_lock:
            if self._scan_mode:
                self.sig_error.emit("PEM100 UI commands are disabled during a scan")
                return False
            if self.isRunning() or self._job is not None:
                self.sig_error.emit("PEM100 is busy")
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
            self.sig_status.emit("PEM100 stop requested; waiting for VISA timeout")
        return stopped

    def start_scan(self) -> bool:
        self._scan_mode = False
        if self.isRunning():
            self.sig_error.emit("PEM100 operation is still active")
            return False
        self._cancel_event.clear()
        return True

    def force_stop(self, wait_ms: int = 2_000) -> bool:
        self._cancel_event.set()
        pending = self.isRunning() and not self.wait(wait_ms)
        if pending:
            self.sig_status.emit("PEM100 stop requested; waiting for VISA timeout")
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
                    self.sig_error.emit(f"PEM100 deferred disconnect failed: {exc}")

    def _require_scan_ready(self) -> None:
        if self._cancel_event.is_set():
            raise RuntimeError("PEM100 operation cancelled")
        if not self.connected:
            raise RuntimeError("PEM100 is not connected; call connect(address) first")
