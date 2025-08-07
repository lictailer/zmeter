from PyQt6 import QtCore
import time 
from .MFLI_hardware import MFLI_Hardware, MFLIHardwareError 

class MFLI_Logic(QtCore.QThread):

    """Qt thread-wrapper that exposes MFLI_Hardware methods via signals.""" 
    # ---------- value update signals ----------
    DEMODS = [1, 2] #later will be increased to [1, 2, 3, 4]
    DEMOD_PARAMETERS = ['auto_range', 'harmonic', 'phase', 'auto_phase','zero_phase','sinc_filter', 'time_constant', 'filter_order'] # 'adc', 'rate', 'osc', 'enable'

    sig_output_enable = QtCore.pyqtSignal(object)

    sig_differential_output = QtCore.pyqtSignal(object)

    sig_osc1_output_enable = QtCore.pyqtSignal(object)
    
    sig_frequency1 = QtCore.pyqtSignal(object)
    
    sig_amplitude1 = QtCore.pyqtSignal(object)
    
    sig_phase1 = QtCore.pyqtSignal(object)
    sig_phase2 = QtCore.pyqtSignal(object)
    sig_phase3 = QtCore.pyqtSignal(object)
    sig_phase4 = QtCore.pyqtSignal(object) 
    

    sig_dc_offset = QtCore.pyqtSignal(object)
    sig_dc_offset_enable = QtCore.pyqtSignal(object)
    sig_preset_basic = QtCore.pyqtSignal(object)
    sig_output_autorange = QtCore.pyqtSignal(object)
    sig_output_range = QtCore.pyqtSignal(object)
    

    # ---------- plot signals ----------
    sig_X1 = QtCore.pyqtSignal(object)
    sig_Y1 = QtCore.pyqtSignal(object)
    sig_R1 = QtCore.pyqtSignal(object)
    sig_Theta1 = QtCore.pyqtSignal(object)
    sig_X2 = QtCore.pyqtSignal(object)
    sig_Y2 = QtCore.pyqtSignal(object)
    sig_R2 = QtCore.pyqtSignal(object)
    sig_Theta2 = QtCore.pyqtSignal(object)

    # ---------- demodulator signals ----------
    #DEMOD_PARAMETERS = ['auto_range', 'harmonic', 'phase', 'auto_phase','zero_phase','sinc_filter', 'time_constant', 'filter_order'] # 'adc', 'rate', 'osc', 'enable'
    sig_auto_range_1 = QtCore.pyqtSignal(object)
    sig_harmonic_1 = QtCore.pyqtSignal(object)
    sig_phase_1 = QtCore.pyqtSignal(object)
    sig_auto_phase_1 = QtCore.pyqtSignal(object)
    sig_zero_phase_1 = QtCore.pyqtSignal(object)
    sig_sinc_filter_1 = QtCore.pyqtSignal(object)
    sig_time_constant_1 = QtCore.pyqtSignal(object)
    sig_filter_order_1 = QtCore.pyqtSignal(object)

    sig_auto_range_2 = QtCore.pyqtSignal(object)
    sig_harmonic_2 = QtCore.pyqtSignal(object)
    sig_phase_2 = QtCore.pyqtSignal(object)
    sig_auto_phase_2 = QtCore.pyqtSignal(object)
    sig_zero_phase_2 = QtCore.pyqtSignal(object)
    sig_sinc_filter_2 = QtCore.pyqtSignal(object)
    sig_time_constant_2 = QtCore.pyqtSignal(object)
    sig_filter_order_2 = QtCore.pyqtSignal(object)


    # ---------- generic state signals ----------

    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object) 

    def __init__(self):

        super().__init__()

        self.job: str = ""

        self._init_setpoints()

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


    def _init_setpoints(self):
        self.setpoint_output_enable = False
        self.setpoint_differential_output = False
        self.setpoint_osc1_output_enable = False
        self.setpoint_osc2_output_enable = False
        self.setpoint_osc3_output_enable = False
        self.setpoint_osc4_output_enable = False
        self.setpoint_frequency1 = 10e3
        self.setpoint_amplitude1 = 0
        self.setpoint_phase1 = 0
        self.setpoint_phase2 = 0
        self.setpoint_phase3 = 0
        self.setpoint_phase4 = 0
        self.setpoint_dc_offset = 0
        self.setpoint_output_autorange = False
        self.setpoint_output_range = 10.0
        self.setpoint_filter_order_1 = 1
        self.setpoint_filter_order_2 = 1
        self.setpoint_auto_range_1 = True
        self.setpoint_auto_range_2 = True
        self.setpoint_auto_phase_1 = True
        self.setpoint_auto_phase_2 = True
        self.setpoint_zero_phase_1 = False
        self.setpoint_zero_phase_2 = False
        self.setpoint_sinc_filter_1 = False
        self.setpoint_sinc_filter_2 = False
        self.setpoint_time_constant_1 = 1e-6
        self.setpoint_time_constant_2 = 1e-6
        self.setpoint_harmonic_1 = 1
        self.setpoint_harmonic_2 = 1


        

    def configure_basic_mode_hardware(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_osc_to_external_ref(demod_index = 0)
            for ext_ref_index in [0, 1]:
                self.hardware.set_external_ref_enable(ext_ref_index = ext_ref_index, enable = False)
                self.hardware.set_osc_to_external_ref(demod_index = ext_ref_index * 2)
            for demod_index in [0, 1, 2, 3]:
                self.hardware.set_demod_enable(demod_index = demod_index, enable = True)
                self.hardware.set_demod_rate(demod_index = demod_index, rate = 1674)
                self.hardware.set_demod_osc(demod_index = demod_index, osc_index = 0)
                self.hardware.set_demod_harmonic(demod_index = demod_index, harmonic = 1)
                self.hardware.set_demod_phase(demod_index = demod_index, phase = 0)
                self.hardware.set_demod_sinc_filter(demod_index = demod_index, enable = False)
                self.hardware.set_demod_trigger(demod_index = demod_index, trigger_mode = "continuous")
                self.hardware.set_demod_order(demod_index = demod_index, order = 1)
                
            
            self.hardware.set_demod_adc(demod_index = 0, adc_index = 1)
            self.hardware.set_demod_adc(demod_index = 1, adc_index = 0)
            self.hardware.set_demod_adc(demod_index = 2, adc_index = 0)
            self.hardware.set_demod_adc(demod_index = 3, adc_index = 0)

            self.hardware.set_output_enable(enable = True)
            self.hardware.set_differential_output(enable = False)
            self.hardware.set_osc_output_enable(osc_index = 0, enable = True)
            self.hardware.set_osc_amplitude(osc_index = 0, amplitude = 0)
            self.hardware.set_osc_frequency(osc_index = 0, f_hz = 17.777)

            for osc_index in [1, 2, 3]:
                self.hardware.set_osc_amplitude(osc_index = int(osc_index), amplitude = 0)
                self.hardware.set_osc_frequency(osc_index = int(osc_index), f_hz = 1000)
                self.hardware.set_osc_output_enable(osc_index = int(osc_index), enable = False)

            self.hardware.set_output_impedance(impedance="high_impedance")
            self.hardware.set_output_add(enable = False)
            self.hardware.set_sigin_impedance(impedance="10_MOhm")
            self.hardware.set_sigin_enable(enable=True)
            self.hardware.set_sigin_float(enable=False)
            self.hardware.set_sigin_range(range_v=10.0)
            self.hardware.set_sigin_scaling(scaling=1.0)
            self.hardware.set_currin_enable(enable=True)
            self.hardware.set_currin_range(range_a=1e-6)
            self.hardware.set_currin_scaling(scaling=1.0)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Failed to configure basic hardware: {e}")
            raise

    # --- Frequency ---

    def get_frequency1(self, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_osc_frequency(osc_index = int(osc_index))
            self.sig_frequency1.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting frequency: {e}")
            raise
    
    def set_frequency1(self, osc_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            freq  = float(self.setpoint_frequency1)
            self.hardware.set_osc_frequency(osc_index = int(osc_index), f_hz = freq)
            self.sig_is_changing.emit(f"frequency set to {freq} (osc {int(osc_index)})")
            self.sig_frequency1.emit(freq)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting frequency: {e}")
            raise

    # --- Amplitude ---

    def get_amplitude1(self, osc_index=0) -> float:
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_osc_amplitude(osc_index = int(osc_index))
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
            self.hardware.set_osc_amplitude(osc_index = int(osc_index), amplitude = amp)
            self.sig_is_changing.emit(f"amplitude set to {amp} (osc {int(osc_index)})")
            self.sig_amplitude1.emit(amp)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting amplitude: {e}")
            raise

    # --- Phase ---

    '''def get_phase1(self, demod_index=0):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_phase(demod_index)
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
            self.hardware.set_demod_phase(phase, demod_index)
            self.sig_is_changing.emit(f"phase set to {phase} (demod {demod_index})")
            self.sig_phase1.emit(phase)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting phase: {e}")
            raise

        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            phase = self.setpoint_phase4
            self.hardware.set_demod_phase(phase, demod_index)
            self.sig_is_changing.emit(f"phase set to {phase} (demod {demod_index})")
            self.sig_phase4.emit(phase)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting phase: {e}")
            raise
    '''
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

    def get_demod_sample(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_sample(demod_index = 0)
            self.sig_X1.emit(val['x'])
            self.sig_Y1.emit(val['y'])
            self.sig_R1.emit(val['r'])
            self.sig_Theta1.emit(val['phase'])
            val = self.hardware.get_demod_sample(demod_index = 1)
            self.sig_X2.emit(val['x'])
            self.sig_Y2.emit(val['y'])
            self.sig_R2.emit(val['r'])
            self.sig_Theta2.emit(val['phase'])
            return True
        except (MFLIHardwareError, Exception) as e:
            #self.sig_is_changing.emit(f"Error getting demod sample: {e}")
            print(f"Error getting demod sample: {e}")
            raise 
            
    # --- Demodulator Methods ---
    def set_auto_range_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.sig_is_changing.emit('Autoranging input current')
            self.hardware.set_currin_autorange(enable = True)
            self.sig_is_changing.emit("Current input autoranged")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting auto range: {e}")
            raise
    def set_auto_range_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.sig_is_changing.emit('Autoranging input voltage')
            self.hardware.set_sigin_autorange(enable = True)
            self.sig_is_changing.emit("Voltage input autoranged")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting auto range: {e}")
            raise
    
    def set_zero_phase_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_demod_phase(phase = 0, demod_index = 0)
            self.sig_is_changing.emit("Demodulator 1 phase set to 0")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit("Error setting demodulator 1 phase to 0")
            raise

    def set_zero_phase_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_demod_phase(phase = 0, demod_index = 1)
            self.sig_is_changing.emit("Demodulator 2 phase set to 0")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit("Error setting demodulator 2 phase to 0")
            raise   

    def set_auto_phase_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_demod_auto_phase(demod_index = 0)
            self.sig_is_changing.emit("Demodulator 1: auto_phase ")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit("Error setting demodulator 1 phase auto-set")
            raise

    def set_auto_phase_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            self.hardware.set_demod_auto_phase(demod_index = 1)
            self.sig_is_changing.emit("Demodulator 2: auto_phase ")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit("Error setting demodulator 2 phase auto-set")
            raise

    def set_sinc_filter_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            enable = self.setpoint_sinc_filter_1
            self.hardware.set_demod_sinc_filter(enable = enable, demod_index = 0)
            self.sig_is_changing.emit(f"sinc filter 1 set to {enable}")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting sinc filter 1: {e}")
            raise

    def get_sinc_filter_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_sinc_filter(demod_index = 0)
            self.sig_sinc_filter_1.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting sinc filter 1: {e}")
            raise

    def set_sinc_filter_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            enable = self.setpoint_sinc_filter_2
            self.hardware.set_demod_sinc_filter(enable = enable, demod_index = 1)
            self.sig_is_changing.emit(f"sinc filter 2 set to {enable}")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting sinc filter 2: {e}")
            raise

    def get_sinc_filter_2(self):

        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_sinc_filter(demod_index = 1)
            self.sig_sinc_filter_2.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting sinc filter 2: {e}")
            raise

    
    def set_filter_order_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            order_val = self.setpoint_filter_order_1
            self.hardware.set_demod_order(order = order_val, demod_index = 0)
            self.sig_is_changing.emit(f"filter order 1 set to {order_val}")
            self.sig_filter_order_1.emit(order_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting filter order 1: {e}")
            raise 

    def get_filter_order_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_order(demod_index = 0)
            self.sig_filter_order_1.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting filter order 1: {e}")
            raise 

    def set_filter_order_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            order_val = self.setpoint_filter_order_2
            self.hardware.set_demod_order(order = order_val, demod_index = 1)
            self.sig_is_changing.emit(f"filter order 2 set to {order_val}")
            self.sig_filter_order_2.emit(order_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting filter order 2: {e}")
            raise

    def get_filter_order_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_order(demod_index = 1)
            self.sig_filter_order_2.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting filter order 2: {e}")
            raise
    
    def set_time_constant_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            time_val = self.setpoint_time_constant_1
            self.hardware.set_demod_timeconstant(tau = time_val, demod_index = 0)
            self.sig_is_changing.emit(f"time constant 1 set to {time_val}")
            self.sig_time_constant_1.emit(time_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting time constant 1: {e}")
            raise

    def get_time_constant_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_timeconstant(demod_index = 0)
            self.sig_time_constant_1.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting time constant 1: {e}") 
            raise

    def set_time_constant_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            time_val = self.setpoint_time_constant_2
            self.hardware.set_demod_timeconstant(tau = time_val, demod_index = 1)
            self.sig_is_changing.emit(f"time constant 2 set to {time_val}")
            self.sig_time_constant_2.emit(time_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting time constant 2: {e}")
            raise

    def get_time_constant_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")    
        try:
            val = self.hardware.get_demod_timeconstant(demod_index = 1)
            self.sig_time_constant_2.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting time constant 2: {e}")    
            raise

    def set_harmonic_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            harmonic_val = self.setpoint_harmonic_1
            self.hardware.set_demod_harmonic(harmonic = harmonic_val, demod_index = 0)
            self.sig_is_changing.emit(f"harmonic 1 set to {harmonic_val}")  
            self.sig_harmonic_1.emit(harmonic_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting harmonic 1: {e}")
            raise

    def get_harmonic_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_harmonic(demod_index = 0)
            self.sig_harmonic_1.emit(val)   
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting harmonic 1: {e}")
            raise

    def set_harmonic_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            harmonic_val = self.setpoint_harmonic_2
            self.hardware.set_demod_harmonic(harmonic = harmonic_val, demod_index = 1)
            self.sig_is_changing.emit(f"harmonic 2 set to {harmonic_val}")
            self.sig_harmonic_2.emit(harmonic_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting harmonic 2: {e}")
            raise

    def get_harmonic_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_harmonic(demod_index = 1)
            self.sig_harmonic_2.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting harmonic 2: {e}")
            raise

    def set_phase_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            phase_val = self.setpoint_phase_1
            self.hardware.set_demod_phase(phase = phase_val, demod_index = 0)
            self.sig_is_changing.emit(f"phase 1 set to {phase_val}")
            self.sig_phase_1.emit(phase_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting phase 1: {e}")
            raise

    def get_phase_1(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_phase(demod_index = 0)
            self.sig_phase_1.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting phase 1: {e}")
            raise

    def set_phase_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            phase_val = self.setpoint_phase_2
            self.hardware.set_demod_phase(phase = phase_val, demod_index = 1)
            self.sig_is_changing.emit(f"phase 2 set to {phase_val}")
            self.sig_phase_2.emit(phase_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting phase 2: {e}")
            raise

    def get_phase_2(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:
            val = self.hardware.get_demod_phase(demod_index = 1)
            self.sig_phase_2.emit(val)
            return val
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting phase 2: {e}")    
            raise

    
    
    def get_demod_1_parameters(self):
        if self.hardware is None:
            raise RuntimeError("Hardware not connected")
        try:

            val = self.hardware.get_demod_harmonic(0)
            self.sig_harmonic_1.emit(val)
            val = self.hardware.get_demod_phase(demod_index = 0)
            self.sig_phase_1.emit(val)
            val = self.hardware.get_demod_sinc_filter(demod_index = 0)
            self.sig_sinc_filter_1.emit(val)
            val = self.hardware.get_demod_timeconstant(demod_index = 0)
            self.sig_time_constant_1.emit(val)
            val = self.hardware.get_demod_order(demod_index = 0)
            self.sig_filter_order_1.emit(val)
            return True
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting demod 1 parameters: {e}")
            raise 


    
    def get_demod_2_parameters(self):
            if self.hardware is None:
                raise RuntimeError("Hardware not connected")
            try:
                val = self.hardware.get_demod_harmonic(1)
                self.sig_harmonic_2.emit(val)
                val = self.hardware.get_demod_phase(demod_index = 1)
                self.sig_phase_2.emit(val)
                val = self.hardware.get_demod_sinc_filter(demod_index = 1)
                self.sig_sinc_filter_2.emit(val)
                val = self.hardware.get_demod_timeconstant(demod_index = 1)
                self.sig_time_constant_2.emit(val)
                val = self.hardware.get_demod_order(demod_index = 1)
                self.sig_filter_order_2.emit(val)
                return True
            except (MFLIHardwareError, Exception) as e:
                self.sig_is_changing.emit(f"Error getting demod 2 parameters: {e}")
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
        
        self.get_demod_sample()
        self.get_demod_1_parameters()
        self.get_demod_2_parameters()   


        self.monitor_count += 1
        if self.monitor_count >= 10:
            #self.get_output_enable()
            self.get_differential_output()
            #self.get_osc1_output_enable()
            self.get_frequency1()
            self.get_amplitude1()
            #self.get_phase_1()
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
        self.configure_basic_mode_hardware()
        self.sig_is_changing.emit("Preset complete")

    



    # -------------- stop helper ------------------------

    def stop(self):
        self.reject_signal = True
        self.quit()
        self.wait()
        self.reject_signal = False