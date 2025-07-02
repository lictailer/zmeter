import logging
import time
import pyvisa


class SR860_Hardware:
    """
    Minimal Python driver for the Stanford Research Systems SR860 DSP lock-in
    (GPIB version).  Interface layer is plain PyVISA; no SRS libraries needed.
    """

    # ---------------- initialisation ----------------
    def __init__(self, address: str):
        """
        address : VISA resource string, e.g. 'GPIB0::12::INSTR'
        """
        self._address = address
        rm = pyvisa.ResourceManager()
        self._vi = rm.open_resource(self._address)
        self._vi.write_termination = '\n'
        self._vi.read_termination = '\n'

    # -------------- low-level helpers ---------------
    def _write(self, cmd: str):
        logging.debug(f"→ {cmd}")
        self._vi.write(cmd)

    def _query(self, cmd: str) -> str:
        logging.debug(f"? {cmd}")
        return self._vi.query(cmd).strip()

    # -------------- identity / reset ----------------
    def idn(self) -> str:
        return self._query("*IDN?")

    def reset(self):
        self._write("*RST")

    # -------------- reference oscillator ------------
    def set_frequency(self, f_hz: float):
        """Internal reference frequency in Hz (1 mHz – 500 kHz)."""
        self._write(f"FREQ {f_hz:.6f}")

    def get_frequency(self) -> float:
        return float(self._query("FREQ?"))

    def set_amplitude(self, v_rms: float):
        """Sine-out amplitude (1 nV – 2 V rms)."""
        self._write(f"SLVL {v_rms:.9g}")

    def get_amplitude(self) -> float:
        return float(self._query("SLVL?"))

    def set_ref_mode(self, internal: bool = True):
        """True ⇒ internal reference, False ⇒ external."""
        self._write(f"FMOD {1 if internal else 0}")

    # -------------- detection settings --------------
    def set_time_constant(self, index: int):
        """0–24 → τ = 1 µs … 30 ks (see manual Table)."""
        self._write(f"OFLT {index}")

    def get_time_constant(self) -> int:
        return int(self._query("OFLT?"))

    def set_sensitivity(self, index: int):
        """0–26 → 1 nV … 1 V full-scale."""
        self._write(f"SENS {index}")

    def get_sensitivity(self) -> int:
        return int(self._query("SENS?"))

    def set_phase(self, deg: float):
        self._write(f"PHAS {deg:.3f}")

    def get_phase(self) -> float:
        return float(self._query("PHAS?"))

    # -------------- outputs & readings --------------
    _ch_map = {
        "X":  "X",
        "Y":  "Y",
        "R":  "R",
        "TH": "TH"   # θ (phase)
    }

    def _read_output(self, key: str) -> float:
        """Return X, Y, R or θ (TH) instantly with OUTP?."""
        if key not in self._ch_map:
            raise ValueError("key must be one of 'X','Y','R','TH'")
        return float(self._query(f"OUTP? {self._ch_map[key]}"))

    def get_X(self):   return self._read_output("X")
    def get_Y(self):   return self._read_output("Y")
    def get_R(self):   return self._read_output("R")
    def get_Theta(self): return self._read_output("TH")

    # -------------- aux I/O (unchanged) -------------
    def set_aux_out(self, chan: int, volts: float):
        """chan = 1‥4, volts −10.5 V … +10.5 V (1 mV step)."""
        self._write(f"AUXV {chan}, {volts:.3f}")

    def get_aux_out(self, chan: int) -> float:
        return float(self._query(f"AUXV? {chan}"))

    def get_aux_in(self, chan: int) -> float:
        return float(self._query(f"OAUX? {chan}"))

    # -------------- status polling ------------------
    def unlocked(self) -> bool:
        """True if the reference PLL is unlocked (cleared on read)."""
        return bool(int(self._query("LIAS? 3")))

    def input_overload(self) -> bool:
        return bool(int(self._query("LIAS? 0")))

    # etc. – the remaining LIAS bits are identical to the SR830
    # -----------------------------------------------


if __name__ == "__main__":

    # ---------- simple exhaustive functional test ----------
    ADDRESS = "GPIB0::12::INSTR"          # edit for your setup
    li = SR860_Hardware(ADDRESS)

    print("Connected to", li.idn())

    # Reference oscillator
    li.set_ref_mode(True)
    li.set_frequency(1370)               # 1.370 kHz
    assert abs(li.get_frequency() - 1370) < 1e-3

    li.set_amplitude(0.123)              # 123 mVrms
    assert abs(li.get_amplitude() - 0.123) < 1e-6

    # Detection chain
    li.set_time_constant(3)              # 10 ms
    assert li.get_time_constant() == 3

    li.set_sensitivity(10)               # 100 µV FS
    assert li.get_sensitivity() == 10

    li.set_phase(45.0)
    assert abs(li.get_phase() - 45.0) < 1e-2

    # Aux outputs
    li.set_aux_out(1, 1.234)
    assert abs(li.get_aux_out(1) - 1.234) < 1e-3

    # Read instantaneous signals
    x = li.get_X()
    y = li.get_Y()
    r = li.get_R()
    th = li.get_Theta()
    print(f"X={x:.4e}  Y={y:.4e}  R={r:.4e}  θ={th:.3f}°")

    # Status flags
    print("Ref unlocked:", li.unlocked())
    print("Input overload:", li.input_overload())

    print("All SR860 commands executed without error – test passed.")
