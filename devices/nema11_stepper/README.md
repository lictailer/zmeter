# NEMA 11 closed-loop Z stepper

Driver ID: `nema11_stepper`, widget `nema11_main.Nema11Stepper`. It owns one serial
connection to an Arduino Nano that drives the autofocus Z motor through a
closed-loop STEP/DIR driver. Construction, setup
loading and catalog discovery never enumerate or open ports.

Hardware:

- Motor: StepperOnline 11HS20-1004D-E1000-EGS, NEMA 11 closed loop, 1000 PPR
  (4000 CPR) incremental encoder.
- Driver: StepperOnline CL42T V4.1, 24–48 VDC, 0.3–3.0 A.
- Controller: Arduino Nano (ATmega328P). The sketch refuses to build for other chips.

This replaces the Z part of the archived `autofocus_xuguo` package. The sketch is
the original `stepper_driver.ino` with optional encoder readback added; motion,
pins and command names are unchanged.

## Channels

| Setter/getter channel | Meaning |
| --- | --- |
| `z_angle` | Absolute commanded motor-shaft angle in degrees |

`set_z_angle(value)` sends `MOVE_ABS`, waits for the move to finish and returns the
commanded angle (`GET_CMD`). `get_z_angle()` returns the commanded angle. The CL42T
closes the loop on the motor encoder, so the commanded angle is the shaft angle
unless the driver alarms. zmeter cannot detect a stall or alarm itself: watch the
driver's alarm LED. Values are rounded to whole microsteps (360/6400 = 0.05625 deg
at the default microstep setting).

**Connect sets the current position to 0 deg.** Python sends `ZERO` right after the
handshake, so the origin is wherever the shaft is when you connect, whether or not
opening the port reset the board. Disconnect/exit only close the port: no home,
zero or motion command is sent.

**There are no software travel limits in this device.** Every finite target is sent
as entered, in one move. Panel moves are not limited at all; scan and autofocus
writes still pass ZMeter's global output limits and, for focus runs, the autofocus
Z limits. Make sure those match your mechanics.

## Panel

- COM port, Connect, Disconnect. The workbook address prefills the port.
- Z angle: absolute target, Set, Get and the last acknowledged angle. Get never
  overwrites the target.
- Command timeout (default 120 s), long enough for the longest move:
  at about 9.4 RPM one motor revolution takes about 6.4 s.
- Save/Load setup: a schema-version-1 JSON with the port and timeout. Loading
  requires the device to be idle and disconnected, and touches no hardware.

A move is one command, so Stop takes effect only before the next command. A
timeout or malformed reply marks the connection uncertain: no further command is
sent until you disconnect, inspect the motor and reconnect.

## Wiring

> Disconnect driver power before wiring. Read the labels printed on your driver
> and encoder connector, and follow them if they differ from this table. The
> wiring below was written from the product pages and has not been checked on
> the bench.

### Driver power and motor

| Driver terminal | Connect to |
| --- | --- |
| `+Vdc`, `GND` (power) | 24–48 VDC supply |
| `A+`, `A-`, `B+`, `B-` | Motor phase wires (follow the motor label / driver manual) |
| Encoder port | Motor encoder cable, plugged in as supplied (unchanged) |

### Arduino Nano to driver control inputs

| Arduino Nano | CL42T terminal | Notes |
| --- | --- | --- |
| D2 | `PUL+` | STEP pulse |
| D3 | `DIR+` | Direction. CW is positive |
| GND | `PUL-`, `DIR-` | Common-cathode wiring |
| (not connected) | `ENA+`, `ENA-` | Unconnected means enabled |

**Set the driver's signal-level switch to 5 V.** The CL42T V4.1 factory setting is
24 V. Arduino 5 V signals are not reliable at 24 V, and 24 V signals with the switch
at 5 V can damage the driver inputs.

### Arduino Nano to motor encoder (optional, not used by zmeter)

Not needed: zmeter reads the commanded position. The encoder stays plugged into
the driver for its closed loop. The sketch can still read it for diagnostics
(`GET_POS`) if you tap EA+ → D4, EB+ → D5 and EGND → GND; without the tap `GET_POS`
and the `MOVE_ABS` reply read 0, which is expected.

### Driver DIP switches

- Microstep (SW1–SW4): choose the pulses/rev in the driver manual's table and set
  `STEPS_PER_REV` in the sketch to the same value (default 6400).
- Direction, closed/open loop, pulse type (SW5–SW7): keep closed loop and
  Step & Direction (pulse + direction) mode.

## Firmware

