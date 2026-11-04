"""zcore.devices: the declarative device SDK (ADR 004).

A device author imports only this package and the device's own hardware
layer. A device is a declaration plus a driver::

    from zcore.devices import Choice, Device, MultiParameter, Parameter, Ramp, action
    from .sr860_hardware import SR860_Hardware

    class SR860(Device):
        driver_class = SR860_Hardware

        frequency = Parameter(float, unit="Hz", limits=(1e-3, 500e3),
                              get="get_frequency", set="set_frequency",
                              scan=True, snapshot=True, group="Reference")
        amplitude = Parameter(float, unit="V", limits=(0.0, 2.0),
                              get="get_amplitude", set="set_amplitude",
                              ramp=Ramp(rate=0.1), scan=True)
        outputs = MultiParameter(("X", "Y", "R", "Theta"), get="read_outputs",
                                 unit={"X": "V", "Y": "V", "R": "V", "Theta": "deg"})

        @action("Auto phase")
        def auto_phase(self):
            self.driver.set_auto_phase()

        def stop_hardware(self):
            ...

Declaration mistakes raise ``DeclarationError`` when the class is created.
``Device.spec()`` returns the immutable ``DeviceSpec``. Nothing in zmeter uses
this package yet; the Runner (PR 4) and the bridge (PR 7) build on it.

Same import rules as ``zcore``: no Qt, no ``core``, ``devices`` or ``zui``.
"""

from .declarations import (
    Action,
    ArrayParameter,
    Choice,
    Connection,
    DeclarationError,
    MultiParameter,
    Parameter,
    Ramp,
    Stable,
    Trigger,
    Unlimited,
    action,
    unlimited,
)
from .device import STANDARD_ACTIONS, Device, DeviceSpec

__all__ = [
    "Action",
    "ArrayParameter",
    "Choice",
    "Connection",
    "DeclarationError",
    "Device",
    "DeviceSpec",
    "MultiParameter",
    "Parameter",
    "Ramp",
    "STANDARD_ACTIONS",
    "Stable",
    "Trigger",
    "Unlimited",
    "action",
    "unlimited",
]
