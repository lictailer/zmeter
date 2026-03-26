#!/usr/bin/env python3
"""
UI binding layer for combined autofocus/autoposition XZ feature.

This module keeps UI actions lightweight:
- read values from UI
- call logic methods
- update status/labels/paths
"""

from __future__ import annotations

import os
import sys
import traceback
from functools import partial
from pathlib import Path
from typing import Any

from PyQt6 import QtCore, QtWidgets, uic
import serial.tools.list_ports

try:
    from core.nested_menu import NestedMenu
except ModuleNotFoundError:
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    from core.nested_menu import NestedMenu

try:
    from .autofocusXZ_logic import AutofocusXZLogic
    from .autopositionXZ_helpers import OperationStoppedError
except ImportError:
    from autofocusXZ_logic import AutofocusXZLogic
    from autopositionXZ_helpers import OperationStoppedError


class AutofocusXZMain(QtWidgets.QWidget):
    """Main widget for autofocus/autoposition XZ."""

    def __init__(
        self,
        logic: AutofocusXZLogic | None = None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent=parent)
        ui_path = os.path.join(os.path.dirname(__file__), "autofocusXZ.ui")
        uic.loadUi(ui_path, self)

        self.device_label = "autofocus_xz"
        self.command_router: Any = None
        default_save_path = self.lineSavePath.text().strip() or os.path.join(os.getcwd(), "data")
        self.logic = logic or AutofocusXZLogic(save_path=default_save_path)

        self._channel_catalog: dict[str, Any] = {}
        self._selector_pairs: dict[str, dict[str, Any]] = {}
        self._last_progress_log_line_idx: int | None = None

        self._ensure_status_buttons()
        self._build_channel_selectors()
        self._connect_logic_signals()
        self._connect_ui_signals()

        self._refresh_com_ports()
        self._push_settings_to_logic()
        self._sync_offsets_from_logic()
        self._sync_current_z_from_logic()
        self._sync_report_paths()
        self._set_stepper_status(False)
        self._set_current_status("Idle")
        self._append_status("AutoFocusXZ panel ready.")
        QtCore.QTimer.singleShot(0, self._startup_refresh_channels)

    # ------------------------------------------------------------------
    # Injection / lifecycle hooks
    # ------------------------------------------------------------------
    def configure_command_router(
        self,
        command_router: Any,
        source_device: str | None = None,
    ) -> None:
        if source_device:
            self.device_label = str(source_device)
        self.command_router = command_router
        self.logic.configure_command_router(
            command_router=command_router,
            source_device=self.device_label,
        )
        self._append_status(f"Router injected for {self.device_label}.")
        self._on_refresh_channels()

    def terminate_dev(self) -> None:
        try:
            self.logic.autofocus_hardware.disconnect()
        except Exception:
            pass
        try:
            self.logic.autoposition_hardware.disconnect()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------
    def _connect_logic_signals(self) -> None:
        self.logic.sig_status.connect(self._on_logic_status)
        self.logic.sig_error.connect(self._on_logic_error)
        self.logic.sig_progress.connect(self._on_logic_progress)
        self.logic.sig_xy_offset_changed.connect(self._on_xy_offset_changed)
        self.logic.sig_z_offset_changed.connect(self._on_z_offset_changed)
        self.logic.sig_report_paths_changed.connect(self._on_report_paths_changed)

    def _connect_ui_signals(self) -> None:
        self._connect_click("connect_com_btn", self._on_connect_stepper)
        self._connect_click("disconnect_com_btn", self._on_disconnect_stepper)
        self._connect_click("btn_refreshListChannels", self._on_refresh_channels)
        self._connect_click("btnApplyChannelConfig", self._on_apply_channel_config)
        self._connect_click("btnBrowseSavePath", self._on_browse_save_path)
        self._connect_click("update_settings_btn", self._on_update_settings)

        self._connect_click("btnScanXYReference", self._on_scan_xy_reference)
        self._connect_click("btnLoadXYReference", self._on_load_xy_reference)
        self._connect_click("btnSetXYOffset", self._on_set_xy_offset_from_center)
        self._connect_click("btnMeasureAndSetXYOffset_2", self._on_run_autoposition)
        self._connect_click("btnReadXYOffset", self._on_read_xy_offset)
        self._connect_click("btnClearXYOffsetHistory", self._on_clear_xy_offset)
        self._connect_click("btnExportXYOffsetHistory", self._on_export_xy_history)
        self._connect_click("btnMoveXYHome", self._on_move_xy_home)
        self._connect_click("btnMoveXYAbsHome", self._on_move_xy_abs_home)

        self._connect_click("btnRunAutofocus", self._on_run_autofocus)
        self._connect_click("btnReadZOffset", self._on_read_z_offset)
        self._connect_click("btnClearZOffsetHistory", self._on_clear_z_offset)
        self._connect_click("btnExportZOffsetHistory", self._on_export_z_history)
        self._connect_click("btnCurrentZToZero", self._on_current_z_to_zero)
        self._connect_click("btnReadCurrentZ", self._on_read_current_z)
        self._connect_click("btnMoveZHome", self._on_move_z_home)
        self._connect_click("btnMoveZAbsHome", self._on_move_z_abs_home)

        if hasattr(self, "btnMoveXWithOffset") and hasattr(self, "spinManualXWithOffset"):
            self.btnMoveXWithOffset.clicked.connect(
                lambda: self._run_ui_action(
                    "Move X with offset",
                    lambda: self.logic.set_x_with_offset(self.spinManualXWithOffset.value()),
                )
            )
        if hasattr(self, "btnMoveYWithOffset") and hasattr(self, "spinManualYWithOffset"):
            self.btnMoveYWithOffset.clicked.connect(
                lambda: self._run_ui_action(
                    "Move Y with offset",
                    lambda: self.logic.set_y_with_offset(self.spinManualYWithOffset.value()),
                )
            )
        if hasattr(self, "btnMoveZWithOffset") and hasattr(self, "spinManualZWithOffset"):
            self.btnMoveZWithOffset.clicked.connect(
                lambda: self._run_ui_action(
                    "Move Z with offset",
                    lambda: self.logic.set_z_with_offset(self.spinManualZWithOffset.value()),
                )
            )
        self._connect_click("btnReadXYReferenceValue", self._on_read_xy_reference_value)
        self._connect_click("btnReadZReferenceValue", self._on_read_z_reference_value)
        if hasattr(self, "btnClearStatusLog"):
            self.btnClearStatusLog.clicked.connect(self.statusTextPanel.clear)
        self._connect_click("btnSaveStatusLog", self._on_save_status_log)
        self._connect_click("btnStopOperations", self._on_stop_operations)

    def _connect_click(self, widget_name: str, slot) -> None:
        widget = getattr(self, widget_name, None)
        if widget is not None and hasattr(widget, "clicked"):
            widget.clicked.connect(slot)

    def _ensure_status_buttons(self) -> None:
        layout = self.horizontalLayoutStatus
        if not hasattr(self, "btnSaveStatusLog"):
            self.btnSaveStatusLog = QtWidgets.QPushButton("Save Log")
            self.btnSaveStatusLog.setObjectName("btnSaveStatusLog")
            layout.addWidget(self.btnSaveStatusLog)
        if not hasattr(self, "btnStopOperations"):
            self.btnStopOperations = QtWidgets.QPushButton("Stop")
            self.btnStopOperations.setObjectName("btnStopOperations")
            layout.addWidget(self.btnStopOperations)

    def _startup_refresh_channels(self) -> None:
        try:
            if self.logic.command_router is None:
                return
            self._channel_catalog = self.logic.list_available_channels()
            self._refresh_all_channel_selectors(preserve=True)
            self._append_status("Channel list refreshed on startup.", level="INFO")
        except Exception:
            pass

    def _build_channel_selectors(self) -> None:
        self._selector_pairs = {
            "x_out": {
                "selector": self._replace_combined_channel_with_nested_menu("lineXDevice"),
                "catalog_key": "writable",
            },
            "y_out": {
                "selector": self._replace_combined_channel_with_nested_menu("lineYDevice"),
                "catalog_key": "writable",
            },
            "xy_ref": {
                "selector": self._replace_combined_channel_with_nested_menu("lineXYRefDevice"),
                "catalog_key": "readable",
            },
            "z_ref": {
                "selector": self._replace_combined_channel_with_nested_menu("lineZRefDevice"),
                "catalog_key": "readable",
            },
        }
        for key in self._selector_pairs:
            selector = self._selector_pairs[key]["selector"]
            selector.sig_self_changed.connect(partial(self._on_selector_changed, key))

    def _replace_combined_channel_with_nested_menu(self, line_name: str) -> NestedMenu:
        line_edit = getattr(self, line_name)
        initial_text = line_edit.text().strip() or "None"

        parent_layout = line_edit.parentWidget().layout()
        index = parent_layout.indexOf(line_edit)
        row, col, row_span, col_span = parent_layout.getItemPosition(index)

        selector = NestedMenu(order=1)
        selector.label.hide()
        selector.button.setText(initial_text)
        selector.name = initial_text
        selector.set_choices([initial_text])
        selector.set_chosen_one(initial_text)
        selector.button.setMinimumHeight(line_edit.minimumHeight() or 28)
        selector.button.setMinimumWidth(max(line_edit.minimumWidth(), 130))

        parent_layout.removeWidget(line_edit)
        line_edit.hide()
        parent_layout.addWidget(selector, row, col, row_span, col_span)
        return selector

    def _refresh_com_ports(self) -> None:
        current = self.comboComPort.currentText().strip()
        self.comboComPort.blockSignals(True)
        self.comboComPort.clear()
        ports = [port.device for port in serial.tools.list_ports.comports()]
        ports = sorted(ports)
        if not ports:
            self.comboComPort.addItem("COM7")
        else:
            self.comboComPort.addItems(ports)
        if current:
            index = self.comboComPort.findText(current)
            if index >= 0:
                self.comboComPort.setCurrentIndex(index)
        self.comboComPort.blockSignals(False)

    # ------------------------------------------------------------------
    # Status / signal handlers
    # ------------------------------------------------------------------
    def _append_status(self, message: str, level: str = "INFO", replace_last: bool = False) -> None:
        auto_scroll = self._should_autoscroll_log()
        timestamp = QtCore.QDateTime.currentDateTime().toString("yyyy-MM-dd HH:mm:ss")
        new_line = f"[{timestamp}] [{level}] {message}"

        if replace_last and self._last_progress_log_line_idx is not None:
            lines = self.statusTextPanel.toPlainText().splitlines()
            idx = self._last_progress_log_line_idx
            if 0 <= idx < len(lines):
                lines[idx] = new_line
                self.statusTextPanel.setPlainText("\n".join(lines))
            else:
                self.statusTextPanel.appendPlainText(new_line)
                self._last_progress_log_line_idx = self.statusTextPanel.blockCount() - 1
        else:
            self.statusTextPanel.appendPlainText(new_line)
            if level == "PROGRESS":
                self._last_progress_log_line_idx = self.statusTextPanel.blockCount() - 1
            else:
                self._last_progress_log_line_idx = None
        if auto_scroll:
            self._scroll_log_to_bottom()

    def _should_autoscroll_log(self) -> bool:
        panel = self.statusTextPanel
        scrollbar = panel.verticalScrollBar()
        if panel.hasFocus():
            return False
        if scrollbar.isSliderDown():
            return False
        if panel.textCursor().hasSelection():
            return False
        return True

    def _scroll_log_to_bottom(self) -> None:
        panel = self.statusTextPanel
        scrollbar = panel.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        cursor = panel.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        panel.setTextCursor(cursor)

    def _set_current_status(self, message: str) -> None:
        self.labelCurrentStatusValue.setText(str(message))

    def _set_stepper_status(self, connected: bool) -> None:
        self.ard_label_status.setText("ON" if connected else "OFF")

    def _on_logic_status(self, message: str) -> None:
        self._append_status(message, level="INFO")

    def _on_logic_error(self, message: str) -> None:
        self._set_current_status("Error")
        self._append_status(message, level="ERROR")

    def _on_logic_progress(self, message: str, progress: float) -> None:
        pct = int(max(0.0, min(1.0, float(progress))) * 100.0)
        self._set_current_status(f"{message} ({pct}%)")
        self._append_status(f"{message} ({pct}%)", level="PROGRESS", replace_last=True)

    def _on_xy_offset_changed(self, x_offset: float, y_offset: float) -> None:
        self.labelCurrentXYOffsetXValue.setText(f"{float(x_offset):.6g}")
        self.labelCurrentXYOffsetYValue.setText(f"{float(y_offset):.6g}")

    def _on_z_offset_changed(self, z_offset: float) -> None:
        self.labelCurrentZOffsetValue.setText(f"{float(z_offset):.6g}")

    def _on_report_paths_changed(self, autoposition_ppt: str, autofocus_ppt: str) -> None:
        self.autoPositionPptPath.setText(str(autoposition_ppt))
        self.autoFocusPptPath.setText(str(autofocus_ppt))

    def _sync_offsets_from_logic(self) -> None:
        x_offset, y_offset = self.logic.read_xy_current_offset()
        self._on_xy_offset_changed(x_offset, y_offset)
        self._on_z_offset_changed(self.logic.read_z_current_offset())

    def _sync_current_z_from_logic(self) -> None:
        try:
            value = self.logic.read_current_z()
        except Exception:
            return
        self.labelCurrentZValue.setText(f"{float(value):.6g}")

    def _sync_report_paths(self) -> None:
        paths = self.logic.get_report_paths()
        self._on_report_paths_changed(
            paths["autoposition_ppt_path"],
            paths["autofocus_ppt_path"],
        )

    # ------------------------------------------------------------------
    # Channel selector helpers
    # ------------------------------------------------------------------
    def _selector_value(self, selector: NestedMenu) -> str:
        value = str(selector.name).strip() if selector.name else ""
        if value:
            return value
        return selector.button.text().strip()

    def _on_selector_changed(self, _pair_key: str, _selector_obj: object) -> None:
        pass

    def _selector_to_device_channel(self, selector: NestedMenu, catalog_key: str) -> tuple[str, str]:
        raw = self._selector_value(selector)
        for device in sorted(self._channel_catalog.keys(), key=len, reverse=True):
            prefix = f"{device}_"
            if not raw.startswith(prefix):
                continue
            channel = raw[len(prefix) :]
            channels = self._channel_catalog.get(device, {}).get(catalog_key, [])
            if channel in channels:
                return device, channel
        return raw, ""

    def _set_selector_choices(
        self,
        selector: NestedMenu,
        nested_options: list[dict[str, list[str]]],
        preferred_combined: str | None = None,
    ) -> None:
        options = nested_options if nested_options else [{"None": ["None"]}]
        current = preferred_combined or self._selector_value(selector)
        available = {
            f"{device}_{channel}"
            for item in options
            for device, channels in item.items()
            for channel in channels
        }

        blocker = QtCore.QSignalBlocker(selector)
        try:
            selector.set_choices(options)
            if current in available:
                selector.set_chosen_one(current)
            else:
                first_device = next(iter(options[0].keys()))
                first_channel = options[0][first_device][0]
                selector.set_chosen_one(f"{first_device}_{first_channel}")
        finally:
            del blocker

    def _build_nested_options_for_catalog_key(self, catalog_key: str) -> list[dict[str, list[str]]]:
        nested = []
        for device in sorted(self._channel_catalog.keys()):
            entry = self._channel_catalog.get(device, {})
            channels = list(entry.get(catalog_key, [])) if isinstance(entry, dict) else []
            if channels:
                nested.append({device: [str(ch) for ch in channels]})
        return nested

    def _refresh_all_channel_selectors(self, preserve: bool = True) -> None:
        for pair in self._selector_pairs.values():
            selector = pair["selector"]
            preferred = self._selector_value(selector) if preserve else None
            options = self._build_nested_options_for_catalog_key(pair["catalog_key"])
            self._set_selector_choices(selector, options, preferred_combined=preferred)

    # ------------------------------------------------------------------
    # UI action wrappers
    # ------------------------------------------------------------------
    def _run_ui_action(self, label: str, action) -> Any:
        self._set_current_status(label)
        self._append_status(f"{label} started.", level="INFO")
        QtWidgets.QApplication.processEvents()
        try:
            result = action()
            self._sync_offsets_from_logic()
            self._sync_current_z_from_logic()
            self._sync_report_paths()
            self._set_current_status("Idle")
            self._append_status(f"{label} finished.", level="INFO")
            return result
        except OperationStoppedError as exc:
            self._set_current_status("Stopped")
            self._append_status(f"{label} stopped: {exc}", level="WARN")
            return None
        except Exception as exc:
            self._set_current_status("Error")
            self._append_status(f"{label} failed: {exc}", level="ERROR")
            traceback.print_exc()
            return None

    def _push_settings_to_logic(self) -> None:
        save_path = self.lineSavePath.text().strip() or os.path.join(os.getcwd(), "data")
        self.logic.configure_save_path(save_path)
        self.logic.autoposition_settings.update(self._collect_autoposition_settings())
        self.logic.autofocus_settings.update(self._collect_autofocus_settings())

    def _collect_autoposition_settings(self) -> dict[str, Any]:
        settle_widget = getattr(self, "spinXYSettleS", None)
        settle_time_s = float(settle_widget.value()) if settle_widget is not None else 0.0
        return {
            "center_x": float(self.spinXYCenterX.value()),
            "center_y": float(self.spinXYCenterY.value()),
            "span": float(self.spinXYSpan.value()),
            "points_per_line": int(self.spinXYPoints.value()),
            "settle_time_s": settle_time_s,
            "quality_threshold": float(self.spinXYQualityThreshold.value()),
            "upsample_factor": int(self.spinXYUpsampleFactor.value()),
        }

    def _collect_autofocus_settings(self) -> dict[str, Any]:
        settle_ms_widget = getattr(self, "spinFocusSettleMs", None)
        settle_time_s = (
            float(settle_ms_widget.value()) / 1000.0
            if settle_ms_widget is not None
            else 0.1
        )
        return {
            "x": float(self.spinFocusX.value()),
            "y": float(self.spinFocusY.value()),
            "threshold": float(self.spinFocusThreshold.value()),
            "start_limit": float(self.spinFocusDownLimit.value()),
            "stop_limit": float(self.spinFocusUpLimit.value()),
            "settle_time_s": settle_time_s,
            "coarse_step_um": float(self.spinFocusCoarseStep.value()),
            "fine_step_um": float(self.spinFocusFineStep.value()),
            "fine_span_scale": float(self.spinFocusFineSpanScale.value()),
        }

    def _read_selected_channel_config(self) -> dict[str, str]:
        cfg = {}
        for key, pair in self._selector_pairs.items():
            device, channel = self._selector_to_device_channel(pair["selector"], pair["catalog_key"])
            if not device or not channel:
                raise ValueError(
                    f"Invalid channel selection for '{key}'. "
                    "Please refresh channel list and choose a device/channel item."
                )
            cfg[f"{key}_device"] = device
            cfg[f"{key}_channel"] = channel
        return cfg

    # ------------------------------------------------------------------
    # UI actions
    # ------------------------------------------------------------------
    def _on_connect_stepper(self) -> None:
        def action() -> None:
            self.logic.autofocus_hardware.stepper_motor.com_port = self.comboComPort.currentText().strip()
            self.logic.autofocus_hardware.connect()
            self._set_stepper_status(True)

        self._run_ui_action("Connect stepper", action)

    def _on_disconnect_stepper(self) -> None:
        def action() -> None:
            self.logic.autofocus_hardware.disconnect()
            self._set_stepper_status(False)

        self._run_ui_action("Disconnect stepper", action)

    def _on_refresh_channels(self) -> None:
        def action() -> None:
            self._channel_catalog = self.logic.list_available_channels()
            self._refresh_all_channel_selectors(preserve=True)
            self._append_status(
                f"Loaded channel catalog with {len(self._channel_catalog)} devices.",
                level="INFO",
            )

        self._run_ui_action("Refresh channel catalog", action)

    def _on_apply_channel_config(self) -> None:
        def action() -> None:
            cfg = self._read_selected_channel_config()
            self.logic.configure_xy_position_channels(
                cfg["x_out_device"],
                cfg["x_out_channel"],
                cfg["y_out_device"],
                cfg["y_out_channel"],
            )
            self.logic.configure_xy_reference_channel(
                cfg["xy_ref_device"],
                cfg["xy_ref_channel"],
            )
            self.logic.configure_z_reference_channel(
                cfg["z_ref_device"],
                cfg["z_ref_channel"],
            )
            self.logic.configure_z_height_conversion(
                translator_height_per_rev=float(self.spinZResolution.value()),
                gear_ratio=float(self.spinZGearRatio.value()),
            )

        self._run_ui_action("Apply channel config", action)

    def _on_browse_save_path(self) -> None:
        chosen = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select save path",
            self.lineSavePath.text().strip() or os.getcwd(),
        )
        if chosen:
            self.lineSavePath.setText(chosen)
            self._run_ui_action("Update save path", self._push_settings_to_logic)

    def _on_update_settings(self) -> None:
        self._run_ui_action("Update settings", self._push_settings_to_logic)

    def _on_scan_xy_reference(self) -> None:
        def action() -> None:
            self._push_settings_to_logic()
            result = self.logic.scan_xy_reference_mapping(
                center_x=self.spinXYCenterX.value(),
                center_y=self.spinXYCenterY.value(),
                span=self.spinXYSpan.value(),
                points_per_line=self.spinXYPoints.value(),
            )
            self._append_status(
                (
                    f"Reference map: {result['reference_json_path']}, "
                    f"PPT: {result['report_ppt_path']}"
                ),
                level="INFO",
            )

        self._run_ui_action("Scan XY reference map", action)

    def _on_load_xy_reference(self) -> None:
        start_dir = str(Path(self.lineSavePath.text().strip() or os.getcwd()) / "autoposition")
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load XY reference map",
            start_dir,
            "JSON Files (*.json);;All Files (*.*)",
        )
        if not file_path:
            return

        def action() -> None:
            result = self.logic.load_xy_reference_mapping(file_path)
            self._append_status(
                f"Loaded reference: {result['reference_json_path']}",
                level="INFO",
            )

        self._run_ui_action("Load XY reference map", action)

    def _on_run_autoposition(self) -> None:
        def action() -> None:
            self._push_settings_to_logic()
            result = self.logic.set_autoposition(self._collect_autoposition_settings())
            fit = result["fit_result"]
            self._append_status(
                (
                    f"Autoposition result: success={result['success']}, "
                    f"quality={fit['quality']:.4f}, "
                    f"offset=({result['xy_offset'][0]:.6g}, {result['xy_offset'][1]:.6g}), "
                    f"PPT: {result['report_ppt_path']}."
                ),
                level="INFO",
            )

        self._run_ui_action("Run autoposition", action)

    def _on_set_xy_offset_from_center(self) -> None:
        def action() -> None:
            center_x = float(self.spinXYCenterX.value())
            center_y = float(self.spinXYCenterY.value())
            new_offset = self.logic.set_xy_offset(
                -center_x,
                -center_y,
                source="set_xy_offset_from_center",
            )
            self._append_status(
                f"Set XY offset from center: ({new_offset[0]:.6g}, {new_offset[1]:.6g}).",
                level="INFO",
            )

        self._run_ui_action("Set XY offset from center", action)

    def _on_read_xy_offset(self) -> None:
        self._run_ui_action("Read XY offset", self.logic.read_xy_current_offset)

    def _on_clear_xy_offset(self) -> None:
        self._run_ui_action("Clear XY offset history", self.logic.clear_xy_offset_history)

    def _on_export_xy_history(self) -> None:
        def action() -> None:
            path = self.logic.export_xy_offset_history()
            self._append_status(f"Saved XY history: {path}", level="INFO")

        self._run_ui_action("Export XY offset history", action)

    def _on_move_xy_home(self) -> None:
        self._run_ui_action("Move XY home (offset)", self.logic.move_xy_to_home)

    def _on_move_xy_abs_home(self) -> None:
        self._run_ui_action("Move XY absolute home", self.logic.move_xy_to_abs_home)

    def _on_run_autofocus(self) -> None:
        def action() -> None:
            self._push_settings_to_logic()
            result = self.logic.set_autofocus_abs_maximum(self._collect_autofocus_settings())
            self._append_status(
                (
                    f"Autofocus result: success={result['success']}, "
                    f"message={result['message']}, z_offset={result['z_offset']:.6g}, "
                    f"PPT: {result['report_ppt_path']}."
                ),
                level="INFO",
            )
            self.labelCurrentZValue.setText(f"{self.logic.read_current_z():.6g}")

        self._run_ui_action("Run autofocus", action)

    def _on_read_z_offset(self) -> None:
        self._run_ui_action("Read Z offset", self.logic.read_z_current_offset)

    def _on_clear_z_offset(self) -> None:
        self._run_ui_action("Clear Z offset history", self.logic.clear_z_offset_history)

    def _on_export_z_history(self) -> None:
        def action() -> None:
            path = self.logic.export_z_offset_history()
            self._append_status(f"Saved Z history: {path}", level="INFO")

        self._run_ui_action("Export Z offset history", action)

    def _on_current_z_to_zero(self) -> None:
        self._run_ui_action("Set current Z to zero", self.logic.current_z_to_zero)

    def _on_read_current_z(self) -> None:
        def action() -> None:
            value = self.logic.read_current_z()
            self.labelCurrentZValue.setText(f"{value:.6g}")
            self._append_status(f"Current logical Z: {value:.6g} um", level="INFO")

        self._run_ui_action("Read current Z", action)

    def _on_move_z_home(self) -> None:
        self._run_ui_action("Move Z home (offset)", self.logic.move_z_to_home)

    def _on_move_z_abs_home(self) -> None:
        self._run_ui_action("Move Z absolute home", self.logic.move_z_to_abs_home)

    def _on_read_xy_reference_value(self) -> None:
        def action() -> None:
            value = self.logic.autoposition_hardware.read_reference_value()
            self._append_status(f"XY reference value: {float(value):.6g}", level="INFO")

        self._run_ui_action("Read XY reference value", action)

    def _on_read_z_reference_value(self) -> None:
        def action() -> None:
            value = self.logic.autofocus_hardware.read_reference_value()
            self._append_status(f"Z reference value: {float(value):.6g}", level="INFO")

        self._run_ui_action("Read Z reference value", action)

    def _on_stop_operations(self) -> None:
        self.logic.request_stop()
        self._set_current_status("Stopping...")
        self._append_status("Stop button pressed.", level="WARN")

    def _on_save_status_log(self) -> None:
        default_dir = Path(self.lineSavePath.text().strip() or os.getcwd())
        default_dir.mkdir(parents=True, exist_ok=True)
        default_file = default_dir / f"autofocusXZ_log_{QtCore.QDateTime.currentDateTime().toString('yyyyMMdd_HHmmss')}.txt"
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save status log",
            str(default_file),
            "Text Files (*.txt);;All Files (*.*)",
        )
        if not file_path:
            return
        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(self.statusTextPanel.toPlainText())
            self._append_status(f"Saved log text: {file_path}", level="INFO")
        except Exception as exc:
            self._append_status(f"Failed to save log text: {exc}", level="ERROR")


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    window = AutofocusXZMain()
    window.show()
    sys.exit(app.exec())
