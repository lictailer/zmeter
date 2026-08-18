# Device Logging and Kinesis Connection Update Plan

> Implementation note (2026-08-18): this file preserves the original
> investigation and its more defensive proposal. The subsequently approved
> implementation keeps the connection change smaller: initialize each Kinesis
> component once, connect the supplied serial directly, then perform one
> refresh and one retry of that same serial after failure. It intentionally
> does not add serial-list validation or other new hardware checks.

## Status and scope

- Status: investigation record retained alongside the implemented update.
- Investigation baseline: `merge_offline_branches` at `829e5f0`.
- Primary devices: BBD30X, Four9, and K10CR1.
- Shared component in scope: `core/shared_runtime/kinesis.py`.
- Canonical developer documentation in scope: `documents/device_contract.md`.
- This work affects device UI presentation, worker-thread error reporting,
  Kinesis discovery/connection lifecycle, and shared runtime state.
- This work does not change scan channels, units, motion limits, persisted scan
  data, backup behavior, or measurement schemas.
- Agents must not load Kinesis, discover devices, connect hardware, home, move,
  read, write, stop, or disconnect real laboratory equipment. All hardware
  validation in this document is user-executed.

## Goals

1. Make device logs concise operator-facing event logs rather than command
   transcripts.
2. Give BBD30X and Four9 consistent log presentation and add the same facility
   to K10CR1.
3. Preserve an approximately eight-line default log height with vertical
   expansion/resizing.
4. Stop rebuilding and enumerating the Kinesis device list before every known-
   serial connection while retaining the initialization required by Kinesis.
5. Classify BBD30X first-connection failures using evidence instead of hiding
   them with arbitrary sleeps or blind retry loops.
6. Keep the update small, reviewable, and limited to the named devices and
   shared runtime behavior.

## Locked requirements

### Device logs

- Every maintained device widget should provide a device log window.
- Log connection and disconnection state, errors, warnings, and important
  device or lifecycle events.
- Do not normally log successful routine set/read operations.
- Do not log polling samples or repeated position samples.
- Use a read-only, auto-scrolling log with timestamps and severity.
- Retain at most 500 in-memory entries; do not write device logs to disk.
- The default log height should show approximately eight lines.
- The log must remain vertically expandable/resizable and must not have a
  restrictive maximum height.
- Use shared presentation infrastructure where practical, while leaving the
  decision about which events are important in each device's logic layer.

### Kinesis connections and discovery

- A known serial should use the normal direct create/open and connect path once
  the relevant Kinesis DeviceManager API has been initialized.
- Do not enumerate or print all connected devices during every normal
  connection.
- Retain the initial `BuildDeviceList` call required by the supported Thorlabs
  connection sequence.
- Cache successful initialization per Kinesis API family/component; BBD30X uses
  the managed CLI API and K10CR1 uses the native integrated-stepper C API.
- Do not cache failed initialization.
- Use one explicit, serialized discovery refresh only when the direct path
  cannot proceed or the known device may have been hot-plugged or removed.
- Inspect the requested serial during fallback; do not silently choose another
  device.
- Do not add unbounded retries, periodic background discovery, or arbitrary
  connection sleeps.

## Investigation findings

### Existing log implementations

#### BBD30X

Relevant files:

- `BBD30X/BBD30X_logic.py`
- `BBD30X/BBD30X_main.py`
- `BBD30X/bbd30x.ui`

`BBD30X_Logic.sig_log` emits `(level, message)` tuples. The widget timestamps
them, appends them to a `QPlainTextEdit`, auto-scrolls, and caps the document at
500 blocks. The UI currently gives the log a 200-pixel minimum height and no
maximum height, so it expands vertically.

The log already includes appropriate lifecycle and fault events, but it also
includes routine successful operations:

- move started and move completed;
- manual position read;
- manual velocity/acceleration readback.

Connection failures are currently duplicated: `BBD30X_Logic.connect()` logs a
contextual error and re-raises, then `BBD30X_Logic.run()` logs the same exception
again as a generic error.

#### Four9

Relevant files:

- `four9/four9_logic.py`
- `four9/four9_main.py`
- `four9/four9.ui`

The widget connects every `Four9Logic.sig_status` message directly to its
`QTextEdit`. The widget timestamps and auto-scrolls entries but does not cap the
document or attach severity. The log expands with the vertical layout.

Because `sig_status` is the log path, successful `get_temperature()` and
`set_temperature()` messages appear in the log. Stable-wait polling itself does
not produce one entry per one-second sample, which should be preserved.

