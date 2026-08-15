# Thorlabs BBD30X / DDS220 Delay Stage

## Purpose and status

This optional package controls channel 1 of a Thorlabs BBD30X benchtop
brushless-motor controller configured for a DDS220 linear delay stage. It
preserves the offline implementation's connection, motion, homing, velocity,
and readback behavior so the device can be reviewed from the main ZMeter tree.

The package has fake-driver and offscreen-GUI coverage, but it has **not** been
validated on laboratory hardware. The safety and lifecycle gaps listed below
are intentionally preserved for a later remediation pass. Do not rely on this
module for unattended motion or as an emergency-stop mechanism.

## Dependencies and configuration

- 64-bit Windows and the repository's Python 3.12/PyQt6 environment;
- NumPy;
- the optional `pythonnet` package, which provides `clr` and `System`;
- the complete matching 64-bit Kinesis 1.14.58.26351 files listed by
  `core/shared_runtime/vendor/thorlabs_kinesis/manifest.json`, including:
  - `Thorlabs.MotionControl.DeviceManagerCLI.dll`;
  - `Thorlabs.MotionControl.GenericMotorCLI.dll`;
  - `Thorlabs.MotionControl.Benchtop.BrushlessMotorCLI.dll`.

Neither `pythonnet` nor proprietary Kinesis DLLs are added to the maintained
Conda environment or Git. Copy the manifest-listed files from one reviewed
release into the ignored shared vendor folder. There is no environment,
Program Files, `PATH`, or device-local fallback. Importing the package and
constructing its widget do not import `pythonnet`, load Kinesis, build the
device list, or connect hardware. Those actions begin only after `connect()`.

The widget's serial field starts with the convenience default `103529564`.
This value does not trigger connection and an explicit `connect(serial)` value
still replaces it. Verify that the displayed serial belongs to the intended
controller before every connection; a checked-in default is not device
identity validation.

## Laboratory-profile example

Keep the controller serial in local profile configuration and inject the same
Kinesis service used by every Kinesis device:

```python
from BBD30X.BBD30X_main import BBD30X
from core.shared_runtime import RuntimeServices

services = RuntimeServices()
delay_stage = BBD30X(kinesis_runtime=services.kinesis)
delay_stage.connect("REVIEWED_SERIAL")

equips = {"Delay_Stage": delay_stage}
equips_set_channels = {"Delay_Stage": ["pos"]}
equips_get_channels = {"Delay_Stage": ["pos"]}
```

The checked-in `start_zmeter.py` intentionally remains mock-only. Keep any
additional laboratory serials in local profile configuration and do not enable
this package in the shared startup profile.

## Scan channel and units

The current ZMeter method/signature discovery exposes exactly one writable and
one readable channel:

| Channel | Method | Unit | Behavior |
| --- | --- | --- | --- |
| `pos` | `set_pos(value)` | mm | Blocking absolute move followed by tolerance-based readback |
| `pos` | `get_pos()` | mm | Returns the current channel position after a fixed read delay |

The GUI accepts and displays micrometers. It divides the GUI target by 1000
before calling the logic layer and multiplies millimeter readback by 1000 for
display. Its spin box currently allows 0 to 220,000 µm. Velocity and
acceleration fields use mm/s and mm/s².

The motion path calls Kinesis `MoveTo(target, 50000)`, then performs at most 100
additional checks with a nominal 0.1 µm (`0.0001 mm`) tolerance. Each read
contains a 0.5-second delay and each failed check adds another 0.05 seconds.
Homing calls `Home(60000)`.

## Preserved connection behavior

An explicit serial is required. Connection builds the Kinesis device list,
prints discovered serials, creates the named BBD30X controller, connects it,
selects channel 1, and waits up to 5000 ms for settings initialization.

