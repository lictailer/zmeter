from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from types import MappingProxyType
from typing import Callable, Mapping

from .models import ConnectionFieldSpec, DeviceConfig, DriverConfigSpec


DeviceFactory = Callable[..., object]
ConnectionAction = Callable[[object, Mapping[str, object]], object]
LifecycleAction = Callable[[object], object]
StateProbe = Callable[[object], bool]


class DriverRegistryError(RuntimeError):
    pass


class DuplicateDriverError(DriverRegistryError):
    pass


class UnknownDriverError(DriverRegistryError):
    pass


class DisabledDeviceError(DriverRegistryError):
    pass


class DriverUnavailableError(DriverRegistryError):
    pass


class DriverConstructionError(DriverRegistryError):
    pass


class DriverConfigurationError(DriverRegistryError):
    pass


class LifecycleUnsupportedError(DriverRegistryError):
    pass


class DriverTerminatedError(DriverRegistryError):
    pass


def _thaw_json_value(value):
    if isinstance(value, Mapping):
        return {key: _thaw_json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json_value(item) for item in value]
    return value


@dataclass(frozen=True, slots=True)
class DriverRegistration:
    """Code-reviewed factory and lifecycle contract for one stable driver ID."""

    config_spec: DriverConfigSpec
    factory: DeviceFactory
    terminate: LifecycleAction
    runtime_services: tuple[str, ...] = ()
    connect: ConnectionAction | None = None
    disconnect: LifecycleAction | None = None
    start_scan: LifecycleAction | None = None
    stop_scan: LifecycleAction | None = None
    force_stop: LifecycleAction | None = None
    close_widget: LifecycleAction | None = None
    is_busy: StateProbe | None = None
    is_connected: StateProbe | None = None
    runtime_mutation_allowed: bool = False

    @property
    def driver_id(self) -> str:
        return self.config_spec.driver_id

    def __post_init__(self) -> None:
        object.__setattr__(self, "runtime_services", tuple(self.runtime_services))
        if not self.driver_id:
            raise ValueError("driver registration requires a stable driver ID")
        if len(set(self.runtime_services)) != len(self.runtime_services):
            raise ValueError(
                f"driver '{self.driver_id}' declares a runtime service more than once"
            )
        for service_name in self.runtime_services:
            if not service_name.isidentifier() or service_name.startswith("_"):
                raise ValueError(
                    f"driver '{self.driver_id}' has invalid runtime service "
                    f"'{service_name}'"
                )
        if self.runtime_mutation_allowed and self.is_busy is None:
            raise ValueError(
                f"runtime-mutable driver '{self.driver_id}' must provide an "
                "explicit reviewed is_busy probe"
            )


class DriverAdapter:
    """One constructed instance behind its reviewed lifecycle callbacks."""

    def __init__(
        self,
        registration: DriverRegistration,
        config: DeviceConfig,
        instance: object,
    ) -> None:
        self.registration = registration
        self.config = config
        self.instance = instance
        self._lifecycle_lock = RLock()
        self._terminated = False
        self._closed = False
        self._termination_error: Exception | None = None
        self._close_error: Exception | None = None

    @property
    def driver_id(self) -> str:
        return self.registration.driver_id

    @property
    def device_id(self) -> str:
        return self.config.id

    @property
    def terminated(self) -> bool:
        return self._terminated

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def termination_error(self) -> Exception | None:
        return self._termination_error

    @property
    def close_error(self) -> Exception | None:
        return self._close_error

    def _require_active(self, action_name: str) -> None:
        if self._terminated:
            raise DriverTerminatedError(
                f"device '{self.device_id}' cannot {action_name} after termination"
            )

    def connect(self):
        with self._lifecycle_lock:
            self._require_active("connect")
            action = self.registration.connect
            if action is None:
                raise LifecycleUnsupportedError(
                    f"driver '{self.driver_id}' does not support manager connection"
                )
            connection = _thaw_json_value(self.config.connection)
            return action(self.instance, connection)

    def disconnect(self):
        with self._lifecycle_lock:
            self._require_active("disconnect")
            action = self.registration.disconnect
            if action is None:
                raise LifecycleUnsupportedError(
                    f"driver '{self.driver_id}' does not support manager disconnection"
                )
            return action(self.instance)

    def start_scan(self):
        with self._lifecycle_lock:
            self._require_active("start scan activity")
            action = self.registration.start_scan
            if action is not None:
                return action(self.instance)
            return None

    def stop_scan(self):
        with self._lifecycle_lock:
            self._require_active("stop scan activity")
            action = self.registration.stop_scan
            if action is not None:
                return action(self.instance)
            return None

    def force_stop(self):
        with self._lifecycle_lock:
            self._require_active("request force stop")
            action = self.registration.force_stop
            if action is not None:
                return action(self.instance)
            return None

    def terminate(self):
        with self._lifecycle_lock:
            if self._terminated:
                return None
            # Block every later lifecycle call before invoking potentially
            # partial teardown. A failed callback is not retried implicitly;
            # retry safety belongs to the reviewed driver lifecycle contract.
            self._terminated = True
            try:
                return self.registration.terminate(self.instance)
            except Exception as exc:
                self._termination_error = exc
                raise

    def close(self):
        with self._lifecycle_lock:
            if self._closed:
                return None
            # Closing a Qt/native object can partially release resources before
            # raising. Treat it as a one-attempt teardown operation, just like
            # terminate(), so repeated shutdown cannot double-close the object.
            self._closed = True
            action = self.registration.close_widget
            try:
                if action is not None:
                    return action(self.instance)
                close = getattr(self.instance, "close", None)
                return close() if callable(close) else None
            except Exception as exc:
                self._close_error = exc
                raise

    def busy(self) -> bool:
        with self._lifecycle_lock:
            if self._terminated:
                return False
            probe = self.registration.is_busy
            return bool(probe(self.instance)) if probe is not None else False

    def connected(self) -> bool:
        with self._lifecycle_lock:
            if self._terminated:
                return False
            probe = self.registration.is_connected
            return bool(probe(self.instance)) if probe is not None else False


