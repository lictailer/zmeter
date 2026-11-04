"""Declarations of SR860-, SR830-, K10CR1-, nidaq-, auto_focus- and
attoDRY-like devices against fake drivers (phase 1, PR 3).

The fake drivers copy the method names and call shapes of the real hardware
layers (``devices/*/*_hardware.py``) without importing them, so the SDK is
checked against today's device patterns (ADR 004, decision 10) before anything
else uses it. Nothing here imports a device package or touches hardware.
"""

import unittest
from pathlib import Path

from zcore.devices import (
    ArrayParameter,
    Choice,
    Connection,
    Device,
    MultiParameter,
    Parameter,
    Ramp,
    Stable,
    Trigger,
    action,
    unlimited,
)


# --- SR860 lock-in: VISA driver built with an address, option-style methods ---


class FakeSR860Hardware:
    def __init__(self, address, visa_runtime=None):
        self.address = address
        self.state = {"frequency": 1000.0, "amplitude": 0.0, "phase": 0.0, "time_constant": 7}

    def get_frequency(self):
        return self.state["frequency"]

    def set_frequency(self, f_hz):
        self.state["frequency"] = f_hz

    def get_amplitude(self):
        return self.state["amplitude"]

    def set_amplitude(self, v_rms):
        self.state["amplitude"] = v_rms

    def phase(self, deg=None, write=False, read=False):
        if write:
            self.state["phase"] = deg
        return self.state["phase"]

    def time_constant(self, index=None, write=False, read=False):
        if write:
            self.state["time_constant"] = index
        return self.state["time_constant"]

    def get_multiple_outputs(self, *args):
        return tuple(float(i) for i, _ in enumerate(args))

    def set_auto_phase(self):
        pass

    def reset(self):
        pass

    def disconnect(self):
        pass


SR860_TIME_CONSTANTS = {"1 ms": 6, "3 ms": 7, "10 ms": 8, "30 ms": 9, "100 ms": 10}


class SR860Like(Device):
    driver_class = FakeSR860Hardware
    connection = Connection(str, timeout_s=5.0)

    def __init__(self, driver=None):
        super().__init__(driver)
        self.amplitude_ramp_rate_v_per_s = 0.1

    def _read_phase(self):
        return self.driver.phase(read=True)

    def _write_phase(self, deg):
        self.driver.phase(deg, write=True)

    def _read_ramp_rate(self):
        return self.amplitude_ramp_rate_v_per_s

    def _write_ramp_rate(self, rate):
        self.amplitude_ramp_rate_v_per_s = rate

    frequency = Parameter(float, unit="Hz", limits=(1e-3, 500e3),
                          get="get_frequency", set="set_frequency",
                          scan=True, snapshot=True, group="Reference")
    phase = Parameter(float, unit="deg", limits=(-360.0, 360.0),
                      get=_read_phase, set=_write_phase,
                      scan=True, snapshot=True, group="Reference")
    time_constant = Parameter(Choice(SR860_TIME_CONSTANTS),
                              get=lambda device: device.driver.time_constant(read=True),
                              set=lambda device, index: device.driver.time_constant(index, write=True),
                              snapshot=True, group="Filter")
    amplitude_ramp_rate = Parameter(float, unit="V/s", limits=(1e-3, 1.0),
                                    get=_read_ramp_rate, set=_write_ramp_rate, group="Output")
    amplitude = Parameter(float, unit="V", limits=(0.0, 2.0),
                          get="get_amplitude", set="set_amplitude",
                          ramp=Ramp("amplitude_ramp_rate"), safe=0.0, scan=True, group="Output")
    outputs = MultiParameter(
        ("X", "Y", "R", "Theta"),
        get=lambda device: device.driver.get_multiple_outputs("X", "Y", "R", "Theta"),
        unit={"X": "V", "Y": "V", "R": "V", "Theta": "deg"},
    )

    @action("Auto phase")
    def auto_phase(self):
        self.driver.set_auto_phase()

    def connect(self, address, timeout_s):
        if self.driver is None:
            self.driver = self.driver_class(address)

    def stop_hardware(self):
        # The amplitude ramp is stepped by the Runner; the instrument itself
        # has nothing in motion to stop.
        pass

    def reset(self):
        self.driver.reset()


