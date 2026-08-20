# Phase 2 Device Registration Review

## Outcome and compatibility policy

Phase 2 of [DEVICE_REGISTRATION_ROADMAP.md](DEVICE_REGISTRATION_ROADMAP.md)
has completed its registration review. `four9`, `montana2`, `opticool`, and
`tlpm` are admitted as lazy, startup-only drivers. Montana2, OptiCool, and TLPM
retain user-approved limitations that are recorded here rather than concealed.
The remaining ongoing packages stay explicitly unregistered.

The admitted drivers use the same profile behavior as Phase 1:

- ordered best-effort construction and startup connection;
- a failed construction or connection does not prevent the Main Window or
  unrelated devices from loading;
- `connect_on_start=false` for initial commissioning;
- asynchronous connection requests are reported as pending and finish in the
  existing device panel;
- `runtime_mutation_allowed=False`;
- lazy imports keep mock-only and unrelated startup free of optional device
  dependencies and network activity.

OptiCool vendor acquisition was moved behind its Connect worker, and TLPM
failure/stop/termination handling was made retryable and bounded. Montana2's
device implementation and the remaining normal-condition commands, units, and
transports were not rewritten. No physical instrument, vendor runtime, native
DLL, or external/laboratory network service was contacted by the coding agent.

## Admission matrix

| Driver ID | Package | Decision | Reason |
| --- | --- | --- | --- |
| `four9` | `devices.four9` | Registered startup-only | Explicit host/port, no constructor I/O, asynchronous panel connection, fake TCP/hardware coverage, abortable stable wait, and final client cleanup |
| `montana2` | `devices.montana2` | Registered startup-only with accepted limitations | Required profile address prefills the existing panel; source quick-connect endpoint, missing fake boundary, incomplete signal, unbounded REST, and uncertain final worker exit remain |
| `opticool` | `devices.opticool` | Registered startup-only with accepted limitations | Construction is vendor-free and Connect retries the fixed DLL load; limits, stable-wait timeout, fake boundary, and final worker proof remain incomplete |
| `autofocus_xz` | `devices.autofocus_xuguo` | Deferred | Constructor enumerates COM ports; long hardware/router work runs on the UI thread; active work is not stopped before termination |
| `auto_focus` | `devices.auto_focus` | Deferred | Constructor enumerates COM ports; object wiring is incomplete; direct NI coupling, UI blocking, embedded identifiers, and no coherent lifecycle |
| `auto_position` | `devices.auto_position` | Deferred | PyQt5 widget, direct legacy NI construction/tasks, no `.logic` device boundary, explicit profile resource, or final lifecycle |
| `anc300` | `devices.ANC300` | Deferred | Not an importable ZMeter package; no widget, logic, schema, scan channels, lifecycle, or fake backend |
| `tlpm` | `devices.tlpm` | Registered startup-only with accepted limitations | Native load remains inside Connect; failures are retryable and stop/join/disconnect are bounded, but Connect still selects and resets the first resource and no production fake backend exists |

The remaining deferred IDs are deliberately absent from the registry. Selecting one produces
the visible profile validation error `driver '<id>' is not registered` rather
than constructing an uncertain integration.

## Registered contracts

| Item | Reviewed value |
| --- | --- |
| Stable driver ID | `four9` |
| Widget | `devices.four9.four9_main.Four9` |
| Runtime dependency | Standard-library TCP socket; no shared runtime |
| Required connection fields | `host: str`, `port: int` |
| Optional connection fields | `socket_timeout_s: int/float` |
| Startup request | Existing `Four9Logic` QThread job; returns pending without waiting |
| Runtime mutation | Disabled |
| Set channels | `temperature`, `temperature_stable` |
| Get channels | `temperature` |
| Target limit | 0–300 K in the existing driver |
| Scan stop/final cleanup | `force_stop()` aborts the stable wait; `terminate_dev()` waits beyond the configured socket timeout and closes the client |

| Driver | Profile fields | Startup request | Runtime mutation |
| --- | --- | --- | --- |
| `montana2` | Required `address: str` | Existing QThread Connect job; pending | Disabled |
| `opticool` | None; fixed vendor installation path retained | Existing QThread Connect job; pending and retryable | Disabled |
| `tlpm` | None; first-resource selection retained | Existing QThread Connect job; pending and retryable | Disabled |

