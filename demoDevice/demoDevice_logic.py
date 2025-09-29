from __future__ import annotations

from PyQt6 import QtCore  # type: ignore
import time
from demoDevice_hardware import DemoDeviceHardware


class DemoDeviceLogic(QtCore.QThread):
    """Qt thread-wrapper exposing *DemoDeviceHardware* in a signal-friendly API.

    This template mimics the conventions used in *sr860_logic.py* so that UI
    developers can reuse components with minimal changes.

    Naming rules (project-wide):
    1. **get_xxx**   – read access, will be displayed in the scan code readable dropdown
    2. **set_xxx**   – write access for *numeric* parameters, will be displayed in the scan code settable dropdown

    """


    # ----------- value update signals ---------------
    #signals are used to update the UI with the current value of the parameter
    sig_operating_mode = QtCore.pyqtSignal(object)
    sig_voltage_level = QtCore.pyqtSignal(object)

    # ----------- generic state signals --------------
    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)


    # -----------------------------------------------
    def __init__(self) -> None:
        super().__init__()

        # queued instruction name processed in run()
        self.job: str = ""  # name of the next action

        # -------- set-points (set_* / setup_*) --------
        self.setpoint_operating_mode: str | int = "local"
        self.setpoint_voltage_level: float = 0.0

        # runtime state
        self.connected: bool = False
        self.reject_signal: bool = False #reject signal is to prevent multiple jobs from running at the same time

        self.hardware: DemoDeviceHardware | None = None


    # -------------- connection helpers --------------
    def connect_visa(self, address: str):
        """Instantiate *DemoDeviceHardware* and open VISA connection."""
        self.hardware = DemoDeviceHardware(address)
        self.idn = self.get_idn()
        self.connected = True
        self.sig_connected.emit(f"connected to {address}, {self.idn}")


    # -------------- disconnect helper --------------
    def disconnect(self):
        """Safely stop the thread and close the VISA link."""
        self.reject_signal = True
        self.job = ""

        if self.isRunning():
            self.wait()

        if self.hardware is not None:
            try:
                self.hardware.disconnect()
            except Exception as exc:  # pragma: no cover – defensive
                print("[WARN] Error during hardware.disconnect():", exc)
            self.hardware = None

        if self.connected:
            self.connected = False
            self.sig_connected.emit("disconnected")

        # allow new jobs after future reconnect
        self.reject_signal = False


    # -------------- getter wrappers -----------------
    def get_idn(self):
        assert self.hardware is not None
        val = self.hardware.idn()
        # No need to emit a signal here as the idn is already emitted in the connect_visa function
        return val

    def get_operating_mode(self):
        assert self.hardware is not None
        val = self.hardware.operating_mode(read=True)
        self.sig_operating_mode.emit(val)
        return val

    def get_voltage_level(self):
        assert self.hardware is not None
        val = self.hardware.voltage_level(read=True)
        self.sig_voltage_level.emit(val)
        return val

    # -------------- setter wrappers -----------------
    def set_operating_mode(self):
        assert self.hardware is not None
        self.hardware.operating_mode(self.setpoint_operating_mode, write=True)
        self.sig_is_changing.emit(
            f"operating_mode set to {self.setpoint_operating_mode}"
        )
        self.sig_operating_mode.emit(self.setpoint_operating_mode)

    def set_voltage_level(self):
        assert self.hardware is not None
        self.hardware.voltage_level(self.setpoint_voltage_level, write=True)
        self.sig_is_changing.emit(
            f"voltage_level set to {self.setpoint_voltage_level} V"
        )
        # Enable this will automatically update the voltage level, but this is only the setpoint voltage level
        self.sig_voltage_level.emit(self.setpoint_voltage_level) 

    # -------------- bulk helper ---------------------
    def get_all(self):
        """Convenience method: query a representative subset of parameters."""
        self.get_operating_mode()
        self.get_voltage_level()
        time.sleep(0.05)

    # -------------- thread main ---------------------
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
                    print(f"[WARN] DemoDeviceLogic job '{self.job}' error:", exc)
            else:
                print(f"[WARN] DemoDeviceLogic has no job '{self.job}'")

            # reset marker so next queued job can run
            self.job = ""

    # -------------- stop helper ---------------------
    def stop(self):
        self.reject_signal = True
        self.quit()
        self.wait()
        self.reject_signal = False


# -----------------------------------------------------------------------------
# Example usage – runs only when file is executed directly
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    # ADDRESS = "GPIB0::1::INSTR"  # TODO: change to your VISA resource
    ADDRESS = "DUMMY::INSTR"
    logic = DemoDeviceLogic()
    logic.connect_visa(ADDRESS)

    # Query identification string
    logic.get_idn()

    # Example: change operating mode then voltage
    logic.setpoint_operating_mode = "remote"
    logic.set_operating_mode()

    logic.setpoint_voltage_level = 1.234
    logic.set_voltage_level()

    # Clean up
    logic.disconnect()
