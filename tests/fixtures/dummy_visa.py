"""Test fixture: dummy_visa

Light-weight stand-in for PyVISA for hardware-free tests. ``DummyResourceManager``
implements the subset of the VISA API the shared runtime tests use
(``open_resource`` returning an object with ``write`` and ``query``) and is
injected into ``VisaRuntime``; it never monkey-patches the real :mod:`pyvisa`
module or process-global imports. ``DummyVisaHardware`` is a minimal hardware
class that leases a resource from the runtime, like the maintained drivers.

Usage example
-------------
>>> from core.shared_runtime.visa import VisaRuntime
>>> from tests.fixtures.dummy_visa import DummyResourceManager, DummyVisaHardware
>>> runtime = VisaRuntime(manager_factory=DummyResourceManager)
>>> dev = DummyVisaHardware("DUMMY::INSTR", runtime)
>>> print(dev.idn())
DummyInstrument,Simulated,1.0
>>> dev.disconnect()

The dummy instrument tracks MODE and VOLT commands internally.
"""

from __future__ import annotations

from typing import Tuple
import random

from core.shared_runtime.visa import VisaRuntime

# -----------------------------------------------------------------------------
# Dummy VISA instrument implementation
# -----------------------------------------------------------------------------
class _DummyInstrument:
    """Simulated VISA instrument supporting basic SCPI subset."""

    # attributes that drivers set after opening a resource
    write_termination: str = "\n"
    read_termination: str = "\n"
    timeout: int = 100  # milliseconds

    def __init__(self):
        self._mode: int = 0  # 0=local, 1=remote, 2=lockout
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
            return "DummyInstrument,Simulated,1.0"
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
    def list_resources(self, _query="?*::INSTR") -> Tuple[str, ...]:  # noqa: D401
        return ("DUMMY::INSTR",)

    def close(self):
        """No-op manager shutdown for the in-process simulator."""
        pass


class DummyVisaHardware:
    """Minimal hardware class that leases a resource from a ``VisaRuntime``."""

    def __init__(self, address: str, visa_runtime: VisaRuntime):
        self._lease = visa_runtime.open_resource(
            f"DummyVisaHardware:{id(self):x}", address
        )
        self._instrument = self._lease.resource

    def idn(self) -> str:
        return self._instrument.query("*IDN?").strip()

    def disconnect(self) -> None:
        if self._lease is not None:
            self._lease.close()
        self._lease = None
        self._instrument = None
