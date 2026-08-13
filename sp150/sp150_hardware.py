"""PyVISA transport for the SP150 monochromator."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any


class SP150Error(RuntimeError):
    """Base error for SP150 operations."""


class SP150ConnectionError(SP150Error):
    """Raised when an SP150 connection cannot be established."""


class SP150ProtocolError(SP150Error):
    """Raised when the SP150 returns an invalid response."""


class SP150Hardware:
    """Own one explicitly configured SP150 VISA session."""

    MIN_WAVELENGTH_NM = 0.0
    MAX_WAVELENGTH_NM = 3000.0

    def __init__(
        self, resource_manager_factory: Callable[[], Any] | None = None
    ) -> None:
        self._resource_manager_factory = resource_manager_factory
        self.resource_manager: Any | None = None
        self.instrument: Any | None = None
        self.address: str | None = None
        self.query_delay_s = 1.0

    @property
    def connected(self) -> bool:
        return self.instrument is not None

    def connect(
        self,
        address: str,
        timeout_ms: int = 10_000,
        query_delay_s: float = 1.0,
    ) -> bool:
        address = str(address).strip()
        if not address:
            raise ValueError("SP150 VISA address must be provided explicitly")
        if timeout_ms <= 0:
            raise ValueError("SP150 timeout_ms must be positive")
        query_delay = self._finite_value(query_delay_s, "query delay")
        if query_delay < 0:
            raise ValueError("SP150 query delay cannot be negative")
        if self.connected:
            if address == self.address:
                return True
            raise SP150ConnectionError(
                f"SP150 is already connected at {self.address}; disconnect first"
            )

        resource_manager = None
        instrument = None
        try:
            if self._resource_manager_factory is None:
                import pyvisa

                resource_manager = pyvisa.ResourceManager()
            else:
                resource_manager = self._resource_manager_factory()
            instrument = resource_manager.open_resource(address)
            instrument.read_termination = "\n"
            instrument.write_termination = "\r"
            instrument.timeout = int(timeout_ms)
        except Exception as exc:
            self._close_partial(instrument, resource_manager)
            raise SP150ConnectionError(
                f"Could not connect SP150 at {address}: {exc}"
            ) from exc

        self.resource_manager = resource_manager
        self.instrument = instrument
        self.address = address
        self.query_delay_s = query_delay
        return True

    def disconnect(self) -> None:
        instrument = self.instrument
        resource_manager = self.resource_manager
        self.instrument = None
        self.resource_manager = None
        self.address = None
        self._close_partial(instrument, resource_manager)

    close = disconnect

    def command_wavelength(self, wavelength_nm: float) -> None:
        value = self.validate_wavelength(wavelength_nm)
        instrument = self._require_connection()
        command = f"{value:.2f} <GOTO>"
        try:
            instrument.write(command)
        except Exception as exc:
            raise SP150ProtocolError(
                f"SP150 write failed for {command!r}: {exc}"
            ) from exc

    def read_wavelength(self) -> float:
        instrument = self._require_connection()
        try:
            response = instrument.query("?NM", delay=self.query_delay_s)
        except Exception as exc:
            raise SP150ProtocolError(f"SP150 wavelength query failed: {exc}") from exc
        try:
            value = float(str(response).strip())
        except (TypeError, ValueError) as exc:
            raise SP150ProtocolError(
                f"Invalid SP150 wavelength response: {response!r}"
            ) from exc
        if not math.isfinite(value):
            raise SP150ProtocolError(
                f"Invalid SP150 wavelength response: {response!r}"
            )
        return value

    @classmethod
    def validate_wavelength(cls, wavelength_nm: float) -> float:
        value = cls._finite_value(wavelength_nm, "wavelength")
        if not cls.MIN_WAVELENGTH_NM <= value <= cls.MAX_WAVELENGTH_NM:
            raise ValueError("SP150 wavelength must be between 0 and 3000 nm")
        return value

    def _require_connection(self) -> Any:
        if self.instrument is None:
            raise SP150ConnectionError("SP150 is not connected")
        return self.instrument

    @staticmethod
    def _finite_value(value: float, label: str) -> float:
        try:
            converted = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"SP150 {label} must be numeric") from exc
        if not math.isfinite(converted):
            raise ValueError(f"SP150 {label} must be finite")
        return converted

    @staticmethod
    def _close_partial(instrument: Any | None, resource_manager: Any | None) -> None:
        if instrument is not None:
            try:
                instrument.close()
            except Exception:
                pass
        if resource_manager is not None:
            try:
                resource_manager.close()
            except Exception:
                pass
