# Scan Engine Contract

## Active path

`core/scan.py` imports `ScanLogic` directly from `core/scan_logic.py`. The active worker is `core.scan_logic.ScanLogic`; the retired `scan_logic_old.py` now lives in `archive/legacy-scan-engine/` and is not the active engine. Verify this import path before any scan-engine change.

## Scan dictionary

A scan uses these top-level fields:

| Field | Contract |
| --- | --- |
| `name` | Operator-visible scan name; used in output names |
| `levels` | Ordered `level0` through `levelN` mappings |
| `data` | Initially empty; during a run, a list of per-level NumPy arrays indexed by level; JSON lists when saved |
| `plots` | `line_plots` and `image_plots` mappings |
| `comments` | Free-form operator text; defaulted to `""` on load |
| `scan_log` | Timestamped run log list; defaulted to `[]` on load |
| `plots_per_page` | Persisted UI selection when present |

Each level contains:

| Field | Contract |
| --- | --- |
| `setters` | Ordered `setter0`, `setter1`, ... mappings |
| `setting_method` | Optional expression used to combine setter destination arrays |
| `getters` | Ordered direct or averaged getter tokens; `"none"` represents no direct measurement |
| `setting_array` | Two-dimensional array shaped `[setter, point]` |
| `settle_time` | Seconds after write and before read when direct getters exist; default `0.0` |
| `start_wait_time` | One-time seconds before the first non-skipped read in each invocation of that level loop; default `0.0` |
| `manual_set_before` / `manual_set_after` | Ordered lists of `{full_channel: value}` writes; default `[]` |
| `fixed_axis` | Present only on a fixed level (array axis): `{"channel", "axis", "name", "units"}`; see [Array getters](#array-getters) |

Each setter contains `channel`, `explicit`, `linear_setting`, `explicit_setting`, and `destinations`. Linear settings currently retain `start`, `end`, `step`, `mid`, `span`, `points`, and `destinations`. The UI derives the chosen `destinations` and rebuilds `setting_array` before plotting, starting, and saving.

## Level ordering and arrays

- `level0` is the innermost, fastest-changing level.
- The highest numbered level is the outermost, slowest-changing level.
- `ScanLogic.scan()` starts recursion at the highest level and calls the next lower level after the current level's direct read.
- Data arrays are shaped `[getter, outermost_points, ..., current_level_points]` and initialized with `NaN`.
- Progress counts every visited user-level point, including outer levels (fixed array levels are not counted; see [Array getters](#array-getters)), so the displayed total is the sum over levels of the product of the point counts of that level and all levels above it (an 11 x 11 scan shows 11·11 + 11 = 132 points). The time estimate is that total times the measured average time per point. `tests/test_scan_regression.py` checks that the count ends at the total.

`setting_method` is interpreted by `Brakets`. Without a personalized method, setter destination sequences form aligned rows with `NaN` padding. A `NaN` setter value means “do not write this setter at this point”; it does not remove the point from the loop.

If the same full channel appears more than once at a point, the first active setter in setter order wins. Later duplicates and `NaN` entries do not overwrite it.

## Point execution order

For each invocation of a level:

1. Execute `manual_set_before` in list order.
2. For each target index, check pause/stop.
3. Build the point payload, omit `NaN`, group by device, and write devices in parallel. Writes within one device remain in setter order. Shift Compensation groups run afterwards in their own phases: first `compensated_source_*`, then `compensated_target_*`, so a target correction sees the source value written at this point (see [shift_compensation.md](shift_compensation.md)).
4. Consume artificial-channel and global-range skip flags.
5. Apply `start_wait_time` once, before the first non-skipped read for this invocation.
6. Apply `settle_time` when the level has direct getters.
7. Read direct getters, grouped in parallel across devices and sequentially within a device. Compensated getters are read after the plain ones, because they read the same devices. A skipped point stores `NaN` instead.
8. Store direct values and emit a `phase="direct"` data update.
9. Recurse to the next lower level unless an artificial-channel rejection suppresses it. A split artificial pair across adjacent levels may still recurse so the lower write can complete the pair.
10. Compute and store averaged getters, then emit `phase="average"` when present.
11. Update indices, progress, remaining-time estimate, and hourly autosave trigger.
12. After all points, execute `manual_set_after` in list order and reset the level index.

Any write, read, or manual-action exception becomes a runtime error containing operation, level, indices, channel, optional value, and original cause. The scan stops through the worker's `finally` cleanup and reports the error to the UI.

## Getter forms

- A direct getter is a discovered full channel such as `<device_label>_<channel>`.
- `none` yields no read and keeps the placeholder result as `NaN`.
- An averaged getter has the exact token `level<source>_average_<full_channel>`. It is valid only at a higher current level and only when the source level contains that channel as a direct getter.
- Averaging uses `numpy.nanmean` over the completed lower-level slice. An unresolved or entirely `NaN` source produces `NaN`.

The UI removes stale averaged tokens when source getters change. Keep token parsing, menu construction, data shape, plot selection, save/load, and tests synchronized.

## Array getters

A getter declared in a device's `ARRAY_GETTERS` (see [device_contract.md](device_contract.md#array-getters)) returns a whole array per read, at most 2 axes (`core.array_getters.MAX_ARRAY_DIMS`; raising it needs plotting work only, the storage is generic).

- **Fixed levels.** Picking an array getter on the innermost user level inserts one locked level per array axis below it, and the user's levels move up. The last array axis becomes `level0` (a spectrum adds `level0` = pixel; an image adds `level0` = column and `level1` = row). A fixed level has the setter `none` with the axis values as destinations, a `fixed_axis` marker, the array getters on fixed `level0` only, and `["none"]` on the other fixed levels. In the UI it is greyed out except the getter menu and Clean.
- **Sync.** `core.array_levels.sync_fixed_levels` adds, keeps, rebuilds or removes fixed levels so they match the getters, and returns a level mapping used to renumber averaged-getter tokens and plot tokens (`levelN`, `LxSy_`, `LxGy_`). It runs when getters change, when a level is added or deleted, when a setting file is loaded or a queue item is built, and at scan start with `refresh=True` (axis values re-read). It does not run when the device catalog is republished. Removing the last array getter removes every fixed level. Array getters on outer user levels, or with a shape different from the first one, are dropped with a warning. A device that is offline keeps the saved fixed levels. A file that already holds data keeps its levels exactly as saved.
- **Engine.** `ScanLogic` validates that fixed levels are contiguous from `level0`, that fixed `level0` holds only direct getters and the other fixed levels none, and that at least one user level exists. When recursion reaches the lowest user level, `read_array_block()` makes one read per array getter, validates the shape (`ArrayShapeError` names the channel), stores the block into the fixed levels' data slices, and emits `phase="block"` with `fixed_levels`. The fixed levels themselves are not looped: no writes, waits or per-pixel progress. An artificial-channel skip leaves the block `NaN`.
- **Progress and time.** `total_points` counts user levels only, so a 21-point gate sweep recording a 1024-pixel spectrum counts 21 points; the time per point includes the exposure.
- **Averages.** `level0_average_<array>` on a user level averages the whole block (all fixed levels below) for each point of that level.
- **Plots.** A line plot on fixed `level0` (x `L0S0_none` for axis values or `level0` for the index) redraws the latest array; an image with x on a fixed level fills a row per user point, or a whole frame when y is also fixed.
- **Limits.** `channel_check.array_size_problems` refuses a scan whose stored values would exceed 100 million per getter.

## Parallel I/O and channel resolution

Channels are split using the registered equipment labels, not a fixed underscore count. Reads and writes use a `ThreadPoolExecutor` with one task per device. This permits different devices to operate concurrently but deliberately keeps commands for one device sequential.

Do not assume a vendor transport is thread-safe. If a device can also be used by monitoring or UI jobs, its registered lifecycle must prevent contention. Before the scan worker starts, `Scan` seals executable settings while leaving the scan name and comments editable, then captures the physical devices referenced by executable setters, getters, averaged-getter sources, and manual before/after writes. Completion snapshots use the latest name and comments entered by the operator. The bounded scan-boundary worker calls `stop_scan()` for that immutable participating set and initializes NumPy result arrays from a copied level model. Each driver owns its monitor-intent snapshot and marshals only Qt timer/widget changes to the owner thread; core does not perform a second generic `stop_monitor()` pass. An explicit `False` preparation result is failure. Only successful preparation returns to the GUI thread for plot setup and `ScanLogic.start()`; a failure calls idempotent `start_scan()` for the same captured set before releasing the runtime reservation. Plot-only and default channels do not participate; an artificial write expands to both configured physical backing devices, while an artificial getter alone does not.

## Limits and skipped points

`MainWindow.write_info()` rejects configured values outside `scan_range_limits.json`, does not call the setter, and marks the next scan read as skipped. When a scan starts, before device preparation, `Scan` logs one warning in its run log (and so in the saved `scan_log`) naming every physical channel the scan writes (level setters and manual before/after sets) that has no active scan limit, for example `[ScanRange] No scan limit for nidaq_0_AO0, nidaq_0_AO1; these writes are not range-checked.` `MainWindow.channels_without_scan_limit()` resolves labels with the same prefix rule as `write_info()` and skips `default_*`, artificial and Shift Compensation channels. It is a warning only; writes are unchanged. In v2 such a scan will refuse to start (ADR 003). Artificial-channel logic may also reject a transformed/ramped point. Rejected measurements are stored as `NaN`; the two skip flags are reset at scan start and cleanup.

Changing rejection or artificial-pair behavior requires focused tests for writes not performed, recursion choice, retained target/current state, `NaN` placement, force-stop propagation, and next-point recovery.

## Pause, stop, restart, and cleanup

- Pause blocks the scan worker only at explicit safe checkpoints; it does not undo completed hardware operations.
- Resume releases the wait condition.
- Stop sets the worker stop flag, releases pause, sets the scan stop marker, and calls `force_stop()` only for the captured participating devices.
- Pressing Scan during an active run requests stop, finalizes/saves that run, then starts a fresh run.
- The worker always resets skip/control flags and emits one terminal result, including after error or stop. It does not call device widgets. `Scan` then enters `finalizing` and restores the same captured participating devices on the scan-boundary worker; equipment restart remains an idempotent no-op after application-shutdown intent is reserved.
- Finish status is logged as completed, stopped/restarted, or error. Finalization is deferred one GUI event-loop turn so Qt-owned widget captures can be encoded as PNG bytes. PowerPoint, JSON, recovery, and backup I/O then consume that immutable snapshot off-thread before the serial advances.
- Application shutdown seals new work, stops or cancels the active scan boundary, waits for preparation/restore/output finalization (including JSON recovery fallback), and only then starts device teardown.

## Progress, logging, autosave, and output

The worker emits remaining/total time and finished/total points after completed points. `Scan` records each `sig_new_data` point and each progress string immediately, but draws plots and progress labels from one timer (`LIVE_REDRAW_INTERVAL_MS`, about 20 Hz), so fast scans cannot queue up redraws on the GUI thread. Plots on hidden pages wait until shown; `flush_live_display()` draws everything before plots are saved or captured at scan end. A line plot clears when its own sweep restarts at point 0, an image when the levels above it move on. `Scan` maintains a bounded display history and persists the current `scan_log`. Each elapsed whole-hour boundary triggers `autosave.json`, overwriting the previous autosave in the configured save directory. See [data_format.md](data_format.md) for output details.

## Compatibility and required tests

Internal scan code does not require legacy compatibility by default. Persisted scan dictionaries, output naming, plot tokens, and signal payloads are relied-upon interfaces: before breaking one, identify consumers and make an explicit migration decision.

At minimum, test changes to:

- level ordering, recursion, index/data shapes, and progress;
- setting-array construction, `NaN` writes, and duplicate-channel precedence;
- manual before/after ordering and timing semantics;
- direct/averaged getter resolution and all-`NaN` behavior;
- grouping and per-device ordering without real hardware;
- artificial/global range skips and adjacent artificial pairs;
- pause, resume, stop while paused, force stop, exception cleanup, and restart;
- signal payloads, plot updates, autosave, and JSON save/load round trips.

All agent-executed tests must be hardware-independent. Provide real-instrument procedures to the user; never execute them.
