# Thorlabs BBD30X / DDS220 Delay Stage

## Purpose and status

This optional package controls channel 1 of a Thorlabs BBD30X benchtop
brushless-motor controller configured for a DDS220 linear delay stage. It
supports guarded asynchronous UI jobs, unit-aware scan channels, session T0
delay coordinates, move-loop position updates, and an embedded device log.

The package has fake-driver and offscreen-GUI coverage but has **not** been
validated on laboratory hardware. Mechanically constrain and supervise the
stage independently of ZMeter. Software limits and the ZMeter stop button are
not substitutes for controller limits, physical clearance, or a hardware
emergency stop.

It is registered under driver ID `bbd30x` with required connection field
`serial`. For first commissioning keep `connect_on_start=false`; a later
reviewed startup request queues the existing asynchronous panel connection and
reports pending without waiting for completion. The panel remains authoritative
for the final result and manual retry. The adapter injects
`RuntimeServices.kinesis`; runtime mutation remains disabled.

## Dependencies and configuration

- 64-bit Windows and the repository's Python 3.12/PyQt6 environment;
- the optional pythonnet package, which provides clr and System;
- the complete matching 64-bit Kinesis files listed by
  core/shared_runtime/vendor/thorlabs_kinesis/manifest.json.

The Kinesis runtime remains lazy. Importing the package and constructing its
widget do not import pythonnet, load Kinesis, build the device list, or connect
hardware. These operations start only after connect().

The serial field contains the convenience value 103529564, but this is not
device identity validation. Keep the reviewed controller serial in local lab
configuration and verify it before connecting.

    from devices.BBD30X.BBD30X_main import BBD30X
    from core.shared_runtime import RuntimeServices

    services = RuntimeServices()
    delay_stage = BBD30X(kinesis_runtime=services.kinesis)
    delay_stage.connect("REVIEWED_SERIAL")

    equips = {"delay_stage": delay_stage}
    equips_set_channels = {
        "delay_stage": ["pos_mm", "pos_um", "delay_ps"],
    }
    equips_get_channels = {
        "delay_stage": ["pos_mm", "pos_um", "delay_ps"],
    }

The checked-in default profile remains mock-only. Do not add lab serials or
enable this device in a shared profile.

## Connection and motion parameters

The first BBD30X connection for a shared Kinesis runtime builds the managed
DeviceManager list once. Later connections create and connect the requested
serial directly. If a direct connection fails, BBD30X performs one serialized
DeviceManager refresh and retries the same serial once; it does not enumerate,
log, or select other devices. After connection it selects channel 1, waits up
to 5000 ms for settings, starts 50 ms controller polling, and enables the
channel. If device configuration loading fails, the existing DDS220 file-
settings fallback is applied.

Every successful connection then writes and reads back:

- velocity: 100 mm/s;
- acceleration: 2000 mm/s².

The UI displays those values. Set / Read Back treats each empty field as
"preserve the current controller value." If both fields are empty, it performs
readback without writing. Inputs must be finite and greater than zero; final
stage-specific limits remain enforced by Kinesis.

Connection and UI-operation exceptions are contained in the worker thread,
reported in the status label and device log, and do not intentionally close
the application. Failed connection performs best-effort controller cleanup,
releases the runtime lease, and permits retry.

## Position UI, T0, and delay conversion

The device panel uses millimeters only:

- the move target accepts 0–220 mm, has four decimal places, and steps by
  0.0001 mm;
- Current and Target display millimeters and picoseconds with four decimals;
- position displays update during an active move and when Read Position is
  clicked; there is no continuous UI timer;
- the embedded log shows connection state, T0, home/stop lifecycle, warnings,
  and errors; successful routine moves, reads, and parameter updates stay in
  their dedicated status fields and are not logged;
- the log is approximately eight lines high by default, remains vertically
  resizable, and retains the latest 500 timestamped entries in memory only.

Set T0 reads the actual current position without moving the stage. T0 is
cleared on connect and disconnect and is never persisted. A delay_ps scan
operation fails until T0 has been explicitly set for the current connection.

The retroreflector round-trip conversion uses c = 0.299792458 mm/ps:

    delay_ps    = 2 * (position_mm - t0_mm) / c
    position_mm = t0_mm + delay_ps * c / 2

Micrometers are available as a scan unit but are not displayed in the device
panel.

## Scan channels

ZMeter method/signature discovery exposes three writable and readable
channels. All setters converge on the same finite 0–220 mm validation and
motion path.

| Channel | Setter input / getter output | Coordinate |
| --- | --- | --- |
| pos_mm | millimeters | absolute stage position |
| pos_um | micrometers | absolute stage position |
| delay_ps | picoseconds | round-trip delay relative to session T0 |

Only the current channel names are supported. Configure scans and
scan_range_limits.json with pos_mm, pos_um, or delay_ps as appropriate.

## Motion, cancellation, and remaining risks

Moves use Kinesis's asynchronous completion callback. While a move is active,
the worker reads the controller's cached position every 100 ms and emits it to
the UI. Success requires callback completion and final readback within
0.0001 mm. The overall deadline remains 50 seconds.

On force-stop, cancellation, or timeout, the move loop requests Kinesis
Stop(5000) and reports the outcome. This is a software-controlled stop and
does not provide emergency-stop guarantees.

Remaining hardware-facing risks include:

- The DDS220 file-settings fallback can initialize settings when device
  configuration loading fails; the attached stage model is not independently
  verified first.
- Homing remains a blocking Home(60000) call. The move cancellation event
  does not interrupt a blocking home operation.
- The preserved alternate connect3() path changes homing direction and is
  not used by the ZMeter widget.
- Shutdown cannot safely disconnect until the active worker operation exits.
- A Kinesis stop or disconnect failure leaves physical controller state
  uncertain and requires operator verification.
- The 0–220 mm software check does not prove physical clearance or correct
  stage orientation.

## Hardware-independent validation

Run with the maintained environment active:

    python -B -m py_compile devices\BBD30X\BBD30X_hardware.py devices\BBD30X\BBD30X_logic.py devices\BBD30X\BBD30X_main.py
    python -B -m unittest discover -s devices\BBD30X\tests -p "test_*.py" -v

The tests inject fake Kinesis bindings and must not load vendor DLLs, build a
device list, or operate hardware.

## **User-executed hardware test**

The user must review and run this procedure; agents must not execute it.

1. Verify the controller/channel are a BBD30X with the intended DDS220 and
   confirm the reviewed serial, stage orientation, physical clearance,
   controller limits, cabling, and emergency stop.
2. Connect without homing. Confirm the UI remains open on an intentionally
   invalid serial, reports the error, and then successfully retries the
   reviewed serial.
3. Confirm connection reads back 100 mm/s and 2000 mm/s². Change only one
   field while leaving the other empty, then verify the empty parameter is
   preserved.
4. Click Read Position and compare Current against the controller or an
   independent known position.
5. Command the current position, then the smallest approved move in each
   direction. Confirm intermediate Current updates, Target remains correct,
   final readback is within tolerance, and routine samples do not flood the
   device log.
6. Set T0 and confirm Current delay becomes 0 ps. Make equivalent smallest
   approved moves through pos_mm, pos_um, and delay_ps, verifying the
   retroreflector factor of two and physical displacement.
7. Under independent hardware protection, request Stop during a bounded move
   and verify the controller decelerates/stops as intended. Do not treat this
   as an emergency-stop qualification.
8. Disconnect and close ZMeter. Confirm polling, controller handles, stage
   state, and external safety controls are in the intended state.

Do not test homing until direction, speed, travel, and limit-switch behavior
have been reviewed separately for the installed mechanism.
