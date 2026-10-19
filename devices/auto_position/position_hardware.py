"""Routed serpentine maps; no transport creation, discovery or device imports."""
import numpy as np
from core.measurement_io import RouterIO
from .position_engine import checkpoint


class MapReader:
    def __init__(self, geometry, io):
        self.geometry, self.io = geometry, io
        self.image = None
        self.completed_points = 0
        self.last_commands = {}

    def prepare(self, stop):
        checkpoint(stop)
        g = self.geometry
        g.validate()
        self.io.refresh()
        for ref, endpoints in ((g.x, (g.x_min, g.x_max)), (g.y, (g.y_min, g.y_max))):
            for value in endpoints:
                self.io.validate(ref, "writable", value)
        self.io.validate(g.signal, "readable")
        self.io.read(g.signal)  # Fail before motion if the input is unavailable.

    def move(self, point, stop):
        x, y = self.geometry.point(point)
        # Validate BOTH coordinates before issuing either command.
        self.io.validate(self.geometry.x, "writable", x)
        self.io.validate(self.geometry.y, "writable", y)
        for name, ref, value in (("x", self.geometry.x, x), ("y", self.geometry.y, y)):
            checkpoint(stop)
            if self.last_commands.get(name) != value:
                self.io.write(ref, value)
                self.last_commands[name] = value
        if stop.wait(self.geometry.settle_s):
            checkpoint(stop)

    def acquire(self, stop, on_row=None):
        g = self.geometry
        self.image = np.full((g.y_points, g.x_points), np.nan)
        xs, ys = g.xs, g.ys
        for row, y in enumerate(ys):
            indices = range(g.x_points) if row % 2 == 0 else reversed(range(g.x_points))
            for col in indices:
                self.move((float(xs[col]), float(y)), stop)
                values = []
                for index in range(g.samples):
                    checkpoint(stop)
                    values.append(self.io.read(g.signal))
                    if index + 1 < g.samples and stop.wait(g.sample_interval_s):
                        checkpoint(stop)
                self.image[row, col] = np.mean(values)
                self.completed_points += 1
            if on_row:
                on_row(self.image.copy(), row + 1)
        return self.image.copy()
