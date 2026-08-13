# HP 34401A Digital Multimeter

## Purpose and status

This package controls an HP 34401A-compatible digital multimeter through PyVISA and exposes DC-voltage acquisition to ZMeter. The implementation has separate widget, logic, and hardware files, but it has no device-specific automated tests or recorded hardware validation in this repository.

Constructing the widget creates a VISA resource manager and enumerates resources. Do not instantiate it during hardware-independent tests.

## Scan channels

Current `.logic` discovery exposes `get_dc_voltage`, `get_idn`, and `get_all`. Only `get_dc_voltage()` is a normal numeric measurement channel in volts. `get_idn()` returns text and `get_all()` returns no measurement value; filter them from a production profile.

NPLC and display controls are UI jobs named `read_NPLC`, `write_NPLC`, and `write_display_on`, so they are not scan-visible under the exact `get_*`/`set_*(value)` contract. The hardware accepts NPLC values `0.02`, `0.2`, `1`, `10`, and `100`.

## Setup

- Python: PyQt6, PyVISA, NumPy, and pyqtgraph;
- system: a compatible VISA backend and the instrument interface driver;
- configuration: an explicit VISA resource string in the lab startup profile.

The widget starts a 50 ms monitor timer but only schedules reads while connected and idle. Verify the intended measurement rate and NPLC together; the communication timeout and integration period must remain coherent.

## Lifecycle and safety

The widget provides `connect_visa`, `disconnect_device`, and `terminate_dev`; termination calls the logic disconnect path. It does not provide `start_scan`, `stop_scan`, or `force_stop`, so background-monitor coordination relies only on its busy check and is not a complete device lifecycle.

Review identity, error queue handling, NPLC, display state, timeout behavior, and disconnect after partial connection before enabling it. Agents must not enumerate VISA resources, connect, configure, read, or disconnect this instrument. See [hardware_safety.md](../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile hp34401a/hp34401a_hardware.py hp34401a/hp34401a_logic.py hp34401a/hp34401a_main.py`. This does not import the driver or validate an instrument.

**User-executed hardware test:** with the DMM disconnected from sensitive samples, select the reviewed VISA address; connect and confirm the HP 34401A identity; read a known safe DC reference at each intended NPLC; verify timeout/error reporting by removing the reference rather than the interface; stop monitoring; disconnect; and confirm the UI and VISA session are closed. The user reviews and performs every step.
