import opticool.opticool_dll as opticool_dll
import QuantumDesign
import System


class OptiCool_Hardware:
    def __init__(self):
        self.name = QuantumDesign.QDInstrument.QDInstrumentBase.QDInstrumentType.OptiCool
        self.instrument = None
        self.connected = False

        self.handle_field_mode = opticool_dll.dll.GetType(
            "QuantumDesign.QDInstrument.QDInstrumentBase+FieldMode"
        )
        self.field_mode = System.Activator.CreateInstance(self.handle_field_mode)

        self.handle_field_status = opticool_dll.dll.GetType(
            "QuantumDesign.QDInstrument.QDInstrumentBase+FieldStatus"
        )
        self.field_status = System.Activator.CreateInstance(self.handle_field_status)

        self.handle_field_approach = opticool_dll.dll.GetType(
            "QuantumDesign.QDInstrument.QDInstrumentBase+FieldApproach"
        )
        self.field_approach = System.Activator.CreateInstance(self.handle_field_approach)

        self.handle_temperature_status = opticool_dll.dll.GetType(
            "QuantumDesign.QDInstrument.QDInstrumentBase+TemperatureStatus"
        )
        self.temperature_status = System.Activator.CreateInstance(
            self.handle_temperature_status
        )

        self.handle_temperature_approach = opticool_dll.dll.GetType(
            "QuantumDesign.QDInstrument.QDInstrumentBase+TemperatureApproach"
        )
        self.temperature_approach = System.Activator.CreateInstance(    
            self.handle_temperature_approach
        )

    def connect_hardware(self):
        if self.connected and self.instrument is not None:
            return True

        self.instrument = QuantumDesign.QDInstrument.QDInstrumentFactory().GetQDInstrument(
            self.name, False
        )
        self.connected = self.instrument is not None
        return self.connected

    def disconnect(self):
        self.instrument = None
        self.connected = False
        return True

    def _require_connected(self):
        if not self.connected or self.instrument is None:
            raise RuntimeError("OptiCool is not connected.")
        return self.instrument

    def set_temperature(self, val, rate=20):
        instrument = self._require_connected()
        if val < 1.5 or val > 350:
            print("please enter a temperature between 1.5K and 350K")
        instrument.SetTemperature(val, rate, self.temperature_approach)

    def get_temperature(self):
        instrument = self._require_connected()
        val = 0.0
        [status, val, temperature_status] = instrument.GetTemperature(
            val, self.temperature_status
        )
        return [status, val, instrument.TemperatureStatusString(temperature_status)]

    def set_field(self, val, rate=150):
        instrument = self._require_connected()
        instrument.SetField(val, rate, self.field_approach, self.field_mode)

    def get_field(self):
        instrument = self._require_connected()
        val = 0.0
        [status, val, field_status] = instrument.GetField(val, self.field_status)

        return [status, val, instrument.FieldStatusString(field_status)]



if __name__ == "__main__":
    o = OptiCool_Hardware()
    if o.connect_hardware():
        print(o.get_field())
        print(o.get_temperature())
    