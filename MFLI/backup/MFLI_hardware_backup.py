import logging
import time
import math
import zhinst.ziPython as zi

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class MFLIHardwareError(Exception):
    """Custom exception for MFLI hardware errors."""
    pass

class MFLI_Hardware:
    """
    Python driver for Zurich Instruments MFLI lock-in amplifier using zhinst.ziPython.
    """

    def __init__(self, device_id: str, host='localhost', port=8004, api_level=6, interface='1GbE'):
        """
        device_id: e.g. 'dev30037'
        """
        self.device_id = device_id
        self.device = device_id
        self.daq = None
        self._connect(self.device_id)


    @staticmethod
    def get_available_devices():
        try:
            discovery = zi.ziDiscovery()
            devices = discovery.findAll()
            return [device.lower() for device in devices]
        except Exception as e:
            logging.error(f"Failed to get available devices: {e}")
            raise MFLIHardwareError(f"get_available_devices failed: {e}")

    def _create_daq_server(self, host='localhost', port=8004, api_level=6):
        """Create and return a ziDAQServer instance."""
        try:
            daq = zi.ziDAQServer(host, port, api_level)
            return daq
        except Exception as e:
            logging.error(f"Failed to create ziDAQServer: {e}")
            raise MFLIHardwareError(f"ziDAQServer creation failed: {e}")

    def _connect(self, device_id, host='localhost', port=8004, api_level=6, interface='1GbE'):
        """Connect to the device using the DAQ server."""
        
        try:
            self.daq = self._create_daq_server(host, port, api_level)
            self.daq.connectDevice(device_id, interface)
            logging.info(f"Connected to MFLI {device_id} at {host}:{port} via {interface}")
        except Exception as e:
            logging.error(f"Failed to connect to MFLI {device_id}: {e}")
            raise MFLIHardwareError(f"Connection failed: {e}")
    # -------------- Output and Oscillator --------------
    def set_frequency(self, osc_index: int, f_hz: float):
        """Set oscillator frequency in Hz."""
        if osc_index not in [0, 1, 2, 3]:
            raise MFLIHardwareError(f"Invalid oscillator index: {osc_index}")
        else:
            try:
                self.daq.setDouble(f'/{self.device}/oscs/{osc_index}/freq', f_hz)
                logging.info(f"Set frequency to {f_hz} Hz")
            except Exception as e:
                logging.error(f"Failed to set frequency: {e}")
                raise MFLIHardwareError(f"set_frequency failed: {e}")

    def get_frequency(self, osc_index: int) -> float:
        """Get oscillator frequency in Hz."""
        if osc_index not in [0, 1, 2, 3]:
            raise MFLIHardwareError(f"Invalid oscillator index: {osc_index}")
        else:
            try:
                freq = self.daq.getDouble(f'/{self.device}/oscs/{osc_index}/freq')
                logging.info(f"Got frequency: {freq} Hz")
                return freq
            except Exception as e:
                logging.error(f"Failed to get frequency: {e}")
                raise MFLIHardwareError(f"get_frequency failed: {e}")

    def set_amplitude(self, v: float, osc_index: int = 0):
        """Set output amplitude (V) for the specified oscillator index (0, 1, 2, or 3)."""
        if osc_index not in [0, 1, 2, 3]:
            raise MFLIHardwareError(f"Invalid osc_index: {osc_index}. Must be 0, 1, 2, or 3.")
        try:
            self.daq.setDouble(f'/{self.device}/sigouts/0/amplitudes/{osc_index}', v)
            logging.info(f"Set amplitude to {v} V for osc_index {osc_index}")
        except Exception as e:
            logging.error(f"Failed to set amplitude for osc_index {osc_index}: {e}")
            raise MFLIHardwareError(f"set_amplitude failed for osc_index {osc_index}: {e}")


    def get_amplitude(self, osc_index: int = 0) -> float:
        """Get output amplitude (V) for the specified oscillator index (0, 1, 2, or 3)."""
        if osc_index not in [0, 1, 2, 3]:
            raise MFLIHardwareError(f"Invalid osc_index: {osc_index}. Must be 0, 1, 2, or 3.")
        try:
            amp = self.daq.getDouble(f'/{self.device}/sigouts/0/amplitudes/{osc_index}')
            logging.info(f"Got amplitude: {amp} V for osc_index {osc_index}")
            return amp
        except Exception as e:
            logging.error(f"Failed to get amplitude for osc_index {osc_index}: {e}")
            raise MFLIHardwareError(f"get_amplitude failed for osc_index {osc_index}: {e}")

    def get_autorange(self):
        try:
            autorange = self.daq.getInt(f'/{self.device}/sigouts/0/autorange')
            logging.info(f"Autorange: {autorange}")
            return autorange
        except Exception as e:
            logging.error(f"Failed to get autorange: {e}")
    def set_autorange(self, autorange=True):
        try:
            self.daq.setInt(f'/{self.device}/sigouts/0/autorange', int(autorange))
            logging.info(f"Set autorange to {autorange}")
        except Exception as e:
            logging.error(f"Failed to set autorange: {e}")
            raise MFLIHardwareError(f"set_autorange failed: {e}")

    def set_output_enable(self, on=True):
        """Enable or disable output."""
        try:
            self.daq.setInt(f'/{self.device}/sigouts/0/on', int(on))
            logging.info(f"Output {'enabled' if on else 'disabled'}")
        except Exception as e:
            logging.error(f"Failed to set output state: {e}")
            raise MFLIHardwareError(f"set_output_enable failed: {e}")
    def get_output_enable(self):
        try:
            enable = self.daq.getInt(f'/{self.device}/sigouts/0/on')
            logging.info(f"Output {'enabled' if enable else 'disabled'}")
            return enable
        except Exception as e:
            logging.error(f"Failed to get output enable: {e}")

    def set_osc_output_enable(self, on=True, osc_index=0):
        try:
            self.daq.setInt(f'/{self.device}/sigouts/0/enables/{osc_index}', int(on))
            logging.info(f"Oscillator {osc_index} output {'enabled' if on else 'disabled'}")
        except Exception as e:
            logging.error(f"Failed to set oscillator output enable: {e}")
            raise MFLIHardwareError(f"set_osc_output_enable failed: {e}")
    def get_osc_output_enable(self, osc_index=0):
        try:
            enable = self.daq.getInt(f'/{self.device}/sigouts/0/enables/{osc_index}')
            logging.info(f"Oscillator {osc_index} output {'enabled' if enable else 'disabled'}")
            return enable
        except Exception as e:
            logging.error(f"Failed to get oscillator output enable: {e}")

    def set_differential_output(self, enable=True):
        try:
            self.daq.setInt(f'/{self.device}/sigouts/0/diff', int(enable))
            logging.info(f"Set differential output to {'enabled' if enable else 'disabled'}")
        except Exception as e:
            logging.error(f"Failed to set differential output: {e}")
            raise MFLIHardwareError(f"set_differential_output failed: {e}")
    def get_differential_output(self):
        try:
            enable = self.daq.getInt(f'/{self.device}/sigouts/0/diff')
            logging.info(f"Differential output {'enabled' if enable else 'disabled'}")
            return enable
        except Exception as e:
            logging.error(f"Failed to get differential output: {e}")
    def set_output_range(self, rng: float):
        """Set output range (V)."""
        try:
            self.daq.setDouble(f'/{self.device}/sigouts/0/range', rng)
            logging.info(f"Set output range to {rng} V")
        except Exception as e:
            logging.error(f"Failed to set output range: {e}")
            raise MFLIHardwareError(f"set_output_range failed: {e}")

    def get_output_range(self):
        try:
            rng = self.daq.getDouble(f'/{self.device}/sigouts/0/range')
            logging.info(f"Output range: {rng} V")
            return rng
        except Exception as e:
            logging.error(f"Failed to get output range: {e}")
            raise MFLIHardwareError(f"get_output_range failed: {e}")
    def set_output_auto_range(self, auto_range=True):
        try:
            self.daq.setInt(f'/{self.device}/sigouts/0/autorange', int(auto_range))
            logging.info(f"Set output auto range to {auto_range}")
        except Exception as e:
            logging.error(f"Failed to set output auto range: {e}")
            raise MFLIHardwareError(f"set_output_auto_range failed: {e}")
    def get_output_auto_range(self):
        try:
            auto_range = self.daq.getInt(f'/{self.device}/sigouts/0/autorange')
            logging.info(f"Output auto range: {auto_range}")
            return auto_range
        except Exception as e:
            logging.error(f"Failed to get output auto range: {e}")

    # -------------- Demodulator --------------
    def set_phase(self, phase: float, demod_index: int = 0):
        try:
            self.daq.setDouble(f'/{self.device}/demods/{demod_index}/phaseshift', phase)
            logging.info(f"Set phase to {phase} for demod_index {demod_index}")
        except Exception as e:
            logging.error(f"Failed to set phase for demod_index {demod_index}: {e}")
            raise MFLIHardwareError(f"set_phase failed for demod_index {demod_index}: {e}")
    def get_phase(self, demod_index: int = 0):
        try:
            phase = self.daq.getDouble(f'/{self.device}/demods/{demod_index}/phaseshift')
            logging.info(f"Got phase: {phase} for demod_index {demod_index}")
            return phase
        except Exception as e:
            logging.error(f"Failed to get phase for demod_index {demod_index}: {e}")
    





    def set_demod_osc(self, osc_index=0, demod_index=0):
        try:
            self.daq.setInt(f'/{self.device}/demods/{demod_index}/oscselect', osc_index)
            logging.info(f"Set demodulator {demod_index} oscillator to {osc_index}")
        except Exception as e:
            logging.error(f"Failed to set demodulator oscillator: {e}")
            raise MFLIHardwareError(f"set_demod_osc failed: {e}")

    def set_demod_adc(self, adc_index=0):
        try:
            self.daq.setInt(f'/{self.device}/demods/0/adcselect', adc_index)
            logging.info(f"Set demodulator ADC to {adc_index}")
        except Exception as e:
            logging.error(f"Failed to set demodulator ADC: {e}")
            raise MFLIHardwareError(f"set_demod_adc failed: {e}")

    def enable_demod(self, enable=True):
        try:
            self.daq.setInt(f'/{self.device}/demods/0/enable', int(enable))
            logging.info(f"Demodulator {'enabled' if enable else 'disabled'}")
        except Exception as e:
            logging.error(f"Failed to enable demodulator: {e}")
            raise MFLIHardwareError(f"enable_demod failed: {e}")

    def set_demod_rate(self, rate=1000):
        try:
            self.daq.setDouble(f'/{self.device}/demods/0/rate', rate)
            logging.info(f"Set demodulator rate to {rate} Sa/s")
        except Exception as e:
            logging.error(f"Failed to set demodulator rate: {e}")
            raise MFLIHardwareError(f"set_demod_rate failed: {e}")

    def set_demod_timeconstant(self, tau=0.01):
        try:
            self.daq.setDouble(f'/{self.device}/demods/0/timeconstant', tau)
            logging.info(f"Set demodulator time constant to {tau} s")
        except Exception as e:
            logging.error(f"Failed to set demodulator time constant: {e}")
            raise MFLIHardwareError(f"set_demod_timeconstant failed: {e}")

    def set_demod_order(self, order=1):
        try:
            self.daq.setInt(f'/{self.device}/demods/0/order', order)
            logging.info(f"Set demodulator order to {order}")
        except Exception as e:
            logging.error(f"Failed to set demodulator order: {e}")
            raise MFLIHardwareError(f"set_demod_order failed: {e}")

    def sync(self):
        try:
            self.daq.sync()
            logging.info("Synchronized settings with device")
        except Exception as e:
            logging.error(f"Failed to sync: {e}")
            raise MFLIHardwareError(f"sync failed: {e}")

    # -------------- Data Acquisition --------------
    def get_demod_sample(self):
        """Poll demodulator sample and return latest X, Y, R."""
        sample_path = f'/{self.device}/demods/0/sample'
        try:
            self.daq.subscribe(sample_path)
            time.sleep(0.1)
            data = self.daq.poll(0.1, 100, 0, True)
            self.daq.unsubscribe('*')

            if sample_path in data:
                sample_data = data[sample_path]
                if 'value' in sample_data:
                    latest = sample_data['value'][-1]
                    x, y = latest[0], latest[1]
                elif 'x' in sample_data and 'y' in sample_data:
                    x, y = sample_data['x'][-1], sample_data['y'][-1]
                else:
                    raise MFLIHardwareError("Could not find X/Y in sample data")
                r = math.hypot(x, y)
                logging.info(f"Polled demod sample: X={x}, Y={y}, R={r}")
                return {'X': x, 'Y': y, 'R': r}
            else:
                raise MFLIHardwareError("No data received from demodulator")
        except Exception as e:
            logging.error(f"Failed to get demod sample: {e}")
            raise MFLIHardwareError(f"get_demod_sample failed: {e}")

    def get_X(self):
        return self.get_demod_sample()['X']

    def get_Y(self):
        return self.get_demod_sample()['Y']

    def get_R(self):
        return self.get_demod_sample()['R']

    # -------------- Disconnect --------------
    def disconnect(self):
        try:
            if self.daq:
                self.daq.disconnectDevice(self.device)
                self.daq.disconnect()
                logging.info("Disconnected from MFLI")
            else:
                logging.warning("No connection to disconnect from")
        except Exception as e:
            logging.warning(f"Error during disconnect: {e}")

    # -------------- Example: Full Setup --------------
    def setup_basic(self, freq=10e3, amp=0.5, out_range=1.0, demod_rate=1000, tau=0.01, order=1):
        """Convenience method to configure the lock-in for basic operation."""
        try:
            self.set_output_enable(True)
            self.set_amplitude(amp)
            self.set_output_range(out_range)
            self.set_frequency(freq)
            self.set_demod_osc(0)
            self.set_demod_adc(0)
            self.enable_demod(True)
            self.set_demod_rate(demod_rate)
            self.set_demod_timeconstant(tau)
            self.set_demod_order(order)
            self.sync()
            logging.info("Basic setup complete")
        except Exception as e:
            logging.error(f"Failed during basic setup: {e}")
            raise MFLIHardwareError(f"setup_basic failed: {e}")

