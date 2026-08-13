from __future__ import annotations

from collections.abc import Callable

from .mock_device_simulator import MockDeviceSimulator


class MockDeviceHardware:
    """Thin hardware-style adapter around the simulated device."""

    def __init__(self, simulator: MockDeviceSimulator | None = None):
        self.simulator = simulator or MockDeviceSimulator()

    @property
    def connected(self) -> bool:
        return self.simulator.connected

    @property
    def command_log(self) -> tuple[str, ...]:
        return self.simulator.command_log

    @property
    def ramp_active(self) -> bool:
        return self.simulator.ramp_active

    def connect(self, address: str) -> str:
        return self.simulator.connect(address)

    def disconnect(self) -> None:
        self.simulator.disconnect()

    def reset(self) -> None:
        self.simulator.reset()

    def start_scan(self) -> None:
        self.simulator.start_scan()

    def stop_scan(self) -> None:
        self.simulator.stop_scan()

    def force_stop(self) -> bool:
        return self.simulator.force_stop()

    def set_channel_A(self, value: float) -> float:
        return self.simulator.set_channel("A", value)

    def set_channel_B(self, value: float) -> float:
        return self.simulator.set_channel("B", value)

    def read_channel_A(self) -> float:
        return self.simulator.read_channel("A")

    def read_channel_B(self) -> float:
        return self.simulator.read_channel("B")

    def read_random_channel(self) -> float:
        return self.simulator.read_random_channel()

    def ramp_channel_A(
        self,
        target: float,
        progress_callback: Callable[[float], None] | None = None,
    ) -> tuple[float, bool]:
        return self.simulator.ramp_channel("A", target, progress_callback)

    def ramp_channel_B(
        self,
        target: float,
        progress_callback: Callable[[float], None] | None = None,
    ) -> tuple[float, bool]:
        return self.simulator.ramp_channel("B", target, progress_callback)

    def activate_fail_after(self, command_count: int) -> None:
        self.simulator.activate_fail_after(command_count)

    def stop_fail_after(self) -> None:
        self.simulator.stop_fail_after()

    def activate_random_failure(self, probability: float) -> None:
        self.simulator.activate_random_failure(probability)

    def stop_random_failure(self) -> None:
        self.simulator.stop_random_failure()

    def activate_range_rejection(self) -> None:
        self.simulator.activate_range_rejection()

    def stop_range_rejection(self) -> None:
        self.simulator.stop_range_rejection()