The package first tries device motor configuration. If that call fails, it
loads Kinesis file settings, assigns `DDS220`, updates the current
configuration, and calls `SetSettings(..., True, False)`. It then starts 50 ms
polling, waits 0.3 seconds, enables the channel, and waits another 0.3 seconds.
Disconnect stops polling and disconnects the controller.

## Known safety and reliability risks

These are documented integration debt, not assurances of safe operation:

- The hardware layer does not validate finite numbers or enforce position,
  velocity, or acceleration limits. The GUI's 0–220 mm range does not constrain
  values supplied by scans or direct logic calls.
- The DDS220 fallback can apply and initialize file settings when device
  configuration loading fails. The attached stage model is not verified first.
- The alternate `connect3()` path changes homing velocity/direction and motion
  velocity/acceleration. The direction and values are not checked against the
  installed mechanism.
- `Home()` and `MoveTo()` are blocking Kinesis calls. Qt interruption requests
  cannot cancel them, and `force_stop()` does not issue a Kinesis stop command.
- `start_scan()` and `stop_scan()` are empty. They neither reserve the device
  nor establish a scan-specific safe state.
- UI work uses one mutable `job` field on a `QThread`; rapid UI actions or UI
  and scan access can conflict or overwrite pending intent.
- Failed connection now performs best-effort controller cleanup and releases
  the runtime lease; a failing vendor disconnect call can still leave physical
  controller state uncertain and requires operator verification.
- Timeout comments in the source historically disagreed with the actual
  Kinesis values. The effective calls are the values documented above.
- Device discovery enumerates and prints every returned serial number.
- Shutdown requests interruption, waits only one second, and may then
  disconnect while an operation still owns the device.
- Readback uses fixed sleeps, and the post-move verification can add substantial
  time after the blocking move has already returned.

Until these issues are remediated, mechanically constrain and supervise the
system independently of ZMeter. Software limits or the ZMeter stop button are
not substitutes for controller limits, physical clearance, or an appropriate
hardware emergency stop.

## Errors and troubleshooting

- A manifest missing/hash/size error means the ignored shared Kinesis folder is
  absent, incomplete, or does not match the tracked reviewed release.
- An `ImportError` naming `pythonnet` means the optional Python/.NET bridge is
  unavailable.
- A runtime load error after manifest validation commonly indicates incompatible
  bitness, .NET/runtime problems, missing dependent DLLs, or an incompatible
  Kinesis release.
- A move `TimeoutError` is raised when readback remains outside the tolerance
  for all additional checks. It does not prove that motion stopped.

## Hardware-independent validation

From the repository root, with the maintained environment active:

```powershell
python -B -m py_compile BBD30X\BBD30X_hardware.py BBD30X\BBD30X_logic.py BBD30X\BBD30X_main.py
python -B -m unittest discover -s BBD30X\tests -p "test_*.py" -v
```

The tests inject fake Kinesis bindings and must not load vendor DLLs or perform
device discovery.

## **User-executed hardware test**

This procedure is for the user to review and execute only after accepting the
known risks above:

1. Verify the controller and channel are a BBD30X driving the intended DDS220;
   confirm 64-bit Kinesis/pythonnet compatibility and the configured serial.
2. Mechanically clear and independently constrain the complete expected travel.
   Verify stage orientation, home direction, controller limits, units, velocity,
   acceleration, cabling, and the available physical emergency stop.
3. Connect explicitly without invoking `connect3()` or homing. Confirm the
   displayed position agrees with an independent known position.
4. Command the current position first. Observe that no unexpected motion or
   settings change occurs.
5. Make the smallest approved bounded move in each direction, verify readback
   and physical displacement, and return to the starting point.
6. If safe to do so under the controller's own protection, characterize what
   the current GUI stop does during a longer bounded move; expect it may not
   stop motion.
7. Disconnect, close ZMeter, and confirm polling, the controller handle, stage
   state, and external safety controls are in the intended state.

Do not test homing until its direction, speed, travel, and limit-switch behavior
have been separately reviewed for the installed mechanism.
