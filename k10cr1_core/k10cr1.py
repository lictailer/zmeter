from PyQt6 import QtWidgets, uic, QtCore
import sys
from k10cr1_core.k10cr1_logic import K10CR1Logic
import numpy as np
import pyqtgraph as pg


class K10CR1(QtWidgets.QWidget):
    def __init__(self):
        super(K10CR1, self).__init__()
        uic.loadUi(r"Equipments/k10cr1_core/k10cr1.ui", self)
        self.logic = K10CR1Logic()

        self.connect_button.clicked.connect(self.connect)
        self.disconnect_button.clicked.connect(self.disconnect)
        self.go_button.clicked.connect(self.set_angle)
        self.home_button.clicked.connect(self.home)
        self.logic.sig_last_pos.connect(self.update_pos)
        self.logic.sig_info.connect(self.update_info)
        self.logic.sig_connect.connect(self.set_on_off)

    def set_on_off(self, status):
        if status:
            self.label_on_off.setText("ON")
        else:
            self.label_on_off.setText("OFF")

    def update_pos(self, pos):
        deg = "%.3f" % float(pos * 360 / 49152000)
        self.last_pos_label.setText(f"last positon: {deg} deg <-- {pos}")

    def update_info(self, info):
        self.info_label.setText(info)

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

    def terminate_dev(self):
        print("K10cr10 terminated.")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = K10CR1()
    window.show()
    window.lineEdit.setText("55243324")
    app.exec()
