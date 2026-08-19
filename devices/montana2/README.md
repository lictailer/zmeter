# Montana Instruments Cryostat

## Purpose and status

`montana2` controls a Montana Instruments cryostat through the bundled `montana_libs` REST client. The ZMeter layer focuses on platform temperature and stability, while the hardware wrapper also contains cooldown, warmup, vent, vacuum, bakeout, purge, stage, heater, pressure, and user-sensor operations.

It is a networked real-hardware integration with no simulator or focused automated tests. Presence of an operation in the hardware wrapper does not make it an approved scan channel.

## Scan channels

Current `.logic` discovery exposes:

- getters: `platform_temperature`, `stage1_temperature`, `platform_target_temperature`, `platform_temperature_stable`;
- setters: `platform_target_temperature`, `platform_target_temperature_to_stable`.

Temperatures are in kelvin. The stable setter polls once per second, times out after 180 minutes by default, and after stability waits an additional 60-second buffer by default. The UI can change both values.

`get_stage1_temperature()` emits `sig_stage1_temperature`, but that signal is not declared in the current logic class. Treat that channel as incomplete until corrected and tested.

## Setup

- Python: PyQt6 plus the bundled client dependencies (`requests`, `paramiko`, `sshtunnel`, and related packages in the maintained environment);
- network: validated cryostat IP address and permitted lab network path;
- configuration: temperature limits, stable criteria, wait timeout, buffer, and permission for any goal/vacuum/purge operations.

Do not copy the example IP address in source into shared configuration. The widget's quick-connect values and all lab endpoints require local review.

## Lifecycle and safety

The user can request interruption of the stability wait. `terminate_dev` sets that flag, waits up to two seconds, then disconnects if connected. There are no standard `start_scan`, `stop_scan`, or `force_stop` methods, and long-running state transitions remain active on the cryostat unless explicitly handled.

Agents must not probe the IP, connect, change temperature or system goals, vent, pump, purge, read state, abort goals, or disconnect. Review the complete cryostat state machine and recovery plan in a **User-executed hardware test** before enabling. See [hardware_safety.md](../../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile devices/montana2/montana2_hardware.py devices/montana2/montana2_logic.py devices/montana2/montana2_main.py`. It does not test the bundled network client.

**User-executed hardware test:** confirm the cryostat's physical state and vendor recovery procedure; connect to the reviewed IP; read system goal/state, pressure, platform temperature, and stability; set the platform target equal to its current readback; exercise stability-wait interruption and timeout using user-approved settings; disconnect and reconnect; then verify the cryostat continues the intended goal. Cooldown, warmup, vent, vacuum, bakeout, and purge each require a separate approved procedure.
