# Auto Position Prototype

## Status

`auto_position` is a standalone, experimental galvo/photodiode positioning prototype. It is not a current ZMeter device integration: the widget has no `.logic` object, uses PyQt5 while ZMeter uses PyQt6, imports `nidaq_hardware` as a top-level module, and loads its UI from the process working directory.

Do not add it to the reviewed driver registry or select it in a profile in its present form.

## Current behavior

`AutoPositionSystem` creates NI analog-output tasks for X/Y and an analog-input task for the photodiode during construction. It scans a square voltage grid, measures a reflection map, estimates image shift with phase cross-correlation, moves the two outputs to the corrected point of interest, and writes MAT/PNG results.

The current source embeds `Dev1` channel names and default scan coordinates. Those values are experimental defaults, not approved limits or calibration.

## Dependencies and outputs

- PyQt5, NumPy, SciPy, scikit-image, Matplotlib, and the legacy `NIDAQHardWare` interface;
- configured NI-DAQmx system software and an appropriate device;
- `.mat` and `.png` output under the selected results directory.

## Required work before integration

- port the widget to PyQt6 and package-relative paths/imports;
- inject an already-owned DAQ or use the device command router instead of direct device coupling;
- move hardware task creation out of constructors;
- add scan-facing signatures only for deliberate numeric channels;
- add finite/range validation, stop/force-stop, idempotent disconnect, and final teardown;
- make all device names, channels, ranges, centers, and output paths profile configuration.

Agents must not instantiate this prototype or run its scan. See [device_contract.md](../documents/device_contract.md) and [hardware_safety.md](../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile auto_position/canonical_position_logic.py auto_position/canonical_position_main.py`. No bench checklist is sanctioned in the current form because construction creates real NI tasks and the module lacks ZMeter lifecycle/safety boundaries. Refactor and simulate it before proposing a **User-executed hardware test**.
