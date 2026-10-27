from PyQt6 import QtCore
import time
import ctypes
import math
import threading
# from scipy.io import savemat
from ctypes import cdll, c_long, c_ulong, c_uint32, byref, create_string_buffer, c_bool, c_char_p, c_int, c_int16, c_double, sizeof, c_voidp
from .tlpm_hardware import TLPM_Hardware


class TLPMLogic(QtCore.QThread):

    # Read-only getters recorded by setup capture at scan start and end.
    # Labs can add or remove names in lab_context/snapshot_channels.json.
    SNAPSHOT_GETTERS = (
        "power",
    )

    sig_power = QtCore.pyqtSignal(object)
    sig_info = QtCore.pyqtSignal(str)
    sig_connect = QtCore.pyqtSignal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.is_connected = False
        self._hardware_lock = threading.RLock()
        self.target = None
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
        discovery = None
        hardware = None
        try:
            discovery = TLPM_Hardware()
            deviceCount = c_uint32()
            discovery.findRsrc(byref(deviceCount))
            self.pass_info("TLPM devices found: " + str(deviceCount.value))
            if deviceCount.value == 0:
                raise RuntimeError("No TLPM device was found")

            resourceName = create_string_buffer(1024)
            discovery.getRsrcName(c_int(0), resourceName)
            resource_string = c_char_p(resourceName.raw).value
            if not resource_string:
                raise RuntimeError("The first TLPM resource has no identifier")
            self.pass_info(str(resource_string))

            hardware = TLPM_Hardware()
            hardware.open(
                create_string_buffer(resource_string),
                c_bool(True),
                c_bool(True),
            )
            message = create_string_buffer(1024)
            hardware.getCalibrationMsg(message)
            self.pass_info(str(c_char_p(message.raw).value))
        except Exception:
            if hardware is not None:
                try:
                    hardware.close()
                except Exception:
                    pass
            self.is_connected = False
            self.sig_connect.emit(False)
            raise
        finally:
            if discovery is not None:
                try:
                    discovery.close()
                except Exception:
                    pass

        self.hardware = hardware
        self.is_connected = True
        self.sig_connect.emit(True)

    def disconnect(self):
        with self._hardware_lock:
            if not self.is_connected:
                return
            self.hardware.close()
            self.is_connected = False
        self.sig_connect.emit(False)

    def queue_wavelength(self, target):
        """Store a validated UI target for the TLPM worker thread."""
        self.target = self._wavelength_value(target)

    def change_wavelength(self):
        if self.target is None:
            raise RuntimeError("TLPM wavelength target has not been set")
        return self.set_wavelength(self.target)

    def set_wavelength(self, wavelength_nm):
        """Synchronously set the meter's wavelength correction in nanometers."""
        value = self._wavelength_value(wavelength_nm)
        with self._hardware_lock:
            if not self.is_connected:
                raise RuntimeError("TLPM is not connected")
            self.hardware.setWavelength(ctypes.c_double(value))
        return value

    def read_power(self):
        power = c_double()
        with self._hardware_lock:
            if not self.is_connected:
                raise RuntimeError("TLPM is not connected")
            self.hardware.measPower(byref(power))
        self.sig_power.emit(power.value)
        return power.value

    def read_indefinitely(self):
        while not self.receieved_stop:
            self.read_power()
            time.sleep(1/self.freq)

    def request_stop(self):
        self.receieved_stop = True

    def get_power(self):
        power = c_double()
        with self._hardware_lock:
            if not self.is_connected:
                raise RuntimeError("TLPM is not connected")
            self.hardware.measPower(byref(power))
        return power.value

    @staticmethod
    def _wavelength_value(value):
        try:
            converted = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("TLPM wavelength must be numeric") from exc
        if not math.isfinite(converted):
            raise ValueError("TLPM wavelength must be finite")
        return converted
    
    def run(self):
        was_connect = self.do_connect
        try:
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
        except Exception as exc:
            if was_connect:
                self.is_connected = False
            self.pass_info(f"TLPM error: {exc}")
        finally:
            self.reset_flags()


if __name__ == "__main__":
    l = TLPMLogic()
    l.connect()
    p = l.read_power()
    print(p)
    l.disconnect()