The registration copies the validated endpoint into the existing widget,
logic, and hardware fields without opening a socket. Startup then schedules the
same `connect` job used by the Connect button. The panel remains authoritative
for final success, failure, endpoint edits, and manual retry.

The tracked [phase2_lab.json](../config/profiles/phase2_lab.json) contains
disabled placeholders for all four registered drivers and keeps every
`connect_on_start=false`. Copy it to an ignored `*.local.json` profile and
replace only the target device's placeholder locally. No real enablement is
committed.

## Known Four9 limitations and future improvements

- TCP connect/read/write calls are bounded by `socket_timeout_s`, but a slow
  synchronous scan read can still occupy its scan worker for that interval.
- UI connection is asynchronous and the startup report therefore remains
  pending until the panel receives the worker result.
- There are no device-specific `start_scan`/`stop_scan` monitor hooks; the
  manager's documented missing-hook no-op behavior is retained.
- Stable-wait target and timeout behavior is controlled jointly by ZMeter and
  the external Four9 service. Record both versions and limits during bench use.
- Future work should add fake connection-loss/shutdown races around the manager
  adapter and an environment-specific dependency/service manifest.

## Accepted limitations and future work

### Montana2

The registration requires an explicit profile address but intentionally keeps
the existing source quick-connect IP. REST calls still lack explicit timeouts;
the stage-temperature signal is incomplete; scan setters can bypass the UI
range; termination may disconnect after an unconfirmed two-second wait; and no
fake REST boundary exists. Future work should correct these items and test
partial connection, stable-wait abort, disconnect, and shutdown.

### OptiCool

Vendor acquisition is now lazy and retryable, but the fixed
`C:\QdOptiCool\LabVIEW\QDInstrument.dll` installation path and one-second load
delay are intentionally retained inside Connect. Hard temperature/field/rate
validation, bounded stable waits, a termination path that proves the worker
stopped, and a fake .NET boundary remain future work.

### Autofocus packages and Auto Position

Unify ownership around the command router, move COM discovery to an explicit or
deferred operator action, keep long work off the UI thread, make DAQ/serial/save
configuration explicit, define safe limits and stop recovery, and provide a
complete busy/lifecycle/reference contract. Port `auto_position` to PyQt6 and
remove direct task creation from construction.

### ANC300

Build a normal importable widget/logic/hardware package around a reviewed
pyLabLib dependency. Define explicit controller transport, password/axes,
units, limits, channels, bounded stop, cleanup, and a simulator before adding a
registry ID.

### TLPM

Connect still discovers, opens, identity-queries, and resets the first detected
meter by explicit user decision. Connection failures now clean partial sessions
and allow retry; force-stop requests monitor exit; final termination waits up to
10 seconds and disconnects only after confirmed worker exit. Explicit resource
selection, bounded native calls, reviewed scan-channel semantics, and a
production fake backend remain future work.

## User-executed commissioning

Follow [hardware_safety.md](hardware_safety.md) and the device README.

Commission exactly one Phase 2 device at a time. Montana2, OptiCool, and TLPM
must use their device-local procedures and the accepted limitations above;
TLPM commissioning requires that only the intended meter be discoverable.
The detailed Four9 sequence follows.

1. Record the exact Git commit, ignored profile hash, maintained interpreter,
   Four9 service version, cryostat/control configuration, endpoint, approved
   0–300 K subset, socket timeout, and initial target/physical state.
2. Copy `config/profiles/phase2_lab.json` to an ignored local profile, replace
   only the Four9 endpoint, keep exactly that one device enabled, and retain
   `connect_on_start=false`.
3. Launch ZMeter, confirm the Four9 panel opens disconnected, and verify no
   unrelated optional device stack is loaded.
4. Click Connect and verify the expected service greeting/status. Close and
   correct the endpoint if it fails; do not use fallback endpoint selection.
5. Read temperature/status without changing the target.
6. Set the target equal to the already approved current target, then perform
   only one separately approved small change within experiment limits.
7. Exercise a stable wait and its Stop path; confirm the external control
   service continues its intended target.
8. Disconnect, reconnect once if approved, close the full application, and
   independently confirm the client socket is released and the cryostat/service
   remain in the intended final state.
9. Return the Startup Log, device log, service log, observed pass/fail, cleanup
   result, final state, and limitations for that exact installation.

Only after the disconnected/manual-connect run passes should a separate local
run set `connect_on_start=true`. That request is asynchronous; `Pending` in the
Startup Log means the Four9 panel must be checked for the final result.
