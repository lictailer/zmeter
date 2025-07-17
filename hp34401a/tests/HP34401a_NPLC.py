import pyvisa

def main():
    # 1. Open the VISA resource manager
    rm = pyvisa.ResourceManager()
    
    # 2. Open a connection to the DMM 
    inst = rm.open_resource('GPIB0::21::INSTR')
    
    # 3. Basic sanity check: ask for the instrument ID
    idn = inst.query('*IDN?') # type: ignore
    print(f'Connected to: {idn.strip()}')
    
    # 4. Configure for a DC voltage measurement (auto range)
    inst.write('CONF:VOLT:DC AUTO')

    
    
    
    # 5. Trigger and read one measurement
    inst.write('SENS:VOLT:DC:NPLC 100')
    NPLC = inst.query('SENS:VOLT:DC:NPLC?')
    print(f'NPLC: {NPLC.strip()}')

    for i in range(5):
        voltage = inst.query('READ?')
        print(f'Measured DC voltage: {voltage.strip()} V')
    
    # 6. Always clean up
    inst.close()
    rm.close()

if __name__ == '__main__':
    main()
