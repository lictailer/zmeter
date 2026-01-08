import sys
import time
from typing import Any

from PyQt6 import QtWidgets, QtCore, uic  # type: ignore

from montana2_logic import Montana2Logic


class Montana2(QtWidgets.QWidget):

    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()

    # -------------------------------------------------------------
    def __init__(self) -> None:
        super().__init__()

        # ---------------- load UI from external .ui file ---------------
        uic.loadUi("montana2/montana2.ui", self)

        # ---------------- logic layer -------------
        self.logic = Montana2Logic()

        # ---------------- wiring ------------------ 
        # Logic signals
        self.logic.sig_platform_temperature.connect(self._update_platform_temperature)
        self.logic.sig_platform_target_temperature.connect(self._update_platform_target_temperature)
        self.logic.sig_platform_temperature_stable_bool.connect(self._update_platform_temperature_stable)
        self.logic.sig_status.connect(self._update_status)
        self.logic.sig_is_connected.connect(self._update_status)
        # self.logic.sig_is_changing.connect(self._update_status)

        self.connect_pushButton.clicked.connect(self._on_connect_clicked)
        self.disconnect_pushButton.clicked.connect(self._on_disconnect_clicked)
        self.quickConnect_comboBox.currentTextChanged.connect(self._on_quick_connect_changed)
        self.ipaddress_lineEdit.editingFinished.connect(self._on_ipaddress_changed)
        self.setTemperature_pushButton.clicked.connect(self._on_set_temperature_clicked)
        self.getTemperature_pushButton.clicked.connect(self._on_get_temperature_clicked)
        self.bufferTime_spinBox.valueChanged.connect(self._on_buffer_time_changed)
        self.stopwaiting_pushButton.clicked.connect(self._on_stop_waiting_clicked)
        self.maxStablizingWait_spinBox.valueChanged.connect(self._on_max_stabilizing_wait_changed)
        
    # -------------------------------------------------------------

    def _on_connect_clicked(self):
        self.logic.ipaddress = self.ipaddress_lineEdit.text()
        self.logic.job = "connect"
        self.logic.start()

    def _on_disconnect_clicked(self):
        self.logic.job = "disconnect"
        self.logic.start()

    #--------------------------------------------------------------   
    def _update_platform_temperature(self, value: Any):
        self.currentTemperature_label.setText(f"{value:.3f} K")

    def _update_platform_target_temperature(self, value: Any):
        self.targetTemperature_label.setText(f"{value:.1f} K")

    def _update_platform_temperature_stable(self, value: Any):
        if value is False:
            self.temperatureStatus_label.setText("Not stable")
        else:
            self.temperatureStatus_label.setText("Stable")
    
    def _update_status(self, message: Any):
        self.logStatus_textEdit.append(message)
        # Auto-scroll to bottom
        self.logStatus_textEdit.verticalScrollBar().setValue(
            self.logStatus_textEdit.verticalScrollBar().maximum()
        )

    def _on_quick_connect_changed(self, value: str):
        print("quick connect changed:", value)
        if value == "Montana 1":
            self.ipaddress_lineEdit.setText("unknown")
        elif value == "Montana 2":
            self.ipaddress_lineEdit.setText("136.167.55.165")
        elif value == "Other":
            self.ipaddress_lineEdit.setText("")

    def _on_ipaddress_changed(self):
        self.quickConnect_comboBox.setCurrentText("Other")

    def _on_set_temperature_clicked(self):
        self.logic.job = "set_platform_target_temperature"
        print(self.targetTemp_doubleSpinBox.value(), type(self.targetTemp_doubleSpinBox.value()))
        self.logic.setpoint_platform_target_temperature = self.targetTemp_doubleSpinBox.value()
        self.logic.start()

    def _on_get_temperature_clicked(self):
        self.logic.job = "get_platform_temperature"
        self.logic.start()
        while self.logic.isRunning():
            QtCore.QThread.msleep(50)
        self.logic.job = "get_platform_temperature_stable"
        self.logic.start()

    def _on_buffer_time_changed(self, value: int):
        self.logic.set_temperature_buffer_time_s = value

    def _on_stop_waiting_clicked(self):
        self.logic.stable_wait_stop = True

    def _on_max_stabilizing_wait_changed(self, value: int):
        self.logic.stable_wait_timeout_s = value * 60

    def terminate_dev(self):
        print("Montana terminated.")
        try:
            if self.logic.is_connected:
                # Stop any ongoing operations
                self.logic.stable_wait_stop = True
                
                # Wait for any running thread to finish
                if self.logic.isRunning():
                    self.logic.wait(2000)  # Wait up to 2 seconds
                
                # Safely disconnect the device
                self.logic.disconnect()
                
                # Update connection status
                self.logic.is_connected = False
        except Exception as e:
            print(f"Error during Montana termination: {e}")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    montana2 = Montana2()
    montana2.show()
    sys.exit(app.exec())