#### K10CR1

Relevant files:

- `k10cr1/k10cr1_logic.py`
- `k10cr1/k10cr1_main.py`
- `k10cr1/k10cr1.ui`

K10CR1 has no device log. `sig_info` updates one `QLabel`, replacing its prior
contents. `pass_info()` is used for connection details, velocity calls, polling
calls, move calls, and every position sample. Connecting this signal directly
to a new log would create unacceptable noise.

The entire K10CR1 widget currently has a fixed vertical size with a maximum
height of 127 pixels. Adding a resizable log requires removing that root-level
height restriction while preserving the existing control layout and width.

### Existing shared infrastructure

There is no common device-log widget or formatter in `core`. BBD30X, SR860,
SR830_v2, Four9, OptiCool, and Montana2 each implement their own timestamping,
append, cap, and scroll behavior. The closest maintained pattern is the
BBD30X/SR860 combination:

- severity-aware signal payload;
- read-only `QPlainTextEdit`;
- timestamped append;
- 500-block cap;
- scroll to the newest entry.

Because three devices need the same presentation behavior in this update, a
small shared UI helper is warranted. It must not become a logging framework or
move device-event policy into `core`.

## BBD30X connection trace

One BBD30X UI connection request follows this sequence:

1. `BBD30X.connect()` reads the serial and calls
   `logic.submit_ui_job(logic.connect, serial)`.
2. `BBD30X_Logic.submit_ui_job()` starts its `QThread`.
3. `BBD30X_Logic.run()` calls `BBD30X_Logic.connect(serial)` exactly once.
4. `BBD30x_hardware._ensure_bindings()` acquires a shared Kinesis lease and
   lazily loads the managed bindings.
5. `KinesisRuntime.initialize_device_manager()` calls
   `DeviceManagerCLI.BuildDeviceList()` under a lock.
6. `DeviceManagerCLI.GetDeviceList()` is called and every returned serial is
   printed, but the requested serial is not validated.
7. `CreateBenchtopBrushlessMotor(serial)` creates the managed controller object.
8. `device.Connect(serial)` performs the connection.
9. Only after `Connect` succeeds, the code gets channel 1 and calls
   `WaitForSettingsInitialized(5000)`.
10. It loads device motor configuration or applies the existing DDS220 file-
    settings fallback.
11. It starts 50 ms polling, waits 300 ms, enables the channel, and waits
    another 300 ms.
12. It writes and reads back the 100 mm/s velocity and 2000 mm/s^2
    acceleration defaults.

If any step raises, hardware cleanup stops polling when available, disconnects
the created device object when available, clears channel/device references, and
releases the Kinesis lease.

There is no ZMeter reconnect timer, delayed retry, or second asynchronous
connection request. A connection attempt seen several seconds later must come
from another button click or external caller. Vendor-internal background state
is not visible to ZMeter.

## BBD30X first-connection failure conclusion

Observed exception:

```text
DeviceNotReadyException: Device is not connected
  at ...VerifyDeviceConnected(...)
  at ...BenchtopBrushlessMotor.Connect(String serialNo)
```

The stack location proves that the failure occurs inside the first
`device.Connect(serial)` call. Channel selection, settings initialization,
polling, device enable, configuration fallback, and motion-parameter writes all
occur later and cannot cause this exception.

Confirmed application defects:

- `BuildDeviceList()` is executed for every connection instead of being owned
  as initialized process/API-family state.
- `KinesisRuntime.initialize_device_manager()` serializes the callback but does
  not remember successful initialization.
- BBD30X enumerates all devices but does not use that snapshot to validate the
  requested serial.
- The code immediately calls `Connect` after a global list rebuild and records
  no structured evidence about target-serial visibility.

The first-failure/second-success pattern is consistent with a cold or freshly
rebuilt Kinesis/USB manager becoming usable after the first attempt. Static
source cannot distinguish whether the requested serial was absent, present but
not ready, exclusively owned by another application, or unavailable because of
a driver/controller condition. Claiming one of those vendor-side states without
the missing serial-visibility evidence would be speculative.

The implementation must therefore both remove the repeated initialization
defect and preserve enough evidence to classify any remaining failure. It must
not merely suppress `DeviceNotReadyException` or retry until it disappears.

## Is device scanning required?

The initial device-list build must remain. Thorlabs' official BBD30X and K10CR1
examples call `BuildDeviceList()` before creating/opening and connecting a
known serial:

- BBD30X Pythonnet example:
  <https://github.com/Thorlabs/Motion_Control_Examples/blob/main/Python/Kinesis/Benchtop/BBDXXX/bbd_pythonnet.py>
