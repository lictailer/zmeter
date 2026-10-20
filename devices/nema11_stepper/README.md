# NEMA 11 closed-loop Z stepper

Driver ID: `nema11_stepper`, widget `nema11_main.Nema11Stepper`. It owns one serial
connection to an Arduino Nano that drives the autofocus Z motor through a
closed-loop STEP/DIR driver and reads the motor encoder. Construction, setup
loading and catalog discovery never enumerate or open ports.

Hardware:

- Motor: StepperOnline 11HS20-1004D-E1000-EGS, NEMA 11 closed loop, 1000 PPR
  (4000 CPR) incremental encoder.
- Driver: StepperOnline CL42T V4.1, 24–48 VDC, 0.3–3.0 A.
- Controller: Arduino Nano (ATmega328P). The sketch refuses to build for other chips.

This replaces the Z part of the archived `autofocus_xuguo` package. The sketch is
the original `stepper_driver.ino` with encoder readback added; motion, pins and
command names are unchanged.

## Channels

| Setter/getter channel | Meaning |
| --- | --- |
| `z_angle` | Absolute motor-shaft angle in degrees, read from the encoder |

`set_z_angle(value)` moves to the absolute angle and returns the encoder reading
once it is within the position tolerance. `get_z_angle()` returns the encoder
reading. Both are encoder (real) positions, not a step counter.

**Connect sets the current position to 0 deg.** Python sends `ZERO` right after the
handshake, so the origin is wherever the shaft is when you connect, whether or not
opening the port reset the board. Disconnect/exit only close the port: no home,
zero or motion command is sent.

## Panel

- COM port, Connect, Disconnect. The workbook address prefills the port.
- Z angle: absolute target, Set, Get and the last encoder reading. Get never
  overwrites the target.
- Local motion limits, applied before every panel command and required before scans:
  minimum/maximum angle (default -50..50 deg), maximum degrees per stop-aware
  segment (10), encoder position tolerance (0.2 deg) and encoder settle timeout
  (2 s). The defaults are about ±20 um with the old 100/30 gear and 500 um/rev
  translator. They are **not detected safe clearances**. Review your mechanics.
- Command timeout (default 120 s), **Stop subsequent segments**, Save/Load setup.

Moves are split into segments of at most the segment size. Stop takes effect after
the in-flight segment is acknowledged. After each segment the encoder must reach
the waypoint within the tolerance before the settle timeout. Otherwise the move
fails with "Encoder reads X deg, not Y deg". A timeout, malformed reply or encoder
mismatch marks the connection uncertain: no further command is sent until you
disconnect, inspect the motor and reconnect. Moves needing more than 10000 segments
are refused.

The tolerance must cover the encoder resolution (360/4000 = 0.09 deg) plus the
microstep quantization (360/6400 = 0.056 deg at the default microstep setting).
Do not set it below 0.15 deg.

Save/Load setup uses a separate schema-version-1 JSON with the port, timeout and
limits. Loading requires the device to be idle and disconnected, and touches no
hardware.

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

### Arduino Nano to motor encoder (read-only tap)

The encoder stays plugged into the driver for closed-loop control. The Arduino
listens in parallel on the A and B channels:

| Arduino Nano | Encoder signal | Notes |
| --- | --- | --- |
| D4 | `EA+` | Channel A, pin-change interrupt |
| D5 | `EB+` | Channel B, pin-change interrupt |
| GND | `EGND` | Encoder signal ground |
| (not connected) | `EA-`, `EB-`, `VCC` | Do not power the encoder from the Nano |

Splice or tap the wires between the encoder cable and the driver's encoder
connector, keep the tap short, and do not disturb the existing connection. The
encoder outputs are differential. Reading only the `+` side against `EGND` usually
works at 5 V logic. If counts are missing or noisy, put an RS-422 line receiver
(for example AM26LS32) between `EA±`/`EB±` and D4/D5.

