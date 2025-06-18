from __future__ import annotations

import re
import socket
import time
from collections import namedtuple
from contextlib import contextmanager
from typing import Tuple, Union, Optional

import numpy as np  # type: ignore
try:
    import serial   # pyserial
except ImportError as exc:  # pragma: no cover
    raise ImportError("pyserial is required for Serial communication") from exc

__all__ = ["ANC300", "AttocubeError", "AttocubeBackendError"]


class AttocubeError(RuntimeError):
    """Generic Attocube driver error."""


class AttocubeBackendError(AttocubeError):
    """Low‑level communication error."""


TDeviceInfo = namedtuple("TDeviceInfo", ["serial", "version"])


class _SerialWrapper:
    """Minimal pyserial wrapper exposing the subset used by ANC300."""

    def __init__(self, port: str, baudrate: int = 38400, timeout: float = 3.0):
        self._ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=timeout,
        )

    # high‑level helpers ----------------------------------------------------

    def open(self):
        if not self._ser.is_open:
            self._ser.open()

    def close(self):
        self._ser.close()

    @contextmanager
    def using_timeout(self, timeout: float):
        old = self._ser.timeout, self._ser.write_timeout
        self._ser.timeout = self._ser.write_timeout = timeout
        try:
            yield
        finally:
            self._ser.timeout, self._ser.write_timeout = old

    # read / write ----------------------------------------------------------

    def write(self, msg: str):
        if not msg.endswith("\\r\\n"):
            msg += "\\r\\n"
        self._ser.write(msg.encode())

    def read(self, size: int = 1) -> bytes:
        data = self._ser.read(size)
        if not data:
            raise AttocubeBackendError("read timeout")
        return data

    # helpers ---------------------------------------------------------------

    def flush_read(self):
        self._ser.reset_input_buffer()

    def read_until_terms(self, terms=(b"OK", b"ERROR"), remove_term=False) -> bytes:
        """Read until any terminator (e.g. OK/ERROR) arrives."""
        buf = bytearray()
        while True:
            byte = self.read(1)
            buf.extend(byte)
            for term in terms:
                if buf.endswith(term + b"\\r\\n"):
                    if remove_term:
                        return bytes(buf[: -len(term) - 2])
                    return bytes(buf)
            # guard against unreasonably long messages
            if len(buf) > 4096:
                raise AttocubeBackendError("terminator not found")

    # for socket compatibility ---------------------------------------------

    def flush(self):
        self._ser.reset_input_buffer()

    def __getattr__(self, item):
        # delegate other attrs directly to underlying Serial instance
        return getattr(self._ser, item)


class _SocketWrapper:
    """Minimal socket wrapper (TCP)."""

    def __init__(self, host: str, port: int, timeout: float = 3.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)

    def open(self):
        pass  # socket already open via create_connection

    def close(self):
        self._sock.close()

    @contextmanager
    def using_timeout(self, timeout: float):
        old = self._sock.gettimeout()
        self._sock.settimeout(timeout)
        try:
            yield
        finally:
            self._sock.settimeout(old)

    def write(self, msg: str):
        if not msg.endswith("\\r\\n"):
            msg += "\\r\\n"
        self._sock.sendall(msg.encode())

    def read(self, size: int = 1) -> bytes:
        data = self._sock.recv(size)
        if not data:
            raise AttocubeBackendError("socket closed while reading")
        return data

    def flush_read(self):
        # no direct equivalent; consume everything that is already available
        self._sock.setblocking(False)
        try:
            while self._sock.recv(1024):
                pass
        except (BlockingIOError, socket.error):
            pass
        finally:
            self._sock.setblocking(True)

    def read_until_terms(self, terms=(b"OK", b"ERROR"), remove_term=False) -> bytes:
        buf = bytearray()
        while True:
            byte = self.read(1)
            buf.extend(byte)
            for term in terms:
                if buf.endswith(term + b"\\r\\n"):
                    if remove_term:
                        return bytes(buf[: -len(term) - 2])
                    return bytes(buf)
            if len(buf) > 4096:
                raise AttocubeBackendError("terminator not found")

    def flush(self):
        self.flush_read()


