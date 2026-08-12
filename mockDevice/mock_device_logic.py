from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from PyQt6 import QtCore

from .mock_device_hardware import MockDeviceHardware
from .mock_device_simulator import MockDeviceFailAfterError


class MockDeviceLogic(QtCore.QThread):
    sig_connected = QtCore.pyqtSignal(object)
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)
    sig_last_set_A = QtCore.pyqtSignal(object)
    sig_last_set_B = QtCore.pyqtSignal(object)
    sig_last_read_A = QtCore.pyqtSignal(object)
    sig_last_read_B = QtCore.pyqtSignal(object)
    sig_random = QtCore.pyqtSignal(object)
    sig_ramp_active = QtCore.pyqtSignal(bool)
    sig_log_updated = QtCore.pyqtSignal(object)
    sig_reset_completed = QtCore.pyqtSignal()
    sig_fail_after_triggered = QtCore.pyqtSignal()

    def __init__(self, hardware: MockDeviceHardware | None = None):
        super().__init__()
        self.hardware = hardware or MockDeviceHardware()
        self._job_lock = threading.Lock()
        self._pending_job: tuple[str, Any] | None = None

    # Scan-visible API. Keep these as the only get_*/set_* methods.
    def set_channel_A(self, value: float) -> float:
        result = self._execute("Set channel A", self.hardware.set_channel_A, value)
        self.sig_last_set_A.emit(result)
        return result

    def set_channel_B(self, value: float) -> float:
        result = self._execute("Set channel B", self.hardware.set_channel_B, value)
        self.sig_last_set_B.emit(result)
        return result

    def get_channel_A(self) -> float:
        result = self._execute("Read channel A", self.hardware.read_channel_A)
        self.sig_last_read_A.emit(result)
        return result

    def get_channel_B(self) -> float:
        result = self._execute("Read channel B", self.hardware.read_channel_B)
        self.sig_last_read_B.emit(result)
        return result

    def get_random_channel(self) -> float:
        result = self._execute("Read random channel", self.hardware.read_random_channel)
        self.sig_random.emit(result)
        return result

    def set_ramp_channel_A(self, value: float) -> float:
        return self._run_ramp("A", value, self.hardware.ramp_channel_A)

    def set_ramp_channel_B(self, value: float) -> float:
        return self._run_ramp("B", value, self.hardware.ramp_channel_B)

    # Device lifecycle used by the main widget and MainWindow.
    def connect_device(self, address: str) -> str:
        connected_address = self._execute(
            "Connect", self.hardware.connect, str(address).strip()
        )
        self.sig_connected.emit((True, connected_address))
        self.sig_status.emit(f"Connected to {connected_address}")
        return connected_address

    def disconnect_device(self) -> None:
        self.hardware.force_stop()
        self._execute("Disconnect", self.hardware.disconnect)
        self.sig_connected.emit((False, ""))
        self.sig_status.emit("Disconnected")

    def start_scan(self) -> None:
        self._execute("Start scan", self.hardware.start_scan)
        self.sig_status.emit("Ready for scan")

    def stop_scan(self) -> None:
        self._execute("Stop scan", self.hardware.stop_scan)
        self.sig_status.emit("Scan stopped")

    def force_stop(self) -> bool:
        stopped = self.hardware.force_stop()
        self._emit_log()
        if stopped:
            self.sig_status.emit("Emergency ramp stop requested")
        return stopped

    def close(self) -> None:
        self.hardware.force_stop()
        if self.isRunning():
            self.wait(2000)
        if self.hardware.connected:
            self.disconnect_device()

    def reset_device(self) -> None:
        self._execute("Reset", self.hardware.reset)
        self.sig_last_set_A.emit(0.0)
        self.sig_last_set_B.emit(0.0)
        self.sig_last_read_A.emit(None)
        self.sig_last_read_B.emit(None)
        self.sig_random.emit(None)
        self.sig_status.emit("Mock device reset")
        self.sig_reset_completed.emit()

    # Fault controls used by the mock-device UI.
    def activate_fail_after(self, command_count: int) -> None:
        self._execute(
            "Activate fail-after fault",
            self.hardware.activate_fail_after,
            command_count,
        )
        self.sig_status.emit(f"Fail-after fault active: command {int(command_count)}")

    def stop_fail_after(self) -> None:
        self._execute("Stop fail-after fault", self.hardware.stop_fail_after)
        self.sig_status.emit("Fail-after fault stopped")

    def activate_random_failure(self, probability: float) -> None:
        self._execute(
            "Activate random fault",
            self.hardware.activate_random_failure,
            probability,
        )
        self.sig_status.emit(f"Random fault active: probability {float(probability):.3g}")

    def stop_random_failure(self) -> None:
        self._execute("Stop random fault", self.hardware.stop_random_failure)
        self.sig_status.emit("Random fault stopped")

    def activate_range_rejection(self) -> None:
        self._execute(
            "Activate range rejection", self.hardware.activate_range_rejection
        )
        self.sig_status.emit("Out-of-range rejection active")

    def stop_range_rejection(self) -> None:
        self._execute("Stop range rejection", self.hardware.stop_range_rejection)
        self.sig_status.emit("Out-of-range rejection stopped")

    # UI jobs run in this QThread so long ramps do not block the widget.
    def start_job(self, job_name: str, value: Any = None) -> bool:
        with self._job_lock:
            if self.isRunning() or self._pending_job is not None:
                self.sig_status.emit("Mock device is busy")
                return False
            self._pending_job = (job_name, value)
        self.start()
        return True

    def run(self) -> None:
        with self._job_lock:
            job = self._pending_job
            self._pending_job = None
        if job is None:
            return

        job_name, value = job
        actions: dict[str, Callable[[], Any]] = {
            "connect": lambda: self.connect_device(value),
            "disconnect": self.disconnect_device,
            "set_A": lambda: self.set_channel_A(value),
            "set_B": lambda: self.set_channel_B(value),
            "read_A": self.get_channel_A,
            "read_B": self.get_channel_B,
            "read_random": self.get_random_channel,
            "ramp_A": lambda: self.set_ramp_channel_A(value),
            "ramp_B": lambda: self.set_ramp_channel_B(value),
            "reset": self.reset_device,
            "fail_after_on": lambda: self.activate_fail_after(value),
            "fail_after_off": self.stop_fail_after,
            "random_fail_on": lambda: self.activate_random_failure(value),
            "random_fail_off": self.stop_random_failure,
            "range_on": self.activate_range_rejection,
            "range_off": self.stop_range_rejection,
        }
        action = actions.get(job_name)
        if action is None:
            self.sig_error.emit(f"Unknown mock-device job '{job_name}'.")
            return
        try:
            action()
        except Exception:
            pass

    def _run_ramp(
        self,
        channel: str,
        target: float,
        ramp: Callable[[float], tuple[float, bool]],
    ) -> float:
        self.sig_ramp_active.emit(True)
        try:
            value, aborted = self._execute(
                f"Ramp channel {channel}", ramp, float(target)
            )
            if channel == "A":
                self.sig_last_set_A.emit(value)
            else:
                self.sig_last_set_B.emit(value)
            if aborted:
                self.sig_status.emit(
                    f"Ramp {channel} stopped at {value:.9g}"
                )
            else:
                self.sig_status.emit(
                    f"Ramp {channel} completed at {value:.9g}"
                )
            return value
        finally:
            self.sig_ramp_active.emit(False)

    def _execute(
        self,
        description: str,
        operation: Callable[..., Any],
        *args: Any,
    ) -> Any:
        try:
            result = operation(*args)
        except Exception as exc:
            message = f"{description} failed: {type(exc).__name__}: {exc}"
            if isinstance(exc, MockDeviceFailAfterError):
                self.sig_fail_after_triggered.emit()
            self.sig_error.emit(message)
            self.sig_status.emit(message)
            self._emit_log()
            raise
        self._emit_log()
        return result

    def _emit_log(self) -> None:
        self.sig_log_updated.emit(self.hardware.command_log)
