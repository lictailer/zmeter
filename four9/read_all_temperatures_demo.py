"""Lightweight communication test for Four9 Core Controller.

This demo establishes a connection by reading the `/system` endpoint and
prints all thermometer channels repeatedly.
"""

from __future__ import annotations

import argparse
import math
import time

try:
    # When run as `python -m four9.read_all_temperatures_demo`
    from .core_controller import CoreController
except ImportError:
    # When run as `python four9/read_all_temperatures_demo.py`
    from core_controller import CoreController


def format_temperature(temp_k: float) -> str:
    if math.isnan(temp_k):
        return "NaN"
    return f"{temp_k:8.3f} K"


def print_temperature_channels(controller: CoreController) -> None:
    system = controller.read_system()
    print(f"Thermometer channels: {len(system.thermometers)}")
    for index, thermometer in enumerate(system.thermometers):
        print(
            f"CH{index:02d}  status={thermometer.status.name:<12}  "
            f"T={format_temperature(thermometer.temperature)}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Connect to Four9 Core Controller and print all temperatures."
    )
    parser.add_argument(
        "--host",
        default=CoreController.DEFAULT_BASE_URL,
        help=f"Base URL (default: {CoreController.DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=CoreController.DEFAULT_PORT,
        help=(
            "Scripting API port. "
            f"Default from SDK is {CoreController.DEFAULT_PORT}; "
            "many systems use 5000."
        ),
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds between reads (default: 1.0)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of reads; use 0 for infinite loop (default: 1)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    controller = CoreController(base_url=args.host, port=args.port)

    print(
        f"Connecting to Four9 Core Controller at "
        f"{args.host}:{args.port}/core-controller/v1/system"
    )

    try:
        if args.count == 0:
            while True:
                print_temperature_channels(controller)
                print("-" * 56)
                time.sleep(args.interval)
        else:
            for _ in range(args.count):
                print_temperature_channels(controller)
                print("-" * 56)
                if args.count > 1:
                    time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopped by user.")
        return 0
    except Exception as exc:
        print(f"Communication failed: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
