# CI + Gate Measurement Logic Summary

## Purpose

This design measures pulse counts from an **external instrument output** using a National Instruments counter input (CI), while defining the integration window with a separate **hardware gate counter**.

There is **no CO pulse-generation task** in this version. The external instrument already provides the pulse train to be counted.

The goal is to preserve a **hardware-defined integration time** while reducing DAQmx overhead by:

- creating tasks only once at startup
- starting the CI task once and leaving it running
- using a finite gate pulse for each measurement window
- reading cumulative CI counts and subtracting consecutive readings

---

## Core idea

There are only two logical tasks in this structure:

1. **CI task**
   - counts rising edges arriving from the external instrument
   - runs continuously after startup
   - uses the gate signal as a **pause trigger**

2. **Gate task**
   - generates a finite pulse
   - the HIGH time of that pulse is the integration window
   - when the gate is HIGH, CI counts
   - when the gate is LOW, CI is paused

So the hardware determines the integration interval, not Python timing.

---

## Why this structure is useful

If the CI task is created, started, stopped, and destroyed every cycle, the software adds a fixed overhead to each measurement.

A better structure is:

- create CI and gate tasks once
- configure routing and timing once
- commit once
- start CI once
- for each measurement cycle, only start the finite gate pulse
- read the cumulative CI count after the gate finishes
- compute the count for that window from the difference between successive reads

This preserves the same hardware-gated counting logic while reducing per-cycle software overhead compared with recreating tasks every time. The original test structure that recreated tasks each cycle is shown in the uploaded code. fileciteturn0file0

---

## Signal flow

Example signal flow:

- external instrument pulse output -> `PFI8`
- `ctr0` counts edges on `PFI8`
- another counter such as `ctr2` generates the finite gate pulse
- the gate counter's internal output is used as the CI pause trigger source

Conceptually:

```text
External instrument pulse output -> PFI8 -> CI edge counter
Gate counter internal output -----> CI pause trigger
```

---

## Gate logic

The gate pulse defines the integration window.

- gate HIGH: CI is allowed to count
- gate LOW: CI is paused

The gate pulse width is set in ticks of the onboard 100 MHz timebase:

```python
gate_high_ticks = max(1, int(round(integration_time * 100_000_000.0)))
actual_integration_time = gate_high_ticks / 100_000_000.0
```

That means the true integration time is hardware-defined, with 10 ns resolution from the 100 MHz timebase.

---

## Why CI stays running continuously

In this design, the CI task is started once and then left running.

That means:

- you do **not** pay CI start/stop overhead on every measurement
- the counter value returned by `count_task.read()` is a **cumulative total**
- the count for one integration window must be computed as a difference

Formula:

```python
window_count = current_total_count - previous_total_count
```

So the software logic becomes:

1. read an initial CI baseline after startup
2. generate one gate pulse
3. read CI again
4. subtract the previous total
5. store the new total as the next baseline

---

## Recommended task lifecycle

### Initialization

At program startup:

- create CI task
- create gate task
- configure CI channel
- configure CI pause trigger
- configure gate pulse task
- commit both tasks
- start CI once
- read and store an initial CI baseline

### Per measurement cycle

For each measurement:

- start gate task
- wait for the gate pulse to finish
- read the current cumulative CI count
- compute `window_count = current_total_count - previous_total_count`
- update `previous_total_count`
- optionally wait using `time.sleep(random.random())`

### Shutdown

When finished:

- close gate task
- close CI task

---

## Minimal example code

This example shows the essential structure for an external pulse source.

