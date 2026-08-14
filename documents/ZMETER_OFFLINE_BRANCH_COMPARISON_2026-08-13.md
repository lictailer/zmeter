# ZMeter offline-version comparison and integration procedure

Date: 2026-08-13

## Integration status update

The current local integration work ports PEM100, SP150, and BBD30X into the `merge_offline_branches` checkout as optional device packages. A later local pass implemented independent shared VISA and Kinesis services under `core/shared_runtime/`. Maintained VISA devices now share manager ownership without sharing sessions; K10CR1 and BBD30X use one manifest-validated Kinesis 1.14.58.26351 directory. The changes remain local and unstaged for maintainer review; none of these devices is hardware-validated.

The maintainer clarified the remaining scope:

- `NI6432` was a misspelling of the already-present `NI6423`; do not add a second NI package.
- BBD30X is locally integrated for review; safety and lifecycle remediation is deferred.
- The PowerPoint fallback is intentionally ignored.
- Andor/Shamrock plus the required core array/spectrum work is the next integration phase.
- `start_zmeter.py` remains mock-only, but now constructs the two lazy runtime services, documents injection in disabled examples, and shuts the services down after device termination.
- Legacy `sr830/` remains unchanged and is excluded from shared-VISA profiles.
- Removed paths include migrated-device `ResourceManager` ownership,
  constructor enumeration, demoDevice's global PyVISA patch, K10CR1's
  import-time/machine-specific loader, BBD30X's search/PATH loader, and five
  package-local Kinesis DLL copies. Canonical local DLLs remain ignored.
- After user bench validation and one stable lab-use cycle, consider removing
  legacy `sr830/`, pruning unused K10CR1 bindings, and folding its remaining
  small lazy binding helper into the maintained adapter.

## Executive conclusion

Use `C:\Users\Taylo\Documents\GitHub\zmeter` at commit `3630d13` as the stable core baseline. Its working tree was clean when inspected.

Do not replace the baseline with any other folder. The current baseline already contains all committed Montana2 and nE-scan work, plus later scan-engine, mock-device, artificial-channel, test, and documentation changes. The genuinely absent work is concentrated in `zmeter_Mfork` and the untracked `BBD30X` package in `zmeter_tunneling`.

After the current PEM100/SP150 pass and the maintainer's scope decisions, the remaining candidates are:

1. Andor SDK2 camera and Shamrock spectrometer support.
2. Array-valued scan getters and spectrum-map plotting required by the Andor full-spectrum getter.
3. WinSpec remote-trigger and spectrum-file processing workflows.
4. Thorlabs BBD30X/DDS220 safety and lifecycle remediation after the minimal local port.
5. Several smaller scan-channel and lifecycle improvements for devices already present in main.

`start_zmeter.py` was excluded from all feature decisions as requested. Lab-specific addresses, serial numbers, save paths, enabled-device lists, and backup paths found there are not treated as reusable features.

## Scope and method

Folders compared:

| Role | Folder | Git state during inspection |
| --- | --- | --- |
| Baseline | `C:\Users\Taylo\Documents\GitHub\zmeter` | Clean `main` at `3630d13` |
| Offline version | `C:\Users\Taylo\Documents\GitHub\zmeter_Mfork` | Standalone snapshot; no `.git` directory |
| Offline version | `C:\Users\Taylo\Documents\GitHub\zmeter_montana2` | `scan_average_vale_update` at `bb63f6c`, with local edits |
| Offline version | `C:\Users\Taylo\Documents\GitHub\zmeter_nE_scan` | `scan_bug_fix` at `5a62cfc`, with local edits |
| Offline version | `C:\Users\Taylo\Documents\GitHub\zmeter_tunneling` | `scan_average_vale_update` at `bb63f6c`, with local edits and untracked files |

