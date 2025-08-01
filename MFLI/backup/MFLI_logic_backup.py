from PyQt6 import QtCore
import time

from MFLI_hardware import MFLI_Hardware

class MFLI_Logic(QtCore.QThread):
    """Qt thread-wrapper that exposes MFLI_Hardware methods via signals."""

    # Signals for all demodulators, with index as first argument
    #sig_enable = QtCore.pyqtSignal(int, object)      # (demod_index, value)
    #sig_freq = QtCore.pyqtSignal(int, object)        # (osc_index, value)
    #sig_amplitude = QtCore.pyqtSignal(int, object)   # (osc_index, value)
    #sig_phase = QtCore.pyqtSignal(int, object)       # (demod_index, value)
    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.job: str = ""
        #self.setpoint_frequency = 0.0
        #self.setpoint_amplitude = 0.0
        #self.setpoint_phase = 0.0
        #self.setpoint_enable = False
        #self.setpoint_osc_index = 0
        #self.setpoint_demod_index = 0
        self.connected = False
        self.reject_signal = False
        self.hardware: MFLI_Hardware | None = None

    def get_available_devices(self):
        try:
            return MFLI_Hardware.get_available_devices()
        except Exception as e:
            self.sig_is_changing.emit(f"Error: Unable to get available devices. {e}")
            return []

    def connect_device(self, device_id: str):
        if self.connected:
            self.sig_is_changing.emit(f"Already connected to {device_id}")
            return False

        max_attempts = 3
        delay_seconds = 3
        

        for attempt in range(1, max_attempts + 1):
            try:
                self.hardware = MFLI_Hardware(device_id)
                self.connected = True
                self.sig_connected.emit(f"connected to {device_id}")
                return True
            except Exception as e:
                self.sig_is_changing.emit(
                    f"Attempt {attempt} failed: Unable to connect to {device_id}. Retrying..." if attempt < max_attempts else
                    f"Error: Unable to connect to {device_id} after {max_attempts} attempts."
                )
                print(f"Error: Unable to connect to {device_id} on attempt {attempt}: {e}")
                if attempt < max_attempts:
                    time.sleep(delay_seconds)

        return False

    # --- Frequency ---
    def get_frequency(self, osc_index=0):
        assert self.hardware is not None
        val = self.hardware.get_frequency(osc_index)
        #self.sig_freq.emit(osc_index, val)
        return val

    def set_frequency(self, freq, osc_index=0):
        assert self.hardware is not None
        self.hardware.set_frequency(osc_index, freq)
        self.sig_is_changing.emit(f"frequency set to {freq} (osc {osc_index})")
        #self.sig_freq.emit(osc_index, freq)

    # --- Amplitude ---
    def get_amplitude(self, osc_index=0):
        assert self.hardware is not None
        val = self.hardware.get_amplitude(osc_index)
        #self.sig_amplitude.emit(osc_index, val)
        return val

    def set_amplitude(self, amp, osc_index=0):
        assert self.hardware is not None
        self.hardware.set_amplitude(amp, osc_index)
        self.sig_is_changing.emit(f"amplitude set to {amp} (osc {osc_index})")
        #self.sig_amplitude.emit(osc_index, amp)

    # --- Phase ---
    def get_phase(self, demod_index=0):
        assert self.hardware is not None
        val = self.hardware.get_phase(demod_index)
        #self.sig_phase.emit(demod_index, val)
        return val

    def set_phase(self, phase, demod_index=0):
        assert self.hardware is not None
        self.hardware.set_phase(phase, demod_index)
        self.sig_is_changing.emit(f"phase set to {phase} (demod {demod_index})")
        #self.sig_phase.emit(demod_index, phase)

    # --- Enable ---
    def get_output_enable(self):
        assert self.hardware is not None
        val = self.hardware.get_output_enable()
        #self.sig_enable.emit(demod_index, val)
        return val

    def set_output_enable(self, enable):
        assert self.hardware is not None
        self.hardware.set_output_enable(enable)
        self.sig_is_changing.emit(f"enable set to {enable}")
        #self.sig_enable.emit(demod_index, enable)


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
        else:
            print("No connection to disconnect from")

        if self.connected:
            self.connected = False
            self.sig_connected.emit("disconnected")

        # allow new jobs after a future reconnect
        self.reject_signal = False