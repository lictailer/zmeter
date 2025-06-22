import numpy as np
from pylablib.devices import Attocube


class ANC300Hardware:
    def __init__(self):
        self.anc300_port = "Com3"

    def initialize(self, port="Com3"):
        try:
            self.anc300 = Attocube.ANC300(port)
            print(f"ANC300 initialized on port {port}")
            mode_info = self.anc300.get_mode(axis='all')
            print(f"ANC300 current mode info: {mode_info}")
            return True
        except Exception as e:
            print(f"Error initializing ANC300: {e}")
            self.anc300 = None
            return False
        
    def close(self):
        self.anc300.close()
    
    #----------------------------- Positioner Axis Control ----------------------------
    def set_anm150_mode_to_stp(self, axis):
        self.anc300.enable_axis(axis=axis, mode="stp")

    def set_anm150_ground(self, axis):
        self.anc300.enable_axis(axis=axis, mode="gnd")

    def set_anm150_step_volt(self, axis, voltage):
        self.anc300.set_voltage(axis, voltage)

    def set_anm150_freq(self, axis, frequency):
        self.anc300.set_frequency(axis, frequency)

    def get_anm150_step_volt(self, axis):
        return self.anc300.get_voltage(axis)
    
    def get_anm150_freq(self, axis):
        return self.anc300.get_frequency(axis)
    
    def anm150_moveby(self, axis, steps):
        self.anc300.move_by(axis, steps)

    def get_anm150_capacitance(self, axis):
        return self.anc300.get_capacitance(axis, measure=True)
    
    def get_anm150_mode(self, axis):
        return self.anc300.get_mode(axis)
    
    def get_anm150_step_volt(self, axis):
        return self.anc300.get_voltage(axis)
    
    #----------------------------- Scanner Axis Control ----------------------------
    def set_anm200_mode_to_inp(self, axis):
        self.anc300.enable_axis(axis=axis, mode='inp')

    def set_anm200_ground(self, axis):
        self.anc300.enable_axis(axis=axis, mode='gnd')

    def turnOn_anm200_dcin(self, axis):
        self.anc300.query("setdci {} on".format(axis))

    def turnOff_anm200_dcin(self, axis):
        self.anc300.query("setdci {} off".format(axis))  

    def get_anm200_capacitance(self, axis):
        return self.anc300.get_capacitance(axis, measure=True)
    
    def get_anm200_mode(self, axis):
        return self.anc300.get_mode(axis)
    




if __name__ == "__main__":
    anc300_hw = ANC300Hardware()
    anc300_hw.initialize(port="COM3")

    # Example usage
    anc300_hw.set_anm150_mode(axis='1')
    anc300_hw.set_anm150_step_volt(axis='1', voltage=1.0)
    anc300_hw.set_anm150_freq(axis='1', frequency=100)
    print("Current voltage on axis x:", anc300_hw.get_anm150_step_volt(axis='x'))

    anc300_hw.anm150_moveby(axis='1', steps=100)
    print("Voltage on channel 5:", anc300_hw.read_voltage(channel=5))

    anc300_hw.close()