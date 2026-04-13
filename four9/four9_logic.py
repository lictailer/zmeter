from __future__ import annotations

import math
import time
from collections import deque
from typing import Deque, List, Optional

from PyQt6 import QtCore

try:
    from .four9_hardware import Four9Hardware
except ImportError:
    from four9_hardware import Four9Hardware


class Four9Logic(QtCore.QThread):
    """Logic layer for Four9 cryostat control.

    Scan-facing getters:
    - get_ch00_temp() ... get_ch05_temp()
    """

    sig_status = QtCore.pyqtSignal(object)
    sig_is_connected = QtCore.pyqtSignal(object)
    sig_target_temperature = QtCore.pyqtSignal(object)     # [channel, target]
    sig_temperatures = QtCore.pyqtSignal(object)           # [t0..t5]
    sig_heater_powers = QtCore.pyqtSignal(object)          # [p0..p5]
    sig_stability = QtCore.pyqtSignal(object)              # dict

    def __init__(self):
        super().__init__()

        self.job: str = ""
        self.reject_signal: bool = False

        self.hardware = Four9Hardware()
        self.is_connected: bool = False

        # Connection settings (configured in main layer).
        self.base_url: str = self.hardware.base_url
        self.port: int = self.hardware.port

        # Temperature control settings.
        self.setpoint_target_temperature: float = 300.0
        self.setpoint_target_channel: int = 2
        self.temperature_read_channel: int = 2

        # Stability settings.
        self.stability_poll_interval_s: float = 0.5
        self.stability_window_points: int = 120  # 2 min at 0.5 s interval
        self.stable_temperature_tolerance_k: float = 0.1
        self.stable_deviation_threshold_k: float = 0.1
        self.stable_wait_timeout_s: int = 60 * 60
        self.post_stable_wait_s: int = 60
        self.stable_wait_stop: bool = False

        # Cached values for UI use.
        self.latest_temperatures: List[float] = [float("nan")] * 6
        self.latest_heater_powers: List[float] = [float("nan")] * 6
        self.latest_temperature_deviation_k: float = float("nan")

    # ---------------- lifecycle ----------------
    def connect(self):
        self.is_connected = self.hardware.connect_hardware(self.base_url, self.port)
        self.sig_is_connected.emit(self.is_connected)
        if self.is_connected:
            self.sig_status.emit(
                f"Connected to Four9 at {self.base_url}:{self.port}."
            )
        else:
            self.sig_status.emit(
                f"Connection failed to Four9 at {self.base_url}:{self.port}."
            )

    def disconnect(self):
        if self.is_connected:
            self.hardware.disconnect()
            self.is_connected = False
            self.sig_is_connected.emit(self.is_connected)
            self.sig_status.emit("Disconnected.")
        else:
            self.sig_is_connected.emit(self.is_connected)
            self.sig_status.emit("Already disconnected.")

    # ---------------- channel config ----------------
    def set_target_channel(self, channel: int):
        self.setpoint_target_channel = self._validate_channel(channel)

    def set_read_channel(self, channel: int):
        self.temperature_read_channel = self._validate_channel(channel)

    # ---------------- reads ----------------
    def read_temperature(self, channel: int) -> float:
        self._ensure_connected()
        channel = self._validate_channel(channel)
        value = self.hardware.read_temperature(channel)
        self.latest_temperatures[channel] = value
        return value

    def read_all_temperatures(self) -> List[float]:
        self._ensure_connected()
        values = self.hardware.read_all_temperatures()
        self.latest_temperatures = values
        self.sig_temperatures.emit(values)
        return values

    def read_heater_power(self, channel: int) -> float:
        self._ensure_connected()
        channel = self._validate_channel(channel)
        value = self.hardware.read_heater_power(channel)
        self.latest_heater_powers[channel] = value
        return value

    def read_all_heater_powers(self) -> List[float]:
        self._ensure_connected()
        values = self.hardware.read_all_heater_powers()
        self.latest_heater_powers = values
        self.sig_heater_powers.emit(values)
        return values

    # ---------------- set temperature ----------------
    def set_temperature(
        self,
        target_temperature: float,
        target_channel: Optional[int] = None,
        read_channel: Optional[int] = None,
    ) -> None:
        """Set target temperature and return immediately."""
        self._ensure_connected()

        if target_channel is not None:
            self.set_target_channel(target_channel)
        if read_channel is not None:
            self.set_read_channel(read_channel)

        self.hardware.set_target_temperature(
            self.setpoint_target_channel, float(target_temperature)
        )
        self.setpoint_target_temperature = float(target_temperature)
        self.sig_target_temperature.emit(
            [self.setpoint_target_channel, self.setpoint_target_temperature]
        )
        self.sig_status.emit(
            "Set target temperature: "
            f"CH{self.setpoint_target_channel:02d} -> "
            f"{self.setpoint_target_temperature:.3f} K "
            f"(read channel CH{self.temperature_read_channel:02d})."
        )

    def abort_set_temperature_to_stable(self):
        self.stable_wait_stop = True

    def set_temperature_to_stable(
        self,
        target_temperature: float,
        target_channel: Optional[int] = None,
        read_channel: Optional[int] = None,
    ) -> bool:
        """Set target temperature and wait until stable criteria are met."""
        self._ensure_connected()
        self.stable_wait_stop = False

        self.set_temperature(
            target_temperature=target_temperature,
            target_channel=target_channel,
            read_channel=read_channel,
        )

        start_time = time.monotonic()
        stable_since: Optional[float] = None
        history: Deque[float] = deque(maxlen=self.stability_window_points)

        self.sig_status.emit(
            "Waiting for stability on "
            f"CH{self.temperature_read_channel:02d} "
            f"(tol={self.stable_temperature_tolerance_k:.3f} K, "
            f"dev<{self.stable_deviation_threshold_k:.3f} K, "
            f"timeout={self.stable_wait_timeout_s}s)."
        )

        while True:
            now = time.monotonic()

            if self.stable_wait_stop:
                self.stable_wait_stop = False
                self.sig_status.emit("set_temperature_to_stable aborted by user.")
                return False

            elapsed_s = now - start_time
            if elapsed_s >= self.stable_wait_timeout_s:
                self.sig_status.emit(
                    "set_temperature_to_stable timeout "
                    f"after {int(self.stable_wait_timeout_s)} s."
                )
                return False

            temperatures = self.read_all_temperatures()
            current_temp = temperatures[self.temperature_read_channel]

            if math.isfinite(current_temp):
                history.append(current_temp)

            deviation = self._compute_deviation(history)
            self.latest_temperature_deviation_k = deviation

            abs_error = (
                abs(current_temp - self.setpoint_target_temperature)
                if math.isfinite(current_temp)
                else float("inf")
            )
            near_target = abs_error <= self.stable_temperature_tolerance_k
            deviation_ok = deviation <= self.stable_deviation_threshold_k
            stable_now = near_target and deviation_ok

            self.sig_stability.emit(
                {
                    "channel": self.temperature_read_channel,
                    "target_k": self.setpoint_target_temperature,
                    "current_k": current_temp,
                    "abs_error_k": abs_error,
                    "deviation_k": deviation,
                    "points": len(history),
                    "stable": stable_now,
                }
            )

            if stable_now:
                if stable_since is None:
                    stable_since = now
                    self.sig_status.emit(
                        "Stability condition reached. "
                        f"Starting post-stable wait ({self.post_stable_wait_s}s)."
                    )
                elif (now - stable_since) >= self.post_stable_wait_s:
                    self.sig_status.emit("Stable wait complete.")
                    return True
            else:
                if stable_since is not None:
                    self.sig_status.emit(
                        "Stability lost during post-stable wait; timer reset."
                    )
                stable_since = None

            QtCore.QThread.msleep(int(self.stability_poll_interval_s * 1000))

    # ---------------- thread entry ----------------
    def run(self):
        if self.reject_signal:
            return

        try:
            if self.job == "connect":
                self.connect()
            elif self.job == "disconnect":
                self.disconnect()
            elif self.job == "read_all_temperatures":
                self.read_all_temperatures()
            elif self.job == "read_all_heater_powers":
                self.read_all_heater_powers()
            elif self.job == "set_temperature":
                self.set_temperature(self.setpoint_target_temperature)
            elif self.job == "set_temperature_to_stable":
                self.set_temperature_to_stable(self.setpoint_target_temperature)
        except Exception as exc:
            self.sig_status.emit(f"Four9 logic error: {exc}")

    # ---------------- helpers ----------------
    def _ensure_connected(self):
        if not self.is_connected:
            raise RuntimeError("Four9 is not connected. Call connect() first.")

    @staticmethod
    def _validate_channel(channel: int) -> int:
        channel = int(channel)
        if channel < 0 or channel > 5:
            raise ValueError(f"Channel must be in [0, 5], got {channel}.")
        return channel

    @staticmethod
    def _compute_deviation(history: Deque[float]) -> float:
        if len(history) == 0:
            return float("inf")
        values = [v for v in history if math.isfinite(v)]
        if len(values) == 0:
            return float("inf")
        return max(values) - min(values)


def _make_get_temp(index: int):
    def getter(self: Four9Logic) -> float:
        return self.read_temperature(index)

    getter.__name__ = f"get_ch{index:02d}_temp"
    return getter


def _make_read_temp(index: int):
    def reader(self: Four9Logic) -> float:
        return self.read_temperature(index)

    reader.__name__ = f"read_ch{index:02d}_temp"
    return reader


def _make_read_heater_power(index: int):
    def reader(self: Four9Logic) -> float:
        return self.read_heater_power(index)

    reader.__name__ = f"read_ch{index:02d}_heater_power"
    return reader


for _i in range(6):
    setattr(Four9Logic, f"get_ch{_i:02d}_temp", _make_get_temp(_i))
    setattr(Four9Logic, f"read_ch{_i:02d}_temp", _make_read_temp(_i))
    setattr(Four9Logic, f"read_ch{_i:02d}_heater_power", _make_read_heater_power(_i))


if __name__ == "__main__":
    logic = Four9Logic()
    logic.base_url = "http://localhost"
    logic.port = 4949
    logic.connect()
    if logic.is_connected:
        print("Temperatures:", logic.read_all_temperatures())
        print("Heater powers:", logic.read_all_heater_powers())
        logic.disconnect()
