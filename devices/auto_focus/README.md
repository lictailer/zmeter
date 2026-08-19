# Legacy Auto Focus Prototype

## Status

`auto_focus` is an experimental autofocus implementation, not a ready ZMeter device. It combines an Arduino-controlled Z stepper, NI analog outputs for X/Y galvos, and an NI analog input for a photodiode. The widget enumerates serial ports during construction and invokes the autofocus synchronously on the UI thread.

The current widget creates `autofocus_logic` with `xyz_sys=None`; later assigning `window.xyz_sys` does not update `window.logic.xyz_sys`. Connection and autofocus paths therefore require code correction before use. It also lacks the standard scan/start/stop/force-stop/termination lifecycle.

## Current algorithm and data

The stepper/galvo implementation scans a two-dimensional voltage grid, calculates a Sobel-gradient focus metric, samples three relative Z positions per iteration, halves the Z step, and finally moves by the selected accumulated angle. It can write per-iteration PNG files and a MAT summary.

Current embedded defaults include `COM 7`, 115200 baud, 7 RPM, `Dev1/AO0`, `Dev1/AO1`, and `Dev1/AI0`. These are source defaults only—not approved addresses, calibration, or limits.

## Scan discovery

If registered despite the limitations, the logic's only signature-matching getter is `get_run_idx()`. It is a file-number helper rather than a measurement channel and can fail when no save directory is set. Use profile filters or rename it before integration.

## Dependencies and required work

The source requires PyQt6, pyserial, the legacy NI DAQ interface, NumPy, SciPy, OpenCV, and Matplotlib. Before integration, remove direct cross-device coupling in favor of the router, make the UI nonblocking, configure paths/channels externally, validate all ranges and units, define recovery/stop behavior, and add hardware-independent tests.

Agents must not enumerate ports, open the serial device, create NI tasks, move the stepper/galvos, or acquire the photodiode. See [device_contract.md](../documents/device_contract.md) and [hardware_safety.md](../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile auto_focus/autofocus_logic.py auto_focus/autofocus_main.py`. No bench checklist is sanctioned until the broken object wiring, UI blocking, limits, router use, and lifecycle are corrected and covered by simulation. A later hardware procedure must be labeled **User-executed hardware test**.
