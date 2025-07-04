from PyQt6 import QtCore
import time

from sr860_hardware import SR860_Hardware


class SR860_Logic(QtCore.QThread):
    """Qt thread-wrapper that exposes SR860_Hardware methods via signals.

    This layer mirrors only the functionality implemented in sr860_hardware.py
    and should not introduce any additional instrument commands.
    """

    # ----------- value update signals -----------
    sig_frequency = QtCore.pyqtSignal(object)
    sig_amplitude = QtCore.pyqtSignal(object)
    sig_time_constant = QtCore.pyqtSignal(object)
    sig_sensitivity = QtCore.pyqtSignal(object)
    sig_phase = QtCore.pyqtSignal(object)
    sig_X = QtCore.pyqtSignal(object)
    sig_Y = QtCore.pyqtSignal(object)
    sig_R = QtCore.pyqtSignal(object)
    sig_Theta = QtCore.pyqtSignal(object)
    sig_display = QtCore.pyqtSignal(object)        # full four-channel display readback
    sig_aux_out = QtCore.pyqtSignal(object)        # (chan, value) tuple
    sig_aux_in = QtCore.pyqtSignal(object)         # (chan, value) tuple
    sig_unlocked = QtCore.pyqtSignal(object)
    sig_input_overload = QtCore.pyqtSignal(object)
    sig_multiple_outputs = QtCore.pyqtSignal(object)

    # ----------- generic state signals ----------
    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)

    # --------------------------------------------
    def __init__(self):
        super().__init__()

        # queued instruction executed in run()
        self.job: str = ""  # name of the next action

        # user-defined set-points
        self.setpoint_frequency = 0.0
        self.setpoint_amplitude = 0.0
        self.setpoint_time_constant = 0
        self.setpoint_sensitivity = 0
        self.setpoint_phase = 0.0
        self.setpoint_aux_channel = 1
        self.setpoint_aux_voltage = 0.0
        self.setpoint_auto_range = False
        self.setpoint_auto_scale = False
        self.setpoint_auto_phase = False

        # runtime state
        self.connected = False
        self.reject_signal = False

        self.hardware: SR860_Hardware | None = None

    # -------------- connection ------------------
    def connect_visa(self, address: str):
        """Instantiate SR860_Hardware and open VISA connection."""
        self.hardware = SR860_Hardware(address)
        self.connected = True
        self.sig_connected.emit(f"connected to {address}")

    #--------------read-------------------------
    def read_frequency(self):
        assert self.hardware is not None
        val = self.hardware.get_frequency()
        self.sig_frequency.emit(val)
        return val

    def read_amplitude(self):
        assert self.hardware is not None
        val = self.hardware.get_amplitude()
        self.sig_amplitude.emit(val)
        return val

    def read_time_constant(self):
        assert self.hardware is not None
        val = self.hardware.get_time_constant()
        self.sig_time_constant.emit(val)
        return val

    def read_sensitivity(self):
        assert self.hardware is not None
        val = self.hardware.get_sensitivity()
        self.sig_sensitivity.emit(val)
        return val

    def read_phase(self):
        #read the reference phase value, not theta
        assert self.hardware is not None
        val = self.hardware.get_phase()
        self.sig_phase.emit(val)
        return val

    def read_multiple_outputs(self, *args: str):
        assert self.hardware is not None
        val = self.hardware.get_multiple_outputs(*args)
        self.sig_multiple_outputs.emit(val)
        return val

    def read_display(self):
        assert self.hardware is not None
        val = self.hardware.get_display()
        self.sig_display.emit(val)
        return val
    
    def read_aux_out(self, chan: int):
        assert self.hardware is not None
        val = self.hardware.get_aux_out(chan)
        self.sig_aux_out.emit((chan, val))
        return val

    # -------------- getters ---------------------
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

    def get_aux_in(self, chan: int):
        assert self.hardware is not None
        val = self.hardware.get_aux_in(chan)
        self.sig_aux_in.emit((chan, val))
        return val

    def unlocked(self):
        assert self.hardware is not None
        val = self.hardware.unlocked()
        self.sig_unlocked.emit(val)
        return val

    def input_overload(self):
        assert self.hardware is not None
        val = self.hardware.input_overload()
        self.sig_input_overload.emit(val)
        return val

    # -------------- setters ---------------------
    def setup_frequency(self):
        assert self.hardware is not None
        self.hardware.set_frequency(self.setpoint_frequency)
        self.sig_is_changing.emit(f"frequency set to {self.setpoint_frequency}")
        self.sig_frequency.emit(self.setpoint_frequency)

    def setup_amplitude(self):
        assert self.hardware is not None
        self.hardware.set_amplitude(self.setpoint_amplitude)
        self.sig_is_changing.emit(f"amplitude set to {self.setpoint_amplitude}")
        self.sig_amplitude.emit(self.setpoint_amplitude)

    def setup_time_constant(self):
        assert self.hardware is not None
        self.hardware.set_time_constant(self.setpoint_time_constant)
        self.sig_is_changing.emit(f"time_constant set to {self.setpoint_time_constant}")
        self.sig_time_constant.emit(self.setpoint_time_constant)

    def setup_sensitivity(self):
        assert self.hardware is not None
        self.hardware.set_sensitivity(self.setpoint_sensitivity)
        self.sig_is_changing.emit(f"sensitivity set to {self.setpoint_sensitivity}")
        self.sig_sensitivity.emit(self.setpoint_sensitivity)

    def setup_phase(self):
        assert self.hardware is not None
        self.hardware.set_phase(self.setpoint_phase)
        self.sig_is_changing.emit(f"phase set to {self.setpoint_phase}")
        self.sig_phase.emit(self.setpoint_phase)

    def setup_aux_out(self):
        assert self.hardware is not None
        self.hardware.set_aux_out(self.setpoint_aux_channel, self.setpoint_aux_voltage)
        self.sig_is_changing.emit(
            f"aux_out[{self.setpoint_aux_channel}] set to {self.setpoint_aux_voltage}"
        )
        self.sig_aux_out.emit((self.setpoint_aux_channel, self.setpoint_aux_voltage))

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

    # -------------- disconnect helper -----------------
    def disconnect(self):
        """Safely stop the thread, clear the queue, and close the VISA link."""
        # Mark thread as stopping and ensure no pending job
        self.reject_signal = True
        self.job = ""

        # Wait until any running task finished
        if self.isRunning():
            self.wait()

        # Close hardware connection
        if self.hardware is not None:
            try:
                self.hardware.disconnect()
            except Exception as exc:
                print("[WARN] Error during hardware.disconnect():", exc)
            self.hardware = None

        if self.connected:
            self.connected = False
            self.sig_connected.emit("disconnected")

    # -------------- thread main ------------------
    def run(self):
        if self.reject_signal or not self.connected or self.hardware is None:
            return

        # ---------- read ----------
        if self.job == "read_frequency":
            self.read_frequency()
        elif self.job == "read_amplitude":
            self.read_amplitude()
        elif self.job == "read_time_constant":
            self.read_time_constant()
        elif self.job == "read_sensitivity":
            self.read_sensitivity()
        elif self.job == "read_phase":
            self.read_phase()
        elif self.job == "read_aux_out":
            self.read_aux_out(self.setpoint_aux_channel)
        elif self.job == "read_display":
            self.read_display()
        elif self.job == "unlocked":
            self.unlocked()
        elif self.job == "input_overload":
            self.input_overload()
        #----------- get -----------
        elif self.job == "get_X":
            self.get_X()
        elif self.job == "get_Y":
            self.get_Y()
        elif self.job == "get_R":
            self.get_R()
        elif self.job == "get_Theta":
            self.get_Theta()
        elif self.job == "get_aux_in":
            self.get_aux_in(self.setpoint_aux_channel)
        # ---------- setters ----------
        elif self.job == "setup_frequency":
            self.setup_frequency()
        elif self.job == "setup_amplitude":
            self.setup_amplitude()
        elif self.job == "setup_time_constant":
            self.setup_time_constant()
        elif self.job == "setup_sensitivity":
            self.setup_sensitivity()
        elif self.job == "setup_phase":
            self.setup_phase()
        elif self.job == "setup_aux_out":
            self.setup_aux_out()
        elif self.job == "setup_auto_range":
            self.setup_auto_range()
        elif self.job == "setup_auto_scale":
            self.setup_auto_scale()
        elif self.job == "setup_auto_phase":
            self.setup_auto_phase()

        # ---------- bulk poll ----------
        elif self.job == "get_all":
            # minimal delay loop to read out all implemented parameters once
            self.read_frequency()
            self.read_amplitude()
            self.read_time_constant()
            self.read_sensitivity()
            self.read_phase()
            self.get_X()
            self.get_Y()
            self.get_R()
            self.get_Theta()
            self.read_display()
            self.unlocked()
            self.input_overload()
            time.sleep(0.05)

        # reset job marker when done
        self.job = ""

    # -------------- stop helper ------------------
    def stop(self):
        self.reject_signal = True
        self.wait()
