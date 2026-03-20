# Device Command Bus Guide

## What This Feature Adds

The new command bus lets one device talk to another device through `MainWindow` instead of directly reaching into another widget or logic object.

This solves the original problem:

- a device only knows itself
- `MainWindow` knows every device
- so `MainWindow` becomes the router

The bus is intentionally small in v1. It supports only:

- `read`
- `write`
- `list_catalog`

It is also intentionally safe:

- requests are validated before execution
- invalid requests return structured errors
- commands are not queued
- commands are not force-executed

## Files Added Or Changed

- `core/device_command_router.py`
- `core/mainWindow.py`
- `test_device_command_bus.py`

## High-Level Flow

### 1. Startup

When `MainWindow` starts, it now:

1. builds the equipment setter/getter dictionaries
2. adds pseudo-devices like `default` and `artificial_channel`
3. creates `self.command_router`
4. injects `command_router` and `device_label` into each equipment and each `.logic`
5. builds a lightweight device catalog

That means every device can later use the same router object.

### 2. A device sends a request

A device sends a request through `DeviceCommandClient` or directly through:

```python
self.command_router.sig_command_requested.emit(payload)
```

The payload is a Python dict with this shape:

```python
{
    "request_id": "abc-123",
    "source_device": "feature_0",
    "action": "write",          # "read" | "write" | "list_catalog"
    "target_device": "nidaq_0",
    "channel": "AO0",
    "value": 0.25,
}
```

### 3. The router validates the request

The router checks:

- required keys exist
- `source_device` is present
- action is one of the supported values
- target device exists for `read` and `write`
- channel exists in the readable or writable list
- `write` includes a non-null value

If anything is wrong, the router does not execute the command. It emits a structured error response instead.

### 4. The router executes through `MainWindow`

If the request passes validation:

- `read` calls `MainWindow.read_info(f"{target_device}_{channel}")`
- `write` calls `MainWindow.write_info(value, f"{target_device}_{channel}")`
- `list_catalog` returns the current catalog

This is important: the new bus does not create a second device-control path. It reuses the existing `read_info` and `write_info` path.

### 5. The router emits a response

Every request returns a response dict like:

```python
{
    "request_id": "abc-123",
    "ok": True,
    "action": "write",
    "source_device": "feature_0",
    "target_device": "nidaq_0",
    "channel": "AO0",
    "value": 0.25,
    "catalog": None,
    "error_code": None,
    "error_message": None,
}
```

If the request fails, `ok` is `False` and `error_code` / `error_message` are filled.

## Detailed Explanation Of The New Code

## `core/device_command_router.py`

### `DeviceCommandRouter`

This is the main router object.

#### Signals

- `sig_command_requested(object)`
  - devices emit request dicts here
- `sig_command_responded(object)`
  - router emits the result here
- `sig_catalog_changed(object)`
  - router emits the latest catalog when the catalog changes

#### `__init__(self, main_window, parent=None)`

Purpose:

- stores the `MainWindow` reference
- connects `sig_command_requested` to `_handle_request`

Important detail:

- the connection is `QueuedConnection`
- this means the request is delivered through Qt's event system
- this is safer for cross-thread communication than calling the slot directly

#### `_handle_request(self, request)`

Purpose:

- receives one request
- forwards it to `route_command`
- emits the returned response

This keeps the public signal entry point separate from the actual validation and execution logic.

#### `route_command(self, request)`

This is the real command-processing function.

It does the following, in order:

1. makes sure the payload is a dict
2. makes sure all required keys exist
3. validates `source_device`
4. validates the action
5. asks `MainWindow` for the latest catalog
6. if action is `list_catalog`, returns the catalog immediately
7. for `read` and `write`, validates device and channel
8. for `write`, checks that `value` is not `None`
9. builds the full channel name `target_device + "_" + channel`
10. executes with `MainWindow.read_info(...)` or `MainWindow.write_info(...)`
11. catches exceptions and converts them to structured error responses

Why this design is useful:

- one function contains all routing policy
- every device follows the same rules
- errors are explicit and machine-readable

#### `publish_catalog(self, catalog)`

Purpose:

- emits the newest catalog through `sig_catalog_changed`

Why this matters:

- device UIs can refresh their dropdown lists when the available channels change
- this is especially useful for `artificial_channel`, whose names can be reconfigured at runtime

#### `_make_success_response(...)` and `_make_error_response(...)`

These helper functions keep the response format consistent.

That consistency matters because every future device can parse the same fields:

- `ok`
- `value`
- `catalog`
- `error_code`
- `error_message`

