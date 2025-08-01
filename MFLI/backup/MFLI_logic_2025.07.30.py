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

    sig_frequency1 = QtCore.pyqtSignal(object)
    sig_frequency2 = QtCore.pyqtSignal(object)
    sig_frequency3 = QtCore.pyqtSignal(object)
    sig_frequency4 = QtCore.pyqtSignal(object)

    sig_amplitude1 = QtCore.pyqtSignal(object)
    sig_amplitude2 = QtCore.pyqtSignal(object)
    sig_amplitude3 = QtCore.pyqtSignal(object)
    sig_amplitude4 = QtCore.pyqtSignal(object)  

    sig_phase1 = QtCore.pyqtSignal(object)
    sig_phase2 = QtCore.pyqtSignal(object)
    sig_phase3 = QtCore.pyqtSignal(object)
    sig_phase4 = QtCore.pyqtSignal(object) 
    

    sig_dc_offset = QtCore.pyqtSignal(object)
    sig_dc_offset_enable = QtCore.pyqtSignal(object)
    sig_preset_basic = QtCore.pyqtSignal(object)
    sig_output_autorange = QtCore.pyqtSignal(object)
    sig_output_range = QtCore.pyqtSignal(object)

    # ---------- generic state signals ----------

    sig_is_changing = QtCore.pyqtSignal(object)

    sig_connected = QtCore.pyqtSignal(object) 
    def __init__(self):

        super().__init__()

        self.job: str = ""

        self.setpoint_output_enable = None

        self.setpoint_differential_output = None

        self.setpoint_osc1_output_enable = None
        self.setpoint_osc2_output_enable = None
        self.setpoint_osc3_output_enable = None
        self.setpoint_osc4_output_enable = None

        self.setpoint_frequency1 = 1000
        self.setpoint_frequency2 = 2000.0
        self.setpoint_frequency3 = 3000.0
        self.setpoint_frequency4 = 4000.0

        self.setpoint_amplitude1 = 1.0
        self.setpoint_amplitude2 = 1.0
        self.setpoint_amplitude3 = 1.0
        self.setpoint_amplitude4 = 1.0

        self.setpoint_phase1 = 0.0
        self.setpoint_phase2 = 0.0
        self.setpoint_phase3 = 0.0  
        self.setpoint_phase4 = 0.0

        self.setpoint_dc_offset = 0.0
        self.setpoint_output_autorange = True
        self.setpoint_output_range = 1.0

        

        #self.setpoint_osc_index = 0

        #self.setpoint_demod_index = 0

        self.monitor_count = 0

        self.connected = False
        self.reject_signal = False
        self.hardware: MFLI_Hardware | None = None 
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

    def get_frequency1(self, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_frequency(osc_index)
            self.sig_frequency1.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting frequency: {e}")
            raise
    def set_frequency1(self, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            freq  = self.setpoint_frequency1
            self.hardware.set_frequency(osc_index, freq)
            self.sig_is_changing.emit(f"frequency set to {freq} (osc {osc_index})")
            self.sig_frequency1.emit(freq)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting frequency: {e}")
            raise 

    
    def get_frequency2(self, osc_index=1):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_frequency(osc_index)
            self.sig_frequency2.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting frequency: {e}")
            raise
    def set_frequency2(self, osc_index=1):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            freq  = self.setpoint_frequency2
            self.hardware.set_frequency(osc_index, freq)
            self.sig_is_changing.emit(f"frequency set to {freq} (osc {osc_index})")
            self.sig_frequency2.emit(freq)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting frequency: {e}")
            raise 
    
    def get_frequency3(self, osc_index=2):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_frequency(osc_index)
            self.sig_frequency3.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting frequency: {e}")
            raise
    def set_frequency3(self, osc_index=2):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            freq  = self.setpoint_frequency3
            self.hardware.set_frequency(osc_index, freq)
            self.sig_is_changing.emit(f"frequency set to {freq} (osc {osc_index})")
            self.sig_frequency3.emit(freq)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting frequency: {e}")
            raise 

   
    def get_frequency4(self, osc_index=3):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_frequency(osc_index)
            self.sig_frequency4.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting frequency: {e}")
            raise
    def set_frequency4(self, osc_index=3):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            freq  = self.setpoint_frequency4
            self.hardware.set_frequency(osc_index, freq)
            self.sig_is_changing.emit(f"frequency set to {freq} (osc {osc_index})")
            self.sig_frequency4.emit(freq)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting frequency: {e}")
            raise 
    # --- Amplitude ---

    def get_amplitude1(self, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_amplitude(osc_index)
            self.sig_amplitude1.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting amplitude: {e}")
            raise 
        
    def set_amplitude1(self, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            amp = self.setpoint_amplitude1
            self.hardware.set_amplitude(amp, osc_index)
            self.sig_is_changing.emit(f"amplitude set to {amp} (osc {osc_index})")
            self.sig_amplitude1.emit(amp)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting amplitude: {e}")
            raise 

    def get_amplitude2(self, osc_index=1):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_amplitude(osc_index)
            self.sig_amplitude2.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting amplitude: {e}")
            raise 
    def set_amplitude2(self, osc_index=1):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            amp = self.setpoint_amplitude2
            self.hardware.set_amplitude(amp, osc_index)
            self.sig_is_changing.emit(f"amplitude set to {amp} (osc {osc_index})")
            self.sig_amplitude2.emit(amp)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting amplitude: {e}")
            raise 
    
    def get_amplitude3(self, osc_index=2):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_amplitude(osc_index)
            self.sig_amplitude3.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting amplitude: {e}")
            raise 
    def set_amplitude3(self, osc_index=2):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            amp = self.setpoint_amplitude3
            self.hardware.set_amplitude(amp, osc_index)
            self.sig_is_changing.emit(f"amplitude set to {amp} (osc {osc_index})")
            self.sig_amplitude3.emit(amp)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting amplitude: {e}")
            raise 
    def get_amplitude4(self, osc_index=3):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_amplitude(osc_index)
            self.sig_amplitude4.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting amplitude: {e}")
            raise 
    def set_amplitude4(self, osc_index=3):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            amp = self.setpoint_amplitude4
            self.hardware.set_amplitude(amp, osc_index)
            self.sig_is_changing.emit(f"amplitude set to {amp} (osc {osc_index})")
            self.sig_amplitude4.emit(amp)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting amplitude: {e}")
            raise 
    

    # --- Phase ---

    def get_phase1(self, demod_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_phase(demod_index)
            self.sig_phase1.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting phase: {e}")
            raise 
    def set_phase1(self, demod_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            phase = self.setpoint_phase1
            self.hardware.set_phase(phase, demod_index)
            self.sig_is_changing.emit(f"phase set to {phase} (demod {demod_index})")
            self.sig_phase1.emit(phase)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting phase: {e}")
            raise 
    
    def get_phase2(self, demod_index=1):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_phase(demod_index)
            self.sig_phase2.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting phase: {e}")
            raise 
    def set_phase2(self, demod_index=1):    
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            phase = self.setpoint_phase2
            self.hardware.set_phase(phase, demod_index)
            self.sig_is_changing.emit(f"phase set to {phase} (demod {demod_index})")
            self.sig_phase2.emit(phase)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting phase: {e}")
            raise 
    def get_phase3(self, demod_index=2):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_phase(demod_index)
            self.sig_phase3.emit(val)
            return val 
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting phase: {e}")
            raise 
    def set_phase3(self, demod_index=2):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected") 
        try:
            phase = self.setpoint_phase3
            self.hardware.set_phase(phase, demod_index)
            self.sig_is_changing.emit(f"phase set to {phase} (demod {demod_index})")
            self.sig_phase3.emit(phase)
        except (MFLIHardwareError, Exception) as e: 
            self.sig_is_changing.emit(f"Error setting phase: {e}")
            raise 
    
    def get_phase4(self, demod_index=3):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_phase(demod_index)
            self.sig_phase4.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting phase: {e}")
            raise 
    def set_phase4(self, demod_index=3): 
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            phase = self.setpoint_phase4
            self.hardware.set_phase(phase, demod_index)
            self.sig_is_changing.emit(f"phase set to {phase} (demod {demod_index})")
            self.sig_phase4.emit(phase)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting phase: {e}")
            raise 
    
    # --- DC Offset ---

    def get_dc_offset(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_dc_offset()
            self.sig_dc_offset.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting dc offset: {e}")
            raise 
    def set_dc_offset(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            offset = self.setpoint_dc_offset
            self.hardware.set_dc_offset(offset)
            self.sig_is_changing.emit(f"dc offset set to {offset}")
            self.sig_dc_offset.emit(offset)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting dc offset: {e}")
            raise


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
    def set_differential_output(self):

        if self.hardware is None:

            raise RuntimeError("Hardware not connected")

        try:

            enable = self.setpoint_differential_output

            self.hardware.set_differential_output(enable)

            self.sig_is_changing.emit(f"differential output set to {enable}")

        except (MFLIHardwareError, Exception) as e:

            self.sig_is_changing.emit(f"Error setting differential output: {e}")

            raise 
    def get_differential_output(self):

        

        if self.hardware is None:

            raise RuntimeError("Hardware not connected")

        try:

            val = self.hardware.get_differential_output()

            return val

        except (MFLIHardwareError, Exception) as e:

            self.sig_is_changing.emit(f"Error getting differential output: {e}")

            raise

    

    # --- Oscillator Output Enable ---

    def set_osc1_output_enable(self):

        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            enable = self.setpoint_osc1_output_enable
            self.hardware.set_osc_output_enable(enable, 0)
            self.sig_is_changing.emit(f"osc1 output enable set to {enable}")
            self.sig_osc1_output_enable.emit(enable)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting osc1 output enable: {e}")
            raise 
    
    def get_osc1_output_enable(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_osc_output_enable(0)
            self.sig_osc1_output_enable.emit(val)
            return val  
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting osc1 output enable: {e}")
            raise 
    def set_osc2_output_enable(self):

        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            enable = self.setpoint_osc2_output_enable
            self.hardware.set_osc_output_enable(enable, 1)
            self.sig_is_changing.emit(f"osc2 output enable set to {enable}")
            self.sig_osc2_output_enable.emit(enable)    
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting osc2 output enable: {e}")
            raise 
    

        if self.hardware is None:

            raise RuntimeError("Hardware not connected")

        try:

            val = self.hardware.get_osc_output_enable(0)

            return val

        except (MFLIHardwareError, Exception) as e: 

            self.sig_is_changing.emit(f"Error getting osc1 output enable: {e}")

            raise 
    def get_osc2_output_enable(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_osc_output_enable(1)
            self.sig_osc2_output_enable.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting osc2 output enable: {e}")
            raise
    def set_osc3_output_enable(self):

        if self.hardware is None:

            raise RuntimeError("Hardware not connected")

        try:

            enable = self.setpoint_osc3_output_enable

            self.hardware.set_osc_output_enable(enable, 2)

            self.sig_is_changing.emit(f"osc3 output enable set to {enable}")    

            self.sig_osc3_output_enable.emit(enable)

        except (MFLIHardwareError, Exception) as e:

            self.sig_is_changing.emit(f"Error setting osc3 output enable: {e}")

            raise 
    def get_osc3_output_enable(self):   
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_osc_output_enable(2)
            self.sig_osc3_output_enable.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e: 
            self.sig_is_changing.emit(f"Error getting osc3 output enable: {e}")
            raise 
    def set_osc4_output_enable(self):

        if self.hardware is None:

            raise RuntimeError("Hardware not connected")    

        try:

            enable = self.setpoint_osc4_output_enable

            self.hardware.set_osc_output_enable(enable, 3)

            self.sig_is_changing.emit(f"osc4 output enable set to {enable}")

            self.sig_osc4_output_enable.emit(enable)

        except (MFLIHardwareError, Exception) as e: 

            self.sig_is_changing.emit(f"Error setting osc4 output enable: {e}")

            raise 
    def get_osc4_output_enable(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")    
        try:
            val = self.hardware.get_osc_output_enable(3)
            self.sig_osc4_output_enable.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting osc4 output enable: {e}")
            raise   



    def set_output_autorange(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_output_auto_range(self.setpoint_output_autorange)
            self.sig_is_changing.emit(f"output autorange set to {self.setpoint_output_autorange}")
            self.sig_output_autorange.emit(self.setpoint_output_autorange)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting output autorange: {e}")
            raise
    def get_output_autorange(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_output_auto_range()
            self.sig_output_autorange.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting output autorange: {e}")
            raise
        

    # --- Additional Hardware Methods ---

    def get_output_range(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_output_range()
            self.sig_output_range.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting output range: {e}")
            raise 
    
    def set_output_range(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            range_val = self.setpoint_output_range
            self.hardware.set_output_range(range_val)
            self.sig_is_changing.emit(f"output range set to {range_val}")
            self.sig_output_range.emit(range_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting output range: {e}")
            raise 


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
    
    
    
    def get_all(self):
        # 
        self.monitor_count += 1
        if self.monitor_count >= 10:
            self.get_output_enable()
            self.get_differential_output()
            self.get_osc1_output_enable()
            self.get_osc2_output_enable()
            self.get_osc3_output_enable()
            self.get_osc4_output_enable()
            self.get_frequency1()
            self.get_frequency2()
            self.get_frequency3()
            self.get_frequency4()
            self.get_amplitude1()
            self.get_amplitude2()
            self.get_amplitude3()
            self.get_amplitude4()
            self.get_phase1()
            self.get_phase2()
            self.get_phase3()
            self.get_phase4()
            self.get_dc_offset()
            self.get_output_autorange()
            self.get_output_range()
            self.monitor_count = 0
        time.sleep(0.05)
    
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


    def preset_basic(self):
        self.hardware.setup_basic(freq=1e3, amp=0, tau=0.01, order=3)
        self.sig_is_changing.emit("Preset complete")

    # -------------- stop helper ------------------------

    def stop(self):

        self.reject_signal = True

        self.quit()

        self.wait()

        self.reject_signal = False