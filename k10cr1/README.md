# Thorlabs K10CR1 Rotation Mount

## Purpose and status

This package controls a Thorlabs K10CR1 integrated rotation mount through the Kinesis C API. It includes local DLL bindings, a `QThread` logic layer, and a PyQt6 widget. The current stop and termination behavior is incomplete, so it must not be treated as production-ready without corrective work and a user-run bench review.

Importing the hardware module immediately loads and binds the vendor DLL. The fallback contains a lab-specific absolute path, and failure to load can leave the binding variable undefined.

## Scan channels

Current `.logic` discovery exposes:

- `set_angle(value)`: absolute angular target in degrees;
- `get_angle()`: current position converted to degrees.

The conversion uses 49,152,000 device counts per 360 degrees. The setter applies modulo-one-turn completion logic and polls until repeated completion, a stuck-position condition, or an iteration cap. No software angular limits are enforced in this package.

## Setup

- Python: PyQt6;
- system: Thorlabs Kinesis runtime/driver matching process bitness;
- native libraries: `Thorlabs.MotionControl.IntegratedStepperMotors.dll` and its dependencies;
- configuration: exact device serial, homing policy, allowed angular range, velocity, acceleration, and experiment-specific collision constraints.

The connection path builds the Kinesis device list, opens the serial-numbered device, reads hardware information, and overwrites velocity parameters. Homing and movement are blocking polling operations executed in the device thread.

## Lifecycle and safety gaps

The logic contains an immediate-stop call, but its own comment says it does not work. The widget's `force_stop()` is empty, and `terminate_dev()` only prints a message rather than stopping motion or disconnecting. There are no `start_scan`/`stop_scan` hooks or focused tests.

Before enabling the module, implement and simulate bounded stop, idempotent disconnect, shutdown cleanup, range validation, and last-confirmed-position reporting. Agents must not load/run Kinesis discovery, open a mount, home, change velocity, move, stop, or disconnect it. See [hardware_safety.md](../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile k10cr1/k10cr1_hardware.py k10cr1/k10cr1_logic.py k10cr1/k10cr1_main.py`. Loading the module is not hardware-independent because it loads and binds Kinesis.

No production bench test should be run until `force_stop` and termination are fixed. After that, the **User-executed hardware test** is: mechanically clear the full allowed travel; verify serial and limits; connect without homing; compare `get_angle()` to the mount; command the current angle; move +1 degree and back within approved limits; interrupt a longer bounded move; verify the last position; disconnect; and confirm the mount and Kinesis handle are released. Homing requires a separate user-reviewed procedure.
