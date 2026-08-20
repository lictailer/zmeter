# ZMeter Architecture

## Scope and authority

This document defines stable system relationships and ownership. See `project_structure.md` for the maintained directory/module inventory. Code and tests remain authoritative for exact runtime behavior.

## Boot and ownership flow

The checked-in startup path is:

```text
start_zmeter.py
  -> QApplication
  -> RuntimeServices (lazy VisaRuntime + KinesisRuntime)
  -> validated profile + reviewed lazy DriverRegistry
  -> DeviceManager
  -> MainWindow
       -> device discovery and command router
       -> ScanList
            -> Scan
                 -> ScanLogic
```

- `start_zmeter.py` is a thin entry point. It selects a profile path, validates it against the reviewed registry, creates one manager, and supplies profile paths plus the manager snapshot to `MainWindow`. It contains no device imports, addresses, serials, or channel lists. The checked-in default profile instantiates only disconnected mock devices.
- `DeviceManager` is the single owner of enabled device instances and ordered lifecycle records. Profile loading, runtime transaction acknowledgement, and final QWidget close/delete run on its UI-owner thread; slow runtime connect/disconnect/stop/terminate work runs on dedicated lifecycle workers. Startup load is transactional, and final shutdown aggregates failures without releasing shared runtimes under a device that failed to terminate.
- The startup/profile boundary owns one `RuntimeServices` provider. Enabled
  VISA devices receive `provider.visa`; K10CR1 and BBD30X receive
  `provider.kinesis`. Devices terminate before provider shutdown.
- Runtime construction is side-effect free. Dropdown-based VISA widgets
  schedule worker-thread discovery for the next Qt event-loop turn; this may
  create the shared manager but does not open a device session. Discovery has a
  10-second soft watchdog: timed-out results are ignored, while the worker and
  runtime remain retained until the vendor call actually returns. Kinesis
  validation, `clr`, DLL loading, and device connections remain explicit.
- `MainWindow` turns an ordered manager snapshot into one immutable `DeviceCatalogSnapshot`. Runtime changes use a manager-issued, single-use proposal: the UI first performs side-effect-free idle/reference preflight, lifecycle work then runs, and the exact committed generation is acknowledged synchronously before one informational publication. Callable maps, display choices, scan/manual menus, artificial-channel choices, active range-limit view, device buttons, and router catalog are reconciled as one UI-thread transaction. A consumer failure restores the preceding snapshot; a destructive change that cannot be acknowledged leaves calls and controls sealed until exact reconciliation succeeds.
- Catalog replacement is allowed only while scan and queue work, deferred output finalization, and queue UI completion are idle. References from executable available/queued/manual/active work, detached queue workers, artificial-channel mappings, and device-owned state block removal. Completed Past items and the available template remain diagnostic references but do not block; definitions are never silently rewritten.
- Runtime add/disconnect/remove is session-only and never edits the selected profile. Admission is serialized with scan, queue, manual, whole-router-request, individual device-call, and reviewed device-busy reservations. Per-record generations keep retained callables valid across unrelated changes while making handles to a removed and later re-added label stale. Only the mock registration is currently approved for runtime mutation.
- `ScanList` owns available, queued, manual, and completed items. Its worker runs queue items sequentially and exposes stop-now and stop-after-current behavior.
- `Scan` owns one scan editor/window, plot widgets, run log, persistence UI, and its `ScanLogic` worker.
- `ScanLogic` owns scan traversal, per-level data arrays, grouped scan I/O, timing, pause/stop checkpoints, progress, and autosave triggers.

## Application system log

The bottom of the Main Window contains a session-only System Log for concise
application-level startup, profile, catalog, runtime-device mutation,
scan-range-configuration, lifecycle, and shutdown events. Entries use local
timestamps plus `INFO`, `WARNING`, or `ERROR`, auto-scroll, and retain at most
500 in-memory lines. Enabled-device startup results are shown in profile order;
disabled devices appear only in the startup totals, and connection mappings or
raw startup exceptions are not exposed.

Device connection/operation details remain in device logs. Scan, queue,
manual-set, save/export, and ordinary artificial-channel activity remain in
their owning windows and are not duplicated into the System Log. Critical
dialogs remain for invalid profiles, refused device mutations, and unsafe
shutdown. Before a Main Window exists, or after it is unavailable, fatal
application diagnostics continue to use stderr as the fallback.

## Layer responsibilities

Device integrations are flat subpackages of `devices/`, imported as
`devices.<package>`, and normally use three layers:

- **Widget/main:** operator controls and display; translates UI events into logic calls and receives logic signals.
- **Logic:** scan-facing `get_*`/`set_*` API, operation coordination, signal emission, and worker-thread behavior where needed.
- **Hardware:** vendor/transport API calls, device-specific command translation, timeouts, and low-level cleanup.

