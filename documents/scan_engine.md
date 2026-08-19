# Scan Engine Contract

## Active path

`core/scan.py` imports `ScanLogic` directly from `core/scan_logic.py`. The active worker is `core.scan_logic.ScanLogic`; `core/scan_logic_old.py` is not the active engine. Verify this import path before any scan-engine change.

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

Each setter contains `channel`, `explicit`, `linear_setting`, `explicit_setting`, and `destinations`. Linear settings currently retain `start`, `end`, `step`, `mid`, `span`, `points`, and `destinations`. The UI derives the chosen `destinations` and rebuilds `setting_array` before plotting, starting, and saving.

## Level ordering and arrays

- `level0` is the innermost, fastest-changing level.
- The highest numbered level is the outermost, slowest-changing level.
- `ScanLogic.scan()` starts recursion at the highest level and calls the next lower level after the current level's direct read.
- Data arrays are shaped `[getter, outermost_points, ..., current_level_points]` and initialized with `NaN`.
- The displayed total is the product of point counts for all levels. The current implementation increments completed points at every visited level point, including outer levels; for a multilevel scan the numerator can therefore differ from, or exceed, the coordinate-product denominator. Preserve or deliberately correct this behavior with focused progress tests.

`setting_method` is interpreted by `Brakets`. Without a personalized method, setter destination sequences form aligned rows with `NaN` padding. A `NaN` setter value means “do not write this setter at this point”; it does not remove the point from the loop.

If the same full channel appears more than once at a point, the first active setter in setter order wins. Later duplicates and `NaN` entries do not overwrite it.

## Point execution order

For each invocation of a level:

1. Execute `manual_set_before` in list order.
2. For each target index, check pause/stop.
3. Build the point payload, omit `NaN`, group by device, and write devices in parallel. Writes within one device remain in setter order.
4. Consume artificial-channel and global-range skip flags.
5. Apply `start_wait_time` once, before the first non-skipped read for this invocation.
6. Apply `settle_time` when the level has direct getters.
7. Read direct getters, grouped in parallel across devices and sequentially within a device. A skipped point stores `NaN` instead.
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

## Parallel I/O and channel resolution

Channels are split using the registered equipment labels, not a fixed underscore count. Reads and writes use a `ThreadPoolExecutor` with one task per device. This permits different devices to operate concurrently but deliberately keeps commands for one device sequential.

Do not assume a vendor transport is thread-safe. If a device can also be used by monitoring or UI jobs, its integration must prevent contention. `Scan` stops available monitors and calls equipment `stop_scan()` before the worker starts.

## Limits and skipped points

`MainWindow.write_info()` rejects configured values outside `scan_range_limits.json`, does not call the setter, and marks the next scan read as skipped. Artificial-channel logic may also reject a transformed/ramped point. Rejected measurements are stored as `NaN`; the two skip flags are reset at scan start and cleanup.

Changing rejection or artificial-pair behavior requires focused tests for writes not performed, recursion choice, retained target/current state, `NaN` placement, force-stop propagation, and next-point recovery.

## Pause, stop, restart, and cleanup

- Pause blocks the scan worker only at explicit safe checkpoints; it does not undo completed hardware operations.
- Resume releases the wait condition.
- Stop sets the worker stop flag, releases pause, sets the scan stop marker, and calls every equipment's `force_stop()`.
- Pressing Scan during an active run requests stop, finalizes/saves that run, then starts a fresh run.
- The worker always resets skip/control flags, calls `MainWindow.start_equipments()`, and emits `sig_scan_finished`, including after error or stop. Equipment restart is an idempotent no-op after application-shutdown intent is reserved.
- Finish status is logged as completed, stopped/restarted, or error. Finalization is deferred one GUI event-loop turn, exports PPT, writes JSON, and increments the serial.
- Application shutdown seals new work, stops the active scan, waits for output finalization (including JSON recovery fallback), and only then starts device teardown.

## Progress, logging, autosave, and output

The worker emits remaining/total time and finished/total points after completed points. `Scan` maintains a bounded display history and persists the current `scan_log`. Each elapsed whole-hour boundary triggers `autosave.json`, overwriting the previous autosave in the configured save directory. See [data_format.md](data_format.md) for output details.

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