def main():
    """Basic functional test for MFLI_Hardware, similar to SR860_Hardware main."""
    device_id = 'dev30037'  # Change to your device
    try:
        #print(MFLI_Hardware.get_available_devices())
        mfli = MFLI_Hardware(device_id)
        print('available devices:',mfli.get_available_devices())

        #print(f"Connecting to {device_id}...")
        #mfli = MFLI_Hardware(device_id)
        #print("Connected.")
        
        '''
        #mfli.set_frequency(osc_index = 0, f_hz = 1234.56)
        #print(mfli.get_frequency(osc_index = 0))
        #mfli.set_amplitude(v = 0.1, osc_index = 1)
        #print(mfli.get_amplitude(osc_index = 1))
        #mfli.set_output_enable(on = False)
        #print(mfli.get_output_enable())
        #mfli.set_output_range(rng = 1.0)
        #print(mfli.get_output_range())
        mfli.set_osc_output_enable(on = True, osc_index = 0)
        print(mfli.get_osc_output_enable(osc_index = 0))
        mfli.set_autorange(autorange = False)
        print(mfli.get_autorange())
        print(mfli.get_osc_output_enable(osc_index = 0))
        mfli.set_output_auto_range(auto_range = True)
        print(mfli.get_output_auto_range())
        mfli.set_differential_output(enable = True)
        print(mfli.get_differential_output())   
        '''

        '''mfli.set_demod_osc(osc_index = 0, demod_index = 0)
        set_demod_adc(self, adc_index=0)
        enable_demod(self, enable=True)
        set_demod_rate(self, rate=1000)
        set_demod_timeconstant(self, tau=0.01)
        set_demod_order(self, order=1)
        sync(self)
        get_demod_sample(self)
        get_X(self)
        get_Y(self)
        get_R(self)
        '''
        #disconnect(self)
        
        mfli.disconnect()
        print("Disconnected successfully.")
    except MFLIHardwareError as e:
        print(f"MFLI Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    main()
