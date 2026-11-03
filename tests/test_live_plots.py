"""Offscreen tests for live plotting: timed redraw, crosshair readout, lock levels."""

import copy
import os
import unittest
from unittest import mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PyQt6 import QtWidgets

from core.all_plots import ImagePlot, LinePlot
from core.scan import Scan
from core.scan_info import ScanInfo


def _line_plot(xs, ys):
    data = [np.asarray(ys, dtype=float).reshape(1, -1)]
    return LinePlot(
        coordinate={"x": "L0S0_v", "y": "L0G0_y"},
        setting_info=np.asarray(xs, dtype=float),
        data=data,
    )


def _image_plot(nx, ny):
    return ImagePlot(
        coordinate={"x": "level0", "y": "level1", "z": "L0G0_z"},
        x_setting_info={"a": np.linspace(0, 1, nx)},
        y_setting_info={"b": np.linspace(0, 1, ny)},
    )


class _AppTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class LinePlotReadoutTests(_AppTestCase):
    def _readout(self, plot, x_pos):
        for i in range(plot.setting_info_length):
            plot.record_point([i])
        plot.v_line.setValue(x_pos)
        return plot.label.text()

    def test_ascending_setter_axis_reads_value_at_cursor(self):
        xs = np.linspace(0, 0.5, 51)
        plot = _line_plot(xs, xs * 100)
        self.assertEqual(self._readout(plot, 0.3), "X: 3.0000e-01, Y: 3.0000e+01")

    def test_descending_setter_axis_is_in_bounds(self):
        xs = np.linspace(0.5, 0, 51)
        plot = _line_plot(xs, xs * 100)
        self.assertEqual(self._readout(plot, 0.25), "X: 2.5000e-01, Y: 2.5000e+01")

    def test_interpolates_between_points(self):
        plot = _line_plot([0.0, 2.0, 4.0], [10.0, 20.0, 40.0])
        self.assertEqual(self._readout(plot, 3.0), "X: 3.0000e+00, Y: 3.0000e+01")

    def test_outside_sweep_is_out_of_bounds(self):
        plot = _line_plot([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
        self.assertEqual(self._readout(plot, 2.5), "Out of bounds")
        plot.v_line.setValue(-0.1)
        self.assertEqual(plot.label.text(), "Out of bounds")

    def test_missing_point_reads_nan(self):
        plot = _line_plot([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
        plot.record_point([0])
        plot.v_line.setValue(0.5)
        self.assertEqual(plot.label.text(), "X: 5.0000e-01, Y: NaN")

    def test_level_axis_reads_every_setter(self):
        setting = [np.array([0.0, 1.0, 2.0]), np.array([10.0, 20.0, 30.0])]
        plot = LinePlot(
            coordinate={"x": "level0", "y": "L0G0_y"},
            setting_info=setting,
            data=[np.array([[5.0, 6.0, 7.0]])],
        )
        self.assertEqual(
            self._readout(plot, 1.5),
            "X: [1.5000e+00, 2.5000e+01], Y: 6.5000e+00",
        )


class RecordAndRedrawTests(_AppTestCase):
    def test_line_records_without_drawing_until_redraw(self):
        plot = _line_plot([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
        plot.record_point([0])
        plot.record_point([1])
        self.assertTrue(plot.needs_redraw)
        self.assertTrue(np.isnan(plot.line.yData).all())

        plot.redraw()

        self.assertFalse(plot.needs_redraw)
        np.testing.assert_array_equal(plot.line.yData[:2], [1.0, 2.0])
        self.assertTrue(np.isnan(plot.line.yData[2]))

    def test_line_clears_old_sweep_at_point_zero(self):
        plot = _line_plot([0.0, 1.0, 2.0], [1.0, 2.0, 3.0])
        for i in range(3):
            plot.record_point([i])
        plot.redraw()

        plot.record_point([0])
        plot.redraw()

        self.assertEqual(plot.line.yData[0], 1.0)
        self.assertTrue(np.isnan(plot.line.yData[1:]).all())

    def test_image_clears_old_frame_when_outer_level_moves(self):
        image = _image_plot(2, 2)
        data = [np.arange(8, dtype=float).reshape(1, 2, 2, 2)]
        for outer in range(2):
            for j in range(2):
                for i in range(2):
                    image.record_point(data, [i, j, outer])
            if outer == 0:
                image.redraw()
                first_frame = image.image.image.copy()

        image.redraw()
        np.testing.assert_array_equal(first_frame, [[0.0, 1.0], [2.0, 3.0]])
        np.testing.assert_array_equal(image.image.image, [[4.0, 5.0], [6.0, 7.0]])


class LockLevelsTests(_AppTestCase):
    def _fill(self, image, scale):
        data = [np.array([[1.0, 2.0], [3.0, 4.0]]).reshape(1, 2, 2) * scale]
        for j in range(2):
            for i in range(2):
                image.record_point(data, [i, j])
        image.redraw()

    def test_unlocked_levels_follow_data(self):
        image = _image_plot(2, 2)
        self._fill(image, 1.0)
        self._fill(image, 10.0)
        self.assertEqual(tuple(image.image.getLevels()), (10.0, 40.0))

    def test_locked_levels_stay_after_first_fit(self):
        image = _image_plot(2, 2)
        image.set_levels_locked(True)
        self._fill(image, 1.0)
        self.assertEqual(tuple(image.image.getLevels()), (1.0, 4.0))

        self._fill(image, 10.0)
        self.assertEqual(tuple(image.image.getLevels()), (1.0, 4.0))

        image.set_levels_locked(False)
        self.assertEqual(tuple(image.image.getLevels()), (10.0, 40.0))

    def test_locked_levels_keep_user_choice_on_colour_bar(self):
        image = _image_plot(2, 2)
        image.set_levels_locked(True)
        self._fill(image, 1.0)
        image.cbar.region.setRegion([0.0, 100.0])
        self._fill(image, 10.0)
        self.assertEqual(tuple(image.image.getLevels()), (0.0, 100.0))


class ScanLiveDisplayTests(_AppTestCase):
    def setUp(self):
        self.scan = Scan(
            name="live plot probe",
            info=copy.deepcopy(ScanInfo),
            setter_equipment_info={},
            getter_equipment_info={},
            main_window=None,
        )
        self.scan.resize(1000, 800)
        self.scan.show()
        self.app.processEvents()

    def tearDown(self):
        self.scan._live_redraw_timer.stop()
        self.scan.close()
        self.scan.deleteLater()
        self.app.processEvents()

    def _show_tab(self, tab):
        stack = tab.parentWidget()
        tabs = stack.parentWidget() if stack is not None else None
        tabs.setCurrentWidget(tab)
        self.app.processEvents()

    def _add_line(self, page_index, n=200):
        xs = np.linspace(0, 1, n)
        data = [np.full((1, n), np.nan)]
        plot = LinePlot(
            coordinate={"x": "L0S0_v", "y": "L0G0_y"}, setting_info=xs, data=data
        )
        self.scan.graphing_plots[page_index].plots_layout.addWidget(plot, 0, 0)
        return plot, data

    def test_many_points_cost_one_redraw_per_plot(self):
        self._show_tab(self.scan.Plots1Tab)
        plot, data = self._add_line(0)
        self.app.processEvents()

        with mock.patch.object(LinePlot, "redraw", autospec=True, side_effect=LinePlot.redraw) as redraw:
            for i in range(200):
                data[0][0, i] = float(i)
                self.scan.new_data([data, [i], {"source_level": 0, "changed_getter_indices": [0]}])
            self.assertEqual(redraw.call_count, 0)
            self.assertTrue(self.scan._live_redraw_timer.isActive())

            self.scan._on_live_redraw_timer()

        self.assertEqual(redraw.call_count, 1)
        np.testing.assert_array_equal(plot.line.yData, np.arange(200, dtype=float))
        self.assertFalse(self.scan._live_redraw_timer.isActive())

    def test_hidden_page_waits_until_flush_for_capture(self):
        self._show_tab(self.scan.Plots1Tab)
        plot, data = self._add_line(1, n=3)
        data[0][0, 0] = 5.0
        self.scan.new_data([data, [0], None])

        self.scan._on_live_redraw_timer()
        self.assertTrue(plot.needs_redraw)
        self.assertTrue(self.scan._live_redraw_timer.isActive())

        self._show_tab(self.scan.Plots2Tab)
        self.scan._on_live_redraw_timer()
        self.assertFalse(plot.needs_redraw)
        self.assertEqual(plot.line.yData[0], 5.0)

    def test_flush_draws_hidden_pages(self):
        self._show_tab(self.scan.Plots1Tab)
        plot, data = self._add_line(2, n=3)
        data[0][0, 0] = 7.0
        self.scan.new_data([data, [0], None])

        self.assertFalse(self.scan.flush_live_display())

        self.assertFalse(plot.needs_redraw)
        self.assertEqual(plot.line.yData[0], 7.0)

    def test_progress_labels_set_once_per_redraw(self):
        labels = (
            self.scan.scan_time_info_1,
            self.scan.scan_time_info_2,
            self.scan.scan_time_info_3,
            self.scan.scan_point_info_1,
            self.scan.scan_point_info_2,
            self.scan.scan_point_info_3,
        )
        set_text_calls = []
        for label in labels:
            original = label.setText
            label.setText = (
                lambda text, _orig=original: (set_text_calls.append(text), _orig(text))
            )

        for n in range(50):
            self.scan.update_remaining_time_label(f"0:00:{n:02d} / 0:01:00")
            self.scan.update_remaining_points_label(f"{n + 1} / 50 ({(n + 1) * 2}%)")
        self.assertEqual(set_text_calls, [])

        self.scan._on_live_redraw_timer()

        self.assertEqual(len(set_text_calls), 6)
        for label in labels[3:]:
            self.assertEqual(label.text(), "Finished / Total Points: 50 / 50 (100%)")
        for label in labels[:3]:
            self.assertEqual(label.text(), "Remaining / Total Time: 0:00:49 / 0:01:00")

    def test_lock_checkbox_controls_images_on_its_tab_only(self):
        first = _image_plot(2, 2)
        second = _image_plot(2, 2)
        self.scan.graphing_plots[0].plots_layout.addWidget(first, 0, 0)
        self.scan.graphing_plots[1].plots_layout.addWidget(second, 0, 0)

        self.scan.lock_levels_checkbox_1.setChecked(True)

        self.assertTrue(first.levels_locked)
        self.assertFalse(second.levels_locked)
        self.assertTrue(self.scan.graphing_plots[0].levels_locked)

        self.scan.lock_levels_checkbox_1.setChecked(False)
        self.assertFalse(first.levels_locked)


if __name__ == "__main__":
    unittest.main()
