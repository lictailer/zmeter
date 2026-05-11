# ZMeter Project Summary For LLM Bootstrap

## 1. Project Purpose
`zmeter` is a PyQt6 desktop controller for multi-parameter instrument scans.

It combines:
- Instrument control (NI-DAQ, Keithley, lock-in, cryostat, etc.)
- Hierarchical scan definition (multi-level nested loops)
- Live plotting (line + image)
- Data persistence (JSON + optional PPT + backup/autosave)

Primary usage is experiment automation where each scan point sets one or more channels and reads one or more channels.

Quick scan docs for this repo:
- `documents/README_scan_overview.md` (UI/start flow + level-setting build path)
- `documents/README_scan_logic.md` (runtime engine behavior in `core/scan_logic_new.py`)
- `sr860/sr860_readme.md` (SR860 module behavior, monitor/logging flow, and known risks)

## 2. Entrypoint And Runtime Boot
Primary entrypoint: `start_zmeter.py`.

Boot sequence:
1. Create Qt app (`QApplication`) first.
2. Instantiate instrument widgets in `create_equipment()`.
3. Connect each instrument (`connect()` / `connect_visa()`).
4. Create `core.mainWindow.MainWindow(info=ScanInfo, save_path, backup_main_path, equips, equips_set_channels, equips_get_channels)`.
5. Show main window.

Current default instruments enabled in `start_zmeter.py`:
- `nidaq_0 = NIDAQ()`, connected to `"Dev1"`
- `Keithley_0 = Keithley24xx()`, connected to `"GPIB2::17::INSTR"`
- `Keithley_1 = Keithley24xx()`, connected to `"GPIB2::18::INSTR"`

Other imports are available but commented for optional setups.

## 3. Core Architecture
Top-level runtime stack:

`start_zmeter.py` -> `MainWindow` -> `ScanList` -> `Scan` -> `ScanLogic` -> `MainWindow.read_info/write_info` -> device logic methods.

Main components:
- `core/mainWindow.py`: global orchestrator and device registry.
- `core/device_command_router.py`: optional cross-device command router owned by `MainWindow`.
- `core/scanlist.py`: queue manager for multiple scan presets and manual actions.
- `core/scan.py`: per-scan configuration window + start/stop/pause/save + plots.
- `core/scan_logic_new.py`: threaded recursive scan engine.
- `core/all_level.py`, `core/individual_setter.py`, `core/brakets.py`: scan parameter construction.
- `core/all_plot_settings.py`, `core/all_plots.py`: plot definitions and rendering.
- `core/artificial_channel_logic.py`, `core/artificial_channel_2d_main.py`: virtual 2D coordinate transform channels.

## 4. Device Abstraction Pattern
Most devices follow a 3-layer pattern:
- `xxx_main.py`: QWidget UI wrapper.
- `xxx_logic.py`: QThread + get_/set_ methods + signals.
- `xxx_hardware.py`: low-level I/O (PyDAQmx, PyVISA, vendor libs).

Important integration contract used by scan engine:
- Device object must expose `.logic`.
- Scan-discoverable setters are methods named `set_<var>` in `.logic`.
- Scan-discoverable getters are methods named `get_<var>` in `.logic`.
- `MainWindow.make_variables_dictionary()` introspects `.logic` for these names.

Cross-device communication update:
- `MainWindow` now creates one shared `DeviceCommandRouter`.
- Devices are expected to receive injected `command_router` and `device_label` metadata from `MainWindow`, including nested `.logic` / `.hardware` layers when present.
- Preferred device-side usage is direct synchronous `command_router.route_command({...})`; `DeviceCommandClient` exists but is optional convenience only.
- See `documents/device_command_bus_guide.md` for the full design and integration pattern.

Shutdown contract expected by `MainWindow.closeEvent()`:
- `terminate_dev()`
- `close()`
- Optional `start_scan()`, `stop_scan()`, `force_stop()`

## 5. Channel Naming Rules
Scan channels are encoded as strings:
- `<equipment_label>_<variable>`
- Example: `nidaq_0_AO0`, `Keithley_0_current`, `default_wait`, `artificial_channel_n`

Routing logic:
- `MainWindow.write_info(value, master_channel)` finds equipment by prefix match `label_`.
- Variable name is suffix after `label_`.
- Calls setter function dictionary built from `.logic.set_*`.
- `MainWindow.read_info(slave_channel)` mirrors this for getters.

Scan-channel whitelist update:
- `start_zmeter.py` can now define optional `equips_set_channels` and `equips_get_channels` dictionaries keyed by equipment label (for example `ni6432_0`).
- If a label is present in these dictionaries, only the listed scan variables are exposed in the scan channel list.
- This filtering only affects scan discovery in `MainWindow`; it does not change the device GUI or remove methods from the logic object.
- If a label is omitted, all discovered `set_*` / `get_*` scan channels remain available.
- Unknown whitelist entries are silently skipped.

Special pseudo-devices:
- `default`: built-in wait/count setters.
- `artificial_channel`: virtual channels mapped to two original hardware channels.

## 6. Scan Configuration Data Model
Core schema object: `ScanInfo` (`core/scan_info.py`), copied and mutated in UI.

