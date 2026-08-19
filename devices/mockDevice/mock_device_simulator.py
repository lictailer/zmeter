from __future__ import annotations

import math
import random
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime


class MockDeviceError(RuntimeError):
    """Base error raised by the simulated instrument."""


class MockDeviceConnectionError(MockDeviceError):
    """Raised when an operation requires an active connection."""


class MockDeviceCommandError(MockDeviceError):
    """Raised by an enabled simulated command fault."""


class MockDeviceFailAfterError(MockDeviceCommandError):
    """Raised when the one-shot fail-after fault reaches zero."""


class MockDeviceRangeError(MockDeviceError):
    """Raised when a setter value is invalid or outside the enabled limits."""


class MockDeviceSimulator:
    CHANNEL_MIN = -10.0
    CHANNEL_MAX = 10.0
    READ_NOISE_SIGMA = 0.001
    RANDOM_MEAN = 0.0
    RANDOM_SIGMA = 1.0
    RAMP_STEP = 0.01
    RAMP_INTERVAL_SECONDS = 0.001
    MAX_LOG_ENTRIES = 500

    def __init__(self, random_seed: int = 12345):
        self._lock = threading.RLock()
        self._ramp_stop = threading.Event()
        self._measurement_random = random.Random(random_seed)
        self._fault_random = random.Random(random_seed + 1)
        self._command_log = deque(maxlen=self.MAX_LOG_ENTRIES)
        self._log_sequence = 0
        self.connected = False
        self.address = ""
        self._reset_state(clear_log=False)

    @property
    def command_log(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._command_log)

    @property
    def ramp_active(self) -> bool:
        with self._lock:
            return self._ramp_active

    def connect(self, address: str) -> str:
        normalized_address = str(address).strip()
        if not normalized_address:
            raise MockDeviceConnectionError("Mock device address cannot be empty.")
        with self._lock:
            self.address = normalized_address
            self.connected = True
            self._ramp_stop.clear()
            self._log(f"CONNECT address={normalized_address}")
        return normalized_address

    def disconnect(self) -> None:
        self.force_stop()
        with self._lock:
            if not self.connected:
                return
            self._log(f"DISCONNECT address={self.address}")
            self.connected = False

    def reset(self) -> None:
        with self._lock:
            self._require_connected()
            self._reset_state(clear_log=True)
            self._log("RESET completed")

    def start_scan(self) -> None:
        with self._lock:
            self._require_connected()
            self._ramp_stop.clear()
            self._log("START_SCAN")

    def stop_scan(self) -> None:
        with self._lock:
            self._require_connected()
            self._log("STOP_SCAN")

    def force_stop(self) -> bool:
        with self._lock:
            if not self._ramp_active:
                return False
            self._ramp_stop.set()
            self._log("FORCE_STOP requested")
            return True

    def set_channel(self, channel: str, value: float) -> float:
        channel = self._normalize_channel(channel)
        try:
            numeric_value = self._begin_scan_operation(
                f"SET_CHANNEL_{channel}", value, is_setter=True
            )
            with self._lock:
                self._channel_values[channel] = numeric_value
                self._last_set_values[channel] = numeric_value
                self._log(f"SET_CHANNEL_{channel} value={numeric_value:.9g}")
            return numeric_value
        except Exception as exc:
            self._log_failure(f"SET_CHANNEL_{channel}", exc)
            raise

    def read_channel(self, channel: str) -> float:
        channel = self._normalize_channel(channel)
        try:
            self._begin_scan_operation(f"GET_CHANNEL_{channel}")
            with self._lock:
                value = self._channel_values[channel] + self._measurement_random.gauss(
                    0.0, self.READ_NOISE_SIGMA
                )
                self._last_read_values[channel] = value
                self._log(f"GET_CHANNEL_{channel} result={value:.9g}")
            return value
        except Exception as exc:
            self._log_failure(f"GET_CHANNEL_{channel}", exc)
            raise

    def read_random_channel(self) -> float:
        try:
            self._begin_scan_operation("GET_RANDOM_CHANNEL")
            with self._lock:
                value = self._measurement_random.gauss(
                    self.RANDOM_MEAN, self.RANDOM_SIGMA
                )
                self._last_random_value = value
                self._log(f"GET_RANDOM_CHANNEL result={value:.9g}")
            return value
        except Exception as exc:
            self._log_failure("GET_RANDOM_CHANNEL", exc)
            raise

    def ramp_channel(
        self,
        channel: str,
        target: float,
        progress_callback: Callable[[float], None] | None = None,
    ) -> tuple[float, bool]:
        channel = self._normalize_channel(channel)
        operation = f"RAMP_CHANNEL_{channel}"
        try:
            numeric_target = self._begin_scan_operation(
                operation, target, is_setter=True
            )
            with self._lock:
                start = self._channel_values[channel]
                self._ramp_stop.clear()
                self._ramp_active = True
                self._log(
                    f"{operation} start={start:.9g} target={numeric_target:.9g}"
                )

            current = start
            aborted = False
            try:
                while not math.isclose(current, numeric_target, abs_tol=1e-12):
                    if self._ramp_stop.wait(self.RAMP_INTERVAL_SECONDS):
                        aborted = True
                        break

                    remaining = numeric_target - current
                    step = math.copysign(min(abs(remaining), self.RAMP_STEP), remaining)
                    current = float(current + step)
                    if math.isclose(current, numeric_target, abs_tol=1e-12):
                        current = numeric_target

                    with self._lock:
                        if not self.connected:
                            raise MockDeviceConnectionError(
                                "Mock device disconnected during ramp."
                            )
                        self._channel_values[channel] = current
                        self._last_set_values[channel] = current
                    if progress_callback is not None:
                        progress_callback(current)

            finally:
                with self._lock:
                    self._ramp_active = False
                    self._ramp_stop.clear()

            with self._lock:
                outcome = "aborted" if aborted else "completed"
                self._log(f"{operation} {outcome} value={current:.9g}")
            return current, aborted
        except Exception as exc:
            with self._lock:
                self._ramp_active = False
                self._ramp_stop.clear()
            self._log_failure(operation, exc)
            raise

    def activate_fail_after(self, command_count: int) -> None:
        count = int(command_count)
        if count <= 0:
            raise ValueError("Fail-after command count must be greater than zero.")
        with self._lock:
            self._fail_after_remaining = count
            self._log(f"FAULT_FAIL_AFTER enabled count={count}")

    def stop_fail_after(self) -> None:
        with self._lock:
            self._fail_after_remaining = None
            self._log("FAULT_FAIL_AFTER disabled")

    def activate_random_failure(self, probability: float) -> None:
        probability = float(probability)
        if not 0.0 <= probability <= 1.0:
            raise ValueError("Random failure probability must be between 0 and 1.")
        with self._lock:
            self._random_failure_probability = probability
            self._log(f"FAULT_RANDOM enabled probability={probability:.6g}")

    def stop_random_failure(self) -> None:
        with self._lock:
            self._random_failure_probability = 0.0
            self._log("FAULT_RANDOM disabled")

    def activate_range_rejection(self) -> None:
        with self._lock:
            self._range_rejection_enabled = True
            self._log(
                "FAULT_RANGE_REJECTION enabled "
                f"limits=[{self.CHANNEL_MIN:.9g}, {self.CHANNEL_MAX:.9g}]"
            )

    def stop_range_rejection(self) -> None:
        with self._lock:
            self._range_rejection_enabled = False
            self._log("FAULT_RANGE_REJECTION disabled")

    def _begin_scan_operation(
        self,
        operation: str,
        value: float | None = None,
        *,
        is_setter: bool = False,
    ) -> float | None:
        with self._lock:
            self._require_connected()
            self._operation_count += 1

            if self._fail_after_remaining is not None:
                self._fail_after_remaining -= 1
                if self._fail_after_remaining == 0:
                    self._fail_after_remaining = None
                    raise MockDeviceFailAfterError(
                        f"Simulated fail-after fault during {operation}."
                    )

            if (
                self._random_failure_probability > 0.0
                and self._fault_random.random() < self._random_failure_probability
            ):
                raise MockDeviceCommandError(
                    f"Simulated random failure during {operation}."
                )

            if not is_setter:
                return None

            numeric_value = float(value)
            if not math.isfinite(numeric_value):
                raise MockDeviceRangeError("Setter value must be finite.")
            if self._range_rejection_enabled and not (
                self.CHANNEL_MIN <= numeric_value <= self.CHANNEL_MAX
            ):
                raise MockDeviceRangeError(
                    f"Setter value {numeric_value:.9g} is outside "
                    f"[{self.CHANNEL_MIN:.9g}, {self.CHANNEL_MAX:.9g}]."
                )
            return numeric_value

    def _require_connected(self) -> None:
        if not self.connected:
            raise MockDeviceConnectionError("Mock device is not connected.")

    @staticmethod
    def _normalize_channel(channel: str) -> str:
        normalized = str(channel).upper()
        if normalized not in {"A", "B"}:
            raise ValueError(f"Unknown mock channel '{channel}'.")
        return normalized

    def _reset_state(self, *, clear_log: bool) -> None:
        self._channel_values = {"A": 0.0, "B": 0.0}
        self._last_set_values = {"A": 0.0, "B": 0.0}
        self._last_read_values = {"A": None, "B": None}
        self._last_random_value = None
        self._operation_count = 0
        self._fail_after_remaining = None
        self._random_failure_probability = 0.0
        self._range_rejection_enabled = False
        self._ramp_active = False
        self._ramp_stop.clear()
        if clear_log:
            self._command_log.clear()
            self._log_sequence = 0

    def _log_failure(self, operation: str, error: Exception) -> None:
        with self._lock:
            self._log(f"{operation} failed: {type(error).__name__}: {error}")

    def _log(self, message: str) -> None:
        self._log_sequence += 1
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self._command_log.append(f"{self._log_sequence:05d} {timestamp} {message}")
