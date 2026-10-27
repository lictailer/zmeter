"""Scan-facing and asynchronous UI coordination for the MC2000B."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PyQt6 import QtCore

from .mc2000b_hardware import MC2000BHardware, MC2000BProtocolError


class MC2000BLogic(QtCore.QThread):
    sig_frequency = QtCore.pyqtSignal(object)
    sig_blade_index = QtCore.pyqtSignal(object)
    sig_reference_input = QtCore.pyqtSignal(object)
    sig_phase = QtCore.pyqtSignal(object)
    sig_enabled = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(bool)
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)

    def __init__(self, hardware: MC2000BHardware | None = None) -> None:
        super().__init__()
        self.hardware = hardware or MC2000BHardware()
        self._operation_lock = threading.RLock()
        self._job_lock = threading.Lock()
        self._job: tuple[Callable[..., Any], tuple[Any, ...]] | None = None
        self._terminate_requested = False

    @property
    def connected(self) -> bool:
        return self.hardware.connected

    def connect(self, address: str) -> bool:
        with self._operation_lock:
            result = self.hardware.connect(address)
        self.sig_connected.emit(True)
        self.sig_status.emit(f"connected to {address}")
        try:
            self.get_enabled()
            self.get_blade_index()
            self.get_reference_input()
        except Exception as exc:
            self.sig_error.emit(f"connected, but could not read controller state: {exc}")
        return result

    def disconnect(self) -> None:
        with self._operation_lock:
            self.hardware.disconnect()
        self.sig_connected.emit(False)
        self.sig_enabled.emit(None)
        self.sig_blade_index.emit(None)
        self.sig_reference_input.emit(None)
        self.sig_status.emit("disconnected")

    def get_blade_index(self) -> int:
        with self._operation_lock:
            self._require_connected()
            index = self.hardware.get_blade_index()
        self.sig_blade_index.emit(index)
        return index

    def get_reference_input(self) -> int:
        with self._operation_lock:
            self._require_connected()
            reference = self.hardware.get_reference_input()
        self.sig_reference_input.emit(reference)
        return reference

    def select_internal_reference(self, reference: int) -> int:
        with self._operation_lock:
            self._require_connected()
            selected = self.hardware.select_internal_reference(reference)
        self.sig_reference_input.emit(selected)
        self.sig_frequency.emit(None)
        side = "outer" if selected == 0 else "inner"
        self.sig_status.emit(
            f"MC1F10HP internal {side} reference selected; "
            "frequency target readback cleared"
        )
        return selected

    def set_frequency(self, frequency_hz):
        with self._operation_lock:
            self._require_connected()
            value = self.hardware.set_frequency(frequency_hz)
        self.sig_frequency.emit(None)
        self.sig_status.emit(f"frequency set to {value} Hz; use Get to read back")
        return value

    def get_frequency(self):
        with self._operation_lock:
            self._require_connected()
            value = self.hardware.get_frequency()
        self.sig_frequency.emit(value)
        return value

    def set_phase(self, phase_deg):
        with self._operation_lock:
            self._require_connected()
            value = self.hardware.set_phase(phase_deg)
        self.sig_phase.emit(None)
        self.sig_status.emit(f"phase set to {value} degrees; use Get to read back")
        return value

    def get_phase(self):
        with self._operation_lock:
            self._require_connected()
            value = self.hardware.get_phase()
        self.sig_phase.emit(value)
        return value

    def get_enabled(self) -> bool:
        with self._operation_lock:
            self._require_connected()
            enabled = self.hardware.get_enabled()
        self.sig_enabled.emit(enabled)
        return enabled

    def start_chopper(self) -> bool:
        return self._set_chopper_enabled(True)

    def stop_chopper(self) -> bool:
        return self._set_chopper_enabled(False)

    def _set_chopper_enabled(self, requested: bool) -> bool:
        self.sig_enabled.emit(None)
        with self._operation_lock:
            self._require_connected()
            self.hardware.set_enabled(requested)
            actual = self.hardware.get_enabled()
        self.sig_enabled.emit(actual)
        if actual != requested:
            raise MC2000BProtocolError(
                "MC2000B run mode did not match the requested state "
                f"(requested {int(requested)}, received {int(actual)})"
            )
        self.sig_status.emit("chopper run mode enabled" if actual else "chopper standby")
        return actual

    def submit_ui_job(
        self,
        operation: Callable[..., Any],
        *args: Any,
    ) -> bool:
        with self._job_lock:
            if self.isRunning() or self._job is not None:
                self.sig_error.emit("MC2000B is busy")
                return False
            self._job = (operation, args)
            self.start()
            return True

    def force_stop(self, wait_ms: int = 2_000) -> bool:
        if self.isRunning() and not self.wait(wait_ms):
            self.sig_status.emit(
                "MC2000B stop requested; waiting for the serial timeout"
            )
            return False
        return True

    def terminate_dev(self, wait_ms: int = 2_000) -> bool:
        self._terminate_requested = True
        if not self.force_stop(wait_ms):
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
                    self.sig_error.emit(f"MC2000B deferred disconnect failed: {exc}")

    def _require_connected(self) -> None:
        if not self.connected:
            raise RuntimeError(
                "MC2000B is not connected; call connect(address) first"
            )