Open [nema11_stepper.ino](arduino/nema11_stepper/nema11_stepper.ino) in the Arduino
IDE, select **Arduino Nano** with the matching processor (ATmega328P or
ATmega328P Old Bootloader), and upload. The top configuration block holds:

| Constant | Default | Meaning |
| --- | --- | --- |
| `STEP_PIN`, `DIR_PIN` | 2, 3 | Driver STEP/DIR |
| `ENC_A_PIN`, `ENC_B_PIN` | 4, 5 | Optional encoder tap A/B (must be D4–D7) |
| `STEPS_PER_REV` | 6400 | Must equal the driver microstep setting |
| `STEP_DELAY_US` | 500 | Half pulse period. 6400 steps/rev gives about 9.4 RPM |
| `ENCODER_COUNTS_PER_REV` | 4000 | 1000 PPR × 4 |
| `ENCODER_SIGN` | 1 | Set to -1 if `GET_POS` goes negative on a positive move |
| `SETTLE_MS` | 20 | Wait after the last pulse before replying |

The protocol is 115200 baud ASCII, one command per newline:

| Command | Reply |
| --- | --- |
| `PING` | `OK NEMA11 1` |
| `GET_POS` | `POS <encoder_deg>` (diagnostic; 0 without the encoder tap) |
| `GET_CMD` | `CMD <commanded_deg>` (position used by Python) |
| `MOVE_ABS <deg>` | `OK <encoder_deg>` after the pulses finish; Python then reads `GET_CMD` |
| `MOVE_REL <deg>` | `OK <encoder_deg>` (kept from the original; not used by Python) |
| `ZERO` | `OK 0.000000`: commanded and encoder positions both set to 0 |
| `HOME` | `OK <encoder_deg>` after moving to 0 (kept; not used by Python) |

Startup prints `READY`. Unknown commands reply `ERR Unknown command`. Changes from
the original sketch: `PING` replies `OK NEMA11 1` instead of `OK PONG`, so Python
refuses any other sketch. Position replies carry the encoder angle, `GET_CMD` is
new, and `ZERO` also clears the encoder count. Motion uses the commanded step
counter, as in the original.

## Using it in autofocus

Connect `nema11_stepper` in its own panel first. In `auto_focus` → **Z actuator**,
select setter and getter `nema11_stepper/z_angle`, native unit `deg`. To work in
micrometers, enable conversion with the measured distance per degree. With the old
`autofocus_xuguo` defaults (500 um per translator revolution, 100/30 gear):

```text
distance_per_native = 500 / (360 * 100/30) = 0.416667 um/deg
```

Verify this on your mechanics before relying on it. The autofocus Z tolerance must
cover microstep rounding (at least 0.03 deg, or 0.012 um after conversion). The
autofocus Z limits are the only travel limits for focus runs: set them from your
mechanics. The previous coarse+fine Gaussian
search corresponds to the autofocus **Full Z sweep → Gaussian fit** method.

## Workbook

`device_config.xlsx` → Devices row 31 has id `nema11_stepper`, address `COM7`,
scan channels `z_angle`. It ships disabled and manual-connect like the other new
rows: tick **enabled** (a checkbox) to load it, and change the address if your
Nano uses another port. The Guide sheet lists `nema11_stepper` as a known driver.

## Validation

```text
python -B -m unittest discover -s devices/nema11_stepper/tests -p 'test_*.py' -v
```

Fake-serial tests cover the handshake, connect-time zero, commanded readback with
no encoder tap, no software limits, Stop, malformed reply, timeout,
worker/teardown, setup round trip, registration construction and an autofocus run routed through
`z_angle`. A host C++ compiler builds the actual sketch against a fake closed-loop
motor, encoder and serial port. That is not an Arduino build or a physical test.

## User-executed hardware test

The agent has not connected, uploaded or moved real hardware.

1. With power off, wire as above, set the signal switch to 5 V and set the microstep
   switches to match `STEPS_PER_REV`. Mechanically free the Z stage or decouple the
   motor.
2. Upload the sketch. In Serial Monitor (115200, newline) send `PING`, `MOVE_ABS 10`,
   `GET_CMD`. The shaft should turn 10 deg and `GET_CMD` reply `CMD 10.000000`.
3. Close Serial Monitor. Connect from the panel, confirm the reading is 0, then make
   one small move and check the direction and angle against the shaft.
4. Check that the driver alarm LED stays off during moves.
5. Re-couple the stage, select `nema11_stepper/z_angle` in autofocus, and run a small
   bounded sweep with **Move to selected focus Z** unchecked before normal use.
