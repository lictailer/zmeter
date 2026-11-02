# Data and Output Formats

## Scope

ZMeter persists the active scan dictionary as JSON, overwrites an hourly `autosave.json`, appends scan screenshots to a PowerPoint log, and may copy JSON/PPT output to a configured backup directory. These are high-risk measurement contracts; code is authoritative and any breaking change requires an explicit compatibility/migration decision.

## Scan JSON schema

The top-level fields are:

| Field | Type/meaning |
| --- | --- |
| `name` | String scan name |
| `levels` | Mapping of contiguous `level0` ... `levelN` objects |
| `data` | Initially empty; during/after a run, a list of acquired arrays indexed by level |
| `plots` | `{ "line_plots": {...}, "image_plots": {...} }` |
| `comments` | Operator text |
| `scan_log` | Ordered strings for the current run log |
| `plots_per_page` | Persisted UI selection, stored as text |
| `shift_compensation` | Output files only (since the Shift Compensation feature): the Shift Compensation record written at scan start; see below. Not part of the scan settings and ignored on load |

Each level stores ordered `setters`, `setting_method`, ordered `getters`, `setting_array`, `settle_time`, `start_wait_time`, `manual_set_before`, and `manual_set_after`. Each setter stores its full scan channel, explicit/linear selection, both setting descriptions, and selected destinations. See [scan_engine.md](scan_engine.md) for execution semantics.

Plot entries use string indices:

- line plot: `{ "x": <level-or-setter-token>, "y": <getter-token> }`;
- image plot: `{ "x": "levelN", "y": "levelN+1", "z": <getter-token> }`.

Selector tokens currently include `levelN`, `L<level>S<setter>_<channel>`, and `L<level>G<getter>_<channel-or-average-token>`. These are persisted interfaces, not merely display text.

## Shift Compensation record and files

Every scan output JSON written by a version with Shift Compensation carries a
`shift_compensation` object, taken at scan start and added to the output
snapshot only (the scan's `info` dictionary does not get it, so loading or
re-saving scan settings never carries a stale record):

```json
{
  "recorded_at": "2026-11-02T14:03:11",
  "scan": {"name": "qwp_map", "serial": "0071"},
  "channels": {
    "source": ["compensated_source_k10cr1_0_angle"],
    "target": ["compensated_target_ni6423_AO0", "compensated_target_ni6423_AO1"]
  },
  "readback_cache": "<rule text>",
  "active": [<mapping>, ...]
}
```

`active` is `[]` when no mapping was active. Each `<mapping>` is:

| Key | Meaning |
| --- | --- |
| `id`, `name`, `csv_name` | Mapping identity and the CSV file name it was loaded from |
| `points.source`, `points.shift` | The CSV columns (source value, amount added to the target) |
| `channels.source_set`, `source_read`, `target_set`, `target_read` | Full raw channel names |
| `model` | `cosine` or `polynomial` |
| `options` | `period`, `free_period`, `order` as chosen in the window |
| `fit` | `{model, options, params, rms, r2, n_points}`; cosine `params` are `A`, `P`, `C`, `D` of `A cos(2πx/P + C) + D`, polynomial `params.coefficients` are ascending powers |
| `x_ref` | Reference source value, or `null` for the first CSV source value |
| `active` | Active flag |

The window's **Save set...** file uses the same mapping objects:
`{"format": "zmeter.shift_compensation_set", "version": 1, "saved_at": ...,
"mappings": [...]}`, written atomically. Loading rejects another format or
version, keeps the saved Active flags and re-checks each against the current
catalog; a mapping that fails the checks loads inactive with a note.

Mapping CSVs (input only) have one optional header row and two numeric
columns: source value in source-readback units, and the amount to add to
the target in target-setter units. `skills/zmeter-shift-mapping/` writes
them; `tests/test_shift_mapping_skill.py` keeps the skill and the loader in
step.

## Array and `NaN` encoding

In memory, `setting_array` and acquired `data` contain NumPy arrays. JSON serialization converts arrays to nested lists. The current encoder can emit non-finite list values as Python JSON's unquoted `NaN` literal; this is accepted by Python's loader but is not strict JSON. Loading also recursively converts the exact legacy/external string `"NaN"` to `numpy.nan`.

