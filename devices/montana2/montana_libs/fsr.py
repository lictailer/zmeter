#!/usr/bin/env python3
#
"""
Class to simplify RESTful API communication with the FSR instrument.

Example usage:
 import fsr
 fsr = fsr.Fsr('192.168.1.123')

 # Shows how to use high-level methods for accessing common functions
 fsr.cooldown()
 fsr.set_platform_target_temperature(3.1)
 fsr.get_platform_temperature()
 fsr.get_platform_temperature_stability()
 fsr.warmup()

 # Shows how to use generic post/get/put methods for accessing any REST url/end-point
 fsr.call_method('/controller/methods/cooldown()')
 fsr.get_prop('/sampleChamber/temperatureControllers/platform/thermometer/sample')['sample']['temperature']
 fsr.set_prop('/controller/properties/platformTargetTemperature', 1.7)
"""
import sys
import os
from . import instrument
from . import genericcryostat

Ports = instrument.Rest_Ports


@genericcryostat.register
class Fsr(genericcryostat.GenericCryostat):
    def __init__(self, ip, version='v1', verbose=False, tunnel=False, port=Ports.chronos_hlm):
        super().__init__(ip=ip,
                         port=port,
                         version=version,
                         verbose=verbose,
                         tunnel=tunnel)

    def get_cold_head_pressure(self):
        return self.get_prop('/vacuumSystem/vacuumGauges/coldHeadPressure/properties/pressureSample')['pressureSample']['pressure']
    
    def get_sample_chamber_pressure(self):
        return self.get_prop('/vacuumSystem/vacuumGauges/sampleChamberPressure/properties/pressureSample')['pressureSample']['pressure']
