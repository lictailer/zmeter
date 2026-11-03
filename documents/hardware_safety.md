# Hardware Safety

## Agent execution boundary

All real-instrument operation and testing is reviewed and performed directly by the user. Coding agents may write hardware-facing code and exact test procedures, but must never execute any command or test that could discover, connect to, configure, home, ramp, move, source, trigger, read/write, disconnect, reset, or otherwise affect laboratory hardware. General requests to test, verify, or run tests do not cross this boundary.

Agents may execute only confirmed hardware-independent compilation, unit tests, mocks, simulations, and offscreen GUI tests. Any real-instrument procedure must be labeled **User-executed hardware test**.

The only exception is the test-PC bench test described in the last subsection of this section; without every one of its conditions the ban applies.

### Agent bench tests on the test PC

This is the only exception to the boundary above. The default stays forbidden unless every condition below is met.

**Scope**

- Only the designated test PC; never a lab measurement PC.
- Only Keithley 24xx, SR860, and nidaq.
- No sample is connected. Outputs are open, or connected to a dummy load or loopback that the user wired and stated in the authorization.

**Authorization**

- Per session. The user's message names the devices, addresses, test scripts to run, and the wiring state. "Test this" and "verify this" are not authorization.
- An authorization covers only that session and only those scripts.

**How tests run**

- Only committed scripts that the user has reviewed, in `tests/bench/` with file names `bench_*.py`. The standard `test_*.py` discovery never runs them.
- A skip gate requires the environment variable `ZMETER_BENCH=1` and an allowlist file on the test PC, outside the repository, that lists the allowed instrument addresses and per-channel test limits. Tests never touch instruments on other computers.
- Test limits are stricter than device limits and are kept next to the allowlist. Values are chosen conservatively with the user when a test is prepared; they are not defined in this document.
- Stop at the first error: no retries and no trying other parameters; hand the result to the user.
- At the end, including after an error or interruption, write every output to its safe state, read it back to confirm, then disconnect.
- Every run writes a log (time, script, commit, every written and read-back value) to a fixed folder on the test PC, outside the experiment data folder.

**Forbidden**

- Changing firmware, writing non-volatile memory, changing GPIB or network addresses, calibration, and saving or recalling instrument setups.
- Touching any instrument that is not on the allowlist, or discovering new instruments on the bus.
- Installing or upgrading packages on the test PC.
- Loosening limits or safety checks to make a test pass.

**How results count**

Reports label the evidence "agent-executed bench test (test PC, no sample)". It can replace part of the repeated checking during development. It does not replace the user's acceptance on the lab PC; the user-executed bench check before each phase switches its default stays required.

## Ranges, units, and configuration

- Device logic/hardware must validate finite values, units, device limits, and experiment/profile limits before an operation.
- Repository-wide scan limits are loaded from `scan_range_limits.json` and keyed by registered device label plus channel. Device-specific physical limits remain in device configuration/README and must not be weakened by a broader global limit.
- A missing, mismatched, or uncertain label/channel/unit is a configuration error; fail safely rather than guessing.
- Keep addresses, serials, enabled devices, calibration, and lab-specific limits outside shared core logic.

When `MainWindow.write_info()` rejects a configured scan value, it does not call the setter and marks the associated measurement to be stored as `NaN`. Preserve that skip behavior and make rejection visible to the operator.

## Safe ramps and writes

A ramp implementation must define target units, allowed range, maximum step/rate, settle requirements, timeout, stop polling frequency, and the state reported after interruption. Validate the complete planned path, not only the endpoint. Never bypass ramping or limits to make a test pass.

On stop or failure, preserve the last confirmed completed waypoint. Do not report the requested target as actual state unless the device confirms it. A partial write/ramp must leave enough status and logging for the user to determine the instrument state before continuing.

## Pause, stop, force stop, and abort

- **Pause** blocks scan progression at defined checkpoints; it does not reverse completed writes or necessarily halt an in-progress device command.
- **Resume** continues only after the state remains coherent.
- **Stop** requests scan-worker exit, releases a paused wait, and propagates `force_stop()` to equipment.
- **Force stop** must promptly interrupt bounded device operations where supported and remain asserted until the lifecycle deliberately clears it. Current `MainWindow` clears its global force-stop flag in `start_equipments()` after scan cleanup.
- **Abort/error** must stop further unsafe writes, retain confirmed state, report contextual failure, reset transient skip/control flags, and run cleanup.