Do not change array axis ordering or normalize the `NaN` representation without auditing plotting, scan initialization, downstream loaders, and existing measurement files. Moving to strict JSON requires an explicit compatibility decision. Tests must include partially filled arrays, skipped points, averaged getters, unquoted and string `NaN`, and nested round trips.

## Naming and serials

The normal base name is:

```text
<four-digit-serial>_<scan-name>
```

The serial initializes to one greater than the largest filename in the save directory matching `^\d{4}_`. A run chooses one unique base shared by JSON and PPT titles. If `<base>.json` exists, `_1`, `_2`, ... is appended. JSON save performs a second existence check before writing and also chooses a numeric suffix; it does not intentionally overwrite a normal measurement file.

Changing filename rules requires explicit review of operator workflow, backup organization, serial scanning, and external consumers.

## Save and load lifecycle

Before JSON save, ZMeter rebuilds setting arrays and synchronizes comments, `plots_per_page`, and `scan_log`. A configured save directory is created if absent; otherwise the operator receives a file dialog. Save success/failure and backup result are appended to the log.

If the primary JSON write fails, its directory/name preparation fails, or the
operator cancels the primary save dialog, ZMeter attempts an atomic copy of the
same scan dictionary under the platform-local application-data directory:
`ZMeter/recovery/recovery_<timestamp>_<original-name>.json`. Recovery names are
unique and retain the normal array/`NaN` encoding and schema. Recovery success
or failure is logged; failure of both paths does not add a retry state machine.

Load requires a JSON object. It defaults missing `comments` and `scan_log`, normalizes a non-list log to `[]`, rebuilds the level/plot widgets, rehydrates plot settings, and loads persisted data into line/image plots. Other missing structural fields are not generally migrated.

A file whose `data` is missing or empty loads as a scan setting: `data` becomes `{}`, the log reports `Loaded scan setting`, and the file is not treated as this scan's saved data file, so questionnaire answers are never written next to it.

Current compatibility is therefore limited: old files missing `comments`, `scan_log`, or `plots_per_page` are tolerated, but a general schema-version migration layer does not exist.

## Scan setting files

**Save setting** in the scan window (below **Load**) writes the current scan configuration without measurement data. The file uses the scan JSON schema above with `data` set to `{}` and `scan_log` set to `[]`. The previous run's `setup` snapshots are left out, and questionnaire answers are dropped; `questionnaire` is kept only as `{"enabled": true, "record": null}` when the questionnaire is switched on. The in-memory scan is not changed.

The save dialog opens in the data folder with `scan_setting_<scan-name>.json` as the default name. There is no serial, so setting files never affect serial discovery. The write is atomic (temporary file, then replace); overwriting an existing setting file is confirmed by the dialog. No backup copy, recovery JSON, or `.setup.json` sidecar is written, and a canceled dialog writes nothing.

Channels that are not in the current device catalog are kept in the loaded scan unchanged. The setter button shows `Unresolved: <channel>`, and Record getters and manual-set channels show `<channel> (unresolved)`. The marks clear when the device's channels are published. Loading also writes one warning block to the scan's log listing each unresolved use (`level0 setter A: SR860_0_X`, `level0 getter: ...`, `level1 manual set before: ...`; an average getter counts as resolved when its channel is a getter of the lower level). The block is display only and is not saved in `scan_log`. Starting a single scan with an unresolved channel is not blocked here; it fails during device preparation.

## Saved queues

**save queue** and **load queue** sit under the queue list in the scan list window. A saved queue is a folder:

```text
my_queue/
  queue.json
  01_gate_sweep.json
  03_field_sweep.json
```

Each scan in the queue becomes a scan setting file (the format above), so any one of them can also be opened with **Load** in a scan window. The number in a file name is the scan's position in the queue; characters that Windows does not allow in file names become `_`. `queue.json` holds the order. Manual sets are stored in it directly, since they have no settings of their own:

```json
{
    "format": "zmeter_queue",
    "version": 1,
    "items": [
        {"scan": "01_gate_sweep.json"},
        {"manual_set": {"channel": "nidaq_0_AO0", "value": 0.5}},
        {"scan": "03_field_sweep.json"}
    ]
}
```

Saving asks for the name of a new folder (default `queue_<YYYYMMDD_HHMM>` in the data folder) and never writes into an existing one. Files are written to a temporary folder that is renamed when complete, so a failed save leaves nothing behind. An empty queue, or a queue whose scan is preparing, running, or finalizing, is not saved.

