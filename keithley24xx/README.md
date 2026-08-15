# Keithley 24xx SourceMeter

## Purpose and status

This package controls a Keithley 24xx-family source-measure unit through the shared `VisaRuntime`. It supports voltage or current sourcing, voltage or current sensing, a software voltage ramp, live UI reads, and output shutdown on close. Shared-session lifecycle and offscreen construction have fake coverage; model-by-model hardware validation remains pending.

After construction, the widget schedules one VISA enumeration on the next Qt event-loop turn. Discovery runs in a worker thread, populates a width-adjusted address dropdown, and never opens an instrument session. The operator can still click **Refresh VISA**. Disconnect closes only this device's session; the manager closes at provider shutdown.

## Scan channels

Current `.logic` discovery exposes:

- setters: `set_direct_source_voltage`, `set_ramp_source_voltage`, `set_source_current`;
- getters: `get_voltage`, `get_current`.

Units are volts and amperes. A setter silently returns without action when the source mode does not match, so the user must establish and verify source mode before a scan. Getter calls change the sensing function before reading.

## Ramp and compliance behavior

The default software voltage ramp is 1 V/s with 100 updates/s. `force_stop` is checked between steps and preserves the last commanded voltage. The implementation falls back to a presumed 0 V ramp start when the initial voltage response is nonnumeric; this is a high-risk uncertainty that must be resolved before production use.

Default sensing compliance arguments are 200 V for voltage sensing and `1e-5` A for current sensing. They are code defaults, not experiment-approved protection values. The hardware layer does not enforce explicit source limits; configure matching device and `scan_range_limits.json` limits before use.

## Setup and lifecycle

- Python: PyQt6, PyVISA, NumPy, pyqtgraph;
- system: a compatible VISA backend and the correct interface driver;
- configuration: exact model, VISA address, source mode, sense mode, compliance, ramp rate, update rate, and safe output range.

Connection selects voltage source/current sense and enables output. `terminate_dev` requests ramp stop, waits up to two seconds, and closes the hardware; hardware close turns output off and clears status. The widget has no `start_scan`/`stop_scan` hooks.

Agents must not enumerate VISA resources, connect, enable output, source, ramp, read, reset, or disconnect the SMU. See [hardware_safety.md](../documents/hardware_safety.md). Hardware validation is a **User-executed hardware test** only.

## Validation

Hardware-independent syntax check: `python -B -m py_compile keithley24xx/keithley24xx_hardware.py keithley24xx/keithley24xx_logic.py keithley24xx/keithley24xx_main.py`.

**User-executed hardware test:** isolate the SMU from the experiment and attach a suitable dummy load; set reviewed compliance and source limits on the instrument; connect to the explicit VISA address; command 0 V; ramp only to a user-approved low target; request stop during a second ramp and record the last actual value; test one bounded current-source/readback case; terminate; and verify output is off with an independent meter. Do not use the scan engine until this sequence passes.
