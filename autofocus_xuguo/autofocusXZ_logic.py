#!/usr/bin/env python3
"""
Logic layer for combined autofocus (Z) and autoposition (X/Y).

This module keeps state and workflow logic in one place while delegating
hardware communication and reusable math/reporting to helper modules.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from PyQt6 import QtCore

from .autofocusXZ_hardware import AutofocusXZHardware, AutoPositionXZHardware
from .autopositionXZ_helpers import (
    append_autofocus_report_slide,
    append_autoposition_report_slide,
    export_history_to_csv,
    fit_gaussian_peak,
    fit_offset,
    gaussian_fit_to_dict,
    offset_fit_to_dict,
    run_autofocus_z_profile,
    run_autoposition_square_mapping,
)


class AutofocusXZLogic(QtCore.QObject):
    """
    Combined logic for:
    - auto-position compensation in X/Y by map correlation
    - autofocus compensation in Z by two-pass Gaussian peak search
    """

    sig_status = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)
    sig_progress = QtCore.pyqtSignal(str, float)
    sig_xy_offset_changed = QtCore.pyqtSignal(float, float)
    sig_z_offset_changed = QtCore.pyqtSignal(float)
    sig_report_paths_changed = QtCore.pyqtSignal(str, str)

    def __init__(
        self,
        *,
        autofocus_hardware: AutofocusXZHardware | None = None,
        autoposition_hardware: AutoPositionXZHardware | None = None,
        save_path: str | os.PathLike[str] | None = None,
    ) -> None:
        super().__init__()
        self.autofocus_hardware = autofocus_hardware or AutofocusXZHardware()
        self.autoposition_hardware = autoposition_hardware or AutoPositionXZHardware()

        self.command_router: Any = None
        self.device_label = "autofocus_xz_logic"

        self.save_path = str(save_path) if save_path is not None else os.path.join(os.getcwd(), "data")
        self.xy_offset = (0.0, 0.0)
        self.z_offset = 0.0

        self.xy_offset_history: list[dict[str, Any]] = []
        self.z_offset_history: list[dict[str, Any]] = []

        self.xy_reference_mapping: dict[str, Any] | None = None
        self.xy_reference_mapping_path: str | None = None

        self.autoposition_settings: dict[str, Any] = {
            "center_x": 0.0,
            "center_y": 0.0,
            "span": 0.1,
            "points_per_line": 51,
            "settle_time_s": 0.0,
            "quality_threshold": 0.6,
            "upsample_factor": 20,
            "comments": "",
        }
        self.autofocus_settings: dict[str, Any] = {
            "x": 0.0,
            "y": 0.0,
            "threshold": 0.0,
            "up_limit": 20.0,
            "down_limit": -20.0,
            "settle_time_s": 0.0,
            "coarse_step_um": 1.0,
            "fine_span_scale": 0.25,
            "fine_step_um": 0.5,
            "peak_delta_max_um": 5.0,
            "fine_peak_ratio_min": 0.85,
        }
        self._stop_requested = False
        self._emit_xy_offset()
        self._emit_z_offset()
        self._emit_report_paths()

    def request_stop(self) -> None:
        self._stop_requested = True
        self._emit_status("Stop requested. Current operation will stop soon.")

    def clear_stop_request(self) -> None:
        self._stop_requested = False

    def is_stop_requested(self) -> bool:
        return bool(self._stop_requested)

    # -------------------------------------------------------------------------
    # Router and hardware setup
    # -------------------------------------------------------------------------
    def configure_command_router(
        self,
        command_router: Any,
        source_device: str | None = None,
    ) -> None:
        self.command_router = command_router
        if source_device:
            self.device_label = str(source_device)

        base = self.device_label
        self.autofocus_hardware.configure_command_router(
            command_router,
            source_device=f"{base}_autofocus",
        )
        self.autoposition_hardware.configure_command_router(
            command_router,
            source_device=f"{base}_autoposition",
        )
        self._emit_status("Command router configured.")

    def configure_save_path(self, save_path: str | os.PathLike[str]) -> None:
        self.save_path = str(save_path)
        self._emit_report_paths()

    def get_available_channels(self) -> dict[str, Any]:
        return self.autoposition_hardware.list_available_channels()

    def list_available_channels(self) -> dict[str, Any]:
        """Compatibility alias."""
        return self.get_available_channels()

    def get_report_paths(self) -> dict[str, str]:
        return {
            "autoposition_ppt_path": self._autoposition_report_ppt_path(),
            "autofocus_ppt_path": self._autofocus_report_ppt_path(),
        }

    def configure_xy_position_channels(
        self,
        x_target_device: str,
        x_channel: str,
        y_target_device: str,
        y_channel: str,
    ) -> None:
        self.autoposition_hardware.set_position_channels(
            x_target_device=x_target_device,
            x_channel=x_channel,
            y_target_device=y_target_device,
            y_channel=y_channel,
        )
        self._emit_status(
            f"Configured XY outputs: X={x_target_device}_{x_channel}, "
            f"Y={y_target_device}_{y_channel}."
        )

    def configure_xy_reference_channel(self, target_device: str, channel: str) -> None:
        self.autoposition_hardware.set_reference_channel(target_device, channel)
        self._emit_status(f"Configured XY reference: {target_device}_{channel}.")

    def configure_z_reference_channel(self, target_device: str, channel: str) -> None:
        self.autofocus_hardware.set_reference_channel(target_device, channel)
        self._emit_status(f"Configured Z reference: {target_device}_{channel}.")

    # -------------------------------------------------------------------------
    # UI / general methods
    # -------------------------------------------------------------------------
    def scan_xy_reference_mapping(
        self,
        center_x: float,
        center_y: float,
        span: float,
        points_per_line: int,
    ) -> dict[str, Any]:
        self.clear_stop_request()
        self._emit_progress("Scanning XY reference map...", 0.0)
        self.autoposition_settings.update(
            {
                "center_x": float(center_x),
                "center_y": float(center_y),
                "span": float(span),
                "points_per_line": int(points_per_line),
            }
        )

        result = run_autoposition_square_mapping(
            self.autoposition_hardware,
            center_x=float(center_x),
            center_y=float(center_y),
            span=float(span),
            points_per_line=int(points_per_line),
            settle_time_s=float(self.autoposition_settings["settle_time_s"]),
            save_path=self.save_path,
            name="autoposition_xy_reference",
            comments="reference map",
            line_finished_callback=lambda line_idx, total: self._emit_progress(
                f"Reference map line {line_idx}/{total}",
                (line_idx / max(total, 1)) * 0.9,
            ),
            should_stop=self.is_stop_requested,
            process_events=self._process_qt_events,
        )
        self.xy_reference_mapping = self._mapping_result_to_reference(result)
        self.xy_reference_mapping_path = str(result["json_path"])
        report_ppt = append_autoposition_report_slide(
            ppt_path=self._autoposition_report_ppt_path(),
            reference_image=np.asarray(self.xy_reference_mapping["image"], dtype=float),
            new_image=np.asarray(self.xy_reference_mapping["image"], dtype=float),
            offset_x=0.0,
            offset_y=0.0,
            quality=1.0,
            success=True,
            details="Reference map updated.",
        )
        self._emit_report_paths()
        self._emit_progress("XY reference map scan completed.", 1.0)
        self._emit_status(f"Reference map saved: {self.xy_reference_mapping_path}")
        return {
            "reference_json_path": self.xy_reference_mapping_path,
            "shape": tuple(self.xy_reference_mapping["image"].shape),
            "report_ppt_path": report_ppt,
        }

    def load_xy_reference_mapping(self, file_path: str | os.PathLike[str]) -> dict[str, Any]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Reference mapping file not found: {path}")

        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        image = self._extract_image_from_scan_payload(payload)
        x_values = self._extract_first_setter_values(payload, "level0")
        y_values = self._extract_first_setter_values(payload, "level1")

        span_x = float(x_values[-1] - x_values[0]) if x_values.size > 1 else 0.0
        span_y = float(y_values[-1] - y_values[0]) if y_values.size > 1 else 0.0
        span = float(max(abs(span_x), abs(span_y)))

        self.xy_reference_mapping = {
            "image": image,
            "x_values": x_values,
            "y_values": y_values,
            "span": span,
            "points_per_line": int(image.shape[0]),
            "json_path": str(path),
            "info": payload,
        }
        self.xy_reference_mapping_path = str(path)
        self._emit_status(f"Loaded XY reference map: {path}")

        return {
            "reference_json_path": str(path),
            "shape": tuple(image.shape),
            "span": span,
        }

    def read_xy_current_offset(self) -> tuple[float, float]:
        return float(self.xy_offset[0]), float(self.xy_offset[1])

    def set_xy_offset(self, offset_x: float, offset_y: float, *, source: str = "manual_set") -> tuple[float, float]:
        old_offset = self.read_xy_current_offset()
        self.xy_offset = (float(offset_x), float(offset_y))
        self._emit_xy_offset()
        self.xy_offset_history.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": str(source),
                "old_offset_x": float(old_offset[0]),
                "old_offset_y": float(old_offset[1]),
                "new_offset_x": float(self.xy_offset[0]),
                "new_offset_y": float(self.xy_offset[1]),
            }
        )
        self._emit_status(
            f"XY offset updated to ({self.xy_offset[0]:.6g}, {self.xy_offset[1]:.6g})."
        )
        return self.read_xy_current_offset()

    def clear_xy_offset_history(self) -> tuple[float, float]:
        self.xy_offset_history.clear()
        self.xy_offset = (0.0, 0.0)
        self._emit_xy_offset()
        self._emit_status("Cleared XY offset history and reset XY offset to (0, 0).")
        return self.read_xy_current_offset()

    def export_xy_offset_history(self, csv_path: str | os.PathLike[str] | None = None) -> str:
        if csv_path is None:
            csv_path = self._autoposition_folder() / f"{self._timestamp()}_xy_offset_history.csv"
        output = export_history_to_csv(self.xy_offset_history, csv_path)
        self._emit_status(f"Exported XY offset history: {output}")
        return output

    def read_z_current_offset(self) -> float:
        return float(self.z_offset)

    def clear_z_offset_history(self) -> float:
        self.z_offset_history.clear()
        self.z_offset = 0.0
        self._emit_z_offset()
        self._emit_status("Cleared Z offset history and reset Z offset to 0.")
        return float(self.z_offset)

    def export_z_offset_history(self, csv_path: str | os.PathLike[str] | None = None) -> str:
        if csv_path is None:
            csv_path = self._autofocus_folder() / f"{self._timestamp()}_z_offset_history.csv"
        output = export_history_to_csv(self.z_offset_history, csv_path)
        self._emit_status(f"Exported Z offset history: {output}")
        return output

    def read_current_z(self) -> float:
        return float(self.autofocus_hardware.current_height() - self.z_offset)

    def current_z_to_zero(self) -> float:
        current_physical = float(self.autofocus_hardware.current_height())
        old_offset = float(self.z_offset)
        self.z_offset = current_physical
        self.z_offset_history.append(
            {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "current_z_to_zero",
                "old_z_offset": old_offset,
                "new_z_offset": float(self.z_offset),
            }
        )
        self._emit_z_offset()
        self._emit_status(
            f"Updated Z offset from {old_offset:.6g} to {self.z_offset:.6g}."
        )
        return 0.0

    def move_z_to_abs_home(self) -> float:
        final_physical = float(self.autofocus_hardware.home())
        logical_z = float(final_physical - self.z_offset)
        self._emit_status(f"Moved Z to absolute home. Logical Z={logical_z:.6g} um.")
        return logical_z

    def move_z_to_home(self) -> float:
        """
        Move to offset-home for scan coordinates:
        logical z = 0, physical z = z_offset
        """
        final_logical = float(self.set_z_with_offset(0.0))
        self._emit_status(f"Moved Z to offset-home. Logical Z={final_logical:.6g} um.")
        return final_logical

    def move_xy_to_abs_home(self) -> tuple[float, float]:
        self.autoposition_hardware.move_absoluteX(0.0)
        self.autoposition_hardware.move_absoluteY(0.0)
        self._emit_status("Moved XY to absolute home (0, 0).")
        return 0.0, 0.0

    def move_xy_to_home(self) -> tuple[float, float]:
        """
        Move to offset-home for scan coordinates:
        logical (x, y) = (0, 0), physical (x, y) = (x_offset, y_offset)
        """
        final_x = float(self.set_x_with_offset(0.0))
        final_y = float(self.set_y_with_offset(0.0))
        self._emit_status(
            f"Moved XY to offset-home. X={final_x:.6g}, Y={final_y:.6g}."
        )
        return final_x, final_y

    # -------------------------------------------------------------------------
    # Scan-facing setters
    # -------------------------------------------------------------------------
    def set_x_with_offset(self, x_value: float) -> float:
        commanded = float(x_value) + float(self.xy_offset[0])
        self.autoposition_hardware.move_absoluteX(commanded)
        return commanded

    def set_y_with_offset(self, y_value: float) -> float:
        commanded = float(y_value) + float(self.xy_offset[1])
        self.autoposition_hardware.move_absoluteY(commanded)
        return commanded

    def set_z_with_offset(self, z_value: float) -> float:
        commanded_physical = float(z_value) + float(self.z_offset)
        final_physical = float(self.autofocus_hardware.move_absolute_height(commanded_physical))
        return float(final_physical - self.z_offset)

    def set_autoposition(self, settings: Any) -> dict[str, Any]:
        self.clear_stop_request()
        self._emit_progress("Autoposition started.", 0.0)
        params = self._resolve_setting_update(
            current=self.autoposition_settings,
            settings=settings,
            allowed_keys=set(self.autoposition_settings.keys()),
        )
        self.autoposition_settings.update(params)

        if self.xy_reference_mapping is None:
            raise RuntimeError(
                "No XY reference mapping is loaded. "
                "Call scan_xy_reference_mapping(...) or load_xy_reference_mapping(...) first."
            )

        center_x = float(self.autoposition_settings["center_x"])
        center_y = float(self.autoposition_settings["center_y"])
        span = float(self.autoposition_settings["span"])
        points_per_line = int(self.autoposition_settings["points_per_line"])
        settle_time_s = float(self.autoposition_settings["settle_time_s"])
        quality_threshold = float(self.autoposition_settings["quality_threshold"])
        upsample_factor = int(self.autoposition_settings["upsample_factor"])

        scan_center_x = center_x + float(self.xy_offset[0])
        scan_center_y = center_y + float(self.xy_offset[1])

        mapping = run_autoposition_square_mapping(
            self.autoposition_hardware,
            center_x=scan_center_x,
            center_y=scan_center_y,
            span=span,
            points_per_line=points_per_line,
            settle_time_s=settle_time_s,
            save_path=self.save_path,
            name="autoposition_xy_current",
            comments="current map for autoposition",
            line_finished_callback=lambda line_idx, total: self._emit_progress(
                f"Autoposition map line {line_idx}/{total}",
                (line_idx / max(total, 1)) * 0.85,
            ),
            should_stop=self.is_stop_requested,
            process_events=self._process_qt_events,
        )
        self._emit_progress("Current XY map acquired.", 0.9)

        reference_image = np.asarray(self.xy_reference_mapping["image"], dtype=float)
        new_image = np.asarray(mapping["image"], dtype=float)
        if reference_image.shape != new_image.shape:
            raise ValueError(
                "Reference and current maps must have the same shape. "
                "Use the same span and points_per_line as the reference."
            )

        fit_result = fit_offset(
            reference_image,
            new_image,
            x_values=np.asarray(self.xy_reference_mapping["x_values"], dtype=float),
            y_values=np.asarray(self.xy_reference_mapping["y_values"], dtype=float),
            upsample_factor=upsample_factor,
            quality_threshold=quality_threshold,
        )

        offset_delta_x = 0.0
        offset_delta_y = 0.0
        old_offset = self.read_xy_current_offset()
        if fit_result.success and fit_result.offset_x is not None and fit_result.offset_y is not None:
            offset_delta_x = float(fit_result.offset_x)
            offset_delta_y = float(fit_result.offset_y)
            self.xy_offset = (
                float(self.xy_offset[0]) + offset_delta_x,
                float(self.xy_offset[1]) + offset_delta_y,
            )
            self._emit_xy_offset()

        if fit_result.success:
            history_row = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "autoposition",
                "quality": float(fit_result.quality),
                "offset_delta_x": float(offset_delta_x),
                "offset_delta_y": float(offset_delta_y),
                "old_offset_x": float(old_offset[0]),
                "old_offset_y": float(old_offset[1]),
                "new_offset_x": float(self.xy_offset[0]),
                "new_offset_y": float(self.xy_offset[1]),
                "scan_center_x": float(scan_center_x),
                "scan_center_y": float(scan_center_y),
            }
            self.xy_offset_history.append(history_row)

        ppt_path = append_autoposition_report_slide(
            ppt_path=self._autoposition_report_ppt_path(),
            reference_image=reference_image,
            new_image=new_image,
            offset_x=fit_result.offset_x,
            offset_y=fit_result.offset_y,
            quality=float(fit_result.quality),
            success=bool(fit_result.success),
            details=fit_result.message,
        )
        self._emit_report_paths()
        self._emit_progress("Autoposition finished.", 1.0)
        if fit_result.success:
            self._emit_status(
                f"Autoposition success. New XY offset=({self.xy_offset[0]:.6g}, "
                f"{self.xy_offset[1]:.6g})."
            )
        else:
            self._emit_status(f"Autoposition failed: {fit_result.message}")

        return {
            "success": bool(fit_result.success),
            "fit_result": offset_fit_to_dict(fit_result),
            "xy_offset": self.read_xy_current_offset(),
            "offset_history_length": len(self.xy_offset_history),
            "current_map_json_path": str(mapping["json_path"]),
            "report_ppt_path": ppt_path,
        }

    def set_autofocus_abs_maximum(self, settings: Any) -> dict[str, Any]:
        self.clear_stop_request()
        self._emit_progress("Autofocus started.", 0.0)
        params = self._resolve_setting_update(
            current=self.autofocus_settings,
            settings=settings,
            allowed_keys=set(self.autofocus_settings.keys()),
        )
        self.autofocus_settings.update(params)

        x_value = float(self.autofocus_settings["x"])
        y_value = float(self.autofocus_settings["y"])
        threshold = float(self.autofocus_settings["threshold"])
        down_limit = float(self.autofocus_settings["down_limit"])
        up_limit = float(self.autofocus_settings["up_limit"])
        coarse_step = float(self.autofocus_settings["coarse_step_um"])
        fine_step = float(self.autofocus_settings["fine_step_um"])
        fine_span_scale = float(self.autofocus_settings["fine_span_scale"])
        peak_delta_max = float(self.autofocus_settings["peak_delta_max_um"])
        fine_peak_ratio_min = float(self.autofocus_settings["fine_peak_ratio_min"])
        settle_time_s = float(self.autofocus_settings["settle_time_s"])

        if up_limit <= down_limit:
            raise ValueError("up_limit must be larger than down_limit.")
        if coarse_step <= 0 or fine_step <= 0:
            raise ValueError("coarse_step_um and fine_step_um must be positive.")

        self.set_x_with_offset(x_value)
        self.set_y_with_offset(y_value)

        start_logical_z = self.read_current_z()
        old_z_offset = float(self.z_offset)

        coarse_profile = run_autofocus_z_profile(
            self.autofocus_hardware,
            z_start_um=down_limit + old_z_offset,
            z_end_um=up_limit + old_z_offset,
            step_um=coarse_step,
            settle_time_s=settle_time_s,
            point_finished_callback=lambda idx, total: self._emit_progress(
                f"Autofocus coarse {idx}/{total}",
                (idx / max(total, 1)) * 0.45,
            ),
            should_stop=self.is_stop_requested,
            process_events=self._process_qt_events,
        )
        self._emit_progress("Autofocus coarse scan completed.", 0.46)
        coarse_positions_logical = np.asarray(coarse_profile["z_positions"], dtype=float) - old_z_offset
        coarse_values = np.asarray(coarse_profile["values"], dtype=float)
        coarse_fit = fit_gaussian_peak(coarse_positions_logical, coarse_values)

        fine_positions_logical = np.array([], dtype=float)
        fine_values = np.array([], dtype=float)
        fine_fit = None

        success = False
        message = ""

        if not coarse_fit.success:
            message = f"Coarse fit failed: {coarse_fit.message}"
        elif coarse_fit.peak_value is None or coarse_fit.peak_value < threshold:
            message = (
                f"Coarse fit peak {coarse_fit.peak_value} is below threshold {threshold}."
            )
        else:
            coarse_peak = float(coarse_fit.peak_position)
            coarse_span = float(up_limit - down_limit)
            fine_span = float(max(coarse_span * fine_span_scale, fine_step * 2.0))
            fine_down = max(down_limit, coarse_peak - fine_span / 2.0)
            fine_up = min(up_limit, coarse_peak + fine_span / 2.0)
            if fine_up - fine_down < fine_step:
                fine_down = max(down_limit, coarse_peak - fine_step)
                fine_up = min(up_limit, coarse_peak + fine_step)

            fine_profile = run_autofocus_z_profile(
                self.autofocus_hardware,
                z_start_um=fine_down + old_z_offset,
                z_end_um=fine_up + old_z_offset,
                step_um=fine_step,
                settle_time_s=settle_time_s,
                point_finished_callback=lambda idx, total: self._emit_progress(
                    f"Autofocus fine {idx}/{total}",
                    0.5 + (idx / max(total, 1)) * 0.35,
                ),
                should_stop=self.is_stop_requested,
                process_events=self._process_qt_events,
            )
            self._emit_progress("Autofocus fine scan completed.", 0.75)
            fine_positions_logical = np.asarray(fine_profile["z_positions"], dtype=float) - old_z_offset
            fine_values = np.asarray(fine_profile["values"], dtype=float)
            fine_fit = fit_gaussian_peak(fine_positions_logical, fine_values)

            if not fine_fit.success:
                message = f"Fine fit failed: {fine_fit.message}"
            elif fine_fit.peak_position is None or fine_fit.peak_value is None:
                message = "Fine fit returned invalid peak values."
            else:
                peak_distance = abs(float(fine_fit.peak_position) - coarse_peak)
                if coarse_fit.peak_value is None or coarse_fit.peak_value <= 0:
                    peak_ratio = 0.0
                else:
                    peak_ratio = float(fine_fit.peak_value / coarse_fit.peak_value)

                if peak_distance >= peak_delta_max:
                    message = (
                        f"Peak mismatch: |fine-coarse|={peak_distance:.3f} um "
                        f">= {peak_delta_max:.3f} um."
                    )
                elif peak_ratio < fine_peak_ratio_min:
                    message = (
                        f"Fine peak ratio {peak_ratio:.3f} is below "
                        f"{fine_peak_ratio_min:.3f}."
                    )
                elif fine_fit.peak_value < threshold:
                    message = (
                        f"Fine fit peak {fine_fit.peak_value:.6g} is below "
                        f"threshold {threshold:.6g}."
                    )
                else:
                    self.set_z_with_offset(float(fine_fit.peak_position))
                    self.z_offset = float(self.autofocus_hardware.current_height())
                    self._emit_z_offset()
                    success = True
                    message = (
                        f"Autofocus succeeded at logical z={fine_fit.peak_position:.3f} um."
                    )

        if not success:
            # Restore the original logical Z position if autofocus fails.
            try:
                self.set_z_with_offset(start_logical_z)
            except Exception:
                pass

        if success:
            history_row = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "event": "autofocus",
                "x": float(x_value),
                "y": float(y_value),
                "threshold": float(threshold),
                "down_limit": float(down_limit),
                "up_limit": float(up_limit),
                "old_z_offset": float(old_z_offset),
                "new_z_offset": float(self.z_offset),
                "coarse_peak_um": None if coarse_fit.peak_position is None else float(coarse_fit.peak_position),
                "coarse_peak_value": None if coarse_fit.peak_value is None else float(coarse_fit.peak_value),
                "coarse_r2": None if coarse_fit.r2 is None else float(coarse_fit.r2),
                "fine_peak_um": None if fine_fit is None or fine_fit.peak_position is None else float(fine_fit.peak_position),
                "fine_peak_value": None if fine_fit is None or fine_fit.peak_value is None else float(fine_fit.peak_value),
                "fine_r2": None if fine_fit is None or fine_fit.r2 is None else float(fine_fit.r2),
            }
            self.z_offset_history.append(history_row)

        ppt_path = append_autofocus_report_slide(
            ppt_path=self._autofocus_report_ppt_path(),
            coarse_positions=coarse_positions_logical,
            coarse_values=coarse_values,
            fine_positions=fine_positions_logical,
            fine_values=fine_values,
            coarse_peak=coarse_fit.peak_position,
            fine_peak=None if fine_fit is None else fine_fit.peak_position,
            success=success,
            details=message,
        )
        self._emit_report_paths()
        self._emit_progress("Autofocus finished.", 1.0)
        if success:
            self._emit_status(message)
        else:
            self._emit_error(message)

        return {
            "success": bool(success),
            "message": message,
            "coarse_fit": gaussian_fit_to_dict(coarse_fit),
            "fine_fit": None if fine_fit is None else gaussian_fit_to_dict(fine_fit),
            "z_offset": float(self.z_offset),
            "z_history_length": len(self.z_offset_history),
            "report_ppt_path": ppt_path,
        }

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _autoposition_folder(self) -> Path:
        folder = Path(self.save_path) / "autoposition"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _autofocus_folder(self) -> Path:
        folder = Path(self.save_path) / "autofocus"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _report_folder(self) -> Path:
        folder = Path(self.save_path) / "autofocusXZ_reports"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _autoposition_report_ppt_path(self) -> str:
        return str(self._report_folder() / "autoposition_report.pptx")

    def _autofocus_report_ppt_path(self) -> str:
        return str(self._report_folder() / "autofocus_report.pptx")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def _emit_status(self, message: str) -> None:
        self.sig_status.emit(str(message))

    def _emit_error(self, message: str) -> None:
        self.sig_error.emit(str(message))

    def _emit_progress(self, message: str, progress: float) -> None:
        self.sig_progress.emit(str(message), float(progress))

    def _emit_xy_offset(self) -> None:
        self.sig_xy_offset_changed.emit(float(self.xy_offset[0]), float(self.xy_offset[1]))

    def _emit_z_offset(self) -> None:
        self.sig_z_offset_changed.emit(float(self.z_offset))

    def _emit_report_paths(self) -> None:
        self.sig_report_paths_changed.emit(
            self._autoposition_report_ppt_path(),
            self._autofocus_report_ppt_path(),
        )

    @staticmethod
    def _process_qt_events() -> None:
        app = QtCore.QCoreApplication.instance()
        if app is not None:
            app.processEvents()

    @staticmethod
    def _resolve_setting_update(
        *,
        current: dict[str, Any],
        settings: Any,
        allowed_keys: set[str],
    ) -> dict[str, Any]:
        if settings is None:
            return {}
        if isinstance(settings, str):
            text = settings.strip()
            if text == "":
                return {}
            if text.startswith("{"):
                loaded = json.loads(text)
                if not isinstance(loaded, dict):
                    raise ValueError("JSON setter input must decode to a dictionary.")
                settings = loaded
            else:
                return {}
        if isinstance(settings, dict):
            updates = {}
            for key, value in settings.items():
                if key in allowed_keys:
                    updates[key] = value
            return updates
        if isinstance(settings, (int, float, np.number, bool)):
            return {}
        raise ValueError(
            "Setter input must be a dict, JSON dict string, or numeric trigger."
        )

    @staticmethod
    def _mapping_result_to_reference(mapping_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "image": np.asarray(mapping_result["image"], dtype=float),
            "x_values": np.asarray(mapping_result["x_values"], dtype=float),
            "y_values": np.asarray(mapping_result["y_values"], dtype=float),
            "span": float(mapping_result["info"]["autoposition_metadata"]["span"]),
            "points_per_line": int(mapping_result["info"]["autoposition_metadata"]["points_per_line"]),
            "json_path": str(mapping_result["json_path"]),
            "info": mapping_result["info"],
        }

    @staticmethod
    def _extract_image_from_scan_payload(payload: dict[str, Any]) -> np.ndarray:
        data = payload.get("data")
        if not isinstance(data, list) or len(data) == 0:
            raise ValueError("Invalid scan JSON: missing 'data'.")
        level0 = np.asarray(data[0], dtype=float)
        if level0.ndim == 3 and level0.shape[0] >= 1:
            image = level0[0]
        elif level0.ndim == 2:
            image = level0
        else:
            raise ValueError("Invalid scan JSON: could not parse level0 image data.")
        if image.ndim != 2:
            raise ValueError("Reference map must be a 2D image.")
        return image

    @staticmethod
    def _extract_first_setter_values(payload: dict[str, Any], level_name: str) -> np.ndarray:
        levels = payload.get("levels", {})
        level = levels.get(level_name, {})
        setters = level.get("setters", {})
        if not isinstance(setters, dict) or not setters:
            raise ValueError(f"Invalid scan JSON: no setters in {level_name}.")

        first_key = sorted(setters.keys())[0]
        setter = setters[first_key]
        destinations = setter.get("destinations")
        if destinations is None:
            linear = setter.get("linear_setting", {})
            destinations = linear.get("destinations")
        values = np.asarray(destinations, dtype=float)
        if values.ndim != 1 or values.size < 2:
            raise ValueError(f"Invalid scan JSON: bad destinations in {level_name}.")
        return values