- K10CR1 example:
  <https://github.com/Thorlabs/Motion_Control_Examples/blob/main/Python/Kinesis/Integrated%20Stages/Cage%20Rotator/K10CR1_pythonnet.py>
- Kinesis C# getting-started guide:
  <https://media.thorlabs.com/contentassets/5f57e82e38004e2aa5dfd0071bcf0732/kinesis_with_c_quick_start_guide.pdf?v=1116111504>

The normal target behavior is:

```text
first use of API family
  -> serialized BuildDeviceList once
  -> verify requested serial when the API supports it
  -> create/open known serial
  -> connect

later connection with known serial
  -> create/open known serial directly
  -> connect

direct connection cannot proceed
  -> one serialized forced refresh
  -> inspect only the requested serial
  -> classify absent versus present-but-unavailable
  -> at most one connection retry when the refresh is the justified fallback
```

`GetDeviceList()` and printing every serial are not required in the normal
known-serial path. Discovery is a cold-initialization or explicit fallback
operation, not a per-connection display action.

## Target logging policy

### Log these events

- connection requested, succeeded, failed, and disconnected;
- fallback discovery and whether the requested serial was found;
- validation warnings, busy rejections, transport/protocol errors, timeouts,
  and cleanup failures;
- device identity/firmware summary after connection when useful;
- important state changes such as BBD30X T0, home, cancellation/stop, Four9
  stable-wait start/result/timeout/abort, and server-reported errors;
- K10CR1 stuck-position or iteration-limit conditions.

### Do not log these successful routine events

- successful position or temperature reads;
- successful ordinary position, angle, temperature, or parameter sets;
- every move/poll position sample;
- raw successful vendor return codes;
- periodic stable-wait status polls.

Routine results must continue updating their dedicated UI labels and signals;
removing them from the log must not remove user feedback.

## Implementation plan

### 1. Shared device-log presentation helper

Add `core/device_log.py` with two small functions or one equivalently small
helper object:

- configure a `QPlainTextEdit` as read-only;
- cap it at 500 document blocks;
- use active font metrics to calculate a minimum/default height of about eight
  text lines;
- retain an expanding vertical size policy and no restrictive maximum height;
- append `[timestamp] [LEVEL] message`;
- scroll to the newest entry.

Do not add Python's global `logging` configuration, disk handlers, cross-device
event routing, or a device base class in this update.

### 2. Shared Kinesis DeviceManager state

Update `core/shared_runtime/kinesis.py`:

- retain the existing device-manager lock;
- add initialized state keyed by explicit API family/component;
- provide an `ensure` operation that runs and caches the first successful build;
- report whether initialization ran or was already cached when callers need to
  choose between cold and direct paths;
- provide an explicit forced-refresh operation under the same lock;
- do not mark a key initialized when its build callback fails;
- keep managed and native keys separate unless tests and vendor evidence prove
  they safely share initialization state;
- preserve lazy loading, lease accounting, diagnostics, and shutdown behavior.

Suggested keys:

- `bbd30x-managed-cli`;
- `k10cr1-native-integrated-stepper`.

### 3. BBD30X connection and logging

Update `BBD30X/BBD30X_hardware.py`:

- use the managed DeviceManager ensure operation;
- on cold initialization, check whether the requested serial is present without
  printing every serial;
- on an already initialized runtime, create/connect the known serial directly;
- if that direct path raises a discovery/readiness error, clean the failed
  object, force one refresh, and inspect the requested serial;
- if absent, raise an actionable unavailable/invalid-serial error without
  attempting another device;
- if present after a justified fallback refresh, recreate the object and allow
  at most one connection retry;
- if cold initialization just found the serial but the first `Connect` still
  fails, report present-but-unavailable rather than immediately rebuilding and
  retrying;
- preserve channel 1 selection, settings initialization, DDS220 fallback,
  polling, enable timing, default parameters, and cleanup.

Update `BBD30X/BBD30X_logic.py`:

- keep lifecycle, fallback discovery, default-parameter connection summary,
  T0, home, stop/cancellation, warning, and error log events;
- remove successful routine move, manual position-read, and manual motion-
  parameter readback log events;
- preserve status-label and position/target/parameter signals;
- ensure each failed UI job creates one contextual log entry rather than a
  contextual plus generic duplicate.

Update `BBD30X/BBD30X_main.py` and `BBD30X/bbd30x.ui`:

