"""demo_device.dummy_visa

Light-weight stand-in for PyVISA that lets you run *DemoDeviceHardware* and
*DemoDeviceLogic* without physical hardware attached.  It implements the subset
of the VISA API used by our drivers: ``ResourceManager`` → ``open_resource``
returning an object that exposes ``write`` and ``query``.

Usage example
-------------
>>> import pyvisa
>>> from demo_device.dummy_visa import patch_pyvisa
>>> patch_pyvisa()  # monkey-patches the real pyvisa module
>>> from demo_device.demoDevice_hardware import DemoDeviceHardware
>>> dev = DemoDeviceHardware("DUMMY::INSTR")
>>> print(dev.idn())
DemoDevice,Simulated,1.0
>>> dev.operating_mode("remote", write=True)
>>> print(dev.operating_mode(read=True))
remote
>>> dev.voltage_level(1.234, write=True)
>>> print(dev.voltage_level(read=True))
1.234

The dummy driver tracks MODE and VOLT commands internally so you can verify
logic end-to-end, including the Qt GUI.
"""

from __future__ import annotations

from typing import Tuple
import random

# -----------------------------------------------------------------------------
# Dummy VISA instrument implementation
# -----------------------------------------------------------------------------
class _DummyInstrument:
    """Simulated VISA instrument supporting basic SCPI subset."""

    # attributes that DemoDeviceHardware expects to set
    write_termination: str = "\n"
    read_termination: str = "\n"
    timeout: int = 100  # milliseconds

    def __init__(self):
        self._mode: int = 0  # 0=local, 1=remote, 2=lockout (see DemoDeviceLogic.MODES)
        self._voltage: float = 0.0

    # ---------------- SCPI helpers ----------------
    def write(self, cmd: str):  # noqa: D401 – keep simple signature
        cmd = cmd.strip()
        parts = cmd.split()
        if not parts:
            return
        if parts[0] == "MODE" and len(parts) == 2:
            self._mode = int(parts[1])
        elif parts[0] == "VOLT" and len(parts) == 2:
            self._voltage = float(parts[1])
        # ignore unknown commands – real instruments often do

    def query(self, cmd: str) -> str:  # noqa: D401 – keep simple signature
        cmd = cmd.strip()
        if cmd == "*IDN?":
            return "DemoDevice,Simulated,1.0"
        if cmd == "MODE?":
            return str(self._mode)
        if cmd == "VOLT?":
            return f"{self._voltage + random.random()*self._voltage/10}"  # already string
        # default fall-back
        return "0"

    # ---------------- housekeeping ----------------
    def clear(self):  # type: ignore[empty-body]
        """No-op for compatibility."""
        pass

    def close(self):  # type: ignore[empty-body]
        """No-op for compatibility."""
        pass


# -----------------------------------------------------------------------------
# Dummy ResourceManager exposing open_resource / list_resources
# -----------------------------------------------------------------------------
class DummyResourceManager:
    """Drop-in replacement for ``pyvisa.ResourceManager``."""

    def open_resource(self, address: str, *_, **__) -> _DummyInstrument:  # noqa: D401
        # address is ignored – always return a fresh dummy instrument
        return _DummyInstrument()

    # PyVISA returns a tuple of resource strings
    def list_resources(self) -> Tuple[str, ...]:  # noqa: D401
        return ("DUMMY::INSTR",)


# -----------------------------------------------------------------------------
# Helper to monkey-patch the *pyvisa* module in-place
# -----------------------------------------------------------------------------

def patch_pyvisa() -> None:
    """Replace ``pyvisa.ResourceManager`` with :class:`DummyResourceManager`."""
    import sys
    import types

    try:
        import pyvisa  # type: ignore
    except ModuleNotFoundError:
        # create a fake *pyvisa* module so importers succeed
        pyvisa = types.ModuleType("pyvisa")  # type: ignore
        sys.modules["pyvisa"] = pyvisa  # type: ignore

    pyvisa.ResourceManager = DummyResourceManager  # type: ignore[attr-defined]

    # Ensure callers can instantiate directly: ``pyvisa.ResourceManager()``
    sys.modules["pyvisa"].ResourceManager = DummyResourceManager  # type: ignore 