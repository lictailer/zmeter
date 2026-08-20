from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Mapping

from .models import (
    ChannelFilters,
    DeviceConfig,
    DriverConfigSpec,
    ProfileConfig,
    ProfilePaths,
)


SCHEMA_VERSION = 1
DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
DRIVER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
RESERVED_DEVICE_IDS = frozenset({"artificial_channel", "default"})


class ProfileValidationError(ValueError):
    """Raised only after all safely collectible profile errors are gathered."""

    def __init__(self, errors: list[str] | tuple[str, ...]):
        self.errors = tuple(errors)
        detail = "\n".join(f"- {error}" for error in self.errors)
        super().__init__(f"Invalid ZMeter profile:\n{detail}")


class _DuplicateJsonKeyError(ValueError):
    pass


def _object_without_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKeyError(f"duplicate JSON field '{key}'")
        result[key] = value
    return result


def repository_root_from_module() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_path(value: str, repository_root: Path) -> Path:
    if "\x00" in value:
        raise ValueError("path contains a null character")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repository_root / candidate
    # Normalize lexically. Path.resolve() can touch existing path components,
    # including mapped/network drives, which configuration validation must not
    # probe merely because a path is present in a profile.
    return Path(os.path.abspath(os.path.normpath(candidate)))


def _unexpected_fields(
    payload: Mapping[str, object],
    allowed: set[str],
    context: str,
    errors: list[str],
) -> None:
    for field in sorted(set(payload) - allowed):
        errors.append(f"{context} contains unsupported field '{field}'")


def _parse_configured_path(
    value: object,
    *,
    context: str,
    repository_root: Path,
    allow_none: bool,
    errors: list[str],
) -> Path | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        expected = "a non-empty path string or null" if allow_none else "a non-empty path string"
        errors.append(f"{context} must be {expected}")
        return None
    try:
        return _resolve_path(value.strip(), repository_root)
    except (OSError, ValueError) as exc:
        errors.append(f"{context} is invalid: {exc}")
        return None


def _parse_channel_filter(
    value: object,
    *,
    context: str,
    errors: list[str],
) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        errors.append(f"{context} must be a list of channel names or null")
        return None

    channels: list[str] = []
    for index, channel in enumerate(value):
        if not isinstance(channel, str) or not channel.strip():
            errors.append(f"{context}[{index}] must be a non-empty string")
            continue
        # Channel membership is deliberately not checked here. The approved
        # compatibility contract silently skips names a constructed device does
        # not expose, exactly as MainWindow.filter_scan_channels() does today.
        channels.append(channel.strip())
    return tuple(channels)


