# Device Integration Contract

## Purpose

A device package adapts one instrument or simulator to ZMeter without leaking vendor-specific behavior into core scan code. Use `devices/mockDevice/` as the executable reference. `devices/demoDevice/` is historical/template evidence only until reconciled with this contract and current tests.

## Package layout and ownership

The conventional layout is:

```text
devices/<device>/
  __init__.py
  <device>_main.py       # QWidget/operator interface
  <device>_logic.py      # scan-facing API and coordination
  <device>_hardware.py   # transport/vendor I/O
  <device>.ui            # optional Qt Designer UI
  README.md              # device-specific setup, channels, limits, bench procedure
```

Equivalent names are acceptable when the separation is clear. Keep responsibilities strict:

- widget/main: UI state, input validation, buttons, and signal-to-widget updates;
- logic: public scan channels, lifecycle coordination, safe worker jobs, and status/error signals;
- hardware: connection, commands, units, limits, timeouts, low-level stop, and cleanup.

## Scan channel discovery

`MainWindow` inspects the device instance's `.logic` object. A scan-visible method must be callable and match exactly:

```python
def get_channel_name(): ...       # bound method: zero positional arguments
def set_channel_name(value): ...  # bound method: one positional argument
```

Variadic positional signatures are not exposed. The part after `get_` or `set_` is the channel name. Full runtime names are `<registered_device_label>_<channel>`; the registered label may contain underscores.

Do not expose helper/control methods with these prefixes unless they are valid scan channels. Return a numeric/scalar value suitable for NumPy storage, or explicitly coordinate any broader data contract. Setters must validate units, finite values, and permitted range before hardware action.

The startup profile may supply setter/getter allowlists. `None` exposes all valid methods; unknown requested names are ignored. Support profile filtering rather than removing useful public methods for one lab.

Runtime catalog changes are definition preserving. A device or channel must not
be removed from the active session while it is referenced by an executable
available/queued/manual/active scan configuration, detached queue worker, an
artificial-channel configuration, or a device-owned reference. Completed Past
items and the available-scan template are retained for diagnostics but do not
block removal. Core code must not rename, clear, or substitute stored channels.

## Signals and threads

- Widget mutation occurs on the Qt UI thread through signals/slots.
- Device I/O, ramps, polling, waits, and reconnect attempts must not block the UI thread.
- Serialize access to transports that cannot safely accept concurrent UI, monitor, scan, or router operations.
- A long operation must have a bounded stop path and publish the actual completed state, especially after a partial ramp.
- Exceptions must preserve context and reach the UI/scan controller; do not silently convert an uncertain hardware state into success.
- A registration marked `runtime_mutation_allowed=True` must provide a fast,
  side-effect-free, reviewed `is_busy(instance)` probe covering every
  device-owned worker, ramp, discovery, monitor, and other operation that would
  make disconnect/removal unsafe. A missing or failed probe must fail closed.

## Device logs

Every active device widget should provide an operator-facing device log. Use
the shared `core.device_log` presentation helper where practical so logs are
read-only, timestamped with severity, auto-scrolling, limited to 500 in-memory
entries, approximately eight lines high by default, and vertically resizable.

Log connection and disconnection, errors, warnings, and important device or
lifecycle events. Routine successful set/read results, raw successful vendor
return codes, and repeated polling samples normally belong in dedicated UI
fields or signals rather than the log. Device logs remain in memory unless a
separate persistence requirement is explicitly approved.

## Lifecycle contract

An active device widget should provide the following where applicable:

| Method | Required behavior |
| --- | --- |
| `connect(..., timeout_ms)` | Complete within the positive reviewed timeout and return literal `True` only after one connection succeeds |
| `disconnect()` | Stop device activity as needed and release the connection idempotently |
| `start_scan()` | Prepare for scan use and clear only stale stop state that is safe to clear |
| `stop_scan()` | Stop monitoring/background activity that could contend with scanning; do not necessarily disconnect |
| `force_stop()` | Promptly request interruption of active ramp/write/operation and preserve the last confirmed state |
| `terminate_dev()` | Final teardown: stop workers, release resources, and disconnect |
| `close()` | Widget close may hide the window; application shutdown must still call final teardown |

`MainWindow` delegates these actions through `DeviceManager`. Scan preparation
and cleanup retain their existing calling threads. Scan-specific stop, force-stop,
and restart calls are filtered to the immutable physical-device set used by that
scan; `None` retains the all-device compatibility behavior, and application
shutdown continues to force-stop and tear down every device. Missing optional
scan hooks are successful no-ops. Runtime connect, disconnect,
force-stop, stop-scan, and termination callbacks run on manager lifecycle
workers and must not mutate a `QWidget` directly; publish UI changes through
signals. Final widget `close()` and `deleteLater()` remain on the manager's Qt
UI-owner thread. Methods should be safe when disconnected, partially
initialized, already stopped, or called more than once. The manager preserves
one-attempt termination/close errors and will not release shared runtimes after
uncertain cleanup.

