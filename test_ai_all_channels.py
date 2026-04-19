"""
Read all NI6423 analog input channels using persistent AI task setup.

This test verifies:
1. connect() creates the persistent AI task.
2. read_analog_input() can read AI0..AI31 sequentially.
"""

import argparse
import time

from ni6423.ni6423_hardware import NI6423Hardware


def run(
    device: str,
    integration_time: float,
    cycles: int,
    inter_cycle_sleep: float,
) -> None:
    hw = NI6423Hardware(device_name=device)

    try:
        print(f"[TEST] connect({device})")
        hw.connect()
        print("[PASS] connected")

        cycle = 0
        while cycles <= 0 or cycle < cycles:
            cycle += 1
            print(f"\n[CYCLE] {cycle}")

            for channel_index in range(32):
                channel = f"AI{channel_index}"
                t0 = time.time()
                value = hw.read_analog_input(channel, integration_time)
                t1 = time.time()
                print(f"{channel:>4s} = {value:+.6f} V", "time: ", t1-t0)


            if inter_cycle_sleep > 0:
                time.sleep(inter_cycle_sleep)
    except KeyboardInterrupt:
        print("\n[STOP] interrupted by user")
    finally:
        try:
            hw.disconnect()
            print("[PASS] disconnected")
        except Exception as exc:
            print(f"[WARN] disconnect failed: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Sequentially read AI0..AI31 after one hardware connect."
    )
    parser.add_argument("--device", default="Dev2")
    parser.add_argument(
        "--integration-time",
        type=float,
        default=1e-4,
        help="Integration time in seconds (100 us step).",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=0,
        help="Number of full AI0..AI31 scans. <=0 runs until Ctrl+C.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Optional delay between cycles (seconds).",
    )
    args = parser.parse_args()

    run(
        device=args.device,
        integration_time=args.integration_time,
        cycles=args.cycles,
        inter_cycle_sleep=args.sleep,
    )
