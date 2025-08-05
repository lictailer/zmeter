from PyQt6.QtCore import QThread, pyqtSignal
from synthHD.synthHD_hardware import SynthHD_Hardware
import logging

class SynthHD_Logic(QThread):
    '''
    Logic layer for SynthHD V2 device control
    '''
    # Signals for UI updates
    frequency_changed = pyqtSignal(float)
    power_changed = pyqtSignal(float)
    output_enabled_changed = pyqtSignal(bool)
    channel_changed = pyqtSignal(int)
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.hardware = SynthHD_Hardware()
        self.connected = False
        self.current_channel = 0  # 0 for A, 1 for B

    def connect_device(self, device_path=None):
        '''
        Connect to the SynthHD device
        '''
        try:
            success = self.hardware.connect(device_path)
            self.connected = success
            self.connection_changed.emit(success)
            if success:
                # Update UI with current values
                self.update_ui_values()
            return success
        except Exception as e:
            self.error_occurred.emit(f"Connection error: {e}")
            return False

    def disconnect_device(self):
        '''
        Disconnect from the SynthHD device
        '''
        try:
            self.hardware.disconnect()
            self.connected = False
            self.connection_changed.emit(False)
        except Exception as e:
            self.error_occurred.emit(f"Disconnection error: {e}")

    def set_channel(self, channel):
        '''
        Set the current channel (0 for A, 1 for B)
        '''
        if channel in [0, 1]:
            self.current_channel = channel
            self.hardware.set_channel(channel)
            self.channel_changed.emit(channel)
            # Update UI with values for the new channel
            self.update_ui_values()
            return True
        return False

    def get_channel(self):
        '''
        Get the current channel
        '''
        return self.current_channel

    def set_frequency(self, frequency):
        '''
        Set frequency for the current channel
        '''
        if not self.connected:
            return False
        
        try:
            success = self.hardware.set_frequency(frequency, self.current_channel)
            if success:
                self.frequency_changed.emit(frequency)
            return success
        except Exception as e:
            self.error_occurred.emit(f"Frequency setting error: {e}")
            return False

    def get_frequency(self):
        '''
        Get frequency for the current channel
        '''
        if not self.connected:
            return 0
        
        try:
            return self.hardware.get_frequency(self.current_channel)
        except Exception as e:
            self.error_occurred.emit(f"Frequency reading error: {e}")
            return 0

    def set_power(self, power):
        '''
        Set power for the current channel
        '''
        if not self.connected:
            return False
        
        try:
            success = self.hardware.set_power(power, self.current_channel)
            if success:
                self.power_changed.emit(power)
            return success
        except Exception as e:
            self.error_occurred.emit(f"Power setting error: {e}")
            return False

    def get_power(self):
        '''
        Get power for the current channel
        '''
        if not self.connected:
            return 0
        
        try:
            return self.hardware.get_power(self.current_channel)
        except Exception as e:
            self.error_occurred.emit(f"Power reading error: {e}")
            return 0

    def enable_output(self, enable=True):
        '''
        Enable/disable output for the current channel
        '''
        if not self.connected:
            return False
        
        try:
            success = self.hardware.enable_output(enable, self.current_channel)
            if success:
                self.output_enabled_changed.emit(enable)
            return success
        except Exception as e:
            self.error_occurred.emit(f"Output enable error: {e}")
            return False

    def get_output_enabled(self):
        '''
        Get output enable state for the current channel
        '''
        if not self.connected:
            return False
        
        try:
            return self.hardware.get_output_enabled(self.current_channel)
        except Exception as e:
            self.error_occurred.emit(f"Output enable reading error: {e}")
            return False

    def get_channel_info(self):
        '''
        Get information about both channels
        '''
        if not self.connected:
            return {}
        
        try:
            return self.hardware.get_channel_info()
        except Exception as e:
            self.error_occurred.emit(f"Channel info error: {e}")
            return {}

    def update_ui_values(self):
        '''
        Update UI with current values for the active channel
        '''
        if not self.connected:
            return
        
        try:
            freq = self.get_frequency()
            power = self.get_power()
            enabled = self.get_output_enabled()
            
            self.frequency_changed.emit(freq)
            self.power_changed.emit(power)
            self.output_enabled_changed.emit(enabled)
        except Exception as e:
            self.error_occurred.emit(f"UI update error: {e}")

    def run(self):
        '''
        Main thread loop for monitoring device
        '''
        while True:
            if self.connected:
                try:
                    # Periodically update UI values
                    self.update_ui_values()
                except Exception as e:
                    logging.error(f"Monitoring error: {e}")
            
            # Sleep for a short time
            self.msleep(1000)  # Update every second 