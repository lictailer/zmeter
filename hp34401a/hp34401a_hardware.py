import logging
import pyvisa
import time
from typing import Optional, List, Tuple, Union

logging.basicConfig(level=logging.ERROR, format='%(asctime)s - %(levelname)s - %(message)s')
'''
logging.DEBUG -- Detailed information, typically only of interest to a developer trying to diagnose a problem.
logging.INFO -- Confirmation that things are working as expected.
logging.WARNING -- An indication that something unexpected happened, or that a problem might occur in the near future (e.g. ‘disk space low’). The software is still working as expected.
logging.ERROR -- Due to a more serious problem, the software has not been able to perform some function.
logging.CRITICAL -- A serious error, indicating that the program itself may be unable to continue running.
'''

class HP34401AError(Exception):
    """Custom exception for HP34401A specific errors."""
    pass


class HP34401A_Hardware:
    """
    HP34401A Digital Multimeter Controller
    
    Provides a clean interface for controlling the HP34401A multimeter
    via GPIB/USB/Ethernet using PyVISA.
    """
    
    # Valid NPLC (Number of Power Line Cycles) values
    VALID_NPLC_VALUES = [0.02, 0.2, 1, 10, 100]
    
    # Default timeouts and retry settings
    DEFAULT_TIMEOUT = 5000  # milliseconds
    MAX_RETRY_ATTEMPTS = 3
    RETRY_DELAY = 0.01  # seconds
    
    def __init__(self, address: str, timeout: Optional[int] = None):
        """
        Initialize connection to HP34401A multimeter.
        
        Args:
            address: VISA resource address (e.g., 'GPIB0::21::INSTR')
            timeout: Communication timeout in milliseconds
        """
        self._address = address
        self._timeout = timeout or self.DEFAULT_TIMEOUT
        self._rm = None
        self._vi = None
        
        self._connect()
        self._initialize_device()
    
    def _connect(self):
        """Establish VISA connection to the instrument."""
        try:
            self._rm = pyvisa.ResourceManager()
            self._vi = self._rm.open_resource(self._address)
            self._vi.timeout = self._timeout
            logging.info(f"Connected to HP34401A at {self._address}")
        except Exception as e:
            raise HP34401AError(f"Failed to connect to {self._address}: {e}")
    
    def _initialize_device(self):
        """Reset and initialize the device to a known state."""
        self._write("*RST")  # Reset to known state
        self._write("*CLS")  # Clear status
        time.sleep(0.1)  # Allow device to settle
        
        # Verify connection by checking device identity
        idn = self.get_identity()
        if "34401A" not in idn:
            logging.warning(f"Unexpected device identity: {idn}")
    
    def _write(self, command: str):
        """ Send a command to the instrument. """
        if not self._vi:
            raise HP34401AError("Device not connected")
        
        logging.debug(f"→ {command}")
        try:
            self._vi.write(command)
        except Exception as e:
            raise HP34401AError(f"Failed to write command '{command}': {e}")
    
    def _query(self, command: str) -> str:
        """
        Send a query command and return the response.
        Args:
            command: SCPI query command string
        Returns:
            Response string from the instrument
        """
        if not self._vi:
            raise HP34401AError("Device not connected")
        
        logging.debug(f"? {command}")
        
        for attempt in range(self.MAX_RETRY_ATTEMPTS):
            try:
                response = self._vi.query(command).strip() # type: ignore
                logging.debug(f"← {response}")
                return response
            except Exception as e:
                if attempt < self.MAX_RETRY_ATTEMPTS - 1:
                    logging.warning(f"Query '{command}' failed (attempt {attempt + 1}): {e}")
                    time.sleep(self.RETRY_DELAY)
                else:
                    raise HP34401AError(f"Failed to query '{command}' after {self.MAX_RETRY_ATTEMPTS} attempts: {e}")
    
    def get_identity(self) -> str:
        """ Returns: Device identification string """
        return self._query("*IDN?")
    
    def set_nplc(self, nplc: float):
        """
        Set the Number of Power Line Cycles for DC voltage measurements.
        Args: nplc (0.02, 0.2, 1, 10, or 100)
        """
        if nplc not in self.VALID_NPLC_VALUES:
            raise ValueError(f"NPLC must be one of {self.VALID_NPLC_VALUES}")
        
        self._write(f"VOLT:DC:NPLC {nplc}")
        logging.info(f"Set NPLC to {nplc}")
    
    def get_nplc(self) -> float:
        """ Returns current NPLC value """
        response = self._query("SENS:VOLT:DC:NPLC?")
        return float(response)
    
    def set_display(self, enabled: bool = True):
        """ True to enable display, False to disable (dark mode) """
        command = "DISPlay ON" if enabled else "DISPlay OFF"
        self._write(command)
        logging.info(f"Display {'enabled' if enabled else 'disabled'}")
    
    def measure_dc_voltage(self) -> float:
        """ Measured DC voltage in volts """
        try:
            response = self._query("READ?")
            voltage = float(response)
            logging.debug(f"Measured DC voltage: {voltage} V")
            return voltage
        except ValueError as e:
            raise HP34401AError(f"Invalid voltage reading: {response}")
    

    
    def get_errors(self, clear_after_read: bool = False) -> List[Tuple[int, str]]:
        """
        Read all errors from the instrument error queue.
        
        Args:
            clear_after_read: If True, clear the error queue after reading
            
        Returns:
            List of (error_code, error_message) tuples
        """
        errors = []
        
        while True:
            try:
                response = self._query("SYST:ERR?")
                code_str, message = response.split(",", 1)
                code = int(code_str)
                message = message.strip().strip('"')
                
                if code == 0:  # No error
                    break
                    
                errors.append((code, message))
                logging.warning(f"Device error {code}: {message}")
                
            except Exception as e:
                logging.error(f"Failed to read error queue: {e}")
                break
        
        if clear_after_read and errors:
            self._write("*CLS")
        
        return errors
    
    def check_for_errors(self):
        """
        Check for errors and raise an exception if any are found.
        
        Raises:
            HP34401AError: If any errors are found in the error queue
        """
        errors = self.get_errors(clear_after_read=True)
        if errors:
            error_msgs = [f"{code}: {msg}" for code, msg in errors]
            raise HP34401AError(f"Device errors: {'; '.join(error_msgs)}")
    
    def reset(self):
        """Reset the instrument to its default state."""
        self._write("*RST")
        self._write("*CLS")
        time.sleep(0.1)
        logging.info("Device reset")
    
    def disconnect(self):
        """
        Safely disconnect from the instrument.
        
        Clears any pending operations and closes the VISA connection.
        """
        if not self._vi:
            return
        
        try:
            # Clear any pending operations
            self._vi.clear()
            self._write("*CLS")
            logging.info("Disconnecting from HP34401A")
        except Exception as e:
            logging.warning(f"Error during disconnect cleanup: {e}")
        
        try:
            self._vi.close()
            if self._rm:
                self._rm.close()
        except Exception as e:
            logging.warning(f"Error closing VISA resources: {e}")
        finally:
            self._vi = None
            self._rm = None


def main():
    """Example usage of the HP34401A_Hardware controller."""
    logging.basicConfig(level=logging.INFO)
    
    address = 'GPIB0::21::INSTR'
    
    try:
        dmm = HP34401A_Hardware(address)
        print(f"Connected to: {dmm.get_identity()}")
        
        # Configure measurement settings
        dmm.set_nplc(1)  # 1 power line cycle for good accuracy/speed balance
        #dmm.set_display(False)  # Dark mode for sensitive measurements
        
        print(f"Current NPLC: {dmm.get_nplc()}")
        
        # Perform measurements
        print("\nPerforming 5 DC voltage measurements:")
        for i in range(5):
            voltage = dmm.measure_dc_voltage()
            print(f"  Measurement {i+1}: {voltage:.6f} V")
            time.sleep(0.1)
        
        # Check for any errors
        errors = dmm.get_errors()
        if errors:
            print(f"\nDevice errors detected: {errors}")
        else:
            print("\nNo errors detected")
            
        # Always disconnect
        dmm.disconnect()
        
    except HP34401AError as e:
        print(f"HP34401A Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()