class DriverRegistry:
    def __init__(self, registrations=()) -> None:
        self._registrations: dict[str, DriverRegistration] = {}
        for registration in registrations:
            self.register(registration)

    def register(self, registration: DriverRegistration) -> None:
        driver_id = registration.driver_id
        if driver_id in self._registrations:
            raise DuplicateDriverError(f"driver '{driver_id}' is already registered")
        self._registrations[driver_id] = registration

    @property
    def driver_ids(self) -> tuple[str, ...]:
        return tuple(self._registrations)

    @property
    def config_specs(self) -> Mapping[str, DriverConfigSpec]:
        return MappingProxyType(
            {
                driver_id: registration.config_spec
                for driver_id, registration in self._registrations.items()
            }
        )

    def registration(self, driver_id: str) -> DriverRegistration:
        try:
            return self._registrations[driver_id]
        except KeyError:
            raise UnknownDriverError(
                f"driver '{driver_id}' is not registered"
            ) from None

    def create(self, config: DeviceConfig, runtime_services: object) -> DriverAdapter:
        if not config.enabled:
            raise DisabledDeviceError(
                f"device '{config.id}' is disabled and will not be constructed"
            )

        registration = self.registration(config.driver)
        self._validate_config(config, registration.config_spec)
        if not registration.config_spec.available:
            reason = (
                registration.config_spec.unavailable_reason.strip()
                or "driver is unavailable"
            )
            raise DriverUnavailableError(
                f"driver '{config.driver}' is unavailable: {reason}"
            )

        runtime_kwargs = {}
        for service_name in registration.runtime_services:
            try:
                runtime_kwargs[service_name] = getattr(
                    runtime_services,
                    service_name,
                )
            except AttributeError:
                raise DriverConstructionError(
                    f"driver '{config.driver}' requires runtime service "
                    f"'{service_name}'"
                ) from None

        try:
            instance = registration.factory(**runtime_kwargs)
        except (ImportError, ModuleNotFoundError) as exc:
            raise DriverUnavailableError(
                f"driver '{config.driver}' could not load an optional dependency: "
                f"{exc}"
            ) from exc
        except Exception as exc:
            raise DriverConstructionError(
                f"device '{config.id}' construction failed for driver "
                f"'{config.driver}': {type(exc).__name__}: {exc}"
            ) from exc

        return DriverAdapter(registration, config, instance)

    @staticmethod
    def _validate_config(
        config: DeviceConfig,
        config_spec: DriverConfigSpec,
    ) -> None:
        connection = _thaw_json_value(config.connection)
        allowed_fields = set(config_spec.connection_fields)
        unexpected = sorted(set(connection) - allowed_fields)
        if unexpected:
            fields = ", ".join(repr(field) for field in unexpected)
            raise DriverConfigurationError(
                f"device '{config.id}' has unsupported connection field(s) "
                f"for driver '{config.driver}': {fields}"
            )

        for field, field_spec in config_spec.connection_fields.items():
            if field not in connection:
                if field_spec.required:
                    raise DriverConfigurationError(
                        f"device '{config.id}' requires connection field '{field}'"
                    )
                continue
            if not field_spec.accepts(connection[field]):
                raise DriverConfigurationError(
                    f"device '{config.id}' connection field '{field}' must be "
                    f"{field_spec.expected_type_names}"
                )


def _create_mock_device():
    from mockDevice.mock_device_main import MockDevice

    return MockDevice()


def _mock_connect(instance, connection):
    return instance.connect(**connection)


def _mock_disconnect(instance):
    return instance.disconnect()


def _mock_start_scan(instance):
    return instance.start_scan()


def _mock_stop_scan(instance):
    return instance.stop_scan()


def _mock_force_stop(instance):
    return instance.force_stop()


def _mock_terminate(instance):
    return instance.terminate_dev()


def _mock_is_busy(instance) -> bool:
    return bool(instance.logic.is_busy())


def _mock_is_connected(instance) -> bool:
    return bool(instance.logic.hardware.connected)


def mock_device_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="mock_device",
            connection_fields={
                "address": ConnectionFieldSpec((str,)),
            },
        ),
        factory=_create_mock_device,
        connect=_mock_connect,
        disconnect=_mock_disconnect,
        start_scan=_mock_start_scan,
        stop_scan=_mock_stop_scan,
        force_stop=_mock_force_stop,
        terminate=_mock_terminate,
        is_busy=_mock_is_busy,
        is_connected=_mock_is_connected,
        runtime_mutation_allowed=True,
    )


def build_default_registry() -> DriverRegistry:
    """Return reviewed registrations without importing any device package."""

    return DriverRegistry((mock_device_registration(),))
