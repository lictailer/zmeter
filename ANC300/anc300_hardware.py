#!/usr/bin/env python3
"""
anc300_simple.py
================
Tiny, self-contained driver for an Attocube ANC300 controller over USB-serial.
Only a subset of everyday commands are implemented:

* set/get voltage amplitude      → set_voltage, get_voltage
* set/get step frequency         → set_frequency, get_frequency
* move relative (N steps)        → move_by
* continuous jog (+ / -)         → jog
* emergency stop                 → stop
* read controller version / SN   → get_version, get_serial

The code is intentionally brief (~150 lines) and mirrors the minimal test that
already works for you.  Feel free to extend it further.
"""

from __future__ import annotations

import re
import time
from typing import Union

import serial


class AttocubeError(RuntimeError):
    """Generic ANC300 error (e.g. controller returned ERROR)."""


class AttocubeTimeout(AttocubeError):
    """Timed out waiting for controller reply."""


class ANC300:
    """Serial-only stand-alone ANC300 driver."""

    def __init__(
        self,
        port: str = "COM3",
        baudrate: int = 38400,
        timeout: float = 2.0,
    ):
        self.ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=timeout,
            write_timeout=timeout,
        )
        # give the controller a brief moment, then silence echoes
        time.sleep(0.3)
        self.ser.reset_input_buffer()
        self.query("echo off")

    # ------------------------------------------------------------------ #
    # low-level helpers                                                  #
    # ------------------------------------------------------------------ #
    def _send(self, cmd: str) -> None:
        if not cmd.endswith("\r\n"):
            cmd += "\r\n"
        self.ser.write(cmd.encode())

    def _read_until_ok(self) -> str:
        buf = bytearray()
        while True:
            byte = self.ser.read(1)
            if not byte:  # timeout
                raise AttocubeTimeout("no response (timeout)")
            buf.extend(byte)
            if buf.endswith(b"OK\r\n"):
                return buf[:-4].decode().strip()
            if buf.endswith(b"ERROR\r\n"):
                msg = buf[:-7].decode().strip()
                raise AttocubeError(msg)

    def query(self, cmd: str) -> str:
        """Send *cmd* and return reply without trailing 'OK'."""
        self.ser.reset_input_buffer()
        self._send(cmd)
        return self._read_until_ok()

    # ------------------------------------------------------------------ #
    # high-level API (subset)                                            #
    # ------------------------------------------------------------------ #
    # version / serial
    def get_version(self) -> str:
        return self.query("ver")

    def get_serial(self) -> str:
        return self.query("getcser")

    # helpers for axis argument
    @staticmethod
    def _ax(axis: Union[int, str]) -> str:
        if axis == "all":
            return "all"
        if isinstance(axis, int) and 1 <= axis <= 7:
            return str(axis)
        raise ValueError("axis must be 1-7 or 'all'")

    # voltage amplitude
    def set_voltage(self, axis: Union[int, str], volts: float) -> None:
        self.query(f"setv {self._ax(axis)} {volts}")

    def get_voltage(self, axis: Union[int, str]) -> float:
        rep = self.query(f"getv {self._ax(axis)}")
        return self._parse_float(rep, "voltage", "V")

    # frequency
    def set_frequency(self, axis: Union[int, str], freq_hz: float) -> None:
        self.query(f"setf {self._ax(axis)} {freq_hz}")

    def get_frequency(self, axis: Union[int, str]) -> float:
        rep = self.query(f"getf {self._ax(axis)}")
        return self._parse_float(rep, "frequency", "Hz")

    # motion
    def move_by(self, axis: int, steps: int) -> None:
        if steps == 0:
            return
        cmd = "stepu" if steps > 0 else "stepd"
        self.query(f"{cmd} {axis} {abs(steps)}")

    def jog(self, axis: int, direction: str) -> None:
        if direction not in ("+", "-"):
            raise ValueError("direction must be '+' or '-'")
        cmd = "stepu" if direction == "+" else "stepd"
        self.query(f"{cmd} {axis} c")  # continuous

    def stop(self, axis: Union[int, str] = "all") -> None:
        self.query(f"stop {self._ax(axis)}")

    # ------------------------------------------------------------------ #
    # parsing utility                                                    #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_float(reply: str, label: str, unit: str) -> float:
        # expected format: '<label> = 40.0 V'
        m = re.match(fr"^{label}\s*=\s*([0-9.+-eE]+)\s*{unit}$", reply)
        if not m:
            raise AttocubeError(f"unexpected reply: {reply!r}")
        return float(m[1])

    # context manager sugar
    def close(self):
        self.ser.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


# ---------------------------------------------------------------------- #
# Example                                                                
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    import sys

    port = sys.argv[1] if len(sys.argv) > 1 else "COM6"
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 38400

    with ANC300(port, baudrate=baud, timeout=3.0) as stage:
        print("Controller firmware:", stage.get_version())
        print("Serial number     :", stage.get_serial())

        stage.set_voltage(5, 30)
        print("Axis 5 voltage    :", stage.get_voltage(5), "V")

        stage.set_frequency(5, 1000)
        print("Axis 1 freq       :", stage.get_frequency(1), "Hz")

        # print("Moving +100 steps …")
        # stage.move_by(1, 100)
        # print("Done")
