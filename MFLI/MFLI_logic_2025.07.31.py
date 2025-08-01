# =============================================================================
# MFLI_logic.py - Business Logic for MFLI Lock-in Amplifier
# Focused implementation: 1 oscillator, 2 demodulators (voltage/current)
# =============================================================================

from PyQt6 import QtCore
import time
import logging
from MFLI_hardware import MFLI_Hardware, MFLIHardwareError


class MFLI_Logic(QtCore.QThread):
    """
    MFLI Logic Layer - Simplified for single oscillator + dual demodulator setup.
    
    Configuration:
    - Oscillator 0: Main frequency source
    - Demodulator 0: Voltage measurements (Signal Input)
    - Demodulator 1: Current measurements (Current Input)
    - All other oscillators/demodulators disabled
    """

    # -------------------------------------------------------------------------
    # SIGNALS - Value Updates
    # -------------------------------------------------------------------------
    # Connection status
    sig_connected = QtCore.pyqtSignal(object)
    sig_is_changing = QtCore.pyqtSignal(object)
    
    # Device info
    sig_clockbase = QtCore.pyqtSignal(object)
    
    # Oscillator 0 (main frequency source)
    sig_frequency = QtCore.pyqtSignal(object)
    
    # Signal output controls
    sig_output_enable = QtCore.pyqtSignal(object)
    sig_amplitude = QtCore.pyqtSignal(object)
    sig_dc_offset = QtCore.pyqtSignal(object)
    sig_differential_output = QtCore.pyqtSignal(object)
    sig_output_range = QtCore.pyqtSignal(object)
    sig_output_autorange = QtCore.pyqtSignal(object)
    
    # Demodulator controls
    sig_voltage_demod_enable = QtCore.pyqtSignal(object)    # Demod 0
    sig_current_demod_enable = QtCore.pyqtSignal(object)    # Demod 1
    sig_voltage_phase = QtCore.pyqtSignal(object)           # Demod 0 phase
    sig_current_phase = QtCore.pyqtSignal(object)           # Demod 1 phase
    sig_voltage_timeconstant = QtCore.pyqtSignal(object)    # Demod 0 filter
    sig_current_timeconstant = QtCore.pyqtSignal(object)    # Demod 1 filter
    
    # Input controls
    sig_sigin_enable = QtCore.pyqtSignal(object)
    sig_sigin_range = QtCore.pyqtSignal(object)
    sig_sigin_autorange = QtCore.pyqtSignal(object)
    sig_currin_enable = QtCore.pyqtSignal(object)
    sig_currin_range = QtCore.pyqtSignal(object)
    sig_currin_autorange = QtCore.pyqtSignal(object)
    
    # Measurement data
    sig_voltage_sample = QtCore.pyqtSignal(object)          # Demod 0 data
    sig_current_sample = QtCore.pyqtSignal(object)          # Demod 1 data
    
    # Error handling
    sig_error = QtCore.pyqtSignal(object)
    sig_warning = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        
        # Job queue
        self.job = ""
        
        # Connection state
        self.connected = False
        self.reject_signal = False
        
        # Hardware interface
        self._hardware: MFLI_Hardware | None = None
        
        # =====================================================================
        # SETPOINTS - Values to be written to hardware
        # =====================================================================
        
        # Oscillator 0 setpoints
        self.setpoint_frequency = 1000.0  # Hz
        
        # Output setpoints
        self.setpoint_output_enable = False
        self.setpoint_amplitude = 0.1  # V
        self.setpoint_dc_offset = 0.0  # V
        self.setpoint_differential_output = False
        self.setpoint_output_range = 1.0  # V
        self.setpoint_output_autorange = True
        
        # Demodulator setpoints
        self.setpoint_voltage_demod_enable = True
        self.setpoint_current_demod_enable = True
        self.setpoint_voltage_phase = 0.0  # degrees
        self.setpoint_current_phase = 0.0  # degrees
        self.setpoint_voltage_timeconstant = 0.01  # seconds
        self.setpoint_current_timeconstant = 0.01  # seconds
        
        # Input setpoints
        self.setpoint_sigin_enable = True
        self.setpoint_sigin_range = 1.0  # V
        self.setpoint_sigin_autorange = True
        self.setpoint_currin_enable = True
        self.setpoint_currin_range = 1e-6  # A (1 µA)
        self.setpoint_currin_autorange = True
        
        # Setup logging
        self._logger = logging.getLogger(__name__)

    # -------------------------------------------------------------------------
    # CONNECTION METHODS
    # -------------------------------------------------------------------------
    @staticmethod
    def get_available_devices():
        """Get list of available MFLI devices."""
        try:
            return MFLI_Hardware.get_available_devices()
        except Exception as e:
            logging.error(f"Failed to get available devices: {e}")
            return []

    def connect_device(self, device_id: str):
        """Connect to MFLI device and configure for voltage/current measurement."""
        if self.connected:
            self._logger.warning("Already connected. Disconnect first.")
            return False
            
        try:
            self._logger.info(f"Connecting to MFLI {device_id}")
            self._hardware = MFLI_Hardware(device_id)
            
            # Apply initial configuration
            self._configure_for_dual_measurement()
            self.debug_demod_status()  # Temporary debug
            
            self.connected = True
            self.sig_connected.emit(f"Connected to {device_id}")
            self._logger.info(f"Successfully connected to {device_id}")
            return True
            
        except Exception as e:
            error_msg = f"Failed to connect to {device_id}: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)
            self._cleanup_connection()
            return False

    def disconnect_device(self):
        """Safely disconnect from MFLI device."""
        self._logger.info("Disconnecting from MFLI")
        self.reject_signal = True
        self.job = ""
        
        # Wait for thread to finish
        if self.isRunning():
            self._logger.debug("Waiting for thread to finish...")
            self.wait()
        
        # Cleanup hardware
        self._cleanup_connection()
        
        # Update state
        if self.connected:
            self.connected = False
            self.sig_connected.emit("Disconnected")
        
        self.reject_signal = False

    def _cleanup_connection(self):
        """Clean up hardware connection."""
        if self._hardware is not None:
            try:
                self._hardware.disconnect()
            except Exception as e:
                self._logger.warning(f"Error during disconnect: {e}")
            finally:
                self._hardware = None



    def debug_demod_status(self):
        """Debug method to check demodulator configuration."""
        if not self._hardware:
            return
        
        try:
            self._logger.info("=== DEMODULATOR STATUS DEBUG ===")
            
            for demod_idx in [0, 1]:
                enabled = self._hardware.get_demod_enable(demod_idx)
                osc_connected = self._hardware.get_demod_osc(demod_idx)
                adc_input = self._hardware.get_demod_adc(demod_idx)
                rate = self._hardware.get_demod_rate(demod_idx)
                
                self._logger.info(f"Demod {demod_idx}: enabled={enabled}, osc={osc_connected}, adc={adc_input}, rate={rate}")
                
            # Check oscillator frequency
            osc_freq = self._hardware.get_frequency(0)
            self._logger.info(f"Oscillator 0 frequency: {osc_freq} Hz")
            
            # Check input enables
            sigin_enabled = self._hardware.get_sigin_enable()
            currin_enabled = self._hardware.get_currin_enable()
            self._logger.info(f"Signal input enabled: {sigin_enabled}")
            self._logger.info(f"Current input enabled: {currin_enabled}")
            
            self._logger.info("=== END DEBUG ===")
            
        except Exception as e:
            self._logger.error(f"Debug failed: {e}")

    def _configure_for_dual_measurement(self):
        """Configure MFLI for voltage/current dual measurement setup."""
        if not self._hardware:
            return
            
        try:
            self._logger.info("Configuring MFLI for dual voltage/current measurement")
            
            # Disable all outputs initially
            self._hardware.set_output_enable(False)
            for osc_idx in range(4):
                self._hardware.set_osc_output_enable(False, osc_idx)
            
            # Disable all demodulators initially
            for demod_idx in range(4):
                self._hardware.set_demod_enable(demod_idx, False)
            
            # Configure Oscillator 0 as main frequency source
            self._hardware.set_frequency(0, 1000.0)  # Default 1 kHz
            
            # Configure Demodulator 0 for voltage measurement
            self._hardware.set_demod_osc(osc_index=0, demod_index=0)  # Connect to osc 0
            self._hardware.set_demod_adc(adc_index=0, demod_index=0)  # Signal input
            self._hardware.set_demod_harmonic(1, demod_index=0)       # Fundamental
            self._hardware.set_phase(0.0, demod_index=0)              # 0° phase
            self._hardware.set_demod_timeconstant(demod_index=0, tau=0.01)  # 10ms
            self._hardware.set_demod_order(demod_index=0, order=4)    # 4th order filter
            self._hardware.set_demod_rate(demod_index=0, rate=1000)   # 1 kHz sampling
            self._hardware.set_demod_sinc_filter(demod_index=0, enable=True)
            
            # Configure Demodulator 1 for current measurement  
            self._hardware.set_demod_osc(osc_index=0, demod_index=1)  # Same osc as voltage
            self._hardware.set_demod_adc(adc_index=1, demod_index=1)  # Current input
            self._hardware.set_demod_harmonic(1, demod_index=1)       # Fundamental
            self._hardware.set_phase(0.0, demod_index=1)              # 0° phase
            self._hardware.set_demod_timeconstant(demod_index=1, tau=0.01)  # 10ms
            self._hardware.set_demod_order(demod_index=1, order=4)    # 4th order filter
            self._hardware.set_demod_rate(demod_index=1, rate=1000)   # 1 kHz sampling
            self._hardware.set_demod_sinc_filter(demod_index=1, enable=True)
            
            # Configure signal input
            self._hardware.set_sigin_enable(True)
            self._hardware.set_sigin_ac_coupling(False)     # DC coupling
            self._hardware.set_sigin_differential(False)    # Single-ended
            self._hardware.set_sigin_float(False)          # Grounded
            self._hardware.set_sigin_impedance("10_MOhm")  # High impedance
            self._hardware.set_sigin_range(1.0)            # 1V range
            
            # Configure current input
            self._hardware.set_currin_enable(True)
            self._hardware.set_currin_float(False)         # Grounded
            self._hardware.set_currin_range(1e-6)          # 1 µA range
            
            # Configure signal output (initially disabled)
            self._hardware.set_amplitude(0.1, osc_index=0)    # 100 mV
            self._hardware.set_dc_offset(0.0)                  # No DC offset
            self._hardware.set_differential_output(False)     # Single-ended
            self._hardware.set_output_range(1.0)               # 1V range
            self._hardware.set_output_auto_range(True)         # Auto-range
            self._hardware.set_output_impedance("high_impedance")  # High-Z output
            
            # IMPORTANT: Enable demodulators LAST after all configuration
            self._logger.info("Enabling demodulators...")
            self._hardware.set_demod_enable(0, True)  # Enable voltage demodulator
            time.sleep(0.1)  # Give time to settle
            self._hardware.set_demod_enable(1, True)  # Enable current demodulator
            time.sleep(0.1)  # Give time to settle
            
            self._logger.info("MFLI configuration complete")
            
        except Exception as e:
            error_msg = f"Configuration failed: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)
            raise
        
        
    # -------------------------------------------------------------------------
    # OSCILLATOR METHODS (OSC 0 only)
    # -------------------------------------------------------------------------
    def set_frequency(self):
        """Set oscillator 0 frequency."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_frequency(0, self.setpoint_frequency)
            self.sig_frequency.emit(self.setpoint_frequency)
            self.sig_is_changing.emit(f"Frequency set to {self.setpoint_frequency} Hz")
        except Exception as e:
            self._logger.error(f"Error setting frequency: {e}")
            self.sig_error.emit(f"Failed to set frequency: {e}")

    def get_frequency(self):
        """Get oscillator 0 frequency."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            freq = self._hardware.get_frequency(0)
            self.sig_frequency.emit(freq)
            return freq
        except Exception as e:
            self._logger.error(f"Error getting frequency: {e}")
            self.sig_error.emit(f"Failed to get frequency: {e}")

    # -------------------------------------------------------------------------
    # OUTPUT METHODS
    # -------------------------------------------------------------------------
    def set_output_enable(self):
        """Enable/disable signal output."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_output_enable(self.setpoint_output_enable)
            # Enable oscillator 0 output if main output is enabled
            self._hardware.set_osc_output_enable(self.setpoint_output_enable, 0)
            self.sig_output_enable.emit(self.setpoint_output_enable)
            status = "enabled" if self.setpoint_output_enable else "disabled"
            self.sig_is_changing.emit(f"Output {status}")
        except Exception as e:
            self._logger.error(f"Error setting output enable: {e}")
            self.sig_error.emit(f"Failed to set output enable: {e}")

    def get_output_enable(self):
        """Get signal output enable status."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            enable = self._hardware.get_output_enable()
            self.sig_output_enable.emit(enable)
            return enable
        except Exception as e:
            self._logger.error(f"Error getting output enable: {e}")
            self.sig_error.emit(f"Failed to get output enable: {e}")

    def set_amplitude(self):
        """Set output amplitude."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_amplitude(self.setpoint_amplitude, 0)
            self.sig_amplitude.emit(self.setpoint_amplitude)
            self.sig_is_changing.emit(f"Amplitude set to {self.setpoint_amplitude} V")
        except Exception as e:
            self._logger.error(f"Error setting amplitude: {e}")
            self.sig_error.emit(f"Failed to set amplitude: {e}")

    def get_amplitude(self):
        """Get output amplitude."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            amp = self._hardware.get_amplitude(0)
            self.sig_amplitude.emit(amp)
            return amp
        except Exception as e:
            self._logger.error(f"Error getting amplitude: {e}")
            self.sig_error.emit(f"Failed to get amplitude: {e}")

    def set_dc_offset(self):
        """Set DC offset."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_dc_offset(self.setpoint_dc_offset)
            self.sig_dc_offset.emit(self.setpoint_dc_offset)
            self.sig_is_changing.emit(f"DC offset set to {self.setpoint_dc_offset} V")
        except Exception as e:
            self._logger.error(f"Error setting DC offset: {e}")
            self.sig_error.emit(f"Failed to set DC offset: {e}")

    def get_dc_offset(self):
        """Get DC offset."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            offset = self._hardware.get_dc_offset()
            self.sig_dc_offset.emit(offset)
            return offset
        except Exception as e:
            self._logger.error(f"Error getting DC offset: {e}")
            self.sig_error.emit(f"Failed to get DC offset: {e}")

    def set_differential_output(self):
        """Set differential output mode."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_differential_output(self.setpoint_differential_output)
            self.sig_differential_output.emit(self.setpoint_differential_output)
            mode = "differential" if self.setpoint_differential_output else "single-ended"
            self.sig_is_changing.emit(f"Output mode: {mode}")
        except Exception as e:
            self._logger.error(f"Error setting differential output: {e}")
            self.sig_error.emit(f"Failed to set differential output: {e}")

    def get_differential_output(self):
        """Get differential output mode."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            diff = self._hardware.get_differential_output()
            self.sig_differential_output.emit(diff)
            return diff
        except Exception as e:
            self._logger.error(f"Error getting differential output: {e}")
            self.sig_error.emit(f"Failed to get differential output: {e}")

    def set_output_range(self):
        """Set output range."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_output_range(self.setpoint_output_range)
            self.sig_output_range.emit(self.setpoint_output_range)
            self.sig_is_changing.emit(f"Output range set to {self.setpoint_output_range} V")
        except Exception as e:
            self._logger.error(f"Error setting output range: {e}")
            self.sig_error.emit(f"Failed to set output range: {e}")

    def get_output_range(self):
        """Get output range."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            range_val = self._hardware.get_output_range()
            self.sig_output_range.emit(range_val)
            return range_val
        except Exception as e:
            self._logger.error(f"Error getting output range: {e}")
            self.sig_error.emit(f"Failed to get output range: {e}")

    def set_output_autorange(self):
        """Set output auto-range."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_output_auto_range(self.setpoint_output_autorange)
            self.sig_output_autorange.emit(self.setpoint_output_autorange)
            status = "enabled" if self.setpoint_output_autorange else "disabled"
            self.sig_is_changing.emit(f"Output auto-range {status}")
        except Exception as e:
            self._logger.error(f"Error setting output auto-range: {e}")
            self.sig_error.emit(f"Failed to set output auto-range: {e}")

    def get_output_autorange(self):
        """Get output auto-range status."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            auto = self._hardware.get_output_auto_range()
            self.sig_output_autorange.emit(auto)
            return auto
        except Exception as e:
            self._logger.error(f"Error getting output auto-range: {e}")
            self.sig_error.emit(f"Failed to get output auto-range: {e}")

    # -------------------------------------------------------------------------
    # DEMODULATOR METHODS
    # -------------------------------------------------------------------------
    def set_voltage_phase(self):
        """Set voltage demodulator (0) phase."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_phase(self.setpoint_voltage_phase, 0)  # FIXED: use set_phase
            self.sig_voltage_phase.emit(self.setpoint_voltage_phase)
            self.sig_is_changing.emit(f"Voltage phase set to {self.setpoint_voltage_phase}°")
        except Exception as e:
            self._logger.error(f"Error setting voltage phase: {e}")
            self.sig_error.emit(f"Failed to set voltage phase: {e}")

    def get_voltage_phase(self):
        """Get voltage demodulator (0) phase."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            phase = self._hardware.get_phase(0)  # FIXED: use get_phase
            self.sig_voltage_phase.emit(phase)
            return phase
        except Exception as e:
            self._logger.error(f"Error getting voltage phase: {e}")
            self.sig_error.emit(f"Failed to get voltage phase: {e}")

    def set_current_phase(self):
        """Set current demodulator (1) phase."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_phase(self.setpoint_current_phase, 1)  # FIXED: use set_phase
            self.sig_current_phase.emit(self.setpoint_current_phase)
            self.sig_is_changing.emit(f"Current phase set to {self.setpoint_current_phase}°")
        except Exception as e:
            self._logger.error(f"Error setting current phase: {e}")
            self.sig_error.emit(f"Failed to set current phase: {e}")

    def get_current_phase(self):
        """Get current demodulator (1) phase."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            phase = self._hardware.get_phase(1)  # FIXED: use get_phase
            self.sig_current_phase.emit(phase)
            return phase
        except Exception as e:
            self._logger.error(f"Error getting current phase: {e}")
            self.sig_error.emit(f"Failed to get current phase: {e}")

    def set_voltage_timeconstant(self):
        """Set voltage demodulator (0) time constant."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_demod_timeconstant(0, self.setpoint_voltage_timeconstant)
            self.sig_voltage_timeconstant.emit(self.setpoint_voltage_timeconstant)
            self.sig_is_changing.emit(f"Voltage time constant set to {self.setpoint_voltage_timeconstant} s")
        except Exception as e:
            self._logger.error(f"Error setting voltage time constant: {e}")
            self.sig_error.emit(f"Failed to set voltage time constant: {e}")

    def get_voltage_timeconstant(self):
        """Get voltage demodulator (0) time constant."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            tau = self._hardware.get_demod_timeconstant(0)
            self.sig_voltage_timeconstant.emit(tau)
            return tau
        except Exception as e:
            self._logger.error(f"Error getting voltage time constant: {e}")
            self.sig_error.emit(f"Failed to get voltage time constant: {e}")

    def set_current_timeconstant(self):
        """Set current demodulator (1) time constant."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_demod_timeconstant(1, self.setpoint_current_timeconstant)
            self.sig_current_timeconstant.emit(self.setpoint_current_timeconstant)
            self.sig_is_changing.emit(f"Current time constant set to {self.setpoint_current_timeconstant} s")
        except Exception as e:
            self._logger.error(f"Error setting current time constant: {e}")
            self.sig_error.emit(f"Failed to set current time constant: {e}")

    def get_current_timeconstant(self):
        """Get current demodulator (1) time constant."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            tau = self._hardware.get_demod_timeconstant(1)
            self.sig_current_timeconstant.emit(tau)
            return tau
        except Exception as e:
            self._logger.error(f"Error getting current time constant: {e}")
            self.sig_error.emit(f"Failed to get current time constant: {e}")

    def set_voltage_demod_enable(self):
        """Enable/disable voltage demodulator (0)."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_demod_enable(0, self.setpoint_voltage_demod_enable)
            self.sig_voltage_demod_enable.emit(self.setpoint_voltage_demod_enable)
            status = "enabled" if self.setpoint_voltage_demod_enable else "disabled"
            self.sig_is_changing.emit(f"Voltage demodulator {status}")
        except Exception as e:
            self._logger.error(f"Error setting voltage demod enable: {e}")
            self.sig_error.emit(f"Failed to set voltage demod enable: {e}")

    def get_voltage_demod_enable(self):
        """Get voltage demodulator (0) enable status."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            enable = self._hardware.get_demod_enable(0)
            self.sig_voltage_demod_enable.emit(enable)
            return enable
        except Exception as e:
            self._logger.error(f"Error getting voltage demod enable: {e}")
            self.sig_error.emit(f"Failed to get voltage demod enable: {e}")

    def set_current_demod_enable(self):
        """Enable/disable current demodulator (1)."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_demod_enable(1, self.setpoint_current_demod_enable)
            self.sig_current_demod_enable.emit(self.setpoint_current_demod_enable)
            status = "enabled" if self.setpoint_current_demod_enable else "disabled"
            self.sig_is_changing.emit(f"Current demodulator {status}")
        except Exception as e:
            self._logger.error(f"Error setting current demod enable: {e}")
            self.sig_error.emit(f"Failed to set current demod enable: {e}")

    def get_current_demod_enable(self):
        """Get current demodulator (1) enable status."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            enable = self._hardware.get_demod_enable(1)
            self.sig_current_demod_enable.emit(enable)
            return enable
        except Exception as e:
            self._logger.error(f"Error getting current demod enable: {e}")
            self.sig_error.emit(f"Failed to get current demod enable: {e}")

    # -------------------------------------------------------------------------
    # DATA ACQUISITION METHODS
    # -------------------------------------------------------------------------
    def get_voltage_sample(self):
        """Get voltage demodulator (0) sample data."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            sample = self._hardware.get_demod_sample(demod_index=0, timeout=0.1, poll_length=0.05)
            self.sig_voltage_sample.emit(sample)
            return sample
        except Exception as e:
            self._logger.error(f"Error getting voltage sample: {e}")
            self.sig_error.emit(f"Failed to get voltage sample: {e}")

    def get_current_sample(self):
        """Get current demodulator (1) sample data."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            sample = self._hardware.get_demod_sample(demod_index=1, timeout=0.1, poll_length=0.05)
            self.sig_current_sample.emit(sample)
            return sample
        except Exception as e:
            self._logger.error(f"Error getting current sample: {e}")
            self.sig_error.emit(f"Failed to get current sample: {e}")

    def get_dual_samples(self):
        """Get both voltage and current samples."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            voltage_sample = self.get_voltage_sample()
            current_sample = self.get_current_sample()
            return {
                'voltage': voltage_sample,
                'current': current_sample
            }
        except Exception as e:
            self._logger.error(f"Error getting dual samples: {e}")
            self.sig_error.emit(f"Failed to get dual samples: {e}")

    # -------------------------------------------------------------------------
    # INPUT CONTROL METHODS
    # -------------------------------------------------------------------------
    def set_sigin_autorange(self):
        """Set signal input auto-range."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_sigin_autorange(self.setpoint_sigin_autorange)
            self.sig_sigin_autorange.emit(self.setpoint_sigin_autorange)
            status = "enabled" if self.setpoint_sigin_autorange else "disabled"
            self.sig_is_changing.emit(f"Signal input auto-range {status}")
        except Exception as e:
            self._logger.error(f"Error setting signal input auto-range: {e}")
            self.sig_error.emit(f"Failed to set signal input auto-range: {e}")

    def set_currin_autorange(self):
        """Set current input auto-range."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            self._hardware.set_currin_autorange(self.setpoint_currin_autorange)
            self.sig_currin_autorange.emit(self.setpoint_currin_autorange)
            status = "enabled" if self.setpoint_currin_autorange else "disabled"
            self.sig_is_changing.emit(f"Current input auto-range {status}")
        except Exception as e:
            self._logger.error(f"Error setting current input auto-range: {e}")
            self.sig_error.emit(f"Failed to set current input auto-range: {e}")

    def get_sigin_range(self):
        """Get signal input range."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            range_val = self._hardware.get_sigin_range()
            self.sig_sigin_range.emit(range_val)
            return range_val
        except Exception as e:
            self._logger.error(f"Error getting signal input range: {e}")
            self.sig_error.emit(f"Failed to get signal input range: {e}")

    def get_currin_range(self):
        """Get current input range."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            range_val = self._hardware.get_currin_range()
            self.sig_currin_range.emit(range_val)
            return range_val
        except Exception as e:
            self._logger.error(f"Error getting current input range: {e}")
            self.sig_error.emit(f"Failed to get current input range: {e}")

    # -------------------------------------------------------------------------
    # DEVICE INFO METHODS
    # -------------------------------------------------------------------------
    def get_clockbase(self):
        """Get device clockbase frequency."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        try:
            clockbase = self._hardware.get_clockbase()
            self.sig_clockbase.emit(clockbase)
            return clockbase
        except Exception as e:
            self._logger.error(f"Error getting clockbase: {e}")
            self.sig_error.emit(f"Failed to get clockbase: {e}")

    # -------------------------------------------------------------------------
    # PRESET METHODS
    # -------------------------------------------------------------------------
    def preset_basic(self):
        """Apply basic preset configuration for voltage/current measurement."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        
        try:
            self.sig_is_changing.emit("Applying basic preset...")
            
            # Set standard parameters
            self.setpoint_frequency = 1000.0  # 1 kHz
            self.setpoint_amplitude = 0.1     # 100 mV
            self.setpoint_dc_offset = 0.0     # No offset
            self.setpoint_voltage_phase = 0.0  # 0° phase
            self.setpoint_current_phase = 0.0  # 0° phase
            self.setpoint_voltage_timeconstant = 0.01  # 10 ms
            self.setpoint_current_timeconstant = 0.01  # 10 ms
            
            # Apply settings
            self.set_frequency()
            time.sleep(0.05)
            self.set_amplitude()
            time.sleep(0.05)
            self.set_dc_offset()
            time.sleep(0.05)
            self.set_voltage_phase()
            time.sleep(0.05)
            self.set_current_phase()
            time.sleep(0.05)
            self.set_voltage_timeconstant()
            time.sleep(0.05)
            self.set_current_timeconstant()
            time.sleep(0.05)
            
            # Enable demodulators
            self.setpoint_voltage_demod_enable = True
            self.setpoint_current_demod_enable = True
            self.set_voltage_demod_enable()
            time.sleep(0.05)
            self.set_current_demod_enable()
            time.sleep(0.05)
            
            # Enable inputs with auto-range
            self.setpoint_sigin_autorange = True
            self.setpoint_currin_autorange = True
            self.set_sigin_autorange()
            time.sleep(0.05)
            self.set_currin_autorange()
            
            self.sig_is_changing.emit("Basic preset applied successfully")
            
        except Exception as e:
            error_msg = f"Preset failed: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)

    def preset_high_sensitivity(self):
        """Apply high sensitivity preset for low-level measurements."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        
        try:
            self.sig_is_changing.emit("Applying high sensitivity preset...")
            
            # High sensitivity parameters
            self.setpoint_frequency = 777.0   # Avoid harmonics
            self.setpoint_amplitude = 0.01    # 10 mV for low perturbation
            self.setpoint_voltage_timeconstant = 0.1   # 100 ms for noise reduction
            self.setpoint_current_timeconstant = 0.1   # 100 ms for noise reduction
            
            # Apply basic preset first
            self.preset_basic()
            time.sleep(0.1)
            
            # Override with high sensitivity settings
            self.set_frequency()
            time.sleep(0.05)
            self.set_amplitude()
            time.sleep(0.05)
            self.set_voltage_timeconstant()
            time.sleep(0.05)
            self.set_current_timeconstant()
            
            self.sig_is_changing.emit("High sensitivity preset applied")
            
        except Exception as e:
            error_msg = f"High sensitivity preset failed: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)

    def preset_fast_measurement(self):
        """Apply fast measurement preset for quick scans."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        
        try:
            self.sig_is_changing.emit("Applying fast measurement preset...")
            
            # Fast measurement parameters
            self.setpoint_frequency = 10000.0  # 10 kHz for fast response
            self.setpoint_amplitude = 0.1      # 100 mV
            self.setpoint_voltage_timeconstant = 0.001  # 1 ms for speed
            self.setpoint_current_timeconstant = 0.001  # 1 ms for speed
            
            # Apply basic preset first
            self.preset_basic()
            time.sleep(0.1)
            
            # Override with fast settings
            self.set_frequency()
            time.sleep(0.05)
            self.set_voltage_timeconstant()
            time.sleep(0.05)
            self.set_current_timeconstant()
            
            self.sig_is_changing.emit("Fast measurement preset applied")
            
        except Exception as e:
            error_msg = f"Fast measurement preset failed: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)

    # -------------------------------------------------------------------------
    # BULK OPERATIONS
    # -------------------------------------------------------------------------
    def get_all(self):
        """Get all important parameter values."""
        try:
            if not self.connected:
                return
            
            # Get device info
            self.get_clockbase()
            time.sleep(0.01)
            
            # Get oscillator settings
            self.get_frequency()
            time.sleep(0.01)
            
            # Get output settings
            self.get_output_enable()
            time.sleep(0.01)
            self.get_amplitude()
            time.sleep(0.01)
            self.get_dc_offset()
            time.sleep(0.01)
            self.get_differential_output()
            time.sleep(0.01)
            self.get_output_range()
            time.sleep(0.01)
            self.get_output_autorange()
            time.sleep(0.01)
            
            # Get demodulator settings
            self.get_voltage_phase()
            time.sleep(0.01)
            self.get_current_phase()
            time.sleep(0.01)
            self.get_voltage_timeconstant()
            time.sleep(0.01)
            self.get_current_timeconstant()
            time.sleep(0.01)
            self.get_voltage_demod_enable()
            time.sleep(0.01)
            self.get_current_demod_enable()
            time.sleep(0.01)
            
            # Get input ranges
            self.get_sigin_range()
            time.sleep(0.01)
            self.get_currin_range()
            
        except Exception as e:
            self._logger.error(f"Error in get_all: {e}")
            self.sig_error.emit(f"Failed to get all parameters: {e}")

    def get_measurements(self):
        """Get both voltage and current measurements."""
        try:
            if not self.connected:
                return
            
            # Get measurement data
            self.get_voltage_sample()
            time.sleep(0.01)
            self.get_current_sample()
            
        except Exception as e:
            self._logger.error(f"Error getting measurements: {e}")
            self.sig_error.emit(f"Failed to get measurements: {e}")
    # Add this method to your MFLI_logic.py file, right after the get_measurements() method:

    def get_demod_sample(self):
        """Get both voltage and current demodulator samples (for monitoring)."""
        try:
            if not self.connected:
                return
            
            # Get both samples
            self.get_voltage_sample()
            time.sleep(0.01)
            self.get_current_sample()
            
        except Exception as e:
            self._logger.error(f"Error getting demod samples: {e}")
            self.sig_error.emit(f"Failed to get demod samples: {e}")
    # -------------------------------------------------------------------------
    # THREAD EXECUTION
    # -------------------------------------------------------------------------
    def run(self):
        """Main thread execution method."""
        if self.reject_signal or not self.connected or self._hardware is None:
            return

        # Execute job if one is queued
        if self.job:
            fn = getattr(self, self.job, None)
            if callable(fn):
                try:
                    fn()
                except Exception as exc:
                    error_msg = f"MFLI job '{self.job}' failed: {exc}"
                    self._logger.error(error_msg)
                    self.sig_error.emit(error_msg)
            else:
                warning_msg = f"Unknown job '{self.job}'"
                self._logger.warning(warning_msg)
                self.sig_warning.emit(warning_msg)

            # Clear job
            self.job = ""

    def stop(self):
        """Stop the thread and reject new signals."""
        self._logger.info("Stopping MFLI logic thread")
        self.reject_signal = True
        self.quit()
        self.wait()
        self.reject_signal = False


    # Add these methods to your MFLI_logic.py for synchronization and testing:

    def sync_with_hardware(self):
        """Synchronize software state with actual hardware settings."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        
        try:
            self.sig_is_changing.emit("Synchronizing with hardware...")
            
            # Read all current hardware settings and update setpoints
            self.setpoint_frequency = self._hardware.get_frequency(0)
            self.setpoint_amplitude = self._hardware.get_amplitude(0)
            self.setpoint_dc_offset = self._hardware.get_dc_offset()
            self.setpoint_output_enable = self._hardware.get_output_enable()
            self.setpoint_differential_output = self._hardware.get_differential_output()
            self.setpoint_output_range = self._hardware.get_output_range()
            self.setpoint_output_autorange = self._hardware.get_output_auto_range()
            
            # Read demodulator settings
            self.setpoint_voltage_phase = self._hardware.get_phase(0)
            self.setpoint_current_phase = self._hardware.get_phase(1)
            self.setpoint_voltage_timeconstant = self._hardware.get_demod_timeconstant(0)
            self.setpoint_current_timeconstant = self._hardware.get_demod_timeconstant(1)
            self.setpoint_voltage_demod_enable = self._hardware.get_demod_enable(0)
            self.setpoint_current_demod_enable = self._hardware.get_demod_enable(1)
            
            # Read input settings
            self.setpoint_sigin_range = self._hardware.get_sigin_range()
            self.setpoint_currin_range = self._hardware.get_currin_range()
            self.setpoint_sigin_autorange = self._hardware.get_sigin_autorange()
            self.setpoint_currin_autorange = self._hardware.get_currin_autorange()
            
            # Emit all current values to update GUI
            self.sig_frequency.emit(self.setpoint_frequency)
            self.sig_amplitude.emit(self.setpoint_amplitude)
            self.sig_dc_offset.emit(self.setpoint_dc_offset)
            self.sig_output_enable.emit(self.setpoint_output_enable)
            self.sig_differential_output.emit(self.setpoint_differential_output)
            self.sig_output_range.emit(self.setpoint_output_range)
            self.sig_output_autorange.emit(self.setpoint_output_autorange)
            self.sig_voltage_phase.emit(self.setpoint_voltage_phase)
            self.sig_current_phase.emit(self.setpoint_current_phase)
            self.sig_voltage_timeconstant.emit(self.setpoint_voltage_timeconstant)
            self.sig_current_timeconstant.emit(self.setpoint_current_timeconstant)
            self.sig_voltage_demod_enable.emit(self.setpoint_voltage_demod_enable)
            self.sig_current_demod_enable.emit(self.setpoint_current_demod_enable)
            
            self.sig_is_changing.emit("Synchronized with hardware")
            self._logger.info("Successfully synchronized with hardware")
            
        except Exception as e:
            error_msg = f"Synchronization failed: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)

    def enable_output_with_oscillator(self):
        """Enable both main output and oscillator 0 output together."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        
        try:
            self.sig_is_changing.emit("Enabling output and oscillator...")
            
            # Set amplitude first (if not already set)
            if self.setpoint_amplitude <= 0:
                self.setpoint_amplitude = 0.1  # Default 100 mV
                self._hardware.set_amplitude(self.setpoint_amplitude, 0)
            
            # Enable oscillator 0 output
            self._hardware.set_osc_output_enable(True, 0)
            
            # Enable main output
            self._hardware.set_output_enable(True)
            
            # Update setpoints
            self.setpoint_output_enable = True
            
            # Emit signals
            self.sig_output_enable.emit(True)
            self.sig_amplitude.emit(self.setpoint_amplitude)
            
            self.sig_is_changing.emit("Output and oscillator enabled")
            self._logger.info("Output and oscillator 0 enabled successfully")
            
        except Exception as e:
            error_msg = f"Failed to enable output: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)

    def disable_output_and_oscillator(self):
        """Disable both main output and oscillator output."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        
        try:
            self.sig_is_changing.emit("Disabling output and oscillator...")
            
            # Disable main output
            self._hardware.set_output_enable(False)
            
            # Disable oscillator 0 output
            self._hardware.set_osc_output_enable(False, 0)
            
            # Update setpoints
            self.setpoint_output_enable = False
            
            # Emit signals
            self.sig_output_enable.emit(False)
            
            self.sig_is_changing.emit("Output and oscillator disabled")
            self._logger.info("Output and oscillator disabled")
            
        except Exception as e:
            error_msg = f"Failed to disable output: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)

    def test_basic_functionality(self):
        """Test basic MFLI functionality to ensure everything works."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        
        try:
            self.sig_is_changing.emit("Testing basic functionality...")
            
            # Test 1: Set and verify frequency
            test_freq = 1234.56
            self._hardware.set_frequency(0, test_freq)
            read_freq = self._hardware.get_frequency(0)
            assert abs(read_freq - test_freq) < 1.0, f"Frequency test failed: set {test_freq}, got {read_freq}"
            
            # Test 2: Set and verify amplitude
            test_amp = 0.05  # 50 mV
            self._hardware.set_amplitude(test_amp, 0)
            read_amp = self._hardware.get_amplitude(0)
            assert abs(read_amp - test_amp) < 0.001, f"Amplitude test failed: set {test_amp}, got {read_amp}"
            
            # Test 3: Test output enable
            self._hardware.set_output_enable(True)
            self._hardware.set_osc_output_enable(True, 0)
            output_enabled = self._hardware.get_output_enable()
            osc_enabled = self._hardware.get_osc_output_enable(0)
            assert output_enabled, "Output enable test failed"
            assert osc_enabled, "Oscillator output enable test failed"
            
            # Test 4: Test demodulator data acquisition
            sample_0 = self._hardware.get_demod_sample(0, timeout=0.5, poll_length=0.1)
            sample_1 = self._hardware.get_demod_sample(1, timeout=0.5, poll_length=0.1)
            assert sample_0 is not None, "Voltage demodulator data acquisition failed"
            assert sample_1 is not None, "Current demodulator data acquisition failed"
            
            # Test 5: Verify data structure
            required_keys = ['x', 'y', 'r', 'phase', 'timestamp']
            for key in required_keys:
                assert key in sample_0, f"Missing key '{key}' in voltage sample"
                assert key in sample_1, f"Missing key '{key}' in current sample"
            
            self.sig_is_changing.emit("✅ All basic functionality tests passed!")
            self._logger.info("Basic functionality test completed successfully")
            
            return {
                'frequency_test': f"✅ {test_freq} Hz → {read_freq:.2f} Hz",
                'amplitude_test': f"✅ {test_amp} V → {read_amp:.3f} V", 
                'output_test': f"✅ Output: {output_enabled}, Osc: {osc_enabled}",
                'data_test': f"✅ Voltage: {sample_0['r']:.6f}V, Current: {sample_1['r']:.6f}A"
            }
            
        except Exception as e:
            error_msg = f"Functionality test failed: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)
            return None

    def get_complete_status(self):
        """Get comprehensive status of all MFLI settings."""
        if not self._hardware:
            raise MFLIHardwareError("Device not connected")
        
        try:
            status = {
                'device_info': {
                    'clockbase': self._hardware.get_clockbase(),
                },
                'oscillator': {
                    'frequency': self._hardware.get_frequency(0),
                },
                'output': {
                    'enabled': self._hardware.get_output_enable(),
                    'osc0_enabled': self._hardware.get_osc_output_enable(0),
                    'amplitude': self._hardware.get_amplitude(0),
                    'dc_offset': self._hardware.get_dc_offset(),
                    'differential': self._hardware.get_differential_output(),
                    'range': self._hardware.get_output_range(),
                    'autorange': self._hardware.get_output_auto_range(),
                },
                'demod_voltage': {
                    'enabled': self._hardware.get_demod_enable(0),
                    'phase': self._hardware.get_phase(0),
                    'timeconstant': self._hardware.get_demod_timeconstant(0),
                    'rate': self._hardware.get_demod_rate(0),
                    'order': self._hardware.get_demod_order(0),
                },
                'demod_current': {
                    'enabled': self._hardware.get_demod_enable(1),
                    'phase': self._hardware.get_phase(1),
                    'timeconstant': self._hardware.get_demod_timeconstant(1),
                    'rate': self._hardware.get_demod_rate(1),
                    'order': self._hardware.get_demod_order(1),
                },
                'inputs': {
                    'sigin_enabled': self._hardware.get_sigin_enable(),
                    'sigin_range': self._hardware.get_sigin_range(),
                    'sigin_autorange': self._hardware.get_sigin_autorange(),
                    'currin_enabled': self._hardware.get_currin_enable(),
                    'currin_range': self._hardware.get_currin_range(),
                    'currin_autorange': self._hardware.get_currin_autorange(),
                }
            }
            
            # Log comprehensive status
            self._logger.info("=== COMPLETE MFLI STATUS ===")
            for section, values in status.items():
                self._logger.info(f"{section.upper()}:")
                for key, value in values.items():
                    self._logger.info(f"  {key}: {value}")
            self._logger.info("=== END STATUS ===")
            
            return status
            
        except Exception as e:
            error_msg = f"Failed to get complete status: {e}"
            self._logger.error(error_msg)
            self.sig_error.emit(error_msg)
            return None

# =============================================================================
# EXAMPLE USAGE
# =============================================================================
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    logic = MFLI_Logic()
    
    # Get available devices
    devices = logic.get_available_devices()
    print(f"Available devices: {devices}")
    
    if devices:
        # Connect to first device
        device_id = devices[0]
        print(f"Connecting to {device_id}")
        
        if logic.connect_device(device_id):
            print("Connected successfully")
            
            # Apply basic preset
            logic.preset_basic()
            
            # Get some measurements
            for i in range(5):
                voltage_sample = logic.get_voltage_sample()
                current_sample = logic.get_current_sample()
                
                if voltage_sample and current_sample:
                    print(f"Measurement {i+1}:")
                    print(f"  Voltage: X={voltage_sample['x']:.6f}V, Y={voltage_sample['y']:.6f}V, R={voltage_sample['r']:.6f}V")
                    print(f"  Current: X={current_sample['x']:.6f}A, Y={current_sample['y']:.6f}A, R={current_sample['r']:.6f}A")
                
                time.sleep(0.1)
            
            # Disconnect
            logic.disconnect_device()
            print("Disconnected")
        else:
            print("Connection failed")
    else:
        print("No devices found")
    
    sys.exit()