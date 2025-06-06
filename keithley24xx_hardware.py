import pyvisa


class Keithly24xxHardware():
    def __init__(self):
        addr='GPIB0::23::INSTR'
        
    def initialize(self,addr):
        resource_manager = pyvisa.ResourceManager()
        inst = resource_manager.open_resource(addr)
        # inst.write('sense:current:protection 1e-7')
        # inst.write(':source:voltage:range 100')
        inst.write(':source:delay 0.0')
        inst.write(':OUTP ON')
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


if __name__=="__main__":

    k=Keithly24xxHardware()
    k.initialize(addr='GPIB1::19::INSTR')

    k.set_sour_func_to_volt()
    k.set_sour_volt_to(0.01)
    k.set_sens_func_to_curr(compliance=1)
    print(k.read())

    k.set_sour_func_to_curr()
    k.set_sour_curr_to()
    k.set_sens_func_to_volt(compliance=20)
    print(k.read())


