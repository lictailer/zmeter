import sys
from datetime import datetime
from typing import Any, Sequence

from PyQt6 import QtCore, QtWidgets, uic

try:
    from .four9_logic import Four9Logic
except ImportError:
    from four9_logic import Four9Logic


class Four9(QtWidgets.QWidget):
    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()

    def __init__(self) -> None:
        super().__init__()

        uic.loadUi("four9/four9.ui", self)
        self.logic = Four9Logic()

        self._apply_style()
        self._connect_signals()
        self._sync_ui_to_logic()
        self._on_connection_state_changed(False)
        self._set_busy(False)

    # ---------------------------- wiring ----------------------------
    def _connect_signals(self) -> None:
        self.connect_pushButton.clicked.connect(self._on_connect_clicked)
        self.disconnect_pushButton.clicked.connect(self._on_disconnect_clicked)
        self.setTemperature_pushButton.clicked.connect(self._on_set_temperature_clicked)
        self.setTemperature_pushButton_2.clicked.connect(
            self._on_set_temperature_to_stable_clicked
        )
        self.getTemperature_pushButton.clicked.connect(self._on_read_clicked)
        self.stopwaiting_pushButton.clicked.connect(self._on_abort_wait_clicked)

        self.comboBox.currentIndexChanged.connect(self._on_channel_changed)
        self.bufferTime_spinBox.valueChanged.connect(self._on_post_wait_changed)
        self.maxStablizingWait_spinBox.valueChanged.connect(self._on_timeout_changed)
        self.deviationThreshold_doubleSpinBox.valueChanged.connect(
            self._on_deviation_threshold_changed
        )

        self.logic.sig_status.connect(self._append_status)
        self.logic.sig_is_connected.connect(self._on_connection_state_changed)
        self.logic.sig_target_temperature.connect(self._update_target_temperature)
        self.logic.sig_temperatures.connect(self._update_temperatures)
        self.logic.sig_heater_powers.connect(self._update_heater_powers)
        self.logic.sig_stability.connect(self._update_stability)
        self.logic.finished.connect(self._on_logic_finished)

    def _sync_ui_to_logic(self) -> None:
        channel = self._selected_channel()
        self.logic.set_target_channel(channel)
        self.logic.set_read_channel(channel)
        self.logic.post_stable_wait_s = int(self.bufferTime_spinBox.value())
        self.logic.stable_wait_timeout_s = int(self.maxStablizingWait_spinBox.value()) * 60
        self.logic.stable_deviation_threshold_k = float(
            self.deviationThreshold_doubleSpinBox.value()
        )

    # ------------------------- ui actions -------------------------
    def _on_connect_clicked(self) -> None:
        if self.logic.isRunning():
            return
        self.logic.base_url = self.ipaddress_lineEdit.text().strip()
        port_text = self.ipaddress_lineEdit_2.text().strip()
        try:
            self.logic.port = int(port_text)
        except ValueError:
            self._append_status(f"Invalid port: {port_text}")
            return

        self.logic.job = "connect"
        self._set_busy(True)
        self.logic.start()

    def _on_disconnect_clicked(self) -> None:
        if self.logic.isRunning():
            return
        self.logic.job = "disconnect"
        self._set_busy(True)
        self.logic.start()

    def _on_set_temperature_clicked(self) -> None:
        if self.logic.isRunning():
            return
        self._sync_ui_to_logic()
        self.logic.setpoint_target_temperature = float(self.targetTemp_doubleSpinBox.value())
        self.logic.job = "set_temperature"
        self._set_busy(True)
        self.logic.start()

    def _on_set_temperature_to_stable_clicked(self) -> None:
        if self.logic.isRunning():
            return
        self._sync_ui_to_logic()
        self.logic.setpoint_target_temperature = float(self.targetTemp_doubleSpinBox.value())
        self.logic.job = "set_temperature_to_stable"
        self._set_busy(True)
        self.logic.start()

    def _on_read_clicked(self) -> None:
        if self.logic.isRunning():
            return
        self._sync_ui_to_logic()
        self.logic.job = "read_all_temperatures"
        self._set_busy(True)
        self.logic.start()

    def _on_abort_wait_clicked(self) -> None:
        self.logic.abort_set_temperature_to_stable()
        self._append_status("Abort requested.")

    def _on_channel_changed(self) -> None:
        channel = self._selected_channel()
        self.logic.set_target_channel(channel)
        self.logic.set_read_channel(channel)
        if len(self.logic.latest_temperatures) == 6:
            value = self.logic.latest_temperatures[channel]
            self.currentTemperature_label.setText(self._format_temperature(value))

    def _on_post_wait_changed(self, value: int) -> None:
        self.logic.post_stable_wait_s = int(value)

    def _on_timeout_changed(self, value: int) -> None:
        self.logic.stable_wait_timeout_s = int(value) * 60

    def _on_deviation_threshold_changed(self, value: float) -> None:
        self.logic.stable_deviation_threshold_k = float(value)

    # ------------------------- logic updates -------------------------
    def _on_connection_state_changed(self, is_connected: Any) -> None:
        connected = bool(is_connected)
        self.connect_pushButton.setEnabled(not connected)
        self.disconnect_pushButton.setEnabled(connected)

    def _update_target_temperature(self, payload: Any) -> None:
        try:
            channel, target = payload
            self.targetTemperature_label.setText(f"CH{int(channel):02d}: {float(target):.3f} K")
        except Exception:
            self.targetTemperature_label.setText(str(payload))

    def _update_temperatures(self, values: Sequence[float]) -> None:
        channel = self._selected_channel()
        if 0 <= channel < len(values):
            self.currentTemperature_label.setText(self._format_temperature(values[channel]))

    def _update_heater_powers(self, values: Sequence[float]) -> None:
        # Intentionally not displayed in current UI. Hook kept for future UI expansion.
        _ = values

    def _update_stability(self, info: Any) -> None:
        if not isinstance(info, dict):
            self.temperatureStatus_label.setText(str(info))
            return

        stable = bool(info.get("stable", False))
        abs_err = float(info.get("abs_error_k", float("nan")))
        deviation = float(info.get("deviation_k", float("nan")))
        points = int(info.get("points", 0))
        status = "Stable" if stable else "Not Stable"
        self.temperatureStatus_label.setText(
            f"{status} | |dT|={abs_err:.3f} K | dev={deviation:.3f} K | N={points}"
        )
        color = "#207245" if stable else "#8b1f1f"
        self.temperatureStatus_label.setStyleSheet(f"font-weight: 600; color: {color};")

    def _on_logic_finished(self) -> None:
        self._set_busy(False)

    # ------------------------- helpers -------------------------
    def _selected_channel(self) -> int:
        text = self.comboBox.currentText().strip().lower()
        if text.startswith("ch"):
            return int(text[2:])
        return int(self.comboBox.currentIndex())

    @staticmethod
    def _format_temperature(value: float) -> str:
        try:
            if value != value:  # NaN
                return "NaN K"
            return f"{float(value):.3f} K"
        except Exception:
            return str(value)

    def _append_status(self, message: Any) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.logStatus_textEdit.append(f"[{now}] {message}")
        self.logStatus_textEdit.verticalScrollBar().setValue(
            self.logStatus_textEdit.verticalScrollBar().maximum()
        )

    def _set_busy(self, busy: bool) -> None:
        self.setTemperature_pushButton.setEnabled(not busy)
        self.setTemperature_pushButton_2.setEnabled(not busy)
        self.getTemperature_pushButton.setEnabled(not busy)

    def _apply_style(self) -> None:
        self.setWindowTitle("Four9 Cryostat Control")
        self.setStyleSheet(
            """
            QWidget {
                background: #f4f6f8;
            }
            QLabel {
                color: #243447;
            }
            QPushButton {
                min-height: 26px;
                padding: 4px 10px;
                border: 1px solid #8aa0b6;
                border-radius: 6px;
                background: #ffffff;
            }
            QPushButton:hover {
                background: #e9f2ff;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit {
                background: #ffffff;
                border: 1px solid #b8c4cf;
                border-radius: 4px;
            }
            """
        )

    # ------------------------- lifecycle helpers -------------------------
    def connect(self, base_url: str | None = None, port: int | None = None) -> None:
        """Convenience hook for startup scripts."""
        if base_url is not None:
            self.ipaddress_lineEdit.setText(base_url)
        if port is not None:
            self.ipaddress_lineEdit_2.setText(str(int(port)))
        self._on_connect_clicked()

    def force_stop(self) -> None:
        self.logic.abort_set_temperature_to_stable()

    def terminate_dev(self) -> None:
        try:
            self.logic.abort_set_temperature_to_stable()
            if self.logic.isRunning():
                self.logic.wait(2000)
            if self.logic.is_connected:
                self.logic.disconnect()
        except Exception as exc:
            print(f"Error terminating Four9: {exc}")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = Four9()
    window.show()
    sys.exit(app.exec())
