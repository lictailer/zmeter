# Thorlabs Optical Power Meter

## Purpose and status

`tlpm` wraps the Thorlabs TLPM C driver for supported PM100/PM160/PM200/PM400-family devices. The ZMeter logic currently uses only resource discovery, first-resource connection, wavelength setting, power measurement, periodic reads, and disconnect, although the generated hardware wrapper exposes much more of the vendor API.

The package is registered startup-only and has hardware-independent tests that intercept the native boundary, but no production fake backend or recorded hardware-validation matrix. Panel construction does not load `TLPM_64.dll`; connecting constructs the hardware wrapper, discovers devices, and opens the first resource with identity query and reset enabled.

## Scan channels

- getter: `get_power()` returns the driver's power value, normally watts under the default driver unit;
- setters: none. `set_wavelength_target(value)` only stores a target and does not itself write the device, so discovery does not expose wavelength setting as a scan action.

The UI wavelength value is in nanometers. Indefinite display reads default to 20 Hz.

## Setup

- Python: PyQt6, NumPy, pyqtgraph, and `ctypes` from the standard library;
- system: Thorlabs optical power meter driver/VISA components matching 64-bit Python;
- native library: `TLPM_64.dll` and all of its runtime dependencies;
- configuration: approved device identity/resource, sensor model, wavelength range, power unit, averaging, and measurement range.

First-resource selection and reset are explicitly retained compatibility risks. Connect only the intended meter and verify its resource, model, serial, and sensor identity before proceeding.

## Lifecycle and safety gaps

Connection errors close partial discovery/device sessions, report failure, reset worker flags, and permit retry. `force_stop()` requests the indefinite-read loop to exit. `terminate_dev()` waits up to 10 seconds and disconnects only after the worker exits; if it cannot prove exit, it returns failure so the manager does not close beneath the worker. No `start_scan`/`stop_scan` hooks coordinate monitoring with scans, and a native driver call can still occupy the worker beyond the join deadline.

Agents must not load/run resource discovery, open/reset a meter, change wavelength, read power, or disconnect it. See [device_contract.md](../../documents/device_contract.md) and [hardware_safety.md](../../documents/hardware_safety.md). Any bench procedure is a **User-executed hardware test**.

## Validation

Hardware-independent syntax check: `python -B -m py_compile devices/tlpm/tlpm_hardware.py devices/tlpm/tlpm_logic.py devices/tlpm/tlpm_main.py`. It checks syntax only and does not load `TLPM_64.dll`.

**User-executed hardware test:** connect only the intended meter so first-resource selection is unambiguous; verify model, serial, sensor, calibration message, and power unit; set a wavelength within the attached sensor's calibrated range; measure a blocked sensor and a known stable optical source; start and stop the 20 Hz monitor; disconnect; and verify the driver session closes. Do not expose the meter to an unknown or over-range source.
