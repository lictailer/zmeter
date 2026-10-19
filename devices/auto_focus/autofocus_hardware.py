"""Replaceable Z and acquisition adapters; hardware is opened explicitly.

Routed adapters use ZMeter's existing channel catalog and router. They never
construct NI tasks or import another device's driver. Coordinates use the
selected channel's native units, optionally mapped to calibrated distance.
"""
from __future__ import annotations

import math
import threading
import time

import numpy as np
from core.measurement_io import RouterIO

from .autofocus_engine import (
    Channel, SourceSettings, ZSettings, checkpoint, finite, pause,
)


class BoundedZAxis:
    def __init__(self, settings: ZSettings):
        settings.validate()
        self.settings = settings
        self.last_position: float | None = None

    def validate_path(self, lower: float, upper: float) -> None:
        self.settings.validate_target(lower)
        self.settings.validate_target(upper)

    def move_to(self, target: float, stop: threading.Event) -> float:
        target = self.settings.validate_target(target)
        checkpoint(stop)
        current = self.settings.validate_target(self.position())
        steps = max(1, math.ceil(abs(target - current) / self.settings.max_move))
        if steps > 10000:
            raise ValueError("Z move needs more than 10000 segments; review range and maximum move")
        for waypoint in np.linspace(current, target, steps + 1)[1:]:
            checkpoint(stop)
            actual = finite(self._move_once(float(waypoint), stop), "Z readback")
            self.last_position = actual
            self.settings.validate_target(actual)
            if abs(actual - waypoint) > self.settings.tolerance:
                raise RuntimeError(f"Z target {waypoint:g} not confirmed; readback {actual:g}")
            checkpoint(stop)
        return actual


class RoutedZAxis(BoundedZAxis):
    """Any absolute writable Z channel plus a position getter, in native units."""
    def __init__(self, settings: ZSettings, io: RouterIO):
        super().__init__(settings)
        self.io = io
        self.connected = False

    def connect(self, stop: threading.Event) -> None:
        checkpoint(stop)
        self.io.refresh()
        self.io.validate(self.settings.setter, "writable")
        self.io.validate(self.settings.getter, "readable")
        self.settings.validate_target(self.position())
        self.connected = True

    def validate_path(self, lower: float, upper: float) -> None:
        super().validate_path(lower, upper)
        for target in (lower, upper):
            self.io.validate(self.settings.setter, "writable", self.settings.to_native(target))

    def position(self) -> float:
        self.last_position = self.settings.from_native(self.io.read(self.settings.getter))
        return self.last_position

    def _move_once(self, target: float, stop: threading.Event) -> float:
        self.io.write(self.settings.setter, self.settings.to_native(target))
        deadline = time.monotonic() + self.settings.command_timeout_s
        while True:
            actual = self.position()
            if abs(actual - target) <= self.settings.tolerance:
                return actual
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Routed Z target {target:g} not confirmed; last readback {actual:g}")
            pause(stop, 0.05)

    def disconnect(self) -> None:
        # The routed device owns its own connection.
        self.connected = False


class PointSource:
    def __init__(self, settings: SourceSettings, io: RouterIO):
        self.settings, self.io = settings, io
        self._last_x = self._last_y = None

    def prepare(self, stop: threading.Event) -> None:
        self.settings.validate()
        self.io.refresh()
        self.io.validate(self.settings.signal, "readable")
        self.io.read(self.settings.signal)
        if self.settings.position_xy:
            self._validate_xy(self.settings.x_center, self.settings.y_center)
            self._move_xy(self.settings.x_center, self.settings.y_center, stop)

    def _validate_xy(self, x, y) -> None:
        self.io.validate(self.settings.x, "writable", x)
        self.io.validate(self.settings.y, "writable", y)

    def _move_xy(self, x, y, stop) -> None:
        checkpoint(stop)
        if self._last_x != x:
            self.io.write(self.settings.x, x)
            self._last_x = x
        checkpoint(stop)
        if self._last_y != y:
            self.io.write(self.settings.y, y)
            self._last_y = y
        pause(stop, self.settings.xy_settle_s)

    def _sample(self, stop) -> float:
        values = []
        for index in range(self.settings.samples):
            checkpoint(stop)
            values.append(self.io.read(self.settings.signal))
            if index + 1 < self.settings.samples:
                pause(stop, self.settings.sample_interval_s)
        return float(np.mean(values))

    def acquire(self, stop: threading.Event) -> float:
        return self._sample(stop)

    def close(self) -> None:
        pass


class RasterSource(PointSource):
    def prepare(self, stop: threading.Event) -> None:
        self.settings.validate()
        checkpoint(stop)
        self.io.refresh()
        self.io.validate(self.settings.signal, "readable")
        self.io.read(self.settings.signal)
        s = self.settings
        self.xs = np.linspace(s.x_center - s.x_span / 2, s.x_center + s.x_span / 2, s.x_points)
        self.ys = np.linspace(s.y_center - s.y_span / 2, s.y_center + s.y_span / 2, s.y_points)
        # Validate the entire planned rectangle before writing either output.
        for x in (self.xs[0], self.xs[-1]):
            for y in (self.ys[0], self.ys[-1]):
                self._validate_xy(x, y)

    def acquire(self, stop: threading.Event) -> np.ndarray:
        image = np.empty((len(self.ys), len(self.xs)))
        for row, y in enumerate(self.ys):
            indices = range(len(self.xs)) if row % 2 == 0 else reversed(range(len(self.xs)))
            for col in indices:
                self._move_xy(self.xs[col], y, stop)
                image[row, col] = self._sample(stop)
        self._move_xy(self.settings.x_center, self.settings.y_center, stop)
        return image


class CameraSource:
    """OpenCV-compatible camera; vendor cameras can supply capture_factory.

    For an SDK with a different API, implement prepare/acquire/close and add it
    to SOURCE_FACTORIES below. No camera is enumerated during construction.
    """
    def __init__(self, settings: SourceSettings, io=None, capture_factory=None):
        self.settings = settings
        self.capture_factory = capture_factory
        self.capture = None

    def prepare(self, stop: threading.Event) -> None:
        self.settings.validate()
        checkpoint(stop)
        factory = self.capture_factory
        if factory is None:
            import cv2
            factory = cv2.VideoCapture
        self.capture = factory(self.settings.camera_index)
        if not self.capture.isOpened():
            self.close()
            raise RuntimeError("Could not open the selected camera index")
        from .autofocus_engine import image_data
        image_data(self.acquire(stop))  # Verify the frame and ROI before moving Z.

    def acquire(self, stop: threading.Event) -> np.ndarray:
        for _ in range(self.settings.discard_frames + 1):
            checkpoint(stop)
            ok, frame = self.capture.read()
            if not ok or frame is None:
                raise RuntimeError("Camera did not return a frame")
        x, y, width, height = self.settings.roi
        if width and height:
            if x + width > frame.shape[1] or y + height > frame.shape[0]:
                raise ValueError("Camera ROI lies outside the acquired frame")
            frame = frame[y:y + height, x:x + width]
        return np.asarray(frame).copy()

    def close(self) -> None:
        capture, self.capture = self.capture, None
        if capture is not None:
            capture.release()


# Explicit, code-reviewable extension points; the panel populates these lists.
Z_FACTORIES = {
    "routed": ("Registered device channel (Arduino, piezo or stage)", RoutedZAxis),
}
SOURCE_FACTORIES = {
    "point": ("Single-point reflection / scalar signal", PointSource),
    "raster": ("XY raster image from routed channels", RasterSource),
    "camera": ("Camera image (OpenCV)", CameraSource),
}
