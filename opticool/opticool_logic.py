from PyQt6 import QtCore
from .opticool_hardware import OptiCool_Hardware
import time
import numpy as np


class OptiCool_Logic(QtCore.QThread):
    sig_last_temperature = QtCore.pyqtSignal(object)
    sig_last_field = QtCore.pyqtSignal(object)
    sig_setting_temperature = QtCore.pyqtSignal(object)
    sig_setting_field = QtCore.pyqtSignal(object)
    sig_status = QtCore.pyqtSignal(object)
    sig_is_connected = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.hardware = OptiCool_Hardware()
        self.job = ""
        self.setpoint_temperature = 0.0
        self.setpoint_tesla = 0.0
        self.is_connected = False

    def _ensure_connected(self):
        if not self.is_connected:
            raise RuntimeError("OptiCool is not connected.")

    def connect(self):
        if self.is_connected:
            self.sig_is_connected.emit(f"Connecting Status: {self.is_connected}")
            self.sig_status.emit("Already connected.")
            return

        try:
            self.is_connected = bool(self.hardware.connect_hardware())
        except Exception as exc:
            self.is_connected = False
            self.sig_status.emit(f"Connection failed: {exc}")

        self.sig_is_connected.emit(f"Connecting Status: {self.is_connected}")
        if self.is_connected:
            self.sig_status.emit("Connection successful.")
        else:
            self.sig_status.emit("Connection failed.")

    def disconnect(self):
        if not self.is_connected:
            self.sig_is_connected.emit(f"Connecting Status: {self.is_connected}")
            self.sig_status.emit("Already disconnected.")
            return

        try:
            self.hardware.disconnect()
            self.is_connected = False
            self.sig_is_connected.emit(f"Connecting Status: {self.is_connected}")
            self.sig_status.emit("Disconnected.")
        except Exception as exc:
            self.sig_status.emit(f"Disconnect failed: {exc}")

    def set_temperature(self, target_k):
        self._ensure_connected()
        self.sig_setting_temperature.emit("setting...")
        self.hardware.set_temperature(float(target_k))
        self.get_temperature()

    def set_temperature_stable(self, target_k):
        self._ensure_connected()
        self.set_temperature(target_k)
        read_arr = np.zeros(50)
        while True:
            [status, val, temperature_status_string] = self.hardware.get_temperature()
            self.sig_last_temperature.emit(val)
            read_arr[-1] = val
            read_arr[0:-1] = read_arr[1::]

            if temperature_status_string in ["Stable"]:
                break
            elif np.std(read_arr) < 0.0001:
                break
            time.sleep(0.1)

    def get_temperature(self):
        self._ensure_connected()
        [status, val, temperature_status] = self.hardware.get_temperature()
        self.sig_last_temperature.emit(val)
        return val

    def set_field(self, target_t):
        self._ensure_connected()
        self.sig_setting_field.emit("setting...")
        self.hardware.set_field(float(target_t) * 10000)

    def set_field_stable(self, target_t):
        self._ensure_connected()
        self.set_field(target_t)
        while True:
            [status, val, field_status_string] = self.hardware.get_field()
            self.sig_last_field.emit(val)
            if field_status_string == "Holding":
                break
            time.sleep(0.001)

    def get_field(self):
        self._ensure_connected()
        [status, val, field_status] = self.hardware.get_field()
        self.sig_last_field.emit(val)
        return val / 10000

    def run(self):
        try:
            if self.job == "connect":
                self.connect()

            elif self.job == "disconnect":
                self.disconnect()

            elif self.job == "set_temperature":
                self.set_temperature(self.setpoint_temperature)

            elif self.job == "set_temperature_stable":
                self.set_temperature_stable(self.setpoint_temperature)

            elif self.job == "set_field":
                self.set_field(self.setpoint_tesla)

            elif self.job == "set_field_stable":
                self.set_field_stable(self.setpoint_tesla)

            elif self.job == "get_temperature":
                self.get_temperature()

            elif self.job == "get_field":
                self.get_field()
        except Exception as exc:
            self.sig_status.emit(f"OptiCool error: {exc}")
        finally:
            self.job = ""


if __name__ == "__main__":
    o = OptiCool_Logic()
    o.connect()
    o.setpoint_tesla = 1e-3
    o.set_field(o.setpoint_tesla)
    # o.setpoint_temperature = 1.55
    # o.set_temperature(o.setpoint_temperature)
