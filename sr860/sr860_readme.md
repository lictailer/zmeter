# SR860 Module Readme

## Overview
This folder contains the SR860 lock-in amplifier integration for ZMeter.

It follows the standard 3-layer instrument pattern:
- `sr860_main.py`: PyQt widget/UI behavior.
- `sr860_logic.py`: QThread job dispatcher, scan-facing `get_*`/`set_*` methods, status/log signals.
- `sr860_hardware.py`: low-level SR860 SCPI over PyVISA.
- `sr860.ui`: UI layout (including the log panel).

## Current Behavior
- Connection is validated using `*IDN?`; the device is accepted only if the response contains `SR860` (case-insensitive).
- Live monitor is manual-start only:
  - `start graph` starts periodic `get_all`.
  - `stop graph` stops monitoring.
  - It does not auto-start after connect.
- A timestamped log window is shown in the UI (`log_textEdit`) for status/errors.

## Important Functions
- Connection lifecycle:
  - `SR860.connect_visa(...)`
  - `SR860.disconnect_device()`
  - `SR860.terminate_dev()`
- Monitor lifecycle:
  - `SR860.monitor()`
  - `SR860.stop_monitor()`
- Scan-facing methods (logic layer):
  - getters are `get_*` methods on `SR860_Logic`.
  - setters are `set_*` methods on `SR860_Logic`.

## Scan Integration Notes
- Scan start now calls `stop_monitor()` for devices that implement it, including SR860.
- This reduces concurrent polling/read contention when scan threads begin.

## Known Risks / Future Reference
These are not urgent blockers, but they are good to keep in mind for future maintenance.

1. `notch_filter` path is inconsistent:
- `sr860_logic.py` references `sig_notch_filter` and `setpoint_notch_filter`, but these are not currently defined in the signal/setpoint section.

2. Signal-input config may overwrite range unexpectedly:
- `set_signal_input_config()` writes both current range and voltage range every time.
- Both hardware paths use `IRNG`, so one write can override the other depending on mode.

3. Some UI update methods reference widgets that are not present in `sr860.ui`:
- Example names include `ref_input_checkBox`, `input_type_comboBox`, `input_mode_comboBox`.
- These methods are mostly latent unless triggered, but can fail if connected/used later.

4. Text mapping mismatch risk between UI and hardware enums:
- UI text and hardware-return text are not always the same form (for example case/wording differences), so `setCurrentText(...)` updates can silently fail.

5. Scan setter discoverability risk:
- The scan engine expects setter signatures like `set_x(value)`.
- Many SR860 logic setters are zero-arg setpoint-style methods, which may reduce scan exposure unless wrapped/adapted.

## Quick Start
1. Instantiate SR860 in `start_zmeter.py`.
2. Call `connect_visa("GPIB...")`.
3. Open SR860 UI, verify connection status/log.
4. Click `start graph` only when you want live polling.
