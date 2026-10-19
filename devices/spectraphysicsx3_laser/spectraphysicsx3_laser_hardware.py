"""Documented serial queries and explicit controls for an InSight X3.

The controller's USB interface is a Windows virtual COM port. A process that
already owns that port (including the manufacturer's GUI) prevents a second
process from opening it. This driver never attempts to share or steal a port.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class X3Error(RuntimeError):
    """Base error for this device."""


class X3ConnectionError(X3Error):
    """Connection failed or the selected port was not an expected X3."""


class X3ProtocolError(X3Error):
    """The controller returned an empty, malformed, or unexpected response."""


@dataclass(frozen=True)
class X3Status:
    """Status bits from the manufacturer's 2017 Appendix A, Table A-1."""

    word: int

    @property
    def emission(self) -> bool:
        return bool(self.word & (1 << 0))

    @property
    def pulsing(self) -> bool:
        return bool(self.word & (1 << 1))

    @property
    def shutter_open(self) -> bool:
        return bool(self.word & (1 << 2))

    @property
    def interlock_open(self) -> bool:
        return bool(self.word & sum(1 << bit for bit in (9, 10, 11, 12)))

    @property
    def warning(self) -> bool:
        return bool(self.word & (1 << 14))

    @property
    def fault(self) -> bool:
        return bool(self.word & (1 << 15))

    @property
    def state_code(self) -> int:
        return (self.word >> 16) & 0x7F

    @property
    def state_label(self) -> str:
        code = self.state_code
        if code == 25:
            return "Ready"
        if code == 50:
            return "Run"
        if code == 60:
            return "Align"
        if 0 <= code <= 24:
            return "Initializing"
        if 26 <= code <= 49:
            return "Turning on / optimizing"
        if 51 <= code <= 59:
            return "Moving to Align"
        if 61 <= code <= 69:
            return "Exiting Align"
        return f"State {code}"


