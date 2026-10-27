"""PyQt6 reference-map and auto-position panel. All instrument I/O is in workers."""
import json

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from core.device_log import append_device_log, configure_device_log
from core.measurement_io import RouterIO
from core.measurement_widgets import ChannelPicker
from .position_engine import MapSettings, PositionSettings, RegistrationSettings
from .position_logic import AutoPositionLogic


class MapNumber(QtWidgets.QDoubleSpinBox):
    """Keep the compact scan row readable without hiding stored decimal places."""

    def textFromValue(self, value):
        return f"{value:.{self.decimals()}f}".rstrip("0").rstrip(".") or "0"


class MapAxisEditor(QtWidgets.QWidget):
    """UI-only views of one map axis; endpoints/point count remain canonical."""
    sig_error = QtCore.pyqtSignal(str)

    def __init__(self, start, end, points):
        super().__init__()
        grid = QtWidgets.QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        self.fields = {}
        for column, (key, label) in enumerate((("start", "Start"), ("end", "End"),
                ("step", "Step"), ("mid", "Midpoint"), ("span", "Range (span)"), ("points", "Points"))):
            title = QtWidgets.QLabel(label)
            title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(title, 0, column)
            field = QtWidgets.QSpinBox() if key == "points" else MapNumber()
            if key == "points":
                field.setRange(7, 512)
            else:
                field.setDecimals(12 if key == "step" else 10 if key == "mid" else 9)
                field.setRange(0 if key == "span" else -1e9, 2e9 if key in ("span", "step") else 1e9)
            field.setKeyboardTracking(False)
            field.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            field.setMinimumWidth(60)
            field.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored, QtWidgets.QSizePolicy.Policy.Fixed)
            grid.addWidget(field, 1, column)
            grid.setColumnStretch(column, 1)
            self.fields[key] = field
        self.fields["step"].setToolTip("Pixel spacing = (End - Start) / (Points - 1). Editing Step selects the nearest whole point count (7–512).")
        self.fields["span"].setToolTip("Full width, not a radius. Start = Midpoint - Range/2; End = Midpoint + Range/2.")
        self.fields["start"].setValue(start)
        self.fields["end"].setValue(end)
        self.fields["points"].setValue(points)
        self.refresh()
        for key in ("start", "end", "points"):
            self.fields[key].valueChanged.connect(self.refresh)
        for key in ("mid", "span"):
            self.fields[key].valueChanged.connect(self._center_changed)
        self.fields["step"].valueChanged.connect(self._step_changed)

    def _set_values(self, **values):
        blockers = [QtCore.QSignalBlocker(self.fields[key]) for key in values]
        for key, value in values.items():
            self.fields[key].setValue(value)
        # Keep blockers alive until all related controls have been updated.
        del blockers

    def refresh(self):
        start, end = self.fields["start"].value(), self.fields["end"].value()
        self._set_values(mid=(start + end) / 2, span=end - start,
                         step=(end - start) / (self.fields["points"].value() - 1))

    def _center_changed(self):
        mid, span = self.fields["mid"].value(), self.fields["span"].value()
        start, end = mid - span / 2, mid + span / 2
        if start < self.fields["start"].minimum() or end > self.fields["end"].maximum():
            self.refresh()
            self.sig_error.emit("Map midpoint/range exceeds the editor's numeric range; endpoints were not changed.")
            return
        self._set_values(start=start, end=end)
        self.refresh()

    def _step_changed(self):
        span = self.fields["end"].value() - self.fields["start"].value()
        step = self.fields["step"].value()
        if span <= 0 or step <= 0:
            self.refresh()
            self.sig_error.emit("Map Step needs increasing Start/End and positive pixel spacing; point count was not changed.")
            return
        points = round(span / step) + 1
        if not self.fields["points"].minimum() <= points <= self.fields["points"].maximum():
            self.refresh()
            self.sig_error.emit("Map Step would require a point count outside 7–512; point count was not changed.")
            return
        self._set_values(points=points)
        self.refresh()


