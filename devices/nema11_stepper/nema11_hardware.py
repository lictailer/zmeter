"""Explicit, serialized transport for the closed-loop NEMA 11 Z stepper.

Construction never opens a port. Positions are motor-shaft degrees from the
Arduino's commanded step counter (GET_CMD). The CL42T driver closes the loop on
its own encoder, so the commanded angle is the shaft angle unless it alarms.
"""
import math
import threading
import time

PROTOCOL = "OK NEMA11 1"
# The sketch blocks during MOVE_ABS, so long moves are sent in chunks sized from
# the measured speed and the position is reported after each one (about 5 Hz).
# Not a travel limit.
PROGRESS_INTERVAL_S = 0.2
FIRST_CHUNK_DEG = 1.0

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
        raise MotorStopped("Motor operation stopped before the next command")


class Nema11Hardware:
    def __init__(self, *, serial_factory=None, startup_delay_s=2.0):
        self.serial_factory = serial_factory
        self.startup_delay_s = startup_delay_s
        self.serial = None
        self.address = ""
        self.command_timeout_s = 120.0
        self.position = None
        self._uncertain = False
        self._lock = threading.RLock()

    @property
    def connected(self):
        return self.serial is not None

    def configure(self, timeout):
        timeout = number(timeout, "Command timeout")
        if not 0 < timeout <= 3600:
            raise ValueError("Command timeout must be positive and at most 3600 seconds")
        with self._lock:
            self.command_timeout_s = timeout

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
                    raise RuntimeError("Upload the nema11_stepper sketch first")
                # The position at connection is the origin, whether or not the board reset.
                self._command("ZERO")
                self.read_angle()
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

    def read_angle(self):
        with self._lock:
            tokens = self._command("GET_CMD")
            try:
                if len(tokens) != 2 or tokens[0] != "CMD":
                    raise ValueError(f"Unexpected Arduino reply: {tokens!r}")
                self.position = number(tokens[1], "Arduino position")
            except Exception:
                self._uncertain = True
                raise
            return self.position

    def move_angle(self, target, stop, progress=None):
        with self._lock:
            target = number(target, "Target angle")
            checkpoint(stop)
            current = self.position if self.position is not None else self.read_angle()
            chunk = FIRST_CHUNK_DEG
            while True:
                checkpoint(stop)
                remaining = target - current
                waypoint = target if abs(remaining) <= chunk else current + math.copysign(chunk, remaining)
                started = time.monotonic()
                tokens = self._command(f"MOVE_ABS {waypoint:.6f}")
                if not tokens or tokens[0] != "OK":
                    self._uncertain = True
                    raise RuntimeError(f"Unexpected Arduino reply: {tokens!r}")
                # The OK value is the sketch's encoder reading; use the commanded position.
                moved = abs(self.read_angle() - current)
                current = self.position
                if progress is not None:
                    progress(current)
                if waypoint == target:
                    return current
                elapsed = time.monotonic() - started
                if moved > 0 and elapsed > 0:
                    chunk = min(max(moved * PROGRESS_INTERVAL_S / elapsed, FIRST_CHUNK_DEG), 360.0)

    def disconnect(self):
        with self._lock:
            port, self.serial = self.serial, None
            self.position = None
            if port is not None:
                port.close()  # No move, home or zero command.
