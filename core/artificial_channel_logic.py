import math
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Callable

import numpy as np
from PyQt6 import QtCore


class ArtificialChannelLogic(QtCore.QObject):
    sig_state_changed = QtCore.pyqtSignal(object)
    sig_target_changed = QtCore.pyqtSignal(object)
    sig_log = QtCore.pyqtSignal(str, str)
    RAMP_DIVISOR = 100
    RAMP_INTER_STEP_DELAY_S = 0.02

    DEFAULT_ORIGINAL_CHANNEL_X_NAME = "nidaq_0_AO0"
    DEFAULT_ORIGINAL_CHANNEL_Y_NAME = "nidaq_0_AO1"
    DEFAULT_ARTIFICIAL_CHANNEL_X_NAME = "n"
    DEFAULT_ARTIFICIAL_CHANNEL_Y_NAME = "E"

    # Three one-to-one coordinate pairs: ((original_x, original_y), (artificial_x, artificial_y))
    default_coordinate_pairs = (
        ((0.0, 0.0), (0.0, 0.0)),
        ((1.0, 0.0), (1.0, 1.0)),
        ((0.0, 1.0), (1.0, -1.0)),
    )
    _CONFIGURATION_STATE_ATTRIBUTES = (
        "original_channel_x_name",
        "original_channel_y_name",
        "artificial_channel_x_name",
        "artificial_channel_y_name",
        "original_channels",
        "artificial_channels",
        "original_channel_limits",
        "artificial_channel_limits",
        "coordinate_pairs",
        "_original_to_artificial_matrix",
        "_original_to_artificial_offset",
        "_artificial_to_original_matrix",
        "equations",
        "inverse_equations",
        "_commanded_artificial_values",
        "_scan_target_artificial_values",
        "_skip_next_scan_read",
        "state",
    )

    def __init__(
        self,
        write_channel: Callable[[float, str], None],
        read_channel: Callable[[str], float],
        parent: QtCore.QObject | None = None,
        original_channel_x_name: str = DEFAULT_ORIGINAL_CHANNEL_X_NAME,
        original_channel_y_name: str = DEFAULT_ORIGINAL_CHANNEL_Y_NAME,
        artificial_channel_x_name: str = DEFAULT_ARTIFICIAL_CHANNEL_X_NAME,
        artificial_channel_y_name: str = DEFAULT_ARTIFICIAL_CHANNEL_Y_NAME,
        coordinate_pairs: tuple[
            tuple[tuple[float, float], tuple[float, float]],
            tuple[tuple[float, float], tuple[float, float]],
            tuple[tuple[float, float], tuple[float, float]],
        ] | None = None,
        original_channel_x_limits: tuple[float, float] = (-10.0, 10.0),
        original_channel_y_limits: tuple[float, float] = (-10.0, 10.0),
        should_abort_ramp: Callable[[], bool] | None = None,
        resolve_device_label: Callable[[str], str] | None = None,
    ):
        super().__init__(parent)
        self._write_channel = write_channel
        self._read_channel = read_channel
        self._should_abort_ramp_cb = should_abort_ramp
        self._resolve_device_label_cb = resolve_device_label

        self.original_channel_x_name = original_channel_x_name
        self.original_channel_y_name = original_channel_y_name
        self.artificial_channel_x_name = artificial_channel_x_name
        self.artificial_channel_y_name = artificial_channel_y_name

        self.original_channels = (
            self.original_channel_x_name,
            self.original_channel_y_name,
        )
        self.artificial_channels = (
            self.artificial_channel_x_name,
            self.artificial_channel_y_name,
        )

        self.original_channel_limits = {
            self.original_channel_x_name: self._normalize_limit(
                original_channel_x_limits, self.original_channel_x_name
            ),
            self.original_channel_y_name: self._normalize_limit(
                original_channel_y_limits, self.original_channel_y_name
            ),
        }

        self._commanded_artificial_values = {
            self.artificial_channel_x_name: 0.0,
            self.artificial_channel_y_name: 0.0,
        }
        self._scan_target_artificial_values = dict(
            self._commanded_artificial_values
        )
        self._skip_next_scan_read = False

        if coordinate_pairs is None:
            coordinate_pairs = self.default_coordinate_pairs

        self.construct_coordinate_relation(coordinate_pairs)
        self.state = self._make_state("Unknown", "Unknown", "Unknown", "Unknown")

    def apply_configuration(
        self,
        original_channel_x_name: str,
        original_channel_y_name: str,
        artificial_channel_x_name: str,
        artificial_channel_y_name: str,
        coordinate_pairs: tuple[
            tuple[tuple[float, float], tuple[float, float]],
            tuple[tuple[float, float], tuple[float, float]],
            tuple[tuple[float, float], tuple[float, float]],
        ],
        original_channel_x_limits: tuple[float, float],
        original_channel_y_limits: tuple[float, float],
        *,
        emit_signals: bool = True,
    ) -> dict[str, Any]:
        self.original_channel_x_name = original_channel_x_name
        self.original_channel_y_name = original_channel_y_name
        self.artificial_channel_x_name = artificial_channel_x_name
        self.artificial_channel_y_name = artificial_channel_y_name

        self.original_channels = (
            self.original_channel_x_name,
            self.original_channel_y_name,
        )
        self.artificial_channels = (
            self.artificial_channel_x_name,
            self.artificial_channel_y_name,
        )

        self.original_channel_limits = {
            self.original_channel_x_name: self._normalize_limit(
                original_channel_x_limits, self.original_channel_x_name
            ),
            self.original_channel_y_name: self._normalize_limit(
                original_channel_y_limits, self.original_channel_y_name
            ),
        }
        self._commanded_artificial_values = {
            self.artificial_channel_x_name: 0.0,
            self.artificial_channel_y_name: 0.0,
        }
        self._scan_target_artificial_values = dict(
            self._commanded_artificial_values
        )
        self._skip_next_scan_read = False

        self.construct_coordinate_relation(coordinate_pairs)
        self.state = self._make_state("Unknown", "Unknown", "Unknown", "Unknown")
        if emit_signals:
            self.emit_configuration_state(
                target_values={
                    self.artificial_channel_x_name: "Unknown",
                    self.artificial_channel_y_name: "Unknown",
                }
            )
        return dict(self.state)

    def _emit_log(self, level: str, message: str) -> None:
        print(message)
        self.sig_log.emit(str(level).upper(), str(message))

    def capture_configuration_state(self) -> dict[str, Any]:
        """Return a detached checkpoint for an atomic UI configuration edit."""

        return {
            attribute: deepcopy(getattr(self, attribute))
            for attribute in self._CONFIGURATION_STATE_ATTRIBUTES
        }

    def restore_configuration_state(
        self,
        checkpoint: dict[str, Any],
        *,
        emit_signals: bool = True,
    ) -> None:
        """Restore a checkpoint without issuing any device read or write."""

        for attribute in self._CONFIGURATION_STATE_ATTRIBUTES:
            setattr(self, attribute, deepcopy(checkpoint[attribute]))
        if emit_signals:
            self.emit_configuration_state()

    def emit_configuration_state(self, *, target_values=None) -> None:
        """Publish the current target and state after a committed config edit."""

        if target_values is None:
            target_values = self._scan_target_artificial_values
        self.sig_target_changed.emit(dict(target_values))
        self.sig_state_changed.emit(dict(self.state))

    def has_artificial_channel(self, channel_name: str) -> bool:
        return channel_name in self.artificial_channels

    def has_original_channel(self, channel_name: str) -> bool:
        return channel_name in self.original_channels

    def is_supported_channel(self, channel_name: str) -> bool:
        return self.has_artificial_channel(channel_name) or self.has_original_channel(
            channel_name
        )

    def construct_coordinate_relation(
        self,
        coordinate_pairs: tuple[
            tuple[tuple[float, float], tuple[float, float]],
            tuple[tuple[float, float], tuple[float, float]],
            tuple[tuple[float, float], tuple[float, float]],
        ],
    ) -> dict[str, str]:
        """
        Build an affine original->artificial relation from three one-to-one pairs.

        coordinate_pairs format:
            (
                ((original_x1, original_y1), (artificial_x1, artificial_y1)),
                ((original_x2, original_y2), (artificial_x2, artificial_y2)),
                ((original_x3, original_y3), (artificial_x3, artificial_y3)),
            )
        """
        if len(coordinate_pairs) != 3:
            raise ValueError(
                "construct_coordinate_relation expects exactly 3 coordinate pairs."
            )
        self.coordinate_pairs = tuple(coordinate_pairs)

        original_points = np.asarray([pair[0] for pair in coordinate_pairs], dtype=float)
        artificial_points = np.asarray([pair[1] for pair in coordinate_pairs], dtype=float)

        if original_points.shape != (3, 2) or artificial_points.shape != (3, 2):
            raise ValueError(
                "Each coordinate pair must be ((original_x, original_y), (artificial_x, artificial_y))."
            )

        design = np.column_stack((original_points, np.ones(3, dtype=float)))
        try:
            artificial_x_coeff = np.linalg.solve(design, artificial_points[:, 0])
            artificial_y_coeff = np.linalg.solve(design, artificial_points[:, 1])
        except np.linalg.LinAlgError as exc:
            raise ValueError(
                "Cannot construct relation: original reference points must be non-collinear."
            ) from exc

        self._original_to_artificial_matrix = np.array(
            [
                [artificial_x_coeff[0], artificial_x_coeff[1]],
                [artificial_y_coeff[0], artificial_y_coeff[1]],
            ],
            dtype=float,
        )
        self._original_to_artificial_offset = np.array(
            [artificial_x_coeff[2], artificial_y_coeff[2]], dtype=float
        )

        det = float(np.linalg.det(self._original_to_artificial_matrix))
        if np.isclose(det, 0.0):
            raise ValueError(
                "Constructed original->artificial transform is singular; cannot invert."
            )

        self._artificial_to_original_matrix = np.linalg.inv(
            self._original_to_artificial_matrix
        )

        self.equations = {
            self.artificial_channel_x_name: self._format_linear_equation(
                lhs_name=self.artificial_channel_x_name,
                rhs_x_name=self.original_channel_x_name,
                rhs_y_name=self.original_channel_y_name,
                rhs_x_coeff=self._original_to_artificial_matrix[0, 0],
                rhs_y_coeff=self._original_to_artificial_matrix[0, 1],
                bias=self._original_to_artificial_offset[0],
            ),
            self.artificial_channel_y_name: self._format_linear_equation(
                lhs_name=self.artificial_channel_y_name,
                rhs_x_name=self.original_channel_x_name,
                rhs_y_name=self.original_channel_y_name,
                rhs_x_coeff=self._original_to_artificial_matrix[1, 0],
                rhs_y_coeff=self._original_to_artificial_matrix[1, 1],
                bias=self._original_to_artificial_offset[1],
            ),
        }

        inverse_offset = -self._artificial_to_original_matrix @ self._original_to_artificial_offset
        self.inverse_equations = {
            self.original_channel_x_name: self._format_linear_equation(
                lhs_name=self.original_channel_x_name,
                rhs_x_name=self.artificial_channel_x_name,
                rhs_y_name=self.artificial_channel_y_name,
                rhs_x_coeff=self._artificial_to_original_matrix[0, 0],
                rhs_y_coeff=self._artificial_to_original_matrix[0, 1],
                bias=float(inverse_offset[0]),
            ),
            self.original_channel_y_name: self._format_linear_equation(
                lhs_name=self.original_channel_y_name,
                rhs_x_name=self.artificial_channel_x_name,
                rhs_y_name=self.artificial_channel_y_name,
                rhs_x_coeff=self._artificial_to_original_matrix[1, 0],
                rhs_y_coeff=self._artificial_to_original_matrix[1, 1],
                bias=float(inverse_offset[1]),
            ),
        }

        self._update_artificial_limits()
        return dict(self.equations)

    def set_artificial_channel_values(
        self,
        artificial_channel_x_value: float,
        artificial_channel_y_value: float,
        is_scan_write: bool = False,
    ) -> dict[str, Any]:
        target_x = float(artificial_channel_x_value)
        target_y = float(artificial_channel_y_value)
        self.sig_target_changed.emit(
            {
                self.artificial_channel_x_name: target_x,
                self.artificial_channel_y_name: target_y,
            }
        )
        if is_scan_write:
            self._scan_target_artificial_values = {
                self.artificial_channel_x_name: target_x,
                self.artificial_channel_y_name: target_y,
            }

        target_original_x, target_original_y = self._artificial_to_original_coordinate(
            target_x,
            target_y,
        )
        if not self._is_original_coordinate_within_limits(
            target_original_x,
            target_original_y,
        ):
            message = (
                "[ArtificialChannelLogic] Skip set: mapped original channels out of limit. "
                f"{self.original_channel_x_name}={target_original_x:.6f}, "
                f"{self.original_channel_y_name}={target_original_y:.6f}."
            )
            self._emit_log("WARNING", message)
            if is_scan_write:
                self._skip_next_scan_read = True
            else:
                self._sync_scan_target_to_commanded()
            return {
                "skipped": True,
                "reason": "original_limit_exceeded",
                "state": dict(self.state),
            }

        start_x = float(self._commanded_artificial_values[self.artificial_channel_x_name])
        start_y = float(self._commanded_artificial_values[self.artificial_channel_y_name])

        step_x, step_y = self._compute_artificial_step_sizes()
        waypoints = self._build_artificial_ramp_waypoints(
            start_x,
            start_y,
            target_x,
            target_y,
            step_x,
            step_y,
        )

        last_state = dict(self.state)
        for waypoint_index, (ax_value, ay_value) in enumerate(waypoints):
            if self._should_abort_ramp():
                self._emit_log(
                    "WARNING",
                    "[ArtificialChannelLogic] Ramp aborted by force-stop request.",
                )
                self._skip_next_scan_read = False
                self._sync_scan_target_to_commanded()
                return {
                    "skipped": False,
                    "aborted": True,
                    "state": last_state,
                }

            original_channel_x_value, original_channel_y_value = (
                self._artificial_to_original_coordinate(ax_value, ay_value)
            )

            if not self._is_original_coordinate_within_limits(
                original_channel_x_value, original_channel_y_value
            ):
                message = (
                    "[ArtificialChannelLogic] Skip set: mapped original channels out of limit. "
                    f"{self.original_channel_x_name}={original_channel_x_value:.6f}, "
                    f"{self.original_channel_y_name}={original_channel_y_value:.6f}."
                )
                self._emit_log("WARNING", message)
                if is_scan_write:
                    self._skip_next_scan_read = True
                else:
                    self._sync_scan_target_to_commanded()
                return {
                    "skipped": True,
                    "reason": "original_limit_exceeded",
                    "state": dict(self.state),
                }

            try:
                self._write_original_channel_pair(
                    original_channel_x_value,
                    original_channel_y_value,
                )
            except Exception as exc:
                error = RuntimeError(
                    f"Failed to write original channels '{self.original_channel_x_name}'/'{self.original_channel_y_name}': {exc}"
                )
                self._emit_log("ERROR", f"[ArtificialChannelLogic] {error}")
                raise error from exc

            self._commanded_artificial_values[self.artificial_channel_x_name] = ax_value
            self._commanded_artificial_values[self.artificial_channel_y_name] = ay_value
            self.state = self._make_state(
                ax_value,
                ay_value,
                original_channel_x_value,
                original_channel_y_value,
            )
            last_state = dict(self.state)
            self.sig_state_changed.emit(self.state)

            if waypoint_index < len(waypoints) - 1:
                time.sleep(self.RAMP_INTER_STEP_DELAY_S)

        self._skip_next_scan_read = False
        self._sync_scan_target_to_commanded()
        if not is_scan_write:
            self._emit_log(
                "INFO",
                "[ArtificialChannelLogic] Applied artificial target "
                f"{self.artificial_channel_x_name}={target_x:.6f}, "
                f"{self.artificial_channel_y_name}={target_y:.6f}; mapped to "
                f"{self.original_channel_x_name}={target_original_x:.6f}, "
                f"{self.original_channel_y_name}={target_original_y:.6f}.",
            )
        return {
            "skipped": False,
            "state": dict(self.state),
        }

    def set_channel_value(
        self, channel_name: str, value: float, is_scan_write: bool = False
    ) -> dict[str, Any]:
        value = float(value)

        if self.has_artificial_channel(channel_name):
            if is_scan_write:
                target_values = dict(self._scan_target_artificial_values)
            else:
                target_values = dict(self._commanded_artificial_values)
            target_values[channel_name] = value
            return self.set_artificial_channel_values(
                target_values[self.artificial_channel_x_name],
                target_values[self.artificial_channel_y_name],
                is_scan_write=is_scan_write,
            )

        if self.has_original_channel(channel_name):
            low, high = self.original_channel_limits[channel_name]
            if value < low or value > high:
                self._emit_log(
                    "WARNING",
                    f"[ArtificialChannelLogic] Skip set: {channel_name}={value:.6f} "
                    f"out of limit [{low:.6f}, {high:.6f}].",
                )
                if is_scan_write:
                    self._skip_next_scan_read = True
                return {
                    "skipped": True,
                    "reason": "original_limit_exceeded",
                    "state": dict(self.state),
                }

            try:
                self._write_channel(value, channel_name)
            except Exception as exc:
                error = RuntimeError(
                    f"Failed to write original channel '{channel_name}': {exc}"
                )
                self._emit_log("ERROR", f"[ArtificialChannelLogic] {error}")
                raise error from exc
            self._skip_next_scan_read = False
            updated = self.read_all_channel_values()
            return {
                "skipped": False,
                "state": updated,
            }

        raise KeyError(
            f"Unknown channel '{channel_name}'. Supported artificial channels: {self.artificial_channels}; "
            f"supported original channels: {self.original_channels}."
        )

    def read_channel_value(self, channel_name: str) -> float:
        if not self.is_supported_channel(channel_name):
            raise KeyError(
                f"Unknown channel '{channel_name}'. Supported artificial channels: {self.artificial_channels}; "
                f"supported original channels: {self.original_channels}."
            )
        if self.has_artificial_channel(channel_name):
            return float(self._commanded_artificial_values[channel_name])
        state = self.read_all_channel_values()
        return float(state[channel_name])

    def read_all_channel_values(self) -> dict[str, Any]:
        try:
            original_channel_x_value = float(
                self._read_channel(self.original_channel_x_name)
            )
            original_channel_y_value = float(
                self._read_channel(self.original_channel_y_name)
            )
        except Exception as exc:
            raise RuntimeError(
                f"Failed to read original channels '{self.original_channel_x_name}'/'{self.original_channel_y_name}': {exc}"
            ) from exc

        artificial_channel_x_value, artificial_channel_y_value = (
            self._original_to_artificial_coordinate(
                original_channel_x_value, original_channel_y_value
            )
        )

        self._commanded_artificial_values[self.artificial_channel_x_name] = (
            artificial_channel_x_value
        )
        self._commanded_artificial_values[self.artificial_channel_y_name] = (
            artificial_channel_y_value
        )
        self._sync_scan_target_to_commanded()

        self.state = self._make_state(
            artificial_channel_x_value,
            artificial_channel_y_value,
            original_channel_x_value,
            original_channel_y_value,
        )
        self.sig_state_changed.emit(self.state)
        return dict(self.state)

    def consume_skip_read_for_scan(self) -> bool:
        return self._skip_next_scan_read

    def reset_skip_next_scan_read(self) -> None:
        self._skip_next_scan_read = False
        self._sync_scan_target_to_commanded()

    def _sync_scan_target_to_commanded(self) -> None:
        self._scan_target_artificial_values = dict(
            self._commanded_artificial_values
        )

    def _make_state(
        self,
        artificial_channel_x_value: float | str,
        artificial_channel_y_value: float | str,
        original_channel_x_value: float | str,
        original_channel_y_value: float | str,
    ) -> dict[str, Any]:
        return {
            "equations": dict(self.equations),
            "inverse_equations": dict(self.inverse_equations),
            self.artificial_channel_x_name: artificial_channel_x_value,
            self.artificial_channel_y_name: artificial_channel_y_value,
            self.original_channel_x_name: original_channel_x_value,
            self.original_channel_y_name: original_channel_y_value,
        }

    def _artificial_to_original_coordinate(
        self, artificial_channel_x_value: float, artificial_channel_y_value: float
    ) -> tuple[float, float]:
        artificial_vec = np.array(
            [artificial_channel_x_value, artificial_channel_y_value], dtype=float
        )
        original_vec = self._artificial_to_original_matrix @ (
            artificial_vec - self._original_to_artificial_offset
        )
        return float(original_vec[0]), float(original_vec[1])

    def _original_to_artificial_coordinate(
        self, original_channel_x_value: float, original_channel_y_value: float
    ) -> tuple[float, float]:
        original_vec = np.array(
            [original_channel_x_value, original_channel_y_value], dtype=float
        )
        artificial_vec = (
            self._original_to_artificial_matrix @ original_vec
            + self._original_to_artificial_offset
        )
        return float(artificial_vec[0]), float(artificial_vec[1])

    def _format_linear_equation(
        self,
        lhs_name: str,
        rhs_x_name: str,
        rhs_y_name: str,
        rhs_x_coeff: float,
        rhs_y_coeff: float,
        bias: float,
    ) -> str:
        return (
            f"{lhs_name}="
            f"{rhs_x_coeff:.9g}*{rhs_x_name}"
            f"+{rhs_y_coeff:.9g}*{rhs_y_name}"
            f"+{bias:.9g}"
        )

    def _compute_artificial_step_sizes(self) -> tuple[float, float]:
        ax_low, ax_high = self.artificial_channel_limits[self.artificial_channel_x_name]
        ay_low, ay_high = self.artificial_channel_limits[self.artificial_channel_y_name]
        step_x = self._ceil_to_one_significant_digit(
            max(0.0, ax_high - ax_low) / float(self.RAMP_DIVISOR)
        )
        step_y = self._ceil_to_one_significant_digit(
            max(0.0, ay_high - ay_low) / float(self.RAMP_DIVISOR)
        )
        return step_x, step_y

    def _build_artificial_ramp_waypoints(
        self,
        start_x: float,
        start_y: float,
        target_x: float,
        target_y: float,
        step_x: float,
        step_y: float,
    ) -> list[tuple[float, float]]:
        delta_x = target_x - start_x
        delta_y = target_y - start_y

        intervals_x = self._calculate_interval_count(delta_x, step_x)
        intervals_y = self._calculate_interval_count(delta_y, step_y)
        master_intervals = max(intervals_x, intervals_y)
        if master_intervals == 0:
            return [(start_x, start_y)]

        x_is_master = intervals_x >= intervals_y
        decimals_x = self._count_decimal_places(step_x)
        decimals_y = self._count_decimal_places(step_y)

        waypoints = [(start_x, start_y)]
        for step_index in range(1, master_intervals):
            if x_is_master:
                ax_value = self._axis_value_from_step(
                    start=start_x,
                    target=target_x,
                    step_size=step_x,
                    step_index=step_index,
                    total_steps=master_intervals,
                )
                progress = 0.0
                if not np.isclose(delta_x, 0.0):
                    progress = (ax_value - start_x) / delta_x
                ay_value = start_y + delta_y * progress
            else:
                ay_value = self._axis_value_from_step(
                    start=start_y,
                    target=target_y,
                    step_size=step_y,
                    step_index=step_index,
                    total_steps=master_intervals,
                )
                progress = 0.0
                if not np.isclose(delta_y, 0.0):
                    progress = (ay_value - start_y) / delta_y
                ax_value = start_x + delta_x * progress

            ax_value = self._round_to_decimal_places(ax_value, decimals_x)
            ay_value = self._round_to_decimal_places(ay_value, decimals_y)
            waypoints.append((ax_value, ay_value))

        waypoints.append((target_x, target_y))
        return waypoints

    def _axis_value_from_step(
        self,
        start: float,
        target: float,
        step_size: float,
        step_index: int,
        total_steps: int,
    ) -> float:
        delta = target - start
        if np.isclose(delta, 0.0):
            return start

        if step_size <= 0:
            return start + delta * (step_index / float(total_steps))

        direction = 1.0 if delta > 0 else -1.0
        return start + direction * step_size * float(step_index)

    def _calculate_interval_count(self, delta: float, step_size: float) -> int:
        distance = abs(float(delta))
        if np.isclose(distance, 0.0):
            return 0
        if step_size <= 0:
            return 1
        return max(1, int(math.floor((distance / step_size) + 1e-12)))

    @staticmethod
    def _count_decimal_places(value: float) -> int:
        if value <= 0:
            return 6
        text = f"{float(value):.12f}".rstrip("0").rstrip(".")
        if "." not in text:
            return 0
        return len(text.split(".")[1])

    @staticmethod
    def _round_to_decimal_places(value: float, decimal_places: int) -> float:
        quantum = Decimal(1).scaleb(-decimal_places)
        return float(Decimal(str(float(value))).quantize(quantum, rounding=ROUND_HALF_UP))

    @staticmethod
    def _ceil_to_one_significant_digit(value: float) -> float:
        value = abs(float(value))
        if np.isclose(value, 0.0):
            return 0.0
        exponent = math.floor(math.log10(value))
        base = 10 ** exponent
        return math.ceil(value / base) * base

    def _should_abort_ramp(self) -> bool:
        if self._should_abort_ramp_cb is None:
            return False
        try:
            return bool(self._should_abort_ramp_cb())
        except Exception:
            return False

    def _resolve_device_label_for_channel(self, channel_name: str) -> str:
        if self._resolve_device_label_cb is not None:
            try:
                label = str(self._resolve_device_label_cb(channel_name))
                if label != "":
                    return label
            except Exception:
                pass
        if "_" in channel_name:
            return channel_name.rsplit("_", 1)[0]
        return channel_name

    def _write_original_channel_pair(
        self,
        original_channel_x_value: float,
        original_channel_y_value: float,
    ) -> None:
        x_device = self._resolve_device_label_for_channel(self.original_channel_x_name)
        y_device = self._resolve_device_label_for_channel(self.original_channel_y_name)

        if x_device == y_device:
            self._write_channel(original_channel_x_value, self.original_channel_x_name)
            self._write_channel(original_channel_y_value, self.original_channel_y_name)
            return

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    self._write_channel, original_channel_x_value, self.original_channel_x_name
                ),
                executor.submit(
                    self._write_channel, original_channel_y_value, self.original_channel_y_name
                ),
            ]
            for future in futures:
                future.result()

    @staticmethod
    def _normalize_limit(
        channel_limit: tuple[float, float], channel_name: str
    ) -> tuple[float, float]:
        if len(channel_limit) != 2:
            raise ValueError(f"Limit for '{channel_name}' must be (low, high).")
        low = float(channel_limit[0])
        high = float(channel_limit[1])
        if low > high:
            raise ValueError(
                f"Invalid limits for '{channel_name}': low {low} > high {high}."
            )
        return low, high

    def _is_original_coordinate_within_limits(
        self, original_channel_x_value: float, original_channel_y_value: float
    ) -> bool:
        x_low, x_high = self.original_channel_limits[self.original_channel_x_name]
        y_low, y_high = self.original_channel_limits[self.original_channel_y_name]

        return (
            x_low <= original_channel_x_value <= x_high
            and y_low <= original_channel_y_value <= y_high
        )

    def _update_artificial_limits(self) -> None:
        x_low, x_high = self.original_channel_limits[self.original_channel_x_name]
        y_low, y_high = self.original_channel_limits[self.original_channel_y_name]

        corner_originals = (
            (x_low, y_low),
            (x_low, y_high),
            (x_high, y_low),
            (x_high, y_high),
        )

        mapped_artificial = [
            self._original_to_artificial_coordinate(x, y) for x, y in corner_originals
        ]

        artificial_x_values = [xy[0] for xy in mapped_artificial]
        artificial_y_values = [xy[1] for xy in mapped_artificial]

        self.artificial_channel_limits = {
            self.artificial_channel_x_name: (
                float(min(artificial_x_values)),
                float(max(artificial_x_values)),
            ),
            self.artificial_channel_y_name: (
                float(min(artificial_y_values)),
                float(max(artificial_y_values)),
            ),
        }

        ax_low, ax_high = self.artificial_channel_limits[self.artificial_channel_x_name]
        ay_low, ay_high = self.artificial_channel_limits[self.artificial_channel_y_name]

        self._emit_log(
            "INFO",
            "[ArtificialChannelLogic] Artificial channel limits computed: "
            f"{self.artificial_channel_x_name} in [{ax_low:.6f}, {ax_high:.6f}], "
            f"{self.artificial_channel_y_name} in [{ay_low:.6f}, {ay_high:.6f}]"
        )