class ANC300:
    """
    Stand‑alone Attocube ANC300 controller.

    Parameters
    ----------
    conn :
        Connection string/tuple. Use ``\"COM4\"`` or ``\"/dev/ttyUSB0\"`` for serial,
        or ``\"host:port\"`` / ``(\"host\", port)`` for Ethernet.
    pwd :
        Password for Ethernet connection. Default is ``\"123456\"``.
    timeout :
        Communication timeout in seconds.
    """

    def __init__(
        self,
        conn: Union[str, Tuple[str, int]],
        pwd: Optional[str] = "123456",
        timeout: float = 3.0,
    ):
        self._pwd = pwd
        self._timeout = timeout
        self._backend = self._make_backend(conn, timeout)
        self._correction = {}  # axis‑specific step length correction
        self.open()

    # --------------------------------------------------------------------- #
    # backend helpers                                                       #
    # --------------------------------------------------------------------- #
    @staticmethod
    def _make_backend(conn: Union[str, Tuple[str, int]], timeout: float):
        # decide based on value type / presence of ":"
        if isinstance(conn, tuple):
            host, port = conn
            return _SocketWrapper(host, int(port), timeout)
        if isinstance(conn, str) and ":" in conn:
            host, port = conn.split(":", 1)
            return _SocketWrapper(host, int(port), timeout)
        # else treat as serial
        return _SerialWrapper(conn, timeout=timeout)

    def open(self):
        """Open connection and put controller into *quiet* mode."""
        self._backend.open()
        if isinstance(self._backend, _SocketWrapper) and self._pwd is not None:
            self._backend.write(self._pwd)
        self._backend.write("echo off")
        self._backend.read_until_terms()  # consume OK
        time.sleep(0.05)
        self._backend.flush_read()

    def close(self):
        self._backend.close()

    def _flush_read(self):
        self._backend.flush_read()

    # basic communication ---------------------------------------------------

    def query(self, msg: str) -> str:
        """Send a command and return the controller reply (sans terminator)."""
        self._flush_read()
        self._backend.write(msg)
        reply = self._backend.read_until_terms()
        if reply.upper().endswith(b"ERROR\\r\\n"):
            err = reply[:-7].decode().strip()  # remove \"ERROR\"
            raise AttocubeError(err)
        # strip \"OK\" terminator
        return reply[:-4].decode().strip()

    # --------------------------------------------------------------------- #
    # high‑level API (subset)                                               #
    # --------------------------------------------------------------------- #
    # utility --------------------------------------------------------------
    @staticmethod
    def _axis_arg(axis: Union[int, str]) -> str:
        if axis == "all":
            return "all"
        if isinstance(axis, int) and 1 <= axis <= 7:
            return str(axis)
        raise ValueError("axis must be 1‑7 or 'all'")

    # device info -----------------------------------------------------------
    def get_device_info(self) -> TDeviceInfo:
        return TDeviceInfo(self.query("getcser"), self.query("ver"))

    # axis mode -------------------------------------------------------------
    def set_mode(self, axis: Union[int, str] = "all", mode: str = "stp") -> None:
        axis_s = self._axis_arg(axis)
        self.query(f"setm {axis_s} {mode}")

    def get_mode(self, axis: Union[int, str] = "all") -> str:
        axis_s = self._axis_arg(axis)
        reply = self.query(f"getm {axis_s}")
        if reply.startswith("mode = "):
            return reply[7:].strip()
        raise AttocubeError(f"unexpected reply: {reply}")

    # voltage amplitude -----------------------------------------------------
    def set_voltage(self, axis: Union[int, str], voltage: float):
        axis_s = self._axis_arg(axis)
        self.query(f"setv {axis_s} {voltage}")
        return voltage

    def get_voltage(self, axis: Union[int, str]):
        axis_s = self._axis_arg(axis)
        reply = self.query(f"getv {axis_s}")
        return self._parse_float_reply(reply, "voltage", "V")

    # offset voltage --------------------------------------------------------
    def set_offset(self, axis: Union[int, str], voltage: float):
        axis_s = self._axis_arg(axis)
        self.query(f"seta {axis_s} {voltage}")

    def get_offset(self, axis: Union[int, str]):
        axis_s = self._axis_arg(axis)
        reply = self.query(f"geta {axis_s}")
        return self._parse_float_reply(reply, "voltage", "V")

    # frequency -------------------------------------------------------------
    def set_frequency(self, axis: Union[int, str], freq: float):
        axis_s = self._axis_arg(axis)
        self.query(f"setf {axis_s} {freq}")

    def get_frequency(self, axis: Union[int, str]):
        axis_s = self._axis_arg(axis)
        reply = self.query(f"getf {axis_s}")
        return self._parse_float_reply(reply, "frequency", "Hz")

    # movement --------------------------------------------------------------
    def move_by(self, axis: int, steps: int):
        if not isinstance(steps, int):
            raise TypeError("steps must be integer")
        if steps == 0:
            return

        if steps < 0:
            steps = int(steps * self._correction.get(axis, 1.0))

        comm = "stepu" if steps > 0 else "stepd"
        self.query(f"{comm} {axis} {abs(steps)}")

    def jog(self, axis: int, direction: str):
        if direction not in ("+", "-"):
            raise ValueError("direction must be '+' or '-'")
        comm = "stepu" if direction == "+" else "stepd"
        self.query(f"{comm} {axis} c")

    def stop(self, axis: Union[int, str] = "all"):
        axis_s = self._axis_arg(axis)
        self.query(f"stop {axis_s}")

    # helpers ---------------------------------------------------------------
    @staticmethod
    def _parse_float_reply(reply: str, name: str, units: str) -> float:
        patt = f"^{name}\\s*=\\s*([\\d.]+)\\s*{units}$"
        m = re.match(patt, reply, re.IGNORECASE)
        if not m:
            raise AttocubeError(f"unexpected reply: {reply}")
        return float(m[1])

    # context manager -------------------------------------------------------
    def __enter__(self):  # noqa: D401
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

