from PyQt6 import QtCore  # type: ignore
import time

from .hp34401a_hardware import HP34401A_Hardware


class HP34401A_Logic(QtCore.QThread):
    """
    Naming rules (project-wide):
    1. **get_xxx**   – read access, will be displayed in the scan code readable dropdown
    2. **set_xxx**   – write access for *numeric* parameters, will be displayed in the scan code settable dropdown

    """


    # ----------- value update signals ---------------
    #signals are used to update the UI with the current value of the parameter
    sig_NPLC = QtCore.pyqtSignal(object)
    sig_dc_voltage = QtCore.pyqtSignal(object)

    # ----------- generic state signals --------------
    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)


    # -----------------------------------------------
    def __init__(self) -> None:
        super().__init__()

        # queued instruction name processed in run()
        self.job: str = ""  # name of the next action

        # -------- set-points (set_* / setup_*) --------
        self.setpoint_NPLC = 1
        #self.setpoint_dc_voltage: float = 0.0

        # runtime state
        self.connected: bool = False
        self.reject_signal: bool = False #reject signal is to prevent multiple jobs from running at the same time

        self.hardware: HP34401A_Hardware | None = None


    # -------------- connection helpers --------------
    def connect_visa(self, address: str):
        """Instantiate *HP34401A_Hardware* and open VISA connection."""
        self.hardware = HP34401A_Hardware(address)
        self.idn = self.get_idn()
        self.connected = True
        self.sig_connected.emit(f"connected to {address} \n{self.idn}")


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

    def get_dc_voltage(self):
        assert self.hardware is not None
        val = self.hardware.measure_dc_voltage()
        self.sig_dc_voltage.emit(val)
        return val
    # -------------- read wrappers -----------------
    def read_NPLC(self):
        assert self.hardware is not None
        val = self.hardware.NPLC(read=True)
        self.sig_NPLC.emit(val)
        return val

    # -------------- setter wrappers -----------------

    def write_NPLC(self):
        assert self.hardware is not None
        self.hardware.NPLC(self.setpoint_NPLC, write=True)
        self.sig_is_changing.emit(f"NPLC set to {self.setpoint_NPLC}")
        self.sig_NPLC.emit(self.setpoint_NPLC)

    # -------------- bulk helper ---------------------
    def get_all(self):
        """Convenience method: query a representative subset of parameters."""
        #self.get_operating_mode()
        self.get_dc_voltage()
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
                    print(f"[WARN] HP34401A_Logic job '{self.job}' error:", exc)
            else:
                print(f"[WARN] HP34401A_Logic has no job '{self.job}'")

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
    ADDRESS = 'GPIB0::21::INSTR'
    logic = HP34401A_Logic()
    logic.connect_visa(ADDRESS)
    print('Connected')
    # Query identification string
    print(logic.get_idn())

    # Example: change operating mode then voltage
    #logic.setpoint_operating_mode = "remote"
    #logic.set_operating_mode()

    for i in range(100):
        print(logic.get_dc_voltage())
    # Clean up
    logic.disconnect()