```python
import time
import random
import nidaqmx
from nidaqmx.constants import (
    AcquisitionType,
    CountDirection,
    Edge,
    Level,
    TaskMode,
    TriggerType,
)

COUNTER_TIMEBASE_HZ = 100_000_000.0

device = "Dev2"
ci_counter = "Dev2/ctr0"
gate_counter = "Dev2/ctr2"

input_pfi = "/Dev2/PFI8"
gate_internal = "/Dev2/Ctr2InternalOutput"
timebase_100mhz = "/Dev2/100MHzTimebase"

integration_time = 0.03

gate_high_ticks = max(1, int(round(integration_time * COUNTER_TIMEBASE_HZ)))
gate_low_ticks = 10
actual_integration_time = gate_high_ticks / COUNTER_TIMEBASE_HZ
timeout = max(1.0, actual_integration_time * 5.0 + 1.0)

count_task = nidaqmx.Task("edge_count")
gate_task = nidaqmx.Task("gate_pulse")

try:
    # -------------------------
    # CI task: count external pulses on input PFI
    # paused whenever gate is LOW
    # -------------------------
    ci_channel = count_task.ci_channels.add_ci_count_edges_chan(
        counter=ci_counter,
        edge=Edge.RISING,
        initial_count=0,
        count_direction=CountDirection.COUNT_UP,
    )
    ci_channel.ci_count_edges_term = input_pfi

    count_task.triggers.pause_trigger.trig_type = TriggerType.DIGITAL_LEVEL
    count_task.triggers.pause_trigger.dig_lvl_src = gate_internal
    count_task.triggers.pause_trigger.dig_lvl_when = Level.LOW

    # -------------------------
    # Gate task: one finite pulse per cycle
    # HIGH time = integration window
    # -------------------------
    gate_channel = gate_task.co_channels.add_co_pulse_chan_ticks(
        counter=gate_counter,
        source_terminal=timebase_100mhz,
        high_ticks=gate_high_ticks,
        low_ticks=gate_low_ticks,
    )
    gate_channel.co_pulse_idle_state = Level.LOW
    gate_channel.co_pulse_ticks_initial_delay = 0
    gate_task.timing.cfg_implicit_timing(
        sample_mode=AcquisitionType.FINITE,
        samps_per_chan=1,
    )

    # Commit once
    count_task.control(TaskMode.TASK_COMMIT)
    gate_task.control(TaskMode.TASK_COMMIT)

    # Start CI once
    count_task.start()

    # Initial cumulative count baseline
    previous_total_count = int(count_task.read())

    cycle = 0
    while True:
        cycle += 1

        t0 = time.perf_counter()
        gate_task.start()
        t1 = time.perf_counter()

        gate_task.wait_until_done(timeout=timeout)
        t2 = time.perf_counter()

        current_total_count = int(count_task.read())
        t3 = time.perf_counter()

        gate_task.stop()
        t4 = time.perf_counter()

        window_count = current_total_count - previous_total_count
        previous_total_count = current_total_count

        rate_hz = window_count / actual_integration_time

        print(
            f"cycle={cycle:6d} "
            f"count={window_count:8d} "
            f"rate={rate_hz:12.2f} Hz "
            f"gate_dt={actual_integration_time:9.6f}s "
            f"start_gate={t1-t0:.6f} "
            f"wait_gate={t2-t1:.6f} "
            f"read={t3-t2:.6f} "
            f"stop_gate={t4-t3:.6f} "
            f"total={t4-t0:.6f}"
        )

        time.sleep(random.random())

except KeyboardInterrupt:
    pass
finally:
    gate_task.close()
    count_task.close()
```

---

## What each read means

Because CI stays running continuously, `count_task.read()` does **not** return the count from only the latest gate window.

Instead, it returns the total accumulated count since the CI task started.

Therefore this subtraction is essential:

```python
window_count = current_total_count - previous_total_count
```

Without it, the count would keep increasing over time and would not represent a single integration window.

---

## Measurement sequence in words

For one measurement cycle, the logic is:

1. CI is already running.
2. Gate starts a finite pulse.
3. While gate is HIGH, CI counts external pulses.
4. When gate returns LOW, CI pauses.
5. Software reads the new cumulative CI total.
6. Software subtracts the previous cumulative total.
7. The difference is the count for that integration window.

---

## Structure to use in a larger project

A good project structure is:

### Setup phase
Create a measurement object or module that:

- creates CI task once
- creates gate task once
- configures all DAQ settings once
- commits both tasks once
- starts CI once
- stores the initial cumulative count baseline

### Measurement function
Implement a function that:

- starts the gate task
- waits for gate completion
- reads CI total count
- computes the delta from the previous total
- updates the previous total
- returns `window_count`, `actual_integration_time`, and optional timing diagnostics

### Shutdown function
Implement cleanup that closes both tasks.

---

## Practical notes

1. **External signal quality matters**
   The external instrument output must meet the counter input electrical requirements of the DAQ.

2. **The input terminal must be correct**
   Make sure the CI count terminal is routed to the PFI receiving the external pulse signal.

3. **The gate counter must be different from the CI counter**
   The gate pulse needs its own counter resource.

4. **The first baseline read is intentional**
   It defines the reference point for the first delta-count measurement.

5. **This design reduces overhead, but does not eliminate all of it**
   Each cycle still includes gate start, gate completion wait, gate stop, and one CI read.

---

## Short version

This design uses:

- one CI task to count an external pulse stream
- one gate task to define a hardware integration window
- a continuous CI task that stays running after startup
- cumulative CI reads, with count-per-window computed by subtraction between consecutive reads

It preserves a hardware-defined measurement interval while reducing DAQmx overhead compared with recreating and restarting the CI task every cycle.