The baseline was on clean `main` when the comparison snapshot was taken. During final verification, a separate local checkout moved that same folder to branch `merge_offline_branches`; `HEAD`, `main`, and `origin/main` still all pointed to `3630d13`, and the tree remained clean. No compared content changed, so the conclusions are unaffected.

The comparison used Git ancestry, tracked working-tree diffs, relative file inventories, normalized text comparisons, and public class/function/channel inspection. The following noise was excluded or classified separately:

- `start_zmeter.py`;
- `.git`, `__pycache__`, and `.pyc` data;
- archived documentation and legacy measurement data;
- PowerPoint files, lock files, and unrelated scratch text;
- line-ending-only changes;
- machine-specific settings unless they expose a portability or safety problem.

During the original comparison, no instrument was discovered, connected, read, written, moved, homed, configured, or disconnected, and no source code was changed. The later PEM100/SP150 integration likewise used only static checks, fake transports, and offscreen GUI tests; hardware validation remains user-executed.

## Version-level result

| Version | Feature/device absent from main | Disposition |
| --- | --- | --- |
| `zmeter_Mfork` | Andor/Shamrock, array-valued scans, spectrum maps, PEM100, SP150, WinSpec remote, non-instrumental pseudo-device, PowerPoint fallback, and smaller device refinements | PEM100 and SP150 are ported as local review candidates. Preserve remaining evidence; do not port the NI misspelling or PowerPoint fallback and never replace current `core` wholesale. |
| `zmeter_tunneling` | Untracked `BBD30X` package | BBD30X is ported locally for review with lazy optional-driver loading and documented risks. Its unrelated NIDAQ and lab-local range edits remain excluded. |
| `zmeter_montana2` | No substantive missing feature | Do not port. Its committed history is already in main. Local edits are a counter display format already present in main and a lab-specific range file. |
| `zmeter_nE_scan` | No substantive missing feature | Do not port. Its committed history is already in main. Useful local default-channel and skip-reset ideas are already in main; its lower-level recursion change would regress current skip behavior. |

Git ancestry was decisive here: both `bb63f6c` and `5a62cfc` are ancestors of baseline `3630d13`. Consequently, ordinary differences between those old commits and main are newer-main changes, not missing branch features.

## Surveyed missing devices and major capabilities

### 1. Andor SDK2 camera and Shamrock spectrometer

Source candidate: `zmeter_Mfork\Andor`.

What it adds:

- camera and spectrometer enumeration and separate connections through `pylablib`;
- exposure-time and temperature control;
- cooler control, detector information, read modes, and single/accumulate/continuous/kinetic acquisition setup;
- snap, buffered-frame, start, and stop operations;
- Shamrock center-wavelength control and wavelength calibration;
- a PyQt6/pyqtgraph UI with live 1D/2D display and cursors;
- scan setters `temperature`, `exposure_time`, and `center_wavelength`;
- scan getters `temperature`, `exposure_time`, `center_wavelength`, `spectrum`, `spectrum_mean`, and `spectrum_sum`;
- `get_spectrum()` returns a `2 x N` array: wavelength or pixel coordinate in row 0 and intensity in row 1.

Dependencies and external requirements:

- `pylablib>=1.4.3`;
- Andor SDK2 and Shamrock drivers compatible with the installed Python/process architecture;
- NumPy, PyQt6, and pyqtgraph.

Integration changes and preserved risks:

- `pylablib` is imported at module import time; the optional device must not prevent unrelated ZMeter profiles from starting when the driver is absent.
- The folder contains two hardware implementations. `andor_hardware_new.py` is the intended compact `pylablib` backend; the large ctypes-based `andor_hardware.py` and hardware scripts should remain reference/diagnostic material, not a second production path.
- The UI itself labels kinetic and continuous modes as not working. Those modes need explicit simulation and user bench validation or must remain disabled.
- Temperature limits, exposure limits, acquisition timeouts, cooling shutdown/warm-up policy, and partial-failure cleanup are not documented to the current main contract.
- Full-spectrum support depends on the separate core work described next.
- Existing tests in the folder are hardware-driving scripts, not safe automated unit tests.

