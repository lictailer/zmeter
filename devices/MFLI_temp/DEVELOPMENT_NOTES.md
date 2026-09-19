# MFLI development notes

## Global amplitude/DC ramping — 2026-09-19

Updated on `MFLI_dev2.0`, starting at commit
`d42aca7245d08e9f0bfaf817067384fc8a70d6e1`. The pre-existing modified
`device_config.xlsx` was preserved without opening or changing it.

The four amplitude setters and output DC setter now share `_ramp_voltage` in the
maintained hardware layer. This makes panel, routed, standalone, and scan writes
use the same behavior without new public channels or a direct-set alternative.
The original experimental demos remain historical standalone examples. Phase
writes, channel signatures, sample acquisition, and measurement formats are unchanged.

Reference: `devices/keithley24xx/keithley24xx_logic.py::ramp_voltage_to` uses a
fixed voltage increment and interval, clamps the final point, and checks stop
requests. MFLI hardcodes `RAMP_RATE_V_PER_SECOND = 10.0` and
`RAMP_UPDATES_PER_SECOND = 100.0`. Each update waits 10 ms and advances at most
0.1 V; a fractional final step uses the exact target. API overhead slows the
nominal cadence, without catch-up bursts. The ramp reads its initial value from
the instrument and fails if that read fails; it never substitutes zero.

The final target is range-checked before any write; each step re-reads current
amplitudes, offset, and range before applying. Existing global scan target limits
remain in place. The worker's cancellation event interrupts waits, checks again
after settings reads and writes, and raises `InterruptedError` with the last
acknowledged value. Force-stop, scan preparation, disconnect, and shutdown use
this existing event. No reset, zeroing, rollback, or failed-write retry occurs.
Native API calls cannot be interrupted. After a partial ramp, refresh settings
to see the actual value. A successful setter returns the final acknowledgement.

Validation (selected `zmeter-v1.0-beta.1` Python, `QT_QPA_PLATFORM=offscreen`,
TEMP/TMP and compilation caches under ignored `.scratch`):

- `python -B -m unittest tests.test_mfli_ramping tests.test_mfli_integration -v`:
  **24 passed** (9 new ramp tests plus 15 integration tests).
- `python -B -m unittest discover -s devices/MFLI_temp/tests -p 'test_*.py' -v`:
  **60 passed**. Close-during-write tests now request a different amplitude,
  since setting the current value correctly performs no write.
- New tests cover all five channels, both directions/zero crossings, fixed waits
  and step bounds, fractional targets/acknowledgements, no-op values, direct phase,
  invalid targets/start reads, intermediate range changes, failed steps, shared
  panel/scan behavior, and interruption of an active native write by force-stop.
- `python -B -m py_compile devices/mfli/MFLI_hardware.py tests/test_mfli_ramping.py
  devices/MFLI_temp/tests/test_mfli_layers.py` and `git diff --check`: passed.

Final `git status --short --branch` (uncommitted; workbook modification pre-existed):

```text
## MFLI_dev2.0...origin/MFLI_dev2.0
 M device_config.xlsx
 M devices/MFLI_temp/DEVELOPMENT_NOTES.md
 M devices/MFLI_temp/README.md
 M devices/MFLI_temp/tests/test_mfli_layers.py
 M devices/mfli/MFLI_hardware.py
 M devices/mfli/README.md
 M project_structure.md
?? tests/test_mfli_ramping.py
```

All tests use guarded fake APIs. No packages were installed. Real ramp timing
and user-executed ramp acceptance remain pending; prior standalone hardware
success does not validate this new ramp behavior. See the maintained README's
ramp acceptance checklist. Full repository/workbook tests were not rerun for
this isolated hardware-layer change; the relevant MFLI suites passed.

## Address format simplification — 2026-09-16

The current workbook address contract is plain `DEV30037, 192.168.141.54` or
serial-only `DEV30037`. At the user's request, removed outer-bracket compatibility
from `devices/mfli/connection.py`; bracketed addresses now fail validation before
hardware access. Whitespace, case normalization, IP validation, and port 8004
remain unchanged. Updated parser tests, workbook expectations, and the maintained
README. This supersedes the optional-bracket behavior recorded below.

