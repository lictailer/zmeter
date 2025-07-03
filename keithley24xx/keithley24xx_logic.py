from PyQt6 import QtCore
from .keithley24xx_hardware import Keithly24xxHardware
import numpy as np
import time
import re


class Keithley24xxLogic(QtCore.QThread):
    sig_new_read = QtCore.pyqtSignal(object)
    sig_on_off = QtCore.pyqtSignal(object)
    sig_last_set = QtCore.pyqtSignal(object)

    def __init__(self):
        QtCore.QThread.__init__(self)
        self.k24xxHardware = Keithly24xxHardware()
        self.addr = ""
        self.next_pos = 0
        self.reset_flags()
        self.ramp_rate = 1 # V/s
        # Number of update points sent to the instrument per second
        self.points_per_sec: float = 100.0  # default 100 points / s

        # Derived quantities
        self.step_time: float = 1 / self.points_per_sec  # wait time between updates
        self.volt_ramp_step = self.ramp_rate / self.points_per_sec
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
        self.k24xxHardware.initialize(addr)
        self.sour_func_to_volt()
        self.sens_func_to_curr()
    # ---------------------------- sour ----------------------------

    def sour_func_to_volt(self):
        self.k24xxHardware.set_sour_func_to_volt()
        self.sour = 'volt'

    def sour_func_to_curr(self):
        self.k24xxHardware.set_sour_func_to_curr()
        self.sour = 'curr'
    # ---------------------------- sens ----------------------------

    def sens_func_to_volt(self, compliance=200):
        self.k24xxHardware.set_sens_func_to_volt(compliance)
        self.sens = 'volt'

    def sens_func_to_curr(self, compliance=1e-5):
        self.k24xxHardware.set_sens_func_to_curr(compliance)
        self.sens = 'curr'
    # ---------------------------- set ----------------------------

    def set_direct_source_voltage(self, val):
        if self.sour != 'volt':
            return
        self.k24xxHardware.set_sour_volt_to(val)
        self.sig_last_set.emit(val)

    def set_ramp_source_voltage(self, val):
        if self.sour != 'volt':
            return
        self.ramp_voltage_to(val)


    def set_source_current(self, val):
        if self.sour != 'curr':
            return
        self.k24xxHardware.set_sour_curr_to(val)
        self.sig_last_set.emit(val)
    # ---------------------------- read ----------------------------

    def read(self):
        raw = self.k24xxHardware.read()
        try:
            val = float(raw)
        except ValueError:
            # If the response is not purely numeric, treat it as invalid and give caller a chance
            # to handle the exception.
            print(f"Warning: non-numeric instrument response: {raw!r}")
            raise
        self.sig_new_read.emit(val)
        return val
    
    def get_voltage(self):
        self.sens_func_to_volt()
        return self.read()

    def get_current(self):
        self.sens_func_to_curr()
        return self.read()

    # --------------------------------------------------------------

    def close(self):
        self.k24xxHardware.close()

    def ramp_voltage_to(self, val):
        """Ramp the source voltage to *val* at the user-defined ``self.ramp_rate``.

        The function uses the user-selectable update cadence ``self.points_per_sec``
        (default 100 points/s).  The corresponding time step is
        ``self.step_time = 1 / self.points_per_sec``.  The voltage increment
        for each step is chosen to honour the selected ramp rate, guaranteeing
        an average slew rate close to ``self.ramp_rate`` volts per second
        (barring VISA/USB overhead).
        """
        change_back_to_curr = (self.sens == 'curr')

        # Switch the sensing function to voltage so we can read the starting value
        self.sens_func_to_volt()

        # Attempt to read the present voltage level; default to 0 V on failure
        try:
            start_v = self.read()
        except ValueError:
            print("Initial voltage read failed – defaulting to 0 V for ramp start.")
            start_v = 0.0

        # Nothing to do if we are already (very) close to the target voltage
        if np.isclose(start_v, val, atol=1e-9):
            if change_back_to_curr:
                self.sens_func_to_curr()
            return
        
        # Cadence controlled by ``self.points_per_sec``
        step_time = self.step_time  # seconds between updates

        direction = 1 if val >= start_v else -1
        step_size = direction * abs(self.ramp_rate) * step_time  # V per step

        # Ensure we make progress (ramp_rate could be very small)
        if step_size == 0:
            step_size = direction * 1e-6  # 1 µV minimum step

        current_v = start_v
        step_counter = 0  # Counter to track steps for current reading
        self.sens_func_to_curr()
        self.read()

        while (direction == 1 and current_v < val) or (direction == -1 and current_v > val):
            if self.force_stop:
                self.reset_flags()
                break

            # Move to the next intermediate voltage, but do not overshoot
            next_v = current_v + step_size
            if (direction == 1 and next_v > val) or (direction == -1 and next_v < val):
                next_v = val

            self.set_direct_source_voltage(next_v)

            # Wait the fixed time interval to respect the desired ramp rate
            time.sleep(step_time)
            current_v = next_v
            
            # Read current every 10 points
            step_counter += 1
            if step_counter % 10 == 0:
                try:
                    self.read() 
                except ValueError:
                    pass

        self.read()
        # Restore sensing mode if it was changed at the beginning
        if not change_back_to_curr:
            self.sens_func_to_volt()

    def update_next_func(self, fn):
        self.next_func = fn

    def update_next_pos(self, val):
        self.next_pos = val
        
    def reset(self):
        self.k24xxHardware.reset()

    def update_points_per_sec(self, pps: float):
        """Update the number of points sent to the instrument per second.

        Parameters
        ----------
        pps : float
            Desired update frequency in points per second. Must be > 0.
        """
        if pps <= 0:
            raise ValueError("Points per second must be positive")

        self.points_per_sec = float(pps)
        self.step_time = 1.0 / self.points_per_sec
        # Keep volt_ramp_step consistent for any external code still referencing it
        self.volt_ramp_step = self.ramp_rate / self.points_per_sec

    def run(self):
        if self.do_volt:
            # Source voltage then automatically read current
            self.ramp_voltage_to(self.next_pos)
            try:
                self.get_current()  # emits signal for UI
            except ValueError:
                pass  # ignore non-numeric response
        elif self.do_curr:
            # Source current then automatically read voltage
            self.set_source_current(self.next_pos)
            try:
                self.get_voltage()  # emits signal for UI
            except ValueError:
                pass
            finally:
                # Restore sensing to current so subsequent operations behave as expected
                self.sens_func_to_curr()
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
    k.set_direct_source_voltage(0)
    print("Success A")
    k.ramp_voltage_to(2)