- use the shared log helper;
- retain `QPlainTextEdit`, auto-scroll, and the 500-entry cap through the helper;
- replace the 200-pixel device-specific minimum with the shared approximately
  eight-line size;
- retain vertical expansion and resizing.

### 4. Four9 logging

Update `four9/four9_logic.py`:

- stop sending successful routine `get_temperature()` and `set_temperature()`
  result text to the device-log path;
- preserve temperature, target, and stability signals so labels still update;
- retain connection lifecycle, stable-wait lifecycle, timeout/abort, server
  `last_error`, rejected request, malformed protocol, connection loss, and busy
  or disconnected warnings;
- attach explicit severity to log events, either through a dedicated `sig_log`
  signal or a minimal compatible payload change.

Update `four9/four9_main.py` and `four9/four9.ui`:

- use `QPlainTextEdit` and the shared helper;
- retain the existing auto-scroll and vertical layout behavior;
- set the approximately eight-line default/minimum height;
- retain the latest 500 entries.

### 5. K10CR1 discovery, errors, and log window

Update `k10cr1/k10cr1_logic.py`:

- add a severity-aware device-log signal;
- make worker `run()` exception-safe so connection and operation errors reach
  the UI instead of escaping the `QThread`;
- reserve `sig_last_pos` for position display updates;
- stop emitting raw successful return codes and every current-position sample
  to the log;
- log connection/disconnection, requested-device identity/firmware summary,
  errors/warnings, home, stop, stuck/iteration-limit conditions, and important
  lifecycle events;
- use the native-component DeviceManager ensure operation;
- call `ISC_Open(serial)` directly after cached initialization;
- after a failed direct open, force one refresh and use targeted
  `TLI_GetDeviceInfo(serial)` or the narrowest available list call to classify
  the requested serial;
- never select a different serial and never add a retry loop;
- preserve existing velocity values, movement logic, and lease cleanup.

Update `k10cr1/k10cr1_main.py` and `k10cr1/k10cr1.ui`:

- add the shared device log;
- remove the root widget's restrictive fixed/maximum height;
- preserve the existing controls, labels, and width behavior;
- give the new log an approximately eight-line default/minimum height and an
  expanding vertical policy.

Do not use this task to redesign K10CR1 motion, limits, force-stop behavior, or
scan hooks. Those existing safety gaps remain separate work.

### 6. Documentation

Update `documents/device_contract.md` with a required device-log section:

- every active device widget has a log window;
- lifecycle, errors, warnings, and important information are logged;
- routine successful set/read results and polling samples normally are not;
- use timestamp and severity;
- default to approximately eight visible lines;
- remain vertically expandable/resizable;
- use the shared helper where practical;
- keep logging in memory unless a separate persistence requirement is approved.

Update `project_structure.md` if `core/device_log.py` is added.

Update these device documents:

- `BBD30X/README.md`: once-per-family initialization, direct connection,
  fallback discovery, present-but-unavailable errors, and revised log policy;
- `four9/README.md`: remove the statement that ordinary set/read operations are
  logged and document the shared log behavior;
- `k10cr1/README.md`: add the log behavior and revised discovery path while
  preserving the existing hardware-safety warnings.

## Acceptance criteria

### Presentation

- BBD30X, Four9, and K10CR1 each show a read-only device log.
- Each log initially shows approximately eight text lines.
- Each log can grow vertically when its device window is resized.
- Each retains no more than 500 entries and auto-scrolls to the newest entry.
- Entries have consistent timestamps and severity.

### Content

- Connection, disconnection, important events, warnings, and errors appear.
- Successful routine set/read operations do not appear.
- Position, temperature, and other routine results still update dedicated UI
  displays.
- Polling loops do not flood the logs.
- One failed BBD30X UI operation produces one contextual error entry.

### Kinesis behavior

- Each Kinesis API-family key builds its device list only once after successful
  initialization.
- Disconnect/reconnect with the same runtime uses the direct known-serial path.
- Failed initialization remains retryable.
- A failed direct connection can trigger at most one serialized refresh and at
  most one justified retry.
- Missing and present-but-unavailable serials produce different actionable
  errors.
- No normal connection prints or logs every connected Kinesis serial.
- Existing cleanup and lease release remain correct after every partial failure.

## Hardware-independent test plan

### Shared log helper

- Offscreen test read-only behavior, 500-block cap, timestamp/severity format,
  auto-scroll, eight-line sizing, expanding vertical policy, and no maximum-
  height restriction.

### Shared Kinesis runtime

