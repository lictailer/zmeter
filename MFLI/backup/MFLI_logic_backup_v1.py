from PyQt6 import QtCore
import time

from MFLI_hardware import MFLI_Hardware, MFLIHardwareError

class MFLI_Logic(QtCore.QThread):
    """Qt thread-wrapper that exposes MFLI_Hardware methods via signals."""

    # ---------- value update signals ----------
    sig_output_enable = QtCore.pyqtSignal(object)
    sig_differential_output = QtCore.pyqtSignal(object)
    sig_osc1_output_enable = QtCore.pyqtSignal(object)
    sig_osc2_output_enable = QtCore.pyqtSignal(object)
    sig_osc3_output_enable = QtCore.pyqtSignal(object)
    sig_osc4_output_enable = QtCore.pyqtSignal(object)

    sig_amplitude1 = QtCore.pyqtSignal(object)
    sig_amplitude2 = QtCore.pyqtSignal(object)
    sig_amplitude3 = QtCore.pyqtSignal(object)
    sig_amplitude4 = QtCore.pyqtSignal(object)

    sig_frequency1 = QtCore.pyqtSignal(object)
    sig_frequency2 = QtCore.pyqtSignal(object)
    sig_frequency3 = QtCore.pyqtSignal(object)
    sig_frequency4 = QtCore.pyqtSignal(object)

    sig_phase1 = QtCore.pyqtSignal(object)
    sig_phase2 = QtCore.pyqtSignal(object)
    sig_phase3 = QtCore.pyqtSignal(object)
    sig_phase4 = QtCore.pyqtSignal(object)  

    # ---------- generic state signals ----------
    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.job: str = ""
        self.setpoint_output_enable = False
        self.setpoint_differential_output = False
        self.setpoint_osc1_output_enable = False
        self.setpoint_osc2_output_enable = False
        self.setpoint_osc3_output_enable = False
        self.setpoint_osc4_output_enable = False
        
        self.connected = False
        self.reject_signal = False
        self.hardware: MFLI_Hardware | None = None

    # -------------- Signal and setpoint mapping --------------
    def _get_osc_signal(self, osc_index):
        """Get the appropriate signal for the oscillator index."""
        signal_map = {
            1: self.sig_osc1_output_enable,
            2: self.sig_osc2_output_enable,
            3: self.sig_osc3_output_enable,
            4: self.sig_osc4_output_enable
        }
        return signal_map.get(osc_index)

    def _get_osc_setpoint(self, osc_index):
        """Get the setpoint value for the oscillator index."""
        setpoint_map = {
            1: self.setpoint_osc1_output_enable,
            2: self.setpoint_osc2_output_enable,
            3: self.setpoint_osc3_output_enable,
            4: self.setpoint_osc4_output_enable
        }
        return setpoint_map.get(osc_index, False)

    # -------------- connection helpers --------------
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

        max_attempts = 5
        delay_seconds = 3
        
        for attempt in range(1, max_attempts + 1):
            try:
                self.hardware = MFLI_Hardware(device_id)
                self.connected = True
                self.sig_connected.emit(f"connected to {device_id}")
                print(f"Connected to {device_id}")
                return True
            except (MFLIHardwareError, Exception) as e:
                self.sig_is_changing.emit(
                    f"Attempt {attempt} failed: Unable to connect to {device_id}. Retrying..." if attempt < max_attempts else
                    f"Error: Unable to connect to {device_id} after {max_attempts} attempts."
                )
                print(f"Error: Unable to connect to {device_id} on attempt {attempt}: {e}")
                if attempt < max_attempts:
                    time.sleep(delay_seconds)

        return False
    
    # -------------- hardware methods --------------

    # --- Frequency ---
    def get_frequency(self, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_frequency(osc_index)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting frequency: {e}")
            raise

    def set_frequency(self, freq, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_frequency(osc_index, freq)
            self.sig_is_changing.emit(f"frequency set to {freq} (osc {osc_index})")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting frequency: {e}")
            raise

    # --- Amplitude ---
    def get_amplitude(self, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_amplitude(osc_index)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting amplitude: {e}")
            raise

    def set_amplitude(self, amp=0, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_amplitude(amp, osc_index)
            self.sig_is_changing.emit(f"amplitude set to {amp} (osc {osc_index})")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting amplitude: {e}")
            raise

    # --- Phase ---
    def get_phase(self, demod_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_phase(demod_index)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting phase: {e}")
            raise

    def set_phase(self, phase=0, demod_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_phase(phase, demod_index)
            self.sig_is_changing.emit(f"phase set to {phase} (demod {demod_index})")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting phase: {e}")
            raise

    # --- Output Enable ---
    def get_output_enable(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_output_enable()
            self.sig_output_enable.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting output enable: {e}")
            raise

    def set_output_enable(self):
        print('logic set_output_enable')
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            enable = self.setpoint_output_enable
            self.hardware.set_output_enable(enable)
            self.sig_is_changing.emit(f"enable set to {enable}")
            self.sig_output_enable.emit(enable)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting output enable: {e}")
            raise

    # --- Differential Output ---
    def set_differential_output(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            enable = self.setpoint_differential_output
            self.hardware.set_differential_output(enable)
            self.sig_is_changing.emit(f"differential output set to {enable}")
            self.sig_differential_output.emit(enable)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting differential output: {e}")
            raise
    def get_differential_output(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_differential_output()
            self.sig_differential_output.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting differential output: {e}")
            raise
    
    # --- Generic Oscillator Output Enable Methods ---
    def set_osc_output_enable_by_index(self, osc_index):
        """Generic method to set oscillator output enable by index (1-4)."""
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            enable = self._get_osc_setpoint(osc_index)
            # Hardware oscillator indices are 0-based, but UI uses 1-based
            hw_index = osc_index - 1
            self.hardware.set_osc_output_enable(enable, hw_index)
            
            self.sig_is_changing.emit(f"osc{osc_index} output enable set to {enable}")
            
            # Emit the specific oscillator signal
            signal = self._get_osc_signal(osc_index)
            if signal:
                signal.emit(enable)
            
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting osc{osc_index} output enable: {e}")
            raise
    def get_osc_output_enable_by_index(self, osc_index):
        """Generic method to get oscillator output enable by index (1-4)."""
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            # Hardware oscillator indices are 0-based, but UI uses 1-based
            hw_index = osc_index - 1
            val = self.hardware.get_osc_output_enable(hw_index)
            
            # Emit the specific oscillator signal
            signal = self._get_osc_signal(osc_index)
            if signal:
                signal.emit(val)
            
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting osc{osc_index} output enable: {e}")
            raise

        """Generic method to get oscillator frequency by index (1-4)."""
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_frequency(osc_index)
            self.sig_frequency.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting osc{osc_index} frequency: {e}")
            raise
    
    # --- Individual Oscillator Methods (using generic implementation) ---
    def set_osc1_output_enable(self):
        self.set_osc_output_enable_by_index(1)
    def get_osc1_output_enable(self):
        return self.get_osc_output_enable_by_index(1)
    def set_osc2_output_enable(self):
        self.set_osc_output_enable_by_index(2)
    def get_osc2_output_enable(self):
        return self.get_osc_output_enable_by_index(2)
    def set_osc3_output_enable(self):
        self.set_osc_output_enable_by_index(3)
    def get_osc3_output_enable(self):
        return self.get_osc_output_enable_by_index(3)
    def set_osc4_output_enable(self):
        self.set_osc_output_enable_by_index(4)
    def get_osc4_output_enable(self):
        return self.get_osc_output_enable_by_index(4)
    
    # --- Generic Oscillator Frequency Methods ---
    def set_osc_frequency_by_index(self, osc_index, freq):
        """Generic method to set oscillator frequency by index (1-4)."""
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_frequency(freq, osc_index)
            self.sig_is_changing.emit(f"osc{osc_index} frequency set to {freq}")
            
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting osc{osc_index} frequency: {e}")
            raise
    def get_osc_frequency_by_index(self, osc_index):
        """Generic method to get oscillator frequency by index (1-4)."""
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_frequency(osc_index)
            #self.sig_frequency.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting osc{osc_index} frequency: {e}")
            raise
    # --- Individual Oscillator Methods (using generic implementation) --
    def set_osc1_frequency(self, freq):
        self.set_osc_frequency_by_index(1, freq)
    def get_osc1_frequency(self):
        return self.get_osc_frequency_by_index(1)
    def set_osc2_frequency(self, freq):
        self.set_osc_frequency_by_index(2, freq)    
    def get_osc2_frequency(self):
        return self.get_osc_frequency_by_index(2)
    def set_osc3_frequency(self, freq):
        self.set_osc_frequency_by_index(3, freq)
    def get_osc3_frequency(self):
        return self.get_osc_frequency_by_index(3)   
    def set_osc4_frequency(self, freq):
        self.set_osc_frequency_by_index(4, freq)
    def get_osc4_frequency(self):
        return self.get_osc_frequency_by_index(4)
    
    # --- Generic Oscillator Amplitude Methods ---
    # --- Generic Oscillator Phase Methods ---
    # --- Additional Hardware Methods ---
    def get_output_range(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_output_range()
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting output range: {e}")
            raise

    def set_output_range(self, range_val):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_output_range(range_val)
            self.sig_is_changing.emit(f"output range set to {range_val}")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting output range: {e}")
            raise

    def get_osc_output_enable(self, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_osc_output_enable(osc_index)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting osc output enable: {e}")
            raise

    def set_osc_output_enable(self, enable, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_osc_output_enable(enable, osc_index)
            self.sig_is_changing.emit(f"osc {osc_index} output enable set to {enable}")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting osc output enable: {e}")
            raise

    def get_demod_sample(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_sample()
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting demod sample: {e}")
            raise

    def get_X(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_X()
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting X: {e}")
            raise

    def get_Y(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_Y()
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting Y: {e}")
            raise

    def get_R(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_R()
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting R: {e}")
            raise

    def setup_basic(self, freq=10e3, amp=0.5, out_range=1.0, demod_rate=1000, tau=0.01, order=1):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.setup_basic(freq, amp, out_range, demod_rate, tau, order)
            self.sig_is_changing.emit(f"Basic setup complete: freq={freq}, amp={amp}, range={out_range}")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error during basic setup: {e}")
            raise

    def sync(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.sync()
            self.sig_is_changing.emit("Settings synchronized with device")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error syncing: {e}")
            raise

    def disconnect_device(self):
        """Safely stop the thread and close the hardware connection."""
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
                    print(f"[WARN] MFLI_Logic job '{self.job}' error:", exc)
            else:
                print(f"[WARN] MFLI_Logic has no job '{self.job}'")

            # reset marker
            self.job = ""

    # -------------- stop helper ------------------------
    def stop(self):
        self.reject_signal = True
        self.quit()
        self.wait()
        self.reject_signal = False