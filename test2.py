"""
Generate a pulse train on PFI12 and read edge counts on PFI8.

Typical wiring for loopback test:
1. Route pulse output physically from PFI12 to PFI8.
2. Run this script and verify non-zero count/rate results.
"""

import argparse
import time

import nidaqmx
from nidaqmx.constants import AcquisitionType, CountDirection, Edge, Level, TriggerType
import random


COUNTER_TIMEBASE_HZ = 100_000_000.0


def _normalize_channel(device: str, channel: str) -> str:
    token = channel.strip().lstrip("/")
    if "/" not in token:
        token = f"{device}/{token}"
    return token


def _normalize_terminal(device: str, terminal: str) -> str:
    token = terminal.strip().lstrip("/")
    if "/" not in token:
        token = f"{device}/{token}"
    return f"/{token}"


def _counter_internal_output(device: str, counter_channel: str) -> str:
    counter_name = counter_channel.split("/")[-1].capitalize()
    return f"/{device}/{counter_name}InternalOutput"


def _counter_index(counter_channel: str) -> int:
    counter_name = counter_channel.split("/")[-1].lower()
    if not counter_name.startswith("ctr"):
        raise ValueError(f"Invalid counter channel: {counter_channel}")
    suffix = counter_name.replace("ctr", "", 1)
    if not suffix.isdigit():
        raise ValueError(f"Invalid counter channel: {counter_channel}")
    return int(suffix)


def _select_gate_counter(
    device: str,
    ci_counter_channel: str,
    co_counter_channel: str,
    gate_counter: str,
) -> str:
    forbidden = {ci_counter_channel.lower(), co_counter_channel.lower()}

    if gate_counter.strip():
        selected = _normalize_channel(device, gate_counter)
        if selected.lower() in forbidden:
            raise ValueError(
                f"gate counter '{selected}' must be different from CI and CO counters."
            )
        return selected

    ci_index = _counter_index(ci_counter_channel)
    paired_index = ci_index + 1 if ci_index % 2 == 0 else ci_index - 1
    paired_counter = f"{device}/ctr{paired_index}"
    if paired_counter.lower() not in forbidden:
        return paired_counter

    for idx in range(8):
        candidate = f"{device}/ctr{idx}"
        if candidate.lower() not in forbidden:
            return candidate

    raise RuntimeError(
        "No available gate counter found. Specify --gate-counter explicitly."
    )


