# 004: Declarative device SDK

- Status: Accepted
- Date: 2026-11-04
- Owners: ZMeter maintainers
- Supersedes: none

## Context

[ADR 003](003-v2-architecture.md) sets the v2 strategy and the package layout.
This ADR records the device-layer decisions that phase 1 implements, so that
agents and reviewers have one reference while the packages are built.

Verified facts about the current code that shape the decisions:

- A device is a widget plus a logic class plus a hardware class plus a
  registration. Adding one parameter touches the hardware method, the logic
  setter, a dedicated signal, a job string in `run()`, the widget wiring, and
  the `.ui` file. The facts about one parameter (name, unit, limits, scannable,
  snapshot, array) are spread over method prefixes, `ARRAY_GETTERS`,
  `SNAPSHOT_GETTERS`, `scan_range_limits.json`, and READMEs.
- Whether a parameter can be scanned depends on how the widget passes the
  value. Several SR860 setters take no argument and therefore cannot be scanned.
- `MainWindow._discover_variables_dictionary` finds channels with
  `inspect.getattr_static` and exact signatures (`get_x(self)`,
  `set_x(self, value)`). Setup capture reads `type(logic).SNAPSHOT_GETTERS`. A
  proxy that answers `__getattr__` is therefore not discovered.
- Every snapshot getter is also exposed as a scan readout, because discovery
  exposes every `get_` method.
- Scan I/O failures must raise: `scan_logic.py` wraps getter and setter
  exceptions and stops the scan. Returning `None` or `False` would be treated
  as data.
- The device manager runs `request_startup_connections` on the UI thread and
  the other lifecycle callbacks on worker threads that must not touch widgets.
- Device limits are checked only on the scan path today; panels write straight
  to the logic (ADR 003, decision 4).

## Decision

### 1. A device is a declaration plus a driver

A declarative device is a Python class derived from `Device` in
`zcore.devices`. It contains no Qt, no threads, no signals, and no job
strings. The author writes the hardware calls (the existing `*_hardware.py`
layer is reused as `driver_class`) and a table of declarations. Everything
else is derived from the declaration: scan channels, snapshot list, limit
checks, units for data files, the control panel, and the registry entry.

`Device` defines:

- `driver_class`: the hardware class. A driver instance can be injected in
  tests.
- `connection = Connection(address=str, timeout_s=10.0)`: generates the
  registry `DriverConfigSpec`, the panel's address field, and the connect
  timeout.
- `connect(address, timeout_s)` and `disconnect()`. The default builds
  `driver_class` and calls its connect and disconnect.
- `stop_hardware()`: stops motion or ramping at the hardware. Required for any
  device that declares a ramp or a long action.
- Optional `write_many(values)` for grouped writes (nidaq AOs).
- Optional standard actions `reset()`, `self_test()`, `set_display(on)`, with
  fixed signatures.
- `Device.spec()` returns an immutable `DeviceSpec`, built once when the class
  is created.

### 2. Declaration types

All of these are Qt-free values in `zcore.devices`.

| Type | Meaning |
| --- | --- |
| `Parameter(dtype, *, unit, limits, get, set, scan, snapshot, poll, ramp, stable, safe, timeout, group, order, hidden, doc)` | One named value. `dtype` is `float`, `int`, `bool`, `str`, or `Path`. `get` and `set` are driver method names or callables. |
| `Choice(options, settle_s=0.0)` | A fixed set of discrete states with labels (combo box in the panel). |
| `ArrayParameter(axes, shape, axis_values=None, unit=None, get, timeout=None)` | A long array read, at most two axes. Has its own timeout and is cancellable. |
| `MultiParameter(components, get, unit)` | Several values from one hardware read (SR860 X, Y, R, theta). |
| `Ramp(rate, interval=0.05)` | Stepped write. `rate` is a number or the name of another parameter. |
| `Stable(tolerance, duration_s, timeout_s)` | Readout must stay inside the tolerance for the duration. |
| `Trigger(call, *, scan=True, long=False)` | A control channel where writing any finite value runs `call` once. The value is ignored and only recorded. This keeps today's behavior of `auto_focus_focus`, `auto_position_position`, `default_count`, and `default_slack_notification`. |
| `@action(label, long=False)` | A panel-only operation (homing, load reference). User actions take no arguments in phase 1. |
| `unlimited(reason)` | Explicit "no device limit" with a reason. |