# --- SR830 lock-in: no-argument constructor plus connect_visa(address) ---


class FakeSR830Hardware:
    def __init__(self, address=None, visa_runtime=None):
        self.front_panel = True

    def connect_visa(self, address):
        self.address = address

    def get_X(self, ovl=False):
        return 1e-6

    def get_Y(self, ovl=False):
        return 2e-6

    def get_sensitivity(self):
        return 20

    def set_sensitivity(self, sens):
        pass

    def get_frequency(self):
        return 77.7

    def set_frequency(self, frequency):
        pass

    def get_unlocked(self, update=True):
        return False

    def disable_front_panel(self):
        self.front_panel = False

    def enable_front_panel(self):
        self.front_panel = True

    def disconnect(self):
        pass


class SR830Like(Device):
    driver_class = FakeSR830Hardware

    X = Parameter(float, unit="V", get="get_X", scan=True, poll=0.5)
    Y = Parameter(float, unit="V", get="get_Y", scan=True, poll=0.5)
    frequency = Parameter(float, unit="Hz", limits=(1e-3, 102e3),
                          get="get_frequency", set="set_frequency", scan=True, snapshot=True)
    sensitivity = Parameter(Choice({"1 V": 26, "500 mV": 25, "200 mV": 24, "100 mV": 23, "20 uV": 11}),
                            get="get_sensitivity", set="set_sensitivity", snapshot=True)
    unlocked = Parameter(bool, get="get_unlocked", poll=1.0)

    def connect(self, address, timeout_s):
        if self.driver is None:
            self.driver = self.driver_class()
        self.driver.connect_visa(address)

    def set_display(self, on):
        if on:
            self.driver.enable_front_panel()
        else:
            self.driver.disable_front_panel()


# --- K10CR1 rotation mount: Kinesis driver built with a serial, long moves ---


class FakeK10CR1Hardware:
    def __init__(self, serial):
        self.serial = serial
        self.angle = 0.0

    def open(self, timeout_s):
        pass

    def close(self):
        pass

    def get_position(self):
        return self.angle

    def move_to(self, angle):
        self.angle = angle

    def get_velocity(self):
        return 5.0

    def set_velocity(self, velocity):
        pass

    def home(self):
        self.angle = 0.0

    def stop_immediate(self):
        pass


class K10CR1Like(Device):
    driver_class = FakeK10CR1Hardware
    connection = Connection(str, timeout_s=15.0)

    angle = Parameter(float, unit="deg", limits=(-360.0, 360.0),
                      get="get_position", set="move_to", scan=True, snapshot=True, timeout=60.0)
    velocity = Parameter(float, unit="deg/s", limits=(0.1, 10.0),
                         get="get_velocity", set="set_velocity", group="Motion")

    @action("Home", long=True)
    def home(self):
        self.driver.home()

    def connect(self, address, timeout_s):
        if self.driver is None:
            self.driver = self.driver_class(address)
        self.driver.open(timeout_s)

    def disconnect(self):
        self.driver.close()

    def stop_hardware(self):
        self.driver.stop_immediate()


# --- nidaq: two analog outputs with readback, an analog input, counter arrays ---


class FakeNIDAQHardware:
    def __init__(self):
        self.ao = {}

    def setup_single_AO_task(self, physical_channel):
        self.ao.setdefault(physical_channel, 0.0)

    def write_single_AO_task(self, physical_channel, AO_value):
        self.ao[physical_channel] = AO_value

    def read_single_AI_task(self, physical_channel):
        return 0.25

    def get_counts(self, samples=None):
        return [0] * 8

    def counts_shape(self):
        return (8,)

    def close_all(self):
        pass


