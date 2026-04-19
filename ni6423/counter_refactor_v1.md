# Counter Refactor V1 (Hardware Layer)

## Summary

This update changes `NI6423Hardware` counter behavior from per-read task creation to
persistent tasks initialized during `connect()`.

V1 intentionally narrows the counter API:

- Counter read path: `Ctr0` only
- Gate generator: `Ctr1` only
- Pulse train output: `Ctr3` only

The goal is to reduce per-read DAQmx overhead while preserving hardware-timed
integration windows.

## Counter Architecture

At `connect()`:

1. Create and commit persistent CI task on `Ctr0`.
2. Route `Ctr0` edge count input to configurable terminal (default `PFI8`).
3. Create and commit persistent finite gate task on `Ctr1` using 100 MHz timebase.
4. Configure CI pause trigger to `Ctr1InternalOutput`, counting only when gate is HIGH.
5. Start CI task once and read/store initial cumulative count baseline.

At each `read_sample_counter(integration_time)` call:

1. Convert integration time to gate high ticks.
2. Update gate pulse high ticks (task is reused, not recreated).
3. Start gate task, wait until done, stop gate task.
4. Read CI cumulative count.
5. Compute window count by delta from previous cumulative count.
6. Return rate in Hz (`window_count / actual_integration_time`).

## Pulse Train on Ctr3

New methods:

- `start_pulse_train(frequency_hz: float, duty_time_s: float) -> None`
- `stop_pulse_train() -> None`

Validation:

- `frequency_hz > 0`
- `duty_time_s > 0`
- `duty_time_s < 1/frequency_hz`

The output terminal is configurable in `__init__`, default `PFI12`.

Calling `start_pulse_train()` when already running will stop and recreate the
pulse task with the new configuration.

## Configurable Routing (Constructor)

`NI6423Hardware.__init__` now includes:

- `ctr0_input_pfi='PFI8'`
- `ctr1_gate_counter='ctr1'`
- `ctr2_input_pfi='PFI10'` (placeholder for future extension)
- `ctr3_pulse_counter='ctr3'`
- `ctr3_output_pfi='PFI12'`

`Ctr2` mapping is retained as configuration placeholder in V1, but `Ctr2` is not
used by the active read path.

## API Migration Note

`read_sample_counter` signature changed:

- Old: `read_sample_counter(input_counter_channel, integration_time)`
- New: `read_sample_counter(integration_time)`

Behavior now always reads from persistent `Ctr0` configuration.

Any caller passing a counter channel argument must be updated.

## Cleanup Behavior

`disconnect()` now ensures cleanup of:

- AO tasks
- Ctr3 pulse task
- Ctr1 gate task
- Ctr0 CI task

All persistent counter state and cumulative baseline values are cleared.
