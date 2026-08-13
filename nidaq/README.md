# Legacy NI-DAQ Integration

## Purpose and status

`nidaq` is the legacy NI data-acquisition integration built on PyDAQmx. It manages analog outputs, analog inputs, a sample counter, and lower-level clock/counter tasks. Prefer `ni6423` for the currently documented USB-6423 path; retain this module only for configurations that require its older API.

The current package has no focused automated tests or simulated backend. Its hardware layer creates and retains task objects, so validation must explicitly cover cleanup after partial setup.

## Scan channels

Current `.logic` discovery exposes:

- setters: `AO0`, `AO1` in volts;
- getters: `AI0` through `AI6` and `sample_count`.

The logic internally defines targets for AO0 through AO3, but only AO0 and AO1 have exact scan setters. The widget lists AI0 through AI7, but only AI0 through AI6 have exact scan getters. Treat those mismatches as current interface boundaries, not implied support.

AI acquisition averages a configurable sample count, clamped to 1 through 2047. The sample counter uses a configurable accumulation time. The module also contains pulse/clock/counter helpers that are not scan-visible.

## Setup and lifecycle

- Python: PyQt6, NumPy, PyDAQmx, and pyqtgraph;
- system: a compatible NI-DAQmx runtime and device driver;
- configuration: exact NI device name and physical AO/AI/counter/clock terminal names.

`terminate_dev` calls the logic close path, which closes the currently configured tasks. The widget has no standard `start_scan`, `stop_scan`, or `force_stop` hooks. Review monitor contention, task reuse, timeout, stop, and partial-initialization cleanup before enabling it.

Agents must not initialize NI hardware, create tasks, write or read channels, emit pulses, route clocks/counters, or close real tasks. See [device_contract.md](../documents/device_contract.md) and [hardware_safety.md](../documents/hardware_safety.md). Hardware validation is user-executed only.

## Validation

Hardware-independent syntax check: `python -B -m py_compile nidaq/nidaq_hardware.py nidaq/nidaq_logic.py nidaq/nidaq_main.py`. No simulated PyDAQmx backend is present.

**User-executed hardware test:** with a reviewed breakout disconnected from the experiment, initialize the explicit NI device; write 0 V and +0.1 V to each enabled AO separately; read a grounded AI and a known reference; acquire the sample counter from a known source for the configured window; stop monitoring; terminate; and confirm every task can be recreated after cleanup. Do not test clock/pulse helpers until their terminal routing and load are documented.