### 2. Array-valued scan getters and spectrum maps

Source candidates:

- `zmeter_Mfork\core\scan_logic_new.py` for object-valued result storage;
- `zmeter_Mfork\core\all_plots.py` for array detection and spectrum-map rendering;
- `zmeter_Mfork\core\scan.py` for serialization behavior.

What it adds:

- scan result buffers use `dtype=object`, allowing a point to hold either a scalar or an array;
- line plots detect 1D, `2 x N`, and `N x 2` array traces;
- array-valued Y data are rendered as an intensity map with spectrum coordinate on X and scan coordinate on Y;
- plot cursors report spectrum coordinate, scan coordinate, and intensity;
- loaded object-array data can reconstruct the spectrum map;
- image plots reduce an array-valued Z getter to a mean value;
- JSON save paths convert NumPy arrays to lists.

Why this cannot be copied directly:

- Main intentionally consolidated the active engine into `core\scan_logic.py`; `scan_logic_new.py` is not the current architecture.
- MFork's engine predates important main behavior, including the current average-getter model, per-level start wait, current error reporting, global scan limits, skip semantics, backup behavior, and newer signal payloads.
- Main's average-getter implementation assumes numeric scalar arrays. Applying `np.isnan`/`np.nanmean` to object cells containing spectra can fail or produce ambiguous results.
- Save/load, NaN handling, plots, auto-backup, and old JSON compatibility all need round-trip tests.

Correct disposition: port the measurement-value abstraction and plotting behavior into the current `core\scan_logic.py`, `core\all_plots.py`, and persistence path. Do not reactivate or wholesale merge `scan_logic_new.py`.

### 3. NI6423 naming correction

The maintainer confirmed that `NI6432` is a misspelling of `NI6423`, which already exists in main. The `zmeter_Mfork\ni6432` folder is therefore not a new integration target and must not be copied as a second device package. Any genuinely useful NI behavior must be reviewed later as a focused change to the existing `ni6423` package.

### 4. PEM100

Source candidate: `zmeter_Mfork\PEM`.

What it adds:

- VISA serial connection, defaulting to `ASRL4::INSTR`, 2400 baud, 8-N-1, with explicit terminations and 20-second timeout;
- scan-readable/settable wavelength and retardance;
- wavelength validation from 170 nm to 2500 nm;
- retardance validation from 0 to 0.5 lambda;
- PyQt6 UI for set/get and connection/error status.

Problems to fix before integration:

- The scan-facing methods automatically connect if disconnected. Prefer explicit lifecycle failure during a scan rather than surprise connection/discovery.
- The widget lacks standard `start_scan()`/`stop_scan()` hooks.
- Address, timeout, termination, and allowed ranges must be profile/device configuration, not assumed lab globals.
- A failed or interrupted acknowledgement read needs defined recovery and retry behavior.
- Add a device README and fake-VISA tests.

Local integration disposition: addressed in the new `pem100` package. It removes the default address and auto-connect behavior, adds full lifecycle methods and cooperative stop reporting, injects the VISA transport for tests, and documents the hardware protocol and user-executed bench procedure. Hardware validation remains pending.

### 5. SP150 monochromator

Source candidate: `zmeter_Mfork\sp150`.

What it adds:

- VISA/GPIB connection, defaulting to `GPIB1::11::INSTR`;
- scan setter/getter for wavelength;
- `0`-`3000 nm` hardware-layer validation;
- UI for setting and reading wavelength;
- a longer fixed wait when moving downward in wavelength.

Problems to fix before integration:

- The fixed 1-second/10-second sleeps are estimates, not a verified completion protocol, and cannot be interrupted cleanly.
- The scan methods auto-connect when disconnected.
- The widget lacks complete scan/force-stop lifecycle methods.
- Address, wavelength range, motion completion, timeout, grating behavior, and safe stop need device documentation and configuration.
- Add a fake-VISA transport and tests before using real GPIB hardware.

