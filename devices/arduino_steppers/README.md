# Arduino steppers

Standalone driver ID: `arduino_steppers`. It owns one serial connection to three
28BYJ-48/ULN2003 motors A/B/C. The workbook prefills COM6, enabled but manual-connect.
Construction, setup loading and catalog discovery never enumerate/open ports.
Autofocus uses it through the same device/channel selectors as other stages.

## Panel and channels

Motor tabs have separate targets and last-read labels for angle, full steps and
speed. Get does not replace a position target. Angle and steps refer to the same
absolute software coordinate, not two axes. Speed changes rate, not position.
Firmware reports steps/revolution and maximum RPM; Python does not assume 2048.

| Setter/getter channel | Meaning |
| --- | --- |
| `stepperA_angle`, `stepperB_angle`, `stepperC_angle` | Absolute geared motor angle, degrees |
| `stepperA_steps`, `stepperB_steps`, `stepperC_steps` | Absolute full-step position; targets rounded, integer readback |
| `stepperA_speed_rpm`, `stepperB_speed_rpm`, `stepperC_speed_rpm` | Integer RPM in the firmware-configured range |

All have numeric `set_<channel>(value)` and `get_<channel>()` logic methods.
Angle and fractional-step targets round to the nearest full step (ties away from
zero), using firmware-reported steps/revolution for angles. This lets autofocus
use step channels with an appropriate rounding tolerance. Channels
work in scans independently of autofocus. Do not select speed as Z, mix degree
setters with step getters, or set equivalent angle/steps for one motor together.

Local per-motor travel bounds and maximum stop-aware segment size are in full
steps. Defaults -113..113, segment 56 conservatively continue the previous
approximate +/-20-degree example at 2048 steps/rev. They are **not detected safe
clearances**. Review mechanics. Apply local limits before scans; panel commands
also apply displayed limits. Applying limits sends no hardware command. Moves
check both starting and target positions. More than 10000 segments is refused.

A/B/C share one serialized port. UI jobs use a worker; scan calls are synchronous.
Stop consumes a sent segment acknowledgement before refusing later segments.
Timeout/malformed/wrong-axis replies or mismatched acknowledgements mark the
connection uncertain: no retry or subsequent command until reconnect/inspection.
Disconnect/exit wait for active work, then close the port without home/zero/move,
speed or coil commands. Counters are **not encoders**; drift/missed steps/manual
movement are not detected. Reset/upload or opening the port may reset all counters
without physically homing the axes.

## Firmware and wiring

Open [arduino_steppers.ino](arduino/arduino_steppers/arduino_steppers.ino) in Arduino
IDE. This is the sole maintained sketch. Upload is manual with the actual board
and processor selection. No uploader, COM discovery or fallback protocol is added.

| Motor | ULN2003 IN1, IN2, IN3, IN4 -> Arduino pins |
| --- | --- |
| A | D2, D3, D4, D5 (confirmed wiring) |
| B | D6, D7, D8, D9 (from supplied source; review wiring) |
| C | D10, D11, D12, D13 (from supplied source; review wiring) |

Edit the top configuration block: `PINS`, `STEPS_PER_REV`, `INITIAL_RPM`, `MAX_RPM`,
`DIRECTION`, `RELEASE_AFTER_MOVE`. Defaults: nominal 2048 full steps/rev, 12/7/7 RPM,
12 RPM configured ceiling, positive signs and release after movement. The ceiling
is a reviewable setting, not proof of safe loaded speed. Review power ratings and
common ground; GPIO carries control, not motor power. Releasing coils can cause
drift if holding torque is needed. Keeping them energized instead has holding,
power/thermal consequences to review. No startup holding phase or disconnect
coil action is added. The Stepper constructor intentionally uses IN1,IN3,IN2,IN4,
following the supplied code. Other mechanics can replace stepping/release code
while keeping the acknowledged absolute-step protocol. No autofocus change needed.

115200 baud ASCII, one command per newline (CRLF accepted):

| Command | Reply |
| --- | --- |
| `PING` | `OK STEPPERS 1` |
| `GET_CONFIG A` | `CFG A <steps_per_rev> <rpm> <max_rpm>` |
| `GET_POS A` | `POS A <steps>` |
| `MOVE_ABS A <steps>` | `OK A <steps>` after completion |
| `SET_SPEED A <rpm>` | `SPEED A <rpm>` |

Use B/C analogously. Startup prints READY. Unknown axes/commands, bad/extra
arguments, noninteger/overflow targets, invalid speed, overlong lines and embedded
NUL are rejected without movement. HOME/ZERO do not exist. Firmware does not know
objective clearance: do not bypass reviewed ZMeter limits with arbitrary serial
movement commands. This protocol rejects old single-motor OK PONG firmware and
relative stepperA commands. Old sources are recoverable in
[the archive](../../archive/autofocus-legacy-2026-10-18/README.md), not current firmware.

Distance calibration belongs to the [autofocus Z mapping](../auto_focus/README.md).
Angle/full steps are native coordinates; no objective-distance ratio is guessed.

## Saved setup and validation

Explicit Save/Load uses a separate schema-version-1 JSON: port, timeout and all
local limits/segment sizes. Loading requires idle/disconnected state and does not
touch hardware. Firmware speed/configuration is read on connection and is not
silently restored by loading. Speeds reset to firmware defaults on board reset.
Files use QSaveFile; no automatic lab-data/PPT/backup output is introduced. Existing
scan JSON format is unchanged.

```text
python -B -m unittest discover -s devices/arduino_steppers/tests -p 'test_*.py' -v
python -B -m unittest discover -s devices/auto_focus/tests -p 'test_*.py' -v
```

Fake serial/router tests cover channels, quantization, bounds, protocol/timeout,
serialized access, Stop, worker/teardown, settings and calibrated autofocus.
A host C++ compiler builds the actual sketch against fake Stepper/Serial I/O;
this is not a board-specific Arduino build or physical validation.

Combined integration results and platform limitations are maintained in
[the MS integration notes](../../documents/ms_lab_integration.md), rather than
duplicated per-device test counts. Offscreen construction and fake router tests
do not establish actual travel, calibration, missed-step behavior or board build.

## User-executed hardware test

The agent has not connected, uploaded or moved real hardware.

1. Review/support/clear all mechanisms, verify power/pins and choose safe bounds.
2. Close other port owners. Verify/Upload the maintained sketch on COM6 using the
   actual Arduino board/processor. At 115200/newline send only PING, GET_CONFIG
   A/B/C and GET_POS A/B/C first. Verify identity/configuration and counter reset.
3. Close Serial Monitor. Connect the standalone panel explicitly. Read all axes
   before motion, then commission one small approved move per motor, its angle/
   step equivalence, direction, speed, Stop and coil-release drift.
4. Select its same-unit position setter/getter in autofocus. Review calibration
   and rounding tolerance, then commission a small focus profile before temperature
   scans. Verify autofocus release leaves the controller connected and that device
   disconnect/exit sends no movement/home/zero command.
