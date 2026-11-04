# Naming

This document records the naming used by new code and the staged schedule for
replacing old names. Decision record: [ADR 003](decisions/003-v2-architecture.md).
Code and tests remain authoritative for what the current application does.

## Terms

| Current name | New name | Meaning |
| --- | --- | --- |
| `setter` | control channel | Output channel written point by point in a level |
| `getter` | readout channel | Channel read at every point |
| `setting_array` | `sweep_values_array` | Sequence of values to write |
| `setting_method` | `sweep_method` | How several control channels are combined |
| `manual_set_before` / `manual_set_after` | `writes_before` / `writes_after` | One-off writes before / after a level |
| `settle_time` / `start_wait_time` | unchanged | Wait per point / wait before the first point |
| `equips` | `devices` | Device instances |
| `write_info` / `read_info` | `write_channel` / `read_channel` | Write / read one channel |
| artificial channel | virtual channel (umbrella term); "artificial channel" is kept | A virtual channel is any non-physical channel. An artificial channel is specifically the 2D coordinate-transform channel, one kind of virtual channel |
| `Brakets` | `SweepMethodParser` | Parses the `sweep_method` expression into combined write values (also fixes the spelling) |
| (new term) | parameter | One named value of a declarative device; see [ADR 004](decisions/004-declarative-device-sdk.md) |
| (new term) | readout parameter / control parameter | A parameter with `get` only / with `set`. Exposed as a readout channel / control channel when `scan=True` |
| (new term) | action | A panel-only device operation declared with `@action`; a `Trigger` is a control channel that runs one call |
| `scanlist` / `ScanList` | `queue_window` / `QueueWindow` | Scan queue window |

## General rules

- Modules and files use `snake_case` (`mainWindow.py` becomes `main_window.py`),
  classes use `PascalCase`, constants use `UPPER_CASE`.
- Physical quantities in plain variables carry a unit suffix: `wait_s`,
  `rate_v_per_s`, `current_a`. Parameters in device declarations use the `unit=`
  field instead, and the name itself has no unit.
- Booleans start with `is_`, `has_`, or `can_`. Device actions are verbs
  (`reset()`, `self_test()`).
- Channel ids stay `<device label>_<channel name>`, so queue files and analysis
  scripts are not affected.
- Everything committed to the repository is in English.

## Staged renaming

1. **Phase 0:** this document only. No identifier is renamed.
2. **From phase 1:** new code in `zcore`, `zui`, and `sim_device` uses only the new
   names. Old code keeps the old names.
3. **When a module moves into a new package:** its identifiers are renamed in the
   move. The old location keeps an alias, which is a transition interface in
   ADR 003 and is removed one stable tag after the move.
4. **UI labels** change when the corresponding window is reworked (main window in
   phase 2, scan window in phase 3). The old name is shown as a hint during the
   transition.
5. **Keys in scan files** (`setter0`, `getter0`, `setting_array`, ...) change
   last: in phase 4, together with `format_version: 3` (2 is already used by
   v1.0-beta.5 files; see ADR 003). Readers accept every older version, and
   the scan planner skill is updated at the same time. Old files stay
   readable.
