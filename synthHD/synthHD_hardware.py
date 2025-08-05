from windfreak import SynthHD
import logging


class SynthHD_Hardware:
    '''
    Hardware interface for the SynthHD V2 device using the windfreak package.
    Supports both channels A and B with frequency and power control.
    '''
    def __init__(self):
        self.device = None
        self.connected = False
        self.device_path = None
        self.current_channel = 0  # 0 for channel A, 1 for channel B

    def connect(self, device_path=None):
        '''
        Connect to the SynthHD device
        '''
        try:
            # Use provided device path or default to COM9
            if device_path is None:
                device_path = 'COM9'  # Default to COM9

            # Try to connect to the device
            self.device = SynthHD(device_path)
            self.device.init()
            self.device_path = device_path
            self.connected = True
            logging.info(f'SynthHD V2 connected successfully on {device_path}')
            return True

        except Exception as e:
            logging.error(f'Failed to connect to SynthHD on {device_path}: {e}')
            self.connected = False
            return False

    def disconnect(self):
        '''
        Disconnect from the SynthHD device
        '''
        if self.device:
            try:
                self.device.close()
                self.connected = False
                logging.info('SynthHD disconnected')
            except Exception as e:
                logging.error(f'Error disconnecting from SynthHD: {e}')

    def set_channel(self, channel):
        '''
        Set the current channel (0 for A, 1 for B)
        '''
        if channel in [0, 1]:
            self.current_channel = channel
            logging.debug(f'Switched to channel {"A" if channel == 0 else "B"}')
            return True
        return False

    def get_channel(self):
        '''
        Get the current channel (0 for A, 1 for B)
        '''
        return self.current_channel

    def set_frequency(self, frequency, channel=None):
        '''
        Set the output frequency in Hz for the specified channel
        '''
        if not self.connected or not self.device:
            return False

        if channel is None:
            channel = self.current_channel

        try:
            self.device[channel].frequency = frequency
            logging.debug(f'Set channel {channel} frequency to {frequency} Hz')
            return True
        except Exception as e:
            logging.error(f'Failed to set frequency on channel {channel}: {e}')
            return False

    def get_frequency(self, channel=None):
        '''
        Get the current output frequency in Hz for the specified channel
        '''
        if not self.connected or not self.device:
            return 0

        if channel is None:
            channel = self.current_channel

        try:
            freq = self.device[channel].frequency
            logging.debug(f'Got channel {channel} frequency: {freq} Hz')
            return freq
        except Exception as e:
            logging.error(f'Failed to get frequency on channel {channel}: {e}')
            return 0

    def set_power(self, power, channel=None):
        '''
        Set the output power in dBm for the specified channel
        '''
        if not self.connected or not self.device:
            return False

        if channel is None:
            channel = self.current_channel

        try:
            self.device[channel].power = power
            logging.debug(f'Set channel {channel} power to {power} dBm')
            return True
        except Exception as e:
            logging.error(f'Failed to set power on channel {channel}: {e}')
            return False

    def get_power(self, channel=None):
        '''
        Get the current output power in dBm for the specified channel
        '''
        if not self.connected or not self.device:
            return 0

        if channel is None:
            channel = self.current_channel

        try:
            power = self.device[channel].power
            logging.debug(f'Got channel {channel} power: {power} dBm')
            return power
        except Exception as e:
            logging.error(f'Failed to get power on channel {channel}: {e}')
            return 0

    def enable_output(self, enable=True, channel=None):
        '''
        Enable or disable the output for the specified channel
        '''
        if not self.connected or not self.device:
            return False

        if channel is None:
            channel = self.current_channel

        try:
            self.device[channel].enable = enable
            status = "enabled" if enable else "disabled"
            logging.debug(f'Channel {channel} output {status}')
            return True
        except Exception as e:
            logging.error(f'Failed to set output enable on channel {channel}: {e}')
            return False

    def get_output_enabled(self, channel=None):
        '''
        Get the current output enable state for the specified channel
        '''
        if not self.connected or not self.device:
            return False

        if channel is None:
            channel = self.current_channel

        try:
            enabled = self.device[channel].enable
            logging.debug(f'Channel {channel} output enabled: {enabled}')
            return enabled
        except Exception as e:
            logging.error(f'Failed to get output enable state on channel {channel}: {e}')
            return False

    def get_channel_info(self):
        '''
        Get information about both channels
        '''
        if not self.connected or not self.device:
            return {}

        info = {}
        for channel in [0, 1]:
            try:
                info[f'channel_{channel}'] = {
                    'frequency': self.device[channel].frequency,
                    'power': self.device[channel].power,
                    'enabled': self.device[channel].enable
                }
            except Exception as e:
                logging.error(f'Failed to get info for channel {channel}: {e}')
                info[f'channel_{channel}'] = {'error': str(e)}

        return info 