class SpectraPhysicsX3Hardware:
    """One explicitly selected, serialized 115200-baud X3 connection."""

    BAUD_RATE = 115_200
    MANUAL_MIN_NM = 680
    MANUAL_MAX_NM = 1300

    def __init__(
        self,
        serial_factory: Callable[..., Any] | None = None,
        timeout_s: float = 1.0,
    ) -> None:
        self._serial_factory = serial_factory
        self.timeout_s = self._positive_finite(timeout_s, "serial timeout")
        self._serial: Any | None = None
        self._io_lock = threading.RLock()
        self.address: str | None = None
        self.min_wavelength_nm: int | None = None
        self.max_wavelength_nm: int | None = None

    @property
    def connected(self) -> bool:
        return self._serial is not None

    def connect(self, address: str) -> bool:
        address = str(address).strip()
        if not address or address.casefold() in {"false", "none"}:
            raise ValueError("Enter the X3 COM port explicitly")
        with self._io_lock:
            if self.connected:
                if self.address == address:
                    return True
                raise X3ConnectionError(
                    f"X3 is already connected at {self.address}; disconnect first"
                )
            factory = self._serial_factory or self._default_serial_factory
            port = None
            try:
                port = factory(
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
                self._serial = port
                self.address = address
                minimum = self._integer_query("WAVelength:MIN?", "minimum wavelength")
                maximum = self._integer_query("WAVelength:MAX?", "maximum wavelength")
                if not (
                    self.MANUAL_MIN_NM <= minimum < maximum <= self.MANUAL_MAX_NM
                ):
                    raise X3ConnectionError(
                        "Unexpected X3 wavelength limits "
                        f"[{minimum}, {maximum}] nm at {address}"
                    )
                self.min_wavelength_nm = minimum
                self.max_wavelength_nm = maximum
                self.read_actual_wavelength()
                self.read_status()
                return True
            except Exception as exc:
                self._serial = None
                self.address = None
                self.min_wavelength_nm = None
                self.max_wavelength_nm = None
                if port is not None:
                    try:
                        port.close()
                    except Exception:
                        pass
                if isinstance(exc, X3Error):
                    raise
                raise X3ConnectionError(
                    f"Could not connect InSight X3 at {address}: {exc}"
                ) from exc

    def disconnect(self) -> None:
        """Release only the serial handle; do not alter laser or shutter state."""
        with self._io_lock:
            port = self._serial
            self._serial = None
            self.address = None
            self.min_wavelength_nm = None
            self.max_wavelength_nm = None
            if port is not None:
                try:
                    port.close()
                except Exception as exc:
                    raise X3ConnectionError(
                        f"Could not close the X3 serial port: {exc}"
                    ) from exc

    def command_wavelength(self, wavelength_nm: object) -> int:
        """Send one target; acceptance and actual arrival are checked in logic."""
        target = self.validate_wavelength(wavelength_nm)
        with self._io_lock:
            self._write_unlocked(f"WAVelength {target}")
        return target

    def command_shutter(self, state: object) -> int:
        target = self.validate_shutter(state)
        with self._io_lock:
            self._write_unlocked(f"SHUTter {target}")
        return target

    def read_commanded_shutter(self) -> int:
        """Return the last command, not the sensed shutter position."""
        value = self._integer_query("SHUTter?", "commanded shutter")
        if value not in (0, 1):
            raise X3ProtocolError(f"Invalid X3 commanded shutter: {value!r}")
        return value

    def command_diode_on(self) -> None:
        with self._io_lock:
            self._write_unlocked("ON")

    def command_diode_off(self) -> None:
        # The controller itself closes the shutter when OFF is issued.
        with self._io_lock:
            self._write_unlocked("OFF")

    def command_mode(self, mode: str) -> str:
        selected = self.validate_mode(mode)
        with self._io_lock:
            self._write_unlocked(f"MODE {selected}")
        return selected

    def read_mode(self) -> str:
        with self._io_lock:
            response = self._query_unlocked("MODE?")
        selected = response.upper()
        if selected not in ("RUN", "ALIGN"):
            raise X3ProtocolError(f"Invalid X3 mode response: {response!r}")
        return selected

    def read_target_wavelength(self) -> int:
        value = self._integer_query("WAVelength?", "target wavelength")
        return self._valid_read_wavelength(value, "target wavelength")

    def read_actual_wavelength(self) -> int:
        value = self._integer_query("READ:WAVelength?", "actual wavelength")
        return self._valid_read_wavelength(value, "actual wavelength")

    def read_power_w(self) -> float:
        return self._float_query("READ:POWer?", "output power", minimum=0.0)

    def read_diode_temperature_c(self) -> float:
        return self._float_query(
            "READ:PLASer:DIODe1:TEMPerature?", "diode temperature",
            minimum=-math.inf,
        )

    def read_diode_current_a(self) -> float:
        return self._float_query(
            "READ:PLASer:DIODe1:CURRent?", "diode current", minimum=0.0,
        )

    def read_diode_hours(self) -> float:
        return self._float_query(
            "READ:PLASer:DIODe1:HOURS?", "diode hours", minimum=0.0,
        )

    def read_warmup_percent(self) -> float:
        return self._float_query(
            "READ:PCTWarmedup?", "warm-up percentage",
            minimum=0.0, maximum=100.0,
        )

    def read_humidity_percent(self) -> float:
        return self._float_query("READ:HUMidity?", "cavity humidity", minimum=0.0)

    def read_motor_position_percent(self) -> float:
        return self._float_query(
            "CONTrol:DSMPOSition?", "DeepSee motor position", minimum=0.0,
            maximum=100.0,
        )

    def read_status(self) -> X3Status:
        word = self._integer_query("*STB?", "status word")
        if not 0 <= word <= 0xFFFFFFFF:
            raise X3ProtocolError(f"Invalid X3 status word: {word!r}")
        return X3Status(word)

    def read_identity(self) -> str | None:
        # The operator's controller returned an empty response to *IDN?.
        # Do not make identity availability a connection or scan prerequisite.
        with self._io_lock:
            return self._query_unlocked("*IDN?", allow_empty=True) or None

    def validate_wavelength(self, value: object) -> int:
        if isinstance(value, bool):
            raise TypeError("X3 wavelength must be a whole number of nm")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("X3 wavelength must be numeric") from exc
        if not math.isfinite(number) or not number.is_integer():
            raise ValueError("X3 wavelength must be finite and whole nm")
        target = int(number)
        minimum = self.min_wavelength_nm or self.MANUAL_MIN_NM
        maximum = self.max_wavelength_nm or self.MANUAL_MAX_NM
        if not minimum <= target <= maximum:
            raise ValueError(
                f"X3 wavelength {target} nm is outside [{minimum}, {maximum}] nm"
            )
        return target

    @staticmethod
    def validate_shutter(value: object) -> int:
        if isinstance(value, bool):
            raise TypeError("X3 shutter state must be numeric 0 or 1")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError("X3 shutter state must be numeric 0 or 1") from exc
        if not math.isfinite(number) or number not in (0.0, 1.0):
            raise ValueError("X3 shutter state must be 0 (closed) or 1 (open)")
        return int(number)

    @staticmethod
    def validate_mode(value: str) -> str:
        if not isinstance(value, str) or value.upper() not in ("RUN", "ALIGN"):
            raise ValueError("X3 mode must be RUN or ALIGN")
        return value.upper()

    def _valid_read_wavelength(self, value: int, label: str) -> int:
        minimum = self.min_wavelength_nm or self.MANUAL_MIN_NM
        maximum = self.max_wavelength_nm or self.MANUAL_MAX_NM
        if not minimum <= value <= maximum:
            raise X3ProtocolError(
                f"X3 {label} response {value!r} is outside "
                f"[{minimum}, {maximum}] nm"
            )
        return value

    def _integer_query(self, command: str, label: str) -> int:
        with self._io_lock:
            response = self._query_unlocked(command)
        try:
            return int(response)
        except ValueError as exc:
            raise X3ProtocolError(
                f"Invalid X3 {label} response: {response!r}"
            ) from exc

    def _float_query(
        self,
        command: str,
        label: str,
        *,
        minimum: float,
        maximum: float | None = None,
    ) -> float:
        with self._io_lock:
            response = self._query_unlocked(command)
        try:
            value = float(response)
        except ValueError as exc:
            raise X3ProtocolError(
                f"Invalid X3 {label} response: {response!r}"
            ) from exc
        if not math.isfinite(value) or value < minimum or (
            maximum is not None and value > maximum
        ):
            raise X3ProtocolError(f"Invalid X3 {label} response: {response!r}")
        return value

    def _query_unlocked(self, command: str, *, allow_empty: bool = False) -> str:
        port = self._require_connection()
        try:
            port.reset_input_buffer()
            self._write_unlocked(command)
            raw = port.readline()
            if raw.rstrip(b"\r\n") == command.encode("ascii"):
                raw = port.readline()
        except Exception as exc:
            if isinstance(exc, X3Error):
                raise
            raise X3ProtocolError(f"X3 query {command!r} failed: {exc}") from exc
        try:
            response = bytes(raw).decode("ascii").strip()
        except UnicodeDecodeError as exc:
            raise X3ProtocolError(
                f"X3 query {command!r} returned non-ASCII data"
            ) from exc
        if not response and not allow_empty:
            raise X3ProtocolError(f"X3 query {command!r} returned no response")
        return response

    def _write_unlocked(self, command: str) -> None:
        port = self._require_connection()
        try:
            payload = f"{command}\r".encode("ascii")
            written = port.write(payload)
            if written != len(payload):
                raise X3ProtocolError(
                    f"X3 serial write incomplete for {command!r}"
                )
            port.flush()
        except Exception as exc:
            if isinstance(exc, X3Error):
                raise
            raise X3ProtocolError(f"X3 serial write {command!r} failed: {exc}") from exc

    def _require_connection(self) -> Any:
        if self._serial is None:
            raise X3ConnectionError("X3 is not connected; call connect(address) first")
        return self._serial

    @staticmethod
    def _positive_finite(value: object, label: str) -> float:
        try:
            converted = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"X3 {label} must be numeric") from exc
        if not math.isfinite(converted) or converted <= 0:
            raise ValueError(f"X3 {label} must be positive and finite")
        return converted

    @staticmethod
    def _default_serial_factory(**settings: Any) -> Any:
        try:
            import serial
        except ImportError as exc:
            raise X3ConnectionError("X3 requires pyserial") from exc
        return serial.Serial(**settings)
