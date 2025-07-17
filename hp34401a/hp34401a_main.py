from PyQt6 import QtWidgets, QtCore, uic  # type: ignore
import sys
import time
from typing import Any

import pyvisa  # type: ignore


from hp34401a_logic import HP34401A_Logic


class HP34401A(QtWidgets.QWidget):
    """Qt GUI wrapper for the *Demo Device*.

    This is a template for a new device. The design intentionally follows the style of *sr860_main.SR860*.
    Only a subset of parameters (operating mode
    and voltage level) are exposed to demonstrate the pattern.
    """

    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()

    # -------------------------------------------------------------
    def __init__(self) -> None:
        super().__init__()

        # ---------------- load UI from external .ui file ---------------
        uic.loadUi("hp34401a/hp34401a.ui", self)

        # ---------------- logic layer -------------
        self.logic = HP34401A_Logic()

        # Populate VISA resources
        self._refresh_visa_resources()

        # ---------------- wiring ------------------
        self.connect_pushButton.clicked.connect(self._on_connect_clicked) 
        self.disconnect_pushButton.clicked.connect(self._on_disconnect_clicked)  
        #self.operationMode_comboBox.currentIndexChanged.connect(self._on_mode_changed)  
        #self.voltageLevel_doubleSpinBox.valueChanged.connect(self._on_voltage_changed)  
        #self.setVoltage_pushButton.clicked.connect(self._on_set_voltage_clicked)
        self.readVoltage_pushButton.clicked.connect(self._on_read_voltage_clicked)

        # Logic signals
        #self.logic.sig_operating_mode.connect(self._update_mode)
        self.logic.sig_dc_voltage.connect(self._update_dc_voltage)
        self.logic.sig_is_changing.connect(self._update_status)
        self.logic.sig_connected.connect(self._update_status)

        # Periodic monitor timer
        # Periodic monitor is not used in this example
        # enable this following 3 lines will automatically update the UI with the current value of the parameter
        # it is connected the the _monitor() function

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._monitor)
        self.timer.start(500)

    # -------------------------------------------------------------
    # UI event handlers
    # -------------------------------------------------------------
    def _on_connect_clicked(self):
        address = self.address_comboBox.currentText()
        if not address:
            self._update_status("[ERR] No VISA address selected")
            return
        self.logic.connect_visa(address)

    def _on_disconnect_clicked(self):
        self.logic.disconnect()

    '''def _on_mode_changed(self, idx: int):
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.setpoint_operating_mode = idx
        self.logic.job = "set_operating_mode"
        self.logic.start()'''


    def _on_read_voltage_clicked(self):
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.job = "get_dc_voltage"
        self.logic.start()

    # -------------------------------------------------------------
    # Logic signal slots
    # -------------------------------------------------------------
    #def _update_mode(self, mode: Any):
    #    self.operationMode_comboBox.blockSignals(True)
    #    self.operationMode_comboBox.setCurrentText(str(mode))
    #    self.operationMode_comboBox.blockSignals(False)

    def _update_dc_voltage(self, val: Any):
        try:
            fval = float(val)
        except Exception:
            return
        self.dc_voltage_label.setText(f"{fval} V")  

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
    win = HP34401A()
    win.resize(480, 240)
    win.show()
    sys.exit(app.exec())