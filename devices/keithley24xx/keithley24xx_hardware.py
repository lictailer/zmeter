import time

from core.shared_runtime.visa import VisaResourceLease, VisaRuntime


class Keithly24xxHardware():
    def __init__(self, visa_runtime: VisaRuntime | None = None):
        self.visa_runtime = visa_runtime or VisaRuntime()
        self._visa_lease: VisaResourceLease | None = None
        self._visa_owner = f"Keithley24xx:{id(self):x}"
        self.inst = None
        
    def initialize(self,addr):
        lease = self.visa_runtime.open_resource(self._visa_owner, addr)
        inst = lease.resource
        # inst.write('sense:current:protection 1e-7')
        # inst.write(':source:voltage:range 100')
        try:
            inst.write(':source:delay 0.0')
            inst.write(':OUTP ON')
        except Exception:
            lease.close()
            raise
        self._visa_lease = lease
        self.inst=inst
        
    def set_sour_volt_to(self,val):
        self.inst.write(f':SOUR:VOLT:LEV {val}')

    def set_sour_curr_to(self,val):
        self.inst.write(f':SOUR:CURR:LEV {val}')

    def read(self):
        return self.inst.query('READ?')
    
    def reset(self):
        self.inst.write(':*RST')
        self.inst.write(':OUTP ON')

    def set_sour_func_to_volt(self,):
        self.inst.write(':OUTP OFF')
        self.inst.write(':SOUR:FUNC VOLT') #Select voltage source.
        self.inst.write(':SOUR:VOLT:MODE FIXED') #Fixed(DC) voltage source mode.
        self.inst.write(':SOUR:VOLT:RANG:AUTO ON')
        self.inst.write(':OUTP ON')

    def set_sour_func_to_curr(self,):
        self.inst.write(':OUTP OFF')
        self.inst.write(':SOUR:FUNC CURR')
        self.inst.write(':SOUR:CURR:MODE FIXED')
        self.inst.write(':SOUR:CURR:RANG:AUTO ON')
        self.inst.write(':OUTP ON')

    def set_sens_func_to_volt(self,compliance):
        self.inst.write(':SENS:FUNC "VOLT"')
        self.inst.write(f':SENS:VOLT:PROT {compliance}')
        self.inst.write(':SENS:VOLT:RANG:AUTO ON')
        self.inst.write(':FORM:ELEM VOLT') #Voltage reading only.

    def set_sens_func_to_curr(self,compliance):
        self.inst.write(':SENS:FUNC "CURR"')
        self.inst.write(f':SENS:CURR:PROT {compliance}')
        self.inst.write(':SENS:CURR:RANG:AUTO ON')
        self.inst.write(':FORM:ELEM CURR') #Current reading only.

    def close(self):
        """Safely close the VISA connection"""
        lease = self._visa_lease
        instrument = self.inst
        try:
            if instrument is not None:
                # Turn off output
                instrument.write(':OUTP OFF')
                # Clear any pending commands
                instrument.write('*CLS')
                print("Keithley24xx Hardware connection closed safely")
        except Exception as e:
            print(f"Error closing hardware connection: {e}")
        finally:
            if lease is not None:
                lease.close()
            elif instrument is not None:
                try:
                    instrument.close()
                except Exception:
                    pass
            self.inst = None
            self._visa_lease = None

    def ramp_voltage(self, target_voltage: float, ramp_rate: float, step_time: float = 0.0):
        """Ramp the source voltage to ``target_voltage`` at a given ``ramp_rate``.

        Parameters
        ----------
        target_voltage : float
            The final voltage to reach (in Volts).
        ramp_rate : float
            The rate at which to ramp in V/s. Must be positive.
        step_time : float, optional
            Time between successive voltage updates in seconds (default 0.1 s).
        """
        if ramp_rate <= 0:
            raise ValueError("Ramp rate must be positive")

        # Attempt to query the current voltage level
        try:
            current_voltage = float(self.inst.query(':SOUR:VOLT:LEV?'))
        except Exception:
            # If the instrument does not return a value, assume 0 V
            current_voltage = 0.0

        voltage_difference = target_voltage - current_voltage
        direction = 1 if voltage_difference >= 0 else -1
        step_size = ramp_rate * step_time * direction

        next_voltage = current_voltage
        while (direction == 1 and next_voltage < target_voltage) or (direction == -1 and next_voltage > target_voltage):
            next_voltage += step_size
            # Avoid overshooting the target
            if (direction == 1 and next_voltage > target_voltage) or (direction == -1 and next_voltage < target_voltage):
                next_voltage = target_voltage

            self.set_sour_volt_to(next_voltage)
            time.sleep(step_time)

        # Ensure we finish exactly at the target voltage
        self.set_sour_volt_to(target_voltage)


