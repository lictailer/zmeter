import numpy as np
from PyQt6 import QtCore, QtWidgets, uic
import time
from .anc300_hardware_hardware import ANC300Hardware
import sys

class ANC300Logic(QtCore.QThread):
    sig_new_write = QtCore.pyqtSignal(object)
    sig_new_read = QtCore.pyqtSignal(object)
    sig_name = QtCore.pyqtSignal(object)
    sig_capacitance = QtCore.pyqtSignal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.ANC300 = ANC300Hardware()
        self.dev_name = ""
        self.reset_flags()
        self.is_initialized = False

        self.anm150_list = [1, 2, 3]
        self.anm200_list = [4, 5]


    def reset_flags(self):
        self.receieved_stop = False

    def initialize(self, port_name=""):
        if self.is_initialized:
            self.close()
        self.port_name = port_name

        self.is_initialized = self.ANC300.initialize(self.port_name)
        self.reset_flags()

        if self.is_initialized:
            self.set_all_axis_gnd()
            self.sig_name.emit(self.port_name)


    def set_all_axis_gnd(self):
        for i in self.anm150_list:
            self.ANC300.set_anm150_ground(i)
        for i in self.anm200_list:
            self.ANC300.set_anm200_ground(i)

    def set_axis_gnd(self, axis):
        if axis in self.anm150_list:
            self.ANC300.set_anm150_ground(axis)
        elif axis in self.anm200_list:
            self.ANC300.set_anm200_ground(axis)
        else:
            print(f"Invalid axis: {axis}")
        
    def set_enable_anm150(self, axis):
        if axis in self.anm150_list:
            self.ANC300.set_anm150_mode(axis)
        else:
            print(f"Invalid axis: {axis}")
    
    def set_enable_anm200(self, axis):
        if axis in self.anm200_list:
            self.ANC300.set_anm200_mode_to_inp(axis)
        else:
            print(f"Invalid axis: {axis}")

    def update_all_axis_capacitance(self):
        capacitances = {}
        for axis in self.anm150_list + self.anm200_list:
            capacitances[axis] = self.ANC300.get_anm200_capacitance(axis)
        for axis in self.anm150_list:
            capacitances[axis] = self.ANC300.get_anm150_step_volt(axis)
        return capacitances

        

