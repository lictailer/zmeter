from PyQt6 import QtWidgets, QtCore
from PyQt6.uic.load_ui import loadUi
import sys
import time
import numpy as np
import pyqtgraph as pg
from typing import Dict, Any, Optional, Callable
import logging

from .MFLI_logic import MFLI_Logic

"""
function that need to be added:
    recommendation to disable sinc filter if frequency is above 100Hz
    Monitor of all overranges
    Pause data acquisition if input overrange
    add a button to reset the demodulator parameters to default
    add another osc field with RMS value
    change time constant units to ms
    add input range combobox
    update phase spinbox when auto_phase is pressed
"""



class MFLIController:
    """Controller to handle UI-device interactions and reduce coupling"""
    def __init__(self, ui_widget, logic):
        self.ui = ui_widget
        self.logic = logic
    
    def safe_logic_operation(self, job: str, setpoint_updates: Optional[Dict[str, Any]] = None):
        """Safely execute logic operations with proper threading"""
        try:
            if self.logic.isRunning():
                self.logic.wait(2000)  # Wait up to 2 seconds for completion
            
            if setpoint_updates:
                for attr, value in setpoint_updates.items():
                    setattr(self.logic, attr, value)
            
            self.logic.job = job
            self.logic.start()
            
        except Exception as e:
            self.logger.error(f"Logic operation failed: {e}")
            self.ui.show_error("Operation failed", str(e))

