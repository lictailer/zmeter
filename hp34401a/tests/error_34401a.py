import pyvisa
import time

# open resource manager & instrument as before
rm   = pyvisa.ResourceManager()
inst = rm.open_resource('GPIB0::21::INSTR')

# --- Query the first error in the queue ---
err_code, err_msg = inst.query('SYST:ERR?').split(',', 1)
err_code = int(err_code)
err_msg  = err_msg.strip().strip('"')

print(f'Error {err_code}: {err_msg}')

# If you want to clear everything:
inst.write('*CLS')

inst.close()
rm.close()