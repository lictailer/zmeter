# PEM100 Photoelastic Modulator

## Status

This package integrates a PEM100 photoelastic modulator through an explicit PyVISA serial connection. Its transport, scan discovery, lifecycle, and widget behavior have hardware-independent fake-VISA coverage. No physical PEM100 has been accessed or validated by the coding agent.

## Dependencies and configuration

- Python: PyQt6 and PyVISA from `zmeter_May2026_environment.yml`;
- system: a compatible VISA implementation and serial adapter driver;
- configuration: the exact VISA resource address, supplied explicitly by the laboratory profile.

The integration never enumerates VISA resources and has no default address. It configures the selected resource for 2400 baud, 8 data bits, no parity, one stop bit, no flow control, `\r\n` write termination, `\n\r*` read termination, and a default 20-second timeout.

Example profile setup:

```python
from core.shared_runtime import RuntimeServices
from pem100.pem100_main import PEM100

services = RuntimeServices()
pem = PEM100(visa_runtime=services.visa)
pem.connect("ASRL4::INSTR")  # Replace with the reviewed profile address.
equips["pem100"] = pem
```

Do not copy the example address into a shared profile without verifying it in the intended lab.

## Scan channels

| Direction | Channel | Units | Device-layer range |
| --- | --- | --- | --- |
| Set/Get | `wavelength` | nm | 170 to 2500 nm |
| Set/Get | `retardance` | lambda | 0 to 0.5 lambda |

The logic exposes only `set_wavelength(value)`, `get_wavelength()`, `set_retardance(value)`, and `get_retardance()` to scan discovery. Values must be finite. Setters send one command, consume its acknowledgement, and read back the resulting value; failed writes are not retried automatically.

Repository-wide scan limits remain separate and are keyed by the stable equipment label plus channel. A lab profile may set narrower limits but must not broaden the device ranges above.

## Lifecycle and failure behavior

- Widget construction creates no ResourceManager and performs no discovery or connection.
- Getters and setters fail clearly while disconnected; they never auto-connect.
- UI operations run through the logic worker and are rejected while another operation or a scan owns the device.
- `stop_scan()` cancels a conflicting UI operation before scan access; `start_scan()` restores normal UI use after cleanup.
- `force_stop()` is cooperative between VISA calls and protocol waits. A VISA read already in progress may remain pending until the configured VISA timeout.
- `disconnect()` and `terminate_dev()` close only this device's VISA lease/session idempotently. The shared ResourceManager stays alive until provider shutdown. A pending I/O call is allowed to finish before deferred cleanup rather than closing the resource concurrently.

Malformed numeric replies, failed acknowledgements, timeouts, and connection failures are reported with PEM100 context. After a timeout or uncertain acknowledgement, the user must verify the physical value before continuing.

## Hardware-independent validation

```powershell
python -B -m py_compile pem100\pem100_hardware.py pem100\pem100_logic.py pem100\pem100_main.py
python -B -m unittest discover -s pem100\tests -p "test_*.py" -v
```

The tests use an injected `VisaRuntime` with a fake manager. They do not instantiate a real ResourceManager.

## User-executed hardware test

1. Confirm the exact PEM100 model/firmware, serial adapter, VISA address, cable, and permitted optical setup.
2. Verify independently that the current wavelength is within 170–2500 nm and retardance is within 0–0.5 lambda.
3. Start from a reviewed lab profile and connect to the explicit address without enumerating other resources.
4. Read wavelength and retardance once and compare both with the instrument display.
5. Write the current displayed values first, then make the smallest approved bounded change to one channel and verify readback.
6. During a harmless read or bounded command, request stop and confirm the UI reports either completion or a pending VISA timeout honestly.
7. Disconnect, close ZMeter normally, and independently verify the final instrument state.
8. Record the address, driver version, commands, readbacks, timeout/stop result, and final state. Only the observed model and modes may be called hardware-validated.
