from typing import Any, Callable

import numpy as np
from PyQt6 import QtCore


class ArtificialChannelLogic(QtCore.QObject):
    sig_state_changed = QtCore.pyqtSignal(object)

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
    ):
        super().__init__(parent)
        self._write_channel = write_channel
        self._read_channel = read_channel

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
        self._skip_next_scan_read = False

        self.construct_coordinate_relation(coordinate_pairs)
        self.state = self._make_state("Unknown", "Unknown", "Unknown", "Unknown")
        self.sig_state_changed.emit(self.state)
        return dict(self.state)

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
        artificial_channel_x_value = float(artificial_channel_x_value)
        artificial_channel_y_value = float(artificial_channel_y_value)

        original_channel_x_value, original_channel_y_value = (
            self._artificial_to_original_coordinate(
                artificial_channel_x_value, artificial_channel_y_value
            )
        )

        if not self._is_original_coordinate_within_limits(
            original_channel_x_value, original_channel_y_value
        ):
            print(
                "[ArtificialChannelLogic] Skip set: mapped original channels out of limit. "
                f"{self.original_channel_x_name}={original_channel_x_value:.6f}, "
                f"{self.original_channel_y_name}={original_channel_y_value:.6f}."
            )
            if is_scan_write:
                self._skip_next_scan_read = True
            return {
                "skipped": True,
                "reason": "original_limit_exceeded",
                "state": dict(self.state),
            }

        try:
            self._write_channel(original_channel_x_value, self.original_channel_x_name)
            self._write_channel(original_channel_y_value, self.original_channel_y_name)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to write original channels '{self.original_channel_x_name}'/'{self.original_channel_y_name}': {exc}"
            ) from exc

        self._commanded_artificial_values[self.artificial_channel_x_name] = (
            artificial_channel_x_value
        )
        self._commanded_artificial_values[self.artificial_channel_y_name] = (
            artificial_channel_y_value
        )

        self.state = self._make_state(
            artificial_channel_x_value,
            artificial_channel_y_value,
            original_channel_x_value,
            original_channel_y_value,
        )
        self.sig_state_changed.emit(self.state)
        return {
            "skipped": False,
            "state": dict(self.state),
        }

    def set_channel_value(
        self, channel_name: str, value: float, is_scan_write: bool = False
    ) -> dict[str, Any]:
        value = float(value)

        if self.has_artificial_channel(channel_name):
            self._commanded_artificial_values[channel_name] = value
            return self.set_artificial_channel_values(
                self._commanded_artificial_values[self.artificial_channel_x_name],
                self._commanded_artificial_values[self.artificial_channel_y_name],
                is_scan_write=is_scan_write,
            )

        if self.has_original_channel(channel_name):
            low, high = self.original_channel_limits[channel_name]
            if value < low or value > high:
                print(
                    f"[ArtificialChannelLogic] Skip set: {channel_name}={value:.6f} out of limit [{low:.6f}, {high:.6f}]."
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
                raise RuntimeError(
                    f"Failed to write original channel '{channel_name}': {exc}"
                ) from exc
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

        self.state = self._make_state(
            artificial_channel_x_value,
            artificial_channel_y_value,
            original_channel_x_value,
            original_channel_y_value,
        )
        self.sig_state_changed.emit(self.state)
        return dict(self.state)

    def consume_skip_read_for_scan(self) -> bool:
        should_skip = self._skip_next_scan_read
        self._skip_next_scan_read = False
        return should_skip

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

        print(
            "[ArtificialChannelLogic] Artificial channel limits computed: "
            f"{self.artificial_channel_x_name} in [{ax_low:.6f}, {ax_high:.6f}], "
            f"{self.artificial_channel_y_name} in [{ay_low:.6f}, {ay_high:.6f}]"
        )
