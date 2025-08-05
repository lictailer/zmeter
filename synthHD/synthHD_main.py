from PyQt6 import uic, QtWidgets
from PyQt6.QtCore import QTimer
from synthHD.synthHD_logic import SynthHD_Logic
import logging

class SynthHD(QtWidgets.QWidget):
    '''
    Main UI class for SynthHD V2 device control
    '''
    
    def __init__(self):
        super().__init__()
        
        # Load UI
        uic.loadUi('synthHD/synthHD.ui', self)
        
        # Initialize logic
        self.logic = SynthHD_Logic()
        self.logic.start()
        
        # Connect signals
        self.connect_signals()
        
        # Set up logging
        logging.basicConfig(level=logging.INFO)
        
        # Initialize UI state
        self.update_connection_status(False)
        
    def connect_signals(self):
        '''
        Connect UI signals to logic methods
        '''
        # Connection buttons
        self.connectButton.clicked.connect(self.connect_device)
        self.disconnectButton.clicked.connect(self.disconnect_device)
        
        # Channel selection
        self.channelARadio.toggled.connect(self.on_channel_changed)
        self.channelBRadio.toggled.connect(self.on_channel_changed)
        
        # Control inputs
        self.frequencySpinBox.valueChanged.connect(self.on_frequency_changed)
        self.powerSpinBox.valueChanged.connect(self.on_power_changed)
        self.outputCheckBox.toggled.connect(self.on_output_changed)
        
        # Logic signals
        self.logic.frequency_changed.connect(self.update_frequency_display)
        self.logic.power_changed.connect(self.update_power_display)
        self.logic.output_enabled_changed.connect(self.update_output_display)
        self.logic.connection_changed.connect(self.update_connection_status)
        self.logic.error_occurred.connect(self.log_error)
        
    def connect_device(self):
        '''
        Connect to the SynthHD device
        '''
        device_path = self.devicePathEdit.text().strip()
        if not device_path:
            device_path = 'COM9'
        
        self.log_message(f"Attempting to connect to {device_path}...")
        success = self.logic.connect_device(device_path)
        
        if success:
            self.log_message("✓ Connected successfully")
        else:
            self.log_message("✗ Connection failed")
    
    def disconnect_device(self):
        '''
        Disconnect from the SynthHD device
        '''
        self.logic.disconnect_device()
        self.log_message("Disconnected from device")
    
    def on_channel_changed(self):
        '''
        Handle channel selection change
        '''
        if self.channelARadio.isChecked():
            channel = 0  # Channel A
            self.log_message("Switched to Channel A")
        else:
            channel = 1  # Channel B
            self.log_message("Switched to Channel B")
        
        self.logic.set_channel(channel)
    
    def on_frequency_changed(self, value):
        '''
        Handle frequency value change
        '''
        if self.logic.connected:
            self.logic.set_frequency(value)
            self.log_message(f"Set frequency to {value} Hz")
    
    def on_power_changed(self, value):
        '''
        Handle power value change
        '''
        if self.logic.connected:
            self.logic.set_power(value)
            self.log_message(f"Set power to {value} dBm")
    
    def on_output_changed(self, enabled):
        '''
        Handle output enable/disable
        '''
        if self.logic.connected:
            self.logic.enable_output(enabled)
            status = "enabled" if enabled else "disabled"
            self.log_message(f"Output {status}")
    
    def update_frequency_display(self, frequency):
        '''
        Update frequency display
        '''
        self.currentFreqLabel.setText(f"{frequency:.0f} Hz")
    
    def update_power_display(self, power):
        '''
        Update power display
        '''
        self.currentPowerLabel.setText(f"{power:.1f} dBm")
    
    def update_output_display(self, enabled):
        '''
        Update output status display
        '''
        status = "Enabled" if enabled else "Disabled"
        self.outputStatusLabel.setText(status)
    
    def update_connection_status(self, connected):
        '''
        Update connection status and UI state
        '''
        if connected:
            self.connectButton.setEnabled(False)
            self.disconnectButton.setEnabled(True)
            self.controlGroup.setEnabled(True)
            self.channelGroup.setEnabled(True)
        else:
            self.connectButton.setEnabled(True)
            self.disconnectButton.setEnabled(False)
            self.controlGroup.setEnabled(False)
            self.channelGroup.setEnabled(False)
            # Reset displays
            self.currentFreqLabel.setText("0 Hz")
            self.currentPowerLabel.setText("0 dBm")
            self.outputStatusLabel.setText("Disabled")
    
    def log_message(self, message):
        '''
        Add message to log display
        '''
        self.logTextEdit.append(message)
        # Auto-scroll to bottom
        self.logTextEdit.verticalScrollBar().setValue(
            self.logTextEdit.verticalScrollBar().maximum()
        )
    
    def log_error(self, error_message):
        '''
        Log error message
        '''
        self.log_message(f"ERROR: {error_message}")
    
    def terminate_dev(self):
        '''
        Clean up when closing
        '''
        if self.logic.connected:
            self.logic.disconnect_device()
        self.logic.quit()