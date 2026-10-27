# Montana Instruments Cryostat

## Purpose and status

`montana2` controls a Montana Instruments cryostat through the bundled `montana_libs` REST client. The ZMeter layer focuses on platform temperature and stability, while the hardware wrapper also contains cooldown, warmup, vent, vacuum, bakeout, purge, stage, heater, pressure, and user-sensor operations.

It is a startup-only registered network integration with no simulator or device fake backend. The required profile field is `connection.address`; configuration replaces the displayed address before an optional asynchronous startup request. The panel intentionally retains `136.167.55.165` as its standalone Quick Connect default. Presence of an operation in the hardware wrapper does not make it an approved scan channel.

## Scan channels

Current `.logic` discovery exposes:

- getters: `platform_temperature`, `stage1_temperature`, `platform_target_temperature`, `platform_temperature_stable`;
- setters: `platform_target_temperature`, `platform_target_temperature_to_stable`.

Temperatures are in kelvin. The stable setter polls the platform temperature once per second, times out after 60 minutes by default, and after stability waits an additional 60-second buffer by default. The UI can change both values.

## Stability rule

The stable setter does not use the cryostat controller's stable flag, which is stricter than our measurements need. It uses the rule from the Four9 temperature-control server (`lictailer/cryo_control_Four9_QMLab`):

- keep the latest 60 valid platform readings taken since the target was set (failed reads are skipped);
- base threshold `b = sqrt(target + 100) / 50` K (about 0.20 K at 3 K, 0.24 K at 50 K, 0.40 K at 300 K);
- stable when the window is full, `|mean - target| < b x mean multiplier` and population `std < b x std multiplier`;
- targets below 3 K count as stable right away.

The multipliers default to 0.5 (mean) and 1.0 (std). Change them in the panel's **Stable Multipliers** row and press **update**; a running wait uses the new values from its next reading. They are not saved between sessions. While waiting, the log prints the window's mean offset and std against the thresholds once a minute. On timeout the wait ends without being stable and skips the buffer, as before.

The `platform_temperature_stable` getter still returns the controller's own flag.

## Setup

- Python: PyQt6 plus the bundled client dependencies (`requests`, `paramiko`, `sshtunnel`, and related packages in the maintained environment);
- network: validated cryostat IP address and permitted lab network path;
- configuration: temperature limits, stable multipliers, wait timeout, buffer, and permission for any goal/vacuum/purge operations.

Use an ignored local profile for the reviewed endpoint. The widget's retained quick-connect values and all lab endpoints require local review.

## Lifecycle and safety

The manager adapter can request interruption of the stability wait. `terminate_dev` sets that flag, waits up to two seconds, then disconnects if connected. It does not prove the worker exited before disconnecting. REST requests have no explicit timeout, scan-facing setters do not enforce the UI's 2–350 K range, and there are no device `start_scan` or `stop_scan` hooks. These are accepted registration limitations and remain future work.

Agents must not probe the IP, connect, change temperature or system goals, vent, pump, purge, read state, abort goals, or disconnect. Review the complete cryostat state machine and recovery plan in a **User-executed hardware test** before enabling. See [hardware_safety.md](../../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile devices/montana2/montana2_hardware.py devices/montana2/montana2_logic.py devices/montana2/montana2_main.py`. It does not test the bundled network client.

**User-executed hardware test:** confirm the cryostat's physical state and vendor recovery procedure; connect to the reviewed IP; read system goal/state, pressure, platform temperature, and stability; set the platform target equal to its current readback; run the stable setter at a target above 3 K and confirm the once-a-minute log values and the stable decision look right, press **update** with new multipliers during the wait, and exercise stability-wait interruption and timeout using user-approved settings; disconnect and reconnect; then verify the cryostat continues the intended goal. Cooldown, warmup, vent, vacuum, bakeout, and purge each require a separate approved procedure.
