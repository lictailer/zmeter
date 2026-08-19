"""Immutable channel catalog snapshots published by :mod:`core.mainWindow`."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType


ChannelCallable = Callable[..., object]


class DeviceCatalogError(RuntimeError):
    """Base error for a refused or failed catalog replacement."""


class DeviceCatalogReferenceError(DeviceCatalogError):
    """Raised when a replacement would invalidate an open UI reference."""

    def __init__(
        self,
        removed_setters: set[str],
        removed_getters: set[str],
        references: tuple[str, ...],
        removed_labels: set[str] | None = None,
    ) -> None:
        self.removed_setters = frozenset(removed_setters)
        self.removed_getters = frozenset(removed_getters)
        self.references = tuple(references)
        self.removed_labels = frozenset(removed_labels or ())
        super().__init__(
            "catalog replacement refused because open configuration references "
            f"would become unavailable: {', '.join(self.references)}"
        )


class DeviceCatalogBusyError(DeviceCatalogError):
    """Raised when workers could still hold callables from the current catalog."""

    def __init__(self, blockers: tuple[str, ...]) -> None:
        self.blockers = tuple(blockers)
        super().__init__(
            "device catalog replacement requires an idle scan system: "
            + ", ".join(self.blockers)
        )


class DeviceCatalogRollbackError(DeviceCatalogError):
    """Raised after all rollback steps were attempted but at least one failed."""

    def __init__(self, apply_error: Exception, failures) -> None:
        self.apply_error = apply_error
        self.failures = tuple(failures)
        details = "; ".join(
            f"{operation}: {type(error).__name__}: {error}"
            for operation, error in self.failures
        )
        super().__init__(
            f"catalog application failed ({type(apply_error).__name__}: "
            f"{apply_error}); rollback failures: {details}"
        )


def _freeze_callable_maps(
    values: Mapping[str, Mapping[str, ChannelCallable]],
) -> Mapping[str, Mapping[str, ChannelCallable]]:
    return MappingProxyType(
        {
            device_label: MappingProxyType(dict(channel_map))
            for device_label, channel_map in values.items()
        }
    )


def _freeze_channel_maps(
    values: Mapping[str, tuple[str, ...] | list[str]],
) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType(
        {
            device_label: tuple(channel_names)
            for device_label, channel_names in values.items()
        }
    )


def _freeze_filters(
    values: Mapping[str, tuple[str, ...] | None],
) -> Mapping[str, tuple[str, ...] | None]:
    return MappingProxyType(
        {
            device_label: (
                None if channel_filter is None else tuple(channel_filter)
            )
            for device_label, channel_filter in values.items()
        }
    )


def _freeze_router_catalog(
    values: Mapping[str, Mapping[str, tuple[str, ...] | list[str]]],
) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
    return MappingProxyType(
        {
            device_label: MappingProxyType(
                {
                    "readable": tuple(channel_info.get("readable", ())),
                    "writable": tuple(channel_info.get("writable", ())),
                }
            )
            for device_label, channel_info in values.items()
        }
    )


def _freeze_scan_range_limits(
    values: Mapping[tuple[str, str], tuple[float, float]],
) -> Mapping[tuple[str, str], tuple[float, float]]:
    return MappingProxyType(
        {
            (str(device_label), str(channel_name)): (
                float(bounds[0]),
                float(bounds[1]),
            )
            for (device_label, channel_name), bounds in values.items()
        }
    )


@dataclass(frozen=True, slots=True)
class DeviceCatalogSnapshot:
    """A complete, detached view of every MainWindow device/catalog mapping.

    The contained mappings are copied and recursively made read-only. Bound
    methods and device instances intentionally retain their identities so scan
    and router calls reach the manager-owned objects represented by this exact
    snapshot.
    """

    profile_name: str
    equipment: Mapping[str, object]
    setter_filters: Mapping[str, tuple[str, ...] | None]
    getter_filters: Mapping[str, tuple[str, ...] | None]
    setter_callables: Mapping[str, Mapping[str, ChannelCallable]]
    getter_callables: Mapping[str, Mapping[str, ChannelCallable]]
    setter_channels: Mapping[str, tuple[str, ...] | list[str]]
    getter_channels: Mapping[str, tuple[str, ...] | list[str]]
    router_catalog: Mapping[
        str,
        Mapping[str, tuple[str, ...] | list[str]],
    ]
    active_scan_range_limits: Mapping[
        tuple[str, str],
        tuple[float, float],
    ]

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile_name", str(self.profile_name))
        object.__setattr__(
            self,
            "equipment",
            MappingProxyType(dict(self.equipment)),
        )
        object.__setattr__(
            self,
            "setter_filters",
            _freeze_filters(self.setter_filters),
        )
        object.__setattr__(
            self,
            "getter_filters",
            _freeze_filters(self.getter_filters),
        )
        object.__setattr__(
            self,
            "setter_callables",
            _freeze_callable_maps(self.setter_callables),
        )
        object.__setattr__(
            self,
            "getter_callables",
            _freeze_callable_maps(self.getter_callables),
        )
        object.__setattr__(
            self,
            "setter_channels",
            _freeze_channel_maps(self.setter_channels),
        )
        object.__setattr__(
            self,
            "getter_channels",
            _freeze_channel_maps(self.getter_channels),
        )
        object.__setattr__(
            self,
            "router_catalog",
            _freeze_router_catalog(self.router_catalog),
        )
        object.__setattr__(
            self,
            "active_scan_range_limits",
            _freeze_scan_range_limits(self.active_scan_range_limits),
        )
