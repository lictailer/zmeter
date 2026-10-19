"""Serial transport for the Thorlabs MC2000B optical chopper."""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable
from typing import Any


class MC2000BError(RuntimeError):
    """Base error for MC2000B operations."""


class MC2000BConnectionError(MC2000BError):
    """Raised when an MC2000B connection cannot be established."""


class MC2000BProtocolError(MC2000BError):
    """Raised for a timeout, malformed response, or device-reported error."""


class MC2000BHardware:
    """Own one explicitly configured MC2000B USB serial session."""

    BAUD_RATE = 115_200
    MIN_FREQUENCY_HZ = 1
    MAX_FREQUENCY_HZ = 10_000
    MIN_PHASE_DEG = 0
    MAX_PHASE_DEG = 360
    MC1F10HP_BLADE_INDEX = 6
    INTERNAL_OUTER_REFERENCE = 0
    INTERNAL_INNER_REFERENCE = 1
    _PROMPT_PATTERN = re.compile(r"[\r\n]*>\s*$")

    def __init__(
        self,
        serial_factory: Callable[..., Any] | None = None,
        timeout_s: float = 0.5,
    ) -> None:
        self._serial_factory = serial_factory
        self.timeout_s = self._positive_finite(timeout_s, "serial timeout")
        self._serial: Any | None = None
        self.address: str | None = None
        self.identity: str | None = None
        self._io_lock = threading.RLock()

    @property
    def connected(self) -> bool:
        return self._serial is not None

    def connect(self, address: str) -> bool:
        address = str(address).strip()
        if not address:
            raise ValueError("MC2000B COM port must be provided explicitly")
        with self._io_lock:
            if self.connected:
                if address == self.address:
                    return True
                raise MC2000BConnectionError(
                    f"MC2000B is already connected at {self.address}; disconnect first"
                )

            serial_factory = self._serial_factory or self._default_serial_factory
            serial_port = None
            try:
                serial_port = serial_factory(
                    port=address,
                    baudrate=self.BAUD_RATE,
                    bytesize=8,
                    parity="N",
                    stopbits=1,
                    timeout=self.timeout_s,
                    write_timeout=self.timeout_s,
                    xonxoff=False,
                    rtscts=False,
                    dsrdtr=False,
                )
                self._serial = serial_port
                self.address = address
                # The controller rejects a bare CR as CMD_NOT_DEFINED. Clear
                # any opening prompt before sending the first real command.
                serial_port.reset_input_buffer()
                identity = self._exchange("id?")
                if not identity.upper().startswith("THORLABS MC2000B"):
                    raise MC2000BConnectionError(
                        "The serial device did not identify as a Thorlabs MC2000B "
                        f"(received {identity!r})"
                    )
                self.identity = identity
                return True
            except Exception as exc:
                self._serial = None
                self.address = None
                self.identity = None
                if serial_port is not None:
                    try:
                        serial_port.close()
                    except Exception:
                        pass
                if isinstance(exc, MC2000BError):
                    raise
                raise MC2000BConnectionError(
                    f"Could not connect MC2000B at {address}: {exc}"
                ) from exc

    def disconnect(self) -> None:
        with self._io_lock:
            serial_port = self._serial
            self._serial = None
            self.address = None
            self.identity = None
            if serial_port is not None:
                try:
                    serial_port.close()
                except Exception as exc:
                    raise MC2000BConnectionError(
                        f"Could not close the MC2000B serial port: {exc}"
                    ) from exc

    close = disconnect

    def set_frequency(self, frequency_hz: object) -> int:
        value = self.validate_frequency(frequency_hz)
        self._set_property("freq", value)
        return value

    def get_frequency(self) -> int:
        return self._get_integer_property("freq", "frequency")

    def get_blade_index(self) -> int:
        return self._get_integer_property("blade", "blade index")

    def get_reference_input(self) -> int:
        return self._get_integer_property("ref", "reference input")

    def select_internal_reference(self, reference: object) -> int:
        """Select MC1F10HP inner/outer natively; never stop the wheel."""
        if type(reference) is not int or reference not in (
            self.INTERNAL_OUTER_REFERENCE,
            self.INTERNAL_INNER_REFERENCE,
        ):
            raise ValueError("MC1F10HP reference must be 0 (outer) or 1 (inner)")
        with self._io_lock:
            blade = self.get_blade_index()
            if blade != self.MC1F10HP_BLADE_INDEX:
                raise MC2000BError(
                    f"Controller blade index is {blade}, not MC1F10HP (6); "
                    "reference was not changed"
                )
            if self.get_enabled():
                raise MC2000BError(
                    "MC2000B reference selection requires standby; "
                    "stop the chopper explicitly before changing it"
                )
            self._set_property("ref", reference)
            reported = self.get_reference_input()
            if reported != reference:
                raise MC2000BProtocolError(
                    f"MC2000B did not confirm ref={reference}; "
                    f"controller reported {reported}"
                )
        return reported

    def set_phase(self, phase_deg: object) -> int:
        value = self.validate_phase(phase_deg)
        self._set_property("phase", value)
        return value

    def get_phase(self) -> int:
        return self._get_integer_property("phase", "phase")

    def set_enabled(self, enabled: bool) -> None:
        if not isinstance(enabled, bool):
            raise TypeError("MC2000B enable state must be a boolean")
        self._set_property("enable", int(enabled))

    def get_enabled(self) -> bool:
        value = self._get_integer_property("enable", "enable")
        if value not in (0, 1):
            raise MC2000BProtocolError(
                f"Invalid MC2000B enable response: {value!r}; expected 0 or 1"
            )
        return bool(value)

    def _set_property(self, name: str, value: int) -> None:
        with self._io_lock:
            response = self._exchange(f"{name}={value}")
        if response:
            raise MC2000BProtocolError(
                f"MC2000B rejected {name}={value}: {response}"
            )

    def _get_integer_property(self, name: str, label: str) -> int:
        with self._io_lock:
            response = self._exchange(f"{name}?")
        try:
            return int(response)
        except (TypeError, ValueError) as exc:
            raise MC2000BProtocolError(
                f"Invalid MC2000B {label} response: {response!r}"
            ) from exc

    def _exchange(self, command: str) -> str:
        serial_port = self._require_connection()
        request = f"{command}\r".encode("ascii")
        try:
            serial_port.write(request)
            flush = getattr(serial_port, "flush", None)
            if callable(flush):
                flush()
            raw = bytearray()
            while not raw.endswith(b"> "):
                chunk = serial_port.read(1)
                if not chunk:
                    raise MC2000BProtocolError(
                        f"MC2000B timed out waiting for a prompt after {command!r}; "
                        f"received {bytes(raw)!r}"
                    )
                raw.extend(chunk)
        except MC2000BProtocolError:
            raise
        except Exception as exc:
            raise MC2000BProtocolError(
                f"MC2000B serial exchange failed for {command!r}: {exc}"
            ) from exc

        try:
            text = raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise MC2000BProtocolError(
                f"MC2000B returned non-ASCII data for {command!r}: {bytes(raw)!r}"
            ) from exc
        text = self._PROMPT_PATTERN.sub("", text)
        echo = f"{command}\r"
        if text.startswith(echo):
            text = text[len(echo) :]
        elif command and text.startswith(command):
            text = text[len(command) :].lstrip("\r\n")
        return text.replace("\r\n", "\n").replace("\r", "\n").strip()

    def _require_connection(self) -> Any:
        if self._serial is None:
            raise MC2000BConnectionError(
                "MC2000B is not connected; call connect(address) first"
            )
        return self._serial

    @classmethod
    def validate_frequency(cls, value: object) -> int:
        converted = cls._integer_value(value, "frequency")
        if not cls.MIN_FREQUENCY_HZ <= converted <= cls.MAX_FREQUENCY_HZ:
            raise ValueError(
                "MC2000B frequency must be between 1 and 10000 Hz; "
                "the installed blade may impose a narrower range"
            )
        return converted

    @classmethod
    def validate_phase(cls, value: object) -> int:
        converted = cls._integer_value(value, "phase")
        if not cls.MIN_PHASE_DEG <= converted <= cls.MAX_PHASE_DEG:
            raise ValueError("MC2000B phase must be between 0 and 360 degrees")
        return converted

    @staticmethod
    def _integer_value(value: object, label: str) -> int:
        if isinstance(value, bool):
            raise TypeError(f"MC2000B {label} must be an integer")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"MC2000B {label} must be numeric") from exc
        if not math.isfinite(numeric):
            raise ValueError(f"MC2000B {label} must be finite")
        if not numeric.is_integer():
            raise ValueError(f"MC2000B {label} must be a whole number")
        return int(numeric)

    @staticmethod
    def _positive_finite(value: object, label: str) -> float:
        try:
            converted = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"MC2000B {label} must be numeric") from exc
        if not math.isfinite(converted) or converted <= 0:
            raise ValueError(f"MC2000B {label} must be positive and finite")
        return converted

    @staticmethod
    def _default_serial_factory(**settings: Any) -> Any:
        try:
            import serial
        except ImportError as exc:
            raise MC2000BConnectionError(
                "MC2000B requires pyserial in the selected environment"
            ) from exc
        return serial.Serial(**settings)