The encoder pins must stay on D4–D7, the pin-change interrupt group the sketch
uses. D2/D3 stay STEP/DIR as in the original sketch.

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
| `ENC_A_PIN`, `ENC_B_PIN` | 4, 5 | Encoder A/B (must be D4–D7) |
| `STEPS_PER_REV` | 6400 | Must equal the driver microstep setting |
| `STEP_DELAY_US` | 500 | Half pulse period. 6400 steps/rev gives about 9.4 RPM |
| `ENCODER_COUNTS_PER_REV` | 4000 | 1000 PPR × 4 |
| `ENCODER_SIGN` | 1 | Set to -1 if `GET_POS` goes negative on a positive move |
| `SETTLE_MS` | 20 | Wait after the last pulse before replying |

The protocol is 115200 baud ASCII, one command per newline:

| Command | Reply |
| --- | --- |
| `PING` | `OK NEMA11 1` |
| `GET_POS` | `POS <encoder_deg>` |
| `GET_CMD` | `CMD <commanded_deg>` (diagnostic) |
| `MOVE_ABS <deg>` | `OK <encoder_deg>` after the pulses finish |
| `MOVE_REL <deg>` | `OK <encoder_deg>` (kept from the original; not used by Python) |
| `ZERO` | `OK 0.000000`: commanded and encoder positions both set to 0 |
| `HOME` | `OK <encoder_deg>` after moving to 0 (kept; not used by Python) |

Startup prints `READY`. Unknown commands reply `ERR Unknown command`. Changes from
the original sketch: `PING` replies `OK NEMA11 1` instead of `OK PONG`, so Python
refuses the old sketch, whose `GET_POS` had no encoder. Position replies now carry
the encoder angle. `GET_CMD` is new, and `ZERO` also clears the encoder count.

Motion still uses the commanded step counter, as in the original. The encoder is
used for readback and checking. If the encoder disagrees with the target after a
move (driver alarm, stall, unplugged encoder tap), Python stops instead of
retrying.

## Using it in autofocus

Connect `nema11_stepper` in its own panel first. In `auto_focus` → **Z actuator**,
select setter and getter `nema11_stepper/z_angle`, native unit `deg`. To work in
micrometers, enable conversion with the measured distance per degree. With the old
`autofocus_xuguo` defaults (500 um per translator revolution, 100/30 gear):

```text
distance_per_native = 500 / (360 * 100/30) = 0.416667 um/deg
```

Verify this on your mechanics before relying on it. The autofocus Z tolerance must
be at least the device tolerance (0.2 deg, or 0.083 um after conversion), and its
Z limits must sit inside the device limits. The previous coarse+fine Gaussian
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

Fake-serial tests cover the handshake, connect-time zero, encoder readback,
limits, segmentation, Stop, encoder mismatch, timeout, worker/teardown, setup
round trip, registration construction and an autofocus run routed through
`z_angle`. A host C++ compiler builds the actual sketch against a fake closed-loop
motor, encoder and serial port. That is not an Arduino build or a physical test.

## User-executed hardware test

The agent has not connected, uploaded or moved real hardware.

1. With power off, wire as above, set the signal switch to 5 V and set the microstep
   switches to match `STEPS_PER_REV`. Mechanically free the Z stage or decouple the
   motor.
2. Upload the sketch. In Serial Monitor (115200, newline) send `PING`, `GET_POS`,
   `MOVE_ABS 10`, `GET_POS`, `GET_CMD`. Both positions should read about 10. If
   `GET_POS` reads about -10, set `ENCODER_SIGN = -1`. If it stays at 0, check the
   encoder tap.
3. Turn the shaft by hand with the driver disabled, or watch during a move, to
   confirm `GET_POS` follows the real shaft.
4. Close Serial Monitor. Connect from the panel, confirm the reading is 0, set
   reviewed limits, then make one small move and test Stop during a longer move.
5. Re-couple the stage, select `nema11_stepper/z_angle` in autofocus, and run a small
   bounded sweep with **Move to selected focus Z** unchecked before normal use.
