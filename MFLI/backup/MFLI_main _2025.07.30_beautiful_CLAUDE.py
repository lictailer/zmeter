from PyQt6 import QtWidgets, QtCore
from PyQt6.uic.load_ui import loadUi
import sys
import time
import numpy as np
import pyqtgraph as pg
from typing import Dict, Any, Optional, Callable
import logging

from MFLI_logic import MFLI_Logic


class MFLIController:
    """Controller to handle UI-device interactions and reduce coupling"""
    def __init__(self, ui_widget, logic):
        self.ui = ui_widget
        self.logic = logic
    
    def safe_logic_operation(self, job: str, setpoint_updates = None):
        """Safely execute logic operations with proper threading"""
        try:
            if self.logic.isRunning():
                self.logic.wait(1000)  # Wait up to 1 second for completion
            
            if setpoint_updates:
                for attr, value in setpoint_updates.items():
                    setattr(self.logic, attr, value)
            
            self.logic.job = job
            self.logic.start()
            
        except Exception as e:
            logging.error(f"Logic operation failed: {e}")
            self.ui.show_error("Operation failed", str(e))


class MFLI(QtWidgets.QWidget):
    """Qt GUI wrapper for MFLI lock-in amplifier"""

    # Constants
    TIMER_INTERVAL = 50
    PARAMETERS = ['frequency', 'amplitude', 'phase']
    OSCILLATORS = [1, 2, 3, 4]
    # Signals
    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        
        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
        
        self._initialize_ui()
        self._initialize_logic()
        self._setup_connections()
        self._setup_timer()
        self._create_dynamic_methods()

    def _initialize_ui(self):
        """Initialize the UI components"""
        try:
            loadUi("MFLI/MFLI.ui", self)
        except Exception as e:
            self.show_error("UI Loading Error", f"Failed to load UI file: {str(e)}")
            raise

    def _initialize_logic(self):
        """Initialize the logic layer and controller"""
        self.logic = MFLI_Logic()
        self.controller = MFLIController(self, self.logic)
        
        # Populate available devices
        try:
            devices = self.logic.get_available_devices()
            self.address_comboBox.addItems(devices) #type: ignore
        except Exception as e:
            self.logger.error(f"Failed to get available devices: {e}")

    def _setup_connections(self):
        """Setup all signal-slot connections"""
        # Device connection
        self.connect_pushButton.clicked.connect(self.connect_device) #type: ignore
        self.disconnect_pushButton.clicked.connect(self.disconnect_device) #type: ignore
        
        # Basic output controls
        self.output_enable_checkBox.stateChanged.connect(self.set_output_enable) #type: ignore
        self.differential_output_checkBox.stateChanged.connect(self.set_differential_output) #type: ignore
        self.dc_offset_spinBox.editingFinished.connect(self.set_dc_offset) #type: ignore
        self.preset_pushButton.clicked.connect(self.preset) #type: ignore
        
        # Output range controls
        self.output_autorange_checkBox.stateChanged.connect(self.set_output_autorange) #type: ignore
        self.output_range_comboBox.currentTextChanged.connect(self.set_output_range) #type: ignore
        
        # Dynamic connections for oscillators and parameters
        self._setup_dynamic_connections()
        
        # Logic signals
        self._setup_logic_connections()

    def _setup_dynamic_connections(self):
        """Setup connections for oscillators and parameters dynamically"""
        # Oscillator enable checkboxes
        for i in self.OSCILLATORS:
            checkbox = getattr(self, f'osc{i}_output_enable_checkBox') #type: ignore
            checkbox.stateChanged.connect(lambda state, osc=i: self.set_osc_output_enable(osc, state)) #type: ignore
        
        # Parameter spin boxes
        for param in self.PARAMETERS:
            for i in self.OSCILLATORS:
                spinbox = getattr(self, f'{param}{i}_spinBox') #type: ignore
                spinbox.editingFinished.connect(lambda p=param, num=i: self.set_parameter(p, num)) #type: ignore
                
                # Disable keyboard tracking for smoother performance
                if hasattr(spinbox, 'setKeyboardTracking'): #type: ignore
                    spinbox.setKeyboardTracking(False) #type: ignore

    def _setup_logic_connections(self):
        """Setup connections to logic layer signals"""
        signal_mappings = {
            'sig_is_changing': self.update_status,
            'sig_connected': self.update_status,
            'sig_output_enable': self.update_output_enable,
            'sig_differential_output': self.update_differential_output,
            'sig_dc_offset': self.update_dc_offset,
            'sig_preset_basic': self.preset,
            'sig_output_autorange': self.update_output_autorange,
            'sig_output_range': self.update_output_range,
        }
        
        for signal_name, slot in signal_mappings.items():
            if hasattr(self.logic, signal_name):
                getattr(self.logic, signal_name).connect(slot)
        
        # Dynamic signal connections
        for i in self.OSCILLATORS:
            osc_signal = f'sig_osc{i}_output_enable'
            if hasattr(self.logic, osc_signal):
                getattr(self.logic, osc_signal).connect(
                    lambda state, osc=i: self.update_osc_output_enable(osc, state)
                )
        
        for param in self.PARAMETERS:
            for i in self.OSCILLATORS:
                signal_name = f'sig_{param}{i}'
                if hasattr(self.logic, signal_name):
                    getattr(self.logic, signal_name).connect(
                        lambda value, p=param, num=i: self.update_parameter(p, num, value)
                    )

    def _setup_timer(self):
        """Setup the monitoring timer"""
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.monitor)
        self.timer.start(self.TIMER_INTERVAL)
        self.stop_signal.connect(self.stop_timer)

    def _create_dynamic_methods(self):
        """Create methods dynamically for repetitive operations"""
        # This would be expanded to create get/set methods programmatically
        # For now, keeping the essential methods manually defined
        pass

    # ============================================================================
    # Utility Methods
    # ============================================================================
    
    def show_error(self, title: str, message: str):
        """Show error message to user"""
        QtWidgets.QMessageBox.critical(self, title, message)
    
    def show_info(self, title: str, message: str):
        """Show info message to user"""
        QtWidgets.QMessageBox.information(self, title, message)
    
    def _safely_update_widget(self, widget, value, converter: Optional[Callable] = None):
        """Safely update widget value without triggering signals"""
        widget.blockSignals(True)
        try:
            if converter:
                value = converter(value)
            
            if hasattr(widget, 'setValue'):
                widget.setValue(value)
            elif hasattr(widget, 'setChecked'):
                widget.setChecked(bool(value))
            elif hasattr(widget, 'setCurrentText'):
                widget.setCurrentText(str(value))
        except Exception as e:
            self.logger.error(f"Failed to update widget: {e}")
        finally:
            widget.blockSignals(False)
    
    def _is_widget_focused(self, widget) -> bool:
        """Check if widget's line edit has focus"""
        return hasattr(widget, 'lineEdit') and widget.lineEdit().hasFocus()
    
    def _validate_parameter(self, param: str, value: float) -> bool:
        """Validate parameter values"""
        validation_rules = {
            'frequency': lambda x: 0 <= x <= 5e5,  # 0 to 500kHz
            'amplitude': lambda x: 0 <= x <= 10,   # 0 to 10V
            'phase': lambda x: -180 <= x <= 180,   # -180 to 180 degrees
        }
        
        if param in validation_rules:
            return validation_rules[param](value)
        return True

    # ============================================================================
    # Timer and Monitoring
    # ============================================================================
    
    def stop_timer(self):
        """Stop the monitoring timer"""
        if self.timer.isActive():
            self.timer.stop()
    
    def start_timer(self):
        """Start the monitoring timer"""
        if not self.timer.isActive():
            self.timer.start(self.TIMER_INTERVAL)
    
    def monitor(self):
        """Monitor device status periodically"""
        if not self.logic.connected:
            self.update_status("Device not connected")
            return
        
        '''if self.logic.isRunning():
            self.update_status("Operation in progress...")
            return
        '''
        try:
            self.controller.safe_logic_operation("get_all")
        except Exception as e:
            self.logger.error(f"Monitor operation failed: {e}")

    # ============================================================================
    # Device Connection
    # ============================================================================
    
    def connect_device(self, addr: Optional[str] = None):
        """Connect to MFLI device with error handling"""
        try:
            if addr is None or addr is False:
                addr = self.address_comboBox.currentText() #type: ignore
            
            if not addr:
                self.show_error("Connection Error", "Please select a device address")
                return
            
            self.logger.info(f"Connecting to {addr}")
            self.logic.connect_device(device_id=addr)
            self.address_comboBox.setCurrentText(addr) #type: ignore
            
        except Exception as e:
            self.logger.error(f"Connection failed: {e}")
            self.show_error("Connection Error", f"Failed to connect to {addr}: {str(e)}")

    def disconnect_device(self):
        """Disconnect from MFLI device"""
        try:
            self.logic.disconnect_device()
            self.update_status("Disconnected")
        except Exception as e:
            self.logger.error(f"Disconnection failed: {e}")
            self.show_error("Disconnection Error", f"Failed to disconnect: {str(e)}")

    # ============================================================================
    # Generic Parameter Methods
    # ============================================================================
    
    def set_parameter(self, param: str, osc_num: int):
        """Generic method to set oscillator parameters"""
        try:
            spinbox = getattr(self, f'{param}{osc_num}_spinBox')
            value = spinbox.value()
            
            if not self._validate_parameter(param, value):
                self.show_error("Invalid Value", f"Invalid {param} value: {value}")
                return
            
            setpoint_attr = f'setpoint_{param}{osc_num}'
            job = f'set_{param}{osc_num}'
            
            self.controller.safe_logic_operation(job, {setpoint_attr: value})
            
        except AttributeError as e:
            self.logger.error(f"Parameter setting failed: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in set_parameter: {e}")
    
    def update_parameter(self, param: str, osc_num: int, value: float):
        """Generic method to update parameter display"""
        try:
            spinbox = getattr(self, f'{param}{osc_num}_spinBox')
            
            if self._is_widget_focused(spinbox):
                return  # Don't update if user is editing
            
            self._safely_update_widget(spinbox, value, float)
            
        except AttributeError as e:
            self.logger.error(f"Parameter update failed: {e}")

    # ============================================================================
    # Oscillator Control Methods
    # ============================================================================
    
    def set_osc_output_enable(self, osc_num: int, state: Optional[bool] = None):
        """Generic method to set oscillator output enable"""
        try:
            checkbox = getattr(self, f'osc{osc_num}_output_enable_checkBox')
            val = bool(state) if state is not None else checkbox.isChecked()
            
            setpoint_attr = f'setpoint_osc{osc_num}_output_enable'
            job = f'set_osc{osc_num}_output_enable'
            
            self.controller.safe_logic_operation(job, {setpoint_attr: val})
            
        except AttributeError as e:
            self.logger.error(f"Oscillator control failed: {e}")
    
    def update_osc_output_enable(self, osc_num: int, state: bool):
        """Generic method to update oscillator enable display"""
        try:
            checkbox = getattr(self, f'osc{osc_num}_output_enable_checkBox')
            self._safely_update_widget(checkbox, state)
        except AttributeError as e:
            self.logger.error(f"Oscillator update failed: {e}")

    # ============================================================================
    # Basic Control Methods
    # ============================================================================
    
    def update_status(self, txt: str):
        """Update status label"""
        self.status_label.setText(str(txt)) #type: ignore

    def set_output_enable(self, state: Optional[bool] = None):
        """Set main output enable"""
        val = bool(state) if state is not None else self.output_enable_checkBox.isChecked() #type: ignore
        self.controller.safe_logic_operation('set_output_enable', {'setpoint_output_enable': val})
    
    def update_output_enable(self, state: bool):
        """Update output enable display"""
        self._safely_update_widget(self.output_enable_checkBox, state) #type: ignore

    def set_differential_output(self, state: Optional[bool] = None):
        """Set differential output mode"""
        val = bool(state) if state is not None else self.differential_output_checkBox.isChecked() #type: ignore
        self.controller.safe_logic_operation('set_differential_output', {'setpoint_differential_output': val})
    
    def update_differential_output(self, state: bool):
        """Update differential output display"""
        self._safely_update_widget(self.differential_output_checkBox, state) #type: ignore

    def set_dc_offset(self):
        """Set DC offset"""
        value = self.dc_offset_spinBox.value() #type: ignore
        self.controller.safe_logic_operation('set_dc_offset', {'setpoint_dc_offset': value})
    
    def update_dc_offset(self, offset: float):
        """Update DC offset display"""
        if self._is_widget_focused(self.dc_offset_spinBox): #type: ignore
            return
        self._safely_update_widget(self.dc_offset_spinBox, offset, float) #type: ignore

    def set_output_autorange(self, state: Optional[bool] = None):
        """Set output autorange"""
        val = bool(state) if state is not None else self.output_autorange_checkBox.isChecked() #type: ignore
        self.controller.safe_logic_operation('set_output_autorange', {'setpoint_output_autorange': val})
        
        # Enable/disable range combo box based on autorange state
        self.output_range_comboBox.setEnabled(not val) #type: ignore
        
        if val:
            # Update range display when autorange is enabled
            try:
                current_range = self.logic.get_output_range()
                self.update_output_range_combobox(current_range)
            except Exception as e:
                self.logger.error(f"Failed to update range: {e}")
    
    def update_output_autorange(self, state: bool):
        """Update output autorange display"""
        self._safely_update_widget(self.output_autorange_checkBox, state) #type: ignore

    def set_output_range(self):
        """Set output range"""
        range_value = self.output_range_comboBox.currentText() #type: ignore
        self.controller.safe_logic_operation('set_output_range', {'setpoint_output_range': range_value})
    
    def update_output_range(self, range_val: str):
        """Update output range display"""
        self._safely_update_widget(self.output_range_comboBox, range_val) #type: ignore
    
    def update_output_range_combobox(self, range_val: float):
        """Update output range combobox index based on range value"""
        try:
            index = int(2 + np.log10(float(range_val)))
            self.output_range_comboBox.setCurrentIndex(index) #type: ignore
        except (ValueError, OverflowError) as e:
            self.logger.error(f"Invalid range value for combobox: {e}")

    def preset(self):
        """Apply basic preset configuration"""
        self.controller.safe_logic_operation('preset_basic')

    # ============================================================================
    # Cleanup and Event Handling
    # ============================================================================
    
    def closeEvent(self, a0):
        """Properly cleanup resources on close"""
        self.logger.info("Closing MFLI application...")
        
        try:
            # Stop timer
            if hasattr(self, 'timer'):
                self.timer.stop()
            
            # Stop logic thread safely
            if hasattr(self, 'logic') and self.logic.isRunning():
                self.logic.terminate()
                if not self.logic.wait(3000):  # Wait up to 3 seconds
                    self.logger.warning("Logic thread did not terminate gracefully")
            
            # Disconnect device
            if hasattr(self, 'logic'):
                self.logic.disconnect_device()
            
            self.logger.info("MFLI closed successfully")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
        finally:
            a0.accept() #type: ignore


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    
    try:
        window = MFLI()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        logging.error(f"Application failed to start: {e}")
        sys.exit(1)