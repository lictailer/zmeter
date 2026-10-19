from __future__ import annotations

import math
import threading
from importlib import import_module
from typing import Callable, Protocol


class _SampleApi(Protocol):
    def getTemperature(self) -> float: ...

    def setSetPoint(self, value: float) -> None: ...

    def startTempControl(self) -> None: ...


class _MagnetApi(Protocol):
    def getH(self, channel: int) -> float: ...

    def getHState(self, channel: int) -> str: ...

    def getFieldControl(self, channel: int) -> bool: ...

    def getIsInQuenchState(self) -> bool: ...

    def getNumberOfMagnetChannels(self) -> int: ...

    def setHSetPoint(self, channel: int, value: float) -> None: ...

    def startFieldControl(self, channel: int) -> None: ...


class _AttoDryApi(Protocol):
    sample: _SampleApi
    magnet: _MagnetApi

    def connect(self) -> None: ...

    def close(self) -> None: ...


DeviceFactory = Callable[[str], _AttoDryApi]


class AttoDryHardware:
    """Serialized, validated access to one attoDRY2100 controller."""

    MIN_TEMPERATURE_K = 1.8
    MAX_TEMPERATURE_K = 300.0
    MIN_FIELD_T = -9.0
    MAX_FIELD_T = 9.0
    MAGNET_CHANNEL = 0

    def __init__(self, device_factory: DeviceFactory | None = None) -> None:
        self._device_factory = device_factory or self._default_device_factory
        self._lock = threading.RLock()
        self._device: _AttoDryApi | None = None
        self._address = ""
        self._magnet_channels = 0

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._device is not None

    @property
    def address(self) -> str:
        with self._lock:
            return self._address

    @property
    def magnet_channels(self) -> int:
        with self._lock:
            return self._magnet_channels

    @staticmethod
    def _default_device_factory(address: str) -> _AttoDryApi:
        try:
            package = import_module("atto_device")
        except (ImportError, ModuleNotFoundError) as exc:
            raise RuntimeError(
                "The optional atto_device 1.12.0 package is not installed. "
                "Install the vendor-supplied Python wheel before connecting."
            ) from exc
        factory = getattr(package, "CRYO2100", None)
        if factory is None:
            raise RuntimeError(
                "The installed atto_device package does not provide CRYO2100."
            )
        return factory(address)

    @staticmethod
    def _validated_address(address: object) -> str:
        normalized = str(address).strip()
        if not normalized:
            raise ValueError("attoDRY address must not be blank")
        if any(character.isspace() for character in normalized):
            raise ValueError("attoDRY address must not contain whitespace")
        if "://" in normalized or "/" in normalized:
            raise ValueError(
                "attoDRY address must be a host name or IP address without a URL scheme"
            )
        return normalized

    @staticmethod
    def _finite_in_range(
        value: object,
        *,
        name: str,
        low: float,
        high: float,
        unit: str,
    ) -> float:
        try:
            normalized = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a number in {unit}") from exc
        if not math.isfinite(normalized):
            raise ValueError(f"{name} must be finite")
        if not low <= normalized <= high:
            raise ValueError(
                f"{name} must be between {low:g} and {high:g} {unit}"
            )
        return normalized

    def _require_device(self) -> _AttoDryApi:
        if self._device is None:
            raise RuntimeError("attoDRY is not connected")
        return self._device

    def connect(self, address: object) -> bool:
        normalized = self._validated_address(address)
        with self._lock:
            if self._device is not None:
                if normalized == self._address:
                    return True
                raise RuntimeError(
                    "attoDRY is already connected; disconnect before changing address"
                )

            device = self._device_factory(normalized)
            try:
                device.connect()
                channel_count = int(device.magnet.getNumberOfMagnetChannels())
                if channel_count <= self.MAGNET_CHANNEL:
                    raise RuntimeError(
                        "controller reported no usable magnet channel at index 0"
                    )
                temperature = float(device.sample.getTemperature())
                field = float(device.magnet.getH(self.MAGNET_CHANNEL))
                if not math.isfinite(temperature) or not math.isfinite(field):
                    raise RuntimeError(
                        "controller returned a non-finite initial readback"
                    )
            except Exception:
                try:
                    device.close()
                except Exception:
                    pass
                raise

            self._device = device
            self._address = normalized
            self._magnet_channels = channel_count
            return True

    def disconnect(self) -> bool:
        with self._lock:
            device = self._device
            if device is None:
                return True
            try:
                device.close()
            finally:
                self._device = None
                self._address = ""
                self._magnet_channels = 0
            return True

    def read_temperature_k(self) -> float:
        with self._lock:
            value = float(self._require_device().sample.getTemperature())
        if not math.isfinite(value):
            raise RuntimeError("attoDRY returned a non-finite sample temperature")
        return value

    def read_field_t(self) -> float:
        with self._lock:
            value = float(
                self._require_device().magnet.getH(self.MAGNET_CHANNEL)
            )
        if not math.isfinite(value):
            raise RuntimeError("attoDRY returned a non-finite magnetic field")
        return value

    def read_field_state(self) -> str:
        with self._lock:
            return str(
                self._require_device().magnet.getHState(self.MAGNET_CHANNEL)
            )

    def field_control_active(self) -> bool:
        with self._lock:
            return bool(
                self._require_device().magnet.getFieldControl(
                    self.MAGNET_CHANNEL
                )
            )

    def magnet_quenched(self) -> bool:
        with self._lock:
            return bool(self._require_device().magnet.getIsInQuenchState())

    def set_temperature_k(self, target_k: object) -> float:
        target = self._finite_in_range(
            target_k,
            name="sample temperature",
            low=self.MIN_TEMPERATURE_K,
            high=self.MAX_TEMPERATURE_K,
            unit="K",
        )
        with self._lock:
            sample = self._require_device().sample
            sample.setSetPoint(target)
            try:
                sample.startTempControl()
            except Exception as exc:
                raise RuntimeError(
                    "sample setpoint may have changed, but starting temperature "
                    "control failed; controller state is uncertain"
                ) from exc
        return target

    def set_field_t(self, target_t: object) -> float:
        target = self._finite_in_range(
            target_t,
            name="magnetic field",
            low=self.MIN_FIELD_T,
            high=self.MAX_FIELD_T,
            unit="T",
        )
        with self._lock:
            magnet = self._require_device().magnet
            if bool(magnet.getIsInQuenchState()):
                raise RuntimeError(
                    "attoDRY magnet reports a quench; field control was not started"
                )
            magnet.setHSetPoint(self.MAGNET_CHANNEL, target)
            try:
                magnet.startFieldControl(self.MAGNET_CHANNEL)
            except Exception as exc:
                raise RuntimeError(
                    "field setpoint may have changed, but starting field control "
                    "failed; controller state is uncertain"
                ) from exc
        return target
