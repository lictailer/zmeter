# Stanford Research Systems SR860

## Purpose and status

This package controls an SRS SR860 lock-in amplifier through PyVISA. It covers demodulated outputs, reference/source settings, input configuration, sensitivity/time constant, filters, display/status values, and auxiliary I/O. It has no focused automated tests or recorded bench-validation matrix.

Constructing the widget enumerates VISA resources. Do not instantiate it during hardware-independent tests.

## Current scan discovery

The exact `.logic` signatures expose one setter, `set_amplitude(value)`, and many getters. Numeric acquisition candidates include `X`, `Y`, `R`, `Theta`, `frequency`, `amplitude`, `phase`, and the currently selected auxiliary input/output. Status getters expose overload/unlock state.

Configuration getters include time constant, sensitivity, reference mode/input, trigger, harmonic, input modes/ranges, coupling, shield, notch filter, DC level/mode, and filter slope. `get_multiple_outputs`, `get_display`, and `get_all` return compound or non-measurement results. Use profile filters so only numeric scalar measurement channels are exposed.

Most logic `set_*` methods use stored UI setpoints and therefore are not scan-visible. Do not infer scan writability from the widget controls.

## Setup and units

- Python: PyQt6, PyVISA, NumPy, and pyqtgraph;
- system: compatible VISA backend/interface driver;
- configuration: explicit VISA resource, input/reference mode, ranges, sensitivity, time constant, filters, auxiliary channel, and safe source amplitude.

The hardware documents internal reference frequency as 1 mHz–500 kHz and sine output amplitude as 1 nV–2 V RMS. Phase/`Theta` are degrees; voltage-mode demodulated outputs and auxiliary I/O are volts. Confirm limits against the exact instrument/manual and experiment.

## Lifecycle and safety

Connection checks that identity contains `SR860`, and termination stops UI monitoring then disconnects. The widget does not implement standard `start_scan`, `stop_scan`, or `force_stop`, so automatic scan coordination is incomplete. A 50 ms monitor can otherwise compete with scan reads.

Agents must not enumerate VISA resources, connect, configure, source, read, reset, or disconnect the SR860. The user must validate filters, units, timeouts, monitor coordination, auxiliary limits, and shutdown state. See [hardware_safety.md](../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile sr860/sr860_hardware.py sr860/sr860_logic.py sr860/sr860_main.py`.

**User-executed hardware test:** use a disconnected/dummy signal path; connect to the explicit VISA address and confirm SR860 identity; record existing configuration; read X/Y/R/Theta and overload state; set the sine amplitude to a reviewed low value; verify the scan-visible amplitude setter/readback; write only 0 V to a reviewed auxiliary output; stop monitoring and simulate a timeout; terminate; and confirm the session closes without changing unrelated settings.
