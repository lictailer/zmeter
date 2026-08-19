# Thorlabs Optical Power Meter

## Purpose and status

`tlpm` wraps the Thorlabs TLPM C driver for supported PM100/PM160/PM200/PM400-family devices. The ZMeter logic currently uses only resource discovery, first-resource connection, wavelength setting, power measurement, periodic reads, and disconnect, although the generated hardware wrapper exposes much more of the vendor API.

The package has no focused automated tests or recorded hardware-validation matrix. Constructing the hardware wrapper loads `TLPM_64.dll`; connecting discovers devices and opens the first resource with identity query and reset enabled.

## Scan channels

- getter: `get_power()` returns the driver's power value, normally watts under the default driver unit;
- setters: none. `set_wavelength_target(value)` only stores a target and does not itself write the device, so discovery does not expose wavelength setting as a scan action.

The UI wavelength value is in nanometers. Indefinite display reads default to 20 Hz.

## Setup

- Python: PyQt6, NumPy, pyqtgraph, and `ctypes` from the standard library;
- system: Thorlabs optical power meter driver/VISA components matching 64-bit Python;
- native library: `TLPM_64.dll` and all of its runtime dependencies;
- configuration: approved device identity/resource, sensor model, wavelength range, power unit, averaging, and measurement range.

Do not assume the first discovered resource is the intended instrument. Production use should select and verify an explicit resource and sensor identity.

## Lifecycle and safety gaps

`force_stop()` is empty and `terminate_dev()` only prints a message. The indefinite-read stop flag is not the same as final device cleanup, and no `start_scan`/`stop_scan` hooks coordinate monitoring with scans. Implement deterministic stop, join, and disconnect before relying on shutdown.

Agents must not load/run resource discovery, open/reset a meter, change wavelength, read power, or disconnect it. See [device_contract.md](../../documents/device_contract.md) and [hardware_safety.md](../../documents/hardware_safety.md). Any bench procedure is a **User-executed hardware test**.

## Validation

Hardware-independent syntax check: `python -B -m py_compile devices/tlpm/tlpm_hardware.py devices/tlpm/tlpm_logic.py devices/tlpm/tlpm_main.py`. It checks syntax only and does not load `TLPM_64.dll`.

**User-executed hardware test:** connect only the intended meter so first-resource selection is unambiguous; verify model, serial, sensor, calibration message, and power unit; set a wavelength within the attached sensor's calibrated range; measure a blocked sensor and a known stable optical source; start and stop the 20 Hz monitor; disconnect; and verify the driver session closes. Do not expose the meter to an unknown or over-range source.