Local integration disposition: addressed in the new `sp150` package. It removes the default address and auto-connect behavior, replaces direction-based fixed sleeps with bounded cancellable readback polling, adds lifecycle methods and fake-VISA coverage, and documents configuration and the user-executed bench procedure. Hardware validation remains pending.

### 6. WinSpec remote acquisition

Source candidates:

- `zmeter_Mfork\winspec_remote` for the minimal trigger/done protocol;
- `zmeter_Mfork\winspec_remote_workshop` as experimental reference for file detection, plotting, and spectrum processing.

What it adds:

- writes a `trigger.txt` pulse on a shared directory and waits for `done.txt`;
- waits for a new numbered `.SPE` file, verifies that it is readable and its size is stable, and caches the last index;
- copies the acquired SPE file locally;
- converts image data to a WinSpec-style tab-separated text export;
- computes average intensity over a configured wavelength interval (currently 700-790 nm);
- workshop UI for one-shot/continuous acquisition, integration time, accumulations, and live spectrum display.

Problems to fix before integration:

- Network and local paths are hardcoded to `\\192.168.0.1\trigger` and `C:\Users\opticool\Documents\Mohamed\winspec_data`.
- The code creates and deletes coordination files in a shared directory. Define ownership, atomic file naming, stale-file handling, collision handling, permissions, and recovery so unrelated files cannot be removed.
- Poll loops can run up to ten minutes and use Qt waits without a standard cancellation/lifecycle contract.
- The workshop folder contains three competing UI versions. Consolidate one production widget rather than importing the workshop directory.
- SPE decoding depends on `imageio` support and an external wavelength template whose dimensions must be verified.
- Output copying/conversion is measurement persistence and needs temporary-directory tests, duplicate-name tests, and failure recovery.

### 7. Thorlabs BBD30X/DDS220 delay stage

Current disposition: locally integrated as a minimal-behavior optional package. The hardcoded `D:` path and import-time `pythonnet` dependency are removed, fake-driver tests and a device README are added, and startup-profile activation remains excluded. Safety and lifecycle remediation and hardware validation are pending.

Source candidate: `zmeter_tunneling\BBD30X`.

What it adds:

- Thorlabs Kinesis .NET control through `pythonnet`/`clr`;
- BBD30X device-list build, serial connection, channel 1 selection, DDS220 settings, polling, and device enable;
- home, absolute position, position readback, velocity, and acceleration control;
- scan setter `pos` in millimeters and getter `pos`; the UI displays micrometers;
- tolerance-based position verification after a blocking move;
- PyQt6 UI for serial, home, position, velocity, acceleration, and readback.

Problems to fix before integration:

- The machine-specific `D:` path is removed. Loading is deferred until explicit connection and searches an environment-configured directory, standard Kinesis installation, then a package-local directory.
- No Kinesis DLLs are included. The optional `pythonnet` package and a matching 64-bit vendor runtime are documented requirements, not additions to the maintained environment.
- `stop_scan()` and `start_scan()` are empty. `requestInterruption()` cannot cancel a blocking Kinesis `MoveTo()` or `Home()` call.
- The comments and actual Kinesis timeouts disagree, and there is another polling loop after the blocking move.
- No configured travel range is enforced in the package. Units cross micrometers in the UI and millimeters in logic/hardware.
- Discovery prints every BBD serial. Keep discovery behind explicit user connection and avoid logging unnecessary identifiers.
- Initialization may apply DDS220 file settings. This needs an explicit compatibility decision for the actual stage and must not occur accidentally.
- A device README and fake Kinesis injection/tests are added. A safe-state definition and tested partial-connect cleanup remain deferred.

### 8. Non-instrumental pseudo-device

