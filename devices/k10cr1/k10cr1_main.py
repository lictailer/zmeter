import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets, uic

from core.device_log import append_device_log, configure_device_log
from core.shared_runtime.kinesis import KinesisRuntime

from .k10cr1_logic import K10CR1Logic


class K10CR1(QtWidgets.QWidget):
    def __init__(self, kinesis_runtime: KinesisRuntime | None = None):
        super(K10CR1, self).__init__()
        uic.loadUi(str(Path(__file__).with_name("k10cr1.ui")), self)
        self.logic = K10CR1Logic(kinesis_runtime)

        self.connect_button.clicked.connect(self.connect)
        self.disconnect_button.clicked.connect(self.disconnect)
        self.go_button.clicked.connect(self.set_angle)
        self.home_button.clicked.connect(self.home)
        self.stop_button.clicked.connect(self.force_stop)
        self.logic.sig_last_pos.connect(self.update_pos)
        self.logic.sig_log.connect(self._handle_logic_log)
        self.logic.sig_connect.connect(self.set_on_off)
        configure_device_log(self.log_textEdit)

    def set_on_off(self, status):
        if status:
            self.label_on_off.setText("ON")
        else:
            self.label_on_off.setText("OFF")

    def update_pos(self, pos):
        deg = "%.3f" % float(pos * 360 / 49152000)
        self.last_pos_label.setText(f"last positon: {deg} deg <-- {pos}")

    def _handle_logic_log(self, payload):
        if isinstance(payload, tuple) and len(payload) == 2:
            level, message = payload
            append_device_log(self.log_textEdit, level, message)
            return
        append_device_log(self.log_textEdit, "INFO", payload)

    def connect(self, serial=""):
        self.logic.job="connect"
        if serial == False:
            serial = self.lineEdit.text()
        else:
            self.lineEdit.setText(serial)
        self.logic.assign_serial(serial)
        self.logic.start()

    def disconnect(self):
        if self.logic.is_connected is True:
            self.logic.job="disconnect"
            self.logic.start()

    def home(self):
        self.logic.job="home"
        self.logic.start()

    def set_angle(self):
        pos = self.pos_to_go_doubleSpinBox.value()
        self.logic.assign_target(pos)
        self.logic.job="set_angle"
        self.logic.start()

    def force_stop(self):
        pass

    def terminate_dev(self):
        if self.logic.is_connected:
            self.logic.disconnect()
        print("K10cr10 terminated.")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = K10CR1()
    window.show()
    window.lineEdit.setText("55243324")
    app.exec()
