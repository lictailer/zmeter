from __future__ import annotations

import sys
import time
from typing import Any

import pyvisa  # type: ignore
from PyQt6 import QtWidgets, QtCore, uic  # type: ignore

from .demoDevice_logic import DemoDeviceLogic


class DemoDeviceWidget(QtWidgets.QWidget):
    """Qt GUI wrapper for the *Demo Device*.

    This is a template for a new device. The design intentionally follows the style of *sr860_main.SR860*.
    Only a subset of parameters (operating mode
    and voltage level) are exposed to demonstrate the pattern.
    """

    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()

    MODES = ["local", "remote", "lockout"]

    # -------------------------------------------------------------
    def __init__(self) -> None:
        super().__init__()

        # ---------------- load UI from external .ui file ---------------
        uic.loadUi("demo_device/demoDevice.ui", self)  # type: ignore[arg-type]

        # --- runtime attributes created by Qt Designer (.ui) ---
        # The following type annotations inform static analysers that these
        # attributes exist (they are added dynamically by `uic.loadUi`).
        # self.address_cb: QtWidgets.QComboBox  # type: ignore[attr-defined]
        # self.connect_btn: QtWidgets.QPushButton  # type: ignore[attr-defined]
        # self.disconnect_btn: QtWidgets.QPushButton  # type: ignore[attr-defined]
        # self.idn_edit: QtWidgets.QLineEdit  # type: ignore[attr-defined]
        # self.mode_cb: QtWidgets.QComboBox  # type: ignore[attr-defined]
        # self.volt_spin: QtWidgets.QDoubleSpinBox  # type: ignore[attr-defined]
        # self.status_label: QtWidgets.QLabel  # type: ignore[attr-defined]

        # # Ensure mode combo box has expected entries (extend if necessary)
        # for entry in self.MODES:
        #     if self.mode_cb.findText(entry) == -1:
        #         self.mode_cb.addItem(entry) 

        # ---------------- logic layer -------------
        self.logic = DemoDeviceLogic()

        # Populate VISA resources
        self._refresh_visa_resources()

        # ---------------- wiring ------------------
        self.connect_pushButton.clicked.connect(self._on_connect_clicked) 
        self.disconnect_pushButton.clicked.connect(self._on_disconnect_clicked)  

        self.operationMode_comboBox.currentIndexChanged.connect(self._on_mode_changed)  
        self.voltageLevel_doubleSpinBox.valueChanged.connect(self._on_voltage_changed)  

        # Logic signals
        self.logic.sig_operating_mode.connect(self._update_mode)
        self.logic.sig_voltage_level.connect(self._update_voltage)
        self.logic.sig_is_changing.connect(self._update_status)
        self.logic.sig_connected.connect(self._update_status)

        # Periodic monitor timer
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._monitor)
        self.timer.start(500)

    # -------------------------------------------------------------
    # UI event handlers
    # -------------------------------------------------------------
    def _on_connect_clicked(self):
        address = self.address_comboBox.currentText()  # type: ignore[attr-defined]
        if not address:
            self._update_status("[ERR] No VISA address selected")
            return
        self.logic.connect_visa(address)

    def _on_disconnect_clicked(self):
        self.logic.disconnect()

    def _on_mode_changed(self, idx: int):
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.setpoint_operating_mode = self.MODES[idx]
        self.logic.job = "set_operating_mode"
        self.logic.start()

    def _on_voltage_changed(self, value: float):
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.setpoint_voltage_level = value
        self.logic.job = "set_voltage_level"
        self.logic.start()

    # -------------------------------------------------------------
    # Logic signal slots
    # -------------------------------------------------------------
    def _update_mode(self, mode: Any):
        if mode in self.MODES:
            self.mode_cb.blockSignals(True)  # type: ignore[attr-defined]
            self.mode_cb.setCurrentText(str(mode))  # type: ignore[attr-defined]
            self.mode_cb.blockSignals(False)  # type: ignore[attr-defined]

    def _update_voltage(self, val: Any):
        try:
            fval = float(val)
        except Exception:
            return
        self.volt_spin.blockSignals(True)  # type: ignore[attr-defined]
        self.volt_spin.setValue(fval)  # type: ignore[attr-defined]
        self.volt_spin.blockSignals(False)  # type: ignore[attr-defined]

    def _update_status(self, txt: Any):
        self.status_label.setText(str(txt))  # type: ignore[attr-defined]

    # -------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------
    def _refresh_visa_resources(self):
        rm = pyvisa.ResourceManager()
        resources = rm.list_resources()
        self.address_comboBox.clear()  # type: ignore[attr-defined]
        self.address_comboBox.addItems(resources)  # type: ignore[attr-defined]

    # -------------------------------------------------------------
    # Periodic monitor
    # This is used to continuously update the UI with the current value of the parameter
    # See sr860, sr830 or nidaq for examples
    # -------------------------------------------------------------
    def _monitor(self):
        if not self.logic.connected:
            return
        if self.logic.isRunning():
            return
        self.logic.job = "get_all"
        self.logic.start()


# ----------------------------------------------------------------------
# Stand-alone entry-point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = DemoDeviceWidget()
    win.resize(480, 240)
    win.show()
    sys.exit(app.exec())
