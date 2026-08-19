import types
import logging
import time
import pyvisa


class SR830_Hardware:
    '''
    This is the python driver for the Lock-In SR830 from Stanford Research Systems.
    '''

    def __init__(self, address=None):
        '''
        Initializes the SR830.
        Input:
            address (string) : GPIB address
        Output:
            None
        '''
        if address:
            self.connect_visa(address)

    # Functions
    def connect_visa(self, address):
        self._address = address
        resource_manager = pyvisa.ResourceManager()
        # 'GPIB0::7::INSTR'
        self._visainstrument = resource_manager.open_resource(self._address)
        # self._instID = self._visainstrument.query("*IDN?")
        # print(self._instID)
        # for i in range(100):
            # self._visainstrument.read()


    def reset(self):
        '''
        Resets the instrument to default values
        Input:
            None
        Output:
            None
        '''
        self._visainstrument.write('*RST')
        self.get_all()

    def get_all(self):
        '''
        Reads all implemented parameters from the instrument,
        and updates the wrapper.
        Input:
            None
        Output:
            None
        '''
        logging.info(__name__ + ' : reading all settings from instrument')
        self.get_sensitivity()
        self.get_time_constant()
        self.get_frequency()
        self.get_amplitude()
        self.get_phase()
        self.get_X()
        self.get_Y()
        self.get_R()
        self.get_Theta()
        self.get_ref_input()
        self.get_ext_trigger()
        self.get_sync_filter()
        self.get_harmonic()
        self.get_input_config()
        self.get_input_shield()
        self.get_input_coupling()
        self.get_notch_filter()
        self.get_reserve()
        self.get_filter_slope()
        self.get_unlocked()
        self.get_input_overload()
        self.get_time_constant_overload()
        self.get_output_overload()

    def disable_front_panel(self):
        '''
        disable the front panel of the lock-in
        while being in remote control
        '''
        self._visainstrument.write('OVRM 0')

    def enable_front_panel(self):
        '''
        enables the front panel of the lock-in
        while being in remote control
        '''
        self._visainstrument.write('OVRM 1')

    def auto_phase(self):
        '''
        offsets the phase so that
        the Y component is zero
        '''
        self._visainstrument.write('APHS')

    def direct_output(self):
        '''
        select GPIB as interface
        '''
        self._visainstrument.write('OUTX 1')

    def read_output(self, output, ovl):
        '''
        Read out R,X,Y or phase (P) of the Lock-In
        Input:
            mode (int) :
            1 : "X",
            2 : "Y",
            3 : "R"
            4 : "P"
        '''
        parameters = {
            1: "X",
            2: "Y",
            3: "R",
            4: "P"
        }
        # self.direct_output()
        if parameters.__contains__(output):
            logging.info(__name__ + ' : Reading parameter from instrument: %s ' % parameters.get(output))
            if ovl:
                self.get_input_overload()
                self.get_time_constant_overload()
                self.get_output_overload()
            readvalue = float(self._visainstrument.query('OUTP?%s' % output))
        else:
            print('Wrong output requested.')
        return readvalue

    def get_X(self, ovl=False):
        '''
        Read out X of the Lock In
        Check for overloads if ovl is True
        '''
        return self.read_output(1, ovl)

    def get_Y(self, ovl=False):
        '''
        Read out Y of the Lock In
        Check for overloads if ovl is True
        '''
        return self.read_output(2, ovl)

    def get_R(self, ovl=False):
        '''
        Read out R of the Lock In
        Check for overloads if ovl is True
        '''
        return self.read_output(3, ovl)

    def get_Theta(self, ovl=False):
        '''
        Read out P of the Lock In
        Check for overloads if ovl is True
        '''
        return self.read_output(4, ovl)

    def set_frequency(self, frequency):
        '''
        Set frequency of the local oscillator
        Input:
            frequency (float) : frequency in Hz
        Output:
            None
        '''
        logging.debug(__name__ + ' : setting frequency to %s Hz' % frequency)
        self._visainstrument.write('FREQ %e' % frequency)

    def get_frequency(self):
        '''
        Get the frequency of the local oscillator
        Input:
            None
        Output:
            frequency (float) : frequency in Hz
        '''
        self.direct_output()
        logging.debug(__name__ + ' : reading frequency from instrument')
        return float(self._visainstrument.query('FREQ?'))

    def get_amplitude(self):
        '''
        Get the frequency of the local oscillator
        Input:
            None
        Output:
            frequency (float) : frequency in Hz
        '''
        self.direct_output()
        logging.debug(__name__ + ' : reading frequency from instrument')
        return float(self._visainstrument.query('SLVL?'))

    def set_mode(self, val):
        logging.debug(__name__ + ' : Setting Reference mode to external')
        self._visainstrument.write('FMOD %d' % val)

    def set_amplitude(self, amplitude):
        '''
        Set frequency of the local oscillator
        Input:
            frequency (float) : frequency in Hz
        Output:
            None
        '''
        logging.debug(__name__ + ' : setting amplitude to %s V' % amplitude)
        self._visainstrument.write('SLVL %e' % amplitude)

    def set_time_constant(self, timeconstant):
        '''
        Set the time constant of the LockIn
        Input:
            time constant (integer) : integer from 0 to 19
        Output:
            None
        '''

        self.direct_output()
        logging.debug(__name__ + ' : setting time constant on instrument to %s' % (timeconstant))
        self._visainstrument.write('OFLT %s' % timeconstant)

    def get_time_constant(self):
        '''
        Get the time constant of the LockIn
        Input:
            None
        Output:
            time constant (integer) : integer from 0 to 19
        '''

        self.direct_output()
        logging.debug(__name__ + ' : getting time constant on instrument')
        return float(self._visainstrument.query('OFLT?'))

    def set_sensitivity(self, sens):
        '''
        Set the sensitivity of the LockIn
        Input:
            sensitivity (integer) : integer from 0 to 26
        Output:
            None
        '''

        self.direct_output()
        logging.debug(__name__ + ' : setting sensitivity on instrument to %s' % (sens))
        self._visainstrument.write('SENS %d' % sens)

    def get_sensitivity(self):
        '''
        Get the sensitivity
            Output:
            sensitivity (integer) : integer from 0 to 26
        '''
        self.direct_output()
        logging.debug(__name__ + ' : reading sensitivity from instrument')
        return float(self._visainstrument.query('SENS?'))

    def get_phase(self):
        '''
        Get the reference phase shift
        Input:
            None
        Output:
            phase (float) : reference phase shit in degree
        '''
        self.direct_output()
        logging.debug(__name__ + ' : reading frequency from instrument')
        return float(self._visainstrument.query('PHAS?'))

    def set_phase(self, phase):
        '''
        Set the reference phase shift
        Input:
            phase (float) : reference phase shit in degree
        Output:
            None
        '''
        logging.debug(__name__ + ' : setting the reference phase shift to %s degree' % phase)
        self._visainstrument.write('PHAS %e' % phase)

    def set_aux(self, output, value):
        '''
        Set the voltage on the aux output
        Input:
            output - number 1-4 (defining which output you are addressing)
            value  - the voltage in Volts
        Output:
            None
        '''
        logging.debug(__name__ + ' : setting the output %(out)i to value %(val).3f' % {'out': output, 'val': value})
        self._visainstrument.write('AUXV %(out)i, %(val).3f' % {'out': output, 'val': value})

    def read_aux(self, output):
        '''
        Query the voltage on the aux output
        Input:
            output - number 1-4 (defining which output you are addressing)
        Output:
            voltage on the output D/A converter
        '''
        logging.debug(__name__ + ' : reading the output %i' % output)
        return float(self._visainstrument.query('AUXV? %i' % output))

    def get_oaux(self, value):
        '''
        Query the voltage on the aux output
        Input:
            output - number 1-4 (defining which output you are adressing)
        Output:
            voltage on the input A/D converter
        '''
        logging.debug(__name__ + ' : reading the input %i' % value)
        return float(self._visainstrument.query('OAUX? %i' % value))

    def set_out(self, value, channel):
        '''
        Set output voltage, rounded to nearest mV.
        '''
        self.set_aux(channel, value)

    def get_out(self, channel):
        '''
        Read output voltage.
        '''
        return self.read_aux(channel)

    def get_in(self, channel):
        '''
        Read input voltage, resolution is 1/3 mV.
        '''
        return self.get_oaux(channel)

    def get_ref_input(self):
        '''
        Query reference input: internal (true,1) or external (false,0)
        '''
        return int(self._visainstrument.query('FMOD?')) == 1

    def set_ref_input(self, value):
        '''
        Set reference input: internal (true,1) or external (false,0)
        '''
        if value:
            self._visainstrument.write('FMOD 1')
        else:
            self._visainstrument.write('FMOD 0')

    def get_ext_trigger(self):
        '''
        Query trigger source for external reference: sine (0), TTL rising edge (1), TTL falling edge (2)
        '''
        return int(self._visainstrument.query('RSLP?'))

    def set_ext_trigger(self, value):
        '''
        Set trigger source for external reference: sine (0), TTL rising edge (1), TTL falling edge (2)
        '''
        self._visainstrument.write('RSLP ' + str(value))

    def get_sync_filter(self):
        '''
        Query sync filter. Note: only available below 200Hz
        '''
        return int(self._visainstrument.query('SYNC?')) == 1

    def set_sync_filter(self, value):
        '''
        Set sync filter. Note: only available below 200Hz
        '''
        if value:
            self._visainstrument.write('SYNC 1')
        else:
            self._visainstrument.write('SYNC 0')

    def get_harmonic(self):
        '''
        Query detection harmonic in the range of 1..19999.
        Note: frequency*harmonic<102kHz
        '''
        return int(self._visainstrument.query('HARM?'))

    def set_harmonic(self, value):
        '''
        Set detection harmonic in the range of 1..19999.
        Note: frequency*harmonic<102kHz
        '''
        self._visainstrument.write('HARM ' + str(value))

    def get_input_config(self):
        '''
        Query input configuration: A (0), A-B (1), CVC 1MOhm (2), CVC 100MOhm (3)
        '''
        return int(self._visainstrument.query('ISRC?'))

    def set_input_config(self, value):
        '''
        Set input configuration: A (0), A-B (1), CVC 1MOhm (2), CVC 100MOhm (3)
        '''
        self._visainstrument.write('ISRC ' + str(value))

    def get_input_shield(self):
        '''
        Query input shield: float (false,0), gnd (true,1)
        '''
        return int(self._visainstrument.query('IGND?')) == 1

    def set_input_shield(self, value):
        '''
        Set input shield: float (false,0), gnd (true,1)
        '''
        if value:
            self._visainstrument.write('IGND 1')
        else:
            self._visainstrument.write('IGND 0')

    def get_input_coupling(self):
        '''
        Query input coupling: AC (false,0), DC (true,1)
        '''
        return int(self._visainstrument.query('ICPL?')) == 1

    def set_input_coupling(self, value):
        '''
        Set input coupling: AC (false,0), DC (true,1)
        '''
        if value:
            self._visainstrument.write('ICPL 1')
        else:
            self._visainstrument.write('ICPL 0')

    def get_notch_filter(self):
        '''
        Query notch filter: none (0), 1xline (1), 2xline(2), both (3)
        '''
        return int(self._visainstrument.query('ILIN?'))

    def set_notch_filter(self, value):
        '''
        Set notch filter: none (0), 1xline (1), 2xline(2), both (3)
        '''
        self._visainstrument.write('ILIN ' + str(value))

    def get_reserve(self):
        '''
        Query reserve: High reserve (0), Normal (1), Low noise (2)
        '''
        return int(self._visainstrument.query('RMOD?'))

    def set_reserve(self, value):
        '''
        Set reserve: High reserve (0), Normal (1), Low noise (2)
        '''
        self._visainstrument.write('RMOD ' + str(value))

    def get_filter_slope(self):
        '''
        Query filter slope: 6dB/oct. (0), 12dB/oct. (1), 18dB/oct. (2), 24dB/oct. (3)
        '''
        return int(self._visainstrument.query('OFSL?'))

    def set_filter_slope(self, value):
        '''
        Set filter slope: 6dB/oct. (0), 12dB/oct. (1), 18dB/oct. (2), 24dB/oct. (3)
        '''
        self._visainstrument.write('OFSL ' + str(value))

    def get_unlocked(self, update=True):
        '''
        Query if PLL is locked.
        Note: the status bit will be cleared after readout!
        Set update to True for querying present unlock situation, False for querying past events
        '''
        if update:
            self._visainstrument.query('LIAS? 3')  # for realtime detection we clear the bit by reading it
            time.sleep(0.02)  # and wait for a little while so that it can be set
        return int(self._visainstrument.query('LIAS? 3')) == 1

    def get_input_overload(self, update=True):
        '''
        Query if input or amplifier is in overload.
        Note: the status bit will be cleared after readout!
        Set update to True for querying present overload, False for querying past events
        '''
        if update:
            self._visainstrument.query('LIAS? 0')  # for realtime detection we clear the bit by reading it
            time.sleep(0.02)  # and wait for a little while so that it can be set again
        return int(self._visainstrument.query('LIAS? 0')) == 1

    def get_time_constant_overload(self, update=True):
        '''
        Query if filter is in overload.
        Note: the status bit will be cleared after readout!
        Set update to True for querying present overload, False for querying past events
        '''
        if update:
            self._visainstrument.query('LIAS? 1')  # for realtime detection we clear the bit by reading it
            time.sleep(0.02)  # and wait for a little while so that it can be set again
        return int(self._visainstrument.query('LIAS? 1')) == 1

    def get_output_overload(self, update=True):
        '''
        Query if output (also main display) is in overload.
        Note: the status bit will be cleared after readout!
        Set update to True for querying present overload, False for querying past events
        '''
        if update:
            self._visainstrument.query('LIAS? 2')  # for realtime detection we clear the bit by reading it
            time.sleep(0.02)  # and wait for a little while so that it can be set again
        return int(self._visainstrument.query('LIAS? 2')) == 1

    def disconnect(self):
        """Safely close the VISA resource.

        Before closing we attempt to clear the device buffer so that no
        outstanding responses remain in the queue. Any exceptions during
        cleanup are caught and ignored to ensure the application can
        continue shutting down gracefully.
        """
        if getattr(self, "_visainstrument", None) is None:
            return  # nothing to do

        try:
            # IEEE-488.2 device clear: flush buffers on the instrument side
            self._visainstrument.clear()  # type: ignore[attr-defined]
        except Exception:
            pass  # ignore issues during buffer clear

        try:
            self._visainstrument.close()  # type: ignore[attr-defined]
        except Exception:
            pass  # ignore errors if already closed

        self._visainstrument = None


if __name__ == "__main__":

    resource_manager = pyvisa.ResourceManager()
    print(resource_manager.list_resources())
    l1 = SR830_Hardware('GPIB0::8::INSTR')

    for i in range(10):
        a = l1.get_X()
        print(a)
