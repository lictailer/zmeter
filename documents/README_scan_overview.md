# Scan Flow Overview (UI -> Settings -> Engine)

This note is the quickest path to understand how a scan starts, how level settings are built, and where to edit logic around `individual_level.ui` and `all_level.py`.

For execution-thread details, see [README_scan_logic.md](README_scan_logic.md).

## 1) Start Path From `scan.py`

Main entry points:
- `core/scan.py` -> `Scan.when_scan_clicked()`
- `core/scan.py` -> `Scan._start_scan_now()`

Current flow:
1. `when_scan_clicked()` decides whether to stop/restart an active scan or start immediately.
2. `_start_scan_now()`:
   - stops equipment for scan mode (`main_window.stop_equipments_for_scanning()`)
   - resets `ScanLogic` flags and sets `go_scan=True`
   - rebuilds all level `setting_array` values (`update_alllevel_setting_array()`)
   - passes `self.info` into `ScanLogic.initialize_scan_data(...)`
   - rebuilds plot widgets (`update_all_plots()`)
   - starts the scan thread (`self.logic.start()`)

Code pointers:
- `core/scan.py` -> `Scan.when_scan_clicked`
- `core/scan.py` -> `Scan._start_scan_now`
- `core/scan.py` -> `Scan.update_alllevel_setting_array`

## 2) How Level Settings Are Built

### UI layers and ownership

- `core/all_level.py` -> `AllLevelSetting`
  - owns all levels (`level0`, `level1`, ...)
  - manages add/delete level
  - emits merged `all_level_info`
- `core/all_level.py` -> `IndividualLevel`
  - owns one level block (setters/getters/manual set/method)
  - loaded from `core/ui/individual_level.ui`
- `core/individual_setter.py` -> `IndividualSetter`
  - owns one setter row (channel + linear/explicit destinations)
- `core/brakets.py` -> `Brakets`
  - converts `setting_method` + destinations to final `setting_array`

### Build/update sequence

1. `AllLevelSetting.update_all_setting_array()` calls each `IndividualLevel.update_setting_array()`.
2. `IndividualLevel.update_setting_array()` decides mode:
   - setting method enabled: use `setting_method_le.text()` with `personalized_input=True`
   - setting method disabled: clear method string and auto-generate sequence with `personalized_input=False`
3. `IndividualLevel.get_setting_array()` maps setters to letters `A/B/C/...` and builds destinations from:
   - explicit mode: `setter['destinations']`
   - linear mode: `setter['linear_setting']['destinations']`
4. `Brakets(...).output` becomes `level['setting_array']` (2D array, `NaN` means "do not set this setter at this column").

Code pointers:
- `core/all_level.py` -> `AllLevelSetting.update_all_setting_array`
- `core/all_level.py` -> `IndividualLevel.update_setting_array`
- `core/all_level.py` -> `IndividualLevel.get_setting_array`
- `core/brakets.py` -> `Brakets.__init__`
- `core/brakets.py` -> `Brakets._parse_plus_comma`
- `core/brakets.py` -> `Brakets._unpack`

## 3) `individual_level.ui` Fields That Drive Logic

Defined in `core/ui/individual_level.ui`:
- `setting_method_le` and `enable_setting_method_checkBox`
- `manual_set_before` and `manual_set_after`
- `settle_time_spinbox` (seconds)
- getter record area (`record_label`, `record_clean_pb`)
- setter add/delete buttons (`master_add_one_pb`, `master_delete_one_pb`)

Runtime binding lives in:
- `core/all_level.py` -> `IndividualLevel.__init__`

Important behavior:
- `setting_method` is consumed when `update_setting_array()` runs (for example at scan start), not on every keystroke.
- manual set now uses structured controls: one channel menu + value spinbox, then add to before/after list.
- settle time is per-level and applied once between write and read in that level loop.

Code pointers:
- `core/all_level.py` -> `IndividualLevel.when_add_manual_set_before_clicked`
- `core/all_level.py` -> `IndividualLevel.when_add_manual_set_after_clicked`
- `core/all_level.py` -> `IndividualLevel.when_remove_last_manual_set_before_clicked`
- `core/all_level.py` -> `IndividualLevel.when_remove_last_manual_set_after_clicked`
- `core/all_level.py` -> `IndividualLevel.when_clear_all_manual_set_clicked`
- `core/all_level.py` -> `IndividualLevel.when_settle_time_changed`

## 4) Getter/Setter Channel Selection

- Setter channel menu: `core/individual_setter.py` -> `IndividualSetter` + `core/nested_menu.py` -> `NestedMenu`
- Getter record menu: `core/all_level.py` -> `IndividualLevel.set_record_equipment_info`

Channel names are stored as full scan-channel strings (for example `nidaq_0_AO0`) and passed directly into `ScanLogic`.

## 5) Practical Edit Map

If you want to change:
- Level UI layout/text: `core/ui/individual_level.ui`
- Level behavior (method/manual set/getters): `core/all_level.py` (`IndividualLevel`)
- Add/remove level semantics: `core/all_level.py` (`AllLevelSetting`)
- Setter widgets (linear/explicit/channel chooser): `core/individual_setter.py`
- Method parser semantics (`+`, `,`, nesting behavior): `core/brakets.py`
- Scan run/start-stop orchestration: `core/scan.py`
- Scan thread execution: `core/scan_logic_new.py`
