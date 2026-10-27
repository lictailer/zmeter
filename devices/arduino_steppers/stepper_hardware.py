"""Explicit, serialized Arduino transport. Construction never opens a port."""
from dataclasses import dataclass, replace
import math
import threading
import time

AXES = ("A", "B", "C")


def number(value, name):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def integer(value, name):
    value = number(value, name)
    if value != int(value) or not -2147483647 <= value <= 2147483647:
        raise ValueError(f"{name} must be a signed 32-bit integer")
    return int(value)


class MotorStopped(RuntimeError):
    pass


def checkpoint(stop):
    if stop.is_set():
        raise MotorStopped("Motor operation stopped after its last acknowledged segment")


@dataclass(frozen=True)
class MotorLimits:
    # Conservative continuation of the prior +/-20 degree example at 2048 steps/rev.
    # These are editable commissioning values, NOT detected mechanical limits.
    minimum_steps: int = -113
    maximum_steps: int = 113
    segment_steps: int = 56

    def validate(self):
        if any(type(value) is not int for value in (self.minimum_steps, self.maximum_steps, self.segment_steps)):
            raise ValueError("Motion limit settings must use integer full steps")
        lo, hi = integer(self.minimum_steps, "Minimum steps"), integer(self.maximum_steps, "Maximum steps")
        if lo >= hi or integer(self.segment_steps, "Segment steps") <= 0:
            raise ValueError("Minimum must be below maximum and segment size must be positive")

    def check(self, target):
        target = integer(target, "Position steps")
        if not self.minimum_steps <= target <= self.maximum_steps:
            raise ValueError(f"Target {target} steps outside [{self.minimum_steps}, {self.maximum_steps}]")
        return target


@dataclass(frozen=True)
class MotorInfo:
    steps_per_revolution: int
    speed_rpm: int
    maximum_rpm: int


