"""
Generate a pulse train on PFI12 and read edge counts on PFI8.

Version:
- Create/configure tasks only once at startup.
- Start CO once and leave it running.
- Start CI once and leave it running.
- For each measurement cycle, only start the finite gate task.
- Read cumulative count after each gate window.
- Use the difference between consecutive cumulative counts as the count
  for the current integration window.
- Add random.random() delay between reads, as requested.

Typical wiring for loopback test:
1. Route pulse output physically from PFI12 to PFI8.
2. Run this script and verify non-zero count/rate results.
"""

import argparse
import random
import time

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


class PersistentCounterMeasurement:
    def __init__(
        self,
        device: str,
        co_counter: str,
        ci_counter: str,
        gate_counter: str,
        output_pfi: str,
        input_pfi: str,
        pulse_freq: float,
        duty_cycle: float,
        integration_time: float,
    ) -> None:
        if integration_time <= 0:
            raise ValueError("integration_time must be > 0.")
        if pulse_freq <= 0:
            raise ValueError("pulse_freq must be > 0.")
        if not (0.0 < duty_cycle < 1.0):
            raise ValueError("duty_cycle must be between 0 and 1.")

        self.device = device
        self.co_counter_terminal = _normalize_channel(device, co_counter)
        self.ci_counter_terminal = _normalize_channel(device, ci_counter)
        self.gate_counter_terminal = _select_gate_counter(
            device=device,
            ci_counter_channel=self.ci_counter_terminal,
            co_counter_channel=self.co_counter_terminal,
            gate_counter=gate_counter,
        )
        self.output_pfi_terminal = _normalize_terminal(device, output_pfi)
        self.input_pfi_terminal = _normalize_terminal(device, input_pfi)

        self.pulse_freq = pulse_freq
        self.duty_cycle = duty_cycle
        self.integration_time = integration_time

        self.gate_high_ticks = max(1, int(round(integration_time * COUNTER_TIMEBASE_HZ)))
        self.gate_low_ticks = 10
        self.actual_integration_time = self.gate_high_ticks / COUNTER_TIMEBASE_HZ
        self.timeout = max(1.0, self.actual_integration_time * 5.0 + 1.0)

        self.timebase_100mhz = f"/{device}/100MHzTimebase"
        self.gate_internal = _counter_internal_output(device, self.gate_counter_terminal)

        self.co_task = None
        self.count_task = None
        self.gate_task = None

        self.previous_total_count = None

    def setup(self) -> None:
        self.co_task = nidaqmx.Task("pulse_output")
        self.count_task = nidaqmx.Task("edge_count")
        self.gate_task = nidaqmx.Task("gate_pulse")

        # Continuous pulse output task
        co_channel = self.co_task.co_channels.add_co_pulse_chan_freq(
            counter=self.co_counter_terminal,
            idle_state=Level.LOW,
            initial_delay=0.0,
            freq=self.pulse_freq,
            duty_cycle=self.duty_cycle,
        )
        co_channel.co_pulse_term = self.output_pfi_terminal
        self.co_task.timing.cfg_implicit_timing(sample_mode=AcquisitionType.CONTINUOUS)

        # Edge count task, paused when gate is LOW
        ci_channel = self.count_task.ci_channels.add_ci_count_edges_chan(
            counter=self.ci_counter_terminal,
            edge=Edge.RISING,
            initial_count=0,
            count_direction=CountDirection.COUNT_UP,
        )
        ci_channel.ci_count_edges_term = self.input_pfi_terminal

        self.count_task.triggers.pause_trigger.trig_type = TriggerType.DIGITAL_LEVEL
        self.count_task.triggers.pause_trigger.dig_lvl_src = self.gate_internal
        self.count_task.triggers.pause_trigger.dig_lvl_when = Level.LOW

        # One finite pulse per cycle used as gate window
        gate_channel = self.gate_task.co_channels.add_co_pulse_chan_ticks(
            counter=self.gate_counter_terminal,
            source_terminal=self.timebase_100mhz,
            high_ticks=self.gate_high_ticks,
            low_ticks=self.gate_low_ticks,
        )
        gate_channel.co_pulse_idle_state = Level.LOW
        gate_channel.co_pulse_ticks_initial_delay = 0
        self.gate_task.timing.cfg_implicit_timing(
            sample_mode=AcquisitionType.FINITE,
            samps_per_chan=1,
        )

        # Commit once
        self.co_task.control(TaskMode.TASK_COMMIT)
        self.count_task.control(TaskMode.TASK_COMMIT)
        self.gate_task.control(TaskMode.TASK_COMMIT)

        # Start continuous tasks once
        self.co_task.start()
        self.count_task.start()

        # Read initial cumulative count baseline
        self.previous_total_count = int(self.count_task.read())

    def close(self) -> None:
        for task in (self.gate_task, self.count_task, self.co_task):
            if task is not None:
                try:
                    task.close()
                except Exception:
                    pass

    def measure_once(self, debug_timing: bool = False):
        """
        Perform one integration window by starting only the gate task.
        CI remains running continuously.

        Returns:
            window_count, actual_integration_time, total_time
        Or if debug_timing=True:
            window_count, actual_integration_time, timing_dict
        """
        t0 = time.perf_counter()

        self.gate_task.start()
        t1 = time.perf_counter()
        # time.sleep(0.1)
        self.gate_task.wait_until_done(timeout=self.timeout)
        t2 = time.perf_counter()

        current_total_count = int(self.count_task.read())
        t3 = time.perf_counter()

        self.gate_task.stop()
        t4 = time.perf_counter()

        window_count = current_total_count - self.previous_total_count
        self.previous_total_count = current_total_count

        if debug_timing:
            timing = {
                "start_gate": t1 - t0,
                "wait_gate": t2 - t1,
                "read": t3 - t2,
                "stop_gate": t4 - t3,
                "total": t4 - t0,
            }
            return window_count, self.actual_integration_time, timing

        return window_count, self.actual_integration_time, (t4 - t0)


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
    debug_timing: bool,
) -> None:
    measurement = PersistentCounterMeasurement(
        device=device,
        co_counter=co_counter,
        ci_counter=ci_counter,
        gate_counter=gate_counter,
        output_pfi=output_pfi,
        input_pfi=input_pfi,
        pulse_freq=pulse_freq,
        duty_cycle=duty_cycle,
        integration_time=integration_time,
    )

    cycles = 0
    start_time = time.time()

    try:
        measurement.setup()

        print(
            "Starting tasks: "
            f"CO {measurement.co_counter_terminal} -> {measurement.output_pfi_terminal}"
        )
        print(
            "Hardware-timed CI: "
            f"CI {measurement.ci_counter_terminal} <- {measurement.input_pfi_terminal}, "
            f"gate={measurement.gate_counter_terminal} "
            f"(internal={measurement.gate_internal})"
        )
        print(
            f"pulse={measurement.pulse_freq:.3f} Hz, "
            f"duty={measurement.duty_cycle:.6f}, "
            f"integration_time={measurement.integration_time:.6f} s, "
            f"actual_gate_dt={measurement.actual_integration_time:.9f} s"
        )

        while duration <= 0 or (time.time() - start_time) < duration:
            result = measurement.measure_once(debug_timing=debug_timing)
            cycles += 1

            if debug_timing:
                count, actual_dt, timing = result
                rate_hz = count / actual_dt
                print(
                    f"cycle={cycles:6d} "
                    f"count={count:8d} "
                    f"rate={rate_hz:12.2f} Hz "
                    f"gate_dt={actual_dt:9.6f}s "
                    f"start_gate={timing['start_gate']:.6f} "
                    f"wait_gate={timing['wait_gate']:.6f} "
                    f"read={timing['read']:.6f} "
                    f"stop_gate={timing['stop_gate']:.6f} "
                    f"total={timing['total']:.6f}"
                )
            else:
                count, actual_dt, total_time = result
                rate_hz = count / actual_dt
                print(
                    f"cycle={cycles:6d} "
                    f"count={count:8d} "
                    f"rate={rate_hz:12.2f} Hz "
                    f"gate_dt={actual_dt:9.6f}s "
                    f"count_time={total_time:.6f}"
                )

            # Requested: wait a random amount of time between CI reads
            time.sleep(random.random())

    except KeyboardInterrupt:
        print(f"\nStopped by user. cycles={cycles}")
    finally:
        measurement.close()


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
    parser.add_argument(
        "--debug-timing",
        default=True,
        action="store_true",
        help="Print timing breakdown for each cycle.",
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
        debug_timing=args.debug_timing,
    )