The reviewed registry supplies a 10,000 ms connection timeout by default. A
connection result other than literal `True` is failure. When an `is_connected`
probe is registered, it must also report true before the manager publishes the
device as connected. An asynchronous widget method must therefore be wrapped by
a bounded adapter that waits for its completion result; merely scheduling work
is not successful connection. The manager does not force-kill vendor threads.

Runtime mutation eligibility is a separate code-review decision from startup
registration. Before enabling it, the adapter must define coherent
add/connect/disconnect/remove behavior, the busy probe above, bounded stop and
termination behavior, reversible router attachment, and complete stored catalog
reference reporting. The checked-in registry currently enables runtime mutation
only for the mock driver; real drivers require separate user-executed bench
review after these contracts are satisfied.

## Cross-device commands

Direct imports or references between device modules are forbidden. Accept router injection through `configure_command_router(router, source_device=...)` when custom setup is needed, or use the injected `command_router`/`device_label` metadata. Prefer `DeviceCommandClient` for asynchronous catalog/read/write requests and correlate responses by request ID.

If `configure_command_router(...)` creates clients, signal connections, or other
state, the device must also provide an idempotent `detach_command_router()` that
closes those clients and reverses the attachment. A driver with additional
stored cross-device selections must expose them through its reviewed catalog
reference provider before runtime removal can be enabled for that driver.

A composite device may expose `command_router_children()` so catalog rollback
can checkpoint and detach its full object graph. When an object implements
`configure_command_router(...)`, that hook owns router injection for all of its
descendants; core does not call child configure hooks again. Core still walks
`command_router_children()` while capturing and detaching state, so every
`detach_command_router()` in the graph must be safe when called repeatedly.

A registered device that stores cross-device selections must implement
`find_catalog_references(*, removed_setters, removed_getters,
removed_device_labels)`. It returns stable, human-readable descriptions for
every stored reference intersecting those full-channel or exact-label sets.
The hook must be side-effect free and include unresolved selections associated
with a removed device, not only channels currently exported by the catalog.

Router availability does not bypass device validation. A target write still travels through `MainWindow.write_info()` and its configured global range checks.

## Dependencies and configuration

- Guard optional vendor imports so mock-only and unrelated-device use can start without every driver installed.
- Separate Python packages from system drivers, SDKs, DLLs, bitness requirements, and environment variables in the device README.
- Keep VISA resources, NI device names, serials, calibration paths, lab limits, and backup paths in startup/profile or device configuration—not shared core code.
- Never commit credentials, private endpoints, or redistributable vendor binaries without an explicit policy decision.
- Fail with a precise dependency/configuration error; do not silently select another real resource.
- When a startup-only driver retains panel-driven connection, its reviewed
  `configure_instance(instance, connection)` hook may copy the validated
  address/device name/serial into existing UI controls on the owner thread. It
  must not import a vendor runtime, enumerate, connect, or perform device I/O.
- A registration that supports profile startup supplies a separate
  `startup_connect(instance, connection, timeout_ms)` callback. `True` means a
  confirmed synchronous connection, `False` means immediate failure, and
  `None` means an existing asynchronous request was accepted. Profile startup
  catches per-device construction and connection failures and continues in
  order. The strict `connect` callback used by runtime add remains transactional
  and is not replaced by this best-effort path.

## Registration checklist

1. Add the package with widget, logic, hardware, optional UI, and device-local README.
2. Verify getter/setter signatures and units; ensure helpers are not accidentally discovered.
3. Define connect/disconnect, scan start/stop, force stop, termination, and partial-failure behavior.
4. Make optional imports safe when the device is not enabled.
5. Register a stable driver ID and constructor, then select stable instance labels and exact connection configuration in a local startup profile.
6. Add channel filters only when that profile needs a subset.
7. Review `scan_range_limits.json` and device-local limits for matching labels, channels, units, and precedence.
8. Use the router for any cross-device operation.
9. Leave runtime mutation disabled unless the busy, lifecycle-worker,
   reference-provider, and router-detach contracts above have been reviewed and
   tested explicitly.
10. Validate with mocks/unit/offscreen GUI before proposing a user-executed bench procedure.
11. Update environment, safety, structure, and device documentation where affected.

## Minimum validation

- **Static:** compile changed Python; parse/load changed UI XML; verify optional imports fail clearly.
- **Unit/mock:** discovery exposes exactly intended signatures; disconnected calls fail safely; finite/range checks preserve state; connect/disconnect are repeatable; fault/timeout paths propagate; ramps stop at the last completed point.
- **Offscreen GUI:** widget loads, signals update state, long work does not block UI, closing/reopening does not accidentally disconnect if hide-on-close is intended, and `terminate_dev()` releases resources.
- **Integration simulation:** scan start/stop, grouped operations, router catalog/read/write, and shutdown work with simulated transports.
- **Hardware bench:** user only. Include controlled connection, read, bounded write/ramp, timeout, stop/abort, disconnect, and post-test safe-state checks in the device README.

Agents must never execute real-device discovery, connection, configuration, reads/writes, reset, disconnect, or bench tests. Label the exact proposed procedure **User-executed hardware test**.