class NIDAQLike(Device):
    driver_class = FakeNIDAQHardware
    connection = Connection(str, timeout_s=2.0)

    AO0 = Parameter(float, unit="V", limits=(-10.0, 10.0),
                    get=lambda device: device.driver.ao["Dev1/ao0"],
                    set=lambda device, value: device.driver.write_single_AO_task("Dev1/ao0", value),
                    scan=True, safe=0.0)
    AO1 = Parameter(float, unit="V", limits=(-10.0, 10.0),
                    get=lambda device: device.driver.ao["Dev1/ao1"],
                    set=lambda device, value: device.driver.write_single_AO_task("Dev1/ao1", value),
                    scan=True, safe=0.0)
    AI0 = Parameter(float, unit="V", get=lambda device: device.driver.read_single_AI_task("Dev1/ai0"),
                    scan=True)
    counts = ArrayParameter(("sample",), "counts_shape", unit="counts", get="get_counts", timeout=10.0)

    def connect(self, address, timeout_s):
        if self.driver is None:
            self.driver = self.driver_class()
        for channel in ("Dev1/ao0", "Dev1/ao1"):
            self.driver.setup_single_AO_task(channel)

    def disconnect(self):
        self.driver.close_all()

    def write_many(self, values):
        for name, value in values.items():
            self.driver.write_single_AO_task(f"Dev1/{name.lower()}", value)


# --- auto_focus-like: a trigger channel and panel settings ---


class FakeFocusDriver:
    def __init__(self):
        self.focus_runs = 0
        self.reference_map = Path("reference.json")

    def connect(self, address, timeout_s):
        pass

    def disconnect(self):
        pass

    def run_autofocus(self):
        self.focus_runs += 1

    def abort(self):
        pass


class AutoFocusLike(Device):
    driver_class = FakeFocusDriver

    focus = Trigger("run_autofocus", long=True)
    reference_map = Parameter(Path,
                              get=lambda device: device.driver.reference_map,
                              set=lambda device, path: setattr(device.driver, "reference_map", path))

    def stop_hardware(self):
        self.driver.abort()


# --- attoDRY-like cryostat: setpoint that waits until stable ---


class FakeCryostatDriver:
    def connect(self, address, timeout_s):
        pass

    def disconnect(self):
        pass

    def get_temperature(self):
        return 4.2

    def set_temperature(self, kelvin):
        pass

    def get_pressure(self):
        return 1e-6


class CryostatLike(Device):
    driver_class = FakeCryostatDriver

    T = Parameter(float, unit="K", limits=(1.5, 300.0), get="get_temperature", set="set_temperature",
                  stable=Stable(tolerance=0.05, duration_s=60.0, timeout_s=3600.0), scan=True, poll=2.0)
    pressure = Parameter(float, unit="mbar", get="get_pressure", poll=5.0)
    heater_power = Parameter(float, unit="W", set=lambda device, watts: None,
                             limits=unlimited("firmware clamps heater power"))


