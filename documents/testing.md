# Validation and Testing

## Hard boundary

Coding agents may run only checks confirmed to be hardware-independent. They must never execute commands that could discover, connect to, configure, home, ramp, move, source, trigger, read/write, disconnect, reset, or otherwise affect a real instrument. “Run the tests” is not authorization for hardware use. Hardware procedures are reviewed and executed by the user.

Before every command, inspect its imports, fixtures, discovery, setup, environment variables, and startup path. Do not run a broad suite merely because its name says “test.” Use temporary output and keep all JSON, PPT, autosave, backups, screenshots, and caches away from lab data directories.

## Evidence levels

| Level | Examples | What a pass proves | What it does not prove |
| --- | --- | --- | --- |
| Static | `py_compile`, import inspection, UI XML parsing | Syntax/structure is acceptable to the selected tool/runtime | Runtime behavior, GUI behavior, drivers, or hardware |
| Hardware-independent | Unit tests for scan logic, schemas, helpers | Covered pure/core behavior matches assertions | Full GUI integration or physical instruments |
| Simulation/GUI | `mockDevice`, offscreen Qt widgets | Simulated lifecycle, signals, and integration work in that environment | Vendor stack, addresses, timing, limits, or real devices |
| Hardware bench | User-run connection/read/write/timeout/abort/shutdown | Only the specifically observed bench behavior | Other models, labs, ranges, or failure modes |

Always label evidence precisely. A lower level never implies a higher one.

## Environment

Use the maintained Windows Conda environment:

```powershell
conda activate zmeter_May2026
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

Phase 6 manager/UI coverage is available independently with:

```powershell
python -B -m unittest tests.test_device_manager_runtime_mutation -v
python -B -m unittest tests.test_runtime_device_ui -v
```

These suites use fakes and the in-process mock only. They cover generation-bound
call rejection, whole-router-request and scan/queue/manual activity leases,
idle/busy refusal, session-only add/disconnect/remove, slow lifecycle worker UI
responsiveness and thread affinity, exact reference refusal, two-phase catalog
acknowledgement/reconciliation, cleanup quarantine and delete retry, injected
worker-dispatch failures, and asynchronous application teardown. They do not
load a vendor runtime or validate physical equipment.

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
python -B -m unittest -v tests.test_scan_regression tests.test_scan_persistence
```

They cover nested scalar shape/dtype/order, grouped reads and writes, averaged
getters, signal metadata, pause/resume/stop, queue order, the hourly autosave
trigger, empty and populated JSON round trips, `NaN` encoding, fields and level
ordering, comments/logs, collision naming, serial discovery, canonical
`autosave.json` replacement, disabled backup behavior, and intercepted
PowerPoint/COM/`Z:\` paths. All files are confined to an OS temporary directory.

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
startup-only policy, exact best-effort startup argument mapping, NI
`device_name` validation, forbidden NI task creation, and exact NI6423 dynamic
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
verifies the four registered schemas/profile defaults, fresh-process laziness,
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
- compare `documents/device_status.md` with lazy registry metadata and tracked
  profiles without constructing a device or importing a vendor package;
- parse affected JSON examples and confirm tracked real-device templates remain
  disabled unless a separate behavior change was approved;
- run the focused configuration/registry suites when registration or startup
  claims are edited; and
- run `git diff --check`, inspect the complete changed-file list, and confirm no
  generated artifacts, local profiles, code, schema, or lab data entered the
  documentation change.

Archived implementation evidence is not required to retain working relative
links to its former location. Its archive index and all current replacement
links must remain valid.

## User-executed hardware tests

When hardware evidence is required, provide:

1. exact instrument model, interface, address/profile, firmware/driver assumptions, and safe initial state;
2. exact command or GUI procedure;
3. permitted units, range, ramp rate, timeout, and abort action;
4. expected observations and pass/fail criteria;
5. cleanup/disconnect and final safe-state checks;
6. output/logs the user should return for review.

Label it **User-executed hardware test**. The agent must not run it, even after a general request to test or verify.

## Reporting

Record the exact command, interpreter/environment, result, evidence level, and any files created. For checks not run, give the concrete reason. Never report a skipped, blocked, or unrun check as passing.