### `DeviceCommandClient`

This is a convenience wrapper for devices.

Instead of building request dicts manually every time, a device can use:

- `request_catalog()`
- `request_read(...)`
- `request_write(...)`

#### Why this helper exists

- generates `request_id` automatically if needed
- tracks pending requests
- only forwards back responses that belong to that device's request ids
- re-emits `sig_catalog_changed`

#### `send_request(...)`

This is the core helper method.

It:

1. creates a `request_id` if needed
2. stores the request id in `_pending_request_ids`
3. emits the request dict through the router signal
4. returns the request id so the caller can track it if needed

#### `_handle_response(self, response)`

This function filters responses:

- if the response `request_id` is not in `_pending_request_ids`, it ignores it
- if it matches, it removes it from `_pending_request_ids`
- then it emits `sig_response`

This prevents one device from accidentally treating another device's response as its own.

## `core/mainWindow.py`

### New startup logic in `__init__`

These lines are the main integration point:

```python
self.command_router = DeviceCommandRouter(main_window=self, parent=self)
self.inject_command_router_metadata()
self.refresh_device_catalog()
```

What they do:

- create the router
- give each device access to the router
- publish the catalog immediately

### `update_artificial_channel_scan_info(self)`

Before this change, `artificial_channel` was mainly handled in special scan logic.

Now this function also registers artificial-channel read and write callables into:

- `self.setter_equipment_info_for_scanning`
- `self.getter_equipment_info_for_scanning`

That means `artificial_channel` now works through the same `write_info` / `read_info` routing path as normal devices.

### `setup_default_channel_info(self)`

This now explicitly registers:

- writable default channels: `wait`, `count`
- readable default channels: none

That keeps the catalog honest. `default` is write-only, so the catalog should say that.

### `on_artificial_channel_config_applied(self)`

This function already updated scan UI state.

Now it also:

- rebuilds the catalog
- emits `sig_catalog_changed`

So if a user renames `n` / `E` to something else, devices listening to the catalog will see the update.

### `make_variables_dictionary(self, equipment)`

This function used to register every `.logic.get_*` and `.logic.set_*` method by name only.

That was risky because some devices have methods that do not match the standard scan-style contract.

Now it first validates method signatures.

#### Getter rule

Getter must look like:

```python
def get_xxx(self):
    ...
```

In other words:

- no extra positional arguments
- no `*args`

#### Setter rule

Setter must look like:

```python
def set_xxx(self, value):
    ...
```

In other words:

- exactly one positional input after binding
- no `*args`

Why this matters:

- the bus needs a predictable contract
- the scan engine also expects a simple channel-based interface
- non-standard methods should stay hidden until adapted

### `_is_valid_getter`, `_is_valid_setter`, `_safe_signature`

These helper functions use `inspect.signature(...)` to decide whether a method matches the standardized interface.

This gives a clean rule:

- if a method is compatible, expose it
- if not, do not expose it

### `build_device_channel_catalog(self)`

This creates the lightweight catalog:

```python
{
    "device_name": {
        "readable": [...],
        "writable": [...],
    }
}
```

This catalog is intentionally simple in v1:

- only names
- split by readable vs writable
- no units
- no limits
- no command descriptions

### `refresh_device_catalog(self)`

This function:

1. rebuilds `self.device_channel_catalog`
2. publishes it through the router if the router exists

This is the one function to call whenever available channels change.

### `get_device_channel_catalog(self)`

This returns a deep copy of the catalog.

Why a deep copy:

- callers can inspect it
- callers cannot accidentally mutate `MainWindow`'s internal state

### `inject_command_router_metadata(self)`

This function loops over all real devices and injects:

- `device_label`
- `command_router`

into:

- the equipment widget
- the `.logic` object, if present

It also injects the same metadata into `artificial_channel_logic`.

Why this is useful:

- future devices do not need to search for `MainWindow`
- `MainWindow` gives each device the shared router once at startup

### `write_info(self, val, master)`

This function already existed, but it is more strict now.

Current logic:

1. ignore `NaN`
2. find the target device by prefix match
3. extract the channel name
4. call the registered setter
5. raise a `KeyError` if no device matches

The new `KeyError` is important because the router depends on it. If something is wrong, the router should receive a real exception and convert it into a structured error response.

### `_is_nan_value(self, value)`

This helper safely checks for `NaN` without crashing on non-numeric values.

That is safer than calling `np.isnan(value)` directly everywhere.

### `read_info(self, slave)`

This also became more explicit:

