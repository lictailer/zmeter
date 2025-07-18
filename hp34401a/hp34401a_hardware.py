import logging
import pyvisa
import time

# functions that can be added later
#use_front_terminal - check if front panel is selected. This cannot be set remotely, there is a button on the front panel that needs to be released
#input impedance: by default AUTO impedance OFF -- means input resistance is fixed at 10MOhms for all ranges
#check the SENSe:ZERO:AUTO function (seems to be working in triggered mode only)
#define the range
#enable/disable autorange
#+ idn

class HP34401A_Hardware():
    def __init__(self, address: str):
        self._address = address
        rm = pyvisa.ResourceManager()

        self._vi = rm.open_resource(self._address)
        
        self._vi.write("*RST")  # Reset to known state
        self._vi.write("*CLS")  # Clear status

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
    

    def idn(self) -> str:
        return self._query("*IDN?")


    _NPLC_map = [0.02, 0.2, 1, 10, 100]

    def NPLC(self, val=None, write=False, read=False):
        if write and val is not None:
            if val in self._NPLC_map:
                #print('ok',val)
                self._write(f"VOLT:DC:NPLC {val}")
            else:
                raise ValueError(f"value must be one of {self._NPLC_map}")
        elif read:
            NPLC = self._query('SENS:VOLT:DC:NPLC?')
            return NPLC.strip()
        else:
            raise ValueError("Either write or read must be True")
           


    #for sensitive optical measuremens all the displays must be turned off
    def dark_mode(self, turn_off_display: bool = False):
        if turn_off_display:
            self._write("DISPlay OFF")
        else:
            self._write("DISPlay ON")

    def measure_dc_voltage(self):
        return float(self._query("READ?"))
    
    def check_error(self, clear_queue: bool = False):
        """
        Query and return all errors in the 34401A error queue.
        If clear_queue is True, sends *CLS at the end.
        Returns a list of tuples: [(code1, msg1), (code2, msg2), …].
        """
        errors = []
        while True:
            resp = self._query("SYST:ERR?")
            code_str, msg = resp.split(",", 1)
            code = int(code_str)
            msg = msg.strip().strip('"')
            if code == 0:
                break
            errors.append((code, msg))
        if clear_queue:
            self._write("*CLS")
        return errors
    
    
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
            # IEEE-488.2 device clear: flush buffers on the _virument side
            self._vi.clear()  # type: ignore[attr-defined]
        except Exception:
            pass  # ignore issues during buffer clear

        try:
            self._vi.write("*CLS")
            self._vi.write("*RST")
            self._vi.close()  # type: ignore[attr-defined]
            rm.close()
        except Exception:
            pass  # ignore errors if already closed
        self._vi = None



if __name__=="__main__":
    addr = 'GPIB0::21::INSTR'
    dmm = HP34401A_Hardware(addr)
    print("Connected")
    #dmm.set_nplc(nplc = 1)
    #print(dmm.check_error())
    #dmm.dark_mode(False)
    print(dmm.measure_dc_voltage())
    print(dmm.idn())
    #time.sleep(3)
    print(dmm.check_error())
    dmm.NPLC(4, write = True)
    print(dmm.NPLC(read = True))

    for i in range(5):
        #voltage = dmm._query('MEAS:VOLT:DC?')
        #print(f'Measured DC voltage with _query: {voltage} V')
        
        voltage = dmm.measure_dc_voltage()
        print(f'Measured DC voltage with measure_dc: {voltage} V')
        
    dmm.disconnect()