The user's workbook was read only, never modified. At inspection, its saved MFLI
row was row 8, still bracketed, with `connect_on_start=TRUE`; an unsaved Excel edit
may explain the difference from the requested new value. Save the plain-text
address before launch. Existing fixed-row workbook tests also assume the earlier
row 24 layout and manual connection; those expectations do not describe the
user's current saved workbook. No measurement schema, limits, threading, or
hardware-operation behavior changed.

Validation for the address change: `python -B -m unittest tests.test_mfli_integration -v` passed all 15 fake/offscreen tests. `python -B -m py_compile devices/mfli/connection.py tests/test_mfli_integration.py tests/test_device_config_workbook.py` passed. Workbook-dependent tests were not rerun because the saved workbook still differed from the intended format at inspection; a later hash check was blocked by an open-file lock. No real hardware was accessed. Branch remains `MFLI_dev2.0`; existing uncommitted changes are preserved.

## ZMeter integration — 2026-09-16

Implemented on the existing `MFLI_dev2.0` branch, starting at
`0e516ee2ae4de6f180909ddb8d20703f127a5121`. Preserved the pre-existing modified
`project_structure.md` and untracked development folder. No packages installed,
no hardware commands executed, and no commit created.

**Hardware evidence:** before this integration the user reported that the
standalone device worked as expected on the real instrument. This is a
user-reported standalone result, not an agent hardware test. Integrated ZMeter
scan, abort, and shutdown bench acceptance remains pending.

### Maintained ownership and configuration

- Hardware, logic, UI, and pure address/interface helpers now live in
  `devices/mfli/`; they do not import demos. `devices/MFLI_temp/MFLI_main.py`
  delegates to the maintained standalone UI and obtains bench defaults from the
  existing connection demo. The earlier demos and their tests are retained.
- Driver `mfli` is registered lazily and is startup-only. The optional startup
  callback queues the existing worker. Core imports happen only on connection,
  with a useful missing-dependency error in the panel.
- Address text accepts `DEV30037`, `DEV30037, 192.168.141.54`, or one outer bracket
  pair around those forms. Explicit IPs are validated with `ipaddress`; no eval.
  The no-IP host is `mf-dev30037`, port 8004. Invalid configuration is local to
  the panel; other devices and the main window can still load.
- Workbook row 24 is `mfli_0`, enabled TRUE, connect_on_start FALSE, address
  `[DEV30037, 192.168.141.54]`, blank filters. The Devices table now covers A1:H24;
  Guide D21:E21 explains MFLI, and all H2:H201 check formulas reference D4:D21.
  Existing rows, values, formatting, and reserved formula rows were preserved.
  Artifact Tool authored/rendered the update; a targeted OOXML transplant avoided
  its importer's normalization of pre-existing styles and blank formula rows.
  Read-only before/after comparison found no unexpected original-cell differences.
  Final Devices and Guide renders were visually checked in the ignored scratch folder.
- The actual current environment manifest is `zmeter_Aug2026_environment.yml`;
  added its pip pin `zhinst-core==26.7.1.4` and corrected stale May-environment
  links in the launch documentation. Existing selected environment remains
  `zmeter-v1.0-beta.1`: Python 3.12.12, PyQt6 6.9.1, pyqtgraph 0.13.7,
  NumPy 2.4.1, and Core 26.7.1.4. Toolkit/Utils are not needed.

### Scan, routing, and lifecycle decisions

The 9 setters / 16 getters, physical node mappings, units, range checks,
acknowledged values, and sample calculations are unchanged. Discovery, profile
filters, global limits, and measurement persistence use existing ZMeter code.
There is no scan grouping, acquisition cache, or persistence/schema change.

The manager calls `stop_scan()` before the scan and `start_scan()` afterwards.
Preparation gates manual panel/routed jobs immediately, stops monitoring, cancels
pending panel work, and queues a barrier before scan jobs. Active native calls
finish first. Completion restores monitoring only if requested before scanning
and the client is healthy. `force_stop()` cancels cooperative waits/queued work;
it never resets outputs. GUI scan preparation is nonblocking.