Top fields:
- `name`: scan name.
- `levels`: dict of `level0`, `level1`, ... (`level0` is innermost/fastest).
- `plots`: `line_plots` and `image_plots` config dicts.
- `data`: filled during/after scan.
- `plots_per_page`: layout mode string (`2x1`, `2x2`, `2x4`, `3x3`, `3x4`).

Per-level fields:
- `setters`: dict of `setter0`, `setter1`, ...
- `getters`: list of channel names.
- `setting_method`: expression string used by `Brakets` (for custom sequencing).
- `setting_array`: numpy array of final values per setter.
- `manual_set_before`: list of `{channel: value}` actions.
- `manual_set_after`: list of `{channel: value}` actions.

Per-setter fields:
- `channel`
- `explicit` (bool)
- `linear_setting` (`start/end/step/mid/span/points/destinations`)
- `explicit_setting` (list/array)
- `destinations` (active value list)

## 7. How Setting Arrays Are Built
UI path:
- `IndividualSetter` edits one setter.
- `IndividualLevel` combines setters and computes `setting_array`.
- `AllLevelSetting.update_all_setting_array()` runs before starting scan.

Algorithm:
- If `setting_method` enabled, `Brakets(cmd, destinations, personalized_input=True)` parses comma/plus expression.
- If disabled, `Brakets(..., personalized_input=False)` auto-generates sequential command.
- Output is a 2D numpy array where each row is one setter and columns are scan points; `NaN` means "skip set for that setter at that point".

## 8. Scan Execution Engine (`core/scan_logic_new.py`)
Class: `ScanLogic(QThread)`.

Preparation (`initialize_scan_data`):
- Reads level metadata into normalized arrays:
  - `level_target_arrays`
  - `level_setters`
  - `level_getters`
  - `level_data_arrays`
  - `level_manual_settings`
- Computes `total_points`.
- Initializes `current_target_indices`.

Execution (`looping(current_level)`):
1. Pause/stop gate check.
2. Execute `manual_set_before` for current level.
3. Group writing channels by device.
4. For each target index in current level:
5. Multi-thread write per device (`ThreadPoolExecutor`).
6. Multi-thread read per device.
7. Store results into N-D data array at tuple index derived from current indices.
8. Emit `sig_new_data([level_data_arrays, current_target_indices_copy])`.
9. Recurse into inner level (`current_level - 1`).
10. Update progress and remaining time signals.
11. Hourly auto-backup trigger signal.
12. Execute `manual_set_after`.
13. Reset level index.

Thread control:
- `request_pause()`, `request_resume()`, `request_stop()`.
- Pause uses `QMutex + QWaitCondition`.

Completion:
- `scan()` always calls cleanup in `finally`.
- Re-enables equipment via `main_window.start_equipments()`.
- Emits `sig_scan_finished`.

## 9. Queue Model (`core/scanlist.py`)
`ScanList` contains four draggable lists:
- Available scans (`list_available`)
- Queue (`list_queue`)
- Manual actions (`list_manual`)
- Past items (`list_past`)

Queue worker:
- `ScanListLogic(QThread)` executes items sequentially.
- Each item has `start_queue()`:
  - `ScanItem`: starts scan and blocks until scan thread ends.
  - `ManualSetItem`: parses `channel->value` pairs and writes directly.

## 10. Plot Model
Plot definition UI:
- `AllPlotSetting` defines:
  - Line plots: `x`, `y`
  - Image plots: `x`, `y`, `z`

Plot rendering:
- `AllPlots` owns one page of plots.
- Plots are paged by `plots_per_page`.
- `LinePlot` and `ImagePlot` consume `self.info['data']` updates in `Scan.new_data()`.

Coordinate string formats used in plots:
- `levelN` for level axes.
- `L<level>S<setter>_<channel>` for setter-based x.
- `L<level>G<getter>_<channel>` for getter-based y/z.

## 11. Save, Backup, And Autosave
`Scan.scan_finished()` does:
1. Save plots to PPT (`when_save_plots_clicked`).
2. Save scan JSON (`when_save_clicked`).
3. Increment serial counter.

Filename base:
- `<serial4>_<scan_name>` with de-dup suffix if needed.

Serial source:
- `MainWindow.update_serial_counter()` scans target folder for filenames beginning `####_`.

Backup behavior:
- Optional backup path supplied to `MainWindow`.
- JSON/PPT copy attempted when backup path exists.

Autosave:
- `ScanLogic` emits `sig_auto_backup(True)` every elapsed whole hour.
- `Scan.auto_backup()` writes `autosave.json` in save folder.

## 12. Artificial Channel System
Files:
- `core/artificial_channel_logic.py`
- `core/artificial_channel_2d_main.py`

Concept:
- Define two artificial channels (for example `n`, `E`) as affine transform of two original channels (for example `nidaq_0_AO0`, `nidaq_0_AO1`).
- Configured by three reference point pairs.
- Supports forward and inverse equations.
- Enforces original-channel limits.

