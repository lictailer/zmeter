from PyQt6 import QtCore
import time
import logging
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from MFLI_hardware import MFLI_Hardware, MFLIHardwareError


class ParameterType(Enum):
    """Enumeration of supported parameter types"""
    FREQUENCY = "frequency"
    AMPLITUDE = "amplitude"
    PHASE = "phase"


@dataclass
class DeviceState:
    """Data class to hold current device state"""
    connected: bool = False
    output_enable: Optional[bool] = None
    differential_output: Optional[bool] = None
    dc_offset: float = 0.0
    output_autorange: bool = True
    output_range: float = 1.0
    
    # Oscillator states (4 oscillators)
    osc_output_enable: Dict[int, Optional[bool]] = field(default_factory=lambda: {i: None for i in range(4)})
    frequencies: Dict[int, float] = field(default_factory=lambda: {0: 1000, 1: 2000, 2: 3000, 3: 4000})
    amplitudes: Dict[int, float] = field(default_factory=lambda: {i: 1.0 for i in range(4)})
    phases: Dict[int, float] = field(default_factory=lambda: {i: 0.0 for i in range(4)})


class MFLI_Logic(QtCore.QThread):
    """
    Improved Qt thread wrapper for MFLI_Hardware with reduced code duplication
    and better error handling.
    """
    
    # Constants
    NUM_OSCILLATORS = 4
    MAX_CONNECTION_ATTEMPTS = 5
    CONNECTION_RETRY_DELAY = 3
    MONITOR_UPDATE_INTERVAL = 10
    
    # Generic signals - dynamically created
    sig_parameter_updated = QtCore.pyqtSignal(str, int, object)  # param_type, osc_num, value
    sig_osc_enable_updated = QtCore.pyqtSignal(int, object)     # osc_num, enabled
    
    # Basic control signals
    sig_output_enable = QtCore.pyqtSignal(object)
    sig_differential_output = QtCore.pyqtSignal(object)
    sig_dc_offset = QtCore.pyqtSignal(object)
    sig_output_autorange = QtCore.pyqtSignal(object)
    sig_output_range = QtCore.pyqtSignal(object)
    
    # Status signals
    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)
    sig_preset_basic = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Device state management
        self.state = DeviceState()
        self.hardware: Optional[MFLI_Hardware] = None
        
        # Thread control
        self.job: str = ""
        self.reject_signal = False
        self.monitor_count = 0
        
        # Setpoints for parameters
        self.setpoints = self._initialize_setpoints()
        
        # Create dynamic signals for backward compatibility
        self._create_legacy_signals()
        
        # Setup parameter validation
        self._setup_parameter_validation()

    def _initialize_setpoints(self) -> Dict[str, Any]:
        """Initialize setpoint values"""
        setpoints = {
            'output_enable': None,
            'differential_output': None,
            'dc_offset': 0.0,
            'output_autorange': True,
            'output_range': 1.0,
        }
        
        # Add oscillator-specific setpoints
        for i in range(self.NUM_OSCILLATORS):
            setpoints[f'osc{i+1}_output_enable'] = None
            setpoints[f'frequency{i+1}'] = self.state.frequencies[i]
            setpoints[f'amplitude{i+1}'] = self.state.amplitudes[i]
            setpoints[f'phase{i+1}'] = self.state.phases[i]
        
        return setpoints

    def _create_legacy_signals(self):
        """Create individual signals for backward compatibility with existing UI"""
        # Create individual parameter signals
        for param in ['frequency', 'amplitude', 'phase']:
            for i in range(1, self.NUM_OSCILLATORS + 1):
                signal_name = f'sig_{param}{i}'
                signal = QtCore.pyqtSignal(object)
                setattr(self, signal_name, signal)
        
        # Create individual oscillator enable signals
        for i in range(1, self.NUM_OSCILLATORS + 1):
            signal_name = f'sig_osc{i}_output_enable'
            signal = QtCore.pyqtSignal(object)
            setattr(self, signal_name, signal)
        
        # Connect generic signals to specific ones
        self.sig_parameter_updated.connect(self._emit_legacy_parameter_signal)
        self.sig_osc_enable_updated.connect(self._emit_legacy_osc_signal)

    def _emit_legacy_parameter_signal(self, param_type: str, osc_num: int, value):
        """Emit legacy individual parameter signals"""
        signal_name = f'sig_{param_type}{osc_num}'
        if hasattr(self, signal_name):
            getattr(self, signal_name).emit(value)

    def _emit_legacy_osc_signal(self, osc_num: int, value):
        """Emit legacy individual oscillator enable signals"""
        signal_name = f'sig_osc{osc_num}_output_enable'
        if hasattr(self, signal_name):
            getattr(self, signal_name).emit(value)

    def _setup_parameter_validation(self):
        """Setup parameter validation rules"""
        self.validation_rules = {
            ParameterType.FREQUENCY: lambda x: 0 <= x <= 1e9,      # 0 to 1GHz
            ParameterType.AMPLITUDE: lambda x: 0 <= x <= 10,       # 0 to 10V
            ParameterType.PHASE: lambda x: -180 <= x <= 180,       # -180 to 180 degrees
        }

    # ============================================================================
    # Device Connection Management
    # ============================================================================

    def get_available_devices(self):
        """Get list of available MFLI devices"""
        try:
            return MFLI_Hardware.get_available_devices()
        except Exception as e:
            self.logger.error(f"Failed to get available devices: {e}")
            self.sig_is_changing.emit(f"Error: Unable to get available devices. {e}")
            return []

    def connect_device(self, device_id: str) -> bool:
        """Connect to MFLI device with retry mechanism"""
        if self.state.connected:
            self.sig_is_changing.emit(f"Already connected to {device_id}")
            return False

        for attempt in range(1, self.MAX_CONNECTION_ATTEMPTS + 1):
            try:
                self.hardware = MFLI_Hardware(device_id)
                self.state.connected = True
                self.sig_connected.emit(f"connected to {device_id}")
                self.logger.info(f"Connected to {device_id}")
                return True

            except (MFLIHardwareError, Exception) as e:
                error_msg = (
                    f"Attempt {attempt} failed: Unable to connect to {device_id}. Retrying..." 
                    if attempt < self.MAX_CONNECTION_ATTEMPTS else
                    f"Error: Unable to connect to {device_id} after {self.MAX_CONNECTION_ATTEMPTS} attempts."
                )
                
                self.sig_is_changing.emit(error_msg)
                self.logger.error(f"Connection attempt {attempt} failed: {e}")
                
                if attempt < self.MAX_CONNECTION_ATTEMPTS:
                    time.sleep(self.CONNECTION_RETRY_DELAY)

        return False

    def disconnect_device(self):
        """Safely disconnect from device"""
        self.logger.info("Disconnecting from device...")
        
        # Stop thread operations
        self.reject_signal = True
        self.job = ""
        
        if self.isRunning():
            self.wait(5000)  # Wait up to 5 seconds
        
        # Disconnect hardware
        if self.hardware is not None:
            try:
                self.hardware.disconnect()
                self.logger.info("Hardware disconnected successfully")
            except Exception as e:
                self.logger.warning(f"Error during hardware disconnect: {e}")
            finally:
                self.hardware = None
        
        # Update state
        if self.state.connected:
            self.state.connected = False
            self.sig_connected.emit("disconnected")
        
        # Re-enable signals for future connections
        self.reject_signal = False

    # ============================================================================
    # Generic Parameter Management
    # ============================================================================

    def _validate_parameter(self, param_type: ParameterType, value: float) -> bool:
        """Validate parameter value against rules"""
        if param_type in self.validation_rules:
            return self.validation_rules[param_type](value)
        return True

    def _check_hardware_connection(self):
        """Check if hardware is connected, raise exception if not"""
        if self.hardware is None or not self.state.connected:
            raise RuntimeError("Hardware not connected")

    def get_parameter(self, param_type: ParameterType, osc_index: int):
        """Generic method to get any oscillator parameter"""
        self._check_hardware_connection()
        
        try:
            # Map parameter types to hardware methods
            method_map = {
                ParameterType.FREQUENCY: self.hardware.get_frequency,
                ParameterType.AMPLITUDE: self.hardware.get_amplitude,
                ParameterType.PHASE: self.hardware.get_phase,
            }
            
            if param_type not in method_map:
                raise ValueError(f"Unknown parameter type: {param_type}")
            
            # Get value from hardware
            value = method_map[param_type](osc_index)
            
            # Update internal state
            param_name = param_type.value
            if param_name == 'frequency':
                self.state.frequencies[osc_index] = value
            elif param_name == 'amplitude':
                self.state.amplitudes[osc_index] = value
            elif param_name == 'phase':
                self.state.phases[osc_index] = value
            
            # Emit signals
            osc_num = osc_index + 1  # Convert to 1-based numbering for UI
            self.sig_parameter_updated.emit(param_name, osc_num, value)
            
            return value
            
        except (MFLIHardwareError, Exception) as e:
            error_msg = f"Error getting {param_type.value}: {e}"
            self.sig_is_changing.emit(error_msg)
            self.logger.error(error_msg)
            raise

    def set_parameter(self, param_type: ParameterType, osc_index: int, value: float):
        """Generic method to set any oscillator parameter"""
        self._check_hardware_connection()
        
        # Validate parameter
        if not self._validate_parameter(param_type, value):
            raise ValueError(f"Invalid {param_type.value} value: {value}")
        
        try:
            # Map parameter types to hardware methods
            method_map = {
                ParameterType.FREQUENCY: lambda idx, val: self.hardware.set_frequency(idx, val),
                ParameterType.AMPLITUDE: lambda idx, val: self.hardware.set_amplitude(val, idx),
                ParameterType.PHASE: lambda idx, val: self.hardware.set_phase(val, idx),
            }
            
            if param_type not in method_map:
                raise ValueError(f"Unknown parameter type: {param_type}")
            
            # Set value on hardware
            method_map[param_type](osc_index, value)
            
            # Update internal state
            param_name = param_type.value
            if param_name == 'frequency':
                self.state.frequencies[osc_index] = value
            elif param_name == 'amplitude':
                self.state.amplitudes[osc_index] = value
            elif param_name == 'phase':
                self.state.phases[osc_index] = value
            
            # Emit signals
            osc_num = osc_index + 1  # Convert to 1-based numbering for UI
            status_msg = f"{param_name} set to {value} (osc {osc_index})"
            self.sig_is_changing.emit(status_msg)
            self.sig_parameter_updated.emit(param_name, osc_num, value)
            
        except (MFLIHardwareError, Exception) as e:
            error_msg = f"Error setting {param_type.value}: {e}"
            self.sig_is_changing.emit(error_msg)
            self.logger.error(error_msg)
            raise

    # ============================================================================
    # Legacy Method Support (for backward compatibility)
    # ============================================================================

    def _create_legacy_parameter_method(self, param_type: ParameterType, osc_num: int, operation: str):
        """Create legacy parameter methods dynamically"""
        osc_index = osc_num - 1  # Convert to 0-based indexing
        
        if operation == 'get':
            def method():
                return self.get_parameter(param_type, osc_index)
        else:  # set
            def method():
                setpoint_key = f'{param_type.value}{osc_num}'
                value = self.setpoints[setpoint_key]
                self.set_parameter(param_type, osc_index, value)
        
        return method

    def __getattr__(self, name: str):
        """Dynamic method generation for legacy compatibility"""
        # Handle legacy parameter methods: get_frequency1, set_amplitude2, etc.
        for param in ['frequency', 'amplitude', 'phase']:
            for i in range(1, self.NUM_OSCILLATORS + 1):
                if name == f'get_{param}{i}':
                    param_type = ParameterType(param)
                    return lambda: self.get_parameter(param_type, i-1)
                elif name == f'set_{param}{i}':
                    param_type = ParameterType(param)
                    def method(p_type=param_type, osc_idx=i-1, param_name=param, osc_num=i):
                        value = self.setpoints[f'{param_name}{osc_num}']
                        self.set_parameter(p_type, osc_idx, value)
                    return method
        
        # Handle legacy oscillator enable methods
        for i in range(1, self.NUM_OSCILLATORS + 1):
            if name == f'get_osc{i}_output_enable':
                return lambda osc_idx=i-1: self.get_osc_output_enable(osc_idx)
            elif name == f'set_osc{i}_output_enable':
                def method(osc_idx=i-1, osc_num=i):
                    enable = self.setpoints[f'osc{osc_num}_output_enable']
                    self.set_osc_output_enable(osc_idx, enable)
                return method
        
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    # ============================================================================
    # Oscillator Enable Control
    # ============================================================================

    def get_osc_output_enable(self, osc_index: int):
        """Get oscillator output enable state"""
        self._check_hardware_connection()
        
        try:
            value = self.hardware.get_osc_output_enable(osc_index)
            self.state.osc_output_enable[osc_index] = value
            
            # Emit signals
            osc_num = osc_index + 1
            self.sig_osc_enable_updated.emit(osc_num, value)
            
            return value
            
        except (MFLIHardwareError, Exception) as e:
            error_msg = f"Error getting osc{osc_index+1} output enable: {e}"
            self.sig_is_changing.emit(error_msg)
            self.logger.error(error_msg)
            raise

    def set_osc_output_enable(self, osc_index: int, enable: bool):
        """Set oscillator output enable state"""
        self._check_hardware_connection()
        
        try:
            self.hardware.set_osc_output_enable(enable, osc_index)
            self.state.osc_output_enable[osc_index] = enable
            
            # Emit signals
            osc_num = osc_index + 1
            status_msg = f"osc{osc_num} output enable set to {enable}"
            self.sig_is_changing.emit(status_msg)
            self.sig_osc_enable_updated.emit(osc_num, enable)
            
        except (MFLIHardwareError, Exception) as e:
            error_msg = f"Error setting osc{osc_index+1} output enable: {e}"
            self.sig_is_changing.emit(error_msg)
            self.logger.error(error_msg)
            raise

    # ============================================================================
    # Basic Control Methods
    # ============================================================================

    def get_output_enable(self):
        """Get main output enable state"""
        self._check_hardware_connection()
        try:
            value = self.hardware.get_output_enable()
            self.state.output_enable = value
            self.sig_output_enable.emit(value)
            return value
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting output enable: {e}")
            raise

    def set_output_enable(self):
        """Set main output enable state"""
        self._check_hardware_connection()
        try:
            enable = self.setpoints['output_enable']
            self.hardware.set_output_enable(enable)
            self.state.output_enable = enable
            self.sig_is_changing.emit(f"enable set to {enable}")
            self.sig_output_enable.emit(enable)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting output enable: {e}")
            raise

    def get_differential_output(self):
        """Get differential output state"""
        self._check_hardware_connection()
        try:
            value = self.hardware.get_differential_output()
            self.state.differential_output = value
            self.sig_differential_output.emit(value)
            return value
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting differential output: {e}")
            raise

    def set_differential_output(self):
        """Set differential output state"""
        self._check_hardware_connection()
        try:
            enable = self.setpoints['differential_output']
            self.hardware.set_differential_output(enable)
            self.state.differential_output = enable
            self.sig_is_changing.emit(f"differential output set to {enable}")
            self.sig_differential_output.emit(enable)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting differential output: {e}")
            raise

    def get_dc_offset(self):
        """Get DC offset value"""
        self._check_hardware_connection()
        try:
            value = self.hardware.get_dc_offset()
            self.state.dc_offset = value
            self.sig_dc_offset.emit(value)
            return value
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting dc offset: {e}")
            raise

    def set_dc_offset(self):
        """Set DC offset value"""
        self._check_hardware_connection()
        try:
            offset = self.setpoints['dc_offset']
            self.hardware.set_dc_offset(offset)
            self.state.dc_offset = offset
            self.sig_is_changing.emit(f"dc offset set to {offset}")
            self.sig_dc_offset.emit(offset)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting dc offset: {e}")
            raise

    def get_output_autorange(self):
        """Get output autorange state"""
        self._check_hardware_connection()
        try:
            value = self.hardware.get_output_auto_range()
            self.state.output_autorange = value
            self.sig_output_autorange.emit(value)
            return value
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting output autorange: {e}")
            raise

    def set_output_autorange(self):
        """Set output autorange state"""
        self._check_hardware_connection()
        try:
            autorange = self.setpoints['output_autorange']
            self.hardware.set_output_auto_range(autorange)
            self.state.output_autorange = autorange
            self.sig_is_changing.emit(f"output autorange set to {autorange}")
            self.sig_output_autorange.emit(autorange)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting output autorange: {e}")
            raise

    def get_output_range(self):
        """Get output range value"""
        self._check_hardware_connection()
        try:
            value = self.hardware.get_output_range()
            self.state.output_range = value
            self.sig_output_range.emit(value)
            return value
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting output range: {e}")
            raise

    def set_output_range(self):
        """Set output range value"""
        self._check_hardware_connection()
        try:
            range_val = self.setpoints['output_range']
            self.hardware.set_output_range(range_val)
            self.state.output_range = range_val
            self.sig_is_changing.emit(f"output range set to {range_val}")
            self.sig_output_range.emit(range_val)
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error setting output range: {e}")
            raise

    # ============================================================================
    # Additional Hardware Methods
    # ============================================================================

    def get_demod_sample(self):
        """Get demodulator sample"""
        self._check_hardware_connection()
        try:
            return self.hardware.get_demod_sample()
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting demod sample: {e}")
            raise

    def get_X(self):
        """Get X component"""
        self._check_hardware_connection()
        try:
            return self.hardware.get_X()
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting X: {e}")
            raise

    def get_Y(self):
        """Get Y component"""
        self._check_hardware_connection()
        try:
            return self.hardware.get_Y()
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting Y: {e}")
            raise

    def get_R(self):
        """Get R component"""
        self._check_hardware_connection()
        try:
            return self.hardware.get_R()
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error getting R: {e}")
            raise

    def setup_basic(self, freq=10e3, amp=0.5, out_range=1.0, demod_rate=1000, tau=0.01, order=1):
        """Setup basic device configuration"""
        self._check_hardware_connection()
        try:
            self.hardware.setup_basic(freq, amp, out_range, demod_rate, tau, order)
            self.sig_is_changing.emit(f"Basic setup complete: freq={freq}, amp={amp}, range={out_range}")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error during basic setup: {e}")
            raise

    def sync(self):
        """Synchronize settings with device"""
        self._check_hardware_connection()
        try:
            self.hardware.sync()
            self.sig_is_changing.emit("Settings synchronized with device")
        except (MFLIHardwareError, Exception) as e:
            self.sig_is_changing.emit(f"Error syncing: {e}")
            raise

    def preset_basic(self):
        """Apply basic preset configuration"""
        try:
            self.setup_basic(freq=1e3, amp=0, tau=0.01, order=3)
            self.sig_is_changing.emit("Preset complete")
            self.sig_preset_basic.emit(True)
        except Exception as e:
            self.sig_is_changing.emit(f"Preset failed: {e}")
            raise

    # ============================================================================
    # Monitoring and Thread Control
    # ============================================================================

    def get_all(self):
        """Get all parameter values (called periodically by monitor)"""
        if not self.state.connected:
            return
        
        self.monitor_count += 1
        if self.monitor_count >= self.MONITOR_UPDATE_INTERVAL:
            try:
                # Get basic controls
                self.get_output_enable()
                self.get_differential_output()
                self.get_dc_offset()
                self.get_output_autorange()
                self.get_output_range()
                
                # Get oscillator states
                for i in range(self.NUM_OSCILLATORS):
                    self.get_osc_output_enable(i)
                    self.get_parameter(ParameterType.FREQUENCY, i)
                    self.get_parameter(ParameterType.AMPLITUDE, i)
                    self.get_parameter(ParameterType.PHASE, i)
                
                self.monitor_count = 0
                
            except Exception as e:
                self.logger.error(f"Error in get_all: {e}")
        
        time.sleep(0.05)

    def run(self):
        """Main thread execution method"""
        if self.reject_signal or not self.state.connected or self.hardware is None:
            return

        # Generic job dispatcher
        if self.job:
            try:
                method = getattr(self, self.job, None)
                if callable(method):
                    method()
                else:
                    self.logger.warning(f"Unknown job: {self.job}")
            except Exception as e:
                self.logger.error(f"Job '{self.job}' failed: {e}")
            finally:
                self.job = ""

    def stop(self):
        """Stop thread execution"""
        self.reject_signal = True
        self.quit()
        self.wait(3000)  # Wait up to 3 seconds
        self.reject_signal = False

    # ============================================================================
    # Setpoint Management (for backward compatibility)
    # ============================================================================

    def __setattr__(self, name: str, value: Any):
        """Handle setpoint assignments dynamically"""
        if name.startswith('setpoint_'):
            if not hasattr(self, 'setpoints'):
                super().__setattr__(name, value)
            else:
                setpoint_key = name[10:]  # Remove 'setpoint_' prefix
                self.setpoints[setpoint_key] = value
        else:
            super().__setattr__(name, value)

    def __getattr__(self, name: str):
        """Handle setpoint access dynamically"""
        if name.startswith('setpoint_'):
            setpoint_key = name[10:]  # Remove 'setpoint_' prefix
            if hasattr(self, 'setpoints') and setpoint_key in self.setpoints:
                return self.setpoints[setpoint_key]
        
        # Call the method generation logic from earlier __getattr__
        return super().__getattribute__(name)