An array getter read (a camera exposure) is one bounded acquisition: its timeout comes from the device's own timing, it is never retried silently (a retry exposes the detector again), and force stop aborts the exposure without disconnecting or changing the cooler. Cooled cameras must not be switched off by a reconnect; see [devices/andor/README.md](../devices/andor/README.md).

Stop handling must be idempotent and safe when disconnected, partially initialized, already stopped, or invoked during shutdown. Do not confuse a software flag with verified physical safe state.

A queued manual setter runs outside the GUI thread, so Queue Stop remains
responsive and preserves every unstarted entry. Stop is cooperative: it blocks
the next queue item but does not preempt an in-flight setter. The queue waits
for that setter to return or for the operator to use an existing device Abort
action. Never use `QThread.terminate()` or introduce an unreviewed generic or
device timeout to force completion; shutdown must retain its activity barrier
rather than tear down hardware beneath the worker. This core behavior does not
change OptiCool or any other device's limits, timeout, or abort contract.

## Range rejection and skipped measurements

Global range rejection and artificial-channel rejection can suppress a write/read and store `NaN`. Artificial channels may coordinate two underlying channels and ramp through waypoints; a rejected higher-level point normally suppresses lower recursion, except when the immediately lower level completes the paired artificial target.

Changes require tests for no forbidden write, correct `NaN` location, skip-flag consumption/reset, paired-level behavior, retained commanded/target state, and recovery on the next point.

## Partial failure

On connection loss, timeout, malformed response, vendor exception, or uncertain state:

1. stop issuing dependent commands;
2. request bounded cancellation/force stop where safe;
3. report operation, channel, value, scan indices, and original error;
4. preserve acquired data and local recovery output;
5. clean up threads/resources without hiding the primary error;
6. require the user to inspect/restore physical state before another hardware operation.

Do not auto-reconnect, retry a non-idempotent write, reset, home, or continue a scan unless that behavior is explicitly designed, bounded, and safe for the device.

## Shutdown and disconnection

Application exit asks for confirmation, shuts down the scan queue, propagates force stop and scan stop, then calls each equipment's `terminate_dev()` and `close()`. Device window close may merely hide the widget; final application teardown must release workers, connections, vendor handles, and locks.

Keep shutdown ordered and bounded. A GUI close is not evidence that an instrument disconnected or reached a safe state; the user verifies real equipment directly.

## Validation sequence

1. Static review and compilation.
2. Unit tests for limits, state transitions, exceptions, and stop flags.
3. Deterministic mock/simulation tests for ramps, timeouts, partial failure, abort, and shutdown.
4. Offscreen/manual GUI checks with simulated devices.
5. **User-executed hardware test** only after the above evidence and user review.

## Minimum user bench checklist

Provide an instrument-specific procedure containing:

- model/firmware, interface/address, driver version, calibration/configuration, and starting physical state;
- isolated/non-sensitive setup and independently verified permitted range/units;
- connection and one read-only status check;
- smallest safe write or ramp with explicit step/rate/timeout;
- pause/stop/force-stop observation at a controlled point;
- injected or naturally bounded timeout/error response when safe;
- scan cleanup, disconnect, and independently verified final safe state;
- expected logs/data and pass/fail criteria.

The user reviews and executes this checklist. The agent records the result only from user-provided evidence and must not imply broader hardware validation than was observed.

## Post-restructure user bench plan

The registry recognizes the startup-only real drivers listed in
[device_status.md](device_status.md), but their presence in `device_config.xlsx`
is not hardware approval. The user adapts and executes the instrument-specific
checklist above with exactly one real device enabled in a reviewed workbook and
`connect_on_start=FALSE` for first commissioning.

Record the exact deployed Git commit, selected workbook and workbook hash, maintained Python environment/interpreter, vendor SDK/runtime version, device model/firmware/interface, approved limits, and initial physical state. If that driver is separately approved for runtime mutation, test idle disconnect/removal and verify that removal is refused during a safe controlled dependent scan. Otherwise record those two mutation checks as pending or not applicable; never enable runtime mutation merely to exercise the checklist.

After the established read-only, smallest-safe-operation, stop, and force-stop checks, close the entire application and independently verify the final physical/device state. Preserve the observed logs and results, pass/fail decision, limitations, and follow-up against that exact model, configuration, and operation. Hardware evidence supplied later by the user belongs in the restructure progress log's user-hardware-result template.

