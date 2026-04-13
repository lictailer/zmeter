import logging
import time

import pyvisa


class SR830_Hardware:
    """
    Python driver wrapper for Stanford Research SR830 lock-in amplifier.

    Command semantics and index/value conventions are intentionally preserved
    from the existing SR830 module.
    """

    def __init__(self, address=None):
        self._address = None
        self._vi = None
        if address:
            self.connect_visa(address)

    def connect_visa(self, address):
        self._address = address
        resource_manager = pyvisa.ResourceManager()
        self._vi = resource_manager.open_resource(self._address)
        self._vi.write_termination = "\n"
        self._vi.read_termination = "\n"
        self._vi.timeout = 1000

    def _write(self, cmd: str):
        if self._vi is None:
            raise RuntimeError("SR830 VISA resource is not connected.")
        logging.debug(f"-> {cmd}")
        self._vi.write(cmd)

    def _query(self, cmd: str) -> str:
        if self._vi is None:
            raise RuntimeError("SR830 VISA resource is not connected.")
        logging.debug(f"? {cmd}")

        last_error = None
        for _ in range(3):
            try:
                return self._vi.query(cmd).strip()
            except Exception as exc:
                last_error = exc
                time.sleep(0.01)
        raise RuntimeError(f"Error querying '{cmd}' after 3 retries: {last_error}")

    def idn(self) -> str:
        return self._query("*IDN?")

    def reset(self):
        self._write("*RST")
        self.get_all()

    def get_all(self):
        logging.info(__name__ + " : reading all settings from instrument")
        self.get_sensitivity()
        self.get_time_constant()
        self.get_frequency()
        self.get_amplitude()
        self.get_phase()
        self.get_X()
        self.get_Y()
        self.get_R()
        self.get_Theta()
        self.get_ref_input()
        self.get_ext_trigger()
        self.get_sync_filter()
        self.get_harmonic()
        self.get_input_config()
        self.get_input_shield()
        self.get_input_coupling()
        self.get_notch_filter()
        self.get_reserve()
        self.get_filter_slope()
        self.get_unlocked()
        self.get_input_overload()
        self.get_time_constant_overload()
        self.get_output_overload()

    def disable_front_panel(self):
        self._write("OVRM 0")

    def enable_front_panel(self):
        self._write("OVRM 1")

    def auto_phase(self):
        self._write("APHS")

    def direct_output(self):
        self._write("OUTX 1")

    def read_output(self, output, ovl):
        parameters = {
            1: "X",
            2: "Y",
            3: "R",
            4: "P",
        }
        if output not in parameters:
            raise ValueError("Wrong output requested.")

        logging.info(__name__ + " : Reading parameter from instrument: %s " % parameters.get(output))
        if ovl:
            self.get_input_overload()
            self.get_time_constant_overload()
            self.get_output_overload()
        return float(self._query(f"OUTP?{output}"))

    def get_X(self, ovl=False):
        return self.read_output(1, ovl)

    def get_Y(self, ovl=False):
        return self.read_output(2, ovl)

    def get_R(self, ovl=False):
        return self.read_output(3, ovl)

    def get_Theta(self, ovl=False):
        return self.read_output(4, ovl)

    def set_frequency(self, frequency):
        logging.debug(__name__ + " : setting frequency to %s Hz" % frequency)
        self._write("FREQ %e" % frequency)

    def get_frequency(self):
        self.direct_output()
        logging.debug(__name__ + " : reading frequency from instrument")
        return float(self._query("FREQ?"))

    def get_amplitude(self):
        self.direct_output()
        logging.debug(__name__ + " : reading amplitude from instrument")
        return float(self._query("SLVL?"))

    def set_mode(self, val):
        logging.debug(__name__ + " : Setting Reference mode to external")
        self._write("FMOD %d" % val)

    def set_amplitude(self, amplitude):
        logging.debug(__name__ + " : setting amplitude to %s V" % amplitude)
        self._write("SLVL %e" % amplitude)

    def set_time_constant(self, timeconstant):
        self.direct_output()
        logging.debug(__name__ + " : setting time constant on instrument to %s" % timeconstant)
        self._write("OFLT %s" % timeconstant)

    def get_time_constant(self):
        self.direct_output()
        logging.debug(__name__ + " : getting time constant on instrument")
        return float(self._query("OFLT?"))

    def set_sensitivity(self, sens):
        self.direct_output()
        logging.debug(__name__ + " : setting sensitivity on instrument to %s" % sens)
        self._write("SENS %d" % sens)

    def get_sensitivity(self):
        self.direct_output()
        logging.debug(__name__ + " : reading sensitivity from instrument")
        return float(self._query("SENS?"))

    def get_phase(self):
        self.direct_output()
        logging.debug(__name__ + " : reading phase from instrument")
        return float(self._query("PHAS?"))

    def set_phase(self, phase):
        logging.debug(__name__ + " : setting the reference phase shift to %s degree" % phase)
        self._write("PHAS %e" % phase)

    def set_aux(self, output, value):
        logging.debug(
            __name__ + " : setting the output %(out)i to value %(val).3f"
            % {"out": output, "val": value}
        )
        self._write("AUXV %(out)i, %(val).3f" % {"out": output, "val": value})

    def read_aux(self, output):
        logging.debug(__name__ + " : reading the output %i" % output)
        return float(self._query("AUXV? %i" % output))

    def get_oaux(self, value):
        logging.debug(__name__ + " : reading the input %i" % value)
        return float(self._query("OAUX? %i" % value))

    def set_out(self, value, channel):
        self.set_aux(channel, value)

    def get_out(self, channel):
        return self.read_aux(channel)

    def get_in(self, channel):
        return self.get_oaux(channel)

    def get_ref_input(self):
        return int(self._query("FMOD?")) == 1

    def set_ref_input(self, value):
        if value:
            self._write("FMOD 1")
        else:
            self._write("FMOD 0")

    def get_ext_trigger(self):
        return int(self._query("RSLP?"))

    def set_ext_trigger(self, value):
        self._write("RSLP " + str(value))

    def get_sync_filter(self):
        return int(self._query("SYNC?")) == 1

    def set_sync_filter(self, value):
        if value:
            self._write("SYNC 1")
        else:
            self._write("SYNC 0")

    def get_harmonic(self):
        return int(self._query("HARM?"))

    def set_harmonic(self, value):
        self._write("HARM " + str(value))

    def get_input_config(self):
        return int(self._query("ISRC?"))

    def set_input_config(self, value):
        self._write("ISRC " + str(value))

    def get_input_shield(self):
        return int(self._query("IGND?")) == 1

    def set_input_shield(self, value):
        if value:
            self._write("IGND 1")
        else:
            self._write("IGND 0")

    def get_input_coupling(self):
        return int(self._query("ICPL?")) == 1

    def set_input_coupling(self, value):
        if value:
            self._write("ICPL 1")
        else:
            self._write("ICPL 0")

    def get_notch_filter(self):
        return int(self._query("ILIN?"))

    def set_notch_filter(self, value):
        self._write("ILIN " + str(value))

    def get_reserve(self):
        return int(self._query("RMOD?"))

    def set_reserve(self, value):
        self._write("RMOD " + str(value))

    def get_filter_slope(self):
        return int(self._query("OFSL?"))

    def set_filter_slope(self, value):
        self._write("OFSL " + str(value))

    def get_unlocked(self, update=True):
        if update:
            self._query("LIAS? 3")
            time.sleep(0.02)
        return int(self._query("LIAS? 3")) == 1

    def get_input_overload(self, update=True):
        if update:
            self._query("LIAS? 0")
            time.sleep(0.02)
        return int(self._query("LIAS? 0")) == 1

    def get_time_constant_overload(self, update=True):
        if update:
            self._query("LIAS? 1")
            time.sleep(0.02)
        return int(self._query("LIAS? 1")) == 1

    def get_output_overload(self, update=True):
        if update:
            self._query("LIAS? 2")
            time.sleep(0.02)
        return int(self._query("LIAS? 2")) == 1

    def disconnect(self):
        if getattr(self, "_vi", None) is None:
            return

        try:
            self._vi.clear()  # type: ignore[attr-defined]
        except Exception:
            pass

        try:
            self._vi.close()  # type: ignore[attr-defined]
        except Exception:
            pass

        self._vi = None


if __name__ == "__main__":
    rm = pyvisa.ResourceManager()
    print(rm.list_resources())
