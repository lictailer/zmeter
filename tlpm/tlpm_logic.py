from PyQt6 import QtCore
import time
import ctypes
# from scipy.io import savemat
from ctypes import cdll, c_long, c_ulong, c_uint32, byref, create_string_buffer, c_bool, c_char_p, c_int, c_int16, c_double, sizeof, c_voidp
from .tlpm_hardware import TLPM_Hardware


class TLPMLogic(QtCore.QThread):
    sig_power = QtCore.pyqtSignal(object)
    sig_info = QtCore.pyqtSignal(str)
    sig_connect = QtCore.pyqtSignal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.is_connected = False
        self.reset_flags()
        self.freq = 20

    def pass_info(self, info):
        self.sig_info.emit(info)
        print(info)

    def reset_flags(self):
        self.do_connect = False
        self.do_disconnect = False
        self.do_read_power = False
        self.do_change_wavelength = False
        self.do_read_indefinitely = False

        self.receieved_stop = False

    def connect(self):
        if self.is_connected:
            return
        tlPM = TLPM_Hardware()
        deviceCount = c_uint32()
        tlPM.findRsrc(byref(deviceCount))
        self.pass_info("TLPM devices found: " + str(deviceCount.value))
        resourceName = create_string_buffer(1024)

        for i in range(0, deviceCount.value):
            tlPM.getRsrcName(c_int(i), resourceName)
            self.pass_info(str(c_char_p(resourceName.raw).value))
            break
        tlPM.close()

        self.hardware = TLPM_Hardware()
        self.hardware.open(resourceName, c_bool(True), c_bool(True))
        message = create_string_buffer(1024)
        self.hardware.getCalibrationMsg(message)
        info = c_char_p(message.raw).value
        self.pass_info(str(info))
        self.sig_connect.emit(True)
        self.is_connected = True

    def disconnect(self):
        if not self.is_connected:
            return
        self.hardware.close()
        self.sig_connect.emit(False)
        self.is_connected = False

    def set_wavelength_target(self, target):
        self.target = target

    def change_wavelength(self):
        self.hardware.setWavelength(ctypes.c_double(self.target))

    def read_power(self):
        power = c_double()
        self.hardware.measPower(byref(power))
        self.sig_power.emit(power.value)
        return power.value

    def read_indefinitely(self):
        while not self.receieved_stop:
            self.read_power()
            time.sleep(1/self.freq)

    def get_power(self):
        power = c_double()
        self.hardware.measPower(byref(power))
        return power.value
    
    def run(self):
        if self.do_connect:
            self.connect()
        elif self.do_disconnect:
            self.disconnect()
        elif self.do_read_power:
            self.read_power()
        elif self.do_read_indefinitely:
            self.read_indefinitely()
        elif self.do_change_wavelength:
            self.change_wavelength()
        self.reset_flags()


if __name__ == "__main__":
    l = TLPMLogic()
    l.connect()
    p = l.read_power()
    print(p)
    l.disconnect()
