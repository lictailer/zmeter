# Spectra-Physics InSight X3 laser

The panel groups Main, Objectives, Diagnostics, and About like the
manufacturer's GUI. It displays laser emission and tunable-beam shutter state
separately. The panel has explicit diode ON/OFF, shutter open/close, and
Run/Align controls; each requires a continuous three-second hold. It also
reads diode temperature, current, hours, warm-up, power, humidity, mode, and
status. The controller power readout and a 0–3 W display update about once
per second while this panel is visible. That value is reference-only, not a
substitute for a calibrated power meter. Objective editing and service
functions are not implemented.

Closing ZMeter, disconnecting, or stopping a scan sends no diode, shutter, or
mode command. An explicit `OFF` command is different: the controller itself
also closes the shutter when turning the diode off.

## Configuration and scan channels

The tracked `device_config.xlsx` has a `spectraphysicsx3_laser` row with
`enabled=TRUE`, `connect_on_start=FALSE`, address `COM4`, and two
setter scan channels: `wavelenght_stable` and `shutter`. The getter scan
channels are `wavelenght_stable`, `shutter`, and read-only `output_power_w`.
The spelling
`wavelenght_stable` follows the requested channel name exactly; older saved
scan definitions that refer to `wavelength` must be changed to it. Review
that port on the lab PC;
it is a placeholder based on the operator's test. Open ZMeter's X3 panel and
connect manually. Do not connect automatically until the hardware procedure
has been reviewed. The same Windows COM port cannot be opened by Python while
the manufacturer GUI owns it. A separate RS-232 host path may exist, but
concurrent GUI/host control is unverified.

`set_wavelenght_stable(nm)` accepts finite whole-nm targets inside the reported
controller limits (and 680–1300 nm). It checks status for a fault/open
interlock, sends one `WAVelength <nm>` command, confirms `WAVelength?` reports
that target, then waits for two consecutive `READ:WAVelength?` readings at
that exact nm. Default timeout is 120 s. `get_wavelenght_stable()` returns
**actual** wavelength, not the target. This establishes wavelength readback
agreement; it does **not** establish that optical output power has stopped
oscillating. Do not treat it as a power-stability interlock. A power-stability
rule needs a lab-approved tolerance, observation window, and behavior when
power is near zero or the shutter is closed.

`get_output_power_w()` reads the controller's `READ:POWer?` value in watts.
ZMeter can record it at scan points. There is no output-power setter in this
driver; the documented user command list has a power query but no normal
power setpoint command.

`set_shutter(0)` explicitly closes the tunable shutter;
`set_shutter(1)` explicitly opens it only if the diode reports energized and
no fault or open interlock is reported. Both commands are followed by a
`SHUTter?` acceptance query and two sensed `*STB?` confirmations. The getter
`get_shutter()` returns sensed state, 0 or 1. A scan shutter step executes at
its scheduled point, **without a GUI hold**; the three-second requirement is
for the panel buttons. Opening the shutter does not itself turn the diode on.
The diode and Run/Align methods are deliberately not scan setters.

`force_stop()` cancels an active wavelength wait or shutter-open wait but does
not send a laser or shutter command. It does not prevent an explicit shutter
close after a stop. A new three-second panel action can be made after a
cancelled scan; it is a fresh operator command, not a scan restart. No
automatic resend is attempted if command acceptance is uncertain.

The serial connection uses explicit address, 115200 baud, 8N1 and carriage-
return commands. Startup queries are wavelength min/max, actual wavelength,
and status word. `*IDN?` may be empty on this controller and is optional.

## Before the first real scan

1. Follow `documents/hardware_safety.md` and have the lab laser-safety owner
   approve the beam path, allowed wavelength interval, power, operator
   supervision, and abort response. This driver does **not** close an exposed
   beam when the scan fails or stops. If closing the shutter at the end is
   required, include an explicit `shutter=0` scan step and still plan for the
   case where the scan aborts before that step.
2. Verify the actual communication path for this controller. If the GUI is
   open on COM4, this driver cannot share COM4; do not terminate the GUI or
   add a second cable without checking manufacturer guidance and the lab's
   procedure.
3. With qualified staff and the beam secured, first use the panel's read-only
   connect/refresh functions. Check target, actual, status bits, emission,
   shutter, and faults against the manufacturer GUI. A successful connection
   is not evidence that an open-shutter sweep is safe.
4. Only after the lab approves the protocol, separately test the held panel
   commands and sensed readbacks, then one modest wavelength change and a
   short step scan. Confirm shutter close on a scan point and the unchanged
   state on scan stop, disconnect, and ZMeter exit. Stop/fault behavior must
   be observed and documented before routine use.

The device has been verified with fake serial data and compilation only on the
development Mac; the exact COM4 controller and live optical behavior have not
been tested by the agent. The manufacturer's command reference and protocol
evidence are summarized in `documents/insight_x3_integration.md`.