Rules that hold for every declaration:

- A settable numeric `Parameter` without `limits` is a declaration error.
  `limits=unlimited("reason")` is the only way to state that a limit does not
  exist. It produces a warning in the device log at connect, in the same way
  as ADR 003 decision 4 ("a missing limit produces a warning during
  migration").
- `Parameter(str)` and `Parameter(Path)` are panel settings (a reference-map
  path, a save directory). They are never scannable.
- `snapshot=True` parameters must be numeric while the old setup-capture path
  exists, because they also become scan readouts.
- Units are part of the contract. Changing a unit later is a visible change of
  one declaration and appears in data files.
- `Parameter` stays small. New fields are added only for a concrete device.

### 3. Validation at class creation

Declaration errors fail when the class is created, not when a scan runs:
names are unique across parameters, components, and actions; `get` and `set`
exist on `driver_class`; `scan` and `snapshot` parameters are numeric; limits
are finite with `low < high`; `safe` lies inside the limits; `ramp` appears
only on settable numerics; `poll > 0`; array axes are unique and at most two;
`Choice` options are non-empty and unique; a device with a ramp or a long
action implements `stop_hardware`.

### 4. Result type

Every call to a device returns `Result(status, value=None, reason="")` with
status `ok`, `timeout`, `cancelled`, `failed`, or `unknown`. There are
constructors for each status. Callers that need data (the scan bridge) turn
every non-ok result into an exception that names the status; they never
return `None` or `False` to the scan.

### 5. The Runner owns threads, ordering, and lifecycle

- One Runner thread and one priority queue per device instance. Priorities, in
  order: stop, scan, panel, polling. FIFO within a priority.
- `submit(op, priority)` returns a future of `Result`. Synchronous `get`,
  `set`, `call`, and `set_many` are built on it. Every write records its
  source (scan, panel, poll, test).
- A call made from the Runner's own thread (an action that reads a parameter)
  runs inline instead of deadlocking.
- **No automatic retries.** A timeout returns `Result.timeout`, and the device
  state becomes "state unknown" until the next successful read. The stuck
  driver call is not killed; its late result is logged and discarded.
- Device states: disconnected, connecting, idle, busy, error, state unknown.
- **Device limits are checked in the Runner** before any driver call, for every
  source including the panel. Values must be finite and inside the declared
  limit; a rejection returns `Result.failed(reason="outside device limit")`
  and never reaches the driver. Until the SafetyGate exists (phase 2) the
  Runner is the place of this check. Scan limits (`scan_range_limits.json`)
  are unchanged.
- Ramps run in the Runner, step by step at `Ramp.interval`. Each step passes
  the same limit check, checks the cancel flag, and emits progress. An
  interrupted ramp returns `Result.cancelled` with the last written value.
- `force_stop()` bypasses the queue: it sets the cancel flag, calls
  `stop_hardware()` directly on the caller's thread, drops queued panel and
  polling work, and reports where each ramping parameter actually stopped.
  **Driver requirement:** `stop_hardware()` must be safe to call while another
  driver call is in progress.
- Polling follows `poll`, runs at the lowest priority, has at most one pending
  poll per parameter, and can be paused and resumed (nested) for scans.
- Safe state: on disconnect, terminate, and force stop, the Runner writes each
  declared `safe` value through the normal limit and ramp path. Only
  parameters that declare `safe` are touched. A failure is logged and leaves
  the device "state unknown".
- `MultiParameter`: one hardware read fills every component, with a bounded
  cache age.
- `wait_stable(name)` honours `Stable` and is cancellable.

Device lifecycle, the same for every device. The author writes only the
hardware calls.

| Step | What the Runner does | What the device author writes |
| --- | --- | --- |
| Connect | state connecting; `device.connect(address, timeout)` on its thread; reads every readable parameter once so the panel starts filled; logs missing device limits; state idle | `connect()` (default builds `driver_class` and calls its connect) |
| Disconnect | drains the queue, cancels ramps, writes safe values, `device.disconnect()`, state disconnected | `disconnect()` |
| Reset, self-test | standard actions, refused during a scan; after reset every parameter is read again | optional `reset()`, `self_test()` |
| Scan prepare and restore | pauses polling and closes panel writes; reopens and resumes afterwards | nothing |
| Force stop | cancel flag, `stop_hardware()` without queueing, safe values | `stop_hardware()` |
| Timeout or error | state unknown until the next successful read, shown in the panel | nothing |
| Terminate | safe values, disconnect, thread stopped with a bound | nothing |

### 6. Qt layer

- `zcore/events.py` has a thread-safe `EventBus` with frozen events
  (`ValueChanged`, `StateChanged`, `LogEntry`, `Progress`). A failing
  subscriber is logged and never affects the publisher or other subscribers.
- `zui/event_bridge.py` re-emits events to the GUI thread through queued
  signals.
- `zui/auto_panel.py` builds a control panel from the `DeviceSpec`. Panel
  calls are always asynchronous: a button submits to the Runner and returns,
  and the result arrives as an event. While a scan has the device, write
  controls and actions are disabled. A device that needs a custom display
  (waveform, camera view) subclasses `AutoPanel` and adds only the special
  part.

| Declaration | Widget |
| --- | --- |
| numeric with limits and unit | spin box with range and unit suffix, Set and Read buttons |
| `Choice` | combo box |
| `bool` | check box |
| `str` / `Path` | line edit |
| read-only `Parameter` | value label, refreshed by polling events |
| with `ramp` | Ramp button with progress and Stop |
| `ArrayParameter` | curve (1 axis) or image (2 axes) preview |
| `MultiParameter` | one value label per component |
| `Trigger` | button |
| `@action` and standard actions | button; long actions show busy and Stop |
| every device | address field, Connect / Disconnect, state line, device log |

The AutoPanel needs the device-log helper, so `core/device_log.py` moves to
`zui/device_log.py` without a re-export (phase 1, PR 6).

### 7. Bridge to the old core

Until the channel layer (phase 2) reads declarations directly, a declarative
device must look to the registry, `DeviceManager`, `MainWindow` discovery, the
router, and setup capture exactly like an old-style device. The bridge lives
in `zui/bridge/` and has three parts:

- **Logic facade.** `make_logic_facade(device_cls, runner)` builds one real
  subclass per device class with `type()` (not a `__getattr__` proxy).
  It provides `get_<name>()` for scan readouts, snapshot parameters, and
  `MultiParameter` components, and `set_<name>(value)` for scan control
  parameters and triggers, plus array getters with shape and axis-value
  methods, and the class tables `ARRAY_GETTERS` and `SNAPSHOT_GETTERS`. Each
  call goes to the Runner at scan priority and waits up to the parameter
  timeout. A non-ok `Result` raises `DeviceOperationError` naming the status.
- **`BridgeWidget(AutoPanel)`** has `.logic` and the lifecycle methods the
  registry calls. `stop_scan()` pauses polling, closes panel admission, and
  waits with a bound for an in-flight panel call; it returns `False` if the
  device cannot be quiesced in time. `start_scan()` reopens admission and
  resumes polling only if it was running. Both are idempotent and touch no
  widget directly.
- **`declarative_registration(...)`** returns a complete `DriverRegistration`.
  The device module is imported lazily by the factory, so the registry still
  imports no device. `connect` waits on the Runner future with the reviewed
  timeout. `startup_connect` runs on the UI thread, submits to the Runner, and
  returns `None`. `is_busy` and `is_connected` read the Runner state;
  `terminate` applies safe values and shuts the Runner down with a bound.
  `runtime_mutation_allowed` stays `False`.

The generated `get_`/`set_` methods, the class tables, and the old-style
lifecycle methods of `BridgeWidget` exist only so that the old core can use
new devices. This is the "zui bridge adapter" transition interface of ADR 003,
removed at the end of phase 5. From phase 2 the channel layer reads the
declarations directly. Channel names stay `<device label>_<parameter name>`.
During migration a parameter keeps the suffix of its old `get_`/`set_` method,
so saved scans and queues keep working.

### 8. Virtual channels reuse the same value types

Virtual channels (artificial, Shift Compensation, `default_wait`) are not
`Device` classes. They have no driver and no Runner. They are introduced in
phase 2, and this ADR fixes only that they describe themselves with the same
value types as physical parameters (unit, limits, `Ramp`, `Stable`,
`Trigger`). A physical channel's description is built from its `Parameter`;
a virtual channel declares the same fields plus `depends_on`. Scans, the
SafetyGate, the UI, and file metadata then see one kind of channel
description. A virtual write passes its own limit, and then each physical
write passes the device limits. Phase 1 builds no virtual channel.

### 9. What is reserved now and what lands later

| Interface | Phase 1 delivers | Later |
| --- | --- | --- |
| Discrete states (707 switch matrix, relays) | `Choice(options, settle_s=...)` with labels; combo box in AutoPanel | Interlocks in the SafetyGate (phase 2); scanning by label with ScanPlan (phase 3) |
| Output enable and safe state | Standard `output_enabled` parameter; `Parameter(safe=...)` applied by the Runner on disconnect, terminate, and force stop | Panels of migrated devices (phase 5) |
| Wait until stable | `Stable(tolerance, duration_s, timeout_s)`; `Runner.wait_stable(name)` | "Wait until stable" in the executor (phase 3) |
| Several values per read | `MultiParameter`; one hardware read per point | none |
| Long array reads | `ArrayParameter` with its own timeout and cancellation | Block writes in storage (phase 4) |
| Self-test, reset, display off | Standard actions `self_test()`, `reset()`, `set_display(on)`; AutoPanel buttons, disabled during scans | One-click display off and dark theme (phase 2) |
| Grouped writes (nidaq AOs) | Optional `Device.write_many`; `Runner.set_many` | `ChannelService.write_many` (phase 2) |
| Serial text protocols | Not in phase 1 | A helper shaped by the first serial device migrated (phase 5, batch 3) |
| Virtual channels | Type reuse only (decision 8) | `VirtualChannel` in phase 2 |

### 10. Coverage of today's device patterns

| Pattern in zmeter today | Example | Declaration |
| --- | --- | --- |
| Scalar read (`get_x`) | SR860 X, nidaq AI | `Parameter(float, get=..., scan=True)` (read-only) |
| Scalar write (`set_x`), usually with readback | Keithley voltage, nidaq AO | `Parameter(float, get=..., set=..., limits=..., scan=True)` |
| Write that ramps | SR860 amplitude, mock ramp channels | `ramp=Ramp(...)` |
| Write that waits until stable | attoDRY T_stable, X3 wavelength_stable | `stable=Stable(...)` |
| Trigger (value ignored) | auto_focus focus, Slack ping | `Trigger(...)` |
| Array read | Andor spectrum and image, mock frame | `ArrayParameter` |
| Several values from one read | SR860 X/Y/R/theta | `MultiParameter` |
| Setup-capture readings (`SNAPSHOT_GETTERS`) | SR830 sensitivity | `snapshot=True` |
| Monitor timer in a panel | OptiCool temperature | `poll=...` |
| Fixed set of settings | time constant, range | `Choice(...)` |
| Panel-only operations | homing, load reference | `@action` or a non-scan `Parameter` |
| Custom display | nidaq waveform, Andor camera view | `AutoPanel` subclass |
| Virtual channels (artificial, Shift Compensation, `default_wait`) | none | Not device declarations (decision 8) |
| Coordinators that drive other devices | auto_focus, auto_position | Not migrated; they use `ChannelService` after phase 2 |

### 11. Scope and transition rules

- Phase 1 adds the SDK, the Runner, the Qt layer, the bridge, and one new
  declarative mock (`sim_device`). It changes no existing device, no
  `MainWindow`, no scan engine, and no saved file. It writes no bench script
  and needs no real instrument.
- New devices are written in the declarative style from the moment `sim_device`
  exists. Old devices are migrated in phase 5, one at a time, each with a
  reviewed declaration and a user-executed bench check before merge.
- New declarative devices import only `zcore.devices` and their own vendor
  library (ADR 003, decision 3). `zui` imports no device, and imports `core`
  only from `zui/bridge/`.
- Transition interfaces are listed in ADR 003 with their removal conditions.
  This ADR adds the wording of the `zui` bridge adapter (its three parts, as in
  decision 7). The second phase 1 interface, `mockDevice` importing the
  simulator from `devices/sim_device/`, is added to ADR 003 in the pull request
  that moves the simulator.

## Consequences

- Writing a new device becomes a hardware layer plus a table of declarations.
  The default panel works on the first day; custom panels are optional.
- Device limits finally apply to every write from every source for declarative
  devices, including the panel. Old devices are unaffected until migrated.
- Every scan read of a declarative device becomes a thread hop and a future.
  Phase 1 measures the per-point overhead on `sim_device`. If it matters, a
  direct scan-priority path can be added inside the Runner without changing
  any device.
- Two device styles coexist for months. `device_contract.md` documents both and
  marks the old one as legacy (phase 1, PR 10). Phase 5 deletes the old style
  and the bridge.
- The SDK shape is fixed early and later devices depend on it. The mitigation
  is few `Parameter` fields, reserved interfaces that are declared but not
  over-built, and tests that declare SR860-, SR830-, K10CR1-, and nidaq-like
  devices against fake drivers before anything else uses the SDK.
- A migrated device must keep its parameter names, so channel ids in saved
  scans and queues stay valid.

## Alternatives considered

- **Keep the widget-first structure and add helper functions.** Rejected: the
  per-parameter boilerplate and the scattered facts stay, and limits still
  cannot be enforced for panel writes.
- **A proxy logic object using `__getattr__`.** Rejected: channel discovery
  uses `inspect.getattr_static` and setup capture reads class attributes, so a
  proxy is not discovered. The facade is a real class built with `type()`.
- **Use QCoDeS or PyMeasure directly.** Rejected for now: the lab's scan
  engine, file format, and safety rules are specific, and the declaration
  style here follows the same idea with fewer concepts. This can be revisited
  once the SDK has real users.
- **Automatic retries on timeout.** Rejected: a retried write to an instrument
  in an unknown state can repeat a motion or a source change. The device is
  marked "state unknown" instead and the user decides.
- **Per-device threads written by each author (status quo).** Rejected:
  stop, force stop, ramp cancellation, and polling conflicts are reimplemented
  on every device. One tested Runner replaces them.
- **Build a serial text-protocol helper in phase 1.** Deferred: it would have
  no user. Its API should be shaped by the first serial device migrated.

## Validation implications

- Static and unit: every declaration validation rule has a failing case; the
  Runner tests are Qt-free and threaded tests are repeated many times to flush
  out races; `tests/test_layering.py` enforces the import rules for `zcore`,
  `zui`, and declarative devices.
- Offscreen GUI: AutoPanel widgets per declaration type, GUI-thread updates,
  controls disabled during scans.
- Integration (simulation): the bridge is tested through the real `MainWindow`
  discovery, `DeviceManager`, and setup capture, not fakes of them. The same
  scans on `mock_device` and `sim_device` produce identical data.
- Hardware: no phase 1 change needs a real instrument. When a real device is
  migrated (phase 5) its declaration (limits, ramp rates, safe values,
  `stop_hardware`) goes through code review, and a user-executed hardware bench
  check is required before merge.
