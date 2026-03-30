# ScanLogic (`core/scan_logic_new.py`)

This file documents the active scan engine only: `core/scan_logic_new.py`.

For UI-to-engine setup flow (`Scan`, `AllLevelSetting`, `IndividualLevel`, `IndividualSetter`), see [README_scan_overview.md](README_scan_overview.md).

## Scope

Main class:
- `core/scan_logic_new.py` -> `ScanLogic(QtCore.QThread)`

Used by:
- `core/scan.py` -> `self.logic = ScanLogic(...)`

Primary entry path:
1. `Scan._start_scan_now()` calls `self.logic.initialize_scan_data(self.info)`
2. `Scan._start_scan_now()` starts thread via `self.logic.start()`
3. `ScanLogic.run()` checks `go_scan` and calls `scan()`
4. `scan()` calls `looping(self.max_level)` (recursive execution)

## 1) Initialization (`initialize_scan_data`)

`initialize_scan_data(scan_config)` normalizes the scan info into runtime arrays/lists:
- `self.level_target_arrays`: each level's `setting_array`
- `self.level_setters`: setter channel list per level
- `self.level_getters`: getter channel list per level
- `self.level_target_counts`: point count per level (`setting_array.shape[1]`)
- `self.level_getter_counts`: getter count per level
- `self.level_manual_settings`: `[manual_set_before, manual_set_after]` per level
- `self.level_settle_times`: per-level delay (seconds) between write and read
- `self.level_data_arrays`: preallocated `np.nan` arrays for results
- `self.current_target_indices`: current index at each level
- `self.total_points`: product of point counts across levels

Current behavior details:
- If a level has no getters, the code appends `"none"` to that level getter list.
- Data array shape for level `L` is:
  - `[num_getters_at_L, points(level_max), ..., points(level_L)]`

Related functions:
- `initialize_scan_data`
- `reset_flags`

## 2) Recursive Runtime (`looping`)

Core loop function:
- `looping(current_level)`

Execution order at each level:
1. Pause/stop gate (`_pause_gate`, `received_stop`)
2. Apply `manual_set_before` (`main_window.write_info`)
3. Build grouped channel maps:
   - `group_writing_device_channels(...)`
   - `group_reading_device_channels(...)`
4. For each target column:
   - write all setter channels (`multi_thread_write`)
   - wait `settle_time` once for this level (if configured and this level has readable channels)
   - read all getter channels (`multi_thread_read`)
     - if artificial-channel skip-read flag is set, fill getters with `NaN` via `build_nan_measurements`
   - store results in `self.level_data_arrays[...]`
   - emit `sig_new_data([level_data_arrays, current_target_indices_copy])`
   - recurse into inner level: `looping(current_level - 1)`
   - progress/time update (`update_remaining_time_estimate`)
   - hourly autosave trigger check (`check_auto_backup_trigger`)
5. Apply `manual_set_after`
6. Reset this level index to `0`

Notes:
- Base case is `current_level == -1`.
- Scan starts from `max_level` (outermost level) and recurses inward.

Related functions:
- `looping`
- `check_auto_backup_trigger`
- `update_remaining_time_estimate`

## 3) Device Grouping + Multi-Thread I/O

Helpers:
- `extract_device_from_channel(channel_name)`
- `group_writing_device_channels(level_index)`
- `group_reading_device_channels(level_index)`

Write path:
- `multi_thread_write(...)` builds `{device: {channel: value}}`
- uses `ThreadPoolExecutor(max_workers=num_devices)`
- each worker calls `write_single_device_all_channels(...)`

Read path:
- `multi_thread_read(...)` uses one worker per device
- each worker calls `read_single_device_all_channels(...)`
- merged into one dict keyed by full channel name

Artificial channels:
- Write: `artificial_channel_logic.set_channel_value(..., is_scan_write=True)`
- Read: `artificial_channel_logic.read_channel_value(...)`
- Skip-read support: `artificial_channel_logic.consume_skip_read_for_scan()`

## 4) Pause / Resume / Stop Control

Thread control API:
- `request_pause()`
- `request_resume()`
- `request_stop()`

Mechanism:
- `QMutex` + `QWaitCondition`
- `_pause_gate()` blocks while paused, wakes on resume/stop
- stop also clears pause and wakes blocked waiters

`scan.py` wiring:
- pause button -> `ScanLogic.request_pause`
- resume button -> `ScanLogic.request_resume`
- stop button -> `ScanLogic.request_stop`

## 5) Signals Used by GUI

Emitted by `ScanLogic`:
- `sig_new_data(object)` -> consumed by `Scan.new_data(...)`
- `sig_update_remaining_time(str)` -> `Scan.update_remaining_time_label(...)`
- `sig_update_remaining_points(str)` -> `Scan.update_remaining_points_label(...)`
- `sig_auto_backup(bool)` -> `Scan.auto_backup(...)`
- `sig_scan_finished()` -> `Scan.scan_finished(...)`

## 6) Cleanup Guarantees

`scan()` wraps execution in `try/finally`:
- always resets flags
- always clears artificial skip-read state
- always calls `main_window.start_equipments()`
- always emits `sig_scan_finished`

This means pause/stop/interruption still returns control back to GUI and device runtime.

## 7) Where To Edit What

- Change recursion order/data write indexing: `looping`
- Change progress/time computation: `update_remaining_time_estimate`
- Change pause semantics: `_pause_gate`, `request_*`
- Change read/write grouping: `extract_device_from_channel`, `group_*`, `multi_thread_*`
- Change autosave trigger cadence: `check_auto_backup_trigger`
