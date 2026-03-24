# autofocusXZ

## Purpose

This folder is for a newer combined autofocus + auto-position feature for `zmeter`.

The experiment need is:

- `autofocus`: recover the best Z focus when the sample drifts
- `auto-position`: recover the X/Y beam position when the sample shifts

The current work now includes hardware, helpers, logic, and a first integrated GUI binding layer.

## Current Status

Implemented:

- Arduino stepper serial protocol for the Z stepper motor
- Python hardware wrapper for Z autofocus: `AutofocusXZHardware`
- Python hardware wrapper for X/Y auto-position: `AutoPositionXZHardware`
- command-router-based read/write access for remote scan channels
- reusable auto-position helper module for square mapping and offset fitting
- combined logic layer in `autofocusXZ_logic.py` for:
  - XY reference map scan/load
  - XY offset fit/apply/history/export
  - Z offset/history/export
  - scan-facing setters with software offset compensation
  - absolute-home and offset-home helpers for both XY and Z
  - two-pass autofocus absolute-maximum workflow
  - Qt signal output for status/progress/offset/report-path updates
  - separated report targets:
    - autoposition PPT
    - autofocus PPT
- integrated GUI in `autofocusXZ_main.py` with:
  - full button-to-logic binding for autoposition/autofocus/manual functions
  - status panel logging with timestamp/progress/error messages
  - nested device/channel selectors for X out, Y out, XY ref, Z ref
  - channel catalog refresh from `list_available_channels()`

Current files:

- [autofocusXZ_hardware.py](C:/Users/Taylo/Documents/GitHub/zmeter/autofocus_xuguo/autofocusXZ_hardware.py)
- [autopositionXZ_helpers.py](C:/Users/Taylo/Documents/GitHub/zmeter/autofocus_xuguo/autopositionXZ_helpers.py)
- [autofocusXZ_logic.py](C:/Users/Taylo/Documents/GitHub/zmeter/autofocus_xuguo/autofocusXZ_logic.py)
- [autofocusXZ_main.py](C:/Users/Taylo/Documents/GitHub/zmeter/autofocus_xuguo/autofocusXZ_main.py)
- [stepper_driver.ino](C:/Users/Taylo/Documents/GitHub/zmeter/autofocus_xuguo/stepper_driver/stepper_driver.ino)

## Architecture

There are three hardware layers right now.

### 1. Raw stepper motor layer

Class: `stepperMotorHardware`

Responsibility:

- communicate with Arduino Nano over serial
- send blocking motor commands
- work only in motor angle units: degree

Main functions:

- `connect()`
- `disconnect()`
- `motor_move_absolute_to(deg)`
- `motor_move_relative_to(deg)`
- `motor_current_position()`
- `set_motor_current_position_to_zero()`
- `motor_position_to_home()`

Notes:

- CW is hard-coded as the positive motor angle direction
- all move functions wait until the Arduino replies after motion completes
- `HOME` is currently software home at `0 deg`

### 2. Autofocus Z wrapper

Class: `AutofocusXZHardware`

Responsibility:

- control Z only in height units
- convert between motor angle and translator height
- read the focus/reference value from another device through the command router

Default conversion:

- `translator_height_per_rev = 500 um`
- `gear_ratio = 100 / 30`

Meaning:

- one translator revolution moves `500 um`
- one motor revolution moves the translator by `500 / (100/30) = 150 um`

Main functions:

- `list_available_channels()`
- `set_reference_channel(device, channel)`
- `move_absolute_height(height_um)`
- `move_relative_height(delta_height_um)`
- `current_height()`
- `zero()`
- `home()`
- `read_reference_value()`

There is also a typo-safe alias:

- `move_absoulte_height(height_um)`

### 3. Auto-position X/Y wrapper

Class: `AutoPositionXZHardware`

Responsibility:

- control X and Y by writing to two remote output channels
- read the positioning reference from another remote channel
- use the device command bus instead of talking directly to NI hardware

Typical mapping:

- X -> `ni6432_0`, `AO0`
- Y -> `ni6432_0`, `AO1`
- reference -> `ni6432_0`, `AI0`

Main functions:

- `list_available_channels()`
- `set_position_channels(x_device, x_channel, y_device, y_channel)`
- `set_reference_channel(device, channel)`
- `move_absoluteX(value)`
- `move_absoluteY(value)`
- `read_reference_value()`

### 4. Auto-position helper functions

Module: `autopositionXZ_helpers.py`

Responsibility:

- run a lightweight square 2D map with X as fast axis and Y as slow axis
- save the map in a JSON structure compatible with the existing scan reader
- fit the X/Y compensation offset between a reference map and a new map

Main functions:

- `run_autoposition_square_mapping(...)`
- `fit_offset(...)`
- `run_autofocus_z_profile(...)`
- `fit_gaussian_peak(...)`
- `append_autoposition_report_slide(...)`
- `append_autofocus_report_slide(...)`
- `export_history_to_csv(...)`

The mapping helper saves JSON files into:

- `<save_path>/autoposition/`

The offset fitting helper:

- uses map registration to estimate pixel shift
- converts that shift into X/Y axis offsets
- rejects the fit if the quality is below a threshold

## Command Router Usage

The new code follows how `MainWindow` injects router metadata.

`MainWindow` does:

- inject `command_router`
- inject `device_label`

So in logic or hardware we do not need to manually find `MainWindow`.

The intended workflow for both autofocus and auto-position is:

1. call `list_available_channels()`
2. choose device + channel
3. configure the target channel with `set_reference_channel(...)` or `set_position_channels(...)`
4. call `read_reference_value()` or write motion values

Internally, the wrappers use `DeviceCommandClient` and wait for the response in a small blocking loop, so the public API feels like normal synchronous hardware I/O.

## Arduino Serial Protocol

Current Nano protocol:

- `PING`
- `MOVE_ABS <deg>`
- `MOVE_REL <deg>`
- `GET_POS`
- `ZERO`
- `HOME`

Responses:

- `READY`
- `OK PONG`
- `OK <position_deg>`
- `POS <position_deg>`
- `ERR <message>`

This protocol is implemented in:

- [stepper_driver.ino](C:/Users/Taylo/Documents/GitHub/zmeter/autofocus_xuguo/stepper_driver/stepper_driver.ino)

## Example Usage

### Autofocus Z

```python
hw = AutofocusXZHardware()
hw.list_available_channels()
hw.set_reference_channel("ni6432_0", "AI0")

hw.connect()
hw.move_absolute_height(20.0)
value = hw.read_reference_value()
hw.disconnect()
```

### Auto-position X/Y

```python
hw = AutoPositionXZHardware()
hw.list_available_channels()
hw.set_position_channels("ni6432_0", "AO0", "ni6432_0", "AO1")
hw.set_reference_channel("ni6432_0", "AI0")

hw.connect()
hw.move_absoluteX(0.48)
hw.move_absoluteY(0.77)
value = hw.read_reference_value()
hw.disconnect()
```

## Next Planned Work

Likely next steps:

- wire `AutofocusXZMain` into startup equipment list and `MainWindow`
- verify nested channel selector UX with real catalog updates
- bench-test long scans/autofocus in real hardware loop
- run full hardware bench validation (map, fit, offsets, Z scan)

## Update Rule

This file should be updated every time the design changes in a meaningful way.

At minimum, future updates should record:

- new public APIs
- changed workflow assumptions
- router usage changes
- hardware/protocol changes
- what is finished
- what is still pending
