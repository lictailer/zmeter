from PyQt6 import QtCore
import time
from montana2_hardware import Montana2Hardware


class Montana2Logic(QtCore.QThread):

    sig_platform_temperature = QtCore.pyqtSignal(object)
    sig_platform_target_temperature = QtCore.pyqtSignal(object)
    sig_platform_temperature_stable_bool = QtCore.pyqtSignal(object)
    sig_status = QtCore.pyqtSignal(object)

    sig_is_connected = QtCore.pyqtSignal(object)
    sig_is_changing = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()

        self.job: str = ""

        self.setpoint_platform_target_temperature: float = 300

        self.is_connected: bool = False
        self.reject_signal: bool = False

        self.hardware = Montana2Hardware()

        self.set_temperature_buffer_time_s: int = 60
        self.ipaddress: str = ""
        self.stable_wait_timeout_s: int = 180 * 60


    def connect(self):
        """Instantiate *Montana2Hardware* and open connection."""

        self.is_connected = self.hardware.connect_hardware(self.ipaddress)

        self.sig_is_connected.emit("Connecting Status: " + str(self.is_connected))
        if self.is_connected:
            self.sig_status.emit(f"Connection successful to {self.ipaddress}.")
        else:
            self.sig_status.emit(f"Connection failed to {self.ipaddress}.")

    def disconnect(self):
        if self.is_connected:
            self.hardware.disconnect()
            self.is_connected = False
            self.sig_is_connected.emit("Connecting Status: " + str(self.is_connected))
            self.sig_status.emit("Disconnected.")

        elif not self.is_connected:
            self.sig_is_connected.emit("Connecting Status: " + str(self.is_connected))
            self.sig_status.emit("Already disconnected.")

    # -------------- getter wrappers -----------------
    def get_platform_temperature(self):
        assert self.hardware is not None
        assert self.is_connected

        self.platform_temp = self.hardware.get_platform_temperature()
        self.sig_platform_temperature.emit(self.platform_temp)

        return self.platform_temp
    
    def get_stage1_temperature(self):
        assert self.hardware is not None
        assert self.is_connected

        self.stage1_temp = self.hardware.get_stage1_temperature()
        self.sig_stage1_temperature.emit(self.stage1_temp)

        return self.stage1_temp
    
    def get_platform_target_temperature(self):
        assert self.hardware is not None
        assert self.is_connected

        self.platform_target_temp = self.hardware.get_platform_target_temperature()
        self.sig_platform_target_temperature.emit(self.platform_target_temp)

        return self.platform_target_temp
    
    def get_platform_temperature_stable(self):
        assert self.hardware is not None
        assert self.is_connected

        self.platform_temp_stability = self.hardware.get_platform_temperature_stable()
        self.sig_platform_temperature_stable_bool.emit(self.platform_temp_stability)

        return self.platform_temp_stability

    # -------------- setter wrappers -----------------
    def set_platform_target_temperature(self, target):
        assert self.hardware is not None
        assert self.is_connected

        self.hardware.set_platform_target_temperature(target)
        self.sig_platform_target_temperature.emit(target)

    def set_platform_target_temperature_to_stable(self, target):
        assert self.hardware is not None
        assert self.is_connected

        self.hardware.set_platform_target_temperature(target)
        self.sig_platform_target_temperature.emit(target)

        start_time = time.time()
        stable_reached = False

        while True:
            # check stability
            stable = self.get_platform_temperature_stable()
            if stable:
                stable_reached = True
                break

            # emit intermediate updates
            self.sig_platform_temperature_stable_bool.emit(False)
            self.sig_platform_temperature.emit(self.get_platform_temperature())

            # user-requested interrupt
            if self.stable_wait_stop:
                self.sig_status.emit("Wait till stable interrupted by user.")
                self.stable_wait_stop = False
                break

            # timeout check
            elapsed = time.time() - start_time
            if elapsed >= self.stable_wait_timeout_s:
                minutes = int(self.stable_wait_timeout_s / 60)
                self.sig_status.emit(f"Timeout: waited {minutes} minutes for temperature to become stable. Stopping wait.")
                break

            QtCore.QThread.msleep(1000)

        if stable_reached:
            self.sig_status.emit(f"Target temperature {target} reached and stable. {minutes} minutes waited.")
            self.sig_status.emit(f"Waiting additional {self.set_temperature_buffer_time_s} seconds for buffer time.")
            QtCore.QThread.msleep(self.set_temperature_buffer_time_s * 1000)
            self.sig_status.emit("Buffer time completed.")
        else:
            # If we exited without reaching stability (timeout or user stop), notify user.
            if not self.stable_wait_stop:
                # stable_reached is False and stable_wait_stop is False => timeout
                pass

    def run(self):
        if self.reject_signal:
            return

        if self.job == "connect":
            self.connect()

        elif self.job == "disconnect":
            self.disconnect()

        elif self.job == "get_platform_temperature":
            self.get_platform_temperature()

        elif self.job == "get_platform_target_temperature":
            self.get_platform_target_temperature()

        elif self.job == "get_platform_temperature_stable":
            self.get_platform_temperature_stable()

        elif self.job == "set_platform_target_temperature":
            self.set_platform_target_temperature(self.setpoint_platform_target_temperature)

        elif self.job == "set_platform_target_temperature_to_stable":
            self.set_platform_target_temperature_to_stable(self.setpoint_platform_target_temperature)

    

if __name__ == "__main__":
    logic = Montana2Logic()
    logic.connect("1.1.1.1")
    logic.connect("136.167.55.165")
    logic.get_platform_temperature()
    logic.get_platform_temperature_stable()
    logic.set_platform_target_temperature(4.0)
    logic.get_platform_target_temperature()