Source candidate: `zmeter_Mfork\non_instrumental`.

It exposes `set_wait(seconds)` and `get_random()`. Main already provides built-in `default_wait`/`default_count` scan channels and has a maintained `mockDevice`, so this package adds no necessary capability. Do not port it as a production device. Preserve it only as historical evidence if desired.

## Other branch-only improvements worth reviewing

These are selective patch candidates, not reasons to copy whole files.

| Area | Branch-only behavior | Recommendation |
| --- | --- | --- |
| PowerPoint export | MFork guards the Windows COM import and falls back to `python-pptx`, including image fitting, titles, metadata, and comments. | High-value independent port. Add create/append/layout/error tests and verify both backends. |
| HP34401A | Scan-friendly aliases `get_nplc`, `set_nplc`, and `set_display_on`; guarded VISA resource refresh and package-relative UI path. | Port the deliberate channels and guarded refresh after defining valid NPLC/display values. `get_voltage` is only an alias for existing `get_dc_voltage`. |
| NIDAQ | Adds `AI7` and `get_count`, more defensive connection/UI checks, and package-relative UI loading. | Port `AI7` only if supported by the target device; choose one canonical counter channel name and preserve compatibility deliberately. |
| TLPM | Adds scan-settable wavelength, consistent read/emit behavior, and real disconnect behavior in `force_stop()`/`terminate_dev()`. | Port explicit wavelength control and cleanup; avoid implicit device discovery/connection from a scan getter. |
| K10CR1 | Adds bounded/stuck-aware home and move polling, wrap-aware target tolerance, constants, and cleaner polling teardown. | Review as a safety/stability port with a fake Kinesis layer. Do not copy without resolving its changed UI/thread job model. |
| Keithley24xx | Adds generic `set_voltage` and `set_current` aliases that switch source mode automatically. | Decide whether surprise mode switching is acceptable. If adopted, port only the aliases; MFork's ramp code has weaker force-stop cleanup than main. |
| Montana2 | Uses nonblocking signal chaining to read stability after temperature and adds busy guards/package-relative UI loading. | Consider the UI/lifecycle fixes only. Do not replace main logic's fail-fast assertions with silent `None` returns in scan getters. |
| Legacy `auto_focus` | Fixes broken widget-to-logic wiring, uses absolute Z targets, adds median/Gaussian filtering and edge cropping, closes figures, and exposes a scan autofocus action. | The algorithm is distinct but the maintained `autofocus_xuguo` package is more complete. Preserve useful preprocessing ideas; do not revive direct DAQ/serial coupling. |
| Legacy `auto_position` | Ports the UI to PyQt6, fixes relative imports/UI paths, uses configured channel arguments, adds median/Gaussian/crop preprocessing and optional absolute-value registration, and returns result metadata. | Treat as algorithm reference only; the maintained `autofocus_xuguo` router-based XY workflow supersedes its direct NI coupling. |
| OptiCool | Adds a legacy `set_SET_field_stable(*args)` alias intentionally hidden from current scan discovery. | No new feature. Do not port unless an old persisted scan file demonstrably requires migration support. |

## Local differences that should not be treated as reusable features

### `zmeter_montana2`

- Its `ni6423` counter display changes from five decimal places to one. Main already uses one decimal place.
- Its `scan_range_limits.json` changes device labels and adds lab-specific Keithley top/back-gate limits. These labels and limits belong in a named profile and require operator review; they are not a general default.
- Its committed core/device changes are already in main through ancestry.

### `zmeter_nE_scan`

- Local default wait/count channel registration and artificial skip-flag reset behavior are already implemented in current main.
- The local engine change always descends into lower levels even when an artificial write is skipped. Current main deliberately stores NaN and skips lower/faster levels; adopting the local edit would regress that behavior.
- `scan_logic_new.py`, scratch tests, bytecode, and old UI files should not be restored.

