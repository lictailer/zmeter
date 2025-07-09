from PyQt6 import QtCore
import time

from sr860_hardware import SR860_Hardware


class SR860_Logic(QtCore.QThread):
    """Qt thread-wrapper that exposes **all** SR860_Hardware methods via signals.

    Naming rules (enforced project-wide):
    1. read_xxx   – purely read access; proxies <hardware>.xxx(read=True) or <hardware>.get_xxx().
    2. write_xxx  – write / set access; proxies <hardware>.xxx(write=True) or <hardware>.set_xxx().
    3. set_xxx  – boolean two-state helpers (ON / OFF like auto_range, sync_filter …).
    4. get_xxx    - get_X, get_Y, get_R, get_Theta and get_aux_in to be used as getters in scan control.

    The QThread processes queued jobs.  The *job* string **must exactly match** the wrapper
    method name so the dispatcher can automatically call it.
    """

    # ---------- value update signals ----------
    sig_frequency = QtCore.pyqtSignal(object)
    sig_amplitude = QtCore.pyqtSignal(object)
    sig_time_constant = QtCore.pyqtSignal(object)
    sig_sensitivity = QtCore.pyqtSignal(object)
    sig_phase = QtCore.pyqtSignal(object)
    sig_ref_mode = QtCore.pyqtSignal(object)
    sig_ext_trigger = QtCore.pyqtSignal(object)
    sig_ref_input = QtCore.pyqtSignal(object)
    sig_sync_filter = QtCore.pyqtSignal(object)
    sig_harmonic = QtCore.pyqtSignal(object)
    sig_signal_input_type = QtCore.pyqtSignal(object)
    sig_signal_input_mode = QtCore.pyqtSignal(object)
    sig_input_config = QtCore.pyqtSignal(object)
    sig_voltage_input_coupling = QtCore.pyqtSignal(object)
    sig_voltage_input_range = QtCore.pyqtSignal(object)

    sig_X = QtCore.pyqtSignal(object)
    sig_Y = QtCore.pyqtSignal(object)
    sig_R = QtCore.pyqtSignal(object)
    sig_Theta = QtCore.pyqtSignal(object)

    sig_display = QtCore.pyqtSignal(object)
    sig_aux_out = QtCore.pyqtSignal(object)        # (chan, value)
    sig_aux_in = QtCore.pyqtSignal(object)         # (chan, value)
    sig_unlocked = QtCore.pyqtSignal(object)
    sig_input_overload = QtCore.pyqtSignal(object)
    sig_multiple_outputs = QtCore.pyqtSignal(object)

    # ---------- generic state signals ----------
    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)

    # -------------------------------------------
    def __init__(self):
        super().__init__()

        # queued instruction executed in run()
        self.job: str = ""  # name of the next action

        # -------- set-points (write_* / setup_*) --------
        self.setpoint_frequency = 0.0
        self.setpoint_amplitude = 0.0
        self.setpoint_time_constant = 0
        self.setpoint_sensitivity = 0
        self.setpoint_phase = 0.0
        self.setpoint_ref_mode = "internal"
        self.setpoint_ext_trigger = "sine"
        self.setpoint_ref_input = 0
        self.setpoint_sync_filter = False
        self.setpoint_harmonic = 1
        self.setpoint_input_config = "0"
        self.setpoint_signal_input_type = "voltage"
        self.setpoint_signal_input_mode = "A"
        self.setpoint_voltage_input_coupling = "AC"
        self.setpoint_voltage_input_range = "1 V"
        self.setpoint_current_input_range = "1 uA"

        self.setpoint_aux_channel = 1
        self.setpoint_aux_voltage = 0.0

        self.setpoint_auto_range = False
        self.setpoint_auto_scale = False
        self.setpoint_auto_phase = False

        # for bulk read_multiple_outputs
        self.setpoint_outputs = ("X", "Y", "R")

        self.monitor_count = 10

        # runtime state
        self.connected = False
        self.reject_signal = False

        self.hardware: SR860_Hardware | None = None

    # -------------- connection helpers ----------------
    def connect_visa(self, address: str):
        """Instantiate SR860_Hardware and open VISA connection."""
        self.hardware = SR860_Hardware(address)
        self.connected = True
        self.sig_connected.emit(f"connected to {address}")

    # -------------- read wrappers ---------------------
    def read_frequency(self):
        assert self.hardware is not None
        val = self.hardware.get_frequency()
        print(f"frequency: {val}")
        self.sig_frequency.emit(val)
        return val

    def read_amplitude(self):
        assert self.hardware is not None
        val = self.hardware.get_amplitude()
        self.sig_amplitude.emit(val)
        return val

    def read_time_constant(self):
        assert self.hardware is not None
        val = self.hardware.time_constant(read=True)
        self.sig_time_constant.emit(val)
        return val

    def read_sensitivity(self):
        assert self.hardware is not None
        val = self.hardware.sensitivity(read=True)
        self.sig_sensitivity.emit(val)
        return val

    def read_phase(self):
        assert self.hardware is not None
        val = self.hardware.phase(read=True)
        self.sig_phase.emit(val)
        return val

    def read_ref_mode(self):
        assert self.hardware is not None
        val = self.hardware.ref_mode(read=True)
        self.sig_ref_mode.emit(val)
        return val

    def read_ext_trigger(self):
        assert self.hardware is not None
        val = self.hardware.ext_trigger(read=True)
        self.sig_ext_trigger.emit(val)
        return val

    def read_ref_input(self):
        assert self.hardware is not None
        val = self.hardware.ref_input(read=True)
        self.sig_ref_input.emit(val)
        return val

    def read_sync_filter(self):
        assert self.hardware is not None
        val = self.hardware.sync_filter(read=True)
        self.sig_sync_filter.emit(val)
        return val

    def read_harmonic(self):
        assert self.hardware is not None
        val = self.hardware.harmonic(read=True)
        self.sig_harmonic.emit(val)
        return val

    def read_signal_input_type(self):
        assert self.hardware is not None
        val = self.hardware.signal_input_type(read=True)
        self.sig_signal_input_type.emit(val)
        return val

    def read_signal_input_mode(self):
        assert self.hardware is not None
        val = self.hardware.signal_input_mode(read=True)
        self.sig_signal_input_mode.emit(val)
        return val

    def read_voltage_input_coupling(self):
        assert self.hardware is not None
        val = self.hardware.voltage_input_coupling(read=True)
        self.sig_voltage_input_coupling.emit(val)
        return val

    def read_voltage_input_range(self):
        assert self.hardware is not None
        val = self.hardware.voltage_input_range(read=True)
        self.sig_voltage_input_range.emit(val)
        return val

    def read_multiple_outputs(self):
        assert self.hardware is not None
        val = self.hardware.get_multiple_outputs(*self.setpoint_outputs)
        self.sig_multiple_outputs.emit(val)
        return val

    def read_display(self):
        assert self.hardware is not None
        val = self.hardware.get_display()
        self.sig_display.emit(val)
        return val

    def read_aux_out(self):
        assert self.hardware is not None
        val = self.hardware.get_aux_out(self.setpoint_aux_channel)
        self.sig_aux_out.emit((self.setpoint_aux_channel, val))
        return val

    def read_unlocked(self):
        assert self.hardware is not None
        val = self.hardware.unlocked()
        self.sig_unlocked.emit(val)
        return val

    def read_input_overload(self):
        assert self.hardware is not None
        val = self.hardware.input_overload()
        self.sig_input_overload.emit(val)
        return val

    # ----- special getters that keep original names -----
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

    def get_aux_in(self):
        assert self.hardware is not None
        val = self.hardware.get_aux_in(self.setpoint_aux_channel)
        self.sig_aux_in.emit((self.setpoint_aux_channel, val))
        return val

    # -------------- write wrappers ---------------------
    def write_frequency(self):
        assert self.hardware is not None
        self.hardware.set_frequency(self.setpoint_frequency)
        self.sig_is_changing.emit(f"frequency set to {self.setpoint_frequency}")
        self.sig_frequency.emit(self.setpoint_frequency)

    def write_amplitude(self):
        assert self.hardware is not None
        self.hardware.set_amplitude(self.setpoint_amplitude)
        self.sig_is_changing.emit(f"amplitude set to {self.setpoint_amplitude}")
        self.sig_amplitude.emit(self.setpoint_amplitude)

    def write_time_constant(self):
        assert self.hardware is not None
        self.hardware.time_constant(self.setpoint_time_constant, write=True)
        self.sig_is_changing.emit(f"time_constant set to {self.setpoint_time_constant}")
        self.sig_time_constant.emit(self.setpoint_time_constant)

    def write_sensitivity(self):
        assert self.hardware is not None
        self.hardware.sensitivity(self.setpoint_sensitivity, write=True)
        self.sig_is_changing.emit(f"sensitivity set to {self.setpoint_sensitivity}")
        self.sig_sensitivity.emit(self.setpoint_sensitivity)

    def write_phase(self):
        assert self.hardware is not None
        self.hardware.phase(self.setpoint_phase, write=True)
        self.sig_is_changing.emit(f"phase set to {self.setpoint_phase}")
        self.sig_phase.emit(self.setpoint_phase)

    def write_ref_mode(self):
        assert self.hardware is not None
        self.hardware.ref_mode(self.setpoint_ref_mode, write=True)
        self.sig_is_changing.emit(f"ref_mode set to {self.setpoint_ref_mode}")
        self.sig_ref_mode.emit(self.setpoint_ref_mode)

    def write_ext_trigger(self):
        assert self.hardware is not None
        self.hardware.ext_trigger(self.setpoint_ext_trigger, write=True)
        self.sig_is_changing.emit(f"ext_trigger set to {self.setpoint_ext_trigger}")
        self.sig_ext_trigger.emit(self.setpoint_ext_trigger)

    def write_harmonic(self):
        assert self.hardware is not None
        self.hardware.harmonic(self.setpoint_harmonic, write=True)
        self.sig_is_changing.emit(f"harmonic set to {self.setpoint_harmonic}")
        self.sig_harmonic.emit(self.setpoint_harmonic)

    def write_signal_input_type(self):
        assert self.hardware is not None
        self.hardware.signal_input_type(self.setpoint_signal_input_type, write=True)
        self.sig_is_changing.emit(f"signal_input_type set to {self.setpoint_signal_input_type}")
        self.sig_signal_input_type.emit(self.setpoint_signal_input_type)

    def write_signal_input_mode(self):
        assert self.hardware is not None
        self.hardware.signal_input_mode(self.setpoint_signal_input_mode, write=True)
        self.sig_is_changing.emit(f"signal_input_mode set to {self.setpoint_signal_input_mode}")
        self.sig_signal_input_mode.emit(self.setpoint_signal_input_mode)

    def write_signal_input_config(self):
        assert self.hardware is not None
        
        if self.setpoint_input_config == "Current" or 0:
            self.setpoint_signal_input_type = "current"
            self.hardware.signal_input_type(self.setpoint_signal_input_type, write=True)
            self.hardware.current_input_range(self.setpoint_current_input_range, write=True)
        elif self.setpoint_input_config == "Voltage: A" or 1:
            self.setpoint_signal_input_type = "voltage"
            self.setpoint_signal_input_mode = "A"
            self.hardware.signal_input_mode(self.setpoint_signal_input_mode, write=True)
            self.hardware.voltage_input_range(self.setpoint_voltage_input_range, write=True)
        elif self.setpoint_input_config == "Voltage: A-B" or 2:
            self.setpoint_signal_input_type = "voltage"
            self.setpoint_signal_input_mode = "A-B"
            self.hardware.signal_input_mode(self.setpoint_signal_input_mode, write=True)
            self.hardware.voltage_input_range(self.setpoint_voltage_input_range, write=True)
        else:
            raise ValueError(f"Invalid signal input config: {self.setpoint_input_config}")

        self.sig_is_changing.emit(f"input_config set to {self.setpoint_input_config}")

    def write_voltage_input_coupling(self):
        assert self.hardware is not None
        self.hardware.voltage_input_coupling(self.setpoint_voltage_input_coupling, write=True)
        self.sig_is_changing.emit(f"voltage_input_coupling set to {self.setpoint_voltage_input_coupling}")
        self.sig_voltage_input_coupling.emit(self.setpoint_voltage_input_coupling)

    def write_voltage_input_range(self):
        assert self.hardware is not None
        self.hardware.voltage_input_range(self.setpoint_voltage_input_range, write=True)
        self.sig_is_changing.emit(f"voltage_input_range set to {self.setpoint_voltage_input_range}")
        self.sig_voltage_input_range.emit(self.setpoint_voltage_input_range)

    def write_aux_out(self):
        assert self.hardware is not None
        self.hardware.set_aux_out(self.setpoint_aux_channel, self.setpoint_aux_voltage)
        self.sig_is_changing.emit(
            f"aux_out[{self.setpoint_aux_channel}] set to {self.setpoint_aux_voltage}")
        self.sig_aux_out.emit((self.setpoint_aux_channel, self.setpoint_aux_voltage))

    # -------------- setup (boolean) wrappers ------------
    def setup_ref_input(self):
        assert self.hardware is not None
        self.hardware.ref_input(self.setpoint_ref_input, write=True)
        self.sig_is_changing.emit(f"ref_input set to {self.setpoint_ref_input}")
        self.sig_ref_input.emit(self.setpoint_ref_input)

    def setup_sync_filter(self):
        assert self.hardware is not None
        self.hardware.sync_filter(self.setpoint_sync_filter, write=True)
        self.sig_is_changing.emit(f"sync_filter set to {self.setpoint_sync_filter}")
        self.sig_sync_filter.emit(self.setpoint_sync_filter)

    def setup_auto_range(self):
        assert self.hardware is not None
        self.hardware.set_auto_range(self.setpoint_auto_range)
        self.sig_is_changing.emit(f"auto_range set to {self.setpoint_auto_range}")

    def setup_auto_scale(self):
        assert self.hardware is not None
        self.hardware.set_auto_scale(self.setpoint_auto_scale)
        self.sig_is_changing.emit(f"auto_scale set to {self.setpoint_auto_scale}")

    def setup_auto_phase(self):
        assert self.hardware is not None
        self.hardware.set_auto_phase(self.setpoint_auto_phase)
        self.sig_is_changing.emit(f"auto_phase set to {self.setpoint_auto_phase}")

    # -------------- bulk helper ------------------------
    def get_all(self):
        """Read a representative subset of parameters at once."""

        self.read_input_overload()
        self.get_X()
        self.get_Y()
        self.get_R()
        self.get_Theta()
        # self.read_display()
        # self.read_unlocked()

        self.monitor_count += 1
        if self.monitor_count >= 10:
            self.read_frequency()
            self.read_amplitude()
            self.read_time_constant()
            self.read_sensitivity()
            self.read_phase()
            self.read_ref_mode()
            self.read_ext_trigger()
            self.read_ref_input()
            self.read_sync_filter()
            self.read_harmonic()
            self.read_signal_input_type()
            self.read_signal_input_mode()
            self.read_voltage_input_coupling()
            self.read_voltage_input_range()
            self.monitor_count = 0
        time.sleep(0.05)

    # -------------- disconnect helper ------------------
    def disconnect(self):
        """Safely stop the thread and close the VISA link."""
        self.reject_signal = True
        self.job = ""

        if self.isRunning():
            self.wait()

        if self.hardware is not None:
            try:
                self.hardware.disconnect()
            except Exception as exc:
                print("[WARN] Error during hardware.disconnect():", exc)
            self.hardware = None

        if self.connected:
            self.connected = False
            self.sig_connected.emit("disconnected")

    # -------------- thread main ------------------------
    def run(self):
        if self.reject_signal or not self.connected or self.hardware is None:
            return

        # generic dispatcher: call method named in self.job (no args)
        if self.job:
            fn = getattr(self, self.job, None)
            if callable(fn):
                try:
                    fn()
                except Exception as exc:
                    print(f"[WARN] SR860_Logic job '{self.job}' error:", exc)
            else:
                print(f"[WARN] SR860_Logic has no job '{self.job}'")

            # reset marker
            self.job = ""

    # -------------- stop helper ------------------------
    def stop(self):
        self.reject_signal = True
        self.quit()
        self.wait()
        self.reject_signal = False
        print("stop")
