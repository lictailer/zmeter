import numpy as np
from PyQt6 import QtCore, QtWidgets, uic
import time
from anc300_hardware import ANC300Hardware
import sys

class ANC300Logic(QtCore.QThread):
    sig_name = QtCore.pyqtSignal(object)
    sig_ANC300_info =  QtCore.pyqtSignal(object)  #record axis freq, step size, capacitance signal
    sig_cap_measurement_info = QtCore.pyqtSignal(object)  #record axis capacitance measurement status
    sig_anm150_pos_indictor = QtCore.pyqtSignal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.ANC300 = ANC300Hardware()
        self.dev_name = ""
        self.reset_flags()
        self.is_initialized = False
        self.job = ""
        self._positioner_refresh_rate = 10 #Hz

        self.anm150_list = [1, 2, 3]
        self.anm200_list = [4, 5]

        self.ANC300_info = {}
        for axis in self.anm150_list:
            self.ANC300_info[axis] = {'mode': 'unknown',
                                      'capacitance': 0.0, 
                                      'step_volt': 0.0, 
                                      'freq': 0.0,
                                      'pos': 0}
        for axis in self.anm200_list:
            self.ANC300_info[axis] = {'mode': 'unknown',
                                      'capacitance': 0.0}
        self.sig_ANC300_info.emit(self.ANC300_info)

    def reset_flags(self):
        self.receieved_stop = False

    def initialize(self, port_name=""):
        if self.is_initialized:
            self.close()
        self.port_name = port_name

        self.is_initialized = self.ANC300.initialize(self.port_name)
        self.reset_flags()

        if self.is_initialized:
            self.set_ground_all_axis()
            self.sig_name.emit(self.port_name)
            self.reset_pos_indictor()

    def close(self):
        self.set_ground_all_axis()
        self.ANC300.close()
        self.sig_name.emit("Disconnected")

    def reset_pos_indictor(self):
        for axis in self.anm150_list + self.anm200_list:
            self.ANC300_info[axis]['pos'] = 0
        self.sig_ANC300_info.emit(self.ANC300_info)

    #----------------------------- ANM150/200 Mode Switch ----------------------------
    def set_ground_all_axis(self):
        for axis in self.anm150_list + self.anm200_list:
            self.ANC300.set_mode(axis, 'gnd')
            
        
        self.sig_ANC300_info.emit(self.ANC300_info)

    def set_ground_axis(self, axis):
        if axis in self.anm150_list:
            self.ANC300.set_anm150_ground(axis)
        elif axis in self.anm200_list:
            self.ANC300.set_anm200_ground(axis)
        else:
            print(f"Invalid axis: {axis}")
            return
        
        self.ANC300_info[axis]['mode'] = 'gnd'
        self.sig_ANC300_info.emit(self.ANC300_info)
        
    def set_enable_axis(self, axis):
        if axis in self.anm150_list:
            self.ANC300.set_anm150_mode_to_stp(axis)
            self.ANC300_info[axis]['mode'] = 'stp'
            self.sig_ANC300_info.emit(self.ANC300_info)
        elif axis in self.anm200_list:
            self.ANC300.set_anm200_mode_to_inp(axis)
            self.ANC300_info[axis]['mode'] = 'inp'
            self.sig_ANC300_info.emit(self.ANC300_info)
        else:
            print(f"Invalid axis: {axis}")


    #----------------------------- ANM150 Position Move ----------------------------
    def move_anm150_one_step(self, axis):
        self.ANC300.anm150_moveby(axis, 1)
        self.ANC300_info[axis]['pos'] += 1
        self.sig_ANC300_info.emit(self.ANC300_info)

    def move_an150_continuesly(self, axis):
        step_count = int(round(self.ANC300_info[axis]['freq'] / self._positioner_refresh_rate))
        self.ANC300.anm150_moveby(axis, step_count)
        self.ANC300_info[axis]['pos'] += step_count
        self.sig_ANC300_info.emit(self.ANC300_info)


    #----------------------------- ANM150 Properties Change (not for scan) ----------------------------
    def change_anm150_freq(self, axis, freq):
        if axis in self.anm150_list:
            self.ANC300.set_anm150_freq(axis, freq)
            self.ANC300_info[axis]['freq'] = freq
            self.sig_ANC300_info.emit(self.ANC300_info)
        else:
            print(f"Invalid axis: {axis}")

    def change_anm150_step_volt(self, axis, volt):
        if axis in self.anm150_list:
            self.ANC300.set_anm150_step_volt(axis, volt)
            self.ANC300_info[axis]['step_volt'] = volt
            self.sig_ANC300_info.emit(self.ANC300_info)
        else:
            print(f"Invalid axis: {axis}")


    #----------------------------- Read ANC300 Info ----------------------------
    def read_all_axis_info(self):
        for axis in self.anm150_list:
            self.ANC300_info[axis]['mode'] = self.ANC300.get_anm150_mode(axis)
            self.ANC300_info[axis]['step_volt'] =  self.ANC300.get_anm150_step_volt(axis)
            self.ANC300_info[axis]['freq'] = self.ANC300.get_anm150_freq(axis)
        for axis in self.anm200_list:
            self.ANC300_info[axis]['mode'] = self.ANC300.get_anm200_mode(axis)
        print(self.ANC300_info)
        self.sig_ANC300_info.emit(self.ANC300_info)

    def read_all_axis_capacitance(self):
        self.sig_cap_measurement_info.emit("Please wait till capacitance measurement is done.")

        for axis in self.anm150_list:
            self.ANC300_info[axis]['capacitance'] = self.ANC300.get_anm150_capacitance(axis)
        for axis in self.anm200_list:
            self.ANC300_info[axis]['capacitance'] = self.ANC300.get_anm200_capacitance(axis)
        print(self.ANC300_info)
        self.sig_ANC300_info.emit(self.ANC300_info)
        self.sig_cap_measurement_info.emit("")

    def run(self):
        if self.job == "enable_axis":
            self.set_enable_axis(self.target_axis)
            self.target_axis = None

        elif self.job == "ground_axis":
            self.set_ground_axis(self.target_axis)

        elif self.job == "ground_all_axis":
            self.set_ground_all_axis()

        elif self.job == "read_all_axis_capacitance":
            self.read_all_axis_capacitance()
        
        elif self.job == 'read_all_axis_info':
            self.read_all_axis_info()
        
        elif self.job == 'reset_scan_center':
            self.reset_pos_indictor()


        self.reset_flags()
        self.job = ""


    
if __name__ == "__main__":
    anc300_logic = ANC300Logic()
    # anc300_logic.initialize("COM6")  # Example port name

    time_start = time.time()
    print("start info reading", time.time())
    anc300_logic.read_all_axis_info()
    time_end = time.time()
    print("Time taken for reading info", time_end - time_start)

    print("start capacitance reading")
    time_start = time.time()
    anc300_logic.read_all_axis_capacitance()
    time_end = time.time()
    print("Time taken for reading info and capacitance:", time_end - time_start)
    anc300_logic.close()

        