All API calls stay on one worker. Lifecycle and busy/connected probes use locked
worker state, independent of delayed Qt signals. The manager busy probe excludes
passive monitoring: shutdown is allowed to cancel and drain a monitor read; actual
control work remains busy. Manager waits are 10 seconds. A late timed-out
connection closes its client instead of becoming connected. Failed cleanup
retains the client/worker and propagates to the manager. Blocking native calls
can outlast the wait budget; no thread is force-killed.

Managed panel close hides it; standalone close and final manager termination
perform client-only cleanup. Applied settings remain applied. Existing manager
leases can refuse shutdown during active routed or scan calls; these must drain
or be aborted before retrying. Manager teardown errors remain visible and retain
resources rather than claiming successful disposal.

The existing router signal slot normally executes on the GUI thread. MFLI opts
into background routing to preserve its synchronous scalar API without blocking
Qt. A manager session lease is acquired before dispatch and held until completion.
The router enters the logic's thread-local manual-request scope, so delayed routed
commands cannot bypass the scan gate. Other drivers keep their previous routing.

### Validation

All execution used fake APIs / offscreen Qt. Tests forbid Zurich imports at the
hardware boundary. Logs, workbook backups/renders, and compilation caches are
under ignored `devices/MFLI_temp/.scratch`, never in measurement folders.

Commands run with the selected environment's explicit Python executable, `-B`,
`QT_QPA_PLATFORM=offscreen`, and TEMP/TMP pointing into `.scratch`:

```text
python -B -m unittest tests.test_mfli_integration -v
python -B -m unittest discover -s devices/MFLI_temp/tests -p "test_*.py" -v
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m py_compile <all changed Python files>
```

Integration: **15 passed**, covering address/lazy/missing-dependency behavior,
25-channel discovery, filtering, global limits, scalar scan I/O and failures,
signal routing, scan gating/barriers, cancellation, monitor restoration, reconnect,
hide/reopen, async startup, late connections, blocked native calls, failed cleanup,
manager failure reporting, and responsive application shutdown during monitoring.
Existing device/demo regressions: **60 passed**. Compilation passed.

The older workbook test
`test_checked_in_workbook_keeps_reviewed_device_values` already failed before this
update: it expects every old address formatted as Text, the first real instrument
enabled/auto-connected, and a Boolean validation range that the actual workbook
does not have. The current workbook instead keeps those real-device flags FALSE.
Those unrelated values/styles were preserved rather than changed to satisfy the
stale test. The new MFLI row, guide recognition, table coverage, and configuration
load checks pass. Final repository suite: **341 tests, 340 passed and this one
pre-existing failure** (37.085 seconds). The 15 integration tests are included
in that count; the 60 device/demo regressions are a separate suite. Both the
maintained and old direct-file entry points were imported under the vendor guard.
`git diff --check` passed. No hardware acceptance was executed by the agent.

Current operator contract and integrated bench checklist:
[maintained MFLI README](../mfli/README.md). The remaining sections are historical
development records; references to files in this folder describe their pre-promotion
locations unless explicitly stated otherwise.

### Final working-tree status

No changes were committed. The pre-existing development work remains present.

```text
## MFLI_dev2.0
 M README.md
 M core/device_command_router.py
 M core/device_management/registrations.py
 M core/device_management/registry.py
 M device_config.xlsx
 M documents/device_status.md
 M documents/environment_windows.md
 M project_structure.md
 M tests/test_device_config_workbook.py
 M tests/test_device_manager.py
 M tests/test_device_registry.py
 M tests/test_phase1_device_registrations.py
 M tests/test_phase2_device_registrations.py
 M zmeter_Aug2026_environment.yml
?? devices/MFLI_temp/
?? devices/mfli/
?? tests/test_mfli_integration.py
```

## Standalone three-layer device — 2026-09-16

Implemented on `MFLI_dev2.0`, based on working-tree HEAD
`0e516ee2ae4de6f180909ddb8d20703f127a5121`. The existing modified structure document
and untracked MFLI demos were preserved. This section records the current device;
the later sections retain the earlier demo-stage history and validation.

