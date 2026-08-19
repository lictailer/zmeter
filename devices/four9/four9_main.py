"""PyQt widget for the Four9 temperature-control service."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6 import QtCore, QtWidgets, uic

from core.device_log import append_device_log, configure_device_log

from .four9_hardware import MAX_TEMPERATURE_K, MIN_TEMPERATURE_K
from .four9_logic import Four9Logic


class Four9(QtWidgets.QWidget):
    """Montana-style manual controls and status display for Four9."""

    def __init__(self, logic: Four9Logic | None = None) -> None:
        super().__init__()
        uic.loadUi(str(Path(__file__).with_name("four9.ui")), self)

        self.logic = logic or Four9Logic()
        self.host_lineEdit.setText(str(self.logic.host))
        self.port_spinBox.setValue(int(self.logic.port))
        self.targetTemperature_doubleSpinBox.setRange(
            MIN_TEMPERATURE_K, MAX_TEMPERATURE_K
        )

        self.logic.sig_temperature.connect(self._update_temperature)
        self.logic.sig_target_temperature.connect(self._update_target_temperature)
        self.logic.sig_temperature_stable.connect(self._update_stability)
        self.logic.sig_log.connect(self._handle_logic_log)
        self.logic.sig_is_connected.connect(self._update_connection_status)
        self.logic.started.connect(self._on_logic_started)
        self.logic.finished.connect(self._on_logic_finished)

        self.connect_pushButton.clicked.connect(self._on_connect_clicked)
        self.disconnect_pushButton.clicked.connect(self._on_disconnect_clicked)
        self.setTemperature_pushButton.clicked.connect(self._on_set_temperature_clicked)
        self.getTemperature_pushButton.clicked.connect(self._on_get_temperature_clicked)

        configure_device_log(self.logStatus_textEdit)
        self._update_connection_status(self.logic.is_connected)

    def _on_connect_clicked(self) -> None:
        self.logic.host = self.host_lineEdit.text().strip()
        self.logic.port = int(self.port_spinBox.value())
        self._start_logic_job("connect")

    def _on_disconnect_clicked(self) -> None:
        self._start_logic_job("disconnect")

    def _on_set_temperature_clicked(self) -> None:
        if not self.logic.is_connected:
            self._append_log(
                "Cannot set temperature while Four9 is disconnected.", "WARNING"
            )
            return
        self.logic.setpoint_temperature = self.targetTemperature_doubleSpinBox.value()
        self._start_logic_job("set_temperature")

    def _on_get_temperature_clicked(self) -> None:
        if not self.logic.is_connected:
            self._append_log(
                "Cannot read temperature while Four9 is disconnected.", "WARNING"
            )
            return
        self._start_logic_job("get_temperature")

    def _start_logic_job(self, job: str) -> bool:
        if self.logic.isRunning():
            self._append_log("Four9 is busy with another UI request.", "WARNING")
            return False
        self.logic.job = job
        self.logic.start()
        return True

    def _on_logic_started(self) -> None:
        for button in (
            self.connect_pushButton,
            self.disconnect_pushButton,
            self.setTemperature_pushButton,
            self.getTemperature_pushButton,
        ):
            button.setEnabled(False)

    def _on_logic_finished(self) -> None:
        self._update_connection_status(self.logic.is_connected)

    def _update_connection_status(self, connected: bool) -> None:
        connected = bool(connected)
        self.connectionStatus_label.setText(
            "Connected" if connected else "Disconnected"
        )
        self.connectionStatus_label.setStyleSheet(
            "color: #147a21; font-weight: bold;"
            if connected
            else "color: #9b1c1c; font-weight: bold;"
        )
        self.host_lineEdit.setEnabled(not connected)
        self.port_spinBox.setEnabled(not connected)
        self.connect_pushButton.setEnabled(not connected)
        self.disconnect_pushButton.setEnabled(connected)
        self.setTemperature_pushButton.setEnabled(connected)
        self.getTemperature_pushButton.setEnabled(connected)

    def _update_temperature(self, temperature_k: object) -> None:
        self.currentTemperature_label.setText(f"{float(temperature_k):.5f} K")

    def _update_target_temperature(self, target_k: object) -> None:
        self.targetTemperature_label.setText(f"{float(target_k):.5f} K")

    def _update_stability(self, stable: bool, reason: str) -> None:
        readable_reason = str(reason).replace("_", " ")
        state = "Stable" if stable else "Not stable"
        self.temperatureStatus_label.setText(f"{state} ({readable_reason})")
        self.temperatureStatus_label.setStyleSheet(
            "color: #147a21; font-weight: bold;"
            if stable
            else "color: #9b5d00; font-weight: bold;"
        )

    def _handle_logic_log(self, payload: object) -> None:
        if isinstance(payload, tuple) and len(payload) == 2:
            level, message = payload
            self._append_log(message, level)
            return
        self._append_log(payload)

    def _append_log(self, message: object, level: object = "INFO") -> None:
        append_device_log(self.logStatus_textEdit, level, message)

    def force_stop(self) -> None:
        """Allow ZMeter scan stop to interrupt a stable wait promptly."""

        self.logic.request_abort_stable_wait(log_if_idle=False)

    def terminate_dev(self) -> None:
        """Interrupt active work, then close only this client connection."""

        self.logic.request_abort_stable_wait(log_if_idle=False)
        if self.logic.isRunning():
            wait_ms = int(max(2.0, self.logic.socket_timeout_s + 1.0) * 1000)
            self.logic.wait(wait_ms)
        if self.logic.is_connected or bool(
            getattr(self.logic.hardware, "is_connected", False)
        ):
            self.logic.disconnect()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    widget = Four9()
    widget.setWindowTitle("Four9")
    widget.show()
    sys.exit(app.exec())
