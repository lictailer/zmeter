# Device Integration Contract

## Purpose

A device package adapts one instrument or simulator to ZMeter without leaking vendor-specific behavior into core scan code. Use `mockDevice/` as the executable reference. `demoDevice/` is historical/template evidence only until reconciled with this contract and current tests.

## Package layout and ownership

The conventional layout is:

```text
<device>/
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

## Signals and threads

- Widget mutation occurs on the Qt UI thread through signals/slots.
- Device I/O, ramps, polling, waits, and reconnect attempts must not block the UI thread.
- Serialize access to transports that cannot safely accept concurrent UI, monitor, scan, or router operations.
- A long operation must have a bounded stop path and publish the actual completed state, especially after a partial ramp.
- Exceptions must preserve context and reach the UI/scan controller; do not silently convert an uncertain hardware state into success.

## Lifecycle contract

An active device widget should provide the following where applicable:

| Method | Required behavior |
| --- | --- |
| `connect(...)` | Validate configuration, establish one connection, and report actual connected state |
| `disconnect()` | Stop device activity as needed and release the connection idempotently |
| `start_scan()` | Prepare for scan use and clear only stale stop state that is safe to clear |
| `stop_scan()` | Stop monitoring/background activity that could contend with scanning; do not necessarily disconnect |
| `force_stop()` | Promptly request interruption of active ramp/write/operation and preserve the last confirmed state |
| `terminate_dev()` | Final teardown: stop workers, release resources, and disconnect |
| `close()` | Widget close may hide the window; application shutdown must still call final teardown |

`MainWindow` calls `stop_scan()` before a scan, `start_scan()` after scan cleanup, `force_stop()` on scan stop/shutdown, and `terminate_dev()` followed by `close()` on confirmed application exit. Methods should be safe when disconnected, partially initialized, already stopped, or called more than once.

## Cross-device commands

Direct imports or references between device modules are forbidden. Accept router injection through `configure_command_router(router, source_device=...)` when custom setup is needed, or use the injected `command_router`/`device_label` metadata. Prefer `DeviceCommandClient` for asynchronous catalog/read/write requests and correlate responses by request ID.

Router availability does not bypass device validation. A target write still travels through `MainWindow.write_info()` and its configured global range checks.

## Dependencies and configuration

- Guard optional vendor imports so mock-only and unrelated-device use can start without every driver installed.
- Separate Python packages from system drivers, SDKs, DLLs, bitness requirements, and environment variables in the device README.
- Keep VISA resources, NI device names, serials, calibration paths, lab limits, and backup paths in startup/profile or device configuration—not shared core code.
- Never commit credentials, private endpoints, or redistributable vendor binaries without an explicit policy decision.
- Fail with a precise dependency/configuration error; do not silently select another real resource.

## Registration checklist

1. Add the package with widget, logic, hardware, optional UI, and device-local README.
2. Verify getter/setter signatures and units; ensure helpers are not accidentally discovered.
3. Define connect/disconnect, scan start/stop, force stop, termination, and partial-failure behavior.
4. Make optional imports safe when the device is not enabled.
5. Register a stable label and constructor in a lab startup/profile; add exact address/configuration locally.
6. Add channel filters only when that profile needs a subset.
7. Review `scan_range_limits.json` and device-local limits for matching labels, channels, units, and precedence.
8. Use the router for any cross-device operation.
9. Validate with mocks/unit/offscreen GUI before proposing a user-executed bench procedure.
10. Update environment, safety, structure, and device documentation where affected.

## Minimum validation

- **Static:** compile changed Python; parse/load changed UI XML; verify optional imports fail clearly.
- **Unit/mock:** discovery exposes exactly intended signatures; disconnected calls fail safely; finite/range checks preserve state; connect/disconnect are repeatable; fault/timeout paths propagate; ramps stop at the last completed point.
- **Offscreen GUI:** widget loads, signals update state, long work does not block UI, closing/reopening does not accidentally disconnect if hide-on-close is intended, and `terminate_dev()` releases resources.
- **Integration simulation:** scan start/stop, grouped operations, router catalog/read/write, and shutdown work with simulated transports.
- **Hardware bench:** user only. Include controlled connection, read, bounded write/ramp, timeout, stop/abort, disconnect, and post-test safe-state checks in the device README.

Agents must never execute real-device discovery, connection, configuration, reads/writes, reset, disconnect, or bench tests. Label the exact proposed procedure **User-executed hardware test**.