### Files and ownership

- `MFLI_hardware.py`: lazy Core client construction, existing connection-helper
  reuse, read-only identity/settings snapshot, permitted node writes, current
  range validation, sample parsing/freshness, and client-only cleanup. Frozen
  records define tone settings, settings snapshots, demodulator samples, and
  monitor batches. Construction has no I/O.
- `MFLI_logic.py`: explicit nine scalar setters and sixteen getters, one worker
  with a bounded FIFO, Future results for non-GUI callers, Qt completion/log
  signals, and per-channel error/recovery deduplication. All API calls, including
  client construction and disconnect, execute on the same worker.
- `MFLI_main.py`: directly runnable programmatic PyQt6 layout; four tone rows,
  DC offset, acknowledged readbacks, read-only mapping/frequency, four independently
  configurable pyqtgraph plots, and a resizable 500-entry log. No dependency on
  ZMeter startup, device registry, runtime services, or workbook loading.
- `tests/test_mfli_layers.py`: strict fake API and offscreen Qt coverage. The fake
  permits only the nine intended writable nodes; tests forbid vendor imports.
  Existing demos and their tests remain unchanged.

The API/interface selection is shared with `connection_demo.py`; the GUI uses its
existing bench defaults without duplicating addresses in the hardware or logic.
Imports are explicit for both direct-file execution and package imports.

### Locked decisions and behavior

- User selected LabOne-owned acquisition setup, `get_` getter names, explicit
  individual Set buttons, fixed tone/demodulator rows, and initial demodulator-1
  X/Y/R/theta plots. No frequency/routing/rate/enable/filter setters were added.
- Channels are one-based publicly, zero-based in nodes. OSCx means the tone
  associated with demodulator x, regardless of its current oscillator assignment.
  Amplitudes are signed peak volts; phase is -180..180 degrees; output DC uses V.
- R/theta derive from the same X/Y sample. Theta at zero magnitude is NaN. V/A
  units follow voltage/current input selection; other sources say native units.
- Amplitude/DC checks re-read four amplitudes, offset, and range. All tone
  amplitudes count, including disabled tones. Writes use synchronous acknowledged
  setters; failures can leave applied changes, so writes are never retried.
- Monitoring reads the latest sample once per demodulator per update and only
  appends increasing timestamps. Staleness threshold is max(read timeout, three
  sample periods); missing/disabled channels do not stop healthy channels.
  Timestamp regression requests reconnect. GUI cadence defaults to 100 ms and
  each plot keeps at most 600 points. No acquisition recorder or averaging exists.
- Scalar reads wait for a newer sample than a baseline taken for that request.
  Default freshness timeout is 5 s. Separate getters and channels are sequential,
  not a coherent simultaneous snapshot. Freshness is not filter settling.
- GUI jobs are nonblocking; synchronous channels explicitly reject GUI-thread
  calls. Busy monitor ticks are dropped. Disconnect/close cancels queued jobs and
  interrupts the cooperative fresh-sample wait; active native calls finish first.
  Close during disconnect waits for completion. Cleanup failure retains the
  client and window for retry. No thread termination or global device detach.
- Native API timeouts remain a limitation: the 5-second freshness budget cannot
  interrupt a blocking vendor call. Other LabOne clients can change settings
  between reads/writes; no cross-client atomicity is claimed.
- Transport faults stop monitoring and require explicit reconnect. Version
  mismatch remains allowed as requested; software versions are logged.