1. returns `np.nan` for `"none"`
2. routes by device prefix
3. extracts the channel
4. calls the getter
5. raises `KeyError` if the device or variable does not exist

Again, that explicit failure behavior is important for the router.

## Why The Design Looks Like This

### Why use `MainWindow` as the router?

Because `MainWindow` already owns:

- all devices
- all channel discovery
- the read/write path used by scans

So it is already the natural control center.

### Why keep only `read`, `write`, and `list_catalog` in v1?

Because those three operations are already well-defined in the current architecture.

If we also added:

- `connect`
- `disconnect`
- `reset`
- `auto_phase`
- custom workflows

then we would need a much bigger registration system and a lot more safety logic.

This v1 builds the foundation first.

### Why validate method signatures?

Because not every method that starts with `get_` or `set_` is truly scan-compatible or bus-compatible.

The router needs a standard interface.

If a method is not standard, it should be adapted first rather than exposed automatically.

### Why keep the catalog lightweight?

Because the first need was selection and routing:

- what device exists?
- what can I read?
- what can I write?

That is enough for dropdown menus and cross-device communication.

Units, limits, and richer metadata can come later.

## Short Demo: How To Add A New Device That Uses The Bus

This is a minimal example for a new feature-device.

## Step 1. Expose normal scan channels in `.logic`

If the device should appear in scan setter/getter menus, its logic must expose standard methods:

```python
class MyFeatureLogic(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self._gain = 1.0

    def set_gain(self, value):
        self._gain = float(value)

    def get_gain(self):
        return self._gain
```

Because the method names and signatures are standard, `MainWindow` will automatically include them in the catalog.

## Step 2. Use the injected router from the widget

After `MainWindow` is created, it injects:

- `self.command_router`
- `self.device_label`

into the device widget and its logic.

So in the device widget, create the client lazily:

```python
from PyQt6 import QtCore, QtWidgets
from core.device_command_router import DeviceCommandClient


class MyFeatureDevice(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self._bus_client = None

    def _client(self):
        if self._bus_client is None:
            if not hasattr(self, "command_router"):
                raise RuntimeError("command_router has not been injected by MainWindow yet.")
            self._bus_client = DeviceCommandClient(
                self.command_router,
                self.device_label,
                parent=self,
            )
            self._bus_client.sig_response.connect(self._handle_bus_response)
            self._bus_client.sig_catalog_changed.connect(self._handle_catalog_changed)
        return self._bus_client
```

## Step 3. Ask for the available devices and channels

```python
    def refresh_remote_choices(self):
        self._client().request_catalog()

    def _handle_catalog_changed(self, catalog):
        print("Catalog changed:", catalog)
```

The catalog will look like:

```python
{
    "nidaq_0": {"readable": ["AI0"], "writable": ["AO0", "AO1"]},
    "Keithley_0": {"readable": ["current"], "writable": ["direct_source_voltage"]},
}
```

You can use that to populate dropdown menus.

## Step 4. Write to another device

```python
    def move_nidaq_x(self, value):
        self._client().request_write("nidaq_0", "AO0", value)
```

## Step 5. Read from another device

```python
    def read_keithley_current(self):
        self._client().request_read("Keithley_0", "current")
```

## Step 6. Handle the responses

```python
    def _handle_bus_response(self, response):
        if not response["ok"]:
            print("Bus error:", response["error_code"], response["error_message"])
            return

        if response["action"] == "list_catalog":
            catalog = response["catalog"]
            print("Available devices:", catalog.keys())

        elif response["action"] == "read":
            print("Read value:", response["value"])

        elif response["action"] == "write":
            print("Write finished:", response["target_device"], response["channel"])
```

## Very Short Mental Model

Think of the system like this:

- device asks `MainWindow` to do something
- `MainWindow` checks whether it is valid
- `MainWindow` executes using the normal channel path
- `MainWindow` sends back the result

So the device never needs to know where another device lives in memory. It only needs:

- target device name
- channel name
- action
- optional value

## Current Limitations

This v1 does **not** yet support:

- custom commands beyond `read`, `write`, `list_catalog`
- automatic blocking wait-for-reply helpers
- richer metadata like units and limits
- direct scan-engine migration onto the new bus

Those can be built later on top of this foundation.

## Recommended Rule For Future Devices

If a new device should:

- appear in scan menus: add standard `get_*` / `set_*`
- talk to other devices: use `DeviceCommandClient`
- update its UI when available channels change: listen to `sig_catalog_changed`

That will keep new devices consistent with the architecture introduced here.
