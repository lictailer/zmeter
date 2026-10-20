"""Explicit, serialized transport for the closed-loop NEMA 11 Z stepper.

Construction never opens a port. Positions are motor-shaft degrees; readback
comes from the motor encoder through the Arduino, not from a step counter.
"""
from dataclasses import dataclass
import math
import threading
import time

PROTOCOL = "OK NEMA11 1"


def number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


class MotorStopped(RuntimeError):
    pass


def checkpoint(stop):
    if stop.is_set():
        raise MotorStopped("Motor operation stopped after its last acknowledged segment")


@dataclass(frozen=True)
class MotorLimits:
    # About +/-20 um of Z with the previous 100/30 gear and 500 um/rev translator.
    # These are editable commissioning values, NOT detected mechanical limits.
    minimum_deg: float = -50.0
    maximum_deg: float = 50.0
    segment_deg: float = 10.0
    # Must cover encoder resolution (0.09 deg at 4000 counts/rev) plus following error.
    tolerance_deg: float = 0.2
    settle_timeout_s: float = 2.0

    def validate(self):
        lo, hi = number(self.minimum_deg, "Minimum angle"), number(self.maximum_deg, "Maximum angle")
        if lo >= hi:
            raise ValueError("Minimum angle must be below maximum angle")
        if number(self.segment_deg, "Segment size") <= 0:
            raise ValueError("Segment size must be positive")
        if number(self.tolerance_deg, "Position tolerance") <= 0:
            raise ValueError("Position tolerance must be positive")
        if not 0 <= number(self.settle_timeout_s, "Settle timeout") <= 60:
            raise ValueError("Settle timeout must be 0..60 seconds")

    def check(self, target, name="Target angle"):
        target = number(target, name)
        if not self.minimum_deg <= target <= self.maximum_deg:
            raise ValueError(f"{name} {target:g} deg outside [{self.minimum_deg:g}, {self.maximum_deg:g}]")
        return target


class Nema11Hardware:
    def __init__(self, *, serial_factory=None, startup_delay_s=2.0):
        self.serial_factory = serial_factory
        self.startup_delay_s = startup_delay_s
        self.serial = None
        self.address = ""
        self.command_timeout_s = 120.0
        self.limits = MotorLimits()
        self.position = None
        self._uncertain = False
        self._lock = threading.RLock()

    @property
    def connected(self):
        return self.serial is not None

    def configure(self, limits, timeout):
        limits.validate()
        timeout = number(timeout, "Command timeout")
        if not 0 < timeout <= 3600:
            raise ValueError("Command timeout must be positive and at most 3600 seconds")
        with self._lock:
            self.limits, self.command_timeout_s = limits, timeout

    def connect(self, address, stop):
        with self._lock:
            address = str(address).strip()
            if self.connected:
                if address != self.address:
                    raise RuntimeError("Disconnect before changing the COM port")
                return True
            if not address:
                raise ValueError("Enter the Arduino COM port")
            factory = self.serial_factory
            if factory is None:
                import serial
                factory = serial.Serial
            try:
                self.serial = factory(port=address, baudrate=115200, timeout=0.2, write_timeout=2)
                self.address = address
                if stop.wait(self.startup_delay_s):
                    checkpoint(stop)
                self.serial.reset_input_buffer()
                self._uncertain = False
                if " ".join(self._command("PING")) != PROTOCOL:
                    raise RuntimeError("Upload the nema11_stepper encoder sketch first")
                # The position at connection is the origin, whether or not the board reset.
                self.position = self._position("ZERO", "OK")
            except Exception:
                self.disconnect()
                raise
            return True

    def _command(self, command):
        if not self.connected:
            raise RuntimeError("Connect nema11_stepper first")
        if self._uncertain:
            raise RuntimeError("Stepper state uncertain after a failed command; reconnect and inspect the position")
        try:
            self.serial.write((command + "\n").encode("ascii"))
            self.serial.flush()
            deadline = time.monotonic() + self.command_timeout_s
            while time.monotonic() < deadline:
                raw = self.serial.readline()
                if not raw:
                    continue
                tokens = raw.decode("ascii").strip().split()
                if not tokens or tokens == ["READY"]:
                    continue
                if tokens[0] == "ERR":
                    raise RuntimeError("Arduino rejected command: " + " ".join(tokens[1:]))
                return tokens
            raise TimeoutError(f"No acknowledgement for {command}; position may be uncertain")
        except Exception:
            self._uncertain = True
            raise

    def _position(self, command, prefix):
        tokens = self._command(command)
        try:
            if len(tokens) != 2 or tokens[0] != prefix:
                raise ValueError(f"Unexpected Arduino reply: {tokens!r}")
            return number(tokens[1], "Arduino position")
        except Exception:
            self._uncertain = True
            raise

    def read_angle(self):
        with self._lock:
            self.position = self._position("GET_POS", "POS")
            return self.position

    def read_command_angle(self):
        with self._lock:
            return self._position("GET_CMD", "CMD")

    def _confirm(self, target, actual, stop):
        limits = self.limits
        deadline = time.monotonic() + limits.settle_timeout_s
        while abs(actual - target) > limits.tolerance_deg:
            if time.monotonic() >= deadline:
                self._uncertain = True
                raise RuntimeError(f"Encoder reads {actual:g} deg, not {target:g} deg; "
                                   "check the driver alarm LED and encoder wiring")
            if stop.wait(0.05):
                checkpoint(stop)
            actual = self.read_angle()
        return actual

    def move_angle(self, target, stop):
        with self._lock:
            limits = self.limits
            target = limits.check(target)
            checkpoint(stop)
            current = limits.check(self.read_angle(), "Current angle")
            if math.ceil(abs(target - current) / limits.segment_deg) > 10000:
                raise ValueError("Move needs more than 10000 segments; review limits and segment size")
            while abs(target - current) > limits.tolerance_deg:
                checkpoint(stop)
                delta = max(-limits.segment_deg, min(limits.segment_deg, target - current))
                waypoint = current + delta
                self.position = self._position(f"MOVE_ABS {waypoint:.6f}", "OK")
                current = self._confirm(waypoint, self.position, stop)
                checkpoint(stop)
            return current

    def disconnect(self):
        with self._lock:
            port, self.serial = self.serial, None
            self.position = None
            if port is not None:
                port.close()  # No move, home or zero command.