def _measure_hardware_timed_count(
    device: str,
    ci_counter_channel: str,
    input_pfi_terminal: str,
    gate_counter_channel: str,
    integration_time: float,
) -> tuple[int, float]:
    gate_high_ticks = max(1, int(round(integration_time * COUNTER_TIMEBASE_HZ)))
    gate_low_ticks = 10
    actual_integration_time = gate_high_ticks / COUNTER_TIMEBASE_HZ

    gate_internal = _counter_internal_output(device, gate_counter_channel)
    timebase_100mhz = f"/{device}/100MHzTimebase"
    timeout = max(1.0, actual_integration_time * 5.0 + 1.0)

    with nidaqmx.Task() as count_task, nidaqmx.Task() as gate_task:
        gate_channel = gate_task.co_channels.add_co_pulse_chan_ticks(
            counter=gate_counter_channel,
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

        ci_channel = count_task.ci_channels.add_ci_count_edges_chan(
            counter=ci_counter_channel,
            edge=Edge.RISING,
            initial_count=0,
            count_direction=CountDirection.COUNT_UP,
        )
        ci_channel.ci_count_edges_term = input_pfi_terminal

        count_task.triggers.pause_trigger.trig_type = TriggerType.DIGITAL_LEVEL
        count_task.triggers.pause_trigger.dig_lvl_src = gate_internal
        count_task.triggers.pause_trigger.dig_lvl_when = Level.LOW

        t0 = time.perf_counter()
        count_task.start()
        t1 = time.perf_counter()
        gate_task.start()
        t2 = time.perf_counter()
        gate_task.wait_until_done(timeout=timeout)
        t3 = time.perf_counter()
        count = int(count_task.read())
        t4 = time.perf_counter()

        print(
            f"start_count={t1-t0:.6f}, "
            f"start_gate={t2-t1:.6f}, "
            f"wait_gate={t3-t2:.6f}, "
            f"read={t4-t3:.6f}, "
            f"total={t4-t0:.6f}"
        )

    return count, actual_integration_time


def run(
    device: str,
    co_counter: str,
    ci_counter: str,
    gate_counter: str,
    output_pfi: str,
    input_pfi: str,
    pulse_freq: float,
    duty_cycle: float,
    integration_time: float,
    duration: float,
) -> None:
    if integration_time <= 0:
        raise ValueError("integration_time must be > 0.")

    co_counter_terminal = _normalize_channel(device, co_counter)
    ci_counter_terminal = _normalize_channel(device, ci_counter)
    gate_counter_terminal = _select_gate_counter(
        device=device,
        ci_counter_channel=ci_counter_terminal,
        co_counter_channel=co_counter_terminal,
        gate_counter=gate_counter,
    )
    output_pfi_terminal = _normalize_terminal(device, output_pfi)
    input_pfi_terminal = _normalize_terminal(device, input_pfi)

    with nidaqmx.Task() as co_task:
        co_channel = co_task.co_channels.add_co_pulse_chan_freq(
            counter=co_counter_terminal,
            idle_state=Level.LOW,
            initial_delay=0.0,
            freq=pulse_freq,
            duty_cycle=duty_cycle,
        )
        co_channel.co_pulse_term = output_pfi_terminal
        co_task.timing.cfg_implicit_timing(sample_mode=AcquisitionType.CONTINUOUS)

        print(
            "Starting tasks: "
            f"CO {co_counter_terminal} -> {output_pfi_terminal}"
        )
        print(
            "Hardware-timed CI: "
            f"CI {ci_counter_terminal} <- {input_pfi_terminal}, "
            f"gate={gate_counter_terminal} "
            f"(internal={_counter_internal_output(device, gate_counter_terminal)})"
        )
        print(
            f"pulse={pulse_freq:.3f} Hz, duty={duty_cycle:.6f}, "
            f"integration_time={integration_time:.6f} s"
        )

        co_task.start()

        start_time = time.time()
        cycles = 0

        try:
            while duration <= 0 or (time.time() - start_time) < duration:
                count, actual_dt = _measure_hardware_timed_count(
                    device=device,
                    ci_counter_channel=ci_counter_terminal,
                    input_pfi_terminal=input_pfi_terminal,
                    gate_counter_channel=gate_counter_terminal,
                    integration_time=integration_time,
                )
                rate_hz = count / actual_dt
                cycles += 1

                print(
                    f"cycle={cycles:6d} "
                    f"count={count:8d} "
                    f"rate={rate_hz:10.2f} Hz "
                    f"(gate_dt={actual_dt:9.6f}s)",
                    end="\r",
                )
                time.sleep(random.random())
        except KeyboardInterrupt:
            pass
        finally:
            print(f"\nStopped. cycles={cycles}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Output pulse train on PFI12 and read counter input on PFI8."
    )
    parser.add_argument("--device", default="Dev2")
    parser.add_argument("--co-counter", default="ctr1", help="Counter output channel")
    parser.add_argument("--ci-counter", default="ctr0", help="Counter input channel")
    parser.add_argument(
        "--gate-counter",
        default="",
        help="Gate counter for hardware-timed integration (auto-select if empty).",
    )
    parser.add_argument("--output-pfi", default="PFI12")
    parser.add_argument("--input-pfi", default="PFI8")
    parser.add_argument("--pulse-freq", type=float, default=135752.0, help="Hz")
    parser.add_argument("--duty-cycle", type=float, default=0.005)
    parser.add_argument("--integration-time", type=float, default=0.1, help="Seconds")
    parser.add_argument(
        "--duration",
        type=float,
        default=0.0,
        help="Seconds; <=0 runs until Ctrl+C.",
    )
    args = parser.parse_args()

    run(
        device=args.device,
        co_counter=args.co_counter,
        ci_counter=args.ci_counter,
        gate_counter=args.gate_counter,
        output_pfi=args.output_pfi,
        input_pfi=args.input_pfi,
        pulse_freq=args.pulse_freq,
        duty_cycle=args.duty_cycle,
        integration_time=args.integration_time,
        duration=args.duration,
    )