class StepperHardware:
    def __init__(self, *, serial_factory=None, startup_delay_s=2.0):
        self.serial_factory = serial_factory
        self.startup_delay_s = startup_delay_s
        self.serial = None
        self.address = ""
        self.command_timeout_s = 120.0
        self.limits = {axis: MotorLimits() for axis in AXES}
        self.info = {}
        self.positions = {}
        self._uncertain = False
        self._lock = threading.RLock()

    @property
    def connected(self):
        return self.serial is not None

    def configure(self, limits, timeout):
        if set(limits) != set(AXES):
            raise ValueError("Configure limits for A, B and C")
        for item in limits.values():
            item.validate()
        timeout = number(timeout, "Command timeout")
        if not 0 < timeout <= 3600:
            raise ValueError("Command timeout must be positive and at most 3600 seconds")
        with self._lock:
            self.limits, self.command_timeout_s = dict(limits), timeout

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
                if self._command("PING", allow_ready=True) != ["OK", "STEPPERS", "1"]:
                    raise RuntimeError("Upload the standalone three-motor STEPPERS protocol-1 sketch first")
                self.info, self.positions = {}, {}
                for axis in AXES:
                    checkpoint(stop)
                    self.read_info(axis)
                    self.read_steps(axis)
            except Exception:
                self.disconnect()
                raise
            return True

    def _command(self, command, allow_ready=False):
        if not self.connected:
            raise RuntimeError("Connect arduino_steppers first")
        if self._uncertain:
            raise RuntimeError("Arduino state uncertain after a failed command; reconnect and inspect the software origin")
        try:
            self.serial.write((command + "\n").encode("ascii"))
            self.serial.flush()
            deadline = time.monotonic() + self.command_timeout_s
            while time.monotonic() < deadline:
                raw = self.serial.readline()
                if not raw:
                    continue
                tokens = raw.decode("ascii").strip().split()
                if not tokens or (allow_ready and tokens == ["READY"]):
                    continue
                if tokens[0] == "ERR":
                    raise RuntimeError("Arduino rejected command: " + " ".join(tokens[1:]))
                return tokens
            raise TimeoutError(f"No acknowledgement for {command}; position may be uncertain")
        except Exception:
            self._uncertain = True
            raise

    def _reply(self, command, prefix, axis, fields):
        tokens = self._command(command)
        try:
            if len(tokens) != fields + 2 or tokens[:2] != [prefix, axis]:
                raise ValueError(f"Unexpected Arduino reply: {tokens!r}")
            return [integer(value, "Arduino response") for value in tokens[2:]]
        except Exception:
            self._uncertain = True
            raise

    @staticmethod
    def _axis(axis):
        if axis not in AXES:
            raise ValueError("Select motor A, B or C")

    def read_info(self, axis):
        self._axis(axis)
        with self._lock:
            steps, rpm, maximum = self._reply(f"GET_CONFIG {axis}", "CFG", axis, 3)
            if not 0 < steps <= 32767 or not 0 < rpm <= maximum <= 1000:
                self._uncertain = True
                raise ValueError("Invalid motor configuration from Arduino")
            self.info[axis] = MotorInfo(steps, rpm, maximum)
            return self.info[axis]

    def read_steps(self, axis):
        self._axis(axis)
        with self._lock:
            value, = self._reply(f"GET_POS {axis}", "POS", axis, 1)
            self.positions[axis] = value
            return value

    def read_angle(self, axis):
        with self._lock:
            return self.read_steps(axis) * 360.0 / self.info[axis].steps_per_revolution

    def move_steps(self, axis, target, stop):
        self._axis(axis)
        with self._lock:
            limits = self.limits[axis]
            target = number(target, "Target steps")
            if not limits.minimum_steps <= target <= limits.maximum_steps:
                raise ValueError(f"Target {target:g} steps outside [{limits.minimum_steps}, {limits.maximum_steps}]")
            # Device-side quantization also makes fractional scan/converted-Z
            # targets meaningful. Getter/acknowledgement stays integer steps.
            target = limits.check(math.copysign(math.floor(abs(target) + 0.5), target))
            checkpoint(stop)
            current = limits.check(self.read_steps(axis))
            if math.ceil(abs(target - current) / limits.segment_steps) > 10000:
                raise ValueError("Move needs more than 10000 segments; review limits and segment size")
            while current != target:
                checkpoint(stop)
                delta = max(-limits.segment_steps, min(limits.segment_steps, target - current))
                waypoint = current + delta
                actual, = self._reply(f"MOVE_ABS {axis} {waypoint}", "OK", axis, 1)
                self.positions[axis] = actual
                if actual != waypoint:
                    self._uncertain = True
                    raise RuntimeError(f"Motor {axis} did not acknowledge the requested step position")
                current = actual
                checkpoint(stop)
            return current

    def move_angle(self, axis, target, stop):
        self._axis(axis)
        with self._lock:
            if not self.connected:
                raise RuntimeError("Connect arduino_steppers first")
            scaled = number(target, "Motor angle") * self.info[axis].steps_per_revolution / 360.0
            actual = self.move_steps(axis, scaled, stop)
            return actual * 360.0 / self.info[axis].steps_per_revolution

    def set_speed(self, axis, rpm):
        self._axis(axis)
        with self._lock:
            if not self.connected:
                raise RuntimeError("Connect arduino_steppers first")
            rpm = integer(rpm, "Speed RPM")
            if not 1 <= rpm <= self.info[axis].maximum_rpm:
                raise ValueError(f"Motor {axis} speed must be 1..{self.info[axis].maximum_rpm} RPM")
            actual, = self._reply(f"SET_SPEED {axis} {rpm}", "SPEED", axis, 1)
            if actual != rpm:
                self._uncertain = True
                raise RuntimeError("Speed acknowledgement did not match")
            self.info[axis] = replace(self.info[axis], speed_rpm=actual)
            return actual

    def disconnect(self):
        with self._lock:
            port, self.serial = self.serial, None
            if port is not None:
                port.close()  # No move, home, zero, speed or coil command.
