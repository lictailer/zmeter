# =============================================================================
# MFLI_main.py - Qt GUI for MFLI Lock-in Amplifier
# =============================================================================

# -----------------------------------------------------------------------------
# IMPORTS
# -----------------------------------------------------------------------------
from PyQt6 import QtWidgets, QtCore
from PyQt6.uic.load_ui import loadUi
import sys
import time
import numpy as np
import pyqtgraph as pg

from MFLI_logic import MFLI_Logic


# -----------------------------------------------------------------------------
# MAIN GUI CLASS
# -----------------------------------------------------------------------------
class MFLI(QtWidgets.QWidget):
    """Qt GUI wrapper for MFLI lock-in amplifier."""

    # Class-level signals
    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        
        # Load UI and initialize components
        self._load_ui()
        self._init_logic()
        self._init_plots()
        self._init_device_discovery()
        self._connect_ui_signals()
        self._connect_logic_signals()
        self._start_monitoring()

    # -------------------------------------------------------------------------
    # INITIALIZATION METHODS
    # -------------------------------------------------------------------------
    def _load_ui(self):
        """Load the UI file."""
        loadUi("MFLI/MFLI.ui", self)

    def _init_logic(self):
        """Initialize the logic layer."""
        self.logic = MFLI_Logic()

    def _init_plots(self):
        """Initialize live plotting widgets."""
        w = pg.GraphicsLayoutWidget(show=True)
        w.viewport().setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        
        # Create plots
        self.plot_x = w.addPlot(row=0, col=0, title="X (V)")
        self.plot_y = w.addPlot(row=0, col=1, title="Y (V)")
        self.plot_r = w.addPlot(row=1, col=0, title="R (V)")
        self.plot_phase = w.addPlot(row=1, col=1, title="Phase (°)")
        
        # Add to UI (assuming you have a graph_layout in your .ui file)
        # self.graph_layout.addWidget(w)
        
        # Initialize data buffers
        self.buffer_size = 1000
        self.x_log = np.full(self.buffer_size, np.nan)
        self.y_log = np.full(self.buffer_size, np.nan)
        self.r_log = np.full(self.buffer_size, np.nan)
        self.phase_log = np.full(self.buffer_size, np.nan)

    def _init_device_discovery(self):
        """Initialize device discovery and populate device list."""
        try:
            devices = self.logic.get_available_devices()
            self.address_comboBox.addItems(devices)
        except Exception as e:
            self.address_comboBox.addItem("Discovery failed")
            print(f"Device discovery error: {e}")

    def _connect_ui_signals(self):
        """Connect UI widget signals to handler methods."""
        # Connection controls
        self.connect_pushButton.clicked.connect(self.connect_device)
        self.disconnect_pushButton.clicked.connect(self.disconnect_device)
        
        # Output controls
        self.output_enable_checkBox.stateChanged.connect(self.set_output_enable)
        self.differential_output_checkBox.stateChanged.connect(self.set_differential_output)
        
        self.output_autorange_checkBox.stateChanged.connect(self.set_output_autorange)
        self.output_range_comboBox.currentTextChanged.connect(self.set_output_range)
        
        # Parameter controls
        self.frequency1_spinBox.editingFinished.connect(self.set_frequency1)
        self.amplitude1_spinBox.editingFinished.connect(self.set_amplitude1)
        self.phase1_spinBox.editingFinished.connect(self.set_phase1)
        self.dc_offset_spinBox.editingFinished.connect(self.set_dc_offset)
        
        # Action buttons
        self.preset_pushButton.clicked.connect(self.preset)

    def _connect_logic_signals(self):
        """Connect logic layer signals to update methods."""
        # Status signals
        self.logic.sig_is_changing.connect(self.update_status)
        self.logic.sig_connected.connect(self.update_status)
        
        # Parameter update signals - UPDATED NAMES
        self.logic.sig_output_enable.connect(self.update_output_enable)
        self.logic.sig_differential_output.connect(self.update_differential_output)
        
        # Frequency signal (simplified - only one oscillator)
        self.logic.sig_frequency.connect(self.update_frequency1)
        
        # Output control signals
        self.logic.sig_amplitude.connect(self.update_amplitude1)
        self.logic.sig_dc_offset.connect(self.update_dc_offset)
        self.logic.sig_output_autorange.connect(self.update_output_autorange)
        self.logic.sig_output_range.connect(self.update_output_range)
        
        # Phase signals - UPDATED NAMES
        self.logic.sig_voltage_phase.connect(self.update_phase1)  # Using voltage phase for main display
        
        # Data signals
        self.logic.sig_voltage_sample.connect(self.update_voltage_sample)
        self.logic.sig_current_sample.connect(self.update_current_sample)
        self.logic.sig_clockbase.connect(self.update_clockbase)
        
        # Error handling (add these if missing)
        if hasattr(self.logic, 'sig_error'):
            self.logic.sig_error.connect(self.handle_error)
        if hasattr(self.logic, 'sig_warning'):
            self.logic.sig_warning.connect(self.handle_warning)

    def _start_monitoring(self):
        """Start the periodic monitoring timer."""
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._monitor)
        self.timer.start(50)
        self.stop_signal.connect(self._stop_timer)

    # -------------------------------------------------------------------------
    # CONNECTION METHODS
    # -------------------------------------------------------------------------
    def connect_device(self, addr=None):
        """Connect to MFLI device."""
        if addr is None or addr is False:
            addr = self.address_comboBox.currentText()
        
        if not addr or "failed" in addr.lower():
            self.update_status("Please select a valid device")
            return
            
        print(f"Connecting to {addr}")
        self.logic.connect_device(device_id=addr)
        self.address_comboBox.setCurrentText(addr)

    def disconnect_device(self):
        """Disconnect from MFLI device."""
        self.logic.disconnect_device()

    # -------------------------------------------------------------------------
    # OUTPUT CONTROL METHODS
    # -------------------------------------------------------------------------
    def set_output_enable(self, state=None):
        """Enable/disable signal output."""
        self.logic.stop()
        self.logic.setpoint_output_enable = bool(state) if state is not None else self.output_enable_checkBox.isChecked()
        self.logic.job = "set_output_enable"
        self.logic.start()

    def set_differential_output(self, state=None):
        """Set differential output mode."""
        self.logic.stop()
        self.logic.setpoint_differential_output = bool(state) if state is not None else self.differential_output_checkBox.isChecked()
        self.logic.job = "set_differential_output"
        self.logic.start()

  
    def set_output_autorange(self, state=None):
        """Set output auto-ranging."""
        self.logic.stop()
        if state is not None:
            self.logic.setpoint_output_autorange = bool(state)
        else:
            self.logic.setpoint_output_autorange = self.output_autorange_checkBox.isChecked()
        self.logic.job = "set_output_autorange"
        self.logic.start()
        
        # Update UI state
        if bool(state):
            self.output_range_comboBox.setEnabled(False)
        else:
            self.output_range_comboBox.setEnabled(True)

    def set_output_range(self):
        """Set output voltage range."""
        self.logic.stop()
        self.logic.setpoint_output_range = self.output_range_comboBox.currentText()
        self.logic.job = "set_output_range"
        self.logic.start()


    # Add these methods to your MFLI_main.py for testing and synchronization:

    def sync_with_hardware(self):
        """Sync software with hardware state."""
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.job = "sync_with_hardware"
        self.logic.start()

    def enable_output_and_osc(self):
        """Enable both output and oscillator."""
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.job = "enable_output_with_oscillator"
        self.logic.start()

    def disable_output_and_osc(self):
        """Disable both output and oscillator."""
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.job = "disable_output_and_oscillator"
        self.logic.start()

    def test_functionality(self):
        """Test basic MFLI functionality."""
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.job = "test_basic_functionality"
        self.logic.start()

    def get_complete_status(self):
        """Get complete device status."""
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.job = "get_complete_status"
        self.logic.start()

    # You can also add buttons to your UI to call these methods
    # Or create keyboard shortcuts for testing:

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts for testing."""
        if event.key() == QtCore.Qt.Key.Key_S:  # S for Sync
            self.sync_with_hardware()
        elif event.key() == QtCore.Qt.Key.Key_O:  # O for Output enable
            self.enable_output_and_osc()
        elif event.key() == QtCore.Qt.Key.Key_D:  # D for Disable
            self.disable_output_and_osc()
        elif event.key() == QtCore.Qt.Key.Key_T:  # T for Test
            self.test_functionality()
        elif event.key() == QtCore.Qt.Key.Key_I:  # I for Info
            self.get_complete_status()
        else:
            super().keyPressEvent(event)

    # -------------------------------------------------------------------------
    # PARAMETER CONTROL METHODS
    # -------------------------------------------------------------------------
        
    def set_frequency1(self):
        """Set oscillator frequency."""
        self.logic.stop()
        self.logic.setpoint_frequency = self.frequency1_spinBox.value()  # Note: changed from setpoint_frequency1
        self.logic.job = "set_frequency"
        self.logic.start()

    def set_amplitude1(self):
        """Set output amplitude."""
        self.logic.stop()
        self.logic.setpoint_amplitude = self.amplitude1_spinBox.value()  # Note: changed from setpoint_amplitude1
        self.logic.job = "set_amplitude"
        self.logic.start()

    def set_phase1(self):
        """Set voltage demodulator phase."""
        self.logic.stop()
        self.logic.setpoint_voltage_phase = self.phase1_spinBox.value()  # Note: changed from setpoint_phase1
        self.logic.job = "set_voltage_phase"
        self.logic.start()

    def set_dc_offset(self):
        """Set DC offset."""
        self.logic.stop()
        self.logic.setpoint_dc_offset = self.dc_offset_spinBox.value()
        self.logic.job = "set_dc_offset"
        self.logic.start()

    # -------------------------------------------------------------------------
    # UI UPDATE METHODS
    # -------------------------------------------------------------------------
    def update_output_enable(self, state):
        """Update output enable checkbox."""
        self.output_enable_checkBox.blockSignals(True)
        self.output_enable_checkBox.setChecked(bool(state))
        self.output_enable_checkBox.blockSignals(False)

    def update_differential_output(self, state):
        """Update differential output checkbox."""
        self.differential_output_checkBox.blockSignals(True)
        self.differential_output_checkBox.setChecked(bool(state))
        self.differential_output_checkBox.blockSignals(False)

    def update_osc1_output_enable(self, state):
        """Update oscillator 1 output enable checkbox."""
        self.osc1_output_enable_checkBox.blockSignals(True)
        self.osc1_output_enable_checkBox.setChecked(bool(state))
        self.osc1_output_enable_checkBox.blockSignals(False)

    def update_frequency1(self, freq):
        """Update frequency display."""
        if self.frequency1_spinBox.lineEdit().hasFocus():
            return
        self.frequency1_spinBox.blockSignals(True)
        self.frequency1_spinBox.setValue(float(freq))
        self.frequency1_spinBox.blockSignals(False)
        
        # Update related displays
        if hasattr(self, 'frequency4_spinBox') and not self.frequency4_spinBox.lineEdit().hasFocus():
            self.frequency4_spinBox.blockSignals(True)
            self.frequency4_spinBox.setValue(float(freq))
            self.frequency4_spinBox.blockSignals(False)

    def update_amplitude1(self, amp):
        """Update amplitude display."""
        if self.amplitude1_spinBox.lineEdit().hasFocus():
            return
        self.amplitude1_spinBox.blockSignals(True)
        self.amplitude1_spinBox.setValue(float(amp))
        self.amplitude1_spinBox.blockSignals(False)

    def update_phase1(self, phase):
        """Update phase display."""
        if self.phase1_spinBox.lineEdit().hasFocus():
            return
        self.phase1_spinBox.blockSignals(True)
        self.phase1_spinBox.setValue(float(phase))
        self.phase1_spinBox.blockSignals(False)

    def update_dc_offset(self, offset):
        """Update DC offset display."""
        if self.dc_offset_spinBox.lineEdit().hasFocus():
            return
        self.dc_offset_spinBox.blockSignals(True)
        self.dc_offset_spinBox.setValue(float(offset))
        self.dc_offset_spinBox.blockSignals(False)

    def update_output_autorange(self, state):
        """Update output autorange checkbox."""
        self.output_autorange_checkBox.blockSignals(True)
        self.output_autorange_checkBox.setChecked(bool(state))
        self.output_autorange_checkBox.blockSignals(False)

    def update_output_range(self, range_val):
        """Update output range display."""
        self.output_range_comboBox.blockSignals(True)
        self.output_range_comboBox.setCurrentText(str(range_val))
        self.output_range_comboBox.blockSignals(False)

    def update_status(self, txt):
        """Update status label."""
        self.status_label.setText(str(txt))

    # -------------------------------------------------------------------------
    # DATA VISUALIZATION METHODS
    # -------------------------------------------------------------------------
    def update_demod_sample(self, sample_data):
        """Update plots with new demodulator sample data."""
        if sample_data is None:
            return
        
        try:
            # Extract values
            x = float(sample_data.get('x', 0))
            y = float(sample_data.get('y', 0))
            r = float(sample_data.get('r', 0))
            phase = float(sample_data.get('phase', 0))
            
            # Update circular buffers
            self._update_data_buffers(x, y, r, phase)
            
            # Update plots
            self._update_plots()
            
            # Update text displays
            self._update_value_displays(x, y, r, phase)
            
        except Exception as e:
            print(f"Error updating demod sample: {e}")

    def _update_data_buffers(self, x, y, r, phase):
        """Update circular data buffers."""
        self.x_log[:-1] = self.x_log[1:]
        self.y_log[:-1] = self.y_log[1:]
        self.r_log[:-1] = self.r_log[1:]
        self.phase_log[:-1] = self.phase_log[1:]
        
        self.x_log[-1] = x
        self.y_log[-1] = y
        self.r_log[-1] = r
        self.phase_log[-1] = phase

    def _update_plots(self):
        """Update all plot displays."""
        pen = pg.mkPen((255, 255, 255), width=2)
        self.plot_x.plot(self.x_log, clear=True, pen=pen)
        self.plot_y.plot(self.y_log, clear=True, pen=pen)
        self.plot_r.plot(self.r_log, clear=True, pen=pen)
        self.plot_phase.plot(self.phase_log, clear=True, pen=pen)

    def _update_value_displays(self, x, y, r, phase):
        """Update numerical value displays."""
        if hasattr(self, 'x_label'):
            self.x_label.setText(f"X: {x:.6f} V")
        if hasattr(self, 'y_label'):
            self.y_label.setText(f"Y: {y:.6f} V")
        if hasattr(self, 'r_label'):
            self.r_label.setText(f"R: {r:.6f} V")
        if hasattr(self, 'phase_label'):
            self.phase_label.setText(f"φ: {phase:.2f}°")

    def update_voltage_sample(self, sample_data):
        """Update voltage measurement display."""
        if sample_data:
            try:
                x = float(sample_data.get('x', 0))
                y = float(sample_data.get('y', 0))
                r = float(sample_data.get('r', 0))
                phase = float(sample_data.get('phase', 0))
                
                # Update your voltage displays here
                if hasattr(self, 'voltage_x_label'):
                    self.voltage_x_label.setText(f"X: {x:.6f} V")
                if hasattr(self, 'voltage_y_label'):
                    self.voltage_y_label.setText(f"Y: {y:.6f} V")
                if hasattr(self, 'voltage_r_label'):
                    self.voltage_r_label.setText(f"R: {r:.6f} V")
                if hasattr(self, 'voltage_phase_label'):
                    self.voltage_phase_label.setText(f"φ: {phase:.2f}°")
            except Exception as e:
                print(f"Error updating voltage sample: {e}")

    def update_current_sample(self, sample_data):
        """Update current measurement display."""
        if sample_data:
            try:
                x = float(sample_data.get('x', 0))
                y = float(sample_data.get('y', 0))
                r = float(sample_data.get('r', 0))
                phase = float(sample_data.get('phase', 0))
                
                # Update your current displays here
                if hasattr(self, 'current_x_label'):
                    self.current_x_label.setText(f"X: {x:.6f} A")
                if hasattr(self, 'current_y_label'):
                    self.current_y_label.setText(f"Y: {y:.6f} A")
                if hasattr(self, 'current_r_label'):
                    self.current_r_label.setText(f"R: {r:.6f} A")
                if hasattr(self, 'current_phase_label'):
                    self.current_phase_label.setText(f"φ: {phase:.2f}°")
            except Exception as e:
                print(f"Error updating current sample: {e}")

    def handle_error(self, error_msg):
        """Handle error messages from logic layer."""
        self.status_label.setText(f"❌ ERROR: {error_msg}")
        print(f"MFLI Error: {error_msg}")

    def handle_warning(self, warning_msg):
        """Handle warning messages from logic layer."""
        self.status_label.setText(f"⚠️ WARNING: {warning_msg}")
        print(f"MFLI Warning: {warning_msg}")

    def update_clockbase(self, freq):
        """Update clockbase display."""
        try:
            freq_mhz = float(freq) / 1e6
            # Update clockbase display if you have one
            if hasattr(self, 'clockbase_label'):
                self.clockbase_label.setText(f"Clock: {freq_mhz:.1f} MHz")
        except:
            pass

    def reset_graphs(self):
        """Reset all plot data."""
        self.x_log[:] = np.nan
        self.y_log[:] = np.nan
        self.r_log[:] = np.nan
        self.phase_log[:] = np.nan
        self._update_plots()

    # -------------------------------------------------------------------------
    # UTILITY METHODS
    # -------------------------------------------------------------------------
    def preset(self):
        """Apply preset configuration."""
        self.logic.stop()
        self.logic.job = "preset_basic"
        self.logic.start()

    def update_output_range_combobox(self, range_val):
        """Helper to update range combobox by calculated index."""
        try:
            index = int(2 + np.log10(float(range_val)))
            self.output_range_comboBox.setCurrentIndex(index)
        except:
            pass

    # -------------------------------------------------------------------------
    # TIMER AND MONITORING
    # -------------------------------------------------------------------------
    def _monitor(self):
        """Periodic monitoring method."""
        if not self.logic.connected:
            return
        if self.logic.isRunning():
            return
        
        # Alternate between full status and data acquisition
        if not hasattr(self, '_monitor_counter'):
            self._monitor_counter = 0
        
        self._monitor_counter += 1
        
        if self._monitor_counter % 20 == 0:  # Every 1 second (50ms * 20), get full status
            self.logic.job = "get_all"
        else:  # Otherwise get measurement data
            self.logic.job = "get_demod_sample"  # This should now work
        
        self.logic.start()

    # Alternative simpler version if you want to test step by step:
    def _monitor_simple(self):
        """Simplified monitoring for testing."""
        if not self.logic.connected:
            return
        if self.logic.isRunning():
            return
        
        # For now, just get measurements
        self.logic.job = "get_demod_sample"
        self.logic.start()

    def _stop_timer(self):
        """Stop the monitoring timer."""
        if self.timer.isActive():
            self.timer.stop()

    def start_timer(self):
        """Start the monitoring timer."""
        if not self.timer.isActive():
            self.timer.start(50)

    # -------------------------------------------------------------------------
    # CLEANUP AND TERMINATION
    # -------------------------------------------------------------------------
    def terminate_dev(self):
        """Terminate device connection."""
        self.logic.disconnect_device()
        print("MFLI terminated.")

    def closeEvent(self, event):
        """Handle window close event."""
        self.terminate_dev()
        print("MFLI closed.")
        event.accept()


# -----------------------------------------------------------------------------
# STANDALONE ENTRY POINT
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MFLI()
    window.show()
    sys.exit(app.exec())