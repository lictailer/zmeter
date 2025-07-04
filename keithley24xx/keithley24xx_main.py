from PyQt6 import QtWidgets, uic, QtCore
import sys
from keithley24xx.keithley24xx_logic import Keithley24xxLogic
import numpy as np
import pyqtgraph as pg
import pyvisa
import time


class Keithley24xx(QtWidgets.QWidget):
    def __init__(self):
        super(Keithley24xx, self).__init__()
        uic.loadUi("keithley24xx/keithley24xx.ui", self)
        self.logic = Keithley24xxLogic()
        self.connect_sig_slot()
        self.is_connected = False
        resource_manager = pyvisa.ResourceManager()
        ls = resource_manager.list_resources()
        self.address_cb.addItems(ls)
        self.ramp_rate_label.setText(
            f"Current ramp rate: {self.logic.ramp_rate:.2e} V/s"
        )

    def connect_visa(self, addr):
        if self.is_connected:
            print("device already connected")
            return
        self.logic.addr = addr
        self.logic.do_connect = True
        self.logic.start()
        self.address_cb.setCurrentText(addr)

    def connect_sig_slot(self):
        self.connect_btn.clicked.connect(self.when_connect_clicked)
        self.disconnect_btn.clicked.connect(self.when_close_clicked)
        self.sour_func_cb.currentTextChanged.connect(self.update_sour_func)
        self.sens_func_cb.currentTextChanged.connect(self.update_sens_func)
        self.go_btn.clicked.connect(self.when_go_button_clicked)
        self.read_btn.clicked.connect(self.when_read_clicked)
        self.stop_btn.clicked.connect(self.force_stop)
        self.reset_btn.clicked.connect(self.reset)
        self.ramp_rate_pb.clicked.connect(self.set_ramp_rate)

        self.logic.sig_last_set.connect(self.update_set)
        self.logic.sig_new_read.connect(self.update_read)
        self.logic.sig_on_off.connect(self.on_off_label)

    def force_stop(self):
        self.logic.force_stop = True

    def reset(self):
        self.logic.do_reset = True
        self.logic.start()

    def set_ramp_rate(self):
        val = float(self.ramp_rate.value())
        t = f"Current ramp rate: {val:.2e} V/s"
        self.ramp_rate_label.setText(t)
        self.logic.ramp_rate = val
        # Maintain backward-compatibility for any code that still reads volt_ramp_step
        self.logic.volt_ramp_step = val / self.logic.points_per_sec

    def update_sour_func(self, t):
        if t == "volt":
            self.logic.sour_func_to_volt()
        if t == "curr":
            self.logic.sour_func_to_curr()

    def update_sens_func(self, t):
        if t == "volt":
            self.logic.sens_func_to_volt()
        if t == "curr":
            self.logic.sens_func_to_curr()

    def update_set(self, val):
        # Use scientific notation so very small or very large numbers are rendered accurately
        if self.logic.sour == "volt":
            t = f"last set: {val:.4e} volts"
        elif self.logic.sour == "curr":
            t = f"last set: {val:.4e} Amps"
        self.sour_label.setText(t)

    def update_read(self, val):
        # Use scientific notation for accurate representation of small readings
        if self.logic.sens == "volt":
            t = f"last read: {val:.4e} volts"
        elif self.logic.sens == "curr":
            t = f"last read: {val:.4e} Amps"
        self.sens_label.setText(t)

    def when_go_button_clicked(self):
        if not self.is_connected:
            print("device not connected")
            return
        val = float(self.next_pos_le.text())
        self.logic.update_next_pos(val)
        if self.logic.sour == "volt":
            self.logic.do_volt = True
        if self.logic.sour == "curr":
            self.logic.do_curr = True
        self.logic.start()

    def when_read_clicked(self):
        if not self.is_connected:
            print("device not connected")
            return
        self.logic.do_read = True
        self.logic.start()

    def when_connect_clicked(self):
        if self.is_connected:
            print("device already connected")
            return
        self.logic.addr = self.address_cb.currentText()
        self.logic.do_connect = True
        self.logic.start()

    def when_close_clicked(self):
        if not self.is_connected:
            print("device not connected")
            return
        self.logic.do_close = True
        self.logic.start()

    def on_off_label(self, state):
        if state:
            t = "ON"
            self.is_connected = True
        else:
            t = "OFF"
            self.is_connected = False
        self.label_on_off.setText(t)

    def set_curr(self, val):
        self.logic.update_next_pos(val)
        self.logic.do_curr = True
        self.logic.start()

    def set_volt(self, val):
        self.logic.update_next_pos(val)
        self.logic.do_volt = True
        self.logic.start()
        while self.logic.isRunning():
            time.sleep(0.1)

    def terminate_dev(self):
        try:
            if self.is_connected:
                # Stop any ongoing operations
                self.logic.force_stop = True
                
                # Wait for any running thread to finish
                if self.logic.isRunning():
                    self.logic.wait(2000)  # Wait up to 2 seconds
                
                # Safely disconnect the device
                self.logic.close()
                
                # Update connection status
                self.is_connected = False
                self.on_off_label(False)
                
                print("Keithley24xx terminated safely.")
            else:
                print("Device was not connected.")
        except Exception as e:
            print(f"Error during termination: {e}")
        finally:
            # Ensure cleanup even if errors occur
            self.is_connected = False
            if hasattr(self.logic, 'k24xxHardware'):
                self.logic.k24xxHardware.inst = None

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = Keithley24xx()
    window.show()
    app.exec()
    # resource_manager = pyvisa.ResourceManager()
    # ls = resource_manager.list_resources()
    # print(ls)