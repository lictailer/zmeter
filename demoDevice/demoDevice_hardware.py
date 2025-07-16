import logging
import time
import pyvisa


from dummy_visa import patch_pyvisa
patch_pyvisa() # To overwrite the pyvisa module with the dummy visa module, do not include this line in the actual code

class DemoDeviceHardware:
    """
    Template Python driver illustrating best practices for hardware drivers in
    the *zmeter* project.  The structure copies the style of `sr860_hardware.py`
    while remaining generic so that developers can adapt it to any instrument.

    Key design guidelines:
    1. **PyVISA first** – communicate via plain VISA commands, avoid proprietary
       libraries if possible.
    2. **Symmetric API** – every setting provides a *setter* (``write=True``)
       and *getter* (``read=True``) in the same method.
    3. **Human-readable enums** – expose descriptive strings to users while
       translating to numerical codes internally via mapping dictionaries.
    4. **Robust I/O helpers** – centralise ``_write`` and ``_query`` for
       logging, retry logic and error handling.
    5. **Thin abstraction** – driver should not hide the underlying SCPI/GPIB
       commands; instead, document them clearly so that advanced users can
       debug issues with a scope or terminal.

    Replace the placeholder commands (e.g. ``MODE``, ``VOLT``) with ones
    relevant to your instrument.  The goal is to show patterns, *not* to offer
    a working implementation out-of-the-box.
    """

    # ---------------- initialisation ----------------
    def __init__(self, address: str):
        """Connect to the instrument.

        Parameters
        ----------
        address : str
            VISA resource string, e.g. ``'USB0::0x1AB1::0x0588::DS1ZA00000001::INSTR'``
        """
        self._address = address
        rm = pyvisa.ResourceManager()
        self._visaInstrument = rm.open_resource(self._address)  # type: ignore[attr-defined]
        # Configure terminators (adjust if your instrument differs)
        self._visaInstrument.write_termination = "\n"  # type: ignore[attr-defined]
        self._visaInstrument.read_termination = "\n"  # type: ignore[attr-defined]
        self._visaInstrument.timeout = 100  # milliseconds

    # -------------- low-level helpers ---------------
    def _write(self, cmd: str):
        """Send a command string to the instrument (no query)."""
        logging.debug(f"→ {cmd}")
        self._visaInstrument.write(cmd)  # type: ignore[attr-defined]

    def _query(self, cmd: str) -> str:
        """Send a query command and return the string response.

        Implements *three* retry attempts with a short back-off, emitting debug
        logs on failure.  This mirrors the defensive programming style found in
        ``sr860_hardware.py``.
        """
        logging.debug(f"? {cmd}")

        attempts = 0
        while attempts < 3:
            try:
                return self._visaInstrument.query(cmd).strip()  # type: ignore[attr-defined]
            except Exception as exc:
                attempts += 1
                logging.warning(
                    "Query '%s' failed (%s). Retry %d/3", cmd, exc, attempts
                )
                time.sleep(0.05)
        # After three unsuccessful tries, escalate the error
        raise RuntimeError(f"Instrument is not responding to '{cmd}'")


    # -------------- identity / reset ----------------
    def idn(self) -> str:
        """Return instrument identification string (SCPI *IDN?)."""
        return self._query("*IDN?")

    def reset(self):
        """Issue a device reset (SCPI *RST)."""
        self._write("*RST")


    # -------------- example enumeration -------------
    _mode_map = {
        "local": 0,
        "remote": 1,
        "lockout": 2,
    }

    def operating_mode(self, mode=None, *, write=False, read=False):
        """Set or query the operating mode of the instrument.

        Usage examples
        --------------
        >>> dev.operating_mode("remote", write=True)  # set remote mode
        >>> dev.operating_mode(1, write=True)  # set remote mode
        >>> current = dev.operating_mode(read=True)    # -> 'remote'
        """
        if write and mode is not None:
            if mode in self._mode_map:
                self._write(f"MODE {self._mode_map[mode]}")
            elif mode in self._mode_map.values() or str(mode) in self._mode_map.values():
                self._write(f"MODE {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._mode_map.keys())}")
        elif read:
            code = int(self._query("MODE?"))
            for key, value in self._mode_map.items():
                if value == code:
                    return key
            return None  # unknown code
        else:
            raise ValueError("Either write or read must be True")


    # -------------- example numeric param -----------
    def voltage_level(self, volts: float | None = None, *, write=False, read=False):
        """Set or query the analog output voltage (0…10 V).

        Mirrors the signature style of ``sr860_hardware.voltage_input_coupling`` etc.
        """
        if write and volts is not None:
            if not 0 <= volts <= 10:
                raise ValueError("volts must be within [0, 10] V")
            self._write(f"VOLT {volts:.4f}")
        elif read:
            return float(self._query("VOLT?"))
        else:
            raise ValueError("Either write or read must be True")


    # -------------- connection teardown -------------
    def disconnect(self):
        """Safely close the VISA session"""
        if getattr(self, "_visaInstrument", None) is None:
            return  # nothing to do

        try:
            self._visaInstrument.clear()  # type: ignore[attr-defined]
        except Exception:
            pass  # ignore buffer clear issues

        try:
            self._visaInstrument.close()  # type: ignore[attr-defined]
        except Exception:
            pass  # ignore if already closed

        self._visaInstrument = None


# -----------------------------------------------------------------------------
# Example usage – will *not* work unless you update ADDRESS/commands accordingly
# Will only run if this file is run directly, not imported as a module
# -----------------------------------------------------------------------------
# if __name__ == "__main__":
#     ADDRESS = "GPIB0::1::INSTR"  # TODO: Replace with your resource string
#     dev = DemoDeviceHardware(ADDRESS)

#     print("Connected to:", dev.idn())

#     # Demonstrate the API patterns
#     dev.operating_mode("remote", write=True)
#     print("Operating mode:", dev.operating_mode(read=True))

#     dev.voltage_level(1.234, write=True)
#     print("Voltage level:", dev.voltage_level(read=True))

#     dev.disconnect()

# # -----------------------------------------------------------------------------
# # This for running the file for dummy visa
# # -----------------------------------------------------------------------------
# # Stand-alone test with the dummy VISA layer
if __name__ == "__main__":
    # 1) Activate the dummy VISA backend *before* any pyvisa calls
    # from . import dummy_visa
    patch_pyvisa()  # type: ignore[attr-defined]

    # 2) Instantiate the driver (uses the patched ResourceManager)
    ADDRESS = "DUMMY::INSTR"  # the dummy layer accepts any address string
    dev = DemoDeviceHardware(ADDRESS)

    print("IDN :", dev.idn())  # → DemoDevice,Simulated,1.0

    # Exercise the API
    dev.operating_mode("remote", write=True)
    print("Mode:", dev.operating_mode(read=True))

    dev.voltage_level(1.234, write=True)
    print("Volt:", dev.voltage_level(read=True))

    dev.disconnect() 

