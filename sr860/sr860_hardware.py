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
        self._vi.timeout = 100

    # -------------- low-level helpers ---------------
    def _write(self, cmd: str):
        logging.debug(f"→ {cmd}")
        self._vi.write(cmd)

    def _query(self, cmd: str) -> str:
        logging.debug(f"? {cmd}")
        
        count = 0
        while count < 3:
            try:
                return self._vi.query(cmd).strip()
            except Exception as e:
                count += 1
                print(f"Error querying {cmd}, trying again {count} times")
                time.sleep(0.01)
        print(f"Error querying {cmd}")
        return None

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

    # -------------- reference & trigger helpers -----------

    _ref_mode_map = {
        "internal": 0,
        "external": 1,
        "dual": 2,
        "chop": 3
    }

    def ref_mode(self, mode=None, write=False, read=False):
        """Set or get reference mode: internal (0), external (1), dual (2), chop (3)."""
        if write and mode is not None:
            if mode in self._ref_mode_map.keys():
                self._write(f"RSRC {self._ref_mode_map[mode]}")
            elif mode in self._ref_mode_map.values() or str(mode) in self._ref_mode_map.values():
                self._write(f"RSRC {mode}")
            else:
                raise ValueError(f"internal must be one of {list(self._ref_mode_map.keys())}")
        elif read:
            ref_mode = int(self._query("RSRC?"))
            for key, value in self._ref_mode_map.items():
                if value == ref_mode:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    _ext_trigger_map = {
        "sine": 0,
        "Pos_TTL": 1,
        "Neg_TTL": 2
    }

    def ext_trigger(self, mode=None, write=False, read=False):
        """Set or get external reference trigger source: 0=sine, 1=Positive TTL, 2=Negative TTL."""
        if write and mode is not None:
            if mode in self._ext_trigger_map.keys():
                self._write(f"RTRG {self._ext_trigger_map[mode]}")
            elif mode in self._ext_trigger_map.values() or str(mode) in self._ext_trigger_map.values():
                self._write(f"RTRG {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._ext_trigger_map.keys())}")
        elif read:
            ext_trigger = int(self._query("RTRG?"))
            for key, value in self._ext_trigger_map.items():
                if value == ext_trigger:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    def ref_input(self, mode=None, write=False, read=False):   
        """Set or get reference input: 50 Ohms (0), 1 MOhms (1)."""
        if write and mode is not None:
            self._write(f"REFZ {1 if mode else 0}")
        elif read:
            return int(self._query("REFZ?")) == 1
        else:
            raise ValueError("Either write or read must be True")

    def sync_filter(self, mode=None, write=False, read=False):
        """Set or get sync filter: ON (1), OFF (0)."""
        if write and mode is not None:
            self._write(f"SYNC {1 if mode else 0}")
        elif read:
            return int(self._query("SYNC?")) == 1
        else:
            raise ValueError("Either write or read must be True")

    def harmonic(self, value=None, write=False, read=False):
        """Set or get detection harmonic (1-99)."""
        if write and value is not None:
            if value < 1 or value > 99:
                raise ValueError("value must be between 1 and 99")
            self._write(f"HARM {value}")
        elif read:
            return int(self._query("HARM?"))
        else:
            raise ValueError("Either write or read must be True")


    # -------------- detection settings --------------
    _time_constant_map = {
        "1 us": 0,
        "3 us": 1,
        "10 us": 2,
        "30 us": 3,
        "100 us": 4,
        "300 us": 5,
        "1 ms": 6,
        "3 ms": 7,
        "10 ms": 8,
        "30 ms": 9,
        "100 ms": 10,
        "300 ms": 11,
        "1 s": 12,
        "3 s": 13,
        "10 s": 14,
        "30 s": 15,
        "100 s": 16,
        "300 s": 17,
        "1 ks": 18,
        "3 ks": 19,
        "10 ks": 20,
        "30 ks": 21
    }

    def time_constant(self, index=None, write=False, read=False):
        """0–21 → τ = 1 µs … 30 ks (see manual Table)."""
        if write and index is not None:
            if index in self._time_constant_map.keys():
                self._write(f"OFLT {self._time_constant_map[index]}")
            elif index in self._time_constant_map.values() or str(index) in self._time_constant_map.values():
                self._write(f"OFLT {index}")
            else:
                raise ValueError(f"index must be one of {list(self._time_constant_map.keys())}")
        elif read:
            time_constant = int(self._query("OFLT?"))
            for key, value in self._time_constant_map.items():
                if value == time_constant:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    _sensitivity_map = {
        "1 V [uA]": 0,
        "500 mV [nA]": 1,
        "200 mV [nA]": 2,
        "100 mV [nA]": 3,
        "50 mV [nA]": 4,
        "20 mV [nA]": 5,
        "10 mV [nA]": 6,
        "5 mV [nA]": 7,
        "2 mV [nA]": 8,
        "1 mV [nA]": 9,
        "500 uV [pA]": 10,
        "200 uV [pA]": 11,
        "100 uV [pA]": 12,
        "50 uV [pA]": 13,
        "20 uV [pA]": 14,
        "10 uV [pA]": 15,
        "5 uV [pA]": 16,
        "2 uV [pA]": 17,
        "1 uV [pA]": 18,
        "500 nV [fA]": 19,
        "200 nV [fA]": 20,
        "100 nV [fA]": 21,
        "50 nV [fA]": 22,
        "20 nV [fA]": 23,
        "10 nV [fA]": 24,
        "5 nV [fA]": 25,
        "2 nV [fA]": 26,
        "1 nV [fA]": 27
    }
    def sensitivity(self, index=None, write=False, read=False):
        """0–27 → 1 V … 1 nV full-scale."""
        if write and index is not None:
            if index in self._sensitivity_map.keys():
                self._write(f"SCAL {self._sensitivity_map[index]}")
            elif index in self._sensitivity_map.values() or str(index) in self._sensitivity_map.values():
                self._write(f"SCAL {index}")
            else:
                raise ValueError(f"index must be one of {list(self._sensitivity_map.keys())}")
        elif read:
            sensitivity = int(self._query("SCAL?"))
            for key, value in self._sensitivity_map.items():
                if value == sensitivity:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    def phase(self, deg=None, write=False, read=False):
        """Set or get phase: 0–360°."""
        if write and deg is not None:
            self._write(f"PHAS {deg:.3f}")
        elif read:
            return float(self._query("PHAS?"))
        else:
            raise ValueError("Either write or read must be True")

    _signal_input_type_map = {
        "voltage": 0,
        "current": 1
    }
    def signal_input_type(self, mode=None, write=False, read=False):
        """ sets the signal input to voltage (i=0) or current (i=1)."""
        if write and mode is not None:
            if mode in self._signal_input_type_map.keys():
                self._write(f"IVMD {self._signal_input_type_map[mode]}")
            elif mode in self._signal_input_type_map.values() or str(mode) in self._signal_input_type_map.values():
                self._write(f"IVMD {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._signal_input_type_map.keys())}")
        elif read:
            signal_input_mode = int(self._query("IVMD?"))
            for key, value in self._signal_input_type_map.items():
                if value == signal_input_mode:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    _signal_input_mode_map = {
        "A": 0,
        "A-B": 1
    }
    def signal_input_mode(self, mode=None, write=False, read=False):
        """ sets the signal input mode: 0=A, 1=A-B."""
        if write and mode is not None:
            if mode in self._signal_input_mode_map.keys():
                self._write(f"ISRC {self._signal_input_mode_map[mode]}")
            elif mode in self._signal_input_mode_map.values() or str(mode) in self._signal_input_mode_map.values():
                self._write(f"ISRC {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._signal_input_mode_map.keys())}")
        
        elif read:
            signal_input_mode = int(self._query("ISRC?"))
            for key, value in self._signal_input_mode_map.items():
                if value == signal_input_mode: return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    _voltage_input_coupling_map = {
        "AC": 0,
        "DC": 1
    }

    def voltage_input_coupling(self, mode=None, write=False, read=False):
        """ sets the voltage input coupling: 0=AC, 1=DC."""
        if write and mode is not None:
            if mode in self._voltage_input_coupling_map.keys():
                self._write(f"ICPL {self._voltage_input_coupling_map[mode]}")
            elif mode in self._voltage_input_coupling_map.values() or str(mode) in self._voltage_input_coupling_map.values():
                self._write(f"ICPL {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._voltage_input_coupling_map.keys())}")
    
        elif read:
            voltage_input_coupling = int(self._query("ICPL?"))
            for key, value in self._voltage_input_coupling_map.items():
                if value == voltage_input_coupling:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    _voltage_input_range_map = {
        "1 V": 0,
        "300 mV": 1,
        "100 mV": 2,
        "30 mV": 3,
        "10 mV": 4,
    }

    def voltage_input_range(self, mode=None, write=False, read=False):
        """ sets the voltage input range: 0=1V, 1=300mV, 2=100mV, 3=30mV, 4=10mV."""
        if write and mode is not None:
            if mode in self._voltage_input_range_map.keys():
                self._write(f"IRNG {self._voltage_input_range_map[mode]}")
            elif mode in self._voltage_input_range_map.values() or str(mode) in self._voltage_input_range_map.values():
                self._write(f"IRNG {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._voltage_input_range_map.keys())}")

        elif read:
            voltage_input_range = int(self._query("IRNG?"))
            for key, value in self._voltage_input_range_map.items():
                if value == voltage_input_range:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True") 
    
    _current_input_range_map = {
        "1 uA": 0,
        "10 nA": 1
    }

    def current_input_range(self, mode=None, write=False, read=False):
        if write and mode is not None:
            if mode in self._current_input_range_map.keys():
                self._write(f"IRNG {self._current_input_range_map[mode]}")
            elif mode in self._current_input_range_map.values() or str(mode) in self._current_input_range_map.values():
                self._write(f"IRNG {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._current_input_range_map.keys())}")
        elif read:
            current_input_range = int(self._query("IRNG?"))
            for key, value in self._current_input_range_map.items():
                if value == current_input_range:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")
    
    _input_shield_map = {
        "Float": 0,
        "Ground": 1
    }

    def input_shield(self, mode=None, write=False, read=False):
        """ sets the input shield: 0=Float, 1=Ground."""
        if write and mode is not None:
            if mode in self._input_shield_map.keys():
                self._write(f"IGND {self._input_shield_map[mode]}")
            elif mode in self._input_shield_map.values() or str(mode) in self._input_shield_map.values():
                self._write(f"IGND {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._input_shield_map.keys())}")
        elif read:
            input_shield = int(self._query("IGND?"))
            for key, value in self._input_shield_map.items():
                if value == input_shield:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    _notch_filter_map = {
        "100 Hz": 0,
        "200 Hz": 1,
        "300 Hz": 2,
        "400 Hz": 3,
    }
    def notch_filter(self, mode=None, write=False, read=False):
        """ sets the notch filter: 0=100Hz, 1=200Hz, 2=300Hz, 3=400Hz."""
        if write and mode is not None:
            if mode in self._notch_filter_map.keys():
                self._write(f"NOTCH {self._notch_filter_map[mode]}")
            elif mode in self._notch_filter_map.values() or str(mode) in self._notch_filter_map.values():
                self._write(f"NOTCH {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._notch_filter_map.keys())}")
        elif read:
            notch_filter = int(self._query("NOTCH?"))
            for key, value in self._notch_filter_map.items():
                if value == notch_filter:
                    return key  
            return None
        else:
            raise ValueError("Either write or read must be True")

    def dc_level(self, value=None, write=False, read=False):
        if write and value is not None:
            self._write(f"SOFF {value}MV")
        elif read:
            return float(self._query("SOFF?"))
        else:
            raise ValueError("Either write or read must be True")

    _dc_level_mode_map = {
        "common": 0,
        "differential": 1
    }
    def dc_level_mode(self, mode=None, write=False, read=False):
        if write and mode is not None:
            if mode in self._dc_level_mode_map.keys():
                self._write(f"REFM {self._dc_level_mode_map[mode]}")
            elif mode in self._dc_level_mode_map.values() or str(mode) in self._dc_level_mode_map.values():
                self._write(f"REFM {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._dc_level_mode_map.keys())}")
        elif read:
            ref_mode = int(self._query("REFM?"))
            for key, value in self._dc_level_mode_map.items():
                if value == ref_mode:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    _filter_slope_map = {
        "6 dB/oct": 0,
        "12 dB/oct": 1,
        "18 dB/oct": 2,
        "24 dB/oct": 3
    }
    def filter_slope(self, mode=None, write=False, read=False):
        if write and mode is not None:
            if mode in self._filter_slope_map.keys():
                self._write(f"OFSL {self._filter_slope_map[mode]}")
            elif mode in self._filter_slope_map.values() or str(mode) in self._filter_slope_map.values():
                self._write(f"OFSL {mode}")
            else:
                raise ValueError(f"mode must be one of {list(self._filter_slope_map.keys())}")
        elif read:
            slope = int(self._query("OFSL?"))
            for key, value in self._filter_slope_map.items():
                if value == slope:
                    return key
            return None
        else:
            raise ValueError("Either write or read must be True")

    # -------------- outputs & readings --------------
    _ch_map = {
        "X":  "X",
        "Y":  "Y",
        "R":  "R",
        "Theta": "TH",   # θ (phase)
        "AuX_In1": "IN1",
        "AuX_In2": "IN2",
        "AuX_In3": "IN3",
        "AuX_In4": "IN4",
        "Xnoise": "XNO",
        "Ynoise": "YNO",
        "AUX_Out1": "OUT1",
        "AUX_Out2": "OUT2",
        "Reference_Phase": "PHA",
        "Sine_Out_Amplitude": "SAM",
        "DC_Level": "LEV", # DC level
        "Int_Ref_Freq": "FI", # Internal reference frequency
        "Ext_Ref_Freq": "FE" # External reference frequency
    }

    def _read_output(self, key: str) -> float:
        """Return X, Y, R or θ (Theta) instantly with OUTP?."""
        if key not in self._ch_map:
            raise ValueError(f"key must be one of {list(self._ch_map.keys())}")

        return float(self._query(f"OUTP? {self._ch_map[key]}"))


    def get_X(self):   return self._read_output("X")
    def get_Y(self):   return self._read_output("Y")
    def get_R(self):   return self._read_output("R")
    def get_Theta(self): return self._read_output("Theta")

    def _snap_output(self, *args: str):
        """Return X, Y, R or θ (Theta) instantly with OUTP?."""
        for arg in args:
            if arg not in self._ch_map:
                raise ValueError(f"arg must be one of {list(self._ch_map.keys())}")
        if len(args) > 3:
            raise ValueError("At most 3 arguments are allowed")

        return self._query(f"SNAP? {','.join(args)}")


    def get_multiple_outputs(self, *args: str):
        time.sleep(0.001)
        return {arg: float(x) for arg, x in zip(args, self._snap_output(*args).split(","))}

    def _snap_display(self):
        return self._query("SNAPD?")

    def get_display(self):
        display = self._snap_display().split(",")
        return {"green": float(display[0]),
                "blue": float(display[1]),
                "yellow": float(display[2]),
                "orange": float(display[3])}


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
        return bool(int(self._query("LIAS? 4")))

    def sensitivity_overload(self) -> bool:
        return bool(int(self._query("LIAS? 8"))) or bool(int(self._query("LIAS? 9"))) or bool(int(self._query("LIAS? 10"))) or bool(int(self._query("LIAS? 11")))

    # etc. – the remaining LIAS bits are identical to the SR830
    # -----------------------------------------------
    def set_auto_range(self):
        self._write(f"ARNG")
    
    def set_auto_scale(self):
        self._write(f"ASCL")
    
    def set_auto_phase(self):
        self._write(f"APHS")
    

    # -------------- connection teardown ---------------
    def disconnect(self):
        """Safely close the VISA resource.

        Before closing we attempt to clear the device buffer so that no
        outstanding responses remain in the queue. Any exceptions during
        cleanup are caught and ignored to ensure the application can
        continue shutting down gracefully.
        """
        if getattr(self, "_vi", None) is None:
            return  # nothing to do

        try:
            # IEEE-488.2 device clear: flush buffers on the instrument side
            self._vi.clear()  # type: ignore[attr-defined]
        except Exception:
            pass  # ignore issues during buffer clear

        try:
            self._vi.close()  # type: ignore[attr-defined]
        except Exception:
            pass  # ignore errors if already closed

        self._vi = None


