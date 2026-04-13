# from distutils.command.build_scripts import first_line_re
from PyQt6 import QtWidgets, uic
import sys
from datetime import datetime
from .opticool_logic import OptiCool_Logic


class OptiCool(QtWidgets.QWidget):
    def __init__(self):
        super(OptiCool, self).__init__()
        uic.loadUi("opticool/opticool.ui", self)
        self.logic = OptiCool_Logic()
        self.connect_sig_slot()
        self.connectionStatus_label.setText("Connecting Status: False")
        self._append_log("OptiCool ready. Click Connect to initialize hardware.")

    def connect_sig_slot(self):
        self.pushButton.clicked.connect(self.set_temperature_stable)
        self.pushButton_2.clicked.connect(self.set_field_stable)
        self.pushButton_3.clicked.connect(self.get_temperature)
        self.pushButton_4.clicked.connect(self.get_field)
        self.connect_pushButton.clicked.connect(self.connect)
        self.disconnect_pushButton.clicked.connect(self.disconnect)
        self.abortStable_pushButton.clicked.connect(self.abort_stable_wait)

        self.logic.sig_last_field.connect(self.update_field)
        self.logic.sig_last_temperature.connect(self.update_temperature)
        self.logic.sig_setting_field.connect(self.update_setting_field)
        self.logic.sig_setting_temperature.connect(self.update_setting_temperature)
        self.logic.sig_status.connect(self._append_log)
        self.logic.sig_is_connected.connect(self._update_connection_status)

    def _start_logic_job(self, job):
        if self.logic.isRunning():
            self._append_log("OptiCool is busy. Try again in a moment.")
            return False
        self.logic.job = job
        self.logic.start()
        return True

    def connect(self):
        self._start_logic_job("connect")

    def disconnect(self):
        self._start_logic_job("disconnect")

    def abort_stable_wait(self):
        self.logic.request_abort_stable_wait()

    def set_temperature(self):
        if not self.logic.is_connected:
            self._append_log("Cannot set temperature while disconnected.")
            return
        try:
            tem = float(self.lineEdit.text())
        except ValueError:
            self._append_log("Invalid temperature input.")
            return
        self.logic.setpoint_temperature = tem
        self._start_logic_job("set_temperature")

    def set_temperature_stable(self):
        if not self.logic.is_connected:
            self._append_log("Cannot set temperature while disconnected.")
            return
        try:
            tem = float(self.lineEdit.text())
        except ValueError:
            self._append_log("Invalid temperature input.")
            return
        self.logic.setpoint_temperature = tem
        self._start_logic_job("set_temperature_stable")

    def set_field(self):
        if not self.logic.is_connected:
            self._append_log("Cannot set field while disconnected.")
            return
        try:
            field = float(self.lineEdit_2.text())
        except ValueError:
            self._append_log("Invalid field input.")
            return
        self.logic.setpoint_tesla = field
        self._start_logic_job("set_field")

    def set_field_stable(self):
        if not self.logic.is_connected:
            self._append_log("Cannot set field while disconnected.")
            return
        try:
            field = float(self.lineEdit_2.text())
        except ValueError:
            self._append_log("Invalid field input.")
            return
        self.logic.setpoint_tesla = field
        self._start_logic_job("set_field_stable")

    def get_temperature(self):
        if not self.logic.is_connected:
            self._append_log("Cannot read temperature while disconnected.")
            return
        self._start_logic_job("get_temperature")

    def get_field(self):
        if not self.logic.is_connected:
            self._append_log("Cannot read field while disconnected.")
            return
        self._start_logic_job("get_field")

    def update_temperature(self, info):
        self.label_3.setText(f"last read: {info:.5f} Kelvin")

    def update_field(self, info):
        self.label_4.setText(f"last read: {info/10000:.6f} Tesla")

    def update_setting_temperature(self, info):
        self.label_3.setText(info)

    def update_setting_field(self, info):
        self.label_4.setText(info)

    def _update_connection_status(self, message):
        self.connectionStatus_label.setText(str(message))
        self._append_log(message)

    def _append_log(self, message):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.logStatus_textEdit.append(f"[{timestamp}] {message}")
        self.logStatus_textEdit.verticalScrollBar().setValue(
            self.logStatus_textEdit.verticalScrollBar().maximum()
        )

    def terminate_dev(self):
        try:
            if self.logic.isRunning():
                self.logic.wait(2000)
            if self.logic.is_connected:
                self.logic.disconnect()
        except Exception as exc:
            print(f"Error during OptiCool termination: {exc}")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = OptiCool()
    window.show()
    app.exec()
