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


class ANC300Hardware:
    """Serial-only stand-alone ANC300 driver
    (connection established later via `initialize()`).
    """
    # ------------------------------------------------------------------ #
    def __init__(
        self,
        port: str | None = None,
        baudrate: int = 38400,
        timeout: float = 2.0,
    ):
        # store settings; don't open the port yet
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self.ser: serial.Serial | None = None  # created in initialize()
        self.VALID_MODES = {"gnd", "stp", "cap", "offs", "stp+", "stp-"}

    # ------------- NEW explicit initialiser --------------------------------
    def initialize(self, port: str | None = None):
        """
        Open the serial connection.

        • *port* overrides the one given at construction.
        • Safe to call more than once; already-open ports are ignored.
        """
        if self.ser and self.ser.is_open:
            return  # already connected

        # decide which port to use
        port = port or self._port
        if port is None:
            raise ValueError(
                "No COM port specified. "
                "Pass one to ANC300Hardware(..., port='COM6') "
                "or call initialize('COM6')."
            )

        # open the port exactly like your working test script
        self.ser = serial.Serial(
            port=port,
            baudrate=self._baudrate,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self._timeout,
            write_timeout=self._timeout,
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
            
    @staticmethod
    def _parse_string(reply: str, label: str) -> str:
        """
        Extract the right-hand side of replies like "acin = on".
        """
        m = re.match(fr"^{label}\s*=\s*(\S+)$", reply, flags=re.I)
        if not m:
            raise AttocubeError(f"unexpected reply: {reply!r}")
        return m[1].lower()

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

    # mode
    def set_mode(self, axis: Union[int, str] = "all", mode: str = "stp") -> str:
        """
        Put *axis* (1-7 or "all") into the given *mode*.

        Modes (availability depends on the controller module):
          • "gnd"   - ground
          • "stp"   - step (open-loop)
          • "cap"   - measure capacitance, then ground
          • "offs"  - DC offset only, no stepping       (no ANM150)
          • "stp+"  - offset plus stepping waveform     (no ANM150)
          • "stp-"  - offset minus stepping waveform    (no ANM150 / ANM200)

        Returns the mode string reported back by the controller.
        """
        if mode not in self.VALID_MODES:
            raise ValueError(f"mode must be one of {sorted(self.VALID_MODES)}")
        axis_s = self._ax(axis)
        self.query(f"setm {axis_s} {mode}")
        # read back to confirm
        return self.get_mode(axis)

    def get_mode(self, axis: Union[int, str] = "all") -> str:
        """
        Query the current mode of *axis* (1-7) or for all axes.

        Returns the mode string exactly as reported by the controller.
        """
        axis_s = self._ax(axis)
        reply = self.query(f"getm {axis_s}").strip()
        if reply.lower().startswith("mode ="):
            return reply.split("=", 1)[1].strip()
        raise AttocubeError(f"unexpected reply: {reply!r}")
    
    # Capacitance measurement
    def get_capacitance(
        self,
        axis: Union[int, str] = "all",
        measure: bool = False,
        settle_s: float = 1.0,
    ) -> float:
        """
        Return the last (or freshly re-)measured capacitance of *axis*.

        Parameters
        ----------
        axis
            1-7 or ``"all"``.
        measure
            • ``False`` – just read the most recent value the controller has.  
            • ``True``  – trigger a new measurement first (takes ≈ 1 s).
        settle_s
            Extra wait time after starting a measurement (ignored if
            *measure* is *False*).  Increase if your system needs longer.

        Notes
        -----
        * Starting a measurement is equivalent to
          ``set_mode(axis, "cap")`` in the ANC300 console.  
          The axis automatically returns to *gnd* when finished.
        * The value returned by the controller is in **nF**; the method
          converts it to **farads** (F) for convenience.
        """
        axis_s = self._ax(axis)

        if measure:
            # put axis in 'cap' mode → starts measurement, finishes in ~1 s
            self.set_mode(axis, "cap")
            time.sleep(settle_s)           # simple wait is usually enough
            # Optionally poll until mode is back to gnd:
            # while self.get_mode(axis) != "gnd":
            #     time.sleep(0.1)

        reply = self.query(f"getc {axis_s}")
        # reply format: "capacitance = 123.4 nF"
        nF = self._parse_float(reply, "capacitance", "nF")
        return nF * 1e-9  # convert to farads
    
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
    # external BNC input enable / disable                                #
    # ------------------------------------------------------------------ #
    def get_external_input_modes(
        self,
        axis: Union[int, str] = "all",
    ) -> tuple[bool, bool]:
        """
        Return a tuple ``(acin_enabled, dcin_enabled)`` for *axis*.

        • *AC-IN*  (acin) – fast high-voltage input  
        • *DC-IN*  (dcin) – low-voltage offset input
        """
        axis_s = self._ax(axis)

        rep = self.query(f"getaci {axis_s}")
        acin = self._parse_string(rep, "acin") == "on"

        rep = self.query(f"getdci {axis_s}")
        dcin = self._parse_string(rep, "dcin") == "on"

        return acin, dcin

    def set_external_input_modes(
        self,
        axis: Union[int, str],
        acin: bool | None = None,
        dcin: bool | None = None,
    ) -> tuple[bool, bool]:
        """
        Enable/disable the external BNC inputs on *axis*.

        Parameters
        ----------
        acin , dcin
            • ``True``  – enable  
            • ``False`` – disable  
            • ``None``  – leave unchanged

        Returns
        -------
        Tuple *(acin_enabled, dcin_enabled)* reflecting the new state.
        """
        axis_s = self._ax(axis)

        if acin is not None:
            self.query(f"setaci {axis_s} {'on' if acin else 'off'}")
        if dcin is not None:
            self.query(f"setdci {axis_s} {'on' if dcin else 'off'}")

        # read back to confirm
        return self.get_external_input_modes(axis)
    
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

    # port = sys.argv[1] if len(sys.argv) > 1 else "COM6"
    # baud = int(sys.argv[2]) if len(sys.argv) > 2 else 38400

    with ANC300Hardware() as stage:
        stage.initialize('COM6')
        print("Controller firmware:", stage.get_version())
        print("Serial number     :", stage.get_serial())

        stage.set_voltage(5, 30)
        print("Axis 5 voltage    :", stage.get_voltage(5), "V")

        stage.set_frequency(5, 1000)
        print("Axis 1 freq       :", stage.get_frequency(1), "Hz")

        print("Axis 5 mode       :", stage.get_mode(5))
        stage.set_mode(5, "stp")
        print("Axis 5 mode       :", stage.get_mode(5))
        # print("Moving +100 steps …")
        # stage.move_by(5, 100)


        # for i in range(1,6):
        #     print(f"Axis {i} capacitance:", stage.get_capacitance(i, measure=True), "F")
        print("Done")