Scan interaction:
- Scan write to artificial channel maps to original channels.
- If mapped original value exceeds limits, write can be skipped.
- Skip flag propagates to scan read stage (`consume_skip_read_for_scan`) to prevent invalid measurements.

## 13. Active And Legacy Scan Engines
Active engine:
- `core/scan_logic_new.py` (used by `core/scan.py`).

Legacy engine:
- `core/scan_logic.py` exists but is not used by current `Scan`.
- Contains older method names and behavior.

When modifying scan behavior, target `scan_logic_new.py`.

## 14. Instrument Modules In This Repository
Instrument directories generally include `<name>_main.py`, `<name>_logic.py`, `<name>_hardware.py`, and `.ui`.

Examples:
- `nidaq/`: NI-DAQ via PyDAQmx.
- `ni6432/`: NI USB-6432 via `nidaqmx`, with AO feedback, hardware-clocked AI integration, hardware-gated counter reads, dual integration times, and a dedicated PyQt UI/logic stack.
- `keithley24xx/`: Keithley 24xx via PyVISA.
- `sr860/`, `sr830/`: lock-ins via PyVISA.
- `montana2/`: cryostat controller via Montana libs.
- `hp34401a/`, `k10cr1/`, `tlpm/`, `opticool/`, `demoDevice/` etc.

Note:
- `ni6432` is no longer a placeholder. The implemented stack is:
  - `ni6423/ni6423_hardware.py`: `nidaqmx` hardware layer with `connect`, `disconnect`, AO write, hardware-clocked AI integration, and gated counter integration.
  - `ni6432/ni6432_logic.py`: scan-facing `set_AO*`, `get_AI*`, `get_counter*`, `get_AO*` methods, plus AO-feedback caching and separate AO/counter integration times.
  - `ni6432/ni6432_main.py`: GUI wrapper around `ni6432.ui` with AO controls, AO feedback readback, AI/counter live monitor modes, and scan pause/resume hooks.

## 15. Important File Map
- `start_zmeter.py`: app entry, instrument selection, connect addresses.
- `core/mainWindow.py`: global app window, device routing, close/shutdown.
- `documents/README_scan_overview.md`: scan entry and level-building overview.
- `documents/README_scan_logic.md`: detailed runtime notes for `ScanLogic`.
- `ni6432/ni6432_main.py`: NI USB-6432 widget/UI bindings.
- `ni6432/ni6432_logic.py`: NI USB-6432 scan-facing getters/setters and monitor logic.
- `ni6432/ni6432_hardware.py`: NI USB-6432 low-level `nidaqmx` operations.
- `core/scanlist.py`: scan queue UI + sequential worker.
- `core/scan.py`: scan editor, controls, save/load, per-page plots.
- `core/scan_logic_new.py`: recursive scan execution and progress.
- `core/all_level.py`: level editor and setting array generation.
- `core/individual_setter.py`: setter editor (linear/explicit).
- `core/brakets.py`: setting expression parser/expander.
- `core/all_plot_settings.py`: plot selection config UI.
- `core/all_plots.py`: plot widget construction and updates.
- `core/artificial_channel_logic.py`: affine virtual channel logic.
- `core/artificial_channel_2d_main.py`: artificial channel config UI.
- `core/append_to_ppt.py`: slide append helper (PowerPoint COM on Windows).
- `sr860/sr860_readme.md`: SR860 module guide + known risks for future sessions.

## 16. Environment And Platform Expectations
Target environment from `zmeter_Mar2026_environment.yml`:
- Python 3.12
- PyQt6, pyqtgraph, numpy, scipy
- PyVISA
- PyDAQmx
- python-pptx and pywin32-related usage in PPT path

OS assumptions:
- Primarily Windows (PowerPoint COM, NI drivers, VISA/GPIB setup).

Hardware/runtime dependencies not in pure Python:
- NI-DAQmx runtime and VISA stack installed system-wide.
- GPIB/USB adapter drivers.
- Vendor runtimes for some instruments.

## 17. Practical Mental Model For New LLM Sessions
Use this 3-step model:
1. `start_zmeter.py` decides which instruments exist and how they are addressed.
2. `MainWindow` introspects `.logic.get_* / set_*`, optionally filters them through `equips_set_channels` / `equips_get_channels`, exposes the remaining channels to scanning, and can also inject a shared command router into devices for cross-device control.
3. `ScanLogic` executes nested loops over `setting_array`, calling `write_info/read_info`, emitting live data to plots, and saving JSON/PPT on completion.

For the command-router path, use this rule:
- If a device needs to control another device, prefer injected `command_router.route_command({...})` over directly reaching into another module.
- For details, examples, and the current recommended pattern, see `documents/device_command_bus_guide.md`.

If asked to change scan behavior, usually edit:
- `core/scan_logic_new.py`
- `core/scan.py`
- `core/all_level.py` / `core/brakets.py`

If asked to add/modify device channels, usually edit:
- `<device>/<device>_logic.py` `get_* / set_*` methods
- `<device>/<device>_main.py` wrappers/connect lifecycle
- `<device>/<device>_hardware.py` low-level calls
- `start_zmeter.py` for instantiation, connection, and optional scan-channel whitelists.
