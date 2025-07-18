from PyQt6 import QtCore  # type: ignore
import time
import logging
from .hp34401a_hardware import HP34401A_Hardware, HP34401AError


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
        self.setpoint_NPLC = 10
        self.setpoint_display_on: bool = True

        # runtime state
        self._connected: bool = False
        self.reject_signal: bool = False #reject signal is to prevent multiple jobs from running at the same time

        self._hardware: HP34401A_Hardware | None = None

        # Setup logging
        self._logger = logging.getLogger(__name__)

    # -------------- connection helpers --------------
    def connect_visa(self, address: str):
        """Instantiate *HP34401A_Hardware* and open VISA connection."""
        if self._connected:
            self._logger.warning("Already connected. Disconnect first.")
            return False
        try:
            self._logger.info(f"Connecting to HP34401A at {address}")
            self._hardware = HP34401A_Hardware(address)

            self.idn = self.get_idn()
            self._logger.info(f"Connected to: {self.idn}")
            self._connected = True
            self.sig_connected.emit(f"connected to {address} \n{self.idn}")
        except Exception as e:
            error_msg = f"Failed to connect to {address}: {e}"
            self._logger.error(error_msg)
            self._cleanup_connection()
            return False

    # -------------- disconnect helper --------------
    def disconnect(self):
        """Safely stop the thread and close the VISA link."""
        self._logger.info("Disconnecting from HP34401A")
        self.reject_signal = True
        self.job = ""
        
        # Wait for current thread to finish
        if self.isRunning():
            self._logger.debug("Waiting for thread to finish...")
            self.wait()

        # Cleanup hardware connection
        self._cleanup_connection()
        
        #update state
        if self._connected:
            self._connected = False
            self.sig_connected.emit("Disconnected")

        # allow new jobs after future reconnect
        self.reject_signal = False

    def _cleanup_connection(self) -> None:
        """Clean up the hardware connection."""
        if self._hardware is not None:
            try:
                self._hardware.disconnect()
            except Exception as e:
                self._logger.warning(f"Error during hardware disconnect: {e}")
            finally:
                self._hardware = None
    # -------------- getter wrappers -----------------
    def get_idn(self) -> str:
        """ Returns: Device identification string """
        if not self._hardware:
            raise HP34401AError("Device not connected")
        
        try:
            identity = self._hardware.get_identity()
            return identity
        except Exception as e:
            self._logger.error(f"Error getting device identity: {e}")
            raise

    def get_dc_voltage(self) -> float:
        """ Returns DC voltage in volts """
        if not self._hardware:
            raise HP34401AError("Device not connected")
        try:
            voltage = self._hardware.measure_dc_voltage()
            self.sig_dc_voltage.emit(voltage)
            return voltage
        except Exception as e:
            self._logger.error(f"Error measuring DC voltage: {e}")
            raise

    def read_NPLC(self) -> float:
        """ Returns current NPLC value """
        if not self._hardware:
            raise HP34401AError("Device not connected")
        try:
            nplc = self._hardware.get_nplc()
            self.sig_NPLC.emit(nplc)
            return nplc
        except Exception as e:
            self._logger.error(f"Error reading NPLC: {e}")
            raise

    # -------------- setter wrappers -----------------

    def write_NPLC(self) -> None:
        #assert self._hardware is not None
        if not self._hardware:
            raise HP34401AError("Device not connected")
        try:
            self._hardware.set_nplc(self.setpoint_NPLC)
            self.sig_is_changing.emit(f"NPLC set to {self.setpoint_NPLC}")
            self.sig_NPLC.emit(self.setpoint_NPLC)
            self._logger.info(f"NPLC set to {self.setpoint_NPLC}")
        except Exception as e:
            self._logger.error(f"Error writing NPLC: {e}")
            raise

    def write_display_on(self) -> None:
        """ True to enable display, False for dark mode """
        if not self._hardware:
            raise HP34401AError("Device not connected")
        try:
            enabled = self.setpoint_display_on
            self._hardware.set_display(enabled)
            status = "enabled" if enabled else "disabled (dark mode)"
            self.sig_is_changing.emit(f"Display {status}")
        except Exception as e:
            self._logger.error(f"Error setting display: {e}")
            raise

    #get_errors

    # -------------- bulk helper ---------------------
    def get_all(self):
        """Convenience method: query a representative subset of parameters."""
        try:
            if not self._connected:
                return
            self.get_dc_voltage()
            time.sleep(0.05)
        except Exception as e:
            self._logger.error(f"Error in get_all: {e}")
            

    # -------------- thread main ---------------------
    def run(self):
        if self.reject_signal or not self._connected or self._hardware is None:
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
        """Stop the thread and reject new signals."""
        self._logger.info("Stopping HP34401A logic thread")
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