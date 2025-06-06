import numpy as np
from PyQt6 import QtCore, QtWidgets, uic
import time
from nidaq_hardware import NIDAQHardWare
import sys


class NIDAQLogic(QtCore.QThread):
    sig_new_write = QtCore.pyqtSignal(object)
    sig_new_read = QtCore.pyqtSignal(object)
    sig_name = QtCore.pyqtSignal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.daq = NIDAQHardWare()
        self.dev_name = ""
        self.reset_flags()
        self.accumuate_time = 0.1
        self.is_initialized = False
        self.AI_sample_rate = 35000
        self.set_accumulate_count_num()

    def reset_flags(self):
        self.receieved_stop = False

    def initialize(self, dev_name):
        if self.is_initialized:
            self.close()
        self.dev_name = dev_name

        self.AO_channels = ["AO0", "AO1"]
        for ch in self.AO_channels:
            ch = "/" + self.dev_name + "/" + ch
            self.daq.setup_single_AO_task(ch)
        self.next_channel = "AO0"
        self.target_AO = {"AO0": 0.0, "AO1": 0.0, "AO2": 0.0, "AO3": 0.0}
        self.hold_AO = {
            "AO0": 0.0,
            "AO1": 0.0,
            "AO2": 0.0,
            "AO3": 0.0,
        }  # used for coupled channels like rotator

        self.AI_channels = ["AI0", "AI1", "AI2", "AI3"]
        for ch in self.AI_channels:
            ch = "/" + self.dev_name + "/" + ch
            self.daq.setup_single_AI_task(ch)
        self.read_channel = "AI0"

        self.setup_sample_counter()

        self.reset_flags()
        self.wait_sec = 10
        self.is_initialized = True
        self.sig_name.emit(dev_name)

    def close(self):
        if not self.is_initialized:
            print(f"device {self.dev_name} is already disconnected")
            return
        for ch in self.AO_channels:
            ch = "/" + self.dev_name + "/" + ch
            self.daq.close_single_AO_task(ch)

        for ch in self.AI_channels:
            ch = "/" + self.dev_name + "/" + ch
            self.daq.close_single_AI_task(ch)
        self.daq.close_sample_counter()

        self.is_initialized = False
        self.sig_name.emit("None")

    #############      start of AO    ###############
    def setup_AO(self, ch, val):
        self.daq.write_single_AO_task("/" + self.dev_name + "/" + ch, val)
        self.sig_new_write.emit([self.AO_channels.index(ch), val])

    def set_AO0(self, val):
        self.setup_AO("AO0", val)

    def set_AO1(self, val):
        self.setup_AO("AO1", val)

    def assign_AO_target(self, channel, val):
        self.target_AO[channel] = val

    def setup_channel(self, channel):
        self.next_channel = channel

    def setup_wait_sec(self, sec):
        self.wait_sec = sec

    def emit_pulse(self):
        for a in [5, 5, 5, 5, 5, 0, 0, 0, 0, 0]:
            self.daq.write_single_AO_task(f"/{self.dev_name}/AO3", a)
        time.sleep(self.wait_sec)

    #############        end of AO      ###############

    ############# start of sample edge counter ###############
    def setup_sample_counter(self):
        name = self.dev_name
        self.daq.setup_sample_counter(chan=f"/{name}/Ctr0")

    def close_sample_counter(self):
        self.daq.close_sample_counter()

    def get_sample_count(self):
        cnt = self.daq.get_sample_count(wait_time=self.accumuate_time)
        self.sig_new_read.emit(["count", cnt])
        return cnt

    ############# end of sample edge counter ###############

    #############       start of AI     ###############
    
    def set_accumulate_count_num(self):
        count_num = round(self.AI_sample_rate * self.accumuate_time)
        if 1 < count_num < 2047:
            self.accumulate_count_num = count_num
        elif count_num < 1:
            self.accumulate_count_num = 1
        elif count_num > 2047:
            self.accumulate_count_num = 2047

    def read_AI(self, ch):
        read = self.daq.read_mult_AI_task("/" + self.dev_name + "/" + ch, self.accumulate_count_num)
        self.sig_new_read.emit([ch,read])
        return read

    def get_AI0(self):
        return self.read_AI("AI0")

    def get_AI1(self):
        return self.read_AI("AI1")

    def get_AI2(self):
        return self.read_AI("AI2")

    def get_AI3(self):
        return self.read_AI("AI3")

    def get_AI4(self):
        return self.read_AI("AI4")

    def get_AI5(self):
        return self.read_AI("AI5")

    def get_AI6(self):
        return self.read_AI("AI6")

    def assign_next_AI_channel(self, channel):
        self.next_AI_channel = channel

    #####################################################
    def run(self):
        if self.job == "write_AO0":
            self.set_AO0(self.target_AO0)

        elif self.job == "write_AO1":
            self.set_AO1(self.target_AO1)

        elif self.job == "read_AI":
            self.read_AI(self.next_AI_channel)

        elif self.job == "read_single_sample_count":
            self.get_sample_count()

        elif self.job == "write_AO":
            self.setup_AO(self.next_channel, self.target_AO[self.next_channel])

        elif self.job == "pulse":
            self.emit_pulse()

        self.reset_flags()
        self.job = ""


if __name__ == "__main__":

    l = NIDAQLogic()
    l.initialize("Dev1")