- Test one successful build per explicit key.
- Test separate managed/native keys.
- Test concurrent ensure calls remain serialized and invoke one build.
- Test build failure is not cached and a later call can retry.
- Test forced refresh always runs under the same lock without changing lease
  ownership.

### BBD30X

- Fake-Kinesis test the complete cold sequence and requested-serial check.
- Test disconnect/reconnect does not rebuild the list.
- Test direct-path failure followed by one refresh with serial absent.
- Test direct-path failure followed by refresh with serial present and one
  recreated connection attempt.
- Test cold-build serial-present plus failed `Connect` does not blindly retry.
- Test cleanup and lease reacquisition after every failure point.
- Test normal move, read position, and manual parameter readback do not add log
  entries while their UI signals still fire.
- Test lifecycle, T0, home, stop, busy, validation, timeout, and connection
  errors remain logged once.

### Four9

- Test successful set/get updates target/current/stability labels without adding
  routine log entries.
- Test connect/disconnect, stable-wait start/result/timeout/abort, server error,
  protocol error, connection loss, disconnected action, and busy warning logs.
- Preserve the existing guarantee that one-second stable polling is not logged
  per sample.

### K10CR1

- Fake-native test cold build plus open and direct reconnect without rebuild.
- Test failed open fallback refresh, requested-serial classification, bounded
  retry, and lease/open cleanup.
- Test worker exceptions reach the device log.
- Test position polling updates the position label without adding log entries.
- Test important identity, connection, home, stop, stuck, and limit events are
  logged.
- Offscreen test the widget is vertically resizable after removing its fixed
  maximum height.

### Repository validation

1. Parse every changed `.ui` file as XML.
2. Compile every changed Python file.
3. Run the shared runtime, BBD30X, Four9, and K10CR1 hardware-independent suites.
4. Run the broader repository hardware-independent tests.
5. Run `git diff --check`.
6. Do not load vendor libraries or execute any real-device discovery.

## User-executed hardware diagnostics and verification

The first BBD30X bench run must record, without enumerating unrelated serials in
the operator log:

- whether the requested serial is present immediately after the cold
  DeviceManager build;
- whether the failure occurred on cold initialization or cached direct connect;
- exception type, message, and available vendor error code/HResult;
- whether Kinesis or another application has an open device session.

Interpretation:

- serial absent, then present after refresh: discovery/device-enumeration state;
- serial present but `Connect` fails: controller/driver readiness or exclusive
  ownership, not settings/polling/enable sequencing;
- serial present and direct reconnect succeeds without rebuild: confirms that
  repeated global rebuilding was unnecessary.

After code review and hardware-independent tests, the user may perform this
controlled verification:

1. Ensure the intended BBD30X and K10CR1 devices are mechanically safe and no
   other application owns them.
2. Start ZMeter and connect the reviewed BBD30X serial once; capture the concise
   device log and requested-serial diagnostic result.
3. Disconnect and reconnect; verify no full discovery is performed and the
   direct path succeeds.
4. Enter one intentionally unavailable serial; verify one fallback refresh and
   an actionable missing-device error with no retry loop.
5. Restore the reviewed serial and verify connection, read-only UI feedback,
   and disconnect cleanup without commanding movement.
6. Repeat only the connection/disconnection portion for K10CR1. Do not home or
   move it as part of this logging/discovery verification.

## Risks and regression controls

- Caching discovery can miss hot-plug changes. The explicit refresh fallback is
  required for that case.
- Managed BBD30X and native K10CR1 DeviceManager wrappers may not share all
  internal initialization state. Keep separate cache keys unless proven safe.
- Refreshing a global Kinesis list while another Kinesis device is connected
  may affect vendor state. Keep refresh serialized, rare, and limited to a
  failed connection path; verify multi-device behavior on the user bench.
- Removing routine log entries must not remove UI label updates or exception
  propagation to scans.
- Converting Four9 from `QTextEdit` to `QPlainTextEdit` changes presentation
  only; no rich-text behavior is currently used.
- Relaxing K10CR1's fixed height must not alter its existing control widths or
  scan-facing methods.
- Do not expand this task into K10CR1 motion safety, general device base classes,
  global Python logging configuration, disk logs, or scan persistence changes.

## Final implementation boundary

The intended patch is limited to:

- one small shared device-log presentation helper;
- keyed DeviceManager initialization/refresh state in the shared Kinesis
  runtime;
- focused logging and connection-path changes in BBD30X, Four9, and K10CR1;
- matching fake/offscreen tests;
- the canonical device contract, project structure, and three device READMEs.

No unrelated refactor or compatibility layer should be introduced.