if __name__ == "__main__":

    # ---------- comprehensive functional test ----------
    ADDRESS = "GPIB0::7::INSTR"          # edit for your setup
    li = SR860_Hardware(ADDRESS)

    print("Connected to", li.idn())
    li.disconnect()
    li = SR860_Hardware(ADDRESS)
    print("Connected to", li.idn()) 
    # Test reference oscillator functions
    print("\n--- Testing Reference Oscillator ---")

    print("\n--- Testing Reference Mode ---")
    li.ref_mode("internal", write=True)
    assert li.ref_mode(read=True) == "internal"
    print("✓ Reference mode internal")

    li.set_frequency(1370)               # 1.370 kHz
    assert abs(li.get_frequency() - 1370) < 1e-3
    print("✓ Frequency set/get")

    li.set_amplitude(0.123)              # 123 mVrms
    assert abs(li.get_amplitude() - 0.123) < 1e-6
    print("✓ Amplitude set/get")

    # Test reference mode functions
    print("\n--- Testing Reference Mode ---")
    li.ref_mode("internal", write=True)
    assert li.ref_mode(read=True) == "internal"
    print("✓ Reference mode internal")

    li.ref_mode("external", write=True)
    assert li.ref_mode(read=True) == "external"
    print("✓ Reference mode external")

    # Test external trigger functions
    print("\n--- Testing External Trigger ---")
    li.ext_trigger("sine", write=True)
    assert li.ext_trigger(read=True) == "sine"
    print("✓ External trigger sine")

    li.ext_trigger("Pos_TTL", write=True)
    assert li.ext_trigger(read=True) == "Pos_TTL"
    print("✓ External trigger Pos_TTL")

    # Test reference input functions
    print("\n--- Testing Reference Input ---")
    li.ref_input(True, write=True)
    assert li.ref_input(read=True) == True
    print("✓ Reference input 1 MOhms")

    li.ref_input(False, write=True)
    assert li.ref_input(read=True) == False
    print("✓ Reference input 50 Ohms")

    # Test sync filter functions
    print("\n--- Testing Sync Filter ---")
    li.sync_filter(True, write=True)
    assert li.sync_filter(read=True) == True
    print("✓ Sync filter ON")

    li.sync_filter(False, write=True)
    assert li.sync_filter(read=True) == False
    print("✓ Sync filter OFF")

    # Test harmonic functions
    print("\n--- Testing Harmonic ---")
    li.harmonic(2, write=True)
    assert li.harmonic(read=True) == 2
    print("✓ Harmonic 2")

    li.harmonic(1, write=True)
    assert li.harmonic(read=True) == 1
    print("✓ Harmonic 1")

    # Test detection settings
    print("\n--- Testing Detection Settings ---")
    li.time_constant(3, write=True)      # 10 ms
    assert li.time_constant(read=True) == 3
    print("✓ Time constant 3")

    li.sensitivity(10, write=True)       # 100 µV FS
    assert li.sensitivity(read=True) == 10
    print("✓ Sensitivity 10")

    li.phase(45.0, write=True)
    assert abs(li.phase(read=True) - 45.0) < 1e-2
    print("✓ Phase 45.0°")

    # Test signal input type functions
    print("\n--- Testing Signal Input Type ---")
    li.signal_input_type("voltage", write=True)
    assert li.signal_input_type(read=True) == "voltage"
    print("✓ Signal input type voltage")

    li.signal_input_type("current", write=True)
    assert li.signal_input_type(read=True) == "current"
    print("✓ Signal input type current")

    # Test signal input mode functions
    print("\n--- Testing Signal Input Mode ---")
    li.signal_input_mode("A", write=True)
    assert li.signal_input_mode(read=True) == "A"
    print("✓ Signal input mode A")

    li.signal_input_mode("A-B", write=True)
    assert li.signal_input_mode(read=True) == "A-B"
    print("✓ Signal input mode A-B")

    # Test voltage input coupling functions
    print("\n--- Testing Voltage Input Coupling ---")
    li.voltage_input_coupling("AC", write=True)
    assert li.voltage_input_coupling(read=True) == "AC"
    print("✓ Voltage input coupling AC")

    li.voltage_input_coupling("DC", write=True)
    assert li.voltage_input_coupling(read=True) == "DC"
    print("✓ Voltage input coupling DC")

    # Test aux outputs
    print("\n--- Testing Aux Outputs ---")
    li.set_aux_out(1, 1.234)
    assert abs(li.get_aux_out(1) - 1.234) < 1e-3
    print("✓ Aux output 1 set/get")

    li.set_aux_out(2, -0.567)
    assert abs(li.get_aux_out(2) - (-0.567)) < 1e-3
    print("✓ Aux output 2 set/get")

    # Test auto functions
    print("\n--- Testing Auto Functions ---")
    li.set_auto_range(True)
    li.set_auto_scale(True)
    li.set_auto_phase(True)
    print("✓ Auto range/scale/phase set")

    # Read instantaneous signals
    print("\n--- Testing Signal Reading ---")
    x = li.get_X()
    y = li.get_Y()
    r = li.get_R()
    th = li.get_Theta()
    print(f"X={x:.4e}  Y={y:.4e}  R={r:.4e}  θ={th:.3f}°")

    print(li.get_multiple_outputs("X", "Y", "R"))
    print(li.get_display())

    # Status flags
    print("\n--- Testing Status Flags ---")
    print("Ref unlocked:", li.unlocked())
    print("Input overload:", li.input_overload())

    print("\n✓ All SR860 functions tested successfully!")
