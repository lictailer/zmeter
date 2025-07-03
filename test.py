import pyvisa
import time
import numpy as np

# Initialize VISA resource manager
rm = pyvisa.ResourceManager()
keithley = rm.open_resource('GPIB2::18::INSTR')  # Change to your instrument address

# Basic configuration
keithley.write('*RST')  # Reset to default
keithley.write(':SOUR:FUNC VOLT')  # Source voltage
keithley.write(':SOUR:VOLT:MODE FIXED')
keithley.write(':SOUR:VOLT:RANG 2')  # Set range appropriately
keithley.write(':SENS:FUNC "CURR"')  # Measure current
keithley.write(':SENS:CURR:PROT 0.01')  # Compliance current (10 mA)
keithley.write(':OUTP ON')

# Ramp settings
start_voltage = 0
end_voltage = 1
duration = 1  # in seconds
steps = 100  # number of steps for smoother ramp
delay = duration / steps  # delay between steps

voltages = np.linspace(start_voltage, end_voltage, steps)
start_time = time.time()
for v in voltages:
    keithley.write(f':SOUR:VOLT {v}')
    time.sleep(delay)
end_time = time.time()
print(f"Ramp start time: {start_time}")
print(f"Ramp end time: {end_time}")
print(f"Total ramp duration: {end_time - start_time:.3f} seconds")

# Optional: hold or return to 0V
# keithley.write(':SOUR:VOLT 0')
time.sleep(0.5)

# Turn off output and close
keithley.write(':OUTP OFF')
keithley.close()
rm.close()
