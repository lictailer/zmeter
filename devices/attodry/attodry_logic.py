from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt6 import QtCore

from .attodry_hardware import AttoDryHardware


@dataclass(frozen=True)
class StabilitySettings:
    tolerance: float
    stable_samples: int
    poll_interval_s: float


class AttoDryLogic(QtCore.QThread):
    """Scan-facing channels and background jobs for the attoDRY panel."""

    sig_connected = QtCore.pyqtSignal(bool, str)
    sig_temperature = QtCore.pyqtSignal(float)
    sig_field = QtCore.pyqtSignal(float)
    sig_field_state = QtCore.pyqtSignal(str)
    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)
    sig_waiting = QtCore.pyqtSignal(bool, str)

    DEFAULT_TEMPERATURE_TOLERANCE_K = 0.05
    MIN_TEMPERATURE_TOLERANCE_K = 0.001
    MAX_TEMPERATURE_TOLERANCE_K = 5.0
    DEFAULT_FIELD_TOLERANCE_T = 0.001
    MIN_FIELD_TOLERANCE_T = 0.00001
    MAX_FIELD_TOLERANCE_T = 0.1
    DEFAULT_STABLE_SAMPLES = 5
    MIN_STABLE_SAMPLES = 2
    MAX_STABLE_SAMPLES = 100
    DEFAULT_POLL_INTERVAL_S = 2.0
    MIN_POLL_INTERVAL_S = 0.5
    MAX_POLL_INTERVAL_S = 60.0
    TEMPERATURE_TIMEOUT_S = 4 * 60 * 60
    FIELD_TIMEOUT_S = 2 * 60 * 60

    def __init__(self, hardware: AttoDryHardware | None = None) -> None:
        super().__init__()
        self.hardware = hardware or AttoDryHardware()
        self.is_connected = False
        self.monitor_enabled = True
        self._stop_requested = threading.Event()
        self._job_lock = threading.Lock()
        self._settings_lock = threading.Lock()
        self._temperature_stability = StabilitySettings(
            self.DEFAULT_TEMPERATURE_TOLERANCE_K,
            self.DEFAULT_STABLE_SAMPLES,
            self.DEFAULT_POLL_INTERVAL_S,
        )
        self._field_stability = StabilitySettings(
            self.DEFAULT_FIELD_TOLERANCE_T,
            self.DEFAULT_STABLE_SAMPLES,
            self.DEFAULT_POLL_INTERVAL_S,
        )
        self._pending_job: tuple[str, Any] | None = None

    # Scan-visible API. Keep these as the only public get_*/set_* methods.
    def get_T(self) -> float:
        value = self._execute("Read sample temperature", self.hardware.read_temperature_k)
        self.sig_temperature.emit(value)
        return value

    def get_B(self) -> float:
        value = self._execute("Read magnetic field", self.hardware.read_field_t)
        self.sig_field.emit(value)
        return value

    def set_T(self, target_k: float) -> float:
        target = self._execute(
            "Set sample temperature", self.hardware.set_temperature_k, target_k
        )
        self.sig_status.emit(f"Temperature control started at {target:.6g} K")
        return target

    def set_T_stable(self, target_k: float) -> float:
        settings = self.temperature_stability
        target = self.set_T(target_k)
        return self._wait_for_stability(
            quantity="temperature",
            target=target,
            tolerance=settings.tolerance,
            stable_samples=settings.stable_samples,
            poll_interval_s=settings.poll_interval_s,
            timeout_s=self.TEMPERATURE_TIMEOUT_S,
            reader=self.get_T,
            unit="K",
        )

    @property
    def temperature_stability(self) -> StabilitySettings:
        with self._settings_lock:
            return self._temperature_stability

    @property
    def field_stability(self) -> StabilitySettings:
        with self._settings_lock:
            return self._field_stability

    def configure_temperature_stability(
        self,
        tolerance_k: float,
        stable_samples: int,
        poll_interval_s: float,
    ) -> StabilitySettings:
        settings = self._validate_stability_settings(
            quantity="temperature",
            tolerance=tolerance_k,
            minimum_tolerance=self.MIN_TEMPERATURE_TOLERANCE_K,
            maximum_tolerance=self.MAX_TEMPERATURE_TOLERANCE_K,
            tolerance_unit="K",
            stable_samples=stable_samples,
            poll_interval_s=poll_interval_s,
        )
        with self._settings_lock:
            self._temperature_stability = settings
        self.sig_status.emit(self._settings_status("Temperature", settings, "K"))
        return settings

    def configure_field_stability(
        self,
        tolerance_t: float,
        stable_samples: int,
        poll_interval_s: float,
    ) -> StabilitySettings:
        settings = self._validate_stability_settings(
            quantity="field",
            tolerance=tolerance_t,
            minimum_tolerance=self.MIN_FIELD_TOLERANCE_T,
            maximum_tolerance=self.MAX_FIELD_TOLERANCE_T,
            tolerance_unit="T",
            stable_samples=stable_samples,
            poll_interval_s=poll_interval_s,
        )
        with self._settings_lock:
            self._field_stability = settings
        self.sig_status.emit(self._settings_status("Field", settings, "T"))
        return settings

    def set_B(self, target_t: float) -> float:
        target = self._execute(
            "Set magnetic field", self.hardware.set_field_t, target_t
        )
        self.sig_status.emit(f"Magnetic-field control started at {target:.6g} T")
        return target

    def set_B_stable(self, target_t: float) -> float:
        settings = self.field_stability
        target = self.set_B(target_t)
        return self._wait_for_stability(
            quantity="field",
            target=target,
            tolerance=settings.tolerance,
            stable_samples=settings.stable_samples,
            poll_interval_s=settings.poll_interval_s,
            timeout_s=self.FIELD_TIMEOUT_S,
            reader=self._read_field_with_state,
            ready_probe=self._field_sequence_finished,
            unit="T",
        )

    def connect_device(self, address: str) -> bool:
        connected = self._execute("Connect", self.hardware.connect, address)
        self.is_connected = bool(connected)
        self._stop_requested.clear()
        self.sig_connected.emit(self.is_connected, self.hardware.address)
        self.sig_status.emit(f"Connected to {self.hardware.address}")
        return self.is_connected

    def disconnect_device(self) -> bool:
        self.request_stop()
        try:
            disconnected = self._execute("Disconnect", self.hardware.disconnect)
        finally:
            self.is_connected = self.hardware.connected
            self.sig_connected.emit(self.is_connected, self.hardware.address)
        self.sig_status.emit("Disconnected")
        return bool(disconnected)

    def start_scan(self) -> None:
        self._stop_requested.clear()
        self.monitor_enabled = True

    def stop_scan(self) -> None:
        self.monitor_enabled = False

    def resume_monitoring(self) -> None:
        self._stop_requested.clear()
        self.monitor_enabled = True

    def request_stop(self) -> bool:
        self._stop_requested.set()
        self.sig_status.emit(
            "Stable-wait stop requested; the controller target remains active"
        )
        return True

    def close(self) -> bool:
        self.monitor_enabled = False
        self.request_stop()
        if self.isRunning() and not self.wait(15_000):
            return False
        if self.hardware.connected:
            self.disconnect_device()
        return True

    def start_job(self, job_name: str, value: Any = None) -> bool:
        with self._job_lock:
            if self.isRunning() or self._pending_job is not None:
                return False
            if job_name in {"set_T_stable", "set_B_stable"}:
                self._stop_requested.clear()
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
            "connect": lambda: self.connect_device(str(value)),
            "disconnect": self.disconnect_device,
            "read_live": self._read_live,
            "set_T": lambda: self.set_T(value),
            "set_T_stable": lambda: self.set_T_stable(value),
            "set_B": lambda: self.set_B(value),
            "set_B_stable": lambda: self.set_B_stable(value),
        }
        action = actions.get(job_name)
        if action is None:
            self.sig_error.emit(f"Unknown attoDRY job '{job_name}'")
            return
        try:
            action()
        except Exception as exc:
            self.sig_error.emit(
                f"attoDRY job {job_name} stopped: {type(exc).__name__}: {exc}"
            )

    def _read_live(self) -> None:
        self.get_T()
        self._read_field_with_state()

    def _read_field_with_state(self) -> float:
        value = self.get_B()
        state = self._execute("Read magnetic-field state", self.hardware.read_field_state)
        self.sig_field_state.emit(state)
        return value

    def _field_sequence_finished(self) -> bool:
        if self._execute("Read quench state", self.hardware.magnet_quenched):
            message = "attoDRY magnet entered quench state during field wait"
            self.sig_error.emit(message)
            self.sig_status.emit(message)
            raise RuntimeError(message)
        return not self._execute(
            "Read field-control status", self.hardware.field_control_active
        )

    def _wait_for_stability(
        self,
        *,
        quantity: str,
        target: float,
        tolerance: float,
        stable_samples: int,
        poll_interval_s: float,
        timeout_s: float,
        reader: Callable[[], float],
        unit: str,
        ready_probe: Callable[[], bool] | None = None,
    ) -> float:
        self.sig_waiting.emit(True, quantity)
        self.sig_status.emit(
            f"Waiting for {quantity} within {tolerance:g} {unit} for "
            f"{stable_samples} consecutive readings every {poll_interval_s:g} s"
        )
        started = time.monotonic()
        consecutive = 0
        try:
            last_value = reader()
            while True:
                if self._stop_requested.wait(poll_interval_s):
                    last_value = reader()
                    self.sig_status.emit(
                        f"{quantity.capitalize()} stable wait stopped at "
                        f"{last_value:.6g} {unit}; target {target:.6g} {unit} remains active"
                    )
                    return last_value

                last_value = reader()
                controller_ready = ready_probe is None or ready_probe()
                if abs(last_value - target) <= tolerance and controller_ready:
                    consecutive += 1
                    if consecutive >= stable_samples:
                        self.sig_status.emit(
                            f"{quantity.capitalize()} stable at {last_value:.6g} {unit}"
                        )
                        return last_value
                else:
                    consecutive = 0

                if time.monotonic() - started >= timeout_s:
                    message = (
                        f"{quantity} did not stabilize at {target:.6g} {unit} "
                        f"within {timeout_s / 60:.0f} minutes; last reading was "
                        f"{last_value:.6g} {unit}"
                    )
                    self.sig_error.emit(message)
                    self.sig_status.emit(message)
                    raise TimeoutError(message)
        finally:
            self.sig_waiting.emit(False, quantity)

    @classmethod
    def _validate_stability_settings(
        cls,
        *,
        quantity: str,
        tolerance: float,
        minimum_tolerance: float,
        maximum_tolerance: float,
        tolerance_unit: str,
        stable_samples: int,
        poll_interval_s: float,
    ) -> StabilitySettings:
        numeric_tolerance = float(tolerance)
        if not math.isfinite(numeric_tolerance) or not (
            minimum_tolerance <= numeric_tolerance <= maximum_tolerance
        ):
            raise ValueError(
                f"{quantity} stability tolerance must be finite and between "
                f"{minimum_tolerance:g} and {maximum_tolerance:g} {tolerance_unit}"
            )

        if isinstance(stable_samples, bool):
            raise ValueError("stable-reading count must be an integer")
        try:
            numeric_samples = int(stable_samples)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("stable-reading count must be an integer") from exc
        if numeric_samples != stable_samples or not (
            cls.MIN_STABLE_SAMPLES <= numeric_samples <= cls.MAX_STABLE_SAMPLES
        ):
            raise ValueError(
                "stable-reading count must be an integer between "
                f"{cls.MIN_STABLE_SAMPLES} and {cls.MAX_STABLE_SAMPLES}"
            )

        numeric_interval = float(poll_interval_s)
        if not math.isfinite(numeric_interval) or not (
            cls.MIN_POLL_INTERVAL_S
            <= numeric_interval
            <= cls.MAX_POLL_INTERVAL_S
        ):
            raise ValueError(
                "stable-reading interval must be finite and between "
                f"{cls.MIN_POLL_INTERVAL_S:g} and "
                f"{cls.MAX_POLL_INTERVAL_S:g} seconds"
            )
        return StabilitySettings(
            numeric_tolerance,
            numeric_samples,
            numeric_interval,
        )

    @staticmethod
    def _settings_status(
        quantity: str,
        settings: StabilitySettings,
        unit: str,
    ) -> str:
        return (
            f"{quantity} stability set to ±{settings.tolerance:g} {unit}, "
            f"{settings.stable_samples} consecutive readings every "
            f"{settings.poll_interval_s:g} s for future waits"
        )

    def _execute(
        self,
        description: str,
        operation: Callable[..., Any],
        *args: Any,
    ) -> Any:
        try:
            return operation(*args)
        except Exception as exc:
            message = f"{description} failed: {type(exc).__name__}: {exc}"
            self.sig_error.emit(message)
            self.sig_status.emit(message)
            raise
