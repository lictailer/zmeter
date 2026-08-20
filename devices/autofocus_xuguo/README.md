# Autofocus XZ and Autoposition XY

## Purpose and status

This package combines two coordination paths:

- XY autoposition drives two scan channels through ZMeter's device command router, reads a routed reference channel, maps a square grid, and estimates image offset by phase correlation;
- Z autofocus drives an Arduino stepper over serial, reads a routed reference channel, performs coarse/fine height scans, and fits a Gaussian peak.

It is the most complete autofocus implementation in the tree, but it remains hardware-facing and has no focused automated tests or recorded bench-validation matrix. Long UI actions currently run synchronously and call `processEvents`; they can occupy the Qt UI thread and should be moved to a worker before production use.

## Router and hardware configuration

The widget accepts the shared command router and uses the catalog to select X output, Y output, XY reference, and Z reference channels. This avoids direct imports of other device modules. Router writes still pass through ZMeter's configured global output limits.

The stepper defaults are COM7, 115200 baud, 0.2 s read polling, 120 s command timeout, and a 2 s startup delay. Connection performs a `PING`/`OK PONG` handshake. Height conversion defaults to 500 micrometers of translator travel per revolution and a `100/30` motor-to-translator gear ratio. All of these values require lab-specific verification.

## Scan discovery

Current exact setter signatures expose:

- `x_with_offset`, `y_with_offset`, and `z_with_offset` for logical positions;
- `autoposition` and `autofocus_abs_maximum` as numeric triggers or JSON/dictionary setting updates.

`set_autoposition` requires a loaded reference map. Default XY settings are a 0.1-unit span, 51 points per line, zero settle time, 0.6 quality threshold, and 20x registration upsampling. Default Z search limits are -20 to +20 micrometers with 1 micrometer coarse steps, 0.5 micrometer fine steps, and 0.1 s settling.

Discovery also finds `get_available_channels()` and `get_report_paths()`. Both return dictionaries rather than numeric measurement scalars and must be filtered from scan acquisition.

## Coordinates, outputs, and recovery

Logical XY/Z values add stored offsets before reaching physical outputs. “Offset home” moves logical coordinates to zero; “absolute home” moves the underlying physical axes to zero. Zeroing and homing have materially different meanings and must be reviewed before use.

The package writes mapping JSON, offset-history CSV, status logs, and `autoposition_report.pptx`/`autofocus_report.pptx` below the configured save path. Treat these as measurement records and verify filenames, failure handling, and recovery.

The stop request is polled by mapping/focus helpers, but the widget has no standard `start_scan`, `stop_scan`, or `force_stop`, and `terminate_dev` disconnects without first requesting an active operation to stop. Review partial motion, partial maps, router failures, timeout, and teardown before enabling it.

Agents must not enumerate serial ports, open the Arduino, move/home/zero any axis, route real-device reads/writes, acquire a map, or run autofocus/autoposition. See [device_contract.md](../../documents/device_contract.md), [data_format.md](../../documents/data_format.md), and [hardware_safety.md](../../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile devices/autofocus_xuguo/autofocusXZ_hardware.py devices/autofocus_xuguo/autofocusXZ_logic.py devices/autofocus_xuguo/autofocusXZ_main.py devices/autofocus_xuguo/autopositionXZ_helpers.py`. Algorithm tests should inject simulated router and stepper transports and write only to a temporary directory; none are present yet.

No production bench test should run until long work is moved off the UI thread and shutdown is made coherent. After that, the **User-executed hardware test** is: mechanically clear and limit all axes; connect the explicit stepper port and verify the handshake/current position; route X/Y and reference channels with restrictive limits; command current positions first; make one small approved X, Y, and Z move; acquire a minimal 3-by-3 reference/current map; stop during a second map; verify offsets and partial output files; perform a bounded Z profile without applying a fitted move; terminate; and confirm all routed devices and the serial port remain in their intended states.