Hardware I/O must stay out of core scan and UI code. Scan coordination belongs in logic. UI objects must not become a hidden device-to-device control bus.

Process-wide vendor ownership is the narrow exception: typed adapters live in
`core/shared_runtime/`, while device protocols and motion behavior remain in
device hardware layers. VISA and Kinesis do not import or share state with each
other.

## Thread boundaries

The Qt GUI thread owns widgets, screen capture, plot presentation, dialogs, GUI-driven save/export finalization, device construction, catalog commit acknowledgement, and final device-widget close/delete. Runtime connection and termination callbacks execute on lifecycle workers and report back only after those workers stop. `ScanLogic` is a `QThread`; it performs scan traversal and delegates per-device reads/writes to `ThreadPoolExecutor` workers. The queue also has a worker thread. Individual devices may provide their own worker threads for long operations. Application shutdown first closes call admission, then waits for direct/queued workers plus deferred GUI output finalizers, and finally performs asynchronous ordered device teardown before shared runtimes are released; its deadline is cooperative for a GUI callback already executing.

Do not block the GUI thread with device I/O, polling loops, ramps, or long waits. Cross-thread UI updates must use signals/slots. Device code must document thread ownership and serialize access if the transport is not safe for concurrent calls.

## Device discovery and command routing

`MainWindow` discovers callable methods on each registered device's `.logic` object:

- `get_<channel>()`: no positional arguments;
- `set_<channel>(value)`: exactly one positional argument;
- variadic signatures are rejected.

Startup-profile filters may reduce the exposed channels. Full scan channel names are `<device_label>_<channel>`; matching uses the exact registered label prefix, so labels may contain underscores.

Catalog snapshots are detached read-only views. Repeated publication must not retain a removed device's bound callables, duplicate buttons/actions/signals, or mutate an older snapshot. Unknown names in a profile allowlist continue to be silently skipped, but an already stored unknown channel still counts as a reference to its exact device label when removal is considered.

For cross-device operations, use the injected `DeviceCommandRouter`/`DeviceCommandClient`. The router publishes readable/writable catalogs and routes validated `read`, `write`, and `list_catalog` requests through `MainWindow`. One manager session lease spans catalog lookup, validation, device execution, and response construction, so a runtime mutation cannot split one request across generations. Device modules must not import or reach into one another directly.

## Scan and data flow

The scan editor constructs ordered level dictionaries and setting arrays. At start, `Scan` stops device monitoring/scan activity, initializes `ScanLogic`, configures plots, and starts the worker. The worker begins at the highest level, recurses toward `level0`, emits data updates to `Scan`, and triggers progress and hourly autosave signals.

`Scan` stores emitted arrays in the active scan dictionary and updates only affected plots when emission metadata is present. On finish or error, scan cleanup restarts equipment scan state unless shutdown has begun, then GUI-thread finalization exports PPT and JSON and advances the serial counter. A failed/canceled primary JSON save attempts a platform-local recovery JSON. See [scan_engine.md](scan_engine.md) and [data_format.md](data_format.md).

## Extension and coupling rules

- Add instruments as device packages behind the device contract; do not add vendor calls to `core/`.
- Keep addresses, serials, enabled-device lists, save/backup paths, and lab-specific limits at configuration/profile boundaries.
- Keep scan runtime independent of individual device imports; it addresses discovered channels through `MainWindow`.
- Use the shared router for cross-device reads/writes.
- Preserve lifecycle coherence across widget, logic, hardware, scan start/stop, force stop, and shutdown.
- Preserve scan ordering, signal payloads, persistence, and plotting consumers together when changing their contracts.
- Do not create a second scan engine or duplicate persistence path without an explicit decision and migration plan.

## Where to edit

| Change | Primary area | Required review |
| --- | --- | --- |
| Startup devices, labels, filters, or paths | selected file under `config/profiles/` plus a reviewed registry entry when needed | README, environment, safety |
| Launcher/profile-selection behavior | `start_zmeter.py` | profile validation and shutdown tests |
| App ownership, discovery, routing, shutdown | `core/mainWindow.py`, `core/device_command_router.py` | device contract, safety |
| Queue behavior | `core/scanlist.py` | scan lifecycle and shutdown |
| Scan UI, plots, save/load | `core/scan.py`, plot/level widgets | scan engine, data format |
| Traversal, timing, grouped I/O | `core/scan_logic.py` | scan tests and safety |
| Device behavior | target device widget/logic/hardware | device README and contract |
| Current module map/runtime path | `project_structure.md` | verify against code/tests |

