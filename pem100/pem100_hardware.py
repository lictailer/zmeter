"""PyVISA transport for the PEM100 photoelastic modulator."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import Any


class PEM100Error(RuntimeError):
    """Base error for PEM100 operations."""


class PEM100ConnectionError(PEM100Error):
    """Raised when a PEM100 connection cannot be established."""


class PEM100ProtocolError(PEM100Error):
    """Raised when the PEM100 returns an invalid response."""


class PEM100OperationCancelled(PEM100Error):
    """Raised when a cooperative PEM100 operation is cancelled."""


class PEM100Hardware:
    """Own one explicitly configured PEM100 VISA session."""

    MIN_WAVELENGTH_NM = 170.0
    MAX_WAVELENGTH_NM = 2500.0
    MIN_RETARDANCE_LAMBDA = 0.0
    MAX_RETARDANCE_LAMBDA = 0.5

    def __init__(
        self,
        resource_manager_factory: Callable[[], Any] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._resource_manager_factory = resource_manager_factory
        self._sleep = sleep
        self.resource_manager: Any | None = None
        self.instrument: Any | None = None
        self.address: str | None = None

    @property
    def connected(self) -> bool:
        return self.instrument is not None

    def connect(self, address: str, timeout_ms: int = 20_000) -> bool:
        address = str(address).strip()
        if not address:
            raise ValueError("PEM100 VISA address must be provided explicitly")
        if timeout_ms <= 0:
            raise ValueError("PEM100 timeout_ms must be positive")
        if self.connected:
            if address == self.address:
                return True
            raise PEM100ConnectionError(
                f"PEM100 is already connected at {self.address}; disconnect first"
            )

        resource_manager = None
        instrument = None
        try:
            if self._resource_manager_factory is None:
                import pyvisa
                from pyvisa import constants

                resource_manager = pyvisa.ResourceManager()
                parity_none = constants.Parity.none
                stop_bits_one = constants.StopBits.one
                flow_none = constants.VI_ASRL_FLOW_NONE
            else:
                resource_manager = self._resource_manager_factory()
                parity_none = 0
                stop_bits_one = 10
                flow_none = 0

            instrument = resource_manager.open_resource(
                address,
                baud_rate=2400,
                data_bits=8,
                parity=parity_none,
                stop_bits=stop_bits_one,
                flow_control=flow_none,
            )
            instrument.read_termination = "\n\r*"
            instrument.write_termination = "\r\n"
            instrument.timeout = int(timeout_ms)
        except Exception as exc:
            self._close_partial(instrument, resource_manager)
            raise PEM100ConnectionError(
                f"Could not connect PEM100 at {address}: {exc}"
            ) from exc

        self.resource_manager = resource_manager
        self.instrument = instrument
        self.address = address
        return True

    def disconnect(self) -> None:
        instrument = self.instrument
        resource_manager = self.resource_manager
        self.instrument = None
        self.resource_manager = None
        self.address = None
        self._close_partial(instrument, resource_manager)

    close = disconnect

    def set_wavelength(
        self,
        wavelength_nm: float,
        cancel_event: threading.Event | None = None,
    ) -> None:
        value = self._finite_value(wavelength_nm, "wavelength")
        if not self.MIN_WAVELENGTH_NM <= value <= self.MAX_WAVELENGTH_NM:
            raise ValueError("PEM100 wavelength must be between 170 and 2500 nm")
        command_value = int(value * 10)
        self._write(f"W:{command_value:06d}")
        self._read_acknowledgement(cancel_event)

    def set_retardance(
        self,
        retardance_lambda: float,
        cancel_event: threading.Event | None = None,
    ) -> None:
        value = self._finite_value(retardance_lambda, "retardance")
        if not self.MIN_RETARDANCE_LAMBDA <= value <= self.MAX_RETARDANCE_LAMBDA:
            raise ValueError("PEM100 retardance must be between 0 and 0.5 lambda")
        command_value = int(value * 1000)
        self._write(f"R:{command_value:04d}")
        self._read_acknowledgement(cancel_event)

    def get_wavelength(
        self, cancel_event: threading.Event | None = None
    ) -> float:
        self._write("W")
        self._wait(0.2, cancel_event)
        response = self._read("wavelength")
        self._wait(0.01, cancel_event)
        try:
            return int(response.strip()) / 10.0
        except (TypeError, ValueError) as exc:
            raise PEM100ProtocolError(
                f"Invalid PEM100 wavelength response: {response!r}"
            ) from exc

    def get_retardance(
        self, cancel_event: threading.Event | None = None
    ) -> float:
        self._write("R")
        self._wait(0.2, cancel_event)
        response = self._read("retardance")
        self._wait(0.2, cancel_event)
        try:
            return int(response.strip()) / 1000.0
        except (TypeError, ValueError) as exc:
            raise PEM100ProtocolError(
                f"Invalid PEM100 retardance response: {response!r}"
            ) from exc

    def _read_acknowledgement(
        self, cancel_event: threading.Event | None
    ) -> str:
        self._wait(0.2, cancel_event)
        response = self._read("acknowledgement")
        self._wait(0.2, cancel_event)
        if not isinstance(response, str):
            raise PEM100ProtocolError(
                f"Invalid PEM100 acknowledgement: {response!r}"
            )
        return response

    def _write(self, command: str) -> None:
        instrument = self._require_connection()
        try:
            instrument.write(command)
        except Exception as exc:
            raise PEM100ProtocolError(
                f"PEM100 write failed for {command!r}: {exc}"
            ) from exc

    def _read(self, operation: str) -> str:
        instrument = self._require_connection()
        try:
            return instrument.read()
        except Exception as exc:
            raise PEM100ProtocolError(
                f"PEM100 {operation} read failed: {exc}"
            ) from exc

    def _require_connection(self) -> Any:
        if self.instrument is None:
            raise PEM100ConnectionError("PEM100 is not connected")
        return self.instrument

    def _wait(
        self, seconds: float, cancel_event: threading.Event | None
    ) -> None:
        if cancel_event is None:
            self._sleep(seconds)
            return
        if cancel_event.wait(seconds):
            raise PEM100OperationCancelled("PEM100 operation cancelled")

    @staticmethod
    def _finite_value(value: float, label: str) -> float:
        try:
            converted = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"PEM100 {label} must be numeric") from exc
        if not math.isfinite(converted):
            raise ValueError(f"PEM100 {label} must be finite")
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
