# Four9 Temperature Controller

## Purpose

`four9` connects ZMeter to the maintained Four9 temperature-control TCP
service. The service performs the PID control, rolling stability calculation,
and its own stability timeout. This device deliberately does not duplicate
those functions.

The default endpoint is `127.0.0.1:5050`. The widget permits changing both
values while disconnected. Commands and responses use newline-delimited UTF-8
text and one JSON response per command, as documented by the Four9 server.

## ZMeter scan channels

ZMeter discovers the following methods on `Four9.logic`:

- getter `temperature`: returns the server's latest cached controlled
  temperature in kelvin;
- setter `temperature`: sets a target and immediately refreshes the device
  widget from `GET_STATUS`;
- setter `temperature_stable`: sets a target and polls the server status at
  1 Hz until the server reports `stable=true`.

Valid targets are 0-300 K, matching the maintained server protocol. The value
0 K requests the server's documented heater-off/idle behavior.

The stable setter accepts the server flag for every documented reason,
including `normal`, `target_below_2K`, and `timeout_override`. The reason is
shown in the widget. The client has a separate two-hour safety deadline. If
that deadline expires while the server still reports unstable, it logs the
timeout, returns `False`, and permits the ZMeter scan to continue.

## Configuration

The stable-wait timeout is code-only and has no UI setting. It can be changed
after constructing the device:

```python
from devices.four9.four9_main import Four9

four9 = Four9()
four9.logic.stable_wait_timeout_s = 3 * 60 * 60
```

The normal defaults are:

- endpoint: `127.0.0.1:5050`;
- socket I/O timeout: 10 seconds;
- stable polling interval: 1 second;
- client stable-wait timeout: 7200 seconds.

## ZMeter registration

Four9 is a reviewed startup-only registry driver with stable ID `four9`. Use an
ignored local profile entry based on `config/profiles/phase2_lab.json`:

```json
{
  "id": "four9",
  "driver": "four9",
  "enabled": true,
  "connect_on_start": false,
  "connection": {
    "host": "REPLACE_LOCALLY",
    "port": 5050,
    "socket_timeout_s": 10.0
  },
  "scan_channels": {
    "set": null,
    "get": null
  }
}
```

The profile endpoint is copied into the existing panel without opening a
socket. A startup connection uses the same asynchronous logic job as the
Connect button, so the Startup Log reports pending and the panel owns the final
result and manual retry. Runtime add, manager disconnect, and removal remain
disabled pending a separate busy/lifecycle bench review.

The UI performs network work on its `Four9Logic` thread. Scan calls already
run on ZMeter's scan worker and call the same logic methods directly. The
hardware client serializes complete request/response exchanges so those paths
cannot mix socket responses. Successful scan calls emit Qt signals and update
the open device widget passively.

ZMeter scan stop and application shutdown call the widget's `force_stop` and
`terminate_dev` hooks, which interrupt a stable wait and close only the client
connection. They do not stop the Four9 server or its control service.

## Logging and failures

The widget log records connection state, stable-wait lifecycle and timeout,
server `last_error`, rejected requests, malformed responses, warnings, and
connection loss. Successful routine temperature set/read results update the
dedicated target, current-temperature, and stability fields without adding log
entries. The read-only log is approximately eight lines high by default,
remains vertically resizable, and retains the latest 500 timestamped entries
in memory. It does not add an entry for every successful 1 Hz stable poll.

A valid server `ok:false` response raises an operation error but preserves the
TCP connection. Transport errors or malformed protocol data invalidate the
connection and are reflected in the UI. A temperature read raises an error if
the server has not cached its first sample yet.

## Validation and hardware safety

Automated tests use only injected fake hardware and a local fake TCP server.
They must never point at a laboratory controller.

Run the hardware-independent checks from the repository root:

```powershell
python -B -m py_compile devices/four9/four9_hardware.py devices/four9/four9_logic.py devices/four9/four9_main.py
python -B -m unittest discover -s devices/four9/tests -p "test_*.py" -v
```

See [device_contract.md](../../documents/device_contract.md),
[hardware_safety.md](../../documents/hardware_safety.md), and
[testing.md](../../documents/testing.md).

**User-executed hardware test:** confirm the Four9 control service and cryostat
are already in a safe reviewed state; connect to the intended host and port;
read status; set the target equal to the current approved target; verify the
target, temperature, and stability fields update; then exercise a separately
approved small target change and stable wait. Confirm disconnecting ZMeter
does not stop the Four9 service or alter its active target.
