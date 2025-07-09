import sys
import time
from PyQt6.QtCore import QCoreApplication

# Ensure sr860 package is importable regardless of working dir
try:
    from sr860 import sr860_hardware as _s_hw_pkg  # type: ignore
    sys.modules.setdefault("sr860_hardware", _s_hw_pkg)
    from sr860.sr860_logic import SR860_Logic  # type: ignore
except ImportError:
    # Fallback: assume script is executed from inside sr860 directory
    from sr860_hardware import SR860_Hardware  # noqa: F401
    from sr860_logic import SR860_Logic  # type: ignore


def main():
    # Default VISA address – edit this line to match your GPIB address
    DEFAULT_ADDRESS = "GPIB0::7::INSTR"

    if len(sys.argv) >= 2:
        visa_address = sys.argv[1]
    else:
        print("No address supplied on command line; using DEFAULT_ADDRESS =", DEFAULT_ADDRESS)
        visa_address = DEFAULT_ADDRESS

    # Qt application context for signal delivery
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    logic = SR860_Logic()

    # Connect signals to print callbacks
    logic.sig_is_changing.connect(lambda msg: print("[CHANGE]", msg))
    logic.sig_frequency.connect(lambda v: print("[READ] Frequency:", v, "Hz"))
    logic.sig_amplitude.connect(lambda v: print("[READ] Amplitude:", v, "V_rms"))
    logic.sig_time_constant.connect(lambda i: print("[READ] TimeConst index:", i))
    logic.sig_sensitivity.connect(lambda i: print("[READ] Sensitivity index:", i))
    logic.sig_phase.connect(lambda v: print("[READ] Phase:", v, "deg"))
    logic.sig_X.connect(lambda v: print("[READ] X:", v))
    logic.sig_Y.connect(lambda v: print("[READ] Y:", v))
    logic.sig_R.connect(lambda v: print("[READ] R:", v))
    logic.sig_Theta.connect(lambda v: print("[READ] Theta:", v))
    logic.sig_display.connect(lambda d: print("[READ] Display:", d))
    logic.sig_unlocked.connect(lambda b: print("[STATUS] Unlocked:", b))
    logic.sig_input_overload.connect(lambda b: print("[STATUS] Input overload:", b))
    logic.sig_multiple_outputs.connect(lambda d: print("[READ] Multiple outputs:", d))

    # --- Connect to hardware ---
    print(f"Connecting to SR860 at {visa_address} ...")
    logic.connect_visa(visa_address)

    # Short pause to ensure connection established
    time.sleep(0.2)

    # --- Basic getter tests ---
    print("\nInitial readings:")
    logic.read_frequency()
    logic.read_amplitude()
    logic.read_time_constant()
    logic.read_sensitivity()
    logic.read_phase()

    # Read signal outputs
    logic.get_X()
    logic.get_Y()
    logic.get_R()
    logic.get_Theta()

    # Display channels
    logic.read_display()

    # Status flags
    logic.read_unlocked()
    logic.read_input_overload()

    # --- Setter tests with safe values ---
    print("\nApplying new settings (safe values)...")
    logic.setpoint_frequency = 1000.0  # 1 kHz
    logic.write_frequency()

    logic.setpoint_amplitude = 0.01  # 10 mVrms
    logic.write_amplitude()

    logic.setpoint_time_constant = 3  # 10 ms
    logic.write_time_constant()

    logic.setpoint_sensitivity = 10  # 100 µV FS
    logic.write_sensitivity()

    logic.setpoint_phase = 30.0  # 30°
    logic.write_phase()

    # Auxiliary output: channel-1 to 0.123 V
    logic.setpoint_aux_channel = 1
    logic.setpoint_aux_voltage = 0.123
    logic.write_aux_out()

    # Read back
    time.sleep(0.2)
    print("\nRead-back after setting:")
    logic.read_frequency()
    logic.read_amplitude()
    logic.read_time_constant()
    logic.read_sensitivity()
    logic.read_phase()
    logic.read_aux_out()

    # Continuous polling example for 5 seconds
    print("\nStreaming X, Y, R, Theta for 5 s ...")
    # Ensure hardware instance exists for direct hardware calls
    assert logic.hardware is not None
    end = time.time() + 5
    while time.time() < end:
        logic.get_X()
        logic.get_Y()
        logic.get_R()
        logic.get_Theta()
        print(logic.hardware.get_multiple_outputs("X", "Y", "Theta"))
        time.sleep(0.1)

    print("Test complete.")
    
    # Disconnect from device
    print("Disconnecting from device...")
    logic.disconnect()
    print("Disconnected successfully.")


if __name__ == "__main__":
    main() 