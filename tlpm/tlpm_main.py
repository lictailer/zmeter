from PyQt6 import QtWidgets, uic, QtCore
import sys
from .tlpm_logic import TLPMLogic
import numpy as np
import pyqtgraph as pg


class TLPM(QtWidgets.QWidget):
    def __init__(self):
        super(TLPM, self).__init__()
        uic.loadUi("tlpm/tlpm.ui", self)
        self.logic = TLPMLogic()
        self.connect_sig_slot()
        self.power_log = np.zeros(1000)

    def connect_sig_slot(self):
        self.connect_button.clicked.connect(self.connect)
        self.disconnect_button.clicked.connect(self.disconnect)
        self.set_button.clicked.connect(self.set_wavelength)
        self.update_button.clicked.connect(self.read_indef)
        self.stop_button.clicked.connect(self.stop_indef)
        self.logic.sig_power.connect(self.update_power)
        self.logic.sig_info.connect(self.update_info)
        self.logic.sig_connect.connect(self.update_on_off)

    def update_on_off(self, status):
        if status:
            self.label_on_off.setText("ON")
        else:
            self.label_on_off.setText("OFF")

    def update_power(self, power):
        self.power_log[0:-1] = self.power_log[1:]
        self.power_log[-1] = power
        pen1 = pg.mkPen((255, 255, 255), width=3)
        self.input1_PlotWidget.getPlotItem().plot(self.power_log, clear=True, pen=pen1)

        units = ['pw', 'nW', 'uW', 'mW', 'W']
        lv = 3
        if 1e-12 < power and power <= 1e-9:
            power = power*1e12
            lv = 0
        elif 1e-9 < power and power <= 1e-6:
            power = power*1e9
            lv = 1
        elif 1e-6 < power and power <= 1e-3:
            power = power*1e6
            lv = 2
        elif 1e-3 < power and power <= 1e0:
            power = power*1e3
            lv = 3
        self.input1_label.setText(f"{power:.2f} {units[lv]}")

    def update_info(self, info):
        self.info_label.setText(info)

    # actions
    def connect(self):
        self.logic.do_connect = True
        self.logic.start()

    def disconnect(self):
        if self.logic.is_connected is True:
            self.logic.do_disconnect = True
            self.logic.start()

    def set_wavelength(self):
        pos = self.nm_to_go_doubleSpinBox.value()
        self.logic.set_wavelength_target(pos)
        self.logic.do_change_wavelength = True
        self.logic.start()

    def read_power(self):
        self.logic.do_read_power = True
        self.logic.start()

    def read_indef(self):
        self.logic.freq = self.freq_doubleSpinBox.value()
        self.logic.do_read_indefinitely = True
        self.logic.start()

    def stop_indef(self):
        self.logic.receieved_stop = True


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = TLPM()
    window.show()
    app.exec()
