from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_value(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(item) for item in value)
    return value


def _immutable_mapping(values: Mapping[str, Any]) -> Mapping[str, Any]:
    return _freeze_value(values)


@dataclass(frozen=True, slots=True)
class ConnectionFieldSpec:
    """Pure validation metadata for one driver connection field."""

    value_types: tuple[type, ...]
    required: bool = False
    allow_none: bool = False

    def accepts(self, value: object) -> bool:
        if value is None:
            return self.allow_none
        return type(value) in self.value_types

    @property
    def expected_type_names(self) -> str:
        names = [value_type.__name__ for value_type in self.value_types]
        if self.allow_none:
            names.append("null")
        return " or ".join(names)


@dataclass(frozen=True, slots=True)
class DriverConfigSpec:
    """Side-effect-free configuration contract published by a registry entry."""

    driver_id: str
    connection_fields: Mapping[str, ConnectionFieldSpec]
    available: bool = True
    unavailable_reason: str = ""
    supports_startup_connection: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "connection_fields",
            _immutable_mapping(self.connection_fields),
        )


@dataclass(frozen=True, slots=True)
class ProfilePaths:
    save: Path
    backup: Path | None


@dataclass(frozen=True, slots=True)
class ChannelFilters:
    setters: tuple[str, ...] | None
    getters: tuple[str, ...] | None

    def __post_init__(self) -> None:
        for field_name in ("setters", "getters"):
            value = getattr(self, field_name)
            if value is None:
                continue
            if isinstance(value, (str, bytes)):
                raise TypeError(
                    f"channel filter '{field_name}' must be an iterable of names"
                )
            try:
                items = tuple(value)
            except TypeError as exc:
                raise TypeError(
                    f"channel filter '{field_name}' must be an iterable of names"
                ) from exc
            normalized = []
            for item in items:
                if not isinstance(item, str) or not item.strip():
                    raise ValueError(
                        f"channel filter '{field_name}' entries must be "
                        "non-empty strings"
                    )
                normalized.append(item.strip())
            object.__setattr__(self, field_name, tuple(normalized))


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    id: str
    driver: str
    enabled: bool
    connect_on_start: bool
    connection: Mapping[str, object]
    scan_channels: ChannelFilters

    def __post_init__(self) -> None:
        if not isinstance(self.connection, Mapping):
            raise TypeError("device connection must be a mapping")
        if not isinstance(self.scan_channels, ChannelFilters):
            raise TypeError("device scan_channels must be ChannelFilters")
        object.__setattr__(self, "connection", _immutable_mapping(self.connection))


@dataclass(frozen=True, slots=True)
class ProfileConfig:
    schema_version: int
    profile: str
    paths: ProfilePaths
    devices: tuple[DeviceConfig, ...]
    source_path: Path
    repository_root: Path
