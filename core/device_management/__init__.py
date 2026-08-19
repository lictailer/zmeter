"""Validated device configuration and lifecycle ownership for ZMeter."""

from .config import ProfileValidationError, load_profile
from .models import (
    ChannelFilters,
    ConnectionFieldSpec,
    DeviceConfig,
    DriverConfigSpec,
    ProfileConfig,
    ProfilePaths,
)
from .registry import (
    DisabledDeviceError,
    DriverAdapter,
    DriverConstructionError,
    DriverConfigurationError,
    DriverRegistration,
    DriverRegistry,
    DriverRegistryError,
    DriverTerminatedError,
    DriverUnavailableError,
    DuplicateDriverError,
    LifecycleUnsupportedError,
    UnknownDriverError,
    build_default_registry,
)

__all__ = [
    "ChannelFilters",
    "ConnectionFieldSpec",
    "DeviceConfig",
    "DisabledDeviceError",
    "DriverAdapter",
    "DriverConfigSpec",
    "DriverConstructionError",
    "DriverConfigurationError",
    "DriverRegistration",
    "DriverRegistry",
    "DriverRegistryError",
    "DriverTerminatedError",
    "DriverUnavailableError",
    "DuplicateDriverError",
    "LifecycleUnsupportedError",
    "ProfileConfig",
    "ProfilePaths",
    "ProfileValidationError",
    "UnknownDriverError",
    "build_default_registry",
    "load_profile",
]
