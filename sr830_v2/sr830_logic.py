import time
from PyQt6 import QtCore

from .sr830_hardware import SR830_Hardware


class SR830_Logic(QtCore.QThread):
    sig_sensitivity = QtCore.pyqtSignal(object)
    sig_time_constant = QtCore.pyqtSignal(object)
    sig_frequency = QtCore.pyqtSignal(object)
    sig_amplitude = QtCore.pyqtSignal(object)
    sig_phase = QtCore.pyqtSignal(object)
    sig_X = QtCore.pyqtSignal(object)
    sig_Y = QtCore.pyqtSignal(object)
    sig_R = QtCore.pyqtSignal(object)
    sig_Theta = QtCore.pyqtSignal(object)
    sig_ref_input = QtCore.pyqtSignal(object)
    sig_ext_trigger = QtCore.pyqtSignal(object)
    sig_sync_filter = QtCore.pyqtSignal(object)
    sig_harmonic = QtCore.pyqtSignal(object)
    sig_input_config = QtCore.pyqtSignal(object)
    sig_input_shield = QtCore.pyqtSignal(object)
    sig_input_coupling = QtCore.pyqtSignal(object)
    sig_notch_filter = QtCore.pyqtSignal(object)
    sig_reserve = QtCore.pyqtSignal(object)
    sig_filter_slope = QtCore.pyqtSignal(object)
    sig_unlocked = QtCore.pyqtSignal(object)
    sig_input_overload = QtCore.pyqtSignal(object)
    sig_time_constant_overload = QtCore.pyqtSignal(object)
    sig_output_overload = QtCore.pyqtSignal(object)

    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)
    sig_log = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.job: str = ""

        self.setpoint_frequency = 10
        self.setpoint_amplitude = 1
        self.setpoint_time_constant = 0
        self.setpoint_sensitivity = 0
        self.setpoint_phase = 0
        self.setpoint_ref_input = 0
        self.setpoint_ext_trigger = 0
        self.setpoint_sync_filter = 0
        self.setpoint_harmonic = 0
        self.setpoint_input_config = 0
        self.setpoint_input_shield = 0
        self.setpoint_input_coupling = 0
        self.setpoint_notch_filter = 0
        self.setpoint_reserve = 0
        self.setpoint_filter_slope = 0
        self.setpoint_aux_1 = 0
        self.setpoint_aux_2 = 0

        self.connected = False
        self.reject_signal = False
        self.monitor_count = 10

        self.hardware: SR830_Hardware | None = None

    def _emit_log(self, message: str, level: str = "INFO"):
        self.sig_log.emit((level, str(message)))

    def _cleanup_connection(self):
        if self.hardware is None:
            return
        try:
            self.hardware.disconnect()
        except Exception as exc:
            self._emit_log(f"Error during hardware.disconnect(): {exc}", level="WARN")
        finally:
            self.hardware = None

    def connect_visa(self, address: str):
        self.reject_signal = True
        self.job = ""
        if self.isRunning():
            self.wait()
        self.reject_signal = False

        self.connected = False
        self._cleanup_connection()

        temp_hardware: SR830_Hardware | None = None
        try:
            temp_hardware = SR830_Hardware(address)
            idn = temp_hardware.idn()
            if not idn:
                raise RuntimeError("No response to *IDN? query.")
            if "SR830" not in idn.upper():
                raise ValueError(f"Unexpected instrument identity: {idn}")

            self.hardware = temp_hardware
            self.connected = True
            self.sig_connected.emit(f"connected to {address}")
            self._emit_log(f"Connected to {address}: {idn}", level="INFO")
            return True
        except Exception as exc:
            if temp_hardware is not None:
                try:
                    temp_hardware.disconnect()
                except Exception:
                    pass
            self.hardware = None
            self.connected = False
            self.sig_connected.emit("connection failed")
            self._emit_log(f"Connection failed for {address}: {exc}", level="ERROR")
            return False

    def get_sensitivity(self):
        assert self.hardware is not None
        val = self.hardware.get_sensitivity()
        self.sig_sensitivity.emit(val)
        return val

    def get_time_constant(self):
        assert self.hardware is not None
        val = self.hardware.get_time_constant()
        self.sig_time_constant.emit(val)
        return val

    def get_frequency(self):
        assert self.hardware is not None
        val = self.hardware.get_frequency()
        self.sig_frequency.emit(val)
        return val

    def get_amplitude(self):
        assert self.hardware is not None
        val = self.hardware.get_amplitude()
        self.sig_amplitude.emit(val)
        return val

    def get_phase(self):
        assert self.hardware is not None
        val = self.hardware.get_phase()
        self.sig_phase.emit(val)
        return val

    def get_X(self):
        assert self.hardware is not None
        val = self.hardware.get_X()
        self.sig_X.emit(val)
        return val

    def get_Y(self):
        assert self.hardware is not None
        val = self.hardware.get_Y()
        self.sig_Y.emit(val)
        return val

    def get_R(self):
        assert self.hardware is not None
        val = self.hardware.get_R()
        self.sig_R.emit(val)
        return val

    def get_Theta(self):
        assert self.hardware is not None
        val = self.hardware.get_Theta()
        self.sig_Theta.emit(val)
        return val

    def get_ref_input(self):
        assert self.hardware is not None
        val = self.hardware.get_ref_input()
        self.sig_ref_input.emit(val)
        return val

    def get_ext_trigger(self):
        assert self.hardware is not None
        val = self.hardware.get_ext_trigger()
        self.sig_ext_trigger.emit(val)
        return val

    def get_sync_filter(self):
        assert self.hardware is not None
        val = self.hardware.get_sync_filter()
        self.sig_sync_filter.emit(val)
        return val

    def get_harmonic(self):
        assert self.hardware is not None
        val = self.hardware.get_harmonic()
        self.sig_harmonic.emit(val)
        return val

    def get_input_config(self):
        assert self.hardware is not None
        val = self.hardware.get_input_config()
        self.sig_input_config.emit(val)
        return val

    def get_input_shield(self):
        assert self.hardware is not None
        val = self.hardware.get_input_shield()
        self.sig_input_shield.emit(val)
        return val

    def get_input_coupling(self):
        assert self.hardware is not None
        val = self.hardware.get_input_coupling()
        self.sig_input_coupling.emit(val)
        return val

    def get_notch_filter(self):
        assert self.hardware is not None
        val = self.hardware.get_notch_filter()
        self.sig_notch_filter.emit(val)
        return val

    def get_reserve(self):
        assert self.hardware is not None
        val = self.hardware.get_reserve()
        self.sig_reserve.emit(val)
        return val

    def get_filter_slope(self):
        assert self.hardware is not None
        val = self.hardware.get_filter_slope()
        self.sig_filter_slope.emit(val)
        return val

    def get_unlocked(self):
        assert self.hardware is not None
        val = self.hardware.get_unlocked()
        self.sig_unlocked.emit(val)
        return val

    def get_input_overload(self):
        assert self.hardware is not None
        val = self.hardware.get_input_overload()
        self.sig_input_overload.emit(val)
        return val

    def get_time_constant_overload(self):
        assert self.hardware is not None
        val = self.hardware.get_time_constant_overload()
        self.sig_time_constant_overload.emit(val)
        return val

    def get_output_overload(self):
        assert self.hardware is not None
        val = self.hardware.get_output_overload()
        self.sig_output_overload.emit(val)
        return val

    def get_aux_1(self):
        assert self.hardware is not None
        return self.hardware.read_aux(1)

    def get_aux_2(self):
        assert self.hardware is not None
        return self.hardware.read_aux(2)

    def set_frequency(self):
        assert self.hardware is not None
        self.hardware.set_frequency(self.setpoint_frequency)
        self.sig_is_changing.emit(f"frequency set to {self.setpoint_frequency}")
        self.sig_frequency.emit(self.setpoint_frequency)

    def set_amplitude(self):
        assert self.hardware is not None
        self.hardware.set_amplitude(self.setpoint_amplitude)
        self.sig_is_changing.emit(f"amplitude set to {self.setpoint_amplitude}")
        self.sig_amplitude.emit(self.setpoint_amplitude)

    def set_time_constant(self):
        assert self.hardware is not None
        self.hardware.set_time_constant(self.setpoint_time_constant)
        self.sig_is_changing.emit(f"time_constant set to {self.setpoint_time_constant}")
        self.sig_time_constant.emit(self.setpoint_time_constant)

    def set_sensitivity(self):
        assert self.hardware is not None
        self.hardware.set_sensitivity(self.setpoint_sensitivity)
        self.sig_is_changing.emit(f"sensitivity set to {self.setpoint_sensitivity}")
        self.sig_sensitivity.emit(self.setpoint_sensitivity)

    def set_phase(self):
        assert self.hardware is not None
        self.hardware.set_phase(self.setpoint_phase)
        self.sig_is_changing.emit(f"phase set to {self.setpoint_phase}")
        self.sig_phase.emit(self.setpoint_phase)

    def set_ref_input(self):
        assert self.hardware is not None
        self.hardware.set_ref_input(self.setpoint_ref_input)
        self.sig_is_changing.emit(f"ref_input set to {self.setpoint_ref_input}")
        self.sig_ref_input.emit(self.setpoint_ref_input)

    def set_ext_trigger(self):
        assert self.hardware is not None
        self.hardware.set_ext_trigger(self.setpoint_ext_trigger)
        self.sig_is_changing.emit(f"ext_trigger set to {self.setpoint_ext_trigger}")
        self.sig_ext_trigger.emit(self.setpoint_ext_trigger)

    def set_sync_filter(self):
        assert self.hardware is not None
        self.hardware.set_sync_filter(self.setpoint_sync_filter)
        self.sig_is_changing.emit(f"sync_filter set to {self.setpoint_sync_filter}")
        self.sig_sync_filter.emit(self.setpoint_sync_filter)

    def set_harmonic(self):
        assert self.hardware is not None
        self.hardware.set_harmonic(self.setpoint_harmonic)
        self.sig_is_changing.emit(f"harmonic set to {self.setpoint_harmonic}")
        self.sig_harmonic.emit(self.setpoint_harmonic)

    def set_input_config(self):
        assert self.hardware is not None
        self.hardware.set_input_config(self.setpoint_input_config)
        self.sig_is_changing.emit(f"input_config set to {self.setpoint_input_config}")
        self.sig_input_config.emit(self.setpoint_input_config)

    def set_input_shield(self):
        assert self.hardware is not None
        self.hardware.set_input_shield(self.setpoint_input_shield)
        self.sig_is_changing.emit(f"input_shield set to {self.setpoint_input_shield}")
        self.sig_input_shield.emit(self.setpoint_input_shield)

    def set_input_coupling(self):
        assert self.hardware is not None
        self.hardware.set_input_coupling(self.setpoint_input_coupling)
        self.sig_is_changing.emit(f"input_coupling set to {self.setpoint_input_coupling}")
        self.sig_input_coupling.emit(self.setpoint_input_coupling)

    def set_notch_filter(self):
        assert self.hardware is not None
        self.hardware.set_notch_filter(self.setpoint_notch_filter)
        self.sig_is_changing.emit(f"notch_filter set to {self.setpoint_notch_filter}")
        self.sig_notch_filter.emit(self.setpoint_notch_filter)

    def set_reserve(self):
        assert self.hardware is not None
        self.hardware.set_reserve(self.setpoint_reserve)
        self.sig_is_changing.emit(f"reserve set to {self.setpoint_reserve}")
        self.sig_reserve.emit(self.setpoint_reserve)

    def set_filter_slope(self):
        assert self.hardware is not None
        self.hardware.set_filter_slope(self.setpoint_filter_slope)
        self.sig_is_changing.emit(f"filter_slope set to {self.setpoint_filter_slope}")
        self.sig_filter_slope.emit(self.setpoint_filter_slope)

    def set_aux_1(self):
        assert self.hardware is not None
        self.hardware.set_aux(1, self.setpoint_aux_1)
        self.sig_is_changing.emit(f"aux_1 set to {self.setpoint_aux_1}")

    def set_aux_2(self):
        assert self.hardware is not None
        self.hardware.set_aux(2, self.setpoint_aux_2)
        self.sig_is_changing.emit(f"aux_2 set to {self.setpoint_aux_2}")

    def get_all(self):
        self.get_input_overload()
        self.get_time_constant_overload()
        self.get_output_overload()
        self.get_unlocked()
        self.get_X()
        self.get_Y()
        self.get_R()
        self.get_Theta()

        self.monitor_count += 1
        if self.monitor_count >= 10:
            self.get_frequency()
            self.get_amplitude()
            self.get_time_constant()
            self.get_sensitivity()
            self.get_phase()
            self.get_ref_input()
            self.get_ext_trigger()
            self.get_sync_filter()
            self.get_harmonic()
            self.get_input_config()
            self.get_input_shield()
            self.get_input_coupling()
            self.get_notch_filter()
            self.get_reserve()
            self.get_filter_slope()
            self.get_aux_1()
            self.get_aux_2()
            self.monitor_count = 0

        time.sleep(0.05)

    def disconnect(self):
        self.reject_signal = True
        self.job = ""

        if self.isRunning():
            self.wait()

        self._cleanup_connection()

        if self.connected:
            self.connected = False
            self.sig_connected.emit("disconnected")
            self._emit_log("Disconnected SR830.", level="INFO")

        self.reject_signal = False

    def run(self):
        if self.reject_signal or not self.connected or self.hardware is None:
            return

        if self.job:
            fn = getattr(self, self.job, None)
            if callable(fn):
                try:
                    fn()
                except Exception as exc:
                    self._emit_log(f"SR830_Logic job '{self.job}' error: {exc}", level="ERROR")
            else:
                self._emit_log(f"SR830_Logic has no job '{self.job}'", level="WARN")
            self.job = ""

    def stop(self):
        self.reject_signal = True
        self.quit()
        self.wait()
        self.reject_signal = False
