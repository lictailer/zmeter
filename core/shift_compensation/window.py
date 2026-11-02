"""Shift Compensation window: one block per mapping.

Each block holds the CSV, the four channels, the fit choice and options,
the fit result, the reference value, a plot of points and fit, and the
Active switch.  An active mapping is read-only; deactivate it to edit.

Catalog-changing actions (activate, deactivate, delete or replace active
mappings) go through ``apply_change(mutate)``, which the main window
refuses while a scan runs or while a queued scan still uses a compensated
channel.
"""

from __future__ import annotations

import datetime as _dt
import os
from typing import Callable

from PyQt6 import QtCore, QtWidgets

from ..nested_menu import NestedMenu
from .fitting import (
    MAX_POLYNOMIAL_ORDER,
    MODEL_COSINE,
    MODEL_POLYNOMIAL,
    MappingCsvError,
    load_mapping_csv,
)
from .logic import Mapping, ShiftCompensationLogic, evaluate_points
from .persistence import SET_FILE_FILTER, MappingSetError, load_set, save_set

NO_CHOICES = [{"none": ["none"]}]


def _choices(channel_maps: dict) -> list:
    choices = [
        {label: list(channels)}
        for label, channels in channel_maps.items()
        if channels
    ]
    return choices or list(NO_CHOICES)


