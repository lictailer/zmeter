from __future__ import annotations

from pathlib import Path

from PyQt6 import QtWidgets, uic

from core.device_log import append_device_log, configure_device_log
from core.shared_runtime.kinesis import KinesisRuntime

try:
    from .BBD30X_logic import BBD30X_Logic
except ImportError:
    from BBD30X_logic import BBD30X_Logic


class BBD30X(QtWidgets.QWidget):
    def __init__(self, hardware=None, kinesis_runtime: KinesisRuntime | None = None):
        super().__init__()
        uic.loadUi(str(Path(__file__).with_name("bbd30x.ui")), self)
        if hardware is None:
            from .BBD30X_hardware import BBD30x_hardware

            hardware = BBD30x_hardware(kinesis_runtime)
        self.logic = BBD30X_Logic(hardware=hardware)
        self._last_current_mm: float | None = None
        self._last_target_mm: float | None = None
        self._connect_signals()
        self._configure_log()
        self._update_connected(False)
        self._update_t0(None)

    def _connect_signals(self) -> None:
        self.connect_button.clicked.connect(self.connect)
        self.disconnect_button.clicked.connect(self.disconnect)
        self.home_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.home)
        )
        self.move_button.clicked.connect(self._move_from_ui)
        self.set_velocity_button.clicked.connect(self._set_velocity_from_ui)
        self.read_position_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.read_position_from_ui)
        )
        self.set_t0_button.clicked.connect(
            lambda: self.logic.submit_ui_job(
                self.logic.set_t0_from_current_position
            )
        )

        self.logic.sig_current_pos.connect(self._update_current_position)
        self.logic.sig_target_pos.connect(self._update_target_position)
        self.logic.sig_velocity_params.connect(self._update_velocity_params)
        self.logic.sig_connect.connect(self._update_connected)
        self.logic.sig_t0_changed.connect(self._update_t0)
        self.logic.sig_status.connect(self.status_label.setText)
        self.logic.sig_error.connect(self._update_error)
        self.logic.sig_log.connect(self._handle_logic_log)

    def _configure_log(self) -> None:
        configure_device_log(self.log_textEdit)

    def _handle_logic_log(self, payload: object) -> None:
        if isinstance(payload, tuple) and len(payload) == 2:
            level, message = payload
            self._append_log(str(message), str(level))
            return
        self._append_log(str(payload))

    def _append_log(self, message: str, level: str = "INFO") -> None:
        append_device_log(self.log_textEdit, level, message)

    def _update_error(self, message: str) -> None:
        self.status_label.setText(f"Error: {message}")

    def _update_connected(self, connected: bool) -> None:
        self.connection_status_label.setText("ON" if connected else "OFF")
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        for widget in (
            self.home_button,
            self.move_button,
            self.set_velocity_button,
            self.read_position_button,
            self.set_t0_button,
        ):
            widget.setEnabled(connected)

    def _position_text(self, position_mm: float) -> str:
        try:
            delay_ps = self.logic.mm_to_delay_ps(position_mm)
        except RuntimeError:
            return f"{position_mm:.4f} mm | -- ps"
        return f"{position_mm:.4f} mm | {delay_ps:.4f} ps"

    def _update_current_position(self, position_mm: object) -> None:
        self._last_current_mm = float(position_mm)
        self.current_position_label.setText(
            f"Current: {self._position_text(self._last_current_mm)}"
        )

    def _update_target_position(self, position_mm: object) -> None:
        self._last_target_mm = float(position_mm)
        self.target_position_label.setText(
            f"Target: {self._position_text(self._last_target_mm)}"
        )

    def _update_t0(self, position_mm: object) -> None:
        if position_mm is None:
            self.t0_status_label.setText("T0: not set")
        else:
            self.t0_status_label.setText(f"T0: {float(position_mm):.4f} mm")
        if self._last_current_mm is not None:
            self._update_current_position(self._last_current_mm)
        if self._last_target_mm is not None:
            self._update_target_position(self._last_target_mm)

    def _update_velocity_params(self, payload: object) -> None:
        velocity, acceleration = payload
        self.velocity_lineEdit.setText(f"{float(velocity):g}")
        self.acceleration_lineEdit.setText(f"{float(acceleration):g}")

    def connect(self, serial: object = "") -> bool:
        if serial is False or serial is None or serial == "":
            serial_text = self.serial_lineEdit.text().strip()
        else:
            serial_text = str(serial).strip()
            self.serial_lineEdit.setText(serial_text)
        if not serial_text:
            self._update_error("Enter a BBD30X serial number")
            return False
        return self.logic.submit_ui_job(self.logic.connect, serial_text)

    def disconnect(self) -> bool:
        if not self.logic.is_connected:
            return False
        return self.logic.submit_ui_job(self.logic.disconnect)

    def _move_from_ui(self) -> None:
        self.logic.submit_ui_job(
            self.logic.set_pos_mm,
            self.target_mm_doubleSpinBox.value(),
        )

    @staticmethod
    def _optional_float(text: str) -> float | None:
        stripped = text.strip()
        if stripped == "":
            return None
        return float(stripped)

    def _set_velocity_from_ui(self) -> None:
        try:
            velocity = self._optional_float(self.velocity_lineEdit.text())
            acceleration = self._optional_float(self.acceleration_lineEdit.text())
        except ValueError:
            self._update_error("Velocity and acceleration must be numeric")
            self._append_log(
                "Velocity update rejected: enter numeric values or leave a field blank.",
                level="WARNING",
            )
            return
        self.logic.submit_ui_job(
            self.logic.set_velocity_params,
            velocity,
            acceleration,
        )

    def stop_scan(self) -> bool:
        return self.logic.stop_scan()

    def start_scan(self) -> bool:
        return self.logic.start_scan()

    def force_stop(self) -> bool:
        return self.logic.force_stop()

    def terminate_dev(self) -> bool:
        result = self.logic.terminate_dev()
        if result:
            print("BBD30X terminated.")
        return result