class MapView(QtWidgets.QWidget):
    sig_point = QtCore.pyqtSignal(float, float)

    def __init__(self, title):
        super().__init__()
        self.title, self.image, self.geometry, self.point = title, None, None, None
        self.setMinimumSize(310, 200)

    def area(self):
        return QtCore.QRectF(55, 26, max(1, self.width() - 75), max(1, self.height() - 66))

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.fillRect(self.rect(), QtGui.QColor("white"))
        p.setPen(QtGui.QColor("#333333"))
        p.drawText(10, 18, self.title)
        area = self.area()
        if self.image is None:
            p.drawText(area, QtCore.Qt.AlignmentFlag.AlignCenter, "No map acquired")
            return
        values = np.asarray(self.image)
        finite = values[np.isfinite(values)]
        if not finite.size:
            return
        lo, hi = float(finite.min()), float(finite.max())
        pixels = np.ascontiguousarray(np.nan_to_num(np.clip((values[::-1] - lo) / max(hi - lo, 1e-30) * 255, 0, 255), nan=0).astype(np.uint8))
        image = QtGui.QImage(pixels.data, pixels.shape[1], pixels.shape[0], pixels.strides[0], QtGui.QImage.Format.Format_Grayscale8).copy()
        p.drawImage(area, image)
        p.drawRect(area)
        g = self.geometry
        p.drawText(55, self.height() - 22, f"{g.x_min:g}")
        p.drawText(self.width() - 70, self.height() - 22, f"{g.x_max:g}")
        p.drawText(2, 42, f"{g.y_max:g}")
        p.drawText(2, self.height() - 42, f"{g.y_min:g}")
        p.drawText(self.width() // 2 - 35, self.height() - 4, f"X ({g.x_unit}); Y ({g.y_unit})")
        if self.point is not None:
            x = area.left() + (self.point[0] - g.x_min) / (g.x_max - g.x_min) * area.width()
            y = area.bottom() - (self.point[1] - g.y_min) / (g.y_max - g.y_min) * area.height()
            p.setPen(QtGui.QPen(QtGui.QColor("#ff2828"), 2))
            p.drawLine(QtCore.QPointF(x - 7, y), QtCore.QPointF(x + 7, y))
            p.drawLine(QtCore.QPointF(x, y - 7), QtCore.QPointF(x, y + 7))

    def mousePressEvent(self, event):
        area = self.area()
        if self.image is not None and self.geometry is not None and area.contains(event.position()):
            g = self.geometry
            x = g.x_min + (event.position().x() - area.left()) / area.width() * (g.x_max - g.x_min)
            y = g.y_min + (area.bottom() - event.position().y()) / area.height() * (g.y_max - g.y_min)
            self.sig_point.emit(x, y)


class AutoPositionMain(QtWidgets.QWidget):
    route_commands_in_background = True

    def __init__(self, logic=None):
        super().__init__()
        self.logic, self._router = logic or AutoPositionLogic(), None
        self.fields, self.pickers, self.buttons = {}, {}, []
        self._busy = False
        self.setWindowTitle("Auto position")
        self.resize(1100, 950)
        outer = QtWidgets.QVBoxLayout(self)
        directory = QtWidgets.QHBoxLayout()
        directory.addWidget(QtWidgets.QLabel("Results directory (reference and all new runs)"))
        self.directory = QtWidgets.QLineEdit()
        directory.addWidget(self.directory, 1)
        browse = self._button("Choose…", self._choose_directory)
        directory.addWidget(browse)
        outer.addLayout(directory)
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        self.tabs = QtWidgets.QTabWidget()
        self._reference_tab()
        self._position_tab()
        splitter.addWidget(self.tabs)
        maps = QtWidgets.QSplitter()
        self.reference_view, self.current_view = MapView("Reference map + measurement point"), MapView("New map + corrected point")
        maps.addWidget(self.reference_view)
        maps.addWidget(self.current_view)
        splitter.addWidget(maps)
        self.log = QtWidgets.QPlainTextEdit()
        configure_device_log(self.log)
        splitter.addWidget(self.log)
        splitter.setSizes([470, 260, 130])
        outer.addWidget(splitter, 1)
        actions = QtWidgets.QHBoxLayout()
        self.auto_button = self._button("Auto-position", lambda: self._submit(self.logic.set_position, 1))
        actions.addWidget(self.auto_button)
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.stop_button.clicked.connect(self.logic.force_stop)
        actions.addWidget(self.stop_button)
        actions.addWidget(self._button("Refresh channels", self.refresh_channels))
        actions.addWidget(self._button("Save setup", self._save_setup))
        actions.addWidget(self._button("Load setup", self._load_setup))
        outer.addLayout(actions)
        self.status = QtWidgets.QLabel("Connect X/Y actuators and input in their own panels. Choose a directory, acquire or load a reference map.")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        self.load_controls(self.logic.settings)
        self.logic.sig_busy.connect(self._set_busy)
        self.logic.finished.connect(lambda: self._set_busy(False))
        self.logic.sig_settings.connect(self.load_controls)
        self.logic.sig_reference.connect(self._reference_changed)
        self.logic.sig_map.connect(self._map_changed)
        self.logic.sig_result.connect(self._result_changed)
        self.logic.sig_status.connect(self._status)
        self.logic.sig_error.connect(self._error)
        self.reference_view.sig_point.connect(self._pick_point)
        self.method.currentIndexChanged.connect(self._method_fields)
        self._set_busy(False)

    def _button(self, text, callback):
        button = QtWidgets.QPushButton(text)
        button.clicked.connect(callback)
        self.buttons.append(button)
        return button

    def _tab(self, label):
        page = QtWidgets.QWidget()
        form = QtWidgets.QFormLayout(page)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, label)
        return form

    def _number(self, form, key, label, value, low=-1e9, high=1e9, integer=False):
        field = QtWidgets.QSpinBox() if integer else QtWidgets.QDoubleSpinBox()
        if not integer:
            field.setDecimals(9)
        field.setRange(low, high)
        field.setValue(value)
        self.fields[key] = field
        form.addRow(label, field)

    @staticmethod
    def _note(form, text):
        label = QtWidgets.QLabel(text)
        label.setWordWrap(True)
        form.addRow(label)

    def _reference_tab(self):
        form = self._tab("Reference Map")
        actions = QtWidgets.QHBoxLayout()
        actions.addWidget(self._button("Acquire new reference + go to point", lambda: self._submit(self.logic.acquire_reference)))
        actions.addWidget(self._button("Load reference.json", self._load_reference))
        actions.addWidget(self._button("Save edited point (no motion)", lambda: self._submit(self.logic.save_edited_point)))
        actions.addWidget(self._button("Release reference", lambda: self._submit(self.logic.disconnect)))
        form.addRow(actions)
        for key, label, access in (("x", "X output", "writable"), ("y", "Y output", "writable"),
                                   ("signal", "Measured input (reflection, current, etc.)", "readable")):
            picker = ChannelPicker(access)
            self.pickers[key] = picker
            form.addRow(label, picker)
        g = MapSettings()
        for key in ("x_unit", "y_unit"):
            field = QtWidgets.QLineEdit(getattr(g, key))
            self.fields["map." + key] = field
            form.addRow(key[0].upper() + " output native unit", field)
        self._number(form, "point_x", "Measurement point X", 0)
        self._number(form, "point_y", "Measurement point Y", 0)
        self.map_axes = {}
        for axis in ("x", "y"):
            editor = MapAxisEditor(getattr(g, axis + "_min"), getattr(g, axis + "_max"), getattr(g, axis + "_points"))
            self.map_axes[axis] = editor
            for name, control in (("min", "start"), ("max", "end"), ("points", "points")):
                self.fields[f"map.{axis}_{name}"] = editor.fields[control]
            editor.sig_error.connect(self._error)
            form.addRow("Map " + axis.upper(), editor)
        self._note(form, "Edit Start/End or Midpoint/Range; the other pair updates automatically. Range is the full width. "
                   "Step and Points update each other. The measurement point is independent of the map center.")
        for key, label in (("settle_s", "Settle after XY positioning (s)"), ("sample_interval_s", "Between input readings (s)")):
            self._number(form, "map." + key, label, getattr(g, key), low=0)
        self._number(form, "map.samples", "Input readings per pixel", g.samples, 1, 1000, True)
        self._note(form, "Reference maps are immutable saved copies. Click the reference image to pick a point, then explicitly save the edited point. "
                   "X/Y use their selected devices' native units. Change geometry/channels only by acquiring a new matching reference. "
                   "The input can be any numeric readable channel. Device/global limits remain enforced; there is no extra physical-limit copy here.")

    def _position_tab(self):
        form = self._tab("Auto Position")
        self.method = QtWidgets.QComboBox()
        for label, key in (("Subpixel phase correlation (default)", "phase"),
                           ("Subpixel intensity cross-correlation", "intensity"),
                           ("Bounded normalized overlap correlation", "normalized")):
            self.method.addItem(label, key)
        form.addRow("Translation technique", self.method)
        self.preprocessing = QtWidgets.QComboBox()
        self.preprocessing.addItem("Mean-subtracted, standardized intensity", "intensity")
        self.preprocessing.addItem("Gradient magnitude (edges)", "gradient")
        form.addRow("Features used for registration", self.preprocessing)
        self.hann = QtWidgets.QCheckBox("Hann window for FFT registration")
        form.addRow(self.hann)
        r = RegistrationSettings()
        for key, label, low, high, integer in (
            ("upsample", "FFT subpixel upsample factor", 1, 100, True),
            ("smoothing_sigma", "Gaussian smoothing sigma (pixels; 0 = off)", 0, 20, False),
            ("max_shift_x", "Maximum accepted X displacement (X native unit)", 1e-9, 1e9, False),
            ("max_shift_y", "Maximum accepted Y displacement (Y native unit)", 1e-9, 1e9, False),
            ("minimum_overlap", "Minimum overlapping image fraction", 0.01, 1, False),
            ("minimum_correlation", "Minimum aligned correlation", 0, 1, False),
            ("minimum_peak_margin", "Normalized search: minimum separated-peak margin", 0, 1, False),
        ):
            self._number(form, "registration." + key, label, getattr(r, key), low, high, integer)
        self._note(form, "Each run scans the SAME grid/channels as the fixed reference. Registration estimates translation only, not rotation, scale or deformation. "
                   "Corrected point = original reference point + measured feature displacement. Repeated runs do not add the same shift again. "
                   "Insufficient features, poor correlation/overlap, excessive shift or a point outside the map rejects the final positioning move. "
                   "Stop/error leaves completed commands in place; no automatic return move or device disconnect occurs. Getters report commanded points, not independent position feedback.")

    def read_settings(self):
        groups = {"map": {}, "registration": {}}
        for key, field in self.fields.items():
            if "." not in key:
                continue
            section, name = key.split(".")
            groups[section][name] = field.text().strip() if isinstance(field, QtWidgets.QLineEdit) else field.value()
        groups["map"].update({key: picker.ref() for key, picker in self.pickers.items()})
        groups["registration"].update(method=self.method.currentData(), preprocessing=self.preprocessing.currentData(), hann_window=self.hann.isChecked())
        result = PositionSettings(MapSettings(**groups["map"]), RegistrationSettings(**groups["registration"]),
                                  (self.fields["point_x"].value(), self.fields["point_y"].value()), self.directory.text().strip())
        result.validate()
        return result

    def load_controls(self, settings):
        for key, field in self.fields.items():
            value = settings.point[0 if key == "point_x" else 1] if "." not in key else getattr(getattr(settings, key.split(".")[0]), key.split(".")[1])
            blocker = QtCore.QSignalBlocker(field)
            field.setText(str(value)) if isinstance(field, QtWidgets.QLineEdit) else field.setValue(value)
            del blocker
        for editor in self.map_axes.values():
            editor.refresh()
        for key, picker in self.pickers.items():
            picker.set_ref(getattr(settings.map, key))
        self.directory.setText(settings.directory)
        self.method.setCurrentIndex(self.method.findData(settings.registration.method))
        self.preprocessing.setCurrentIndex(self.preprocessing.findData(settings.registration.preprocessing))
        self.hann.setChecked(settings.registration.hann_window)
        self._method_fields()

    def _method_fields(self):
        normalized = self.method.currentData() == "normalized"
        for key, show in (("registration.upsample", not normalized), ("registration.minimum_peak_margin", normalized)):
            field = self.fields[key]
            field.parentWidget().layout().setRowVisible(field, show)
        self.hann.setVisible(not normalized)

    def _submit(self, operation, *args):
        try:
            self.logic.apply_settings(self.read_settings())
            return self.logic.submit(operation, *args)
        except Exception as exc:
            self._error(str(exc))
            return False

    def _set_busy(self, busy):
        self._busy = busy
        self.tabs.setEnabled(not busy)
        self.directory.setEnabled(not busy)
        for button in self.buttons:
            button.setEnabled(not busy)
        self.auto_button.setEnabled(not busy and self.logic.reference is not None)
        self.stop_button.setEnabled(busy)

    def _status(self, message):
        self.status.setText(message)
        append_device_log(self.log, "INFO", message)

    def _error(self, message):
        self.status.setText("Auto-position error: " + message)
        append_device_log(self.log, "ERROR", message)

    def _reference_changed(self, reference):
        self.reference_view.image = reference.image if reference else None
        self.reference_view.geometry = reference.geometry if reference else None
        self.reference_view.point = reference.point if reference else None
        self.reference_view.update()
        self._set_busy(self._busy)

    def _map_changed(self, item):
        image, row = item
        self.current_view.image, self.current_view.geometry = image, self.logic.settings.map
        self.current_view.point = None
        self.current_view.title = f"Current map: {row}/{self.logic.settings.map.y_points} rows"
        self.current_view.update()

    def _result_changed(self, result):
        self.current_view.point = result.point
        self.current_view.title = f"Corrected point ({result.point[0]:.6g}, {result.point[1]:.6g}); correlation {result.correlation:.4f}"
        self.current_view.update()

    def _pick_point(self, x, y):
        if not self.logic.is_busy():
            self.fields["point_x"].setValue(x)
            self.fields["point_y"].setValue(y)
            self.status.setText("Point picked only. Click Save edited reference point to confirm; no motion has occurred.")

    def _choose_directory(self):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Reference and auto-position results directory")
        if directory:
            self.directory.setText(directory)

    def _load_reference(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load saved reference.json", "", "JSON (*.json)")
        if path:
            self.logic.submit(self.logic.load_reference, path)

    def _load_setup(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Load auto-position setup", "", "JSON (*.json)")
        if path:
            self.logic.submit(self.logic.load_setup, path)

    def _save_setup(self):
        try:
            settings = self.read_settings()
            path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save auto-position setup", "", "JSON (*.json)")
            if path:
                payload = json.dumps(settings.to_dict(), indent=2, allow_nan=False).encode("utf-8")
                output = QtCore.QSaveFile(path)
                if not output.open(QtCore.QIODevice.OpenModeFlag.WriteOnly) or output.write(payload) != len(payload) or not output.commit():
                    raise OSError(output.errorString())
        except Exception as exc:
            self._error(str(exc))

    def configure_command_router(self, router, source_device=None):
        self.logic.configure_command_router(router, source_device)
        self._detach_catalog()
        self._router = router
        signal = getattr(router, "sig_catalog_changed", None)
        if signal is not None:
            signal.connect(self._catalog_changed)
        self.refresh_channels()

    def _detach_catalog(self):
        signal = getattr(self._router, "sig_catalog_changed", None)
        if signal is not None:
            try:
                signal.disconnect(self._catalog_changed)
            except (TypeError, RuntimeError):
                pass

    def detach_command_router(self):
        self.logic.detach_command_router()
        self._detach_catalog()
        self._router = None

    def _catalog_changed(self, catalog):
        for picker in self.pickers.values():
            picker.refresh(catalog)

    def refresh_channels(self):
        if self._router is not None:
            try:
                self._catalog_changed(RouterIO(self._router, self.logic.device_label).refresh())
            except Exception as exc:
                self._error(str(exc))

    def find_catalog_references(self, **kwargs):
        refs = set(self.logic.find_catalog_references(**kwargs))
        for picker in self.pickers.values():
            ref = picker.ref()
            removed = kwargs.get("removed_setters" if picker.access == "writable" else "removed_getters", ())
            if ref.device in kwargs.get("removed_device_labels", ()) or f"{ref.device}_{ref.channel}" in removed:
                refs.add(f"auto-position panel selection: {ref.device}/{ref.channel}")
        return tuple(sorted(refs))

    def configure_profile(self, connection):
        if str(connection.get("address", "")).strip():
            raise ValueError("Leave the auto-position address blank; channels belong to their own devices")

    def request_connect(self): return self.logic.submit(self.logic.check_ready)
    def start_scan(self): return self.logic.start_scan()
    def stop_scan(self): return self.logic.stop_scan()
    def force_stop(self): return self.logic.force_stop()
    def terminate_dev(self): return self.logic.terminate_dev()
