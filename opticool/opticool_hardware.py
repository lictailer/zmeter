from time import sleep
import opticool.opticool_dll as opticool_dll
import QuantumDesign
import System


class OptiCool_Hardware:

    name = QuantumDesign.QDInstrument.QDInstrumentBase.QDInstrumentType.OptiCool
    Instrument = QuantumDesign.QDInstrument.QDInstrumentFactory().GetQDInstrument(name, False)

    handleFieldMode = opticool_dll.dll.GetType('QuantumDesign.QDInstrument.QDInstrumentBase+FieldMode')
    FieldMode = System.Activator.CreateInstance(handleFieldMode)

    handleFieldStatus = opticool_dll.dll.GetType('QuantumDesign.QDInstrument.QDInstrumentBase+FieldStatus')
    FieldStatus = System.Activator.CreateInstance(handleFieldStatus)

    handleFieldApproach = opticool_dll.dll.GetType('QuantumDesign.QDInstrument.QDInstrumentBase+FieldApproach')
    FieldApproach = System.Activator.CreateInstance(handleFieldApproach)

    handleTemperatureStatus = opticool_dll.dll.GetType('QuantumDesign.QDInstrument.QDInstrumentBase+TemperatureStatus')
    TemperatureStatus = System.Activator.CreateInstance(handleTemperatureStatus)

    handleTemperatureApproach = opticool_dll.dll.GetType('QuantumDesign.QDInstrument.QDInstrumentBase+TemperatureApproach')
    TemperatureApproach = System.Activator.CreateInstance(handleTemperatureApproach)
    # print(FieldMode, FieldStatus, FieldApproach, TemperatureStatus, TemperatureApproach)

    def set_temperature(self, val, rate=20):
        if val < 1.5 or val > 350:
            print("please enter a temperature between 1.5K and 350K")
        self.Instrument.SetTemperature(val, rate, self.TemperatureApproach)

    def get_temperature(self):
        val = 0.0
        [status, val, TemperatureStatus] = self.Instrument.GetTemperature(val, self.TemperatureStatus)
        return [status, val, self.Instrument.TemperatureStatusString(TemperatureStatus)]

    def set_field(self, val, rate=150):
        self.Instrument.SetField(val, rate, self.FieldApproach, self.FieldMode)

    def get_field(self):
        val = 0.0
        [status, val, FieldStatus] = self.Instrument.GetField(val, self.FieldStatus)

        return [status, val, self.Instrument.FieldStatusString(FieldStatus)]### changed here 23_02_09



if __name__ == "__main__":
    import time

    o = OptiCool_Hardware()

    print(o.get_field())
    print(o.get_temperature())