class MFLI(QtWidgets.QWidget):
    """Qt GUI wrapper for MFLI lock-in amplifier"""


    WidgetRules: dict[str, tuple[str, Callable[[QtWidgets.QWidget], Any]]] = {  #type: ignore
        # Spin boxes emit no args on editingFinished; we call .value()
        'spinBox':       ("editingFinished", lambda w: w.value()),
        'doubleSpinBox': ("editingFinished", lambda w: w.value()),
        # Combo box: use currentIndex() if you want an int, or currentText() for string
        'comboBox':      ("currentIndexChanged", lambda w: w.currentIndex()),
        # Check box: stateChanged emits int (0/2), we convert to bool
        'checkBox':      ("stateChanged", lambda w: w.isChecked()),
        # Push button: clicked emits bool (checked), usually we just treat it as a command
        'pushButton':    ("clicked", lambda w: True)
        }


    # Constants
    TIMER_INTERVAL = 50
    OSC_PARAMETERS = ['frequency', 'amplitude', 'phase']
    OSCILLATORS = [1] #later will be increased to [1, 2, 3, 4]

    DEMODS = [1, 2] #later will be increased to [1, 2, 3, 4]
    """Demod 1 is reserved for current measurement, 
    Demod 2 is reserved for voltage measurement"""

    DEMOD_PARAMETERS = ['auto_range', 'harmonic', 'phase', 'auto_phase','zero_phase','sinc_filter', 'time_constant', 'filter_order'] # 'adc', 'rate', 'osc', 'enable'
    
    DEMOD_WIDGET_TYPES = {
    'harmonic': 'spinBox',
    'phase': 'doubleSpinBox', 
    'time_constant': 'doubleSpinBox',
    'auto_range': 'pushButton',
    'zero_phase': 'pushButton',
    'auto_phase': 'pushButton',
    'filter_order': 'comboBox',
    'sinc_filter': 'checkBox'
    }
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
        #self._create_dynamic_methods() #will be used later
        
    def _initialize_ui(self):
        """Initialize the UI components"""
        try:
            loadUi("MFLI/MFLI.ui", self)
            self._add_plot()
            self._initialize_plot_buffers()
        except Exception as e:
            self.show_error("UI Loading Error", f"Failed to load UI file: {str(e)}")
            raise

    def _initialize_logic(self):
        """Initialize the logic layer and controller"""
        self.logic = MFLI_Logic()
        self.controller = MFLIController(self, self.logic)

        self.get_methods = [method for method in dir(self.logic) if callable(getattr(self.logic, method)) and method.startswith("get_")]
        self.set_methods = [
            method
            for method in dir(self.logic)
            if callable(getattr(self.logic, method)) and method.startswith("set_")
        ]
        print("get_methods")
        print(self.get_methods)
        print(self.set_methods)
        
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
        self.stop_acquisition_button.clicked.connect(self.stop_timer)
        self.start_acquisition_button.clicked.connect(self.start_timer)

        # Basic output controls
        #self.output_enable_checkBox.stateChanged.connect(self.set_output_enable) #type: ignore
        self.differential_output_checkBox.stateChanged.connect(self.set_differential_output) #type: ignore
        self.dc_offset_spinBox.editingFinished.connect(self.set_dc_offset) #type: ignore
        self.preset_pushButton.clicked.connect(self.preset) #type: ignore
        
        # Output range controls
        self.output_autorange_checkBox.stateChanged.connect(self.set_output_autorange) #type: ignore
        self.output_range_comboBox.currentTextChanged.connect(self.set_output_range) #type: ignore
        #self.filter_order_1_comboBox.currentIndexChanged.connect(self.set_filter_order_1) #type: ignore
        
        # Dynamic connections for oscillators and parameters
        self._setup_dynamic_osc_connections()
        
        # Logic signals
        self._setup_logic_connections()
        self._setup_dynamic_demod_connections()
        #self.filter_order_1_comboBox.currentIndexChanged.connect(lambda value: self.set_filter_order(1, value))
    def _setup_dynamic_osc_connections(self):
        """Setup connections for oscillators and parameters dynamically"""
        # Oscillator enable checkboxes
        for i in self.OSCILLATORS:
            checkbox = getattr(self, f'osc{i}_output_enable_checkBox') #type: ignore
            checkbox.stateChanged.connect(lambda state, osc=i: self.set_osc_output_enable(osc, state)) #type: ignore
        
        # Parameter spin boxes
        for param in self.OSC_PARAMETERS:
            for i in self.OSCILLATORS:
                spinbox = getattr(self, f'{param}{i}_spinBox') #type: ignore
                spinbox.editingFinished.connect(lambda p=param, num=i: self.set_parameter(p, num)) #type: ignore
                
                # Disable keyboard tracking for smoother performance
                if hasattr(spinbox, 'setKeyboardTracking'): #type: ignore
                    spinbox.setKeyboardTracking(False) #type: ignore
    
    def _setup_dynamic_demod_connections(self):
        # Add demodulator connections
        for param in self.DEMOD_PARAMETERS:
            for demod_num in self.DEMODS:
                if param in ['auto_range', 'auto_phase', 'zero_phase']:
                    getattr(self, f"{param}_{demod_num}_pushButton").clicked.connect(getattr(self, f"set_{param}_{demod_num}")) #type: ignore
                else: #param in ['phase','sinc_filter', 'time_constant', 'filter_order']'
                    widget_type = self.DEMOD_WIDGET_TYPES[param]        #'comboBox'
                    widget_name = f'{param}_{demod_num}_{widget_type}'  #'filter_order_1_comboBox'
                    widget = getattr(self, widget_name)                 #self.filter_order_1_comboBox
                    signal_name, getter = self.WidgetRules[widget_type] #('currentIndexChanged', lambda w: w.currentIndex())
                    signal = getattr(widget, signal_name)              #self.filter_order_1_comboBox.currentIndexChanged
                    
                    function_to_call = getattr(self, f"set_{param}_{demod_num}")  #self.set_filter_order_1
                    signal.connect(lambda *args, f=function_to_call, g=getter, w=widget: f(g(w)))  #self.filter_order_1_comboBox.currentIndexChanged.connect()
                    
                    

                    """this need to be checked if it is needed"""
                    # Optional: disable keyboard tracking for spin boxes
                    if hasattr(widget, "setKeyboardTracking"): #type: ignore
                        widget.setKeyboardTracking(False) #type: ignore
                
    
    
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
            'sig_X1': self.update_X1,
            'sig_Y1': self.update_Y1,
            'sig_R1': self.update_R1,
            'sig_Theta1': self.update_Theta1,
            'sig_X2': self.update_X2,
            'sig_Y2': self.update_Y2,
            'sig_R2': self.update_R2,
            'sig_Theta2': self.update_Theta2,
            #demod 1
            #sig_auto_range_1': self.auto_range_1, 
            'sig_sinc_filter_1': self.update_sinc_filter_1,
            'sig_filter_order_1': self.update_filter_order_1,
            'sig_time_constant_1': self.update_time_constant_1,
            'sig_harmonic_1': self.update_harmonic_1,
            'sig_phase_1': self.update_phase_1,

            #demod 2
            'sig_sinc_filter_2': self.update_sinc_filter_2,
            'sig_filter_order_2': self.update_filter_order_2,
            'sig_time_constant_2': self.update_time_constant_2,
            'sig_harmonic_2': self.update_harmonic_2,
            'sig_phase_2': self.update_phase_2,
            }
        
        for signal_name, slot in signal_mappings.items():
            if hasattr(self.logic, signal_name):
                getattr(self.logic, signal_name).connect(slot)
        
        # Dynamic signal connections
        for i in self.OSCILLATORS:
            osc_signal = f'sig_osc{i}_output_enable'
            if hasattr(self.logic, osc_signal):
                getattr(self.logic, osc_signal).connect(lambda state, osc=i: self.update_osc_output_enable(osc, state))
        
        for param in self.OSC_PARAMETERS:
            for i in self.OSCILLATORS:
                signal_name = f'sig_{param}{i}'
                if hasattr(self.logic, signal_name):
                    getattr(self.logic, signal_name).connect(
                        lambda value, p=param, num=i: self.update_parameter(p, num, value)
                    )

        for param in self.DEMOD_PARAMETERS:
            for demod_num in self.DEMODS:
                signal_name = f'sig_{param}_{demod_num}'
                if hasattr(self.logic, signal_name):
                    getattr(self.logic, signal_name).connect(lambda value, p=param, num=demod_num: self.update_demod_parameter(p, num, value))

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
        if hasattr(widget, 'lineEdit'):
            if hasattr(widget.lineEdit(), 'hasFocus'):
                return True
        return False
    
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
    def _add_plot(self):
        # ----- helper plot widget (X, Y, R, Theta streams) -----
        w1 = pg.GraphicsLayoutWidget(show=True)
        w1.viewport().setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        self.plot_x = w1.addPlot(row=0, col=0)
        self.plot_y = w1.addPlot(row=0, col=1)
        self.plot_r = w1.addPlot(row=0, col=2)
        self.plot_t = w1.addPlot(row=0, col=3)
        self.plot_x.setTitle("X")
        self.plot_y.setTitle("Y")
        self.plot_r.setTitle("R")
        self.plot_t.setTitle("Theta")
        # *graph_xyrt* is a QVBoxLayout placeholder defined in the .ui file
        self.graph_1_xyrt.addWidget(w1) #type: ignore

        w2 = pg.GraphicsLayoutWidget(show=True)
        w2.viewport().setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        self.plot_x2 = w2.addPlot(row=0, col=0)
        self.plot_y2 = w2.addPlot(row=0, col=1)
        self.plot_r2 = w2.addPlot(row=0, col=2)
        self.plot_t2 = w2.addPlot(row=0, col=3)
        self.plot_x2.setTitle("X")
        self.plot_y2.setTitle("Y")
        self.plot_r2.setTitle("R")
        self.plot_t2.setTitle("Theta")
        self.graph_2_xyrt.addWidget(w2) #type: ignore

    def _initialize_plot_buffers(self):
        self.x1_log = np.full(200, np.nan, dtype=float)
        self.y1_log = np.full(200, np.nan, dtype=float)
        self.r1_log = np.full(200, np.nan, dtype=float)
        self.t1_log = np.full(200, np.nan, dtype=float)
        self.x2_log = np.full(200, np.nan, dtype=float)
        self.y2_log = np.full(200, np.nan, dtype=float)
        self.r2_log = np.full(200, np.nan, dtype=float)
        self.t2_log = np.full(200, np.nan, dtype=float)

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
            
            self.logic.configure_basic_mode_hardware()

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

    def terminate_dev(self):
        self.logic.disconnect_device()
        print("MFLI terminated.")
    
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


    def set_demod_parameter(self, param: str, demod_num: int):
        """Generic method to set demodulator parameters
        dynamic method to set demodulator parameters:
        """
        try:
            widget_type = self.DEMOD_WIDGET_TYPES[param]        #'spinbox'
            widget_name = f'{param}_{demod_num}_{widget_type}'  #'filter_order_1_spinBox'
            widget = getattr(self, widget_name)                 #self.filter_order_1_spinBox

            # Get current value using WidgetRules
            _, getter = self.WidgetRules[widget_type]        
            value = getter(widget)                           

            setpoint_attr = f'setpoint_demod_{param}_{demod_num}' #'setpoint_demod_filter_order_1'
            job = f'set_demod_{param}_{demod_num}'              #'set_demod_filter_order_1'

            self.controller.safe_logic_operation(job, {setpoint_attr: value})

        except AttributeError as e:
            self.logger.error(f"Demod parameter setting failed: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error in set_demod_parameter: {e}")

    def update_demod_parameter(self, param: str, demod_num: int, value):
        """Generic method to update demodulator parameter display"""
        try:
            widget_type = self.DEMOD_WIDGET_TYPES[param]
            widget_name = f'{param}_{demod_num}_{widget_type}'
            widget = getattr(self, widget_name)

            _, getter = self.WidgetRules[widget_type]
            value = getter(widget)

            if widget_type == 'checkBox':
                self._safely_update_widget(widget, bool(value), bool)
            elif widget_type == 'pushButton':       
                pass
            elif self._is_widget_focused(widget):
                return
            elif widget_type in ('spinBox', 'doubleSpinBox'):
                self._safely_update_widget(widget, value, float)
            elif widget_type == 'comboBox':
                self._safely_update_widget(widget, int(value), int)
            
        except AttributeError as e:
            self.logger.error(f"Demod parameter update failed: {e}")

    def trigger_demod_action(self, param: str, demod_num: int):
        """Handle pushButton actions for demodulators"""
        job = f'trigger_{param}_{demod_num}'
        self.controller.safe_logic_operation(job)


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


    def update_X1(self, val):
        self.x1_log[:-1] = self.x1_log[1:]
        self.x1_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_x.plot(self.x1_log, clear=True, pen=pen)

    def update_Y1(self, val):
        self.y1_log[:-1] = self.y1_log[1:]
        self.y1_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_y.plot(self.y1_log, clear=True, pen=pen)

    def update_R1(self, val):
        self.r1_log[:-1] = self.r1_log[1:]
        self.r1_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_r.plot(self.r1_log, clear=True, pen=pen)

    def update_Theta1(self, val):
        self.t1_log[:-1] = self.t1_log[1:]
        self.t1_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_t.plot(self.t1_log, clear=True, pen=pen)

    def update_X2(self, val):
        self.x2_log[:-1] = self.x2_log[1:]
        self.x2_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_x2.plot(self.x2_log, clear=True, pen=pen)

    def update_Y2(self, val):
        self.y2_log[:-1] = self.y2_log[1:]
        self.y2_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_y2.plot(self.y2_log, clear=True, pen=pen)

    def update_R2(self, val):
        self.r2_log[:-1] = self.r2_log[1:]
        self.r2_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_r2.plot(self.r2_log, clear=True, pen=pen)
        
    def update_Theta2(self, val):
        self.t2_log[:-1] = self.t2_log[1:]
        self.t2_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_t2.plot(self.t2_log, clear=True, pen=pen)

    #demodulators
    def set_auto_range_1(self):
        """Set auto range for demodulator 1"""
        print("set_auto_range_1")
        self.controller.safe_logic_operation('set_auto_range_1')

    def set_auto_range_2(self):
        """Set auto range for demodulator 2"""
        self.controller.safe_logic_operation('set_auto_range_2')

    def set_auto_phase_1(self):
        """Set auto phase for demodulator 1"""
        self.controller.safe_logic_operation('set_auto_phase_1')
    
    def set_auto_phase_2(self):
        """Set auto phase for demodulator 2"""
        self.controller.safe_logic_operation('set_auto_phase_2')
    
    def set_zero_phase_1(self):
        """Set zero phase for demodulator 1"""  
        self.controller.safe_logic_operation('set_zero_phase_1')
    
    def set_zero_phase_2(self):
        """Set zero phase for demodulator 2"""
        self.controller.safe_logic_operation('set_zero_phase_2')
        

    def set_sinc_filter_1(self, state: Optional[bool] = None):
        """Set sinc filter for demodulator 1"""
        val = bool(state) if state is not None else self.sinc_filter_1_checkBox.isChecked() #type: ignore
        
        self.controller.safe_logic_operation('set_sinc_filter_1', {'setpoint_sinc_filter_1': val})

    def update_sinc_filter_1(self, val: bool):
        """Update sinc filter display"""
        self._safely_update_widget(self.sinc_filter_1_checkBox, val) #type: ignore

    def set_sinc_filter_2(self, state: Optional[bool] = None):
        """Set sinc filter for demodulator 2"""
        val = bool(state) if state is not None else self.sinc_filter_2_checkBox.isChecked() #type: ignore
        self.controller.safe_logic_operation('set_sinc_filter_2', {'setpoint_sinc_filter_2': val})

    def update_sinc_filter_2(self, val: bool):
        """Update sinc filter display"""
        self._safely_update_widget(self.sinc_filter_2_checkBox, val) #type: ignore

    def set_filter_order_1(self, value: int):
        """Set filter order for demodulator 1"""
        val = int(value) + 1 if value is not None else self.filter_order_1_comboBox.currentIndex() + 1
        self.controller.safe_logic_operation('set_filter_order_1', {'setpoint_filter_order_1': val})

    def update_filter_order_1(self, val: int):
        """Update filter order display"""
        self._safely_update_widget(self.filter_order_1_comboBox, val) #type: ignore
    
    def set_filter_order_2(self, value: int):
        """Set filter order for demodulator 2"""
        val = int(value) + 1 if value is not None else self.filter_order_2_comboBox.currentIndex() + 1
        self.controller.safe_logic_operation('set_filter_order_2', {'setpoint_filter_order_2': val})
    
    def update_filter_order_2(self, val: int):
        """Update filter order display"""
        self._safely_update_widget(self.filter_order_2_comboBox, val) #type: ignore
        
    def set_phase_1(self, value: float):
        """Set phase for demodulator 1"""
        value = float(value) if value is not None else self.phase_1_doubleSpinBox.value() #type: ignore
        self.controller.safe_logic_operation('set_phase_1', {'setpoint_phase_1': value})
    
    def update_phase_1(self, val: float):
        """Update DC offset display"""
        if self._is_widget_focused(self.phase_1_doubleSpinBox): #type: ignore
            return
        self._safely_update_widget(self.phase_1_doubleSpinBox, val, float) #type: ignore

    def set_phase_2(self, value: float):
        """Set phase for demodulator 2"""
        value = float(value) if value is not None else self.phase_2_doubleSpinBox.value() #type: ignore
        self.controller.safe_logic_operation('set_phase_2', {'setpoint_phase_2': value})
    
    def update_phase_2(self, val: float):
        """Update phase display"""  
        if self._is_widget_focused(self.phase_2_doubleSpinBox): #type: ignore
            return
        self._safely_update_widget(self.phase_2_doubleSpinBox, val, float) #type: ignore


    def set_time_constant_1(self, value: float):
        """Set time constant for demodulator 1"""
        val = float(value) if value is not None else self.time_constant_1_doubleSpinBox.value() #type: ignore
        self.controller.safe_logic_operation('set_time_constant_1', {'setpoint_time_constant_1': val})
    
    def update_time_constant_1(self, val: float):
        """Update time constant display"""
        if self._is_widget_focused(self.time_constant_1_doubleSpinBox): #type: ignore
            return
        self._safely_update_widget(self.time_constant_1_doubleSpinBox, val, float) #type: ignore

    def set_time_constant_2(self, value: float):
        """Set time constant for demodulator 2"""
        val = float(value) if value is not None else self.time_constant_2_doubleSpinBox.value() #type: ignore
        self.controller.safe_logic_operation('set_time_constant_2', {'setpoint_time_constant_2': val})
    
    def update_time_constant_2(self, val: float):
        """Update time constant display"""
        if self._is_widget_focused(self.time_constant_2_doubleSpinBox): #type: ignore
            return
        self._safely_update_widget(self.time_constant_2_doubleSpinBox, val, float) #type: ignore
    

    def set_harmonic_1(self, value: int):
        """Set harmonic for demodulator 1"""
        val = int(value) if value is not None else self.harmonic_1_spinBox.value() #type: ignore
        self.controller.safe_logic_operation('set_harmonic_1', {'setpoint_harmonic_1': val})
    
    def update_harmonic_1(self, val: int):
        """Update harmonic display"""
        if self._is_widget_focused(self.harmonic_1_spinBox): #type: ignore
            return
        self._safely_update_widget(self.harmonic_1_spinBox, val) #type: ignore

    def set_harmonic_2(self, value: int):
        """Set harmonic for demodulator 2"""
        val = int(value) if value is not None else self.harmonic_2_spinBox.value() #type: ignore
        self.controller.safe_logic_operation('set_harmonic_2', {'setpoint_harmonic_2': val})

    def update_harmonic_2(self, val: int):
        """Update harmonic display"""
        if self._is_widget_focused(self.harmonic_2_spinBox): #type: ignore
            return
        self._safely_update_widget(self.harmonic_2_spinBox, val) #type: ignore

    # ============================================================================
    # Cleanup and Event Handling
    # ============================================================================
    
    '''def closeEvent(self, a0):
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
    '''

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    
    try:
        window = MFLI()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        self.logger.error(f"Application failed to start: {e}")
        sys.exit(1)