"""Lightweight hardware layer for Four9 Core Controller.

Scope for this layer:
1. Set target temperature for channels CH00-CH05.
2. Read temperature for channels CH00-CH05.
3. Read heater power for channels CH00-CH05.
"""

from __future__ import annotations

from typing import List, Tuple

try:
    # When used as package import: from four9.four9_hardware import Four9Hardware
    from .core_controller import CoreController
except ImportError:
    # When run directly from this directory
    from core_controller import CoreController


class Four9Hardware:
    CHANNEL_MIN = 0
    CHANNEL_MAX = 5

    def __init__(self) -> None:
        self.is_connected = False
        self.base_url = CoreController.DEFAULT_BASE_URL
        self.port = CoreController.DEFAULT_PORT
        self.controller: CoreController | None = None

    def connect_hardware(
        self,
        base_url: str = CoreController.DEFAULT_BASE_URL,
        port: int = CoreController.DEFAULT_PORT,
    ) -> bool:
        """Create controller client and verify communication via /system read."""
        self.base_url = base_url
        self.port = int(port)
        self.controller = CoreController(base_url=self.base_url, port=self.port)

        try:
            self.controller.read_system()
        except Exception as exc:
            print(
                f"Failed to connect to Four9 Core Controller at "
                f"{self.base_url}:{self.port}: {exc}"
            )
            self.is_connected = False
            return False

        self.is_connected = True
        print(f"Connected to Four9 Core Controller at {self.base_url}:{self.port}")
        return True

    def disconnect(self) -> None:
        # HTTP client is stateless here, so disconnect just clears local state.
        self.controller = None
        self.is_connected = False

    def set_target_temperature(self, channel: int, target_temperature: float) -> None:
        self._ensure_connected()
        channel = self._validate_channel(channel)
        assert self.controller is not None
        self.controller.set_target_temperature(channel, float(target_temperature))

    def read_temperature(self, channel: int) -> float:
        self._ensure_connected()
        channel = self._validate_channel(channel)
        assert self.controller is not None
        thermometer = self.controller.read_thermometer(channel)
        return float(thermometer.temperature)

    def read_heater_power(self, channel: int) -> float:
        self._ensure_connected()
        channel = self._validate_channel(channel)
        assert self.controller is not None
        heater = self.controller.read_heater(channel)
        return float(heater.power)

    def read_all_temperatures(self) -> List[float]:
        self._ensure_connected()
        assert self.controller is not None
        system = self.controller.read_system()
        return [
            float(system.thermometers[index].temperature)
            for index in range(self.CHANNEL_MIN, self.CHANNEL_MAX + 1)
        ]

    def read_all_heater_powers(self) -> List[float]:
        self._ensure_connected()
        assert self.controller is not None
        system = self.controller.read_system()
        return [
            float(system.heaters[index].power)
            for index in range(self.CHANNEL_MIN, self.CHANNEL_MAX + 1)
        ]

    def read_all_temperatures_and_heater_powers(self) -> Tuple[List[float], List[float]]:
        """Read both arrays using one /system request."""
        self._ensure_connected()
        assert self.controller is not None
        system = self.controller.read_system()

        temperatures = [
            float(system.thermometers[index].temperature)
            for index in range(self.CHANNEL_MIN, self.CHANNEL_MAX + 1)
        ]
        heater_powers = [
            float(system.heaters[index].power)
            for index in range(self.CHANNEL_MIN, self.CHANNEL_MAX + 1)
        ]
        return temperatures, heater_powers

    def _ensure_connected(self) -> None:
        if not self.is_connected or self.controller is None:
            raise RuntimeError("Four9 is not connected. Call connect_hardware() first.")

    def _validate_channel(self, channel: int) -> int:
        channel = int(channel)
        if not (self.CHANNEL_MIN <= channel <= self.CHANNEL_MAX):
            raise ValueError(
                f"Channel index must be in range {self.CHANNEL_MIN}-{self.CHANNEL_MAX}, got {channel}."
            )
        return channel


if __name__ == "__main__":
    hardware = Four9Hardware()

    # Update port as needed for your Core Controller scripting setup.
    hardware.connect_hardware(base_url="http://localhost", port=4949)

    temperatures, heater_powers = hardware.read_all_temperatures_and_heater_powers()
    print("Temperatures CH00-CH05:", temperatures)
    print("Heater power CH00-CH05:", heater_powers)
