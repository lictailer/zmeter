from PyQt6 import QtCore
from .keithley24xx_hardware import Keithly24xxHardware
import numpy as np
import time


class Keithley24xxLogic(QtCore.QThread):
    sig_new_read = QtCore.pyqtSignal(object)
    sig_on_off = QtCore.pyqtSignal(object)
    sig_last_set = QtCore.pyqtSignal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.k = Keithly24xxHardware()
        self.addr = ""
        self.next_pos = 0
        self.reset_flags()
        self.volt_ramp_step = 1e-2
        self.force_stop = False

    def reset_flags(self):
        self.do_volt = False
        self.do_curr = False
        self.do_read = False
        self.do_connect = False
        self.do_close = False
        self.force_stop = False
        self.do_reset = False

    def initialize(self, addr):
        self.k.initialize(addr)
        self.set_sour_func_to_volt()
        self.set_sens_func_to_curr()
    # ---------------------------- sour ----------------------------

    def set_sour_func_to_volt(self):
        self.k.set_sour_func_to_volt()
        self.sour = 'volt'

    def set_sour_func_to_curr(self):
        self.k.set_sour_func_to_curr()
        self.sour = 'curr'
    # ---------------------------- sens ----------------------------

    def set_sens_func_to_volt(self, compliance=200):
        self.k.set_sens_func_to_volt(compliance)
        self.sens = 'volt'

    def set_sens_func_to_curr(self, compliance=1e-5):
        self.k.set_sens_func_to_curr(compliance)
        self.sens = 'curr'
    # ---------------------------- set ----------------------------

    def set_sour_volt_to(self, val):
        if self.sour != 'volt':
            return
        self.k.set_sour_volt_to(val)
        read = self.k.read()
        self.sig_last_set.emit(val)
        # print('sdsds',val)

    def set_sour_volt_to_rampmode(self, val):
        if self.sour != 'volt':
            return
        self.ramp_voltage_to(val)


    def set_sour_curr_to(self, val):
        if self.sour != 'curr':
            return
        self.k.set_sour_curr_to(val)
        self.sig_last_set.emit(val)
    # ---------------------------- read ----------------------------

    def read(self):
        r = self.k.read()
        r = float(r)
        self.sig_new_read.emit(r)
        return r
    
    def get_volt(self):
        self.set_sens_func_to_volt()
        r = self.k.read()
        r = float(r)
        self.sig_new_read.emit(r)
        return r

    def get_curr(self):
        self.set_sens_func_to_curr()
        r = self.k.read()
        r = float(r)
        self.sig_new_read.emit(r)
        return r

    # --------------------------------------------------------------

    def close(self):
        pass

    def ramp_voltage_to(self, val):
        change_back_to_curr = False
        if self.sens == 'curr':
            change_back_to_curr = True
        self.set_sens_func_to_volt()
        read = self.k.read()
        read = float(read)
        step = np.sign(val - read) * np.abs(self.volt_ramp_step)
        values = np.append(np.arange(read, val, step), np.array([val]))
        for v in values:
            if self.force_stop:
                break
            self.set_sour_volt_to(v)
            time.sleep(0.01)
            self.read()
        if change_back_to_curr:
            self.set_sens_func_to_curr()

    def set_next_func(self, fn):
        self.next_func = fn

    def set_next_pos(self, val):
        self.next_pos = val
        
    def reset(self):
        self.k.reset()



    def run(self):
        if self.do_volt:
            self.ramp_voltage_to(self.next_pos)
        elif self.do_curr:
            self.set_sour_curr_to(self.next_pos)
        elif self.do_read:
            self.read()
        elif self.do_connect:
            self.initialize(self.addr)
            self.sig_on_off.emit(True)
        elif self.do_close:
            self.close()
            self.sig_on_off.emit(False)
        elif self.do_reset:
            self.reset()
        self.reset_flags()


if __name__ == "__main__":
    addr = 'GPIB1::19::INSTR'
    k = Keithley24xxLogic()
    k.initialize(addr=addr)
    k.set_sour_volt_to(0)
    print("Success A")
    k.ramp_voltage_to(2)
