from . import opticool_dll


class OptiCool_Hardware:
    def __init__(self):
        self.instrument = None
        self.connected = False
        self._clear_runtime_state()

    def _clear_runtime_state(self):
        self._vendor_dll = None
        self._quantum_design = None
        self._system = None
        self.name = None
        self.field_mode = None
        self.field_status = None
        self.field_approach = None
        self.temperature_status = None
        self.temperature_approach = None

    @staticmethod
    def _create_vendor_state(dll, quantum_design, system):
        name = (
            quantum_design.QDInstrument.QDInstrumentBase.QDInstrumentType.OptiCool
        )
        field_mode = system.Activator.CreateInstance(
            dll.GetType("QuantumDesign.QDInstrument.QDInstrumentBase+FieldMode")
        )
        field_status = system.Activator.CreateInstance(
            dll.GetType("QuantumDesign.QDInstrument.QDInstrumentBase+FieldStatus")
        )
        field_approach = system.Activator.CreateInstance(
            dll.GetType("QuantumDesign.QDInstrument.QDInstrumentBase+FieldApproach")
        )
        temperature_status = system.Activator.CreateInstance(
            dll.GetType(
                "QuantumDesign.QDInstrument.QDInstrumentBase+TemperatureStatus"
            )
        )
        temperature_approach = system.Activator.CreateInstance(
            dll.GetType(
                "QuantumDesign.QDInstrument.QDInstrumentBase+TemperatureApproach"
            )
        )
        return (
            name,
            field_mode,
            field_status,
            field_approach,
            temperature_status,
            temperature_approach,
        )

    def connect_hardware(self):
        if self.connected and self.instrument is not None:
            return True

        try:
            dll, quantum_design, system = opticool_dll.load_vendor_runtime()
            vendor_state = self._create_vendor_state(
                dll, quantum_design, system
            )
            instrument = (
                quantum_design.QDInstrument.QDInstrumentFactory()
                .GetQDInstrument(vendor_state[0], False)
            )
            if instrument is None:
                raise RuntimeError("OptiCool vendor factory returned no instrument")
        except Exception:
            self.instrument = None
            self.connected = False
            self._clear_runtime_state()
            raise

        self._vendor_dll = dll
        self._quantum_design = quantum_design
        self._system = system
        (
            self.name,
            self.field_mode,
            self.field_status,
            self.field_approach,
            self.temperature_status,
            self.temperature_approach,
        ) = vendor_state
        self.instrument = instrument
        self.connected = True
        return True

    def disconnect(self):
        self.instrument = None
        self.connected = False
        self._clear_runtime_state()
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
