#from distutils.command.build_scripts import first_line_re
from PyQt6 import QtWidgets, uic, QtCore
import sys
from .opticool_logic import OptiCool_Logic
import numpy as np
import pyqtgraph as pg

class OptiCool(QtWidgets.QWidget):
    def __init__(self):
        super(OptiCool, self).__init__()
        uic.loadUi("opticool.ui", self)
        self.logic = OptiCool_Logic()
        self.connect_sig_slot()

    def connect_sig_slot(self):
        self.pushButton.clicked.connect(self.set_temperature_stable)
        self.pushButton_2.clicked.connect(self.set_field_stable)
        self.pushButton_3.clicked.connect(self.get_temperature)
        self.pushButton_4.clicked.connect(self.get_field)

        self.logic.sig_last_field.connect(self.update_field)
        self.logic.sig_last_temperature.connect(self.update_temperature)
        self.logic.sig_setting_field.connect(self.update_setting_field)
        self.logic.sig_setting_temperature.connect(self.update_setting_temperature)

    def set_temperature(self):
        tem = self.lineEdit.text()
        tem = float(tem)
        self.logic.setpoint_temperature = tem
        self.logic.job = "set_temperature"
        self.logic.start()

    def set_temperature_stable(self):
        tem = self.lineEdit.text()
        tem = float(tem)
        self.logic.setpoint_temperature = tem
        self.logic.job = "set_temperature_stable"
        self.logic.start()

    def set_field(self):
        field = self.lineEdit_2.text()
        field = float(field)
        self.logic.setpoint_tesla = field
        self.logic.job = "set_field"
        self.logic.start()

    def set_field_stable(self):
        field = self.lineEdit_2.text()
        field = float(field)
        self.logic.setpoint_tesla = field
        self.logic.job = "set_field_stable"
        self.logic.start()

    def get_temperature(self):
        self.logic.job = "get_temperature"
        self.logic.start()

    def get_field(self):
        self.logic.job = "get_field"
        self.logic.start()

    def update_temperature(self, info):
        self.label_3.setText(f"last read: {info:.5f} Kelvin")

    def update_field(self, info):
        self.label_4.setText(f"last read: {info/10000:.6f} Tesla")

    def update_setting_temperature(self, info):
        self.label_3.setText(info)

    def update_setting_field(self, info):
        self.label_4.setText(info)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = OptiCool()
    window.show()
    app.exec_()
