# Thorlabs MC2000B

This package provides the ZMeter panel and scan channels for a Thorlabs
MC2000B optical chopper. It uses the controller's USB virtual COM port and does
not discover or select serial ports automatically.

## Configuration

Use driver ID `mc2000b`. Put the Windows COM port, such as `COM5`, in the
workbook `address` field. Keep the checked-in row disabled and
`connect_on_start=FALSE` until the COM port has been reviewed at the instrument.

The transport is fixed to the MC2000B protocol: 115200 baud, 8 data bits, one
stop bit, no parity, and no flow control. Connection verifies that `id?` starts
with `THORLABS MC2000B`. On opening the port, the driver clears any pending
input and sends `id?` directly. Commands are sent one at a time through the
same serial lock; an empty command is not sent because the controller reports
`CMD_NOT_DEFINED` for it.

## Panel and scan channels

The panel can set and read integer frequency in hertz and integer phase in
degrees. Set targets and last-read values appear in separate fields. A successful
Set clears the old readback until Get is pressed. The same synchronous logic
methods are exposed to scan discovery:

- setter/getter channel `frequency`: `set_frequency(value)` and
  `get_frequency()`
- setter/getter channel `phase`: `set_phase(value)` and `get_phase()`

For the MC1F10HP wheel (the manual calls it a 100-outer/10-inner-slot
wheel), the controller natively selects the internal outer or inner
reference using `ref=0` or `ref=1`; `ref?` reads that selection. The panel
shows the controller's `blade?` index and current reference separately from
the editable reference choice. A reference change is explicit and is allowed
only when the controller reports standby and blade index 6. ZMeter never
stops the wheel to make the change. Use **Get blade** to confirm the installed
controller setting; the physical wheel marking alone does not establish it.
The user's `MC1F10HPa` marking has not been separately verified against the
manual's `MC1F10HP` name.

The existing `frequency` channel remains the controller's `freq=n`/`freq?`
internal-reference target. Its meaning depends on the selected reference
mode; it is **not** a separate independently adjustable inner and outer
frequency pair or a measured blade-speed readback. The wheel has one motor,
and ZMeter performs no slot-ratio conversion. The panel does not issue
`output=n` or change the REF OUT BNC signal. The documented
`refoutfreq?` query only reports the currently selected REF OUT frequency,
not both inner and outer frequencies at once; it is not exposed as two
independent getters. Ref In is a panel-only configuration action and is not
added as a scan channel. Existing saved scans and workbook filters remain
unchanged.

The shared guard accepts 1 to 10000 Hz, which covers the controller family.
The installed blade and selected reference impose a narrower physical range;
the MC2000B remains authoritative and a device rejection is surfaced as an
error. Phase is limited to 0 through 360 degrees. Values must be whole numbers,
matching the reviewed Thorlabs SDK interface.

**Start** sends `enable=1` and **Stop** sends `enable=0`; both verify the result
with `enable?`. The run-mode label is read on connection and can be updated with
**Refresh state**, including after a change made on the controller itself. It
reports the controller's enabled/standby state, not measured blade speed or
phase lock. Starting a ZMeter scan does not start the chopper automatically,
and disconnecting does not stop it. Panel commands remain available during a
scan and share one serial lock with scan commands. Manual target changes during
a scan can affect the measurement.
The panel's `stop_scan()` and `start_scan()` lifecycle hooks are no-ops: there
is no MC2000B panel monitor to pause or resume, and these hooks do not change
the chopper run mode. This also keeps older device registries that call the
hooks compatible during scan setup and shutdown.

## User-executed hardware test

1. With the chopper stopped or in a safe optical state, confirm the Windows COM
   port in Device Manager and put it in the panel or workbook.
2. Connect and confirm the panel reports connected rather than accepting an
   unrelated serial device.
3. Confirm the run-mode label matches the controller. Press **Refresh state**
   after changing run mode at the controller.
4. Use **Get** for frequency and phase and compare the separate readback labels
   with the front panel. Verify that Get does not change the Set targets.
5. With the chopper explicitly in standby, verify **Get blade** reports index
   6 for MC1F10HP. Compare **Get** for Ref In with the front panel. Select
   Internal outer and then Internal inner through the new panel control,
   checking `ref?`/front-panel agreement each time. Confirm the REF OUT BNC
   setting did not change. Do not attempt to change Ref In during Run mode.
6. Set one in-range frequency appropriate for the selected reference and one phase,
   then read both back. Do not use 10000 Hz unless the installed blade and
   experiment are rated for it.
7. Use **Start** and **Stop** and confirm the controller and run-mode label agree.
8. Run a two-point scan for `frequency` inside the blade's safe range, with
   `frequency` and `phase` as getters. Verify the front-panel values and saved
   scan values.
9. Abort a scan during a sweep, close ZMeter, and confirm that the serial port
   is released. If the chopper must be stopped, press **Stop** before closing
   ZMeter or use the controller's normal run/stop control.

Hardware commissioning is pending. Automated tests use only an injected fake
serial backend and never enumerate or open real ports.

Protocol and blade-mode references: Thorlabs, *MC2000B Optical Chopper User
Guide*, sections 5.3–5.4, 6.5, 8.1–8.4, and 12.1
([manual copy](https://www.manualzz.com/doc/73533923/thorlabs-mc2000b-user-manual)).
