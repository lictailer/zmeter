import copy
import math
import re

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets, uic

from .plot_config import configure_pyqtgraph
from .scan_info import ScanInfo

configure_pyqtgraph()


LINE_PEN = pg.mkPen(color=(240, 255, 255), width=2)


def _token_level(token):
    """Level number of a plot token: ``levelN`` or ``LnS..``/``LnG..``."""
    token = str(token or "")
    match = re.match(r"^level(\d+)$", token) or re.match(r"^L(\d+)[SG]\d+_", token)
    if match is None:
        raise ValueError(f"Not a level plot token: {token!r}")
    return int(match.group(1))


def _outer_block_index(current_target_index, fixed_levels):
    """Data index of the user levels (outermost first) for an array block."""
    return tuple(
        current_target_index[level]
        for level in range(len(current_target_index) - 1, fixed_levels - 1, -1)
    )


def _emit_scan_log(widget, level, message, *, persist_current_run=False):
    root = widget.window() if hasattr(widget, "window") else None
    if root is None or not hasattr(root, "_append_log_entry"):
        return
    try:
        root._append_log_entry(
            message,
            level=level,
            persist_current_run=persist_current_run,
        )
    except Exception:
        return


def _format_number(value):
    return f"{value:.4e}"


class LinePlot(QtWidgets.QWidget):
    """Live 1D plot of one getter against one scan level.

    During a scan ``record_point`` stores each new value (cheap, every point)
    and ``redraw`` pushes the stored values to the screen (called from the
    scan's redraw timer), so fast scans cannot queue up redraws.
    """

    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self, label=None,coordinate=None,setting_info=None,data=None):
        super(LinePlot, self).__init__()
        uic.loadUi("core/ui/line_plot.ui", self)
        self.plot = pg.PlotWidget()

        self.label = QtWidgets.QLabel()
        
        self.graph.addWidget(self.plot)
        self.graph.addWidget(self.label)
        self.data=data
        self.coordinate=coordinate
        self.x_name=coordinate['x']
        self.y_name=coordinate['y']
        self.plot.setLabel('left',self.y_name)
        self.plot.setLabel('bottom',self.x_name)

        #vertical line
        self.v_line = pg.InfiniteLine(angle=90, movable=True)
        self.plot.addItem(self.v_line)
        self.v_line.sigPositionChanged.connect(self.update_label)


        if "level" in self.x_name:
            self.setting_info=[]
            self.setting_info_length=len(setting_info[0])
            for index in range(self.setting_info_length):
                temp_point=[]
                for setter_setting_info in setting_info:
                    temp_point.append(setter_setting_info[index])
                self.setting_info.append(temp_point)
            self.setter_level_number=_token_level(self.x_name)
            self.x_coordinates=np.arange(self.setting_info_length, dtype=float)

        else:
            self.setter_level_number=_token_level(self.x_name)
            self.setting_info=setting_info
            self.setting_info_length=len(self.setting_info)
            self.x_coordinates = np.asarray(self.setting_info, dtype=float)

        getter_match = re.match(r"L(\d+)G(\d+)_", self.y_name or "")
        if getter_match:
            self.getter_level_number = int(getter_match.group(1))
            self.getter_number = int(getter_match.group(2))
        else:
            self.getter_level_number = self.setter_level_number
            self.getter_number = int(self.y_name[3])
                
        self.y_coordinates=np.full(self.setting_info_length, np.nan)
        self.needs_redraw = False
        self.line = self.plot.plot(pen=LINE_PEN)
        self._show_line()

    def _cursor_segment(self, x_pos):
        """Return ``(left, right, fraction)`` of the sweep segment under ``x_pos``.

        ``x_coordinates`` hold setter values (or point numbers for a level
        axis), so the segment is found by value.  Works for ascending,
        descending and back-and-forth sweeps; returns None outside the sweep.
        """
        xs = self.x_coordinates
        if len(xs) == 1:
            if np.isfinite(xs[0]) and np.isclose(x_pos, xs[0]):
                return 0, 0, 0.0
            return None
        left_x = xs[:-1]
        right_x = xs[1:]
        with np.errstate(invalid="ignore"):
            inside = (
                (np.minimum(left_x, right_x) <= x_pos)
                & (x_pos <= np.maximum(left_x, right_x))
            )
        hits = np.flatnonzero(inside)
        if len(hits) == 0:
            return None
        left = int(hits[0])
        right = left + 1
        span = xs[right] - xs[left]
        fraction = 0.0 if span == 0 else float((x_pos - xs[left]) / span)
        return left, right, fraction

    def update_label(self):
        x_pos = self.v_line.pos().x()
        segment = self._cursor_segment(x_pos)
        if segment is None:
            self.label.setText('Out of bounds')
            return
        left, right, fraction = segment

        x_val_text = self._format_x_values(
            self.setting_info[left], self.setting_info[right], fraction
        )

        left_y = self.y_coordinates[left]
        right_y = self.y_coordinates[right]
        if np.isnan(left_y) or np.isnan(right_y):
            y_val_text = "NaN"
        else:
            y_val_text = _format_number(left_y + fraction * (right_y - left_y))

        self.label.setText(f'X: {x_val_text}, Y: {y_val_text}')
    
    def _format_x_values(self, left_val_x, right_val_x, fraction):
        """Format X values handling lists, single values, and NaN values"""
        left_val_x = np.atleast_1d(np.asarray(left_val_x, dtype=float))
        right_val_x = np.atleast_1d(np.asarray(right_val_x, dtype=float))

        # Handle case where arrays have different lengths
        min_len = min(len(left_val_x), len(right_val_x))

        x_values = []
        for left_val, right_val in zip(left_val_x[:min_len], right_val_x[:min_len]):
            if np.isnan(left_val) or np.isnan(right_val):
                x_values.append("NaN")
            else:
                x_values.append(
                    _format_number(left_val + fraction * (right_val - left_val))
                )

        # Join multiple values with commas
        if len(x_values) == 1:
            return x_values[0]
        return "[" + ", ".join(x_values) + "]"

    def record_point(self, current_target_index):
        """Store the newest value; the scan's redraw timer draws it later.

        The line starts empty again whenever its own sweep restarts at
        point 0, so earlier sweeps never stay on screen.
        """
        point_index = current_target_index[self.setter_level_number]
        if point_index == 0:
            self.y_coordinates = np.full(self.setting_info_length, np.nan)
        index_tuple = tuple(current_target_index[::-1][0:len(current_target_index) - self.setter_level_number])
        self.y_coordinates[point_index] = self.data[self.setter_level_number][self.getter_number][index_tuple]
        self.needs_redraw = True

    def update_block(self, data, current_target_index, fixed_levels):
        """Replace the whole line from one array read (fixed levels).

        Drawn by the scan's redraw timer, like single points.
        """
        if self.getter_level_number >= fixed_levels:
            return
        outer = _outer_block_index(current_target_index, fixed_levels)
        block = np.asarray(
            data[self.getter_level_number][self.getter_number][outer], dtype=float
        )
        while block.ndim > 1:
            block = block[-1]
        if block.shape != (self.setting_info_length,):
            return
        self.y_coordinates = block.copy()
        self.needs_redraw = True

    def redraw(self):
        self.needs_redraw = False
        self._show_line()

    def _show_line(self):
        try:
            self.line.setData(self.x_coordinates, self.y_coordinates)
        except Exception as e:
            _emit_scan_log(
                self,
                "WARNING",
                f"Line plot update failed for {self.y_name}: {type(e).__name__}: {e}",
            )

    def load_plot(self,data,target_index):
        self.y_coordinates = np.array(data[self.setter_level_number][self.getter_number])
        while self.y_coordinates.ndim > 1:
            self.y_coordinates = self.y_coordinates[-1]
        self.y_coordinates = np.asarray(self.y_coordinates, dtype=float)
        self.needs_redraw = False
        self._show_line()


