# AI Refactor V1 (Hardware Layer)

## Summary

This update changes analog input from "create a new AI task per read" to
"create one persistent AI task at connect, then reuse it for all reads."

The public API remains:

- `read_analog_input(input_channel, integration_time) -> float`

## Architecture

At `connect()`:

1. Create one AI task with channels `ai0:31`.
2. Configure finite hardware sample clock timing with `AI_SAMPLE_RATE_HZ`.
3. Commit the AI task once.
4. Build channel index mapping (`DevX/ai0` -> 0 ... `DevX/ai31` -> 31).
5. Clamp AI sample clock to a safe per-channel rate derived from device limits
   (`ai_max_single_chan_rate` and `ai_max_multi_chan_rate / channel_count`).

At `read_analog_input(channel, integration_time)`:

1. Validate integration time and channel.
2. Compute `sample_count` from integration time.
3. If `sample_count` changed, reconfigure timing on the existing task
   (`TASK_UNRESERVE -> cfg_samp_clk_timing -> TASK_COMMIT`).
4. Start/read/stop the existing task.
5. Return the mean value for the requested channel.

At `disconnect()`:

- Close the persistent AI task and clear AI caches/maps.

## Why One AI Task

Using one consolidated AI task avoids repeated task object creation and follows
NI guidance to combine same-type operations into one task.

This is particularly appropriate for devices with shared AI resources
(aggregate sample rate/FIFO/scan list behavior).

## Compatibility

- No change to `read_analog_input(...)` function signature.
- No logic-layer changes in this phase.
- Existing callers can continue calling AI reads channel-by-channel.

## Test Flow

`test_ai_all_channels.py` performs:

1. `connect()` once
2. sequential reads for `AI0..AI31`
3. optional multi-cycle scanning
4. `disconnect()` cleanup