class MappingPlotWindow(QtWidgets.QWidget):
    """CSV points and the fitted curve of one mapping."""

    def __init__(self, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        import pyqtgraph as pg

        self.resize(560, 520)
        layout = QtWidgets.QVBoxLayout(self)
        self.plot = pg.PlotWidget()
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.addLegend()
        layout.addWidget(self.plot, 3)
        self.points = self.plot.plot(
            [], [], pen=None, symbol="o", symbolSize=7, name="CSV points"
        )
        self.curve = self.plot.plot([], [], pen=pg.mkPen(width=2), name="fit")
        self.reference = pg.InfiniteLine(angle=90, movable=False)
        self.plot.addItem(self.reference)
        self.residual_plot = pg.PlotWidget()
        self.residual_plot.showGrid(x=True, y=True, alpha=0.3)
        self.residual_plot.setLabel("left", "residual")
        self.residual_plot.setXLink(self.plot)
        self.residual_plot.addItem(pg.InfiniteLine(pos=0, angle=0, movable=False))
        layout.addWidget(self.residual_plot, 1)
        self.residuals = self.residual_plot.plot(
            [], [], pen=None, symbol="o", symbolSize=5
        )

    def show_mapping(self, mapping: Mapping) -> None:
        self.setWindowTitle(f"Shift compensation fit: {mapping.display_name}")
        self.plot.setLabel("bottom", mapping.source_read or "source")
        self.plot.setLabel("left", f"shift added to {mapping.target_set or 'target'}")
        self.points.setData(list(mapping.source_values), list(mapping.shift_values))
        x, y = evaluate_points(mapping)
        self.curve.setData(x, y)
        if mapping.fit is not None and mapping.source_values:
            residual = [
                float(shift - mapping.fit.evaluate(source))
                for source, shift in zip(mapping.source_values, mapping.shift_values)
            ]
            self.residuals.setData(list(mapping.source_values), residual)
        else:
            self.residuals.setData([], [])
        self.residual_plot.setLabel("bottom", mapping.source_read or "source")
        try:
            self.reference.setValue(mapping.reference_value())
            self.reference.show()
        except Exception:  # noqa: BLE001 - no points yet
            self.reference.hide()


class MappingBlock(QtWidgets.QGroupBox):
    """Editor for one mapping."""

    def __init__(self, window: "ShiftCompensationWindow", mapping: Mapping):
        super().__init__()
        self._window = window
        self.mapping_id = mapping.mapping_id
        self._plot_window: MappingPlotWindow | None = None
        self._refreshing = False
        self._build()
        self.refresh(mapping)

    # ------------------------------------------------------------ build
    def _build(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        top = QtWidgets.QHBoxLayout()
        top.addWidget(QtWidgets.QLabel("Name"))
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("source → target")
        top.addWidget(self.name_edit, 1)
        self.csv_button = QtWidgets.QPushButton("Load CSV…")
        top.addWidget(self.csv_button)
        self.csv_label = QtWidgets.QLabel("no CSV")
        top.addWidget(self.csv_label, 1)
        layout.addLayout(top)

        grid = QtWidgets.QGridLayout()
        self.source_set_menu = NestedMenu(d=NO_CHOICES)
        self.source_read_menu = NestedMenu(d=NO_CHOICES)
        self.target_set_menu = NestedMenu(d=NO_CHOICES)
        self.target_read_menu = NestedMenu(d=NO_CHOICES)
        for menu, text in (
            (self.source_set_menu, "Source set: "),
            (self.source_read_menu, "Source read: "),
            (self.target_set_menu, "Target set: "),
            (self.target_read_menu, "Target read: "),
        ):
            menu.label.setText(text)
            menu.label.setMinimumWidth(80)
            menu.button.setFixedWidth(220)
        grid.addWidget(self.source_set_menu, 0, 0)
        grid.addWidget(self.source_read_menu, 0, 1)
        grid.addWidget(self.target_set_menu, 1, 0)
        grid.addWidget(self.target_read_menu, 1, 1)
        layout.addLayout(grid)

        fit_row = QtWidgets.QHBoxLayout()
        fit_row.addWidget(QtWidgets.QLabel("Fit"))
        self.cosine_radio = QtWidgets.QRadioButton("Cosine")
        self.cosine_radio.setToolTip("y = A cos(2πx/P + C) + D")
        self.polynomial_radio = QtWidgets.QRadioButton("Polynomial")
        self.model_group = QtWidgets.QButtonGroup(self)
        self.model_group.addButton(self.cosine_radio)
        self.model_group.addButton(self.polynomial_radio)
        fit_row.addWidget(self.cosine_radio)
        fit_row.addWidget(self.polynomial_radio)

        self.cosine_options = QtWidgets.QWidget()
        cosine_layout = QtWidgets.QHBoxLayout(self.cosine_options)
        cosine_layout.setContentsMargins(12, 0, 0, 0)
        cosine_layout.addWidget(QtWidgets.QLabel("Period"))
        self.period_edit = QtWidgets.QLineEdit()
        self.period_edit.setFixedWidth(90)
        self.period_edit.setToolTip(
            "Source units per cycle, e.g. 360 for degrees or 6.2832 for radians"
        )
        cosine_layout.addWidget(self.period_edit)
        self.free_period_check = QtWidgets.QCheckBox("Free period")
        self.free_period_check.setToolTip(
            "Fit the period too, starting from the value in the box"
        )
        cosine_layout.addWidget(self.free_period_check)
        fit_row.addWidget(self.cosine_options)

        self.polynomial_options = QtWidgets.QWidget()
        poly_layout = QtWidgets.QHBoxLayout(self.polynomial_options)
        poly_layout.setContentsMargins(12, 0, 0, 0)
        poly_layout.addWidget(QtWidgets.QLabel("Order"))
        self.order_spin = QtWidgets.QSpinBox()
        self.order_spin.setRange(1, MAX_POLYNOMIAL_ORDER)
        poly_layout.addWidget(self.order_spin)
        fit_row.addWidget(self.polynomial_options)

        fit_row.addStretch(1)
        self.fit_button = QtWidgets.QPushButton("Fit")
        fit_row.addWidget(self.fit_button)
        self.plot_button = QtWidgets.QPushButton("Show plot")
        fit_row.addWidget(self.plot_button)
        layout.addLayout(fit_row)

        self.result_label = QtWidgets.QLabel("not fitted")
        self.result_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        bottom = QtWidgets.QHBoxLayout()
        bottom.addWidget(QtWidgets.QLabel("Reference source value"))
        self.x_ref_edit = QtWidgets.QLineEdit()
        self.x_ref_edit.setFixedWidth(110)
        self.x_ref_edit.setToolTip(
            "Source value at which the compensated target equals the requested "
            "value. Empty: the first source value of the CSV."
        )
        bottom.addWidget(self.x_ref_edit)
        bottom.addStretch(1)
        self.active_check = QtWidgets.QCheckBox("Active")
        self.active_check.setToolTip(
            "Publish compensated_source_/compensated_target_ channels for "
            "this mapping"
        )
        bottom.addWidget(self.active_check)
        self.delete_button = QtWidgets.QPushButton("Delete")
        bottom.addWidget(self.delete_button)
        layout.addLayout(bottom)

        self.note_label = QtWidgets.QLabel("")
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("color: #b3261e;")
        layout.addWidget(self.note_label)

        self.name_edit.editingFinished.connect(self._on_name_changed)
        self.csv_button.clicked.connect(self._on_load_csv)
        for menu, key in (
            (self.source_set_menu, "source_set"),
            (self.source_read_menu, "source_read"),
            (self.target_set_menu, "target_set"),
            (self.target_read_menu, "target_read"),
        ):
            menu.sig_self_changed.connect(
                lambda _menu, key=key, menu=menu: self._on_channel_changed(key, menu)
            )
        self.cosine_radio.toggled.connect(self._on_model_changed)
        self.period_edit.editingFinished.connect(self._on_options_changed)
        self.free_period_check.toggled.connect(self._on_options_changed)
        self.order_spin.valueChanged.connect(self._on_options_changed)
        self.fit_button.clicked.connect(self._on_fit)
        self.plot_button.clicked.connect(self._on_show_plot)
        self.x_ref_edit.editingFinished.connect(self._on_x_ref_changed)
        self.active_check.clicked.connect(self._on_active_clicked)
        self.delete_button.clicked.connect(self._on_delete)

    # ------------------------------------------------------------ helpers
    @property
    def logic(self) -> ShiftCompensationLogic:
        return self._window.logic

    def mapping(self) -> Mapping:
        return self.logic.get(self.mapping_id)

    def _edit_widgets(self):
        return (
            self.name_edit,
            self.csv_button,
            self.source_set_menu,
            self.source_read_menu,
            self.target_set_menu,
            self.target_read_menu,
            self.cosine_radio,
            self.polynomial_radio,
            self.period_edit,
            self.free_period_check,
            self.order_spin,
            self.fit_button,
            self.x_ref_edit,
        )

    def set_channel_choices(self, setter_choices, getter_choices) -> None:
        self._refreshing = True
        try:
            self.source_set_menu.set_choices(setter_choices)
            self.target_set_menu.set_choices(setter_choices)
            self.source_read_menu.set_choices(getter_choices)
            self.target_read_menu.set_choices(getter_choices)
        finally:
            self._refreshing = False

    @staticmethod
    def _set_menu(menu: NestedMenu, channel: str) -> None:
        current = menu.name or menu.unresolved_name
        if channel == current:
            return
        if channel:
            menu._apply_selection(channel)
        else:
            menu.name = ""
            menu.unresolved_name = ""
            menu.button.setText("")
            menu.button.setToolTip("")

    def refresh(self, mapping: Mapping) -> None:
        self._refreshing = True
        try:
            self.setTitle(mapping.display_name + ("   [active]" if mapping.active else ""))
            if not self.name_edit.hasFocus():
                self.name_edit.setText(mapping.name)
            if mapping.source_values:
                label = mapping.csv_name or "points"
                self.csv_label.setText(
                    f"{label}: {len(mapping.source_values)} points, source "
                    f"{min(mapping.source_values):g} to {max(mapping.source_values):g}, "
                    f"shift {min(mapping.shift_values):.4g} to {max(mapping.shift_values):.4g}"
                )
                preview = "\n".join(
                    f"{source:g}\t{shift:.6g}"
                    for source, shift in list(
                        zip(mapping.source_values, mapping.shift_values)
                    )[:12]
                )
                if len(mapping.source_values) > 12:
                    preview += "\n…"
                self.csv_label.setToolTip("source\tshift\n" + preview)
            else:
                self.csv_label.setText("no CSV")
                self.csv_label.setToolTip("")
            self._set_menu(self.source_set_menu, mapping.source_set)
            self._set_menu(self.source_read_menu, mapping.source_read)
            self._set_menu(self.target_set_menu, mapping.target_set)
            self._set_menu(self.target_read_menu, mapping.target_read)
            cosine = mapping.model == MODEL_COSINE
            self.cosine_radio.setChecked(cosine)
            self.polynomial_radio.setChecked(not cosine)
            self.cosine_options.setVisible(cosine)
            self.polynomial_options.setVisible(not cosine)
            if not self.period_edit.hasFocus():
                self.period_edit.setText(f"{float(mapping.options.get('period', 360.0)):g}")
            self.free_period_check.setChecked(bool(mapping.options.get("free_period", False)))
            self.order_spin.setValue(int(mapping.options.get("order", 1)))
            if mapping.fit is None:
                self.result_label.setText("not fitted")
            else:
                fit = mapping.fit
                self.result_label.setText(
                    f"{fit.describe()}    rms = {fit.rms:.4g}, R² = {fit.r2:.4f}, "
                    f"{fit.n_points} points"
                )
            if not self.x_ref_edit.hasFocus():
                self.x_ref_edit.setText("" if mapping.x_ref is None else f"{mapping.x_ref:g}")
            if mapping.source_values:
                self.x_ref_edit.setPlaceholderText(f"{mapping.source_values[0]:g}")
            else:
                self.x_ref_edit.setPlaceholderText("first CSV value")
            self.active_check.setChecked(mapping.active)
            busy = self._window.busy
            for widget in self._edit_widgets():
                widget.setEnabled(not mapping.active and not busy)
            self.active_check.setEnabled(
                not busy and (mapping.active or mapping.fit is not None)
            )
            self.delete_button.setEnabled(not busy)
            self.note_label.setText(mapping.note)
            self.note_label.setVisible(bool(mapping.note))
        finally:
            self._refreshing = False
        if self._plot_window is not None and self._plot_window.isVisible():
            self._plot_window.show_mapping(mapping)

    def _run(self, action: Callable, failure: str):
        try:
            return action()
        except Exception as exc:  # noqa: BLE001 - shown to the operator
            self._window.report(f"{failure}: {exc}", error=True)
            self._window.refresh_blocks()
            return None

    # ------------------------------------------------------------ slots
    def _on_name_changed(self):
        if self._refreshing:
            return
        name = self.name_edit.text().strip()
        if name == self.mapping().name:
            return
        self._run(
            lambda: self.logic.update_mapping(self.mapping_id, name=name),
            "Rename failed",
        )

    def _on_load_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load mapping CSV",
            self._window._start_folder(),
            "CSV files (*.csv *.txt);;All files (*)",
        )
        if path:
            self.load_csv(path)

    def load_csv(self, path: str) -> bool:
        try:
            source, shift = load_mapping_csv(path)
        except MappingCsvError as exc:
            self._window.report(f"CSV not loaded: {exc}", error=True)
            return False
        self._window.last_folder = os.path.dirname(path)
        result = self._run(
            lambda: self.logic.set_points(
                self.mapping_id, source, shift, csv_name=os.path.basename(path)
            ),
            "CSV not loaded",
        )
        if result is not None:
            self._window.report(
                f"Loaded {len(source)} points from {os.path.basename(path)}."
            )
        return result is not None

    def _on_channel_changed(self, key: str, menu: NestedMenu):
        if self._refreshing:
            return
        channel = menu.name or ""
        if channel.lower() in {"none", "void", "none_none"}:
            channel = ""
        if getattr(self.mapping(), key) == channel:
            return
        self._run(
            lambda: self.logic.update_mapping(self.mapping_id, **{key: channel}),
            "Channel not changed",
        )

    def _on_model_changed(self, _checked=None):
        if self._refreshing:
            return
        model = MODEL_COSINE if self.cosine_radio.isChecked() else MODEL_POLYNOMIAL
        self.cosine_options.setVisible(model == MODEL_COSINE)
        self.polynomial_options.setVisible(model == MODEL_POLYNOMIAL)
        if model == self.mapping().model:
            return
        self._run(
            lambda: self.logic.update_mapping(self.mapping_id, model=model),
            "Model not changed",
        )

    def _read_options(self) -> dict | None:
        try:
            period = float(self.period_edit.text().strip())
        except ValueError:
            self._window.report("The period must be a number.", error=True)
            return None
        return {
            "period": period,
            "free_period": self.free_period_check.isChecked(),
            "order": int(self.order_spin.value()),
        }

    def _on_options_changed(self, *_args):
        if self._refreshing:
            return
        options = self._read_options()
        if options is None or options == {
            key: self.mapping().options.get(key) for key in options
        }:
            return
        self._run(
            lambda: self.logic.update_mapping(self.mapping_id, options=options),
            "Options not changed",
        )

    def _on_fit(self):
        options = self._read_options()
        if options is None:
            return
        model = MODEL_COSINE if self.cosine_radio.isChecked() else MODEL_POLYNOMIAL
        result = self._run(
            lambda: self.logic.fit(self.mapping_id, model=model, options=options),
            "Fit failed",
        )
        if result is not None:
            self._window.report(f"{self.mapping().display_name}: {result.describe()}")
            if self._plot_window is not None and self._plot_window.isVisible():
                self._plot_window.show_mapping(self.mapping())

    def _on_show_plot(self):
        if self._plot_window is None:
            self._plot_window = MappingPlotWindow()
        self._plot_window.show_mapping(self.mapping())
        self._plot_window.show()
        self._plot_window.raise_()
        self._plot_window.activateWindow()

    def _on_x_ref_changed(self):
        if self._refreshing:
            return
        text = self.x_ref_edit.text().strip()
        if text == "":
            x_ref = None
        else:
            try:
                x_ref = float(text)
            except ValueError:
                self._window.report("The reference value must be a number.", error=True)
                self.refresh(self.mapping())
                return
        if x_ref == self.mapping().x_ref:
            return
        self._run(
            lambda: self.logic.update_mapping(self.mapping_id, x_ref=x_ref),
            "Reference not changed",
        )

    def _on_active_clicked(self, checked: bool):
        if self._refreshing:
            return
        if checked:
            done = self._run(
                lambda: self._window.apply_change(
                    lambda: self.logic.activate(self.mapping_id)
                ),
                "Not activated",
            )
            if done is not None:
                self._window.report(f"{self.mapping().display_name} is active.")
        else:
            done = self._run(
                lambda: self._window.apply_change(
                    lambda: self.logic.deactivate(self.mapping_id)
                ),
                "Not deactivated",
            )
            if done is not None:
                self._window.report(f"{self.mapping().display_name} is inactive.")
        self._window.refresh_blocks()

    def _on_delete(self):
        mapping = self.mapping()
        answer = QtWidgets.QMessageBox.question(
            self,
            "Delete mapping",
            f"Delete {mapping.display_name}?",
        )
        if answer != QtWidgets.QMessageBox.StandardButton.Yes:
            return
        self._window.delete_mapping(self.mapping_id)

    def close_plot(self):
        if self._plot_window is not None:
            self._plot_window.close()
            self._plot_window.deleteLater()
            self._plot_window = None


class ValueRecordWindow(QtWidgets.QWidget):
    """Read-only table of the main-window value record."""

    def __init__(self, value_record, parent=None):
        super().__init__(parent, QtCore.Qt.WindowType.Window)
        self._record = value_record
        self.setWindowTitle("Channel value record")
        self.resize(620, 420)
        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            "Newest value of each channel written or read through the main "
            "window or recorded by a scan snapshot. Values set from a device "
            "panel are not seen."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Channel", "Value", "Origin", "Time"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        refresh = QtWidgets.QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh, 0, QtCore.Qt.AlignmentFlag.AlignRight)

    def refresh(self):
        entries = self._record.entries() if self._record is not None else []
        self.table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            stamp = _dt.datetime.fromtimestamp(entry.time).strftime("%H:%M:%S")
            for column, text in enumerate(
                (entry.channel, f"{entry.value!r}" if not isinstance(entry.value, float) else f"{entry.value:.6g}", entry.origin, stamp)
            ):
                self.table.setItem(row, column, QtWidgets.QTableWidgetItem(str(text)))
        self.table.resizeColumnsToContents()


class ShiftCompensationWindow(QtWidgets.QWidget):
    """Stack of mapping blocks with Add, Save set and Load set."""

    def __init__(
        self,
        logic: ShiftCompensationLogic,
        apply_change: Callable[[Callable], object],
        value_record=None,
        parent=None,
        busy_reason: Callable[[], str] | None = None,
        default_folder: Callable[[], str] | None = None,
    ):
        super().__init__(parent)
        self.logic = logic
        self._apply_change = apply_change
        self._value_record = value_record
        self._busy_reason = busy_reason
        self._default_folder = default_folder
        self.busy = False
        self.busy_text = ""
        self._blocks: dict[str, MappingBlock] = {}
        self._setter_choices = list(NO_CHOICES)
        self._getter_choices = list(NO_CHOICES)
        self._record_window: ValueRecordWindow | None = None
        self.last_folder = ""
        self.setWindowTitle("Shift Compensation")
        self.resize(820, 720)
        self._build()
        logic.sig_changed.connect(self.refresh_blocks)
        self._busy_timer = QtCore.QTimer(self)
        self._busy_timer.setInterval(500)
        self._busy_timer.timeout.connect(self.update_busy)
        self.refresh_blocks()
        self.update_busy()

    def showEvent(self, event):
        super().showEvent(event)
        self.update_busy()
        self._busy_timer.start()

    def hideEvent(self, event):
        self._busy_timer.stop()
        super().hideEvent(event)

    def update_busy(self) -> None:
        """Lock editing while a scan, queue item or catalog change runs."""

        reason = ""
        if self._busy_reason is not None:
            try:
                reason = str(self._busy_reason() or "")
            except Exception as exc:  # noqa: BLE001 - lock on doubt
                reason = f"{type(exc).__name__}: {exc}"
        busy = bool(reason)
        if busy == self.busy and reason == self.busy_text:
            return
        self.busy = busy
        self.busy_text = reason
        for button in (self.add_button, self.load_button):
            button.setEnabled(not busy)
        self.busy_label.setText(f"Locked while busy: {reason}" if busy else "")
        self.busy_label.setVisible(busy)
        self.refresh_blocks()

    def _start_folder(self) -> str:
        if self.last_folder:
            return self.last_folder
        if self._default_folder is not None:
            try:
                return str(self._default_folder() or "")
            except Exception:  # noqa: BLE001
                return ""
        return ""

    def _build(self):
        layout = QtWidgets.QVBoxLayout(self)
        intro = QtWidgets.QLabel(
            "Each mapping adds f(source) to the target so the target stays on "
            "the same physical spot when the source moves. Active mappings add "
            "compensated_source_<channel> and compensated_target_<channel> to "
            "the scan channel menus."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        bar = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("Add mapping")
        self.save_button = QtWidgets.QPushButton("Save set…")
        self.load_button = QtWidgets.QPushButton("Load set…")
        self.record_button = QtWidgets.QPushButton("Value record")
        for button in (self.add_button, self.save_button, self.load_button):
            bar.addWidget(button)
        bar.addStretch(1)
        bar.addWidget(self.record_button)
        layout.addLayout(bar)

        self.published_label = QtWidgets.QLabel("")
        self.published_label.setWordWrap(True)
        self.published_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.published_label)
        self.busy_label = QtWidgets.QLabel("")
        self.busy_label.setStyleSheet("color: #8a5a00;")
        self.busy_label.setWordWrap(True)
        self.busy_label.hide()
        layout.addWidget(self.busy_label)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        container = QtWidgets.QWidget()
        self.blocks_layout = QtWidgets.QVBoxLayout(container)
        self.blocks_layout.addStretch(1)
        self.scroll.setWidget(container)
        layout.addWidget(self.scroll, 1)

        self.status_label = QtWidgets.QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.status_label)

        self.add_button.clicked.connect(self.add_mapping)
        self.save_button.clicked.connect(self._on_save_set)
        self.load_button.clicked.connect(self._on_load_set)
        self.record_button.clicked.connect(self._on_show_record)

    # ------------------------------------------------------------ public
    def report(self, message: str, error: bool = False) -> None:
        self.status_label.setStyleSheet("color: #b3261e;" if error else "")
        self.status_label.setText(message)

    def apply_change(self, mutate: Callable):
        return self._apply_change(mutate)

    def block(self, mapping_id: str) -> MappingBlock:
        return self._blocks[mapping_id]

    def blocks(self) -> list[MappingBlock]:
        return [self._blocks[m.mapping_id] for m in self.logic.mappings() if m.mapping_id in self._blocks]

    def refresh_channel_choices(self, setter_maps: dict, getter_maps: dict) -> None:
        self._setter_choices = _choices(setter_maps)
        self._getter_choices = _choices(getter_maps)
        for block in self._blocks.values():
            block.set_channel_choices(self._setter_choices, self._getter_choices)
        self.refresh_blocks()

    def refresh_blocks(self) -> None:
        sources, targets = self.logic.published_channels()
        names = [f"compensated_source_{c}" for c in sources] + [
            f"compensated_target_{c}" for c in targets
        ]
        self.published_label.setText(
            "Published scan channels: " + (", ".join(names) if names else "none")
        )
        mappings = self.logic.mappings()
        wanted = {m.mapping_id for m in mappings}
        for mapping_id in list(self._blocks):
            if mapping_id not in wanted:
                block = self._blocks.pop(mapping_id)
                block.close_plot()
                self.blocks_layout.removeWidget(block)
                block.setParent(None)
                block.deleteLater()
        for index, mapping in enumerate(mappings):
            block = self._blocks.get(mapping.mapping_id)
            if block is None:
                block = MappingBlock(self, mapping)
                block.set_channel_choices(self._setter_choices, self._getter_choices)
                self._blocks[mapping.mapping_id] = block
            if self.blocks_layout.indexOf(block) != index:
                self.blocks_layout.removeWidget(block)
                self.blocks_layout.insertWidget(index, block)
            block.refresh(mapping)

    def add_mapping(self) -> Mapping:
        mapping = self.logic.add_mapping()
        self.report("Added a mapping. Load its CSV, choose the channels, then Fit.")
        return mapping

    def delete_mapping(self, mapping_id: str) -> bool:
        mapping = self.logic.get(mapping_id)
        try:
            if mapping.active:
                self.apply_change(lambda: self.logic.remove_mapping(mapping_id))
            else:
                self.logic.remove_mapping(mapping_id)
        except Exception as exc:  # noqa: BLE001 - shown to the operator
            self.report(f"Not deleted: {exc}", error=True)
            self.refresh_blocks()
            return False
        self.report(f"Deleted {mapping.display_name}.")
        return True

    def save_set(self, path: str) -> bool:
        try:
            save_set(path, self.logic.mappings())
        except Exception as exc:  # noqa: BLE001
            self.report(f"Set not saved: {exc}", error=True)
            return False
        self.last_folder = os.path.dirname(path)
        self.report(f"Saved {len(self.logic.mappings())} mapping(s) to {path}.")
        return True

    def load_set(self, path: str) -> bool:
        try:
            mappings = load_set(path)
        except MappingSetError as exc:
            self.report(f"Set not loaded: {exc}", error=True)
            return False
        try:
            if any(m.active for m in mappings) or any(
                m.active for m in self.logic.mappings()
            ):
                notes = self.apply_change(lambda: self.logic.load_mappings(mappings))
            else:
                notes = self.logic.load_mappings(mappings)
        except Exception as exc:  # noqa: BLE001
            self.report(f"Set not loaded: {exc}", error=True)
            self.refresh_blocks()
            return False
        self.last_folder = os.path.dirname(path)
        active = sum(1 for m in self.logic.mappings() if m.active)
        message = f"Loaded {len(mappings)} mapping(s) from {path}; {active} active."
        if notes:
            message += " Not activated: " + " | ".join(notes)
        self.report(message, error=bool(notes))
        return True

    # ------------------------------------------------------------ slots
    def _on_save_set(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save shift compensation set",
            os.path.join(self._start_folder(), "shift_compensation_set.json"),
            SET_FILE_FILTER,
        )
        if path:
            self.save_set(path)

    def _on_load_set(self):
        if self.logic.mappings():
            answer = QtWidgets.QMessageBox.question(
                self,
                "Load set",
                "Loading a set replaces every mapping in this window. Continue?",
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Load shift compensation set", self._start_folder(), SET_FILE_FILTER
        )
        if path:
            self.load_set(path)

    def _on_show_record(self):
        if self._record_window is None:
            self._record_window = ValueRecordWindow(self._value_record)
        self._record_window.refresh()
        self._record_window.show()
        self._record_window.raise_()
        self._record_window.activateWindow()

    def closeEvent(self, event):
        for block in self._blocks.values():
            block.close_plot()
        if self._record_window is not None:
            self._record_window.close()
        super().closeEvent(event)