def _parse_connection(
    value: object,
    *,
    context: str,
    driver_spec: DriverConfigSpec | None,
    errors: list[str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        errors.append(f"{context} must be an object")
        return {}

    connection = dict(value)
    if driver_spec is None:
        return connection

    allowed_fields = set(driver_spec.connection_fields)
    for field in sorted(set(connection) - allowed_fields):
        errors.append(
            f"{context} contains unsupported field '{field}' for driver "
            f"'{driver_spec.driver_id}'"
        )

    for field, field_spec in driver_spec.connection_fields.items():
        if field not in connection:
            if field_spec.required:
                errors.append(f"{context}.{field} is required")
            continue
        if not field_spec.accepts(connection[field]):
            errors.append(
                f"{context}.{field} must be {field_spec.expected_type_names}"
            )
    return connection


def _parse_device(
    value: object,
    *,
    index: int,
    driver_specs: Mapping[str, DriverConfigSpec],
    errors: list[str],
) -> DeviceConfig | None:
    context = f"devices[{index}]"
    if not isinstance(value, dict):
        errors.append(f"{context} must be an object")
        return None

    _unexpected_fields(
        value,
        {"id", "driver", "enabled", "connect_on_start", "connection", "scan_channels"},
        context,
        errors,
    )

    device_id_value = value.get("id")
    if not isinstance(device_id_value, str) or not device_id_value.strip():
        errors.append(f"{context}.id must be a non-empty string")
        device_id = ""
    else:
        device_id = device_id_value.strip()
        if DEVICE_ID_PATTERN.fullmatch(device_id) is None:
            errors.append(
                f"{context}.id '{device_id}' may contain only letters, digits, "
                "underscores, and hyphens"
            )
        if device_id in RESERVED_DEVICE_IDS:
            errors.append(f"{context}.id '{device_id}' is reserved")

    driver_value = value.get("driver")
    if not isinstance(driver_value, str) or not driver_value.strip():
        errors.append(f"{context}.driver must be a non-empty string")
        driver_id = ""
    else:
        driver_id = driver_value.strip()
        if DRIVER_ID_PATTERN.fullmatch(driver_id) is None:
            errors.append(
                f"{context}.driver '{driver_id}' must be a lowercase registry ID"
            )

    driver_spec = driver_specs.get(driver_id)
    if driver_id and driver_spec is None:
        errors.append(f"{context}.driver '{driver_id}' is not registered")

    enabled_value = value.get("enabled")
    if type(enabled_value) is not bool:
        errors.append(f"{context}.enabled must be a boolean")
        enabled = False
    else:
        enabled = enabled_value

    connect_value = value.get("connect_on_start", False)
    if type(connect_value) is not bool:
        errors.append(f"{context}.connect_on_start must be a boolean")
        connect_on_start = False
    else:
        connect_on_start = connect_value

    if connect_on_start and not enabled:
        errors.append(f"{context}.connect_on_start cannot be true when disabled")
    if (
        connect_on_start
        and driver_spec is not None
        and not driver_spec.supports_startup_connection
    ):
        errors.append(
            f"{context}.driver '{driver_id}' does not support startup connection"
        )
    if enabled and driver_spec is not None and not driver_spec.available:
        reason = driver_spec.unavailable_reason.strip() or "driver is unavailable"
        errors.append(f"{context}.driver '{driver_id}' is unavailable: {reason}")

    connection = _parse_connection(
        value.get("connection"),
        context=f"{context}.connection",
        driver_spec=driver_spec,
        errors=errors,
    )

    scan_channels_value = value.get("scan_channels")
    if not isinstance(scan_channels_value, dict):
        errors.append(f"{context}.scan_channels must be an object")
        scan_channels: dict[str, object] = {}
    else:
        scan_channels = scan_channels_value
        _unexpected_fields(scan_channels, {"set", "get"}, f"{context}.scan_channels", errors)

    setters = _parse_channel_filter(
        scan_channels.get("set"),
        context=f"{context}.scan_channels.set",
        errors=errors,
    )
    getters = _parse_channel_filter(
        scan_channels.get("get"),
        context=f"{context}.scan_channels.get",
        errors=errors,
    )

    return DeviceConfig(
        id=device_id,
        driver=driver_id,
        enabled=enabled,
        connect_on_start=connect_on_start,
        connection=connection,
        scan_channels=ChannelFilters(setters=setters, getters=getters),
    )


def load_profile(
    profile_path: str | Path,
    *,
    driver_specs: Mapping[str, DriverConfigSpec],
    repository_root: str | Path | None = None,
) -> ProfileConfig:
    """Load one profile without importing or constructing a device driver."""

    root = Path(repository_root or repository_root_from_module()).resolve()
    source = Path(profile_path)
    if not source.is_absolute():
        source = root / source
    source = source.resolve(strict=False)

    try:
        with source.open("r", encoding="utf-8") as handle:
            payload = json.load(
                handle,
                object_pairs_hook=_object_without_duplicate_keys,
            )
    except FileNotFoundError as exc:
        raise ProfileValidationError([f"profile file not found: {source}"]) from exc
    except (OSError, json.JSONDecodeError, _DuplicateJsonKeyError) as exc:
        raise ProfileValidationError([f"profile file could not be read: {exc}"]) from exc

    if not isinstance(payload, dict):
        raise ProfileValidationError(["profile root must be an object"])

    errors: list[str] = []
    _unexpected_fields(
        payload,
        {"schema_version", "profile", "paths", "devices"},
        "profile root",
        errors,
    )

    schema_value = payload.get("schema_version")
    if type(schema_value) is not int:
        errors.append("schema_version must be an integer")
        schema_version = -1
    else:
        schema_version = schema_value
        if schema_version != SCHEMA_VERSION:
            errors.append(
                f"schema_version {schema_version} is unsupported; expected {SCHEMA_VERSION}"
            )

    profile_value = payload.get("profile")
    if not isinstance(profile_value, str) or not profile_value.strip():
        errors.append("profile must be a non-empty string")
        profile_name = ""
    else:
        profile_name = profile_value.strip()

    paths_value = payload.get("paths")
    if not isinstance(paths_value, dict):
        errors.append("paths must be an object")
        paths: dict[str, object] = {}
    else:
        paths = paths_value
        _unexpected_fields(paths, {"save", "backup"}, "paths", errors)

    save_path = _parse_configured_path(
        paths.get("save"),
        context="paths.save",
        repository_root=root,
        allow_none=False,
        errors=errors,
    )
    backup_path = _parse_configured_path(
        paths.get("backup"),
        context="paths.backup",
        repository_root=root,
        allow_none=True,
        errors=errors,
    )

    devices_value = payload.get("devices")
    if not isinstance(devices_value, list):
        errors.append("devices must be a list")
        device_values: list[object] = []
    else:
        device_values = devices_value

    indexed_devices: list[tuple[int, DeviceConfig]] = []
    for index, value in enumerate(device_values):
        device = _parse_device(
            value,
            index=index,
            driver_specs=driver_specs,
            errors=errors,
        )
        if device is not None:
            indexed_devices.append((index, device))

    seen_ids: dict[str, int] = {}
    for source_index, device in indexed_devices:
        if not device.id:
            continue
        if device.id in seen_ids:
            errors.append(
                f"devices[{source_index}].id duplicates "
                f"devices[{seen_ids[device.id]}].id "
                f"'{device.id}'"
            )
        else:
            seen_ids[device.id] = source_index

    if errors:
        raise ProfileValidationError(errors)

    assert save_path is not None
    return ProfileConfig(
        schema_version=schema_version,
        profile=profile_name,
        paths=ProfilePaths(save=save_path, backup=backup_path),
        devices=tuple(device for _, device in indexed_devices),
        source_path=source,
        repository_root=root,
    )