class SafeHistogramLUTItem(pg.HistogramLUTItem):
    """Avoid pyqtgraph histogram warnings when image data are all NaN."""

    def imageChanged(self, autoLevel=False, autoRange=False):
        image_ref = self.imageItem
        image_item = image_ref() if callable(image_ref) else None
        if image_item is None:
            return

        image_data = getattr(image_item, "image", None)
        if image_data is None:
            return

        try:
            has_finite = bool(np.isfinite(np.asarray(image_data)).any())
        except Exception:
            has_finite = True

        if not has_finite:
            return

        return super().imageChanged(autoLevel=autoLevel, autoRange=autoRange)


class CustomROI(pg.ROI):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)  # Only accept left mouse button

    def hoverEvent(self, ev):
        # Override hoverEvent to disable the yellow hover effect
        if ev.isExit():
            self.currentPen = self.pen
        else:
            self.currentPen = self.pen
        self.update()

class ImagePlot(pg.GraphicsLayoutWidget):

    def __init__(self,coordinate=None,x_setting_info=None,y_setting_info=None,level_info = None):
        super().__init__()
        self.data = np.zeros((1, 1))
        self.viewport().setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        self.x_name=coordinate['x']
        self.y_name=coordinate['y']
        self.z_name=coordinate['z']

        self.xy_label = self.addLabel('', row=1, col=0)
        self.z_label = self.addLabel('', row=2, col=0)
        
        self.x_level_number=_token_level(self.x_name)
        self.y_level_number=_token_level(self.y_name)

        getter_match = re.match(r"L(\d+)G(\d+)_", self.z_name or "")
        if getter_match:
            self.getter_level_number = int(getter_match.group(1))
            self.getter_number = int(getter_match.group(2))
        else:
            self.getter_level_number = self.x_level_number
            self.getter_number = int(self.z_name[3])
        self.is_full=False

        self.x_setting_info = x_setting_info
        self.y_setting_info = y_setting_info

        #set which point is plotting
        self.current_x = 0
        self.current_y = 0

        self.x_interpolate = False
        self.y_interpolate = False
        #data
        self.plot = self.addPlot(row=0, col=0)


        self.x_step = 1
        self.y_step = 1
        self.x_start = 0
        
        y_datashape = len(list(self.y_setting_info.values())[0])
        x_datashape = len(list(self.x_setting_info.values())[0])

        self.data_shape = [y_datashape, x_datashape]

        self.data = np.full((self.data_shape[0],self.data_shape[1]),np.nan)
        self.outer_context_key = None
        self.needs_redraw = False
        self.levels_locked = False
        self._levels_fitted = False

        # Image plot panel
        self.image = pg.ImageItem()
        self._safe_set_image(self.data)
        self.image.setRect(QtCore.QRectF(-0.5 * self.x_step, -0.5 * self.y_step, self.data.shape[1] * self.x_step, self.data.shape[0] * self.y_step))
        self.plot.addItem(self.image)
        [self.plot.getAxis(ax).setZValue(10) for ax in self.plot.axes]

        #roi
        self.roi = CustomROI([0, 0], [self.x_step, self.y_step], snapSize=min(self.x_step, self.y_step), pen=pg.mkPen(color=(0, 0, 0, 0)))
        self.roi.addTranslateHandle([0.5, 0.5])
        self.plot.addItem(self.roi)

        # Colourmap bar
        self.cbar = SafeHistogramLUTItem(image=self.image)
        self.cbar.gradient.loadPreset('viridis')
        self.addItem(self.cbar, row=0, col=1)
        self.plot.setLabel('left',self.y_name)
        self.plot.setLabel('bottom',self.x_name)
        self.plot.setLabel('top',self.z_name)

        #infinite lines
        self.v_line = pg.InfiniteLine(angle=90, movable=True)
        self.h_line = pg.InfiniteLine(angle=0, movable=True)
        self.plot.addItem(self.v_line, ignoreBounds=True)
        self.plot.addItem(self.h_line, ignoreBounds=True)
        self.roi.sigRegionChanged.connect(self.update_lines_from_roi)
        self.h_line.sigPositionChanged.connect(self.update_roi_from_lines)
        self.v_line.sigPositionChanged.connect(self.update_roi_from_lines)

        self.update_lines_from_roi()
        self.update_roi_text()


    def update_lines_from_roi(self):
        center = self.roi.pos() + self.roi.size() / 2
        self.h_line.setPos(center.y())
        self.v_line.setPos(center.x())
        self.update_roi_text()

    def update_roi_from_lines(self):
        center = QtCore.QPointF(self.v_line.pos().x(), self.h_line.pos().y())
        size = self.roi.size()
        top_left = center - size / 2
        self.roi.blockSignals(True)
        self.roi.setPos(top_left)
        self.roi.blockSignals(False)
        self.update_roi_text()

    def update_roi_text(self):
        pos = self.roi.pos() + self.roi.size() / 2
        x, y = pos.x(), pos.y()
        x1 = math.floor(x)
        x2 = math.ceil(x)
        y1 = math.floor(y)
        y2 = math.ceil(y)

        # Handle bounds checking
        x_out_of_bounds = x1 < 0 or x2 > self.data.shape[1] - 1
        y_out_of_bounds = y1 < 0 or y2 > self.data.shape[0] - 1
        
        # Format X values
        if x_out_of_bounds:
            x_text = 'Out of bounds'
        else:
            x_text = self._format_xy_values(self.x_setting_info, x1, x2, x, 'x')
        
        # Format Y values  
        if y_out_of_bounds:
            y_text = 'Out of bounds'
        else:
            y_text = self._format_xy_values(self.y_setting_info, y1, y2, y, 'y')
        
        # Combine X and Y text
        xy_label_text = f'X: {x_text},     Y: {y_text}'
        self.xy_label.setText(xy_label_text)

        # Handle Z value
        try:
            if x_out_of_bounds or y_out_of_bounds:
                self.z_label.setText('Out of bounds')
            else:
                value = self.data[int(y), int(x)]
                if np.isnan(value):
                    self.z_label.setText('Value: NaN')
                else:
                    self.z_label.setText(f'Value: {value:.4e}')
        except IndexError:
            self.z_label.setText('Out of bounds')
        return
    
    def _format_xy_values(self, setting_info, coord1, coord2, coord_pos, axis_name):
        """Format X or Y values handling lists, single values, and NaN values"""
        values = []
        
        for setter, setting_points in setting_info.items():
            try:
                # Handle bounds checking for this setter
                if coord1 < 0 or coord1 >= len(setting_points) or coord2 >= len(setting_points):
                    values.append("OOB")
                    continue
                    
                val_1 = setting_points[coord1]
                val_2 = setting_points[coord2]
                
                # Convert to numpy arrays if they aren't already
                if not isinstance(val_1, (list, tuple, np.ndarray)):
                    val_1 = [val_1]
                if not isinstance(val_2, (list, tuple, np.ndarray)):
                    val_2 = [val_2]
                    
                val_1 = np.array(val_1)
                val_2 = np.array(val_2)
                
                # Handle case where arrays have different lengths
                min_len = min(len(val_1), len(val_2))
                val_1 = val_1[:min_len]
                val_2 = val_2[:min_len]
                
                # Process each component
                component_values = []
                for i in range(len(val_1)):
                    v1, v2 = val_1[i], val_2[i]
                    
                    # Handle NaN values
                    if np.isnan(v1) or np.isnan(v2):
                        component_values.append("NaN")
                    else:
                        # Interpolate between the two values
                        interpolated = (coord_pos - coord1) * (v2 - v1) + v1
                        
                        # Format the value
                        if abs(interpolated) >= 1e-3 or interpolated == 0:
                            component_values.append(f"{interpolated:.4e}")
                        else:
                            component_values.append(f"{interpolated:.4e}")
                
                # Join multiple components with commas if more than one
                if len(component_values) == 1:
                    values.append(component_values[0])
                else:
                    values.append("[" + ", ".join(component_values) + "]")
                    
            except (IndexError, TypeError, ValueError):
                values.append("Error")
        
        # Join values from different setters
        if len(values) == 1:
            return values[0]
        else:
            return " | ".join(values)
    

    def keyPressEvent(self, event):
        pos = self.roi.pos()
        x, y = pos.x(), pos.y()
        step = 0.1  # Step size for each key press
        if event.key() == QtCore.Qt.Key.Key_Right and x < self.data.shape[1] * self.x_step - step - 0.5 * self.x_step:
            self.roi.setPos([x + step, y])
        elif event.key() == QtCore.Qt.Key.Key_Left and x > -0.5 * self.x_step + step:
            self.roi.setPos([x - step, y])
        elif event.key() == QtCore.Qt.Key.Key_Up and y > -0.5 * self.y_step + step:
            self.roi.setPos([x, y - step])
        elif event.key() == QtCore.Qt.Key.Key_Down and y < self.data.shape[0] * self.y_step - step - 0.5 * self.y_step:
            self.roi.setPos([x, y + step])
        self.update_lines_from_roi()

    def set_levels_locked(self, locked):
        """Keep the current colour levels (True) or re-fit them on every redraw."""
        self.levels_locked = bool(locked)
        if not self.levels_locked:
            self._safe_set_image(self.data)

    def _safe_set_image(self, image_data):
        data_array = np.asarray(image_data)
        if data_array.size == 0:
            return

        try:
            all_nan = bool(np.isnan(data_array).all())
        except Exception:
            all_nan = False

        # Locked levels still need one fit once real data first arrive.
        keep_levels = all_nan or (self.levels_locked and self._levels_fitted)
        self.image.setImage(data_array, autoLevels=not keep_levels)
        if not keep_levels:
            self._levels_fitted = True

    def record_point(self, new_data, current_target_index):
        """Store the newest value; the scan's redraw timer draws it later.

        The image starts empty again whenever the levels above it move on,
        so earlier frames never stay on screen.
        """
        outer_context_key = tuple(current_target_index[self.y_level_number + 1:])
        if self.outer_context_key != outer_context_key:
            self.outer_context_key = outer_context_key
            self.data = np.full((self.data_shape[0], self.data_shape[1]), np.nan)
            self.needs_redraw = True

        current_y=current_target_index[self.x_level_number]
        current_x=current_target_index[self.y_level_number]
        index_tuple = tuple(current_target_index[::-1][0:len(current_target_index) - self.x_level_number])
        new_value = new_data[self.x_level_number][self.getter_number][index_tuple]

        current_value = self.data[current_x, current_y]
        if np.isclose(current_value, new_value, equal_nan=True):
            return

        self.data[current_x, current_y] = new_value
        self.needs_redraw = True

    def redraw(self):
        self.needs_redraw = False
        self._safe_set_image(self.data)

    def update_block(self, new_data, current_target_index, fixed_levels):
        """Fill a row (spectrum vs. a user level) or a whole frame at once."""
        if self.x_level_number >= fixed_levels:
            return
        outer_context_key = tuple(current_target_index[self.y_level_number + 1:])
        if self.outer_context_key != outer_context_key:
            self.outer_context_key = outer_context_key
            self.data = np.full((self.data_shape[0], self.data_shape[1]), np.nan)
        outer = _outer_block_index(current_target_index, fixed_levels)
        block = np.asarray(
            new_data[self.getter_level_number][self.getter_number][outer], dtype=float
        )
        if self.y_level_number < fixed_levels:
            while block.ndim > 2:
                block = block[-1]
            if block.shape != self.data.shape:
                return
            self.data = block.copy()
        else:
            while block.ndim > 1:
                block = block[-1]
            if block.shape != (self.data.shape[1],):
                return
            self.data[current_target_index[self.y_level_number], :] = block
        self.needs_redraw = True

    def load_image(self, data, target_index):
        temp = data[self.x_level_number][self.getter_number]

        # Walk down the levels above y, outermost first (data axes run from
        # the highest level to the lowest).
        target_index = target_index[self.y_level_number+1:]

        for idx in reversed(target_index):
            temp = temp[idx]
        
        self.data = np.array(temp)

        if self.data.ndim != 2:
            _emit_scan_log(
                self,
                "WARNING",
                (
                    f"Image plot load skipped for {self.z_name}: "
                    f"expected 2D array but got shape {self.data.shape}"
                ),
            )
            return

        self.needs_redraw = False
        self._safe_set_image(self.data)




