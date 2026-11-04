# Validation and Testing

## Hard boundary

Coding agents may run only checks confirmed to be hardware-independent. They must never execute commands that could discover, connect to, configure, home, ramp, move, source, trigger, read/write, disconnect, reset, or otherwise affect a real instrument. “Run the tests” is not authorization for hardware use. Hardware procedures are reviewed and executed by the user.
The only exception is the test-PC bench test in [hardware_safety.md](hardware_safety.md), which needs the user's per-session authorization.

Before every command, inspect its imports, fixtures, discovery, setup, environment variables, and startup path. Do not run a broad suite merely because its name says “test.” Use temporary output and keep all JSON, PPT, autosave, backups, screenshots, and caches away from lab data directories.

## Evidence levels

| Level | Examples | What a pass proves | What it does not prove |
| --- | --- | --- | --- |
| Static | `py_compile`, import inspection, UI XML parsing | Syntax/structure is acceptable to the selected tool/runtime | Runtime behavior, GUI behavior, drivers, or hardware |
| Hardware-independent | Unit tests for scan logic, schemas, helpers | Covered pure/core behavior matches assertions | Full GUI integration or physical instruments |
| Simulation/GUI | `mockDevice`, offscreen Qt widgets | Simulated lifecycle, signals, and integration work in that environment | Vendor stack, addresses, timing, limits, or real devices |
| Agent-executed bench (test PC, no sample) | Committed `tests/bench/bench_*.py` scripts run by an agent on the test PC under per-session user authorization | Only the specifically observed behavior of the allowlisted instruments with open or dummy-load outputs | Behavior under a sample, on the lab PC, or of other models; it never replaces the user-executed bench |
| Hardware bench | User-run connection/read/write/timeout/abort/shutdown | Only the specifically observed bench behavior | Other models, labs, ranges, or failure modes |

Always label evidence precisely. A lower level never implies a higher one.

## Bench tests

Bench tests live in `tests/bench/` and are named `bench_*.py`, so the standard `test_*.py` discovery never runs them. A skip gate also requires `ZMETER_BENCH=1` and an allowlist file outside the repository on the test PC. An agent may run them only under the conditions in [hardware_safety.md](hardware_safety.md) ("Agent bench tests on the test PC") and a per-session authorization from the user. `tests/bench/` and the gate do not exist yet; they are added with the first bench test.

## Environment

Use the maintained Windows Conda environment (`zmeter_Aug2026`, built from `zmeter_Sept2026_environment.yml`). A development or Linux environment for hardware-free tests can be built from `environment-dev.yml`; it does not replace the lab environment.

```powershell
conda activate zmeter_Aug2026
python --version
python -c "import sys; print(sys.executable)"
```

Expected Python is 3.12. Run commands from the repository root because UI paths are relative. Setting `QT_QPA_PLATFORM=offscreen` is appropriate for tests designed for offscreen Qt; do not assume every GUI workflow is valid offscreen.

## Canonical hardware-independent commands

### Changed Python compilation

```powershell
python -B -m py_compile <changed-file-1.py> <changed-file-2.py>
```

- Hardware: none, provided the named files do not execute side effects at import/compile time.
- Typical runtime: seconds.
- Writes: `-B` prevents bytecode; no intentional project output.
- Proves: Python syntax compiles under the active interpreter.