### `zmeter_tunneling`

- The NI6423 display edit is already in main.
- The custom range file is the same lab-specific configuration seen in `zmeter_montana2`.
- The NIDAQ edits remove references to a third/fourth AO control and allow zero integration time. Main's logic exposes two AOs; UI reconciliation is useful, but a literal zero integration time conflicts with sampling/count semantics and must not be copied without a defined meaning.
- `Dev3` in a standalone test block, the PPT/lock file, and scratch text are machine-local artifacts.
- `BBD30X` is the only substantive new device in this folder.

## Integration/fix procedure

### Phase 0: preserve and isolate

1. Make read-only archives of all five folders, including untracked files, before changing or deleting anything.
2. Start every integration change from baseline `3630d13` or a newer reviewed main commit.
3. Keep each selected device/capability reviewable. The current local work contains PEM100, SP150, and the minimal-behavior BBD30X port. PowerPoint fallback and the NI misspelling are excluded, BBD30X remediation is deferred, and array-valued results plus Andor/Shamrock remain the next feature phase.
4. Do not merge any offline `core` directory wholesale.
5. Keep lab addresses, serials, paths, enabled devices, global limits, and backup destinations outside shared core logic. Activation can later be done through an explicit lab profile; startup-file differences remain outside this comparison.

### Phase 1: add a device-adapter test boundary

Before porting a device, make its hardware transport injectable:

1. Widget constructs logic only; it must not enumerate or connect hardware.
2. Logic owns scan-facing coordination and accepts a hardware factory/adapter.
3. Hardware layer owns vendor I/O and validates device-local units/ranges.
4. Guard optional vendor imports so an unused device cannot break application startup.
5. Use package-relative UI paths.
6. Implement idempotent `connect`, `disconnect`, `start_scan`, `stop_scan`, `force_stop`, and `terminate_dev` behavior where applicable.
7. Define whether in-flight calls can be canceled. If a vendor API is blocking and non-cancelable, say so and prevent a false “stopped” state.
8. Add a device README with dependencies, channels, units, limits, lifecycle, failure recovery, and a user bench checklist.

### Phase 2: PowerPoint fallback (not selected)

The maintainer explicitly excluded this fallback from the current integration scope. The historical procedure below is retained only as reference.

1. Move the optional import/fallback selection from MFork into current `core\append_to_ppt.py` without replacing main's newer slide layout behavior.
2. Keep COM as the Windows live-update backend and `python-pptx` as a file-based fallback.
3. Preserve image aspect ratio and comments in both backends.
4. Test new-file creation, append to an existing file, duplicate filenames, read-only/locked output, cleanup of temporary PNGs, and behavior when neither backend is installed.
5. Render and inspect representative slides before accepting the change.

### Phase 3: port scalar devices independently

For PEM100 and SP150:

1. Copy only the device package into a feature branch.
2. Rename classes/files only where necessary for current conventions; avoid compatibility aliases without a real persisted consumer.
3. Remove embedded addresses and create explicit connection/config arguments.
4. Reconcile scan-discovered method signatures against the current device contract.
5. Document device-local limits and leave shared/profile range limits unchanged until a reviewed lab profile supplies stable labels.
6. Add fake-transport unit tests for every getter/setter, range error, timeout, disconnect, double-disconnect, scan stop, and partial connection.
7. Leave NI6423 unchanged; the apparent NI6432 target was a naming error, not a new device request.

### Phase 4: repair and port WinSpec remote

1. Select one production implementation. Use the workshop code only as reference for new-file detection and spectrum processing.
2. Put trigger directory, SPE directory, text directory, wavelength template, local cache, prefix, wavelength interval, and all timeouts in configuration.
3. Use uniquely named/atomic request and completion files or a documented lock protocol; never delete a file unless the request owns it.
4. Add a cancellation event checked by every poll loop.
5. Run acquisition/file waits off the Qt UI thread.
6. Validate SPE shape and wavelength-axis length before saving or averaging.
7. Test entirely with temporary local directories and a fake producer that creates partial, locked, delayed, malformed, duplicate, and successful files.

