from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import RLock, get_ident
from types import MappingProxyType
from typing import Mapping

from .models import DeviceConfig, ProfileConfig
from .registry import DriverAdapter, DriverRegistry


class DeviceState(str, Enum):
    """Manager-owned lifecycle state for one configured device."""

    DISABLED = "disabled"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"
    REMOVING = "removing"
    REMOVED = "removed"


@dataclass(frozen=True, slots=True)
class LifecycleFailure:
    device_id: str
    action: str
    error_type: str
    message: str

    @classmethod
    def from_exception(
        cls,
        device_id: str,
        action: str,
        error: Exception,
    ) -> "LifecycleFailure":
        return cls(
            device_id=device_id,
            action=action,
            error_type=type(error).__name__,
            message=str(error),
        )

    def describe(self) -> str:
        detail = f": {self.message}" if self.message else ""
        return (
            f"device '{self.device_id}' {self.action} failed "
            f"({self.error_type}{detail})"
        )


@dataclass(frozen=True, slots=True)
class LifecycleReport:
    operation: str
    failures: tuple[LifecycleFailure, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "failures", tuple(self.failures))

    @property
    def succeeded(self) -> bool:
        return not self.failures

    def __bool__(self) -> bool:
        return self.succeeded


class DeviceManagerError(RuntimeError):
    pass


class DeviceManagerLoadError(DeviceManagerError):
    pass


class DeviceManagerTerminatedError(DeviceManagerError):
    """Raised when a lifecycle call reaches a sealed manager."""


class DeviceManagerThreadError(DeviceManagerError):
    """Raised when UI-owned construction or teardown runs off its owner thread."""


class DeviceLifecycleError(DeviceManagerError):
    """One manager-wide lifecycle operation completed with failures."""

    def __init__(self, report: LifecycleReport) -> None:
        self.report = report
        details = "; ".join(failure.describe() for failure in report.failures)
        super().__init__(f"{report.operation} failed: {details}")


class DeviceStartupError(DeviceManagerError):
    """Startup failed and every already-created adapter was torn down."""

    def __init__(
        self,
        failure: LifecycleFailure,
        cleanup_report: LifecycleReport,
    ) -> None:
        self.failure = failure
        self.cleanup_report = cleanup_report
        details = [failure.describe()]
        details.extend(
            f"rollback: {cleanup_failure.describe()}"
            for cleanup_failure in cleanup_report.failures
        )
        super().__init__("; ".join(details))

    @property
    def failures(self) -> tuple[LifecycleFailure, ...]:
        return (self.failure, *self.cleanup_report.failures)


@dataclass(frozen=True, slots=True)
class DeviceRecordView:
    """Stable immutable view of one mutable manager-owned record."""

    device_id: str
    driver_id: str
    state: DeviceState
    instance: object
    connect_on_start: bool
    setter_filter: tuple[str, ...] | None
    getter_filter: tuple[str, ...] | None
    error: str | None


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """Ordered inputs consumed by the existing static MainWindow catalogs."""

    profile_name: str
    records: tuple[DeviceRecordView, ...]
    equipment: Mapping[str, object]
    setter_filters: Mapping[str, tuple[str, ...] | None]
    getter_filters: Mapping[str, tuple[str, ...] | None]

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(
            self,
            "equipment",
            MappingProxyType(dict(self.equipment)),
        )
        object.__setattr__(
            self,
            "setter_filters",
            MappingProxyType(dict(self.setter_filters)),
        )
        object.__setattr__(
            self,
            "getter_filters",
            MappingProxyType(dict(self.getter_filters)),
        )


@dataclass(slots=True)
class _DeviceRecord:
    config: DeviceConfig
    adapter: DriverAdapter
    state: DeviceState = DeviceState.DISCONNECTED
    error: str | None = None