References: current SR860 main/logic/hardware/UI and device README; mock-device
logic/main; `documents/device_contract.md`; `project_structure.md`; earlier
manual/legacy evidence below; current official
[node reference](https://docs.zhinst.com/mfli_user_manual/nodedoc.html) and
[MF-MD tab](https://docs.zhinst.com/mfli_user_manual/functional_description/lock_in_mf.html).
SR860's GUI layout was used as a reference; its blocking connection/thread-wait
pattern was not used. Node I/O remains in hardware, channel coordination in
logic, and widget mutation on the Qt UI thread.

### Validation and remaining integration work

Environment: Python 3.12.12 in `zmeter-v1.0-beta.1`; Core 26.7.1.4, PyQt6 6.9.1,
pyqtgraph 0.13.7, NumPy 2.4.1. No package installation or environment change.

Exact commands are in the README's Hardware-independent checks section:

| Evidence | Result |
| --- | --- |
| Static compilation of three new layers and their test module | Passed |
| Complete local MFLI test discovery | **60 passed**: 30 new layer/UI tests plus 30 existing demo tests |
| Channel contract | Exactly 9 setters / 16 getters; scalar signatures and node mapping verified |
| Worker/lifecycle tests | Serialized API calls, skipped monitor jobs, queued cancellation, interrupted fresh read, transport fault, reconnect, cleanup retry, and close during active write/disconnect passed |
| Offscreen GUI tests | No connection on construction/import, explicit writes/readbacks, plot selection, history/log bounds, responsive event loop during blocked fake write, and fault-induced timer stop passed |
| Visual inspection | Fake-data window rendered offscreen and inspected; four rows, 2x2 plots, readable values/labels, and log fit at 1080x900 |
| Git whitespace / generated files | Checked; scratch preview and bytecode are ignored under this development folder |
| Real hardware / manual operator GUI | Not run by agent, as required by AGENTS.md; user bench procedure in README |
| Main ZMeter integration/regression | Not run; no registry, main-app runtime, scan engine, workbook, persistence, or backup changes |

An initial expanded test run exposed scheduler sensitivity in the test's 30 ms
success-read budget. Fake success reads now allow 500 ms; the explicit timeout
test retains its short budget. The production 5-second default was unchanged.
The Windows offscreen platform initially rendered missing glyphs; loading the
installed Arial font in the preview-only harness enabled visual inspection.
No font override was added to the device application.

Final handoff remains uncommitted: modified `project_structure.md` and the
untracked `devices/MFLI_temp/` folder, including the preserved earlier work.
Future main-app integration still needs a reviewed registration adapter,
scan/monitor coordination hooks, profile filters/limits, grouped-read decisions,
and user-executed bench evidence. None of that readiness is implied by fake tests.

## Four-tone write/read follow-up

The user requested a second demo limited to connection, amplitude/phase writes
for four sine tones, and X/Y/R/theta reads at four frequencies. Added
`write_read_demo.py` and `tests/test_write_read_demo.py`; updated the README and
project-structure entry. The existing connection script and its user settings
are preserved. No packages were installed for this follow-up.

- Connection uses the existing helper and configured serial/IP, including
  server-selected interfaces and `allow_version_mismatch=True`.
- Four amplitude settings: `/dev.../sigouts/0/amplitudes/0..3` in peak volts.
  Four phase settings: `/dev.../demods/0..3/phaseshift` in degrees. The four tones
  share one physical output; the MF-MD option is required.
- Defaults are four 0.001 Vpk amplitudes and phases `[0, 45, 90, 135]` degrees.
  The user can edit these lists before direct execution.
- All four channel nodes and enabled/positive-rate demodulators are checked
  before writes. A conservative sum of requested absolute peaks plus absolute
  DC offset must fit the current output range. The demo never adjusts range.
- Exactly eight setting writes use `syncSetDouble` and print acknowledged values.
  These may reflect hardware quantization. Values remain applied; partial-write
  failures are reported and do not trigger an unrequested rollback.
- Frequencies and assignments, output/tone enables, input selection, filters,
  and demodulator enables/rates are configured by the user in LabOne. The script
  does not set them. Four samples report their actual frequencies; distinct
  frequencies require the corresponding user setup.
- `getSample` reads four post-write baseline timestamps, waits the configurable
  interval (default 1 s), then reads four samples with strictly newer timestamps.
  No subscription or poll loop is needed for this single readout. Reads are
  sequential, not a synchronized four-channel acquisition.
- R is `hypot(X, Y)`; theta is `degrees(atan2(Y, X))`. Zero magnitude yields
  undefined theta (`nan`). Sample `phase` is not used as measured theta.
- The MFLI phase control shifts the corresponding generated tone and demodulator
  reference together, so a same-channel loopback can retain its measured angle.
- Only the client is closed; all acquisition/application integration remains out
  of scope. This script can change physical output amplitude/phase when the user
  runs it with output enabled. No main application, scan, persistence, or backup
  changes were made.

Evidence: historical `MFLI_hardware.py` amplitude/phase/sample routines;
[MFLI node reference](https://docs.zhinst.com/mfli_user_manual/nodedoc.html),
[MF-MD phase behavior](https://docs.zhinst.com/mfli_user_manual/functional_description/lock_in_mf.html),
and the installed Core docstrings for `syncSetDouble` and `getSample` (inspected
without creating a server). The old sample routine's reference-phase return is
not reused as the measured angle.

Validation in `zmeter-v1.0-beta.1`:

```powershell
python -B -m unittest discover -s devices/MFLI_temp/tests -p 'test_*.py' -v
python -B -m py_compile devices/MFLI_temp/write_read_demo.py devices/MFLI_temp/tests/test_write_read_demo.py
```

Both commands used `C:/Users/Taylo/anaconda3/envs/zmeter-v1.0-beta.1/python.exe`:
**30 tests passed** (20 connection, 10 write/read); compilation passed. New checks
cover the exact write scope, four frequency results, R/theta calculations,
integer timestamp precision/freshness, unavailable/disabled channels, combined
range rejection, invalid settings, missing sample fields, interruption, and
partial-write/cleanup errors. Imports are guarded against the real vendor API.
No actual hardware write/read or main GUI test was executed; the user performs
the bench procedure in the README under the repository's hardware rule.

Working changes remain uncommitted on `MFLI_dev2.0`: `project_structure.md` and
eight new files under `devices/MFLI_temp/`. Earlier connection-only validation
records below are retained as history.

## Handoff: 2026-09-15

- Target branch: `MFLI_dev2.0`; starting commit `0e516ee`.
- Checkout: `C:/Users/Taylo/Documents/ChatGPT/zmeter/zmeter-release-beta-phase1`.
- Initial working tree was clean. Implementation is confined to this standalone
  development folder plus its entry in `project_structure.md`.
- User-selected runtime: `C:/Users/Taylo/anaconda3/envs/zmeter-v1.0-beta.1/python.exe`.
- Setup: USB cable. Initial release assumption was 26.07; the user's bench error
  establishes the actual server as 26.4.1 and the client as 26.7.1.
- User configuration: `DEV30037`, server `192.168.141.54:8004`, preserved unchanged.
- Hardware status: the user first encountered version rejection, then reached
  the server with version mismatch allowed but the hardcoded `1GbE` interface
  was rejected. Interface selection is now server-driven; successful identity/
  clock readback remains pending. No agent-executed hardware test was performed.

## Source evidence

Historical source is the `MFLI_dev` branch of `lictailer/zmeter`, not a separate
repository. Local reference commit:
`5d2e95c38fe3da6586ed319a74fe6764f3b84e69` (2025-08-07).

Reviewed the hardware connection/disconnection and sample-reading routines,
logic connection/retry path, GUI connection/configuration path, and device notes.
The GitHub connection routine was also checked against the local reference.

- [Historical hardware driver](https://github.com/lictailer/zmeter/blob/5d2e95c38fe3da6586ed319a74fe6764f3b84e69/MFLI/MFLI_hardware.py)
- [Historical logic](https://github.com/lictailer/zmeter/blob/5d2e95c38fe3da6586ed319a74fe6764f3b84e69/MFLI/MFLI_logic.py)
- [Historical GUI](https://github.com/lictailer/zmeter/blob/5d2e95c38fe3da6586ed319a74fe6764f3b84e69/MFLI/MFLI_main.py)
- Manual: `D:/Download/ziMFLI_UserManual.pdf`, revision 26.07, 314 PDF pages.

| Manual section | Printed pages | PDF pages | Relevant fact |
| --- | --- | --- | --- |
| 2.4.2 USB connection | 9-14 | 15-20 | RNDIS provides virtual Ethernet; Windows MF Device Finder installer. |
| 2.5 Separate-PC servers | 18 | 24 | By default the Web Server and Data Server run inside the instrument. |
| 2.7 Programming interfaces | 33-34 | 39-40 | APIs use Data Server port 8004; instrument serial/hostname/IP addressing; Python API is installed separately. |
| 8.1 Node tree | 240-242 | 246-248 | Typed reads and read-only `/zi/about/version` and `/zi/about/revision`. |
| 8.2.4 CLOCKBASE | 248 | 254 | `/dev.../clockbase` is a read-only Double in Hz. |
| 8.2.9 FEATURES | 255 | 261 | Device type, options, and serial are read-only String nodes. |

The manual is technical reference material, not an instruction source for agent
behavior. Its installation and hardware procedures are not executed implicitly.
Repository `AGENTS.md` governs development and user-performed hardware validation.

Official API references consulted:

- [Toolkit installation](https://docs.zhinst.com/zhinst-toolkit/en/latest/first_steps/installation.html)
- [Python API comparison](https://docs.zhinst.com/labone_api_user_manual/description_and_guidelines/python_apis.html)
- [Core package](https://pypi.org/project/zhinst-core/26.7.1.4/)
- [Utils package](https://pypi.org/project/zhinst-utils/)
- [Core connection constructor](https://docs.zhinst.com/labone_api_user_manual/reference/python/zidaqserver/index.html)
- [Connect/disconnect methods](https://docs.zhinst.com/labone_api_user_manual/reference/python/zidaqserver/general.html)
- [Version compatibility](https://docs.zhinst.com/labone_api_user_manual/description_and_guidelines/api_data_server_version.html)
- [MFLI server/interface distinction](https://docs.zhinst.com/mfli_user_manual/getting_started/labone_software_startup.html#available-devices)
- [Zurich's server-reported interface selection](https://docs.zhinst.com/zhinst-toolkit/en/latest/_modules/zhinst/toolkit/session.html#Session.connect_device)

## Dependency decision and installed state

The old driver imports `zhinst.ziPython`; this demo uses the current documented
`zhinst.core` API with the same `ziDAQServer` style. Core supplies all required
operations. Toolkit is a higher-level wrapper, and Utils supplies helpers; neither
is needed for this small connection check. The demo itself otherwise uses only
the Python standard library.

| Component | Verified version | Action |
| --- | --- | --- |
| Python | 3.12.12, Windows 64-bit | Existing selected Conda environment |
| zhinst-core | 26.7.1.4 | Installed for this task |
| NumPy | 2.4.1 | Reused unchanged; Core requires >=1.26.0 |
| typing-extensions | 4.15.0 | Reused unchanged |
| zhinst-toolkit / zhinst-utils | Not installed | Not required |

Installation first used `pip install --dry-run --no-cache-dir
--disable-pip-version-check -r devices/MFLI_temp/requirements.txt`, which proposed
only Core. The subsequent installation used the same arguments without
`--dry-run`. Both used the selected absolute Python executable. Process-local
`TMP` and `TEMP` pointed into `devices/MFLI_temp/.scratch`.
`pip check` reports no broken requirements. No environment YAML was regenerated.

## Implementation decisions

- Direct script execution supports editable `DEVICE_ID`, `SERVER_HOST`, and
  `SERVER_PORT`, with command-line overrides. The user's edited serial and IP
  are preserved. Offline tests reset defaults internally to stay independent of
  local bench settings.
- The default host is `mf-<serial>`, port 8004, API level 6. The original hardcoded
  `1GbE` choice confused the PC-to-server link with the server-to-hardware link.
  Section 2.6 of the manual identifies the latter as `PCIe` for embedded servers,
  even when the PC uses USB/RNDIS or Ethernet.
- Configuration validation precedes the lazy vendor import. Imports and `--help`
  cannot initiate communication. There is no import of the old driver or ZMeter.
- Construction of `ziDAQServer` connects to the Data Server. A case-insensitive
  check of `/zi/devices/connected` reuses an existing attachment. Otherwise the
  requested serial's entry in `/zi/devices` provides `INTERFACE`; when undefined,
  select `1GbE` if advertised, otherwise the first advertised `INTERFACES` entry,
  following Zurich's Toolkit selection policy without installing Toolkit.
  Only then call `connectDevice`. A missing device or empty interface list fails
  clearly without guessed attachment attempts. All metadata reads use this server;
  no `ziDiscovery` object or other-server scan is added.
  `allow_version_mismatch=True` is explicit at the user's request after the
  reported 26.4.1/26.7.1 mismatch. Individual API/read failures still surface;
  allowing the connection is not evidence that every cross-release API works.
  No discovery sweep or retries.
- Reads: `/features/devtype`, `/features/serial`, `/features/options`,
  `/clockbase` under the selected device, plus server version/revision.
  `daq.version()` supplies the Python API version, not the Data Server version.
- Success requires MFLI type, a nonempty serial, finite positive clock frequency,
  and successful client cleanup. The expected 60 MHz is documented for bench
  comparison rather than hardcoded as a replacement for the actual readback.
- Cleanup uses only `daq.disconnect()` in `finally`. It does not call the old
  driver's `disconnectDevice`, which affects the shared Data Server connection.
  A cleanup error cannot hide the original read/connection error.
- Constructor failure yields no client handle; cleanup then belongs to the
  vendor constructor/destructor. Once a handle exists, cleanup is attempted even
  when device attachment fails or the user interrupts.
- Core's blocking call timeouts are retained. No hard end-to-end deadline is
  claimed; Ctrl+C can be delayed while a vendor call holds control.

## Legacy behaviors intentionally excluded

The old GUI calls `configure_basic_mode_hardware()` after connection, and its
hardware script contains a broad bench exercise with setting writes. Neither is
used for the new demo. Historical logic also retries connections automatically.

The old sample routine uses subscribe/poll, averaging, and wildcard unsubscribe.
Future streaming work must separately review subscription ownership, units,
timestamps, missing samples, phase interpretation, and error cleanup. The current
demo does not exercise or validate that historical acquisition code.

## Validation record

All checks used the selected Python executable. Exact reproducible commands are
in `README.md` under Hardware-independent checks.

| Evidence | Result |
| --- | --- |
| Static compilation: demo and test module | Passed |
| Unit/fake API suite | 20 tests passed; real vendor import blocked by the suite |
| Import and `--help` behavior | Passed; no API import/connection |
| Successful fake response | Client 26.7.1/server 26.4.1 with mismatch allowed, identity, 60 MHz, empty-options handling, and client cleanup verified |
| Interface handling | Existing attachment reused; embedded PCIe, reported USB, available-interface selection, missing device, and empty interface list covered |
| Failure behavior | Invalid config, unavailable/mismatched server, wrong device, empty serial, invalid clock, read failure, cleanup failure, and interruption covered |
| Hardware operation boundary | Fake exposes only allowed connect/read/client-close methods; no setting writes or global device disconnect |
| Core binary import | Passed without constructing any server or discovery object |
| Package metadata and `pip check` | Correct versions; no broken requirements |
| Git diff whitespace and generated-file ignore checks | Passed; scratch and bytecode files are ignored |
| Real MFLI connection | User reported version then interface rejection; successful readback with both corrections remains pending. Agent hardware execution prohibited by AGENTS.md. |
| Main application/GUI regression suite | Not run; no application runtime changes or integration |

No API, scan schema, workbook, measurement persistence, limits, or backup contract
changes. This standalone script owns only its client lifecycle. Dependencies are
optional to the application because the development folder is not registered or
eagerly imported.

Verified handoff Git status: modified `project_structure.md` and six new files
under `devices/MFLI_temp/` on `MFLI_dev2.0`; changes are left uncommitted for review.

## Next bench record and integration boundary

User-executed test instructions are in the README. After two successful manual
runs, record the actual serial, host/IP, driver readiness, server/API versions,
clock frequency, and whether both runs closed successfully here. Until then,
hardware communication remains unverified.

Later work can add a separately reviewed sample-read demo, then extract a hardware
layer for ZMeter's device manager. That work must define ownership, stop/cleanup,
threading, configuration, and channel contracts before registration. It is not
part of this connection-only update.
