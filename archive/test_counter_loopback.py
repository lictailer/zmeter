"""
Counter loopback test for NI6423Hardware counter refactor V1.

Wiring:
1. Connect Dev2/PFI12 to Dev2/PFI8.
2. Run this script.
"""

import argparse
import time
import random

from ni6423.ni6423_hardware import NI6423Hardware


def run(
    device: str,
    pulse_freq: float,
    duty_time: float,
    integration_time: float,
    cycles: int,
    inter_cycle_sleep: float,
) -> None:
    hw = NI6423Hardware(device_name=device)
    cycle = 0

    try:
        print(f"[TEST] connect({device})")
        hw.connect()
        print("[PASS] connected")

        print(
            "[TEST] start_pulse_train("
            f"frequency_hz={pulse_freq:.6f}, duty_time_s={duty_time:.9f})"
        )
        hw.start_pulse_train(frequency_hz=pulse_freq, duty_time_s=duty_time)
        print("[PASS] pulse started on Ctr3/PFI12")

        print(
            "[TEST] reading Ctr0 via read_sample_counter("
            f"integration_time={integration_time:.6f}s)"
        )

        while cycles <= 0 or cycle < cycles:
            cycle += 1
            measured_hz = hw.read_sample_counter(integration_time=integration_time)
            error_pct = ((measured_hz - pulse_freq) / pulse_freq) * 100.0
            print(
                f"cycle={cycle:5d} "
                f"expected={pulse_freq:12.3f} Hz "
                f"measured={measured_hz:12.3f} Hz "
                f"error={error_pct:+8.3f}%"
            )

            # time.sleep(random.random()/2)
            
    except KeyboardInterrupt:
        print("\n[STOP] interrupted by user")
    finally:
        try:
            hw.stop_pulse_train()
            print("[PASS] pulse stopped")
        except Exception as exc:
            print(f"[WARN] stop_pulse_train failed: {type(exc).__name__}: {exc}")
        try:
            hw.disconnect()
            print("[PASS] disconnected")
        except Exception as exc:
            print(f"[WARN] disconnect failed: {type(exc).__name__}: {exc}")
        

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Loopback test: Ctr3 pulse output on PFI12, Ctr0 counter input on PFI8."
    )
    parser.add_argument("--device", default="Dev2")
    parser.add_argument("--pulse-freq", type=float, default=135495.0, help="Hz")
    parser.add_argument(
        "--duty-time",
        type=float,
        default=2e-8,
        help="Pulse high time in seconds (must be < 1/pulse-freq).",
    )
    parser.add_argument(
        "--integration-time",
        type=float,
        default=0.1,
        help="Counter integration time in seconds.",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=450,
        help="Number of read cycles. <=0 runs until Ctrl+C.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Optional delay between read cycles (seconds).",
    )
    args = parser.parse_args()

    run(
        device=args.device,
        pulse_freq=args.pulse_freq,
        duty_time=args.duty_time,
        integration_time=args.integration_time,
        cycles=args.cycles,
        inter_cycle_sleep=args.sleep,
    )