### Core regression tests

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
```

- Hardware: none after confirming the suite continues to use core stubs/mocks only.
- Typical runtime: seconds.
- Writes: no intentional lab data; Qt/platform caches may depend on environment.
- Proves: covered artificial-channel range/skip/ramp, scan-abort,
  force-stop, startup/profile, catalog, and manager/runtime-session behavior.

The core suite also includes offscreen catalog transaction tests. They exercise
repeated refresh, synthetic add/remove, reference refusal, consumer rollback,
device-button reconciliation, router publication, range-limit visibility, and
the available/queue/manual/past/template scan consumers without loading a real
driver.

### Layering test

```powershell
python -B -m unittest tests.test_layering -v
```

- Hardware: none; the test parses source files with `ast` and imports nothing.
- Proves (rule numbers as in the docstring of `tests/test_layering.py`): (1) `zcore/` does not import `PyQt6`, `core`, `devices`, or `zui`, including relative imports that leave the package and `import_module("...")` / `__import__("...")` strings; (2) `core/`, `zcore/` and `zui/` import no optional vendor library (`openai`, `cv2`, `pylablib`, `zhinst`, `skimage`, `PyDAQmx`, `nidaqmx`, `clr`, `sshtunnel`) at module top level; (3) `core/device_management/registry.py` does not import or name `devices` (the mock registration lives in `registrations.py` with every other driver); (4) `zui/` never imports `devices`, and only `zui/bridge/` imports `core`; (5) a device package in which any non-test file imports `zcore.devices` (a declarative device) imports nothing from `core`, `zui`, `PyQt6`, or another device package (its `tests/` directory is exempt). Synthetic sources check that each rule fails when violated.

### Declarative device SDK tests

```powershell
python -B -m unittest -v tests.test_zcore_device_declarations tests.test_zcore_device_examples tests.test_zcore_results
```

- Hardware: none; Qt-free, fake drivers only. No device package is imported; the example drivers copy the method names of the real hardware layers.
- Proves: every declaration and class-creation rule of `zcore.devices` ([ADR 004](decisions/004-declarative-device-sdk.md), decisions 2 and 3) rejects a violating declaration and accepts a valid one; `DeviceSpec` is built once, immutable, and follows Python attribute lookup for inherited, overridden and hidden declarations; SR860-, SR830-, K10CR1-, nidaq-, auto_focus- and attoDRY-like devices declare cleanly and expose the expected readout, control, array and snapshot names; `Result` constructors and statuses.
- Does not prove: anything about the Runner, threads, limits enforcement at write time, panels, or the bridge (see the Runner tests below and later phase 1 PRs).

### Device Runner and event bus tests

```powershell
python -B -m unittest -v tests.test_zcore_runner tests.test_zcore_events
```

- Hardware: none; Qt-free, fake drivers only. The fake driver blocks on purpose behind events (never on long sleeps) and fails the test if two driver calls ever overlap.
- Proves ([ADR 004](decisions/004-declarative-device-sdk.md), decision 5, Runner core): priority order stop > scan > panel > poll with a blocked worker and FIFO within a priority; a running call past its deadline returns `timeout`, marks "state unknown" without retrying, and its late result is logged and discarded; only a successful read clears "state unknown"; a queued call past its deadline never reaches the driver; driver exceptions become `failed` with context; out-of-limit, NaN, infinite, wrong-type and not-an-option writes from every source never call the driver; values are converted to the declared type; a ramped parameter is never written directly; calls from the Runner's own thread run inline; connect reads every readable parameter and logs `unlimited` parameters, connect failure and timeout give "error" and a late connect is undone; disconnect drops queued work; scan admission refuses panel writes, actions, reset and self-test; `set_many` is all-or-nothing and uses `write_many`; shutdown cancels pending work and is bounded; one value event per read or write and state events only on change; many submitting threads at once; the event bus isolates a failing subscriber and keeps per-publisher order.
- Does not prove: ramps, force stop, polling, safe values, the MultiParameter cache or `wait_stable` (phase 1, PR 5); anything with Qt, panels, the bridge, or a real driver. Before the PR the threaded tests were run 50 times in a row and 80 more times with eight copies in parallel on Linux.

### Registry and workbook expectations

```powershell
python -B -m unittest -v tests.test_device_registry tests.test_device_manager tests.test_phase1_device_registrations tests.test_phase2_device_registrations tests.test_device_config_workbook
```

- Hardware: none; the registry is built without importing any device, and the workbook is only read.
- `tests/registry_expectations.py` is the one place that lists every registered driver ID in registration order. Adding a driver means adding its ID to that file; no other test repeats the list. The registry tests still compare against it explicitly, so an unreviewed or missing registration fails.
- `tests/test_device_config_workbook.py` finds Devices rows by device id and reads the Guide's accepted driver IDs down to the first blank cell, so adding a row or a driver does not change row numbers in tests. It derives the table range and the config-check formula range from those extents. A new driver still needs its Guide row (and, if wanted, a Devices row) added in Excel, because editing the workbook with `openpyxl` drops the checkbox cells.

### Queue model and manual-item tests

```powershell
python -B -m unittest tests.test_queue_model -v
python -B -m unittest -v tests.test_manual_set_item tests.test_scan_queue_configuration_lock tests.test_scanlist_live_queue tests.test_scan_regression tests.test_scanlist_shutdown tests.test_scan_catalog_consumers tests.test_runtime_device_ui
```

These hardware-independent tests use deterministic barriers, fake setters, and
offscreen Qt. They cover stable IDs and state invariants, live pending
add/remove/reorder, the atomic final-add boundary, current-item locking,
preserved pending work after Stop, per-item manual-set thread affinity and GUI
responsiveness, sequential completion, and the single outer queue activity
lease. They must not import OptiCool or another vendor runtime, invent a device
timeout, or hard-terminate a `QThread`.

Phase 6 manager/UI coverage is available independently with:

```powershell
python -B -m unittest tests.test_device_manager_runtime_mutation -v
python -B -m unittest tests.test_runtime_device_ui -v
```

These suites use fakes and the in-process mock only. They cover generation-bound
call rejection, whole-router-request and scan/queue activity leases (including
queued manual work under the outer queue lease),
idle/busy refusal, session-only add/disconnect/remove, slow lifecycle worker UI
responsiveness and thread affinity, exact reference refusal, two-phase catalog
acknowledgement/reconciliation, cleanup quarantine and delete retry, injected
worker-dispatch failures, and asynchronous application teardown. They do not
load a vendor runtime or validate physical equipment.

### Core import test

```powershell
python -B -m unittest tests.test_core_imports -v
```

- Hardware: none; child interpreters import modules only (offscreen Qt), and no device is constructed.
- Proves: every module under `core/` imports in a fresh interpreter with `tkinter`, `python-pptx`, `PIL`, `pywin32` and the optional vendor libraries hidden, so the check also holds on a PC that has them installed (PowerPoint COM is imported only when a slide is appended); every module under `zcore/` imports with `PyQt6`, `core`, `devices` and `zui` hidden as well, and every module under `zui/` imports with `devices` hidden; `core/scan_info.py` holds only the `ScanInfo` template and loads neither Qt nor pyqtgraph; importing `core.all_plots` or `core.mainWindow` sets pyqtgraph's row-major image order.

### Scan-finished hook tests

```powershell
python -B -m unittest -v tests.test_scan_hooks tests.test_scan_boundaries tests.test_slack_notify
```

- Hardware: none; offscreen Qt, a fake main window and a fake or inactive Slack notifier (no network).
- Proves: hooks run in order and a failing hook is a warning while later hooks, device restore and the queue are unaffected; the plot screenshot is captured only when a hook wants it; nothing is emitted for a scan stopped for restart; the hooks run before the scan is marked finalized; the Slack hook reports status, points, queue run and screenshot as before and skips the notifier while Slack is off.

### Mock-device tests

```powershell
python -B -m unittest discover -s devices/mockDevice/tests -p "test_*.py" -v
```

- Hardware: none; `mockDevice` uses its in-process simulator and sets Qt offscreen.
- Typical runtime: seconds.
- Writes: no intentional measurement output.
- Proves: covered simulator, logic, widget, deterministic faults, range rejection, ramp stop, and lifecycle behavior.

The commands are canonical, but successful execution requires the maintained environment. A plain Python 3.12 interpreter missing PyQt6, NumPy, or other declared dependencies can fail during test import; that is an environment failure, not product evidence.

## Additional focused checks

The scalar scan and persistence contracts have dedicated hardware-independent
characterization suites:

```powershell
python -B -m unittest -v tests.test_scan_regression tests.test_scan_persistence tests.test_scan_file_info
```

`tests.test_scan_file_info` covers `format_version` and `software`: the
release-manifest, git (loose ref, `packed-refs`, detached HEAD, worktree) and
unknown cases from fake files, the stamp order, legacy files without the
fields, and refusal of a newer version. The persistence, boundary, setting-file
and queue-file suites check that each writer stamps its file.

They cover nested scalar shape/dtype/order, grouped reads and writes, averaged
getters, signal metadata, pause/resume/stop, queue order, the hourly autosave
trigger, empty and populated JSON round trips, `NaN` encoding, fields and level
ordering, comments/logs, collision naming, serial discovery, canonical
`autosave.json` replacement, disabled backup behavior, and intercepted
PowerPoint/COM/`Z:\` paths. All files are confined to an OS temporary directory.

The missing scan-limit warning has its own suite (fake catalogs, no device):

```powershell
python -B -m unittest -v tests.test_scan_limit_warning
```

It covers which written channels are listed (physical only, once each, in
order, with the `write_info` label rule), the skipped virtual and unknown
channels, that getters are not checked, the log line, and that a failing check
never blocks a scan start. `tests.test_scan_boundaries` checks that the line is
in the scan log before device preparation runs.

Array getters and the Andor port have their own offscreen suites:

```powershell
python -B -m unittest -v tests.test_array_getters tests.test_andor_device tests.test_scan_planner_skill
```

`test_array_getters` covers the `ARRAY_GETTERS` declaration, shape checks,
fixed-level sync (add, keep, rebuild, remove, offline device, renumbering of
averages and plot tokens), engine block reads with the mock `spectrum` and
`frame` getters (including a level average of a frame), the time-estimate point
count, the size limit, and the Scan window (pick, remove, plots, compact JSON
round trip). `test_andor_device` runs the Andor logic and widget against a fake
pylablib. `test_scan_planner_skill` checks the planner's fixed-level output by
loading it in a Scan window. The Andor bench checklist is in
`devices/andor/README.md`.

- Parse changed `.ui` files with a hardware-independent XML parser or load only the affected widget offscreen with simulated dependencies.
- For persistence changes, save to a temporary directory, reload, compare schema/data including `NaN`, verify duplicate naming, and test partial-write/failure reporting.
- For threading changes, use deterministic barriers/events and bounded waits; never rely on long sleeps or real transport timing.
- For optional-device imports, test in a process where the vendor dependency is absent and ensure unrelated mock-only startup remains usable.
- Prefer deterministic seeds for simulated noise/fault behavior.
- Shared-runtime tests must inject fake manager/load functions. They must not
  instantiate a real PyVISA manager, import `clr`, call `AddReference`, load a
  vendor DLL, or enumerate hardware. Run the shared-runtime, migrated VISA,
  K10CR1, BBD30X, and Four9 fake suites before broader core/mock regressions.

Phase 1 registry coverage is in `tests.test_phase1_device_registrations` and
`tests.test_ni6423_registration`. It verifies exact IDs and schemas, fresh-
process lazy imports, shared-runtime constructor mapping, official SR830 path,
startup-only policy, exact best-effort startup argument mapping, generic-address
translation for NI device names, forbidden NI task creation, and exact NI6423 dynamic
channels. `tests.test_best_effort_startup` covers ordered construction skipping,
all-failed empty sessions, startup-result states, one-shot/owner-thread rules,
pending-request teardown, launcher stage order, and the sanitized read-only
Main Window System Log. Its focused coverage verifies timestamp/severity
formatting, enabled-device order, disabled-device totals, identifier
sanitization, bottom-of-window placement, read-only/auto-scroll/500-line
presentation, message normalization, scan-range summary routing, and stderr
fallback before a Main Window exists. `tests.test_runtime_device_ui` also
checks one request/final result per runtime mutation and proves that a denied
scan write remains local to the Scan Range log. Run these before the family
fake suites.

Phase 2 registry coverage is in `tests.test_phase2_device_registrations`. It
verifies the four registered schemas/configuration defaults, fresh-process laziness,
Montana2 address mapping, asynchronous panel-worker connection paths,
lifecycle hooks, startup-only policy, and visible rejection of the remaining
deferred IDs. `tests.test_phase2_driver_behavior` intercepts every vendor/native
boundary while checking OptiCool lazy-load retry and TLPM first-resource,
failure, stop, join, and disconnect behavior. Run both with the existing Four9
fake suite; none of these selectors opens a laboratory connection or DLL.

## Documentation-only validation

For documentation consolidation or path changes:

- check every non-archive relative Markdown link and the active archive indexes;
- search active documents for retired filenames, stale package paths, superseded
  UI terms, and outdated readiness claims;
- compare `documents/device_status.md` with lazy registry metadata and the tracked
  workbook without constructing a device or importing a vendor package;
- inspect affected workbook rows and formulas without launching ZMeter;
- run the focused configuration/registry suites when registration or startup
  claims are edited; and
- run `git diff --check`, inspect the complete changed-file list, and confirm no
  unexpected generated artifacts, unreviewed workbooks, code, schema, or lab data entered the
  documentation change.

Archived implementation evidence is not required to retain working relative
links to its former location. Its archive index and all current replacement
links must remain valid.

## User-executed hardware tests

When hardware evidence is required, provide:

1. exact instrument model, interface, address/workbook, firmware/driver assumptions, and safe initial state;
2. exact command or GUI procedure;
3. permitted units, range, ramp rate, timeout, and abort action;
4. expected observations and pass/fail criteria;
5. cleanup/disconnect and final safe-state checks;
6. output/logs the user should return for review.

Label it **User-executed hardware test**. The agent must not run it, even after a general request to test or verify.

## Reporting

Record the exact command, interpreter/environment, result, evidence level, and any files created. For checks not run, give the concrete reason. Never report a skipped, blocked, or unrun check as passing.
