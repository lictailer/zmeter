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
- `DeviceManager` is the single owner of enabled device instances and ordered lifecycle records. Profile loading and final QWidget teardown run on its UI-owner thread; normal scan start/stop/force calls retain their existing worker ownership. Startup load is transactional, and final shutdown aggregates failures without releasing shared runtimes under a device that failed to terminate.
- The startup/profile boundary owns one `RuntimeServices` provider. Enabled
  VISA devices receive `provider.visa`; K10CR1 and BBD30X receive
  `provider.kinesis`. Devices terminate before provider shutdown.
- Runtime construction is side-effect free. Dropdown-based VISA widgets
  schedule worker-thread discovery for the next Qt event-loop turn; this may
  create the shared manager but does not open a device session. Kinesis
  validation, `clr`, DLL loading, and device connections remain explicit.
- `MainWindow` consumes the manager's initial ordered snapshot and currently owns discovered scan catalogs, global range configuration, artificial channels, the shared `DeviceCommandRouter`, and scan-quiescence coordination. Runtime catalog rebuilding is introduced in a later focused phase.
- `ScanList` owns available, queued, manual, and completed items. Its worker runs queue items sequentially and exposes stop-now and stop-after-current behavior.
- `Scan` owns one scan editor/window, plot widgets, run log, persistence UI, and its `ScanLogic` worker.
- `ScanLogic` owns scan traversal, per-level data arrays, grouped scan I/O, timing, pause/stop checkpoints, progress, and autosave triggers.

## Layer responsibilities

Device integrations normally use three layers:

- **Widget/main:** operator controls and display; translates UI events into logic calls and receives logic signals.
- **Logic:** scan-facing `get_*`/`set_*` API, operation coordination, signal emission, and worker-thread behavior where needed.
- **Hardware:** vendor/transport API calls, device-specific command translation, timeouts, and low-level cleanup.

Hardware I/O must stay out of core scan and UI code. Scan coordination belongs in logic. UI objects must not become a hidden device-to-device control bus.

Process-wide vendor ownership is the narrow exception: typed adapters live in
`core/shared_runtime/`, while device protocols and motion behavior remain in
device hardware layers. VISA and Kinesis do not import or share state with each
other.

## Thread boundaries

The Qt GUI thread owns widgets, screen capture, plot presentation, dialogs, GUI-driven save/export finalization, device construction, and final device-widget teardown. `ScanLogic` is a `QThread`; it performs scan traversal and delegates per-device reads/writes to `ThreadPoolExecutor` workers. The queue also has a worker thread. Individual devices may provide their own worker threads for long operations. Application shutdown seals new scan starts and waits for direct/queued workers plus deferred GUI output finalizers before device teardown; its deadline is cooperative for a GUI callback already executing.

Do not block the GUI thread with device I/O, polling loops, ramps, or long waits. Cross-thread UI updates must use signals/slots. Device code must document thread ownership and serialize access if the transport is not safe for concurrent calls.

## Device discovery and command routing

`MainWindow` discovers callable methods on each registered device's `.logic` object:

- `get_<channel>()`: no positional arguments;
- `set_<channel>(value)`: exactly one positional argument;
- variadic signatures are rejected.

Startup-profile filters may reduce the exposed channels. Full scan channel names are `<device_label>_<channel>`; matching uses the exact registered label prefix, so labels may contain underscores.

For cross-device operations, use the injected `DeviceCommandRouter`/`DeviceCommandClient`. The router publishes readable/writable catalogs and routes validated `read`, `write`, and `list_catalog` requests through `MainWindow`. Device modules must not import or reach into one another directly.

## Scan and data flow

The scan editor constructs ordered level dictionaries and setting arrays. At start, `Scan` stops device monitoring/scan activity, initializes `ScanLogic`, configures plots, and starts the worker. The worker begins at the highest level, recurses toward `level0`, emits data updates to `Scan`, and triggers progress and hourly autosave signals.

`Scan` stores emitted arrays in the active scan dictionary and updates only affected plots when emission metadata is present. On finish or error, scan cleanup restarts equipment scan state, then GUI-thread finalization exports PPT and JSON and advances the serial counter. See [scan_engine.md](scan_engine.md) and [data_format.md](data_format.md).

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

