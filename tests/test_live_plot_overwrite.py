"""Live plots keep the previous sweep on screen and overwrite it point by point."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6 import QtWidgets

from core.all_plots import ImagePlot, LinePlot
from core.scan import Scan


class _Item:
    def __init__(self, widget):
        self._widget = widget

    def widget(self):
        return self._widget


class _Layout:
    def __init__(self, widgets):
        self._widgets = list(widgets)

    def count(self):
        return len(self._widgets)

    def itemAt(self, index):
        return _Item(self._widgets[index])


class _Page:
    def __init__(self, widgets):
        self.plots_layout = _Layout(widgets)


class _ScanStub:
    """Just the attributes Scan.new_data reads."""

    def __init__(self, widgets):
        self.info = {"data": {}}
        self.graphing_plots = [_Page(widgets)]


def _emit(scan, data, indices, *, source_level=0, changed=(0,)):
    Scan.new_data(
        scan,
        [
            data,
            list(indices),
            {
                "source_level": source_level,
                "changed_getter_indices": list(changed),
                "phase": "direct",
            },
        ],
    )


class LivePlotOverwriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_line_plot_keeps_previous_sweep_until_each_point_is_replaced(self):
        # level0: 3 points with one getter, level1 (outer, e.g. QWP): 2 points.
        data = [np.full((1, 2, 3), np.nan), np.full((1, 2), np.nan)]
        plot = LinePlot(
            coordinate={"x": "level0", "y": "L0G0_dev_signal"},
            setting_info=np.array([[0.0, 1.0, 2.0]]),
            data=data,
        )
        scan = _ScanStub([plot])

        for index, value in enumerate((10.0, 11.0, 12.0)):
            data[0][0, 0, index] = value
            _emit(scan, data, [index, 0])
        np.testing.assert_array_equal(plot.y_coordinates, [10.0, 11.0, 12.0])

        # The outer setter moves: its emit does not touch the level0 plot.
        _emit(scan, data, [0, 1], source_level=1, changed=())
        np.testing.assert_array_equal(plot.y_coordinates, [10.0, 11.0, 12.0])

        # First point of the next sweep replaces only its own position.
        data[0][0, 1, 0] = 20.0
        _emit(scan, data, [0, 1])
        np.testing.assert_array_equal(plot.y_coordinates, [20.0, 11.0, 12.0])

        data[0][0, 1, 1] = 21.0
        _emit(scan, data, [1, 1])
        np.testing.assert_array_equal(plot.y_coordinates, [20.0, 21.0, 12.0])

    def test_line_plot_overwrites_with_nan_for_a_skipped_point(self):
        data = [np.full((1, 2, 2), np.nan), np.full((1, 2), np.nan)]
        plot = LinePlot(
            coordinate={"x": "level0", "y": "L0G0_dev_signal"},
            setting_info=np.array([[0.0, 1.0]]),
            data=data,
        )
        scan = _ScanStub([plot])
        data[0][0, 0, :] = [1.0, 2.0]
        _emit(scan, data, [0, 0])
        _emit(scan, data, [1, 0])

        _emit(scan, data, [0, 1])  # skipped point: stored value stays NaN
        self.assertTrue(np.isnan(plot.y_coordinates[0]))
        self.assertEqual(plot.y_coordinates[1], 2.0)

    def test_image_plot_keeps_previous_frame_until_each_pixel_is_replaced(self):
        # level0: 3 x points, level1: 2 y points, level2 (outer): 2 frames.
        data = [
            np.full((1, 2, 2, 3), np.nan),
            np.full((1, 2, 2), np.nan),
            np.full((1, 2), np.nan),
        ]
        plot = ImagePlot(
            coordinate={"x": "level0", "y": "level1", "z": "L0G0_dev_signal"},
            x_setting_info={"dev_x": np.array([0.0, 1.0, 2.0])},
            y_setting_info={"dev_y": np.array([0.0, 1.0])},
        )
        scan = _ScanStub([plot])

        first = np.arange(6, dtype=float).reshape(2, 3)
        for y in range(2):
            for x in range(3):
                data[0][0, 0, y, x] = first[y, x]
                _emit(scan, data, [x, y, 0])
        np.testing.assert_array_equal(plot.data, first)

        # Next frame: the first new pixel overwrites only (y=0, x=0).
        data[0][0, 1, 0, 0] = 100.0
        _emit(scan, data, [0, 0, 1])
        expected = first.copy()
        expected[0, 0] = 100.0
        np.testing.assert_array_equal(plot.data, expected)


if __name__ == "__main__":
    unittest.main()