class DeviceManager:
    """Own a static, profile-ordered set of device adapters.

    Phase 3 deliberately supports one transactional profile load and final
    teardown only. Construction and final QWidget teardown stay on the thread
    that creates the manager. The existing scan start/stop/force calls retain
    their current worker-thread ownership and are serialized by the manager
    lock. Runtime add/remove operations arrive only after catalog consumers
    become rebuildable.
    """

    def __init__(self, registry: DriverRegistry, runtime_services: object) -> None:
        self._registry = registry
        self._runtime_services = runtime_services
        self._lock = RLock()
        self._records: dict[str, _DeviceRecord] = {}
        self._profile_name = ""
        self._load_attempted = False
        self._loaded = False
        self._teardown_report: LifecycleReport | None = None
        self._owner_thread_id = get_ident()

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._loaded

    @property
    def teardown_report(self) -> LifecycleReport | None:
        with self._lock:
            return self._teardown_report

    def load_profile(self, profile: ProfileConfig) -> DeviceSnapshot:
        """Construct enabled entries once, rolling back completely on failure."""

        self._require_owner_thread("load_profile")
        with self._lock:
            if self._load_attempted or self._teardown_report is not None:
                raise DeviceManagerLoadError(
                    "a DeviceManager accepts exactly one profile load attempt"
                )
            self._load_attempted = True
            self._profile_name = profile.profile

            duplicate = self._first_duplicate_enabled_id(profile)
            if duplicate is not None:
                failure = LifecycleFailure(
                    duplicate,
                    "profile validation",
                    "DuplicateDeviceId",
                    "enabled device IDs must be unique",
                )
                cleanup = LifecycleReport("startup_rollback")
                self._teardown_report = cleanup
                raise DeviceStartupError(failure, cleanup)

            for config in profile.devices:
                if not config.enabled:
                    continue

                try:
                    adapter = self._registry.create(config, self._runtime_services)
                except Exception as exc:
                    self._raise_startup_failure(config.id, "construction", exc)

                record = _DeviceRecord(config=config, adapter=adapter)
                self._records[config.id] = record

                if config.connect_on_start:
                    record.state = DeviceState.CONNECTING
                    try:
                        adapter.connect()
                    except Exception as exc:
                        record.state = DeviceState.ERROR
                        record.error = str(exc)
                        self._raise_startup_failure(config.id, "connection", exc)
                    try:
                        connection_mismatch = (
                            adapter.registration.is_connected is not None
                            and not adapter.connected()
                        )
                    except Exception as exc:
                        record.state = DeviceState.ERROR
                        record.error = str(exc)
                        self._raise_startup_failure(
                            config.id,
                            "connection state verification",
                            exc,
                        )
                    if connection_mismatch:
                        mismatch = RuntimeError(
                            "connection callback returned without reporting a "
                            "connected device"
                        )
                        record.state = DeviceState.ERROR
                        record.error = str(mismatch)
                        self._raise_startup_failure(
                            config.id,
                            "connection state verification",
                            mismatch,
                        )
                    record.state = DeviceState.CONNECTED

            self._loaded = True
            return self.snapshot()

    def snapshot(self) -> DeviceSnapshot:
        with self._lock:
            views = tuple(
                DeviceRecordView(
                    device_id=device_id,
                    driver_id=record.adapter.driver_id,
                    state=record.state,
                    instance=record.adapter.instance,
                    connect_on_start=record.config.connect_on_start,
                    setter_filter=record.config.scan_channels.setters,
                    getter_filter=record.config.scan_channels.getters,
                    error=record.error,
                )
                for device_id, record in self._records.items()
            )
            return DeviceSnapshot(
                profile_name=self._profile_name,
                records=views,
                equipment={view.device_id: view.instance for view in views},
                setter_filters={
                    view.device_id: view.setter_filter for view in views
                },
                getter_filters={
                    view.device_id: view.getter_filter for view in views
                },
            )

    def stop_for_scan(self) -> LifecycleReport:
        return self._run_bulk("stop_for_scan", "stop scan activity", "stop_scan")

    def start_after_scan(self) -> LifecycleReport:
        return self._run_bulk(
            "start_after_scan",
            "start scan activity",
            "start_scan",
        )

    def force_stop_all(self) -> LifecycleReport:
        return self._run_bulk("force_stop_all", "force stop", "force_stop")

    def teardown_all(self) -> LifecycleReport:
        """Force, stop, terminate, and close every record once on its UI owner."""

        with self._lock:
            if self._teardown_report is not None:
                return self._teardown_report
            self._require_owner_thread("teardown_all")
            self._load_attempted = True
            report = self._teardown_records(
                tuple(self._records.values()),
                operation="teardown_all",
                skip_known_disconnected_stop=True,
            )
            self._teardown_report = report
            self._loaded = False
            return report

    def _require_owner_thread(self, operation: str) -> None:
        if get_ident() != self._owner_thread_id:
            raise DeviceManagerThreadError(
                f"manager '{operation}' must run on the thread that created it"
            )

    @staticmethod
    def _first_duplicate_enabled_id(profile: ProfileConfig) -> str | None:
        seen: set[str] = set()
        for config in profile.devices:
            if not config.enabled:
                continue
            if config.id in seen:
                return config.id
            seen.add(config.id)
        return None

    def _raise_startup_failure(
        self,
        device_id: str,
        action: str,
        error: Exception,
    ) -> None:
        failure = LifecycleFailure.from_exception(device_id, action, error)
        cleanup = self._teardown_records(
            tuple(self._records.values()),
            operation="startup_rollback",
        )
        self._records.clear()
        self._loaded = False
        self._teardown_report = cleanup
        raise DeviceStartupError(failure, cleanup) from error

    def _run_bulk(
        self,
        operation: str,
        action_name: str,
        adapter_method_name: str,
    ) -> LifecycleReport:
        with self._lock:
            if self._teardown_report is not None:
                raise DeviceManagerTerminatedError(
                    f"manager cannot run '{operation}' after teardown"
                )
            if not self._loaded:
                raise DeviceManagerLoadError(
                    f"manager cannot run '{operation}' before a profile loads"
                )

            failures: list[LifecycleFailure] = []
            for record in self._records.values():
                self._call_adapter(
                    record,
                    action_name,
                    adapter_method_name,
                    failures,
                )
            return LifecycleReport(operation, tuple(failures))

    def _teardown_records(
        self,
        records: tuple[_DeviceRecord, ...],
        *,
        operation: str,
        skip_known_disconnected_stop: bool = False,
    ) -> LifecycleReport:
        failures: list[LifecycleFailure] = []
        failure_counts = {id(record): 0 for record in records}

        for record in records:
            record.state = DeviceState.REMOVING

        for record in records:
            before = len(failures)
            self._call_adapter(record, "force stop", "force_stop", failures)
            failure_counts[id(record)] += len(failures) - before

        for record in records:
            before = len(failures)
            if not (
                skip_known_disconnected_stop
                and self._is_known_disconnected(record)
            ):
                self._call_adapter(
                    record,
                    "stop scan activity",
                    "stop_scan",
                    failures,
                )
            failure_counts[id(record)] += len(failures) - before

        for record in records:
            for action_name, method_name in (
                ("termination", "terminate"),
                ("widget close", "close"),
            ):
                before = len(failures)
                self._call_adapter(
                    record,
                    action_name,
                    method_name,
                    failures,
                )
                failure_counts[id(record)] += len(failures) - before

            record.state = (
                DeviceState.ERROR
                if failure_counts[id(record)]
                else DeviceState.REMOVED
            )

        return LifecycleReport(operation, tuple(failures))

    @staticmethod
    def _is_known_disconnected(record: _DeviceRecord) -> bool:
        """Avoid teardown-only stop calls when a reviewed probe says offline.

        Normal scan lifecycle calls retain exact driver behavior; this narrow
        teardown rule prevents an already-disconnected device from turning a
        best-effort final shutdown into a false failure.
        """
        if record.adapter.registration.is_connected is None:
            return False
        try:
            return not record.adapter.connected()
        except Exception:
            return False

    @staticmethod
    def _call_adapter(
        record: _DeviceRecord,
        action_name: str,
        adapter_method_name: str,
        failures: list[LifecycleFailure],
    ) -> None:
        try:
            getattr(record.adapter, adapter_method_name)()
        except Exception as exc:
            failure = LifecycleFailure.from_exception(
                record.config.id,
                action_name,
                exc,
            )
            failures.append(failure)
            record.state = DeviceState.ERROR
            record.error = failure.describe()
