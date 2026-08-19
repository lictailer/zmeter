# SP150 Monochromator

## Status

This package integrates an SP150 monochromator through an explicit PyVISA connection. Its transport, scan discovery, bounded move polling, lifecycle, and widget behavior have hardware-independent fake-VISA coverage. No physical monochromator has been accessed or validated by the coding agent.

## Dependencies and configuration

- Python: PyQt6 and PyVISA from `zmeter_May2026_environment.yml`;
- system: NI-VISA or another compatible VISA implementation plus the correct GPIB/USB adapter driver;
- configuration: the exact VISA resource address, supplied explicitly by the laboratory profile.

The integration never enumerates resources and has no default address. The resource uses `\r` write termination, `\n` read termination, a default 10-second VISA timeout, and a default one-second query delay.

Example profile setup:

```python
from core.shared_runtime import RuntimeServices
from devices.sp150.sp150_main import SP150

services = RuntimeServices()
mono = SP150(
    visa_runtime=services.visa,
    move_timeout_s=120.0,
    poll_interval_s=0.25,
    completion_tolerance_nm=0.1,
)
mono.connect("GPIB1::11::INSTR")  # Replace with the reviewed profile address.
equips["sp150"] = mono
```

Do not copy the example address into a shared profile without verifying it in the intended lab.

## Scan channels and protocol

| Direction | Channel | Units | Device-layer range |
| --- | --- | --- | --- |
| Set/Get | `wavelength` | nm | 0 to 3000 nm |

The logic exposes only `set_wavelength(value)` and `get_wavelength()` to scan discovery. Values must be finite. Reads send `?NM`; writes send `<value> <GOTO>` with two decimal places.

After a write, the logic polls readback until it is within the configured tolerance. Defaults are a 120-second move timeout, 0.25-second interval between queries, and 0.1 nm tolerance. These values are software limits awaiting bench confirmation; a lab profile should narrow or adjust them only after reviewing the actual grating, drive speed, and safe operating range. Failed writes are not retried automatically.

Repository-wide scan limits remain separate and are keyed by the stable equipment label plus channel. A lab profile may impose a narrower wavelength range.

## Lifecycle and failure behavior

- Widget construction creates no ResourceManager and performs no discovery or connection.
- Getters and setters fail clearly while disconnected; they never auto-connect.
- UI operations run through the logic worker and are rejected while another operation or a scan owns the device.
- `stop_scan()` cancels a conflicting UI operation before scan access; `start_scan()` restores normal UI use after cleanup.
- `force_stop()` cancels move polling immediately between VISA queries. A query already in progress may remain pending until its configured VISA timeout.
- A move timeout reports both the target and last confirmed readback. The requested target is never reported as the actual value without readback confirmation.
- `disconnect()` and `terminate_dev()` close only this device's VISA lease/session idempotently after active I/O finishes. The shared ResourceManager closes at provider shutdown.

After a timeout, cancellation, malformed response, or uncertain move, the user must inspect the monochromator before issuing another command.

## Hardware-independent validation

```powershell
python -B -m py_compile devices/sp150/sp150_hardware.py devices/sp150/sp150_logic.py devices/sp150/sp150_main.py
python -B -m unittest discover -s devices/sp150/tests -p "test_*.py" -v
```

The tests use an injected `VisaRuntime` with a fake manager. They do not instantiate a real ResourceManager.

## User-executed hardware test

1. Confirm the exact monochromator model/firmware, installed grating, adapter, VISA address, cable, and permitted wavelength range.
2. Establish an independently reviewed optical-safe state and verify the current wavelength on the instrument.
3. Start from a reviewed lab profile and connect to the explicit address without enumerating other resources.
4. Read wavelength once and compare it with the instrument display.
5. Command the current wavelength first, then make the smallest approved bounded change and verify polling/readback completion.
6. Test one deliberately short move timeout at a safe target, then restore the reviewed timeout and verify the reported last readback.
7. Request stop during a controlled small move and verify that no new queries are issued after cancellation and that any in-flight query is reported as pending.
8. Disconnect, close ZMeter normally, and independently verify the final wavelength and safe optical state.
9. Record the address, driver/grating configuration, commands, readbacks, timeout/stop result, and final state. Only the observed model and modes may be called hardware-validated.
