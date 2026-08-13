# AutoFocusXZ / AutoPositionXZ

This folder contains a combined drift-compensation module for scanning experiments:

- `autoposition (X/Y)`: compensate lateral drift by map registration
- `autofocus (Z)`: compensate focus drift by two-pass peak search

The module is designed to run as a device in `zmeter` and communicate with other devices through the command bus.

## Purpose

During long scans, sample position and focus can drift (temperature, mechanical drift, etc.).
This module periodically measures drift and updates software offsets:

- `xy_offset` for beam/sample lateral alignment
- `z_offset` for focus alignment

These offsets are then applied by `set_x_with_offset`, `set_y_with_offset`, and `set_z_with_offset`.

## Device Structure

The implementation is split into 4 layers.

1. UI layer: `autofocusXZ_main.py`
- Loads `autofocusXZ.ui`
- Binds all buttons/signals
- Uses nested menus for channel selection (`device -> channel`)
- Shows status/progress/log text

2. Logic layer: `autofocusXZ_logic.py`
- Owns workflow state (`xy_offset`, `z_offset`, references, history)
- Runs autoposition/autofocus algorithms
- Emits Qt signals for status/progress/offset updates
- Handles stop requests for long operations

3. Hardware wrappers: `autofocusXZ_hardware.py`
- `AutofocusXZHardware`: Z stage via Arduino stepper + routed reference read
- `AutoPositionXZHardware`: routed XY writes + routed reference read
- Uses `DeviceCommandClient` with injected `command_router`

4. Helper algorithms: `autopositionXZ_helpers.py`
- Square XY map acquisition and scan-compatible JSON save
- XY offset fitting via `phase_cross_correlation`
- Z profile scan and Gaussian peak fitting
- PPT slide generation (with Windows COM fallback for force-save behavior)

Arduino side:
- `stepper_driver/stepper_driver.ino` handles serial stepper commands and degree-step conversion.

## Command Bus Integration

Channel control is routed through `MainWindow` command router.

Workflow:
1. `list_available_channels()`
2. Select `device_channel` from nested menu
3. Apply config (`X out`, `Y out`, `XY ref`, `Z ref`)
4. Read/write through routed requests

## AutoPosition Algorithm (X/Y)

Reference setup:
1. User defines center `(x, y)`, span, points-per-line.
2. Module scans a square map (X fast axis, Y slow axis).
3. Map is saved to JSON (`save_path/autoposition/...`), and can be loaded later.

Compensation run:
1. Scan a new XY map around current center + existing offset.
2. Fit shift between reference and new map with `phase_cross_correlation`.
3. Convert pixel shift to physical XY offsets.
4. Validate fit quality threshold.
5. If accepted, update:
- `xy_offset <- xy_offset + delta_offset`
6. Save current map JSON and append a comparison slide to autoposition PPT.

## AutoFocus Algorithm (Z)

Input:
- focus reference point `(x, y)`
- threshold
- down/up limits
- coarse/fine step settings

Procedure:
1. Move XY to focus reference (with XY offset applied).
2. Coarse Z sweep between limits and measure reference value at each point.
3. Gaussian-fit coarse profile to estimate peak.
4. Fine Z sweep around coarse peak with smaller step.
5. Gaussian-fit fine profile.
6. Validate fit consistency:
- coarse/fine peak distance limit
- fine/coarse peak ratio limit
- threshold condition
7. If valid, move to fine peak and update:
- `z_offset <- current_physical_z`
8. Append coarse/fine plot slide to autofocus PPT.

## Home and Offset Behavior

- `Move XY Abs Home`: moves hardware XY to `(0, 0)`.
- `Move XY Home (Offset)`: moves logical XY to `(0, 0)`, hardware to `(xy_offset_x, xy_offset_y)`.
- `Move Z Abs Home`: moves hardware Z to absolute home (`0`).
- `Move Z Home (Offset)`: moves logical Z to `0`, hardware to `z_offset`.

## Data and Reports

Saved under `save_path`:

- `autoposition/`: reference and current map JSON files
- `autofocus/`: Z offset history CSV exports
- `autofocusXZ_reports/`:
  - `autoposition_report.pptx`
  - `autofocus_report.pptx`

Status logs can also be exported from the UI (`Save Log`).

## Stop / Safety

- UI `Stop` button sets a stop request flag.
- Long scans check this flag between points/lines.
- If requested, operation exits with a controlled stop message.

## Main Public Logic APIs

Common UI-facing methods include:

- Reference and maps:
  - `scan_xy_reference_mapping(...)`
  - `load_xy_reference_mapping(path)`
  - `set_autoposition(settings)`

- Focus:
  - `set_autofocus_abs_maximum(settings)`

- Offsets/history:
  - `read_xy_current_offset()`
  - `set_xy_offset(x, y, source=...)`
  - `read_z_current_offset()`
  - `current_z_to_zero()`
  - `clear_*_offset_history()`
  - `export_*_offset_history(...)`

- Motion:
  - `set_x_with_offset(v)`
  - `set_y_with_offset(v)`
  - `set_z_with_offset(v)`
  - `move_xy_to_home()`, `move_xy_to_abs_home()`
  - `move_z_to_home()`, `move_z_to_abs_home()`

