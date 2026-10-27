from PyQt6 import QtCore
from collections import deque
import math
import time
from .montana2_hardware import Montana2Hardware


# Stability rule ported from the Four9 temperature-control server
# (lictailer/cryo_control_Four9_QMLab). The cryostat's own stable flag is
# stricter than our measurements need, so the stable wait uses this instead.
STABLE_WINDOW_POINTS = 60  # latest one-second platform readings
STABLE_BELOW_K = 3.0  # targets below this count as stable right away


def stability_thresholds(target, avg_multiplier, std_multiplier):
    """Return (mean, std) thresholds in K: sqrt(target + 100) / 50 * multiplier."""
    base = math.sqrt(target + 100.0) / 50.0
    return base * avg_multiplier, base * std_multiplier


def window_mean_std(temperatures):
    mean = sum(temperatures) / len(temperatures)
    variance = sum((t - mean) ** 2 for t in temperatures) / len(temperatures)
    return mean, math.sqrt(variance)


def is_temperature_stable(temperatures, target, avg_multiplier, std_multiplier):
    """Four9 rule: the last 60 readings average close to target with small spread."""
    if target < STABLE_BELOW_K:
        return True
    if len(temperatures) < STABLE_WINDOW_POINTS:
        return False
    window = list(temperatures)[-STABLE_WINDOW_POINTS:]
    mean, std = window_mean_std(window)
    avg_threshold, std_threshold = stability_thresholds(
        target, avg_multiplier, std_multiplier
    )
    return abs(mean - target) < avg_threshold and std < std_threshold


def _is_valid_temperature(value):
    # The hardware wrapper returns False or None on a failed read.
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


class Montana2Logic(QtCore.QThread):

    # Read-only getters recorded by setup capture at scan start and end.
    # Labs can add or remove names in lab_context/snapshot_channels.json.
    SNAPSHOT_GETTERS = (
        "platform_temperature",
        "stage1_temperature",
        "platform_target_temperature",
        "platform_temperature_stable",
    )

    sig_platform_temperature = QtCore.pyqtSignal(object)
    sig_stage1_temperature = QtCore.pyqtSignal(object)
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
        self.stable_wait_stop: bool = False

        self.hardware = Montana2Hardware()

        self.set_temperature_buffer_time_s: int = 60
        self.ipaddress: str = ""
        self.stable_wait_timeout_s: int = 60 * 60
        self.stable_avg_multiplier: float = 0.5
        self.stable_std_multiplier: float = 1.0


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

    def update_stability_multipliers(self, avg_multiplier, std_multiplier):
        """Change the stable-wait multipliers; a running wait uses them on its next reading."""
        avg_multiplier = float(avg_multiplier)
        std_multiplier = float(std_multiplier)
        for value in (avg_multiplier, std_multiplier):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Stability multipliers must be positive numbers.")

        self.stable_avg_multiplier = avg_multiplier
        self.stable_std_multiplier = std_multiplier
        self.sig_status.emit(
            f"Stability multipliers updated: mean x{avg_multiplier:g}, std x{std_multiplier:g} "
            "(thresholds = sqrt(target + 100) / 50 x multiplier)."
        )

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
        temperatures = deque(maxlen=STABLE_WINDOW_POINTS)
        readings = 0
        if target < STABLE_BELOW_K:
            self.sig_status.emit(f"Target below {STABLE_BELOW_K:g} K counts as stable right away.")

        QtCore.QThread.msleep(1000)

        while True:
            # check stability over the latest one-second platform readings
            temperature = self.get_platform_temperature()
            if _is_valid_temperature(temperature):
                temperatures.append(temperature)
                readings += 1
            stable = is_temperature_stable(
                temperatures, target, self.stable_avg_multiplier, self.stable_std_multiplier
            )
            self.sig_platform_temperature_stable_bool.emit(stable)
            if stable:
                stable_reached = True
                self.sig_status.emit(f"Temperature is now stable at {target}K.")
                break

            # report the window once a minute so the multipliers can be tuned
            if _is_valid_temperature(temperature) and readings % STABLE_WINDOW_POINTS == 0:
                self._report_stability_window(temperatures, target)

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
            minutes = int((time.time() - start_time) / 60)
            self.sig_status.emit(f"Target temperature {target} reached and stable. {minutes} minutes waited.")
            self.sig_status.emit(f"Waiting additional {self.set_temperature_buffer_time_s} seconds for buffer time.")
            QtCore.QThread.msleep(self.set_temperature_buffer_time_s * 1000)
            self.sig_status.emit("Buffer time completed.")
        else:
            # If we exited without reaching stability (timeout or user stop), notify user.
            if not self.stable_wait_stop:
                # stable_reached is False and stable_wait_stop is False => timeout
                pass

    def _report_stability_window(self, temperatures, target):
        mean, std = window_mean_std(temperatures)
        avg_threshold, std_threshold = stability_thresholds(
            target, self.stable_avg_multiplier, self.stable_std_multiplier
        )
        self.sig_status.emit(
            f"Not stable yet: last {len(temperatures)} readings |mean - target| = {abs(mean - target):.3f} K "
            f"(needs < {avg_threshold:.3f}), std = {std:.3f} K (needs < {std_threshold:.3f})."
        )

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
    logic.ipaddress = "136.167.55.165"
    logic.connect()
    logic.get_platform_temperature()
    logic.get_platform_temperature_stable()
    logic.set_platform_target_temperature_to_stable(4.0)