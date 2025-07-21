from PyQt6 import QtWidgets, QtCore, uic  # type: ignore
import sys
import time
from typing import Any
import numpy as np
import pyqtgraph as pg
import pyvisa  # type: ignore


from .hp34401a_logic import HP34401A_Logic


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

        # ----- helper plot widget (X, Y, R, Theta streams) -----
        w = pg.GraphicsLayoutWidget(show=True)
        w.viewport().setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        self.plot_dc_voltage = w.addPlot(row=0, col=0)
        self.plot_dc_voltage.setTitle("V")

        # *graph_dc_voltage* is a QVBoxLayout placeholder defined in the .ui file
        self.graph_dc_voltage.addWidget(w)

        # ----- VISA resource list -----
        resource_manager = pyvisa.ResourceManager()
        self.address_comboBox.addItems(resource_manager.list_resources())

        # ---------------- logic layer -------------
        self.logic = HP34401A_Logic()
        # circular buffers for live plot
        self.dc_voltage_log = np.full(200, np.nan, dtype=float)

        # Populate VISA resources
        self._refresh_visa_resources()

        # ---------------- wiring ------------------
        self.connect_pushButton.clicked.connect(self._on_connect_clicked) 
        self.disconnect_pushButton.clicked.connect(self._on_disconnect_clicked)  
        
        self.NPLC_comboBox.currentTextChanged.connect(self.write_NPLC)
        self.display_on_checkBox.stateChanged.connect(self.write_display_on)
        

        # Logic signals
        self.logic.sig_NPLC.connect(self.update_NPLC)
        self.logic.sig_dc_voltage.connect(self._update_dc_voltage)
        self.logic.sig_is_changing.connect(self._update_status)
        self.logic.sig_connected.connect(self._update_status)

        

        # ----- periodic monitor -----

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._monitor)
        self.timer.start(50)
    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def reset_graph(self):
        self.dc_voltage_log[:] = np.nan
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_dc_voltage.plot(self.dc_voltage_log, clear=True, pen=pen)

    def stop_timer(self):
        if self.timer.isActive():
            self.timer.stop()

    def start_timer(self):
        if not self.timer.isActive():
            self.timer.start(50)

    def update_status(self, txt):
        """Generic label updater for *sig_is_changing* & *sig_connected*."""
        self.status_label.setText(str(txt))

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

        '''
    def _on_read_voltage_clicked(self):
        if not self.logic._connected:
            return
        self.logic.stop()
        self.logic.job = "get_dc_voltage"
        self.logic.start()
        '''




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
            self.dc_voltage_log[:-1] = self.dc_voltage_log[1:]
            self.dc_voltage_log[-1] = val
            pen = pg.mkPen((255, 255, 255), width=3)
            self.plot_dc_voltage.plot(self.dc_voltage_log, clear=True, pen=pen)
        except Exception:
            return
        self.dc_voltage_label.setText(f"{fval} V")  

    def _update_status(self, txt: Any):
        self.status_label.setText(str(txt))  # type: ignore[attr-defined]
    # ------------------------------------------------------------------
    # VISA connection
    # ------------------------------------------------------------------
    def connect_visa(self, addr):
        if addr == None or addr == False:
            addr = self.address_comboBox.currentText()
        print(f"Connecting to {addr}")
        self.logic.connect_visa(addr)
        self.address_comboBox.setCurrentText(addr)
    # ------------------------------------------------------------------
    # read_/write_/setup_ wrappers (naming follows sr860_logic)
    # ----------------------------------------------------------------
        
    def write_NPLC(self, val: float | None = None):
        self.logic.stop()
        self.logic.setpoint_NPLC = float(val) if val is not None else float(self.NPLC_comboBox.currentText())
        self.logic.job = "write_NPLC"
        self.logic.start()

    def write_display_on(self, val: bool | None = None):
        self.logic.stop()
        self.logic.setpoint_display_on = bool(val) if val is not None else bool(self.display_on_checkBox.isChecked())
        self.logic.job = "write_display_on"
        self.logic.start()

    def read_NPLC(self):
        self.logic.job = "read_NPLC"
        self.logic.start()

    def update_NPLC(self, text):
        self.NPLC_comboBox.blockSignals(True)
        self.NPLC_comboBox.setCurrentText(str(text))
        self.NPLC_comboBox.blockSignals(False)

    def disconnect_device(self):
        self.logic.disconnect()

    def terminate_dev(self):
        self.logic.disconnect()
        print("HP34401a terminated.")
    

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
        if not self.logic._connected:
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
    win.resize(480, 400)
    win.show()
    sys.exit(app.exec())