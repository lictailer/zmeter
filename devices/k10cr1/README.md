# Thorlabs K10CR1 Rotation Mount

## Purpose and status

This package controls a Thorlabs K10CR1 integrated rotation mount through the Kinesis C API. Its existing C structures and command surface are retained, but native function resolution now uses the injected shared `KinesisRuntime`. The current stop behavior remains incomplete, so it must not be treated as production-ready without corrective work and a user-run bench review.

Importing the module or constructing the widget does not load a DLL or discover devices. Lazy proxies resolve against `core/shared_runtime/vendor/thorlabs_kinesis/` only during explicit connection. K10CR1 and BBD30X must receive the same `RuntimeServices.kinesis` instance.

## Scan channels

Current `.logic` discovery exposes:

- `set_angle(value)`: absolute angular target in degrees;
- `get_angle()`: current position converted to degrees.

The conversion uses 49,152,000 device counts per 360 degrees. The setter applies modulo-one-turn completion logic and polls until repeated completion, a stuck-position condition, or an iteration cap. No software angular limits are enforced in this package.

## Setup

- Python: PyQt6;
- system: Thorlabs Kinesis runtime/driver matching process bitness;
- native libraries: the complete tracked, manifest-verified Kinesis
  1.14.58.26351 set in the shared vendor folder;
- configuration: exact device serial, homing policy, allowed angular range, velocity, acceleration, and experiment-specific collision constraints.

The first K10CR1 connection for a shared Kinesis runtime builds the native
DeviceManager list once. Later connections open the requested serial directly.
If opening fails, K10CR1 performs one serialized DeviceManager refresh and
retries the same serial once; it does not enumerate or select another device.
After opening, it reads hardware information and overwrites velocity
parameters. Homing and movement are blocking polling operations executed in
the device thread.

Profile construction:

```python
from core.shared_runtime import RuntimeServices
from devices.k10cr1.k10cr1_main import K10CR1

services = RuntimeServices()
mount = K10CR1(services.kinesis)
mount.connect("REVIEWED_SERIAL")
```

The widget includes a read-only device log for connection state, device
identity, home/stop lifecycle, stuck or iteration-limit warnings, and errors.
Successful position samples and raw vendor return codes are not logged. The log
is approximately eight lines high by default, remains vertically resizable,
and retains the latest 500 timestamped entries in memory.

## Lifecycle and safety gaps

The logic contains an immediate-stop call, but its own comment says it does not work. The widget's `force_stop()` is empty. `terminate_dev()` now disconnects an active session and releases its runtime lease, but there are no `start_scan`/`stop_scan` hooks.

Before enabling the module, implement and simulate bounded stop, idempotent disconnect, shutdown cleanup, range validation, and last-confirmed-position reporting. Agents must not load/run Kinesis discovery, open a mount, home, change velocity, move, stop, or disconnect it. See [hardware_safety.md](../documents/hardware_safety.md).

## Validation

Hardware-independent syntax and fake-runtime checks cover import/widget side effects, lazy binding, discovery failure, and lease cleanup. They do not load Kinesis or access hardware.

No production bench test should be run until `force_stop` and termination are fixed. After that, the **User-executed hardware test** is: mechanically clear the full allowed travel; verify serial and limits; connect without homing; compare `get_angle()` to the mount; command the current angle; move +1 degree and back within approved limits; interrupt a longer bounded move; verify the last position; disconnect; and confirm the mount and Kinesis handle are released. Homing requires a separate user-reviewed procedure.
