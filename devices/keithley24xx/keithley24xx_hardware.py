import math
import time

from core.shared_runtime.visa import VisaResourceLease, VisaRuntime


class Keithly24xxHardware():
    NPLC_MIN = 0.01
    NPLC_MAX = 10.0

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

    @classmethod
    def validate_nplc(cls, value):
        """Return a finite NPLC value supported by both the 2400 and 2450."""
        if isinstance(value, bool):
            raise ValueError("NPLC must be a number, not a boolean")
        try:
            nplc = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid NPLC value: {value!r}") from exc
        if not math.isfinite(nplc):
            raise ValueError("NPLC must be finite")
        if not cls.NPLC_MIN <= nplc <= cls.NPLC_MAX:
            raise ValueError(
                f"NPLC must be between {cls.NPLC_MIN:g} and {cls.NPLC_MAX:g}"
            )
        return nplc

    def set_measurement_nplc(self, value):
        """Set one integration time for voltage and current measurements.

        The Keithley 2400 treats NPLC as a global setting. The 2450 can retain
        a value per measurement function, so both functions are programmed to
        keep behavior consistent when the UI switches between them.
        """
        nplc = self.validate_nplc(value)
        command_value = f"{nplc:.9g}"
        self.inst.write(f":SENS:VOLT:NPLC {command_value}")
        self.inst.write(f":SENS:CURR:NPLC {command_value}")
        return self.get_measurement_nplc()

    def get_measurement_nplc(self):
        """Return the voltage and current NPLC readbacks as a tuple."""
        voltage_nplc = self.validate_nplc(
            self.inst.query(":SENS:VOLT:NPLC?")
        )
        current_nplc = self.validate_nplc(
            self.inst.query(":SENS:CURR:NPLC?")
        )
        return voltage_nplc, current_nplc

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

