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

Each level stores ordered `setters`, `setting_method`, ordered `getters`, `setting_array`, `settle_time`, `start_wait_time`, `manual_set_before`, and `manual_set_after`. Each setter stores its full scan channel, explicit/linear selection, both setting descriptions, and selected destinations. See [scan_engine.md](scan_engine.md) for execution semantics.

Plot entries use string indices:

- line plot: `{ "x": <level-or-setter-token>, "y": <getter-token> }`;
- image plot: `{ "x": "levelN", "y": "levelN+1", "z": <getter-token> }`.

Selector tokens currently include `levelN`, `L<level>S<setter>_<channel>`, and `L<level>G<getter>_<channel-or-average-token>`. These are persisted interfaces, not merely display text.

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

Current compatibility is therefore limited: old files missing `comments`, `scan_log`, or `plots_per_page` are tolerated, but a general schema-version migration layer does not exist.

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

The configured backup path and the hard-coded `Z:\` availability gate must be reviewed together before lab use. Local JSON is the primary recovery artifact until copy success is confirmed.

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

Never write test artifacts into a laboratory data or backup folder. PPT/COM manual verification is not hardware operation but can alter a real log file; use a disposable presentation.