class AllPlots(QtWidgets.QWidget):
    sig_info_changed = QtCore.pyqtSignal(object)

    def __init__(self, level_info=None, *, page_number: int = 0):
        super().__init__()
        uic.loadUi("core/ui/all_plots.ui", self)

        self.level_info = level_info or copy.deepcopy(ScanInfo['levels'])
        self.plot_setting_info = None
        self.page_number = page_number
        self.grid_size = []
        self.data = None
        self.levels_locked = False

    def plot_widgets(self):
        """The LinePlot / ImagePlot widgets currently on this page."""
        widgets = []
        for i in range(self.plots_layout.count()):
            w = self.plots_layout.itemAt(i).widget()
            if isinstance(w, (LinePlot, ImagePlot)):
                widgets.append(w)
        return widgets

    def set_levels_locked(self, locked):
        """Lock or unlock the colour levels of every image plot on this page."""
        self.levels_locked = bool(locked)
        for w in self.plot_widgets():
            if isinstance(w, ImagePlot):
                w.set_levels_locked(self.levels_locked)

    def redraw_pending(self, *, include_hidden=False):
        """Redraw plots holding new points; return True if any are still waiting.

        Plots on a page that is not shown wait until it is shown, unless
        ``include_hidden`` (used before the plots are captured or saved).
        """
        still_pending = False
        for w in self.plot_widgets():
            if not w.needs_redraw:
                continue
            if include_hidden or w.isVisible():
                w.redraw()
            else:
                still_pending = True
        return still_pending

    def set_level_info(self, info):
        self.level_info = info

    def receive_plot_info(self, plot_setting_info):
        self.plot_setting_info = plot_setting_info
    
    
    def update_plots(self):    
        """Re-draw every time level-info or plot-settings change."""

        # 0.  How many plots per page right now?
        root = self.window()                      # Scan widget
        ppp = root.findChild(QtWidgets.QComboBox, "PlotsPerPage")

        ppp_setting = ppp.currentText()
        if ppp_setting == "2x1":
            per_page = 2
        elif ppp_setting == "2x2":
            per_page = 4
        elif ppp_setting == "2x4":
            per_page = 8
        elif ppp_setting == "3x3":
            per_page = 9
        elif ppp_setting == "3x4":
            per_page = 12
        else:
            per_page = 4

        # 1.  Flatten every defined plot into one list
        all_coords: list[tuple[str, dict]] = []
        if self.plot_setting_info:
            all_coords += [("line",  c)
                           for c in self.plot_setting_info["line_plots"].values()]
            all_coords += [("image", c)
                           for c in self.plot_setting_info["image_plots"].values()]

        start = self.page_number * per_page
        end   = start + per_page
        subset = all_coords[start:end]            # slice for *this* page

        # 2.  Clear any existing widgets
        while self.plots_layout.count():
            self.plots_layout.takeAt(0).widget().deleteLater()

        # 3.  Decide grid size from per_page
        if   per_page == 2:  self.grid_size = [2, 1]
        elif per_page == 4:  self.grid_size = [2, 2]
        elif per_page == 8:  self.grid_size = [2, 4]    
        elif per_page == 9:  self.grid_size = [3, 3]
        elif per_page == 12: self.grid_size = [3, 4]
        else:                self.grid_size = [2, 2]   # per_page == 4

        # 4.  Create widgets
        row = col = 0
        for kind, coord in subset:
            x_name = coord['x']; y_name = coord['y']

            if kind == "line":
                if x_name in ('None', '') or y_name in ('None', ''):
                    continue
                setting = self.get_setting_info_line(coord)
                w = LinePlot(coordinate=coord, setting_info=setting, data=self.data)
            else:
                z_name = coord.get('z', '')
                if x_name in ('None', '') or y_name in ('None', '') or z_name in ('None', ''):
                    continue
                x_set, y_set = self.get_setting_info_image(coord)
                w = ImagePlot(coordinate=coord, x_setting_info=x_set,
                              y_setting_info=y_set, level_info=self.level_info)
                w.set_levels_locked(self.levels_locked)

            self.plots_layout.addWidget(w, row, col)
            col += 1
            if col >= self.grid_size[1]:
                col = 0
                row += 1

    def get_setting_info_line(self,coordinate):
        x_name=coordinate['x']
        match_level = re.search(r'L(\d+)', x_name)

        if match_level:
            level_number = match_level.group(1)
            level = f'level{level_number}'
            setting_array=self.level_info[level]['setting_array']
            #might need to change this S to G
            match_setter = re.search(r'S(\d+)', x_name)
            setter_number = match_setter.group(1)
            
            return setting_array[int(setter_number)]
        else:
            level=f'level{_token_level(x_name)}'
            setting_array=self.level_info[level]['setting_array']
            return setting_array
        
    def get_setting_info_image(self,coordinate):
        x_name=coordinate['x']
        x_level=f'level{_token_level(x_name)}'
        x_setting_array=self.level_info[x_level]['setting_array']
        x_setters=[]
        for setter,setter_info in self.level_info[x_level]['setters'].items():
            x_setters.append(setter_info['channel'])
        x_setting_dict={}
        for i,setter in enumerate(x_setters):
            x_setting_dict[setter] = x_setting_array[i]

        y_name=coordinate['y']
        y_level=f'level{_token_level(y_name)}'
        y_setting_array=self.level_info[y_level]['setting_array']
        y_setters=[]
        for setter,setter_info in self.level_info[y_level]['setters'].items():
            y_setters.append(setter_info['channel'])
        y_setting_dict={}
        for i,setter in enumerate(y_setters):
            y_setting_dict[setter] = y_setting_array[i]


        return [x_setting_dict,y_setting_dict]