### Phase 5: complete BBD30X safety and lifecycle remediation

1. Preserve the completed removal of the hardcoded `D:` path and lazy loading from a configured, standard, or package-local Kinesis directory.
2. Do not ship vendor DLLs unless their license and versioning permit it; document the required Kinesis release and process bitness.
3. Separate device-manager discovery, controller connection, channel selection, settings application, polling, and enable into recoverable steps.
4. Make controller serial, channel number, stage model, position range, velocity range, acceleration range, home timeout, move timeout, and tolerance explicit configuration.
5. Use one unit at each API boundary and name it (`position_mm`, `display_um`).
6. Replace empty scan hooks with real monitor coordination. Implement stop/abort according to what Kinesis supports; do not claim cancellation if `MoveTo`/`Home` remains blocking.
7. Ensure a failed connection or move stops polling and disconnects partially created objects.
8. Add a fake Kinesis adapter covering connection failure, settings timeout, bounded move, out-of-range rejection, move timeout, stop, and disconnect.

### Phase 6: port array-valued measurement support

1. Define a supported measurement-value contract: finite scalar, NaN skip marker, or a numeric array trace with an optional explicit axis.
2. Prefer a small normalized representation over device-specific shape guesses. If existing `2 x N` arrays are retained, document accepted shapes and reject ambiguous arrays.
3. Adapt current `core\scan_logic.py` result storage. Preserve all current skip, stop, average, start-wait, range-limit, logging, backup, and signal behavior.
4. Make average getters scalar-only unless a specific reduction is configured. Reject selecting a full spectrum as an ordinary average source rather than letting object-array NumPy operations fail.
5. Update scalar line plots, spectrum maps, image plots, and loaded-data paths through shared normalization helpers.
6. Define behavior when spectrum length/axis changes mid-scan. Do not silently erase previous valid points.
7. Update JSON save/load and autosave/backup round trips. Decide how old files and non-finite values migrate.
8. Add hardware-independent tests for:
   - scalar-only scans remaining byte/schema compatible;
   - 1D, `2 x N`, and `N x 2` traces;
   - nested scans with spectra at inner and outer levels;
   - skipped/NaN spectrum points;
   - changing spectrum length or axis;
   - save/load/autosave/backup round trips;
   - scalar average getters and rejected array averages;
   - live and loaded spectrum-map rendering;
   - stop and exception cleanup.

### Phase 7: port Andor after the core supports arrays

1. Port `andor_main.py`, `andor_logic.py`, `andor.ui`, and a cleaned `andor_hardware_new.py` only.
2. Keep `pylablib` and SDK imports optional and lazy.
3. Expose only verified scan channels. Initially enable scalar `spectrum_mean`/`spectrum_sum`; enable full `spectrum` after array persistence and plotting tests pass.
4. Put camera/spectrometer indices, temperature limits, exposure limits, timeout, read mode, acquisition mode, ROI, and cooling shutdown policy in explicit configuration.
5. Ensure acquisition stop, scan stop, disconnect, and application shutdown leave buffers, shutter/cooler, camera, and spectrometer in a documented state.
6. Replace hardware-driving test scripts with fake-camera/fake-spectrometer unit and offscreen-GUI tests. Retain bench scripts outside automated discovery.

### Phase 8: selectively port existing-device refinements

1. Port small changes one device at a time with tests; do not use MFork files as replacements for newer main files.
2. Prioritize cleanup/lifecycle changes and bounded motion loops.
3. Add scan aliases only after choosing stable persisted channel names.
4. Do not port MFork's Keithley ramp implementation over main's stronger force-stop cleanup.
5. Reuse useful median/Gaussian/cropping ideas in `autofocus_xuguo` only if synthetic-map tests show an improvement; do not restore direct device coupling from the legacy autofocus packages.

