"""Configurable autofocus panel; construction performs no hardware discovery."""
from __future__ import annotations

import json
from dataclasses import asdict

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from core.measurement_widgets import ChannelPicker

from .autofocus_engine import AutofocusSettings, Channel, METRICS, OutputSettings, SearchSettings, SourceSettings, ZSettings
from .autofocus_hardware import RouterIO
from .autofocus_logic import AutofocusLogic


class FocusPlot(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.samples = []
        self.gaussian_fit = None
        self.y_label = "Score"
        self.unit = "selected unit"
        self.setMinimumSize(360, 180)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("white"))
        area = QtCore.QRectF(55, 15, self.width() - 75, self.height() - 50)
        p.setPen(QtGui.QColor("#555555"))
        p.drawRect(area)
        p.drawText(5, 14, self.y_label)
        p.drawText(self.width() // 2 - 40, self.height() - 5, f"Z ({self.unit})")
        if not self.samples:
            return
        points = sorted((s.position, s.score) for s in self.samples)
        xs, ys = zip(*points)
        xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
        if self.gaussian_fit is not None:
            fit_x = np.linspace(xmin, xmax, 301)
            fit_y = self.gaussian_fit.values(fit_x)
            ymin, ymax = min(ymin, float(fit_y.min())), max(ymax, float(fit_y.max()))
        dx, dy = max(xmax - xmin, 1e-12), max(ymax - ymin, 1e-12)
        p.drawText(3, 30, f"{ymax:.3g}")
        p.drawText(3, self.height() - 32, f"{ymin:.3g}")
        p.drawText(55, self.height() - 18, f"{xmin:.4g}")
        p.drawText(self.width() - 85, self.height() - 18, f"{xmax:.4g}")
        mapped = [QtCore.QPointF(area.left() + (x - xmin) / dx * area.width(),
                                area.bottom() - (y - ymin) / dy * area.height()) for x, y in points]
        p.setPen(QtGui.QPen(QtGui.QColor("#1266b5"), 2))
        p.drawPolyline(QtGui.QPolygonF(mapped))
        p.setBrush(QtGui.QColor("#1266b5"))
        for point in mapped:
            p.drawEllipse(point, 3, 3)
        if self.gaussian_fit is not None:
            p.setPen(QtGui.QPen(QtGui.QColor("#c4600a"), 2))
            p.drawPolyline(QtGui.QPolygonF([
                QtCore.QPointF(area.left() + (x - xmin) / dx * area.width(),
                              area.bottom() - (y - ymin) / dy * area.height())
                for x, y in zip(fit_x, fit_y)
            ]))
            peak_x = area.left() + (self.gaussian_fit.center - xmin) / dx * area.width()
            p.setPen(QtGui.QPen(QtGui.QColor("#c4600a"), 1, QtCore.Qt.PenStyle.DashLine))
            p.drawLine(QtCore.QPointF(peak_x, area.top()), QtCore.QPointF(peak_x, area.bottom()))
            p.setPen(QtGui.QColor("#1266b5"))
            p.drawText(130, 14, "Measured")
            p.setPen(QtGui.QColor("#c4600a"))
            p.drawText(210, 14, "Gaussian fit")


class AutofocusMain(QtWidgets.QWidget):
    route_commands_in_background = True

    def __init__(self, logic=None):
        super().__init__()
        self.logic = logic or AutofocusLogic()
        self._busy, self._router = False, None
        self.fields, self.pickers = {}, {}
        self.setWindowTitle("Autofocus")
        self.resize(960, 820)
        outer = QtWidgets.QVBoxLayout(self)
        self.tabs = QtWidgets.QTabWidget()
        outer.addWidget(self.tabs)
        self._build_z_tab()
        self._build_measurement_tab()
        self._build_search_tab()
        self._build_saving_tab()
        buttons = QtWidgets.QHBoxLayout()
        self.run_button = QtWidgets.QPushButton("Run autofocus")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.read_z_button = QtWidgets.QPushButton("Read Z")
        self.refresh_button = QtWidgets.QPushButton("Refresh channels")
        for button in (self.run_button, self.stop_button, self.read_z_button, self.refresh_button):
            buttons.addWidget(button)
        outer.addLayout(buttons)
        files = QtWidgets.QHBoxLayout()
        self.save_button = QtWidgets.QPushButton("Save setup")
        self.load_button = QtWidgets.QPushButton("Load setup")
        self.export_button = QtWidgets.QPushButton("Export result / partial data")
        for button in (self.save_button, self.load_button, self.export_button):
            files.addWidget(button)
        outer.addLayout(files)
        self.position_label = QtWidgets.QLabel("Z: not selected")
        self.status_label = QtWidgets.QLabel("Connect the actuator in its own panel, choose its Z channels/units, then Select Z.")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.position_label)
        outer.addWidget(self.status_label)
        display = QtWidgets.QHBoxLayout()
        self.plot = FocusPlot()
        self.image_label = QtWidgets.QLabel("Latest point signal or focus image")
        self.image_label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(220, 160)
        display.addWidget(self.plot, 2)
        display.addWidget(self.image_label, 1)
        outer.addLayout(display)
        self.load_controls(self.logic.settings)
        for button, operation in ((self.run_button, lambda: self._submit(self.logic.set_focus, 1)),
                                  (self.read_z_button, lambda: self._submit(self.logic.get_z)),
                                  (self.connect_button, lambda: self._submit(self.logic.connect_z)),
                                  (self.disconnect_button, lambda: self._submit(self.logic.disconnect))):
            button.clicked.connect(operation)
        self.stop_button.clicked.connect(self.logic.force_stop)
        self.refresh_button.clicked.connect(self.refresh_channels)
        self.save_button.clicked.connect(self._save_setup)
        self.load_button.clicked.connect(self._load_setup)
        self.export_button.clicked.connect(self._export_result)
        self.logic.sig_status.connect(self.status_label.setText)
        self.logic.sig_error.connect(lambda message: self.status_label.setText("Autofocus error: " + message))
        self.logic.sig_connected.connect(lambda _: self._update_controls())
        self.logic.sig_position.connect(self._show_position)
        self.logic.sig_sample.connect(self._show_sample)
        self.logic.sig_result.connect(self._show_result)
        self.logic.sig_busy.connect(self._set_busy)
        self.logic.finished.connect(lambda: self._set_busy(False))
        self.z_backend.currentIndexChanged.connect(self._z_backend_changed)
        self.source_mode.currentIndexChanged.connect(self._source_mode_changed)
        self.search_method.currentIndexChanged.connect(self._update_mode_fields)
        self.bounds_mode.currentIndexChanged.connect(self._update_mode_fields)
        self.set_xy.toggled.connect(self._update_mode_fields)
        self.convert_distance.toggled.connect(self._update_mode_fields)
        self.fields["z.native_unit"].textChanged.connect(self._update_mode_fields)
        self.fields["z.distance_unit"].textChanged.connect(self._update_mode_fields)
        self._update_controls()

    def _tab(self, name):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, name)
        return form

    def _number(self, form, key, label, default, integer=False, low=-1e9, high=1e9):
        widget = QtWidgets.QSpinBox() if integer else QtWidgets.QDoubleSpinBox()
        if not integer:
            widget.setDecimals(9)
        widget.setRange(int(low) if integer else low, int(high) if integer else high)
        widget.setValue(default)
        self.fields[key] = widget
        form.addRow(label, widget)

    def _text(self, form, key, label, value=""):
        widget = QtWidgets.QLineEdit(value)
        self.fields[key] = widget
        form.addRow(label, widget)
        return widget

    def _picker(self, form, key, label, access):
        widget = ChannelPicker(access)
        self.pickers[key] = widget
        form.addRow(label, widget)

    @staticmethod
    def _note(form, text):
        note = QtWidgets.QLabel(text)
        note.setWordWrap(True)
        form.addRow(note)

    def _build_z_tab(self):
        form = self._tab("Z actuator")
        self.z_backend = QtWidgets.QComboBox()
        for key, (label, _) in self.logic.z_factories.items():
            self.z_backend.addItem(label, key)
        form.addRow("Move objective or sample using", self.z_backend)
        self._picker(form, "z.setter", "Absolute Z action channel", "writable")
        self._picker(form, "z.getter", "Native Z position read channel", "readable")
        self._text(form, "z.native_unit", "Native channel unit (both channels must match)", "deg")
        self.convert_distance = QtWidgets.QCheckBox("Convert native position to calibrated distance")
        form.addRow(self.convert_distance)
        self._text(form, "z.distance_unit", "Distance unit: um or mm", "um")
        for key, label in (("distance_per_native", "Distance per native unit (signed calibration)"),
                           ("native_zero", "Native reference position"),
                           ("distance_zero", "Distance at that reference")):
            self._number(form, "z." + key, label, 0)
        self.z_unit_note = QtWidgets.QLabel()
        form.addRow(self.z_unit_note)
        for key, label, value, low in (
            ("minimum", "Minimum allowed Z", -20, -1e9), ("maximum", "Maximum allowed Z", 20, -1e9),
            ("max_move", "Maximum Z change per command", 10, 0.000000001),
            ("tolerance", "Position confirmation tolerance", 0.1, 0.000000001),
            ("command_timeout_s", "Command timeout (s)", 120, 0.01),
        ):
            self._number(form, "z." + key, label, value, low=low)
        row = QtWidgets.QHBoxLayout()
        self.connect_button = QtWidgets.QPushButton("Select Z / read position")
        self.disconnect_button = QtWidgets.QPushButton("Release Z selection")
        row.addWidget(self.connect_button)
        row.addWidget(self.disconnect_button)
        form.addRow(row)
        self._note(form, "Autofocus never connects/disconnects the actuator itself. Z = distance_reference + "
                   "(native - native_reference) × distance_per_native when conversion is enabled. "
                   "Limits, offsets, command size and tolerance use the chosen Z unit. Changing units/calibration "
                   "does not rescale existing numbers: review them before Select Z. No travel calibration is assumed.")

    def _build_measurement_tab(self):
        form = self._tab("Focus measurement")
        self.source_mode, self.metric, self.objective = (QtWidgets.QComboBox() for _ in range(3))
        for key, (label, _) in self.logic.source_factories.items():
            self.source_mode.addItem(label, key)
        for key, metric in METRICS.items():
            self.metric.addItem(metric.label, key)
        self.objective.addItem("Maximize", "maximize")
        self.objective.addItem("Minimize", "minimize")
        form.addRow("Acquisition", self.source_mode)
        form.addRow("Focus score", self.metric)
        self.mean_note = QtWidgets.QLabel(
            "Single-point score = average of the input readings at this Z, in the input channel's units. "
            "For example, 5 readings are averaged into one plotted signal value; this is not image sharpness."
        )
        self.mean_note.setWordWrap(True)
        form.addRow(self.mean_note)
        form.addRow("Optimize", self.objective)
        self._picker(form, "source.signal", "Reflection / photocurrent / other input", "readable")
        self._picker(form, "source.x", "X output (galvo or piezo)", "writable")
        self._picker(form, "source.y", "Y output (galvo or piezo)", "writable")
        self.set_xy = QtWidgets.QCheckBox("Set XY point before single-point acquisition")
        form.addRow(self.set_xy)
        for key, label, value in (
            ("x_center", "X point / raster center", 0), ("y_center", "Y point / raster center", 0),
            ("x_span", "Raster X span", 0.1), ("y_span", "Raster Y span", 0.1),
            ("xy_minimum", "Minimum XY output (native units)", -1),
            ("xy_maximum", "Maximum XY output (native units)", 1),
            ("xy_settle_s", "XY settling time (s)", 0.01),
            ("sample_interval_s", "Between input readings (s)", 0.01),
        ):
            self._number(form, "source." + key, label, value)
        for key, label, value, low, high in (
            ("x_points", "Raster X pixels", 9, 3, 256), ("y_points", "Raster Y pixels", 9, 3, 256),
            ("samples", "Input readings per point", 5, 1, 1000),
            ("camera_index", "OpenCV camera index", 0, 0, 100),
            ("discard_frames", "Camera frames discarded before each image", 2, 0, 100),
        ):
            self._number(form, "source." + key, label, value, True, low, high)
        self._text(form, "source.roi", "Camera ROI x,y,width,height (0,0,0,0 = full frame)", "0,0,0,0")

    def _build_search_tab(self):
        form = self._tab("Z search")
        self.search_method = QtWidgets.QComboBox()
        self.search_method.addItem("Adaptive peak search + bounded Brent (default)", "adaptive_brent")
        self.search_method.addItem("Coarse grid + refinement", "grid")
        self.search_method.addItem("Full Z sweep → measured maximum / minimum", "sweep_maximum")
        self.search_method.addItem("Full Z sweep → Gaussian fit peak / dip", "sweep_gaussian")
        form.addRow("Z optimization method", self.search_method)
        self.bounds_mode = QtWidgets.QComboBox()
        self.bounds_mode.addItem("Relative to starting Z", "relative")
        self.bounds_mode.addItem("Absolute Z coordinates", "absolute")
        form.addRow("Search bounds coordinates", self.bounds_mode)
        for key, label, value, low in (
            ("start_offset", "Search lower bound (relative to starting Z)", -10, -1e9),
            ("stop_offset", "Search upper bound (relative to starting Z)", 10, -1e9),
            ("absolute_lower", "Absolute lower Z", -10, -1e9),
            ("absolute_upper", "Absolute upper Z", 10, -1e9),
            ("settle_s", "Settle after Z motion (s)", 0.1, 0),
            ("minimum_score_change", "Minimum score variation across search", 0, 0),
        ):
            self._number(form, "search." + key, label, value, low=low)
        for key, side in (("start_offset", "lower"), ("stop_offset", "upper")):
            self.fields["search." + key].setToolTip(
                f"Absolute {side} search bound = Z read at the start of this run + this value. "
                "This is a Z search boundary, not an XY image boundary or a prescribed move. "
                "The adaptive optimizer chooses positions within the interval."
            )
        self._number(form, "search.initial_step", "Initial Z probe step", 1, low=0.000000001)
        self._number(form, "search.position_precision", "Requested Z search precision", 0.2, low=0.000000001)
        self._number(form, "search.max_evaluations", "Maximum focus evaluations (adaptive)", 40, True, 3, 1000)
        self._number(form, "search.sweep_points", "Z positions in full sweep (includes both ends)", 41, True, 3, 1001)
        self._number(form, "search.gaussian_min_r_squared", "Minimum accepted Gaussian fit R²", 0.8, low=0, high=1)
        for key, label, value, low, high in (
            ("coarse_points", "Coarse Z points", 9, 3, 101),
            ("refine_points", "Points per refinement", 5, 3, 21),
            ("refinement_rounds", "Refinement rounds", 2, 0, 6),
        ):
            self._number(form, "search." + key, label, value, True, low, high)
        self.move_best = QtWidgets.QCheckBox("Move to selected focus Z after successful search / fit")
        form.addRow(self.move_best)
        self._note(form, "Choose relative bounds or absolute Z endpoints; all Z values use the selected Z unit, not XY image coordinates. "
                   "Full sweeps measure evenly spaced Z positions from lower to upper, with no refinement. Gaussian mode fits a baseline plus "
                   "Gaussian and selects its center; a failed/poor fit does not apply a final focus move. Adaptive search probes both directions, "
                   "expands uphill to bracket a peak, then uses bounded Brent (parabolic / golden-section steps). "
                   "It assumes a reasonably single-peaked curve, not a guaranteed global optimum. Effective precision is at least "
                   "twice the position confirmation tolerance. Grid search retains the original fixed sampling/refinement. "
                   "Both reuse samples. A flat curve, boundary peak or evaluation limit is reported without a final best-position move. "
                   "Stop leaves the last completed position. An in-flight device command may need to finish first.")

    def read_settings(self):
        groups = {"z": {}, "source": {}, "search": {}, "output": {}}
        for full_key, widget in self.fields.items():
            section, key = full_key.split(".")
            groups[section][key] = widget.text().strip() if isinstance(widget, QtWidgets.QLineEdit) else widget.value()
        for full_key, picker in self.pickers.items():
            section, key = full_key.split(".")
            groups[section][key] = picker.ref()
        groups["z"].update(backend=self.z_backend.currentData(), convert_to_distance=self.convert_distance.isChecked())
        groups["source"].update(mode=self.source_mode.currentData(), position_xy=self.set_xy.isChecked())
        groups["source"]["roi"] = tuple(int(v.strip()) for v in groups["source"]["roi"].split(","))
        groups["search"].update(metric=self.metric.currentData(), objective=self.objective.currentData(),
                                move_to_best=self.move_best.isChecked(), method=self.search_method.currentData(),
                                bounds_mode=self.bounds_mode.currentData())
        groups["output"].update(enabled=self.save_runs.isChecked(), save_frames=self.save_frames.isChecked())
        settings = AutofocusSettings(ZSettings(**groups["z"]), SourceSettings(**groups["source"]), SearchSettings(**groups["search"]), OutputSettings(**groups["output"]))
        settings.validate()
        return settings

    def load_controls(self, settings):
        for full_key, widget in self.fields.items():
            section, key = full_key.split(".")
            value = getattr(getattr(settings, section), key)
            if key == "roi":
                value = ",".join(map(str, value))
            if isinstance(widget, QtWidgets.QLineEdit):
                widget.setText(str(value))
            else:
                widget.setValue(value)
        for full_key, picker in self.pickers.items():
            section, key = full_key.split(".")
            picker.set_ref(getattr(getattr(settings, section), key))
        for combo, value in ((self.z_backend, settings.z.backend), (self.source_mode, settings.source.mode),
                             (self.metric, settings.search.metric), (self.objective, settings.search.objective),
                             (self.search_method, settings.search.method), (self.bounds_mode, settings.search.bounds_mode)):
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(value))
            combo.blockSignals(False)
        self.set_xy.setChecked(settings.source.position_xy)
        self.convert_distance.setChecked(settings.z.convert_to_distance)
        self.move_best.setChecked(settings.search.move_to_best)
        self.save_runs.setChecked(settings.output.enabled)
        self.save_frames.setChecked(settings.output.save_frames)
        self._update_mode_fields()

    def _submit(self, operation, *args):
        try:
            settings = self.read_settings()
            self.logic.apply_settings(settings)
            self.plot.unit = settings.z.unit
            return self.logic.submit(operation, *args)
        except Exception as exc:
            self.status_label.setText("Autofocus error: " + str(exc))
            return False

    def _build_saving_tab(self):
        form = self._tab("Saving")
        self.save_runs = QtWidgets.QCheckBox("Automatically save autofocus data and curve PNG for every run")
        self.save_frames = QtWidgets.QCheckBox("Also save every acquired image (raw NPY and PNG)")
        form.addRow(self.save_runs)
        self._text(form, "output.directory", "Results directory")
        browse = QtWidgets.QPushButton("Choose directory…")
        browse.clicked.connect(self._choose_output_directory)
        form.addRow(browse)
        form.addRow(self.save_frames)
        self._note(form, "Off by default. Each run gets a unique folder containing settings, completed samples, outcome and score-versus-Z PNG. "
                   "Stopped/failed runs retain completed data. No automatic return move is made. Image saving can use substantial space.")

    def _choose_output_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Autofocus results directory")
        if directory:
            self.fields["output.directory"].setText(directory)

    def _set_busy(self, busy):
        self._busy = busy
        self._update_controls()

    def _update_controls(self):
        connected = self.logic.connected
        self.tabs.setEnabled(not self._busy)
        for button, enabled in ((self.connect_button, not connected), (self.disconnect_button, connected),
                                (self.run_button, connected), (self.read_z_button, connected),
                                (self.load_button, not connected), (self.save_button, True),
                                (self.export_button, True), (self.refresh_button, True)):
            button.setEnabled(not self._busy and enabled)
        self.stop_button.setEnabled(self._busy)
        self.z_backend.setEnabled(not connected)
        for key, widget in {**self.fields, **self.pickers}.items():
            if key.startswith("z."):
                widget.setEnabled(not connected)
        self.convert_distance.setEnabled(not connected)
        self._update_mode_fields()

    def _update_mode_fields(self):
        unit_key = "z.distance_unit" if self.convert_distance.isChecked() else "z.native_unit"
        self.z_unit_note.setText("Z limits, search bounds, segment size and tolerance use: " + self.fields[unit_key].text())
        mode = self.source_mode.currentData()
        camera, raster = mode == "camera", mode == "raster"
        xy = raster or (mode == "point" and self.set_xy.isChecked())
        for index, metric in enumerate(METRICS.values()):
            self.metric.model().item(index).setEnabled(mode != "point" or metric.scalar)
        self.mean_note.setVisible(mode == "point")
        visible = {
            "search.start_offset": self.bounds_mode.currentData() == "relative",
            "search.stop_offset": self.bounds_mode.currentData() == "relative",
            "search.absolute_lower": self.bounds_mode.currentData() == "absolute",
            "search.absolute_upper": self.bounds_mode.currentData() == "absolute",
            "search.sweep_points": self.search_method.currentData() in ("sweep_maximum", "sweep_gaussian"),
            "search.gaussian_min_r_squared": self.search_method.currentData() == "sweep_gaussian",
            "search.initial_step": self.search_method.currentData() == "adaptive_brent",
            "search.position_precision": self.search_method.currentData() == "adaptive_brent",
            "search.max_evaluations": self.search_method.currentData() == "adaptive_brent",
            "search.coarse_points": self.search_method.currentData() == "grid",
            "search.refine_points": self.search_method.currentData() == "grid",
            "search.refinement_rounds": self.search_method.currentData() == "grid",
            "z.distance_unit": self.convert_distance.isChecked(),
            "z.distance_per_native": self.convert_distance.isChecked(),
            "z.native_zero": self.convert_distance.isChecked(),
            "z.distance_zero": self.convert_distance.isChecked(),
            "source.signal": not camera, "source.x": not camera, "source.y": not camera,
            "source.x_center": xy, "source.y_center": xy,
            "source.x_span": raster, "source.y_span": raster,
            "source.x_points": raster, "source.y_points": raster,
            "source.xy_minimum": xy, "source.xy_maximum": xy,
            "source.xy_settle_s": xy, "source.samples": not camera,
            "source.sample_interval_s": not camera, "source.camera_index": camera,
            "source.discard_frames": camera, "source.roi": camera,
        }
        for key, show in visible.items():
            widget = self.fields.get(key) or self.pickers[key]
            widget.parentWidget().layout().setRowVisible(widget, show)
        self.set_xy.parentWidget().layout().setRowVisible(self.set_xy, mode == "point")

    def _z_backend_changed(self):
        self._update_controls()

    def _source_mode_changed(self):
        if self.source_mode.currentData() == "point":
            self.metric.setCurrentIndex(self.metric.findData("mean"))
        elif self.metric.currentData() == "mean":
            self.metric.setCurrentIndex(self.metric.findData("gradient"))
        self._update_mode_fields()

    def _show_position(self, position):
        self.position_label.setText("Z: not selected" if position is None else
                                    f"Z: {position:g} {self.logic.settings.z.unit} (last read)")

    def _show_sample(self, item):
        if self.logic.run_settings is not None:
            self.plot.unit = self.logic.run_settings.z.unit
            self.plot.y_label = "Mean signal" if self.logic.run_settings.source.mode == "point" else "Score"
        if item is None:
            self.plot.samples = []
            self.plot.gaussian_fit = None
            self.plot.update()
            return
        sample, data = item
        self.plot.samples.append(sample)
        self.plot.update()
        image = np.asarray(data)
        if image.ndim < 2:
            self.image_label.setText(f"Last acquired mean signal: {sample.score:.6g}\n"
                                     f"Measured at Z = {sample.position:g} {self.plot.unit}")
            return
        if image.ndim == 3:
            image = image[:, :, :3].mean(axis=2)
        low, high = float(image.min()), float(image.max())
        pixels = np.ascontiguousarray(np.clip((image - low) / max(high - low, 1e-12) * 255, 0, 255).astype(np.uint8))
        qimage = QtGui.QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0],
                              QtGui.QImage.Format.Format_Grayscale8).copy()
        self.image_label.setPixmap(QtGui.QPixmap.fromImage(qimage).scaled(
            300, 180, QtCore.Qt.AspectRatioMode.KeepAspectRatio))

    def _show_result(self, result):
        self.plot.gaussian_fit = result.gaussian_fit
        self.plot.update()

    def configure_command_router(self, command_router, source_device=None):
        self.logic.configure_command_router(command_router, source_device)
        self._detach_catalog_signal()
        self._router = command_router
        signal = getattr(command_router, "sig_catalog_changed", None)
        if signal is not None:
            signal.connect(self._catalog_changed)
        self.refresh_channels()

    def detach_command_router(self):
        self.logic.detach_command_router()
        self._detach_catalog_signal()
        self._router = None

    def _detach_catalog_signal(self):
        signal = getattr(self._router, "sig_catalog_changed", None)
        if signal is not None:
            try:
                signal.disconnect(self._catalog_changed)
            except (TypeError, RuntimeError):
                pass

    def _catalog_changed(self, catalog):
        for picker in self.pickers.values():
            picker.refresh(catalog)

    def find_catalog_references(self, **kwargs):
        refs = list(self.logic.find_catalog_references(**kwargs))
        for picker in self.pickers.values():
            ref = picker.ref()
            removed = kwargs.get("removed_setters" if picker.access == "writable" else "removed_getters", ())
            if ref.device in kwargs.get("removed_device_labels", ()) or f"{ref.device}_{ref.channel}" in removed:
                refs.append(f"autofocus panel selection: {ref.device}/{ref.channel}")
        return tuple(dict.fromkeys(refs))

    def refresh_channels(self):
        if self._router is None:
            return
        try:
            catalog = RouterIO(self._router, self.logic.device_label).refresh()
            self._catalog_changed(catalog)
        except Exception as exc:
            self.status_label.setText(str(exc))

    @staticmethod
    def write_json(path, data):
        payload = json.dumps(data, indent=2, allow_nan=False).encode("utf-8")
        output = QtCore.QSaveFile(path)
        if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if output.write(payload) != len(payload) or not output.commit():
            raise OSError(output.errorString())

    def _save_setup(self):
        try:
            settings = self.read_settings()
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save autofocus setup", "", "JSON (*.json)")
            if path:
                self.write_json(path, settings.to_dict())
        except Exception as exc:
            self.status_label.setText(str(exc))

    def _load_setup(self):
        try:
            path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load autofocus setup", "", "JSON (*.json)")
            if path:
                with open(path, encoding="utf-8") as stream:
                    settings = AutofocusSettings.from_dict(json.load(stream))
                self.logic.apply_settings(settings)
                self.load_controls(settings)
        except Exception as exc:
            self.status_label.setText(str(exc))

    def _export_result(self):
        try:
            if not self.logic.history:
                raise ValueError("No focus data to export")
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export autofocus result", "", "JSON (*.json)")
            if path:
                self.write_json(path, {
                    "schema_version": 2, "settings": self.logic.run_settings.to_dict(),
                    "outcome": self.logic.last_outcome, "error": self.logic.last_error,
                    "result": self.logic.result.to_dict() if self.logic.result else None,
                    "samples": [asdict(s) for s in self.logic.history],
                })
        except Exception as exc:
            self.status_label.setText(str(exc))

    def request_connect(self):
        return self._submit(self.logic.connect_z)

    def configure_profile(self, connection):
        if str(connection.get("address", "")).strip():
            raise ValueError("Leave the autofocus address blank; configure COM ports on the actuator's own device row")

    def stop_scan(self):
        self.logic.stop_scan()

    def start_scan(self):
        self.logic.start_scan()

    def force_stop(self):
        return self.logic.force_stop()

    def terminate_dev(self):
        return self.logic.terminate_dev()


if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    panel = AutofocusMain()
    panel.show()
    app.aboutToQuit.connect(panel.terminate_dev)
    app.exec()