class ExampleDeviceTests(unittest.TestCase):
    def test_sr860_like(self):
        spec = SR860Like.spec()
        self.assertEqual(spec.readouts, ("frequency", "phase", "amplitude", "X", "Y", "R", "Theta"))
        # Frequency and phase become scannable, which the old widget-driven setters were not.
        self.assertEqual(spec.controls, ("frequency", "phase", "amplitude"))
        self.assertEqual(spec.snapshot, ("frequency", "phase", "time_constant"))
        self.assertEqual(tuple(spec.actions), ("auto_phase",))
        self.assertEqual(spec.standard_actions, ("reset",))
        self.assertTrue(spec.has_stop_hardware)
        self.assertEqual(spec.parameters["amplitude"].ramp, Ramp("amplitude_ramp_rate"))
        self.assertEqual(spec.multis["outputs"].unit_of("Theta"), "deg")
        self.assertEqual(spec.connection.timeout_s, 5.0)

        # Callables receive the device; strings name driver methods.
        device = SR860Like()
        device.connect("TCPIP0::192.0.2.1::INSTR", 5.0)
        phase = spec.parameters["phase"]
        phase.set(device, 45.0)
        self.assertEqual(phase.get(device), 45.0)
        time_constant = spec.parameters["time_constant"]
        time_constant.set(device, SR860_TIME_CONSTANTS["10 ms"])
        self.assertEqual(time_constant.get(device), 8)
        self.assertEqual(spec.multis["outputs"].get(device), (0.0, 1.0, 2.0, 3.0))
        self.assertEqual(getattr(device.driver, spec.parameters["frequency"].get)(), 1000.0)

    def test_sr830_like(self):
        spec = SR830Like.spec()
        self.assertEqual(spec.readouts, ("X", "Y", "frequency"))
        self.assertEqual(spec.controls, ("frequency",))
        self.assertEqual(spec.snapshot, ("frequency", "sensitivity"))
        self.assertEqual(spec.standard_actions, ("set_display",))
        self.assertFalse(spec.has_stop_hardware)
        self.assertEqual(spec.parameters["sensitivity"].dtype.labels[0], "1 V")

        device = SR830Like()
        device.connect("GPIB0::8::INSTR", 10.0)
        device.set_display(False)
        self.assertFalse(device.driver.front_panel)

    def test_k10cr1_like(self):
        spec = K10CR1Like.spec()
        self.assertEqual(spec.readouts, ("angle",))
        self.assertEqual(spec.controls, ("angle",))
        self.assertTrue(spec.actions["home"].long)
        self.assertTrue(spec.has_stop_hardware)
        self.assertEqual(spec.parameters["angle"].timeout, 60.0)

        fake = FakeK10CR1Hardware("55000001")
        device = K10CR1Like(driver=fake)
        device.connect("55000001", 15.0)
        device.disconnect()
        self.assertIs(device.driver, fake)

    def test_nidaq_like(self):
        spec = NIDAQLike.spec()
        self.assertEqual(spec.readouts, ("AO0", "AO1", "AI0"))
        self.assertEqual(spec.controls, ("AO0", "AO1"))
        self.assertEqual(tuple(spec.arrays), ("counts",))
        self.assertTrue(spec.has_write_many)
        self.assertEqual({name: spec.parameters[name].safe for name in ("AO0", "AO1")},
                         {"AO0": 0.0, "AO1": 0.0})

        device = NIDAQLike()
        device.connect("Dev1", 2.0)
        device.write_many({"AO0": 1.0, "AO1": -1.0})
        self.assertEqual(spec.parameters["AO1"].get(device), -1.0)

    def test_auto_focus_like_trigger(self):
        spec = AutoFocusLike.spec()
        self.assertEqual(spec.controls, ("focus",))
        self.assertEqual(spec.readouts, ())
        self.assertTrue(spec.triggers["focus"].long)
        device = AutoFocusLike(driver=FakeFocusDriver())
        getattr(device.driver, spec.triggers["focus"].call)()
        self.assertEqual(device.driver.focus_runs, 1)
        spec.parameters["reference_map"].set(device, Path("other.json"))
        self.assertEqual(spec.parameters["reference_map"].get(device), Path("other.json"))

    def test_cryostat_like_stable_and_unlimited(self):
        spec = CryostatLike.spec()
        self.assertEqual(spec.parameters["T"].stable.duration_s, 60.0)
        self.assertEqual(spec.controls, ("T",))
        self.assertEqual(spec.readouts, ("T",))
        self.assertEqual(spec.parameters["heater_power"].limits.reason, "firmware clamps heater power")


if __name__ == "__main__":
    unittest.main()
