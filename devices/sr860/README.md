# Stanford Research Systems SR860

## Purpose and status

This package controls an SRS SR860 lock-in amplifier through the shared `VisaRuntime`. It covers demodulated outputs, reference/source settings, input configuration, sensitivity/time constant, filters, display/status values, and auxiliary I/O. Shared-session lifecycle and offscreen construction have fake coverage; bench validation remains pending.

It is registered under driver ID `sr860` with required connection field `address`. Keep `connect_on_start=false` for first commissioning and use explicit numeric scan filters. Runtime mutation remains disabled.

After construction, the widget schedules one VISA enumeration on the next Qt event-loop turn. Discovery runs in a worker thread, populates a width-adjusted address dropdown, and never opens an instrument session. The operator can still click **Refresh VISA**. Disconnect clears the instrument session before closing its lease, matching the original SR860 driver behavior.

## Current scan discovery

The exact `.logic` signatures expose two numeric setters, `set_amplitude(value)` in volts RMS and `set_dc_level(value)` in millivolts, plus many getters. Numeric acquisition candidates include `X`, `Y`, `R`, `Theta`, `frequency`, `amplitude`, `phase`, and the currently selected auxiliary input/output. Status getters expose overload/unlock state.

Configuration getters include time constant, sensitivity, reference mode/input, trigger, harmonic, input modes/ranges, coupling, shield, notch filter, DC level/mode, and filter slope. `get_multiple_outputs`, `get_display`, and `get_all` return compound or non-measurement results. Use profile filters so only numeric scalar measurement channels are exposed.

Most logic `set_*` methods use stored UI setpoints and therefore are not scan-visible. Do not infer scan writability from the widget controls.

## Output ramps

Amplitude and DC-level writes ramp from an instrument readback instead of jumping directly to the requested value. Editing either target field does not write to the instrument: the operator must press the adjacent **Set** button. Separate **Current** labels show output readbacks and completed ramp waypoints without changing the target fields. Every ramp waypoint is programmed and queried in one SR860 command line (`SLVL ...;SLVL?` or `SOFF ... MV;SOFF?`), so its response confirms that exact command after the instrument finishes processing it. The atomic waypoint transaction gets a single attempt with a 1000 ms timeout; an uncertain timeout stops the ramp instead of repeating a voltage command. A final mismatch is polled for up to one second without repeating the output write. Comparison follows the documented three-significant-digit rounding and minimum resolution (1 nV amplitude, 0.1 mV DC), so a previous small-step value is not accepted merely because it is within a broad percentage tolerance. Before a ramp, ZMeter also enforces the documented combined-output limit, `|DC offset| + sqrt(2) × amplitude ≤ 6 V`. The panel provides separate session-only rates: amplitude defaults to 0.1 V/s and accepts 0.001–2 V/s; DC level defaults to 100 mV/s and accepts 5–5000 mV/s. Ramps calculate each waypoint from real elapsed time at no more than 20 writes per second, so VISA/GPIB latency changes the spacing of waypoints instead of accumulating into a false timeout. Planned ramps may run for at most 3600 seconds and reject non-finite targets, out-of-range targets, invalid readbacks, and invalid rates before the first write.

The hardware layer sends the panel's millivolt DC target with an explicit `MV` suffix and converts the volts returned by `SOFF?` back to millivolts. Connection remains on the original SR860 implementation: a 100 ms VISA timeout, `*IDN?` through the ordinary query helper, and up to three query attempts. Only ramp waypoint program-and-query transactions use the separate single-attempt 1000 ms path described above; this does not change connection or disconnect behavior.

The **Stop ramp** button and scan force-stop request interrupt between waypoints. Stop logs identify whether the request came from the SR860 panel, scan/application lifecycle, or disconnect. After interruption or failure, the reported setpoint remains the last known output: normally the last successfully written waypoint, or the last instrument readback when endpoint confirmation found a mismatch. The requested endpoint is not reported as reached. A new manual ramp or scan preparation deliberately clears a previous stop request. Scan preparation stops live monitoring, and scan cleanup restores it only when it was previously active.

## Setup and units

- Python: PyQt6, PyVISA, NumPy, and pyqtgraph;
- system: compatible VISA backend/interface driver;
- configuration: explicit VISA resource, input/reference mode, ranges, sensitivity, time constant, filters, auxiliary channel, and safe source amplitude.

The hardware documents internal reference frequency as 1 mHz–500 kHz, sine output amplitude up to 2 V RMS, and sine-output DC level as −5000 mV to +5000 mV. The scan-visible `dc_level` setter uses mV to match the SR860 panel. Phase/`Theta` are degrees; voltage-mode demodulated outputs and auxiliary I/O are volts. Confirm limits and ramp rates against the exact instrument, firmware, wiring, and experiment.

## Lifecycle and safety

Connection uses the original `*IDN?` query path and 100 ms VISA session timeout. The reviewed registration stops monitoring before scans, restores prior monitoring afterward, propagates force-stop to active ramps, and requests ramp stop before bounded disconnect. Ordinary disconnect attempts the original VISA device clear before closing the lease.

Agents must not enumerate VISA resources, connect, configure, source, read, reset, or disconnect the SR860. The user must validate filters, units, timeouts, monitor coordination, auxiliary limits, and shutdown state. See [hardware_safety.md](../../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile devices/sr860/sr860_hardware.py devices/sr860/sr860_logic.py devices/sr860/sr860_main.py`.

**User-executed hardware test:** isolate the output from the experiment or attach a reviewed dummy load; connect to the explicit VISA address and confirm SR860 identity/firmware; record the initial amplitude, DC level, DC mode, and monitoring state; choose conservative rates and ramp amplitude across a small approved range; ramp DC level across a small approved millivolt range around 0 mV; independently verify timing, direction, endpoints, and units; request **Stop ramp** during separate upward and downward ramps and verify the displayed/instrument value remains at the last completed waypoint; start and stop a scan using both channels and confirm monitoring does not contend; exercise one bounded communication failure if safe; terminate; and independently verify the final output and session state.