Loading asks for a saved queue folder and adds its items, in saved order, after anything already in the queue. All cards are built before any is added, so a missing or malformed file adds nothing. `queue.json` is the only source of order; renaming the scan files does not reorder the queue, but the names in `queue.json` must match the files.

If the loaded items name channels missing from the current device catalog, a window lists each missing channel once as `Setter: <channel>` or `Getter: <channel>`, where it is used (`#<queue position> <scan name>, level0 setter A; #<position> manual set; ...`), and a menu of setter or getter channels to replace it with. **OK** replaces the chosen channels in the items being loaded only: setter channels, getters and their `levelN_average_<channel>` tokens, manual sets, and plot selections. Items already in the queue and the files on disk are not changed. Cancel, or leaving a row at "leave as is", keeps the channel; the queue loads either way. The queue log then lists the uses that are still unresolved, and each loaded scan's log shows its own block.

## Queue start check

Pressing start in the scan list first checks every pending item, without contacting any device: every channel is in the catalog (scans and manual sets), every level has a setter channel, and every level's setting array builds with at least one point. A level whose setters are all `none` fails the check: the scan engine skips `none` setters, so the level would step through its points setting nothing; use `default_count` or `default_wait` for a level that only repeats or waits. (`default_slack_notification` is also a built-in setter; it only sends a Slack ping.) Any problem is shown in a warning and written to the queue log by queue position, and the queue does not start. Limits are not checked here. The scan window's own **Scan** button is unchanged.

## Autosave

After each elapsed whole-hour boundary, `ScanLogic` signals the GUI to write `<save-directory>/autosave.json`. Autosave uses the same array/`NaN` encoding and synchronizes comments, `plots_per_page`, and log. It overwrites the previous `autosave.json` and does not currently copy it to the external backup path.

Treat autosave as a recovery snapshot, not proof that final PPT/JSON finalization completed.

## PowerPoint log

Normal finalization calls the primary PPT path before JSON save. The configured PPT file defaults to `data/log.pptx`. The primary export adds:

1. one overview slide containing the scan settings tab and main-window capture, title, timestamp, and comments;
2. one slide for each non-empty plot tab, containing a tab capture and timestamp.

The title uses the shared unique JSON base. Export relies on the Qt GUI and desktop PowerPoint through `core/append_to_ppt.py`/Windows COM. A PPT failure is logged; finalization then proceeds to JSON save. Do not infer one output's success from the other.

## Backup behavior

JSON and PPT save paths attempt a copy only when `Z:\` exists. They then read the live backup-path UI value, create it if non-empty, and copy with metadata using `shutil.copy2`. Missing drive/path and copy exceptions are logged without deleting the local artifact.

The configured backup path and the hard-coded `Z:\` availability gate must be reviewed together before lab use. Local JSON is the primary recovery artifact until copy success is confirmed. The retained gate and required future migration are tracked in [known_issues.md](known_issues.md).

## Compatibility policy

Do not retain internal dead paths merely for backward compatibility. Persisted measurement data, naming, plot selector tokens, PPT organization, autosave location, and external backup workflow are explicitly relied-upon interfaces. Before breaking one:

1. inventory existing files and downstream consumers;
2. state the operator/data impact;
3. choose and document migrate-on-load, conversion tooling, versioned schema, or intentional non-support;
4. preserve originals and make conversion recoverable;
5. add round-trip and representative legacy-fixture tests.

Historical compatibility is a deliberate decision, not an automatic requirement; silent corruption or ambiguous partial migration is never acceptable.

## Required validation for changes

- save/load round trip for an empty and populated scan;
- all top-level, level, setter, getter, plot, comment, and log fields;
- array shape/order and recursive `NaN` encoding;
- duplicate filenames and serial discovery;
- partial/failed JSON and PPT operations with clear logging;
- primary-save cancellation/failure, unique atomic recovery output, and recovery failure;
- hourly autosave overwrite in a temporary directory;
- backup unavailable, empty path, copy success, and copy failure using temporary/mocked paths;
- representative downstream loader and legacy files named in the migration decision.

Never write test artifacts into a laboratory data or backup folder. PPT/COM manual verification is not hardware operation but can alter a real log file; use a disposable presentation. Current integration-evidence limits are tracked in [known_issues.md](known_issues.md).