### Phase 9: validation and release gates

Run the following levels in order:

1. **Static:** compile changed Python and validate all `.ui`, JSON, and dependency metadata without importing real drivers.
2. **Unit:** fake transports for VISA, NI-DAQmx, Kinesis, Andor/Shamrock, and WinSpec filesystem coordination.
3. **Mock/simulation:** current main scan tests plus scalar/array scan, nested scan, averaging, global-limit skip, abort, force-stop, persistence, backup, queue, and shutdown scenarios.
4. **Offscreen GUI:** construct each widget without vendor drivers or hardware; verify optional devices do not affect unrelated startup.
5. **Manual GUI:** operator reviews controls, units, limits, errors, busy state, and stop state using simulated transports.
6. **User-executed hardware test:** only after code review and simulation pass. Mechanically/electrically limit the setup; connect the explicitly named device; perform an identity/read-only check; command the current value first; make one smallest approved bounded change; verify readback; test stop/timeout behavior where safe; disconnect; and confirm the instrument and ZMeter are in the intended safe state. For BBD30X, verify travel, home direction, stage model, and units before any move. For NI outputs, verify wiring and restrictive voltage limits. For Andor, agree on shutter/cooler shutdown behavior before cooling or acquisition. For WinSpec, use a dedicated test share and disposable files.
7. Advance main and tag a stable release only after documentation and the user-executed bench record identify exactly which devices and modes passed.

## Recommended acceptance criteria

A candidate feature is ready to merge only when:

- importing/starting ZMeter without its vendor driver still works when the device is disabled;
- no hardware discovery or connection occurs during module import or widget construction;
- all scan-discovered channels have valid exact signatures, documented units, and deterministic scalar/array types;
- configured limits are enforced at both device and global boundaries with clear precedence;
- stop, failure, partial connection, disconnect, and shutdown behavior are coherent and tested with fakes;
- no machine-specific address, serial, DLL path, network path, or data path remains in shared logic;
- JSON/PPT/autosave/backup behavior is round-trip tested when affected;
- canonical structure/device/safety/environment documentation is updated;
- the precise device/mode has a recorded user-executed hardware result before being called hardware-validated.

## Final source-of-truth matrix

| Capability | Best source candidate | Main integration target |
| --- | --- | --- |
| Stable core | `zmeter` `3630d13` | Keep as base |
| Andor/Shamrock | `zmeter_Mfork\Andor` | New optional device package |
| Array result storage | MFork `scan_logic_new.py` as reference only | Current `core\scan_logic.py` |
| Spectrum maps | MFork `core\all_plots.py` | Current `core\all_plots.py` |
| NI6423 | Current `ni6423` package | Already present; do not add misspelled duplicate |
| PEM100 | `zmeter_Mfork\PEM` | Local `pem100` review candidate; hardware validation pending |
| SP150 | `zmeter_Mfork\sp150` | Local `sp150` review candidate; hardware validation pending |
| WinSpec remote | MFork minimal + workshop reference | One cleaned optional package |
| BBD30X | `zmeter_tunneling\BBD30X` | Local minimal-behavior review candidate; safety remediation and hardware validation pending |
| PowerPoint fallback | MFork `core\append_to_ppt.py` | Explicitly excluded from current integration |
| Autofocus/position | Current `autofocus_xuguo` | Preserve; selectively reuse preprocessing ideas |
| Montana2/nE-scan commits | Current main | Already integrated; no branch port |

## Confidence and limitations

Confidence is high for file presence, Git ancestry, public scan channels, and identification of unique source packages. Readiness and hardware correctness cannot be established by static comparison. `zmeter_Mfork` has no Git metadata, so exact authorship/commit ancestry is unavailable. Binary measurement/log artifacts were not interpreted as features. No hardware-facing import or test was run.
