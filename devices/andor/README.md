# Andor camera and Shamrock spectrograph

## Purpose and status

`andor` drives an Andor SDK2 camera (for example a Newton or iDus CCD) and, optionally, the Shamrock spectrograph in front of it, through pylablib. It is ported from the bench-tested Mfork `Andor/` package and reviewed against [device_contract.md](../../documents/device_contract.md). The Mfork code works on the bench; the port keeps its SDK calls and changes how they are scheduled, guarded and exposed to scans (list below).

Registry ID: `andor`. Status: **ported, not yet bench-tested in this repository** (see "User-executed hardware test").

## Requirements

- Windows with the Andor SDK2 and Shamrock DLLs installed (Andor Solis or the SDK installer).
- `pylablib==1.4.3` (pip, listed in `zmeter_Sept2026_environment.yml`).

pylablib is imported only when a device is opened, so ZMeter starts and this package imports on machines without pylablib or the SDK. Connecting without them fails with a clear error in the device log.

## Address

`<camera index>[,<spectrograph index>|none]`

| Address | Meaning |
| --- | --- |
| blank or `0,0` | camera 0 with spectrograph 0 |
| `1` | camera 1, spectrograph 0 |
| `0,none` | camera 0 only (no spectrograph; spectrum axis is the pixel index) |

The camera is required; a spectrograph that fails to open is logged and the camera stays connected. Connect is bounded by the registry timeout; a connect that finishes after the timeout disconnects itself so the SDK is not left half-open.

## Scan channels

| Channel | Direction | Units | Notes |
| --- | --- | --- | --- |
| `temperature` | get/set | °C | Set changes the cooler target (-120 to 30 °C) and does not wait for the sensor. |
| `exposure_time` | get/set | s | 1 µs to 3600 s. |
| `center_wavelength` | get/set | nm | Shamrock centre wavelength (pylablib uses metres; converted here). Changing it invalidates the cached calibration. |
| `spectrum` | get | counts | **Array getter**, 1-D, one value per pixel column. Full vertical binning and single track give one row; image and multi-track modes are summed over rows. Axis `pixel`, axis values = wavelength calibration in nm (pixel index when there is no spectrograph or calibration fails). |
| `image` | get | counts | **Array getter**, 2-D frame (axes `row`, `column`) in the current read mode. |

`temperature`, `exposure_time` and `center_wavelength` are snapshot getters: setup capture records them at scan start and end.

Each `spectrum` or `image` read is one exposure (`snap`). Array getters can only be recorded on the innermost user level; picking one adds locked fixed levels below it (one per axis). See [scan_engine.md](../../documents/scan_engine.md#array-getters). For a scalar such as the integrated intensity, record a level average of the spectrum on the next level up.

Do not change the read mode, binning or ROI during a scan: the shape is fixed when the scan starts, and a read with a different shape stops the scan with a clear error.

## Panel

The window shows the device log, connection state, cooler, exposure, acquisition and read modes, accumulation settings, and a live image/spectrum. Panel actions run as whitelisted jobs on the device thread; a new job is refused (not queued) while another runs, and all panel jobs are refused while a scan owns the device. The 5 s monitor poll pauses during a scan and resumes after it; a failing poll is logged once, not every 5 s.

## Changes from the Mfork version

1. One re-entrant SDK lock around every camera/spectrograph call (panel jobs, monitor and scan reads used to overlap).
2. `get_spectrum` returns a 1-D array and `get_image` a 2-D array, declared in `ARRAY_GETTERS`; the old `2 x N` return and `get_spectrum_mean` / `get_spectrum_sum` are removed (use a level average).
3. `get_all` renamed `monitor_poll`, so it is no longer discovered as a scan getter.
4. Wavelength calibration is cached and re-read only after centre wavelength, grating, read-mode or connection changes.
5. Centre wavelength is in nm for scans.
6. Setters take one positional value and reject non-finite or out-of-range values before any SDK call.
7. Snap timeout = 10 s + longest acquisition timing × accumulations; a snap is never retried (a retry would expose the detector again).
8. Force stop aborts only the running exposure; the camera stays connected and cooled.
9. The camera opens with `temperature=None` (cooler left as it is) instead of `"off"`, so a reconnect never switches cooling off.
10. No device enumeration in the widget constructor; counts are read when connecting.
11. Bounded connect with self-cleanup after a timeout.
12. Disconnecting below -20 °C logs a warning (Andor recommends warming up first); messages go to the shared device log.

The diagnostic scripts in the Mfork (`simple_minimal.py`, `zumeng_script.py`) stay there.

## Tests

`tests/test_andor_device.py` runs offscreen against a fake pylablib: address parsing, lazy import, getters and shapes, nm conversion and calibration caching, setter validation, snap timeout, abort, panel-job refusal during a scan, lifecycle and registration. No SDK or camera is used.

## User-executed hardware test

Run on the lab PC with the camera cooled or at room temperature, shutter closed first.

1. Connect with address `0,0`; check the device log shows camera and spectrograph info and the cooler state did not change.
2. In the panel: set exposure, snap once, start/stop live acquisition, change read mode (FVB and image).
3. Mock scan: level0 sets `exposure_time` over 3 values and records `spectrum`; confirm one fixed `pixel` level appears, its values are wavelengths in nm (compare with Solis), and each point stores one spectrum.
4. Change `center_wavelength` between two scans; confirm the axis values follow.
5. Force stop during a long exposure (10 s); the exposure aborts, the camera stays connected.
6. Record `image` in image read mode; confirm two fixed levels (`column`, `row`) and the frame plot.
7. Disconnect and reconnect while cooled; the cooler setpoint is unchanged.
