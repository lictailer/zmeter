from PyQt6 import QtCore
from .opticool_hardware import OptiCool_Hardware
import time
import numpy as np

class OptiCool_Logic(QtCore.QThread):
    sig_last_temperature = QtCore.pyqtSignal(object)
    sig_last_field = QtCore.pyqtSignal(object)
    sig_setting_temperature = QtCore.pyqtSignal(object)
    sig_setting_field = QtCore.pyqtSignal(object)

    hardware = OptiCool_Hardware()
    job = ''
    setpoint_temperature = 0
    setpoint_tesla = 0

    def __init__(self):
        QtCore.QThread.__init__(self)

    def set_temperature(self):
        self.sig_setting_temperature.emit('setting...')
        self.hardware.set_temperature(self.setpoint_temperature)
        self.get_temperature()

    def set_temperature_stable(self):
        self.set_temperature()
        read_arr=np.zeros(50)
        while True:
            [status, val, TemperatureStatusString] = self.hardware.get_temperature()
            self.sig_last_temperature.emit(val)
            read_arr[-1]=val
            read_arr[0:-1]=read_arr[1::]
            
            # print(read_arr)
            # print(np.std(read_arr))
            if TemperatureStatusString in ['Stable']:
                break
            elif np.std(read_arr)<0.0001:
                break
            time.sleep(0.1)

    def get_temperature(self):
        [status, val, TemperatureStatus] = self.hardware.get_temperature()
        self.sig_last_temperature.emit(val)
        return val

    def set_field(self):
        self.sig_setting_field.emit('setting...')
        self.hardware.set_field(self.setpoint_tesla*10000)

    def set_field_stable(self):
        self.set_field()
        while True:
            [status, val, FieldStatusString] = self.hardware.get_field()
            self.sig_last_field.emit(val)
            if FieldStatusString == 'Holding':
                break
            time.sleep(0.001)

    def get_field(self):
        [status, val, FieldStatus] = self.hardware.get_field()
        self.sig_last_field.emit(val)
        return val/10000

    def run(self):
        if self.job == "set_temperature":
            self.set_temperature()

        elif self.job == "set_temperature_stable":
            self.set_temperature_stable()

        elif self.job == "set_field":
            self.set_field()

        elif self.job == "set_field_stable":
            self.set_field_stable()

        elif self.job == "get_temperature":
            self.get_temperature()

        elif self.job == "get_field":
            self.get_field()

        self.job = ''


if __name__ == "__main__":
    o = OptiCool_Logic()
    o.setpoint_tesla = 1e-3
    o.set_field()
    # o.setpoint_temperature = 1.55
    # o.set_temperature()
