from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from functools import wraps
import re
from threading import Event, RLock, get_ident
from types import MappingProxyType
from typing import Callable, Iterable, Mapping
import weakref

from PyQt6 import QtCore

from .models import ChannelFilters, DeviceConfig, ProfileConfig
from .registry import DriverAdapter, DriverRegistry


_RUNTIME_DEVICE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_RUNTIME_DRIVER_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
_RUNTIME_RESERVED_DEVICE_IDS = frozenset({"artificial_channel", "default"})


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
    """Raised when UI-owned work runs off the manager's owner thread."""


class DeviceMutationError(DeviceManagerError):
    """Base class for a refused or failed runtime session mutation."""


class DeviceMutationHooksError(DeviceMutationError):
    """Raised when runtime mutation is attempted without complete UI hooks."""


class DeviceCatalogDesynchronizedError(DeviceMutationError):
    """Raised until a failed post-commit UI acknowledgement is reconciled."""

    def __init__(self, cause: Exception) -> None:
        self.cause = cause
        super().__init__(
            "manager and UI catalogs require reconciliation after a failed "
            f"commit ({type(cause).__name__}: {cause})"
        )


class DuplicateDeviceIdError(DeviceMutationError):
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"device '{device_id}' already exists in this session")


class UnknownDeviceIdError(DeviceMutationError):
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"device '{device_id}' is not present in this session")


class RuntimeMutationDriverError(DeviceMutationError):
    def __init__(self, device_id: str, driver_id: str) -> None:
        self.device_id = device_id
        self.driver_id = driver_id
        super().__init__(
            f"driver '{driver_id}' is not reviewed for runtime mutation; "
            f"device '{device_id}' was not changed"
        )


class DeviceMutationBusyError(DeviceMutationError):
    def __init__(self, blockers: Iterable[str]) -> None:
        self.blockers = tuple(dict.fromkeys(str(item) for item in blockers if item))
        detail = ", ".join(self.blockers) or "unknown active work"
        super().__init__(f"runtime device mutation requires an idle session: {detail}")


class DeviceMutationLifecycleError(DeviceMutationError):
    def __init__(
        self,
        operation: str,
        device_id: str | None,
        phase: str,
        failures: Iterable[LifecycleFailure],
        *,
        quarantined: bool = False,
    ) -> None:
        self.operation = operation
        self.device_id = device_id
        self.phase = phase
        self.failures = tuple(failures)
        self.quarantined = bool(quarantined)
        details = "; ".join(failure.describe() for failure in self.failures)
        suffix = "; device quarantined" if self.quarantined else ""
        super().__init__(
            f"runtime operation '{operation}' failed during {phase}: "
            f"{details}{suffix}"
        )


class DeviceHookCallbackError(DeviceMutationError):
    def __init__(
        self,
        operation: str,
        primary_error: Exception | None,
        hook_name: str,
        hook_error: Exception,
    ) -> None:
        self.operation = operation
        self.primary_error = primary_error
        self.hook_name = hook_name
        self.hook_error = hook_error
        prior = (
            f"; primary error: {type(primary_error).__name__}: {primary_error}"
            if primary_error is not None
            else ""
        )
        super().__init__(
            f"runtime operation '{operation}' {hook_name} hook failed "
            f"({type(hook_error).__name__}: {hook_error}){prior}"
        )


class DeviceCallRejectedError(DeviceManagerError):
    """Base error for a manager-gated device or session call."""

    def __init__(self, device_id: str | None, reason: str) -> None:
        self.device_id = device_id
        self.reason = reason
        target = f"device '{device_id}'" if device_id is not None else "device session"
        super().__init__(f"{target} is unavailable: {reason}")


class StaleDeviceGenerationError(DeviceCallRejectedError):
    def __init__(self, device_id: str | None, expected: int, current: int) -> None:
        self.expected_generation = expected
        self.current_generation = current
        super().__init__(
            device_id,
            f"catalog generation {expected} is stale; current generation is {current}",
        )


class DeviceUnavailableError(DeviceCallRejectedError):
    pass


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
    generation: int = 0


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """Ordered, immutable catalog input for one committed generation."""

    profile_name: str
    records: tuple[DeviceRecordView, ...]
    equipment: Mapping[str, object]
    setter_filters: Mapping[str, tuple[str, ...] | None]
    getter_filters: Mapping[str, tuple[str, ...] | None]
    generation: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", tuple(self.records))
        object.__setattr__(self, "generation", int(self.generation))
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


@dataclass(frozen=True, slots=True)
class CatalogMutationProposal:
    operation: str
    device_id: str
    base_generation: int
    proposed_generation: int
    before: DeviceSnapshot
    proposed: DeviceSnapshot
    operation_id: int = 0
    operation_nonce: object | None = None


@dataclass(frozen=True, slots=True)
class DeviceOperationResult:
    operation: str
    device_id: str | None
    base_generation: int
    generation: int
    snapshot: DeviceSnapshot
    error: Exception | None = None
    failures: tuple[LifecycleFailure, ...] = ()
    committed: bool = False
    acknowledged: bool = False
    quarantined: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "failures", tuple(self.failures))

    @property
    def succeeded(self) -> bool:
        return (
            self.error is None
            and not self.failures
            and self.committed
            and self.acknowledged
        )

    def raise_for_error(self) -> "DeviceOperationResult":
        if self.error is not None:
            raise self.error
        if self.failures:
            raise DeviceMutationLifecycleError(
                self.operation,
                self.device_id,
                "lifecycle",
                self.failures,
                quarantined=self.quarantined,
            )
        return self


class DeviceOperation(QtCore.QObject):
    """Qt-safe completion handle for one nonblocking manager operation."""

    sig_finished = QtCore.pyqtSignal(object)

    def __init__(
        self,
        operation_id: int,
        operation: str,
        device_id: str | None,
        parent: QtCore.QObject,
    ) -> None:
        super().__init__(parent)
        self.operation_id = operation_id
        self.operation_nonce = object()
        self.operation = operation
        self.device_id = device_id
        self._done_event = Event()
        self._result: DeviceOperationResult | None = None

    @property
    def done(self) -> bool:
        return self._done_event.is_set()

    @property
    def result(self) -> DeviceOperationResult | None:
        return self._result

    def wait(self, timeout: float | None = None) -> DeviceOperationResult:
        if (
            not self._done_event.is_set()
            and QtCore.QThread.currentThread() is self.thread()
        ):
            raise DeviceManagerThreadError(
                "an unfinished device operation cannot be waited from its UI "
                "owner thread; observe sig_finished or keep processing events"
            )
        if not self._done_event.wait(timeout):
            raise TimeoutError(
                f"operation '{self.operation}' did not finish within {timeout} seconds"
            )
        assert self._result is not None
        return self._result

    def _finish(self, result: DeviceOperationResult) -> None:
        if self._done_event.is_set():
            return
        self._result = result
        self._done_event.set()
        self.sig_finished.emit(result)


class DeviceActivityReservation:
    """Explicit activity token serialized with runtime mutation."""

    def __init__(
        self,
        manager: "DeviceManager",
        reservation_id: int,
        kind: str,
        description: str,
    ) -> None:
        self._manager_ref = weakref.ref(manager)
        self.reservation_id = reservation_id
        self.kind = kind
        self.description = description
        self._released = False
        self._release_lock = RLock()

    @property
    def released(self) -> bool:
        with self._release_lock:
            return self._released

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        manager = self._manager_ref()
        if manager is not None:
            manager._release_activity(self.reservation_id)

    def __enter__(self) -> "DeviceActivityReservation":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


class DeviceShutdownReservation:
    """Owner-thread token that closes admission before workers are quiesced."""

    def __init__(self, manager: "DeviceManager", nonce: object) -> None:
        self._manager_ref = weakref.ref(manager)
        self._nonce = nonce
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        if self._released:
            return
        manager = self._manager_ref()
        if manager is not None:
            manager._release_shutdown_reservation(self)
        self._released = True


@dataclass(slots=True)
class _DeviceRecord:
    config: DeviceConfig
    adapter: DriverAdapter
    state: DeviceState = DeviceState.DISCONNECTED
    error: str | None = None
    generation: int = 0
    in_flight: int = 0
    removing: bool = False
    delete_scheduled: bool = False
    delete_error: Exception | None = None
    ownership_order: int = 0


@dataclass(slots=True)
class _MutationContext:
    operation: DeviceOperation
    kind: str
    device_id: str
    base_generation: int
    record: _DeviceRecord
    proposal: CatalogMutationProposal | None = None
    prepared: object | None = None
    previous_state: DeviceState = DeviceState.DISCONNECTED
    primary_error: Exception | None = None
    manager_committed: bool = False


@dataclass(frozen=True, slots=True)
class _WorkerOutcome:
    phase: str
    failures: tuple[LifecycleFailure, ...] = ()
    terminate_attempted: bool = False


@dataclass(slots=True)
class _AsyncTeardownContext:
    operation: DeviceOperation
    base_generation: int
    records: tuple[_DeviceRecord, ...]
    failures: list[LifecycleFailure]
    previous_public_state: tuple[tuple[DeviceState, str | None, bool], ...]
    next_terminate_index: int = 0
    preamble_complete: bool = False


@dataclass(slots=True)
class _CatalogReconcileContext:
    operation: DeviceOperation
    proposal: CatalogMutationProposal | None = None


@dataclass(frozen=True, slots=True)
class _WorkerEnvelope:
    operation_id: int
    payload: object


class _LifecycleWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(object)

    def __init__(self, operation_id: int, callback: Callable[[], object]) -> None:
        super().__init__()
        self._operation_id = operation_id
        self._callback = callback

    @QtCore.pyqtSlot()
    def run(self) -> None:
        try:
            payload = self._callback()
        except Exception as exc:
            payload = exc
        self.finished.emit(_WorkerEnvelope(self._operation_id, payload))


BlockersHook = Callable[[], Iterable[str]]
PrepareHook = Callable[[CatalogMutationProposal], object]
CommitHook = Callable[[object, DeviceSnapshot], None]
SealHook = Callable[[DeviceOperation], None]
UnsealHook = Callable[[DeviceOperationResult], None]


class DeviceManager(QtCore.QObject):
    """Own device instances, generation-gated calls, and lifecycle mutation."""

    sig_operation_started = QtCore.pyqtSignal(object)
    sig_operation_finished = QtCore.pyqtSignal(object)
    sig_catalog_changed = QtCore.pyqtSignal(object)
    _sig_worker_thread_stopped = QtCore.pyqtSignal(int)

    def __init__(self, registry: DriverRegistry, runtime_services: object) -> None:
        super().__init__()
        self._registry = registry
        self._runtime_services = runtime_services
        self._lock = RLock()
        self._records: dict[str, _DeviceRecord] = {}
        self._quarantined_records: dict[str, _DeviceRecord] = {}
        self._removed_operations: dict[str, DeviceOperation] = {}
        self._profile_name = ""
        self._generation = 0
        self._load_attempted = False
        self._loaded = False
        self._teardown_report: LifecycleReport | None = None
        self._teardown_in_progress = False
        self._teardown_operation: DeviceOperation | None = None
        self._last_acknowledged_snapshot: DeviceSnapshot | None = None
        self._catalog_desynchronized_error: Exception | None = None
        self._shutdown_intent = False
        self._shutdown_nonce: object | None = None
        self._owner_thread_id = get_ident()

        self._blockers_hook: BlockersHook | None = None
        self._prepare_hook: PrepareHook | None = None
        self._commit_hook: CommitHook | None = None
        self._seal_hook: SealHook | None = None
        self._unseal_hook: UnsealHook | None = None

        self._mutation_active = False
        self._active_operation: (
            _MutationContext
            | _AsyncTeardownContext
            | _CatalogReconcileContext
            | None
        ) = None
        self._next_operation_id = 1
        self._session_calls = 0
        self._device_calls = 0
        self._activities: dict[int, tuple[str, str]] = {}
        self._next_activity_id = 1
        self._next_record_order = 1
        self._next_worker_id = 1
        self._worker_threads: dict[int, tuple[QtCore.QThread, _LifecycleWorker]] = {}
        self._worker_results: dict[int, _WorkerEnvelope] = {}
        self._sig_worker_thread_stopped.connect(
            self._worker_thread_finished,
            QtCore.Qt.ConnectionType.QueuedConnection,
        )

    @property
    def loaded(self) -> bool:
        with self._lock:
            return self._loaded

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    @property
    def catalog_generation(self) -> int:
        return self.generation

    @property
    def mutation_in_progress(self) -> bool:
        with self._lock:
            return self._mutation_active or self._teardown_in_progress

    @property
    def shutdown_started(self) -> bool:
        with self._lock:
            return self._shutdown_intent or self._teardown_in_progress

    @property
    def teardown_report(self) -> LifecycleReport | None:
        with self._lock:
            return self._teardown_report

    @property
    def quarantined_device_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._quarantined_records)

    def set_runtime_hooks(
        self,
        blockers: BlockersHook,
        prepare: PrepareHook,
        commit: CommitHook,
        seal: SealHook,
        unseal: UnsealHook,
    ) -> None:
        """Install the complete synchronous UI transaction boundary."""

        self._require_owner_thread("set_runtime_hooks")
        callbacks = (blockers, prepare, commit, seal, unseal)
        if not all(callable(callback) for callback in callbacks):
            raise TypeError(
                "runtime blockers, prepare, commit, seal, and unseal hooks "
                "must be callable"
            )
        with self._lock:
            if self._mutation_active or self._teardown_in_progress:
                raise DeviceMutationBusyError(("manager operation in progress",))
            self._blockers_hook = blockers
            self._prepare_hook = prepare
            self._commit_hook = commit
            self._seal_hook = seal
            self._unseal_hook = unseal

    def validate_active_proposal(self, proposal: CatalogMutationProposal) -> None:
        """Reject copied or forged catalog capabilities, even with a leaked nonce."""

        self._require_owner_thread("validate_active_proposal")
        with self._lock:
            active = self._active_operation
            active_proposal = getattr(active, "proposal", None)
            active_operation = getattr(active, "operation", None)
            if (
                proposal is not active_proposal
                or active_operation is None
                or proposal.operation_id != active_operation.operation_id
                or proposal.operation_nonce is not active_operation.operation_nonce
                or not self._mutation_active
            ):
                raise DeviceMutationHooksError(
                    "catalog proposal is not the manager's exact active capability"
                )

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

                record = _DeviceRecord(
                    config=config,
                    adapter=adapter,
                    ownership_order=self._take_record_order_locked(),
                )
                self._records[config.id] = record
                if config.connect_on_start:
                    record.state = DeviceState.CONNECTING
                    try:
                        self._connect_and_confirm(record)
                    except Exception as exc:
                        record.state = DeviceState.ERROR
                        record.error = str(exc)
                        self._raise_startup_failure(config.id, "connection", exc)
                    record.state = DeviceState.CONNECTED

            self._generation += 1
            for record in self._records.values():
                record.generation = self._generation
            self._loaded = True
            snapshot = self._snapshot_locked()
            self._last_acknowledged_snapshot = snapshot
            return snapshot

    def snapshot(self) -> DeviceSnapshot:
        with self._lock:
            return self._snapshot_locked()

    def runtime_mutation_blockers(self) -> tuple[str, ...]:
        """Return manager-owned blockers without invoking UI hooks."""

        with self._lock:
            blockers: list[str] = []
            if self._mutation_active:
                blockers.append("runtime device mutation in progress")
            if self._teardown_in_progress:
                blockers.append("device teardown in progress")
            blockers.extend(self._manager_idle_blockers_locked())
            return tuple(blockers)

    def reserve_activity(
        self,
        kind: str,
        description: str | None = None,
    ) -> DeviceActivityReservation:
        kind = str(kind).strip()
        if not kind:
            raise ValueError("activity kind must not be empty")
        description = str(description or kind).strip() or kind
        with self._lock:
            self._require_calls_available_locked(None)
            reservation_id = self._next_activity_id
            self._next_activity_id += 1
            self._activities[reservation_id] = (kind, description)
        return DeviceActivityReservation(self, reservation_id, kind, description)

    def begin_scan_activity(
        self,
        description: str | None = None,
    ) -> DeviceActivityReservation:
        return self.reserve_activity("scan", description or "scan execution")

    def _release_activity(self, reservation_id: int) -> None:
        with self._lock:
            self._activities.pop(reservation_id, None)

    @contextmanager
    def session_call(self, expected_generation: int | None = None):
        """Lease the whole current catalog for one router/session request."""

        with self._lock:
            self._require_calls_available_locked(None)
            if (
                expected_generation is not None
                and int(expected_generation) != self._generation
            ):
                raise StaleDeviceGenerationError(
                    None,
                    int(expected_generation),
                    self._generation,
                )
            self._session_calls += 1
            leased_snapshot = self._snapshot_locked()
        try:
            yield leased_snapshot
        finally:
            with self._lock:
                self._session_calls -= 1

    def bind_call(
        self,
        device_id: str,
        generation: int,
        callback: Callable,
    ) -> Callable:
        if not callable(callback):
            raise TypeError("manager-bound device callback must be callable")

        @wraps(callback)
        def guarded(*args, **kwargs):
            return self.invoke(device_id, generation, callback, *args, **kwargs)

        return guarded

    def invoke(
        self,
        device_id: str,
        generation: int,
        callback: Callable,
        *args,
        **kwargs,
    ):
        with self._lock:
            self._require_calls_available_locked(device_id)
            record = self._records.get(device_id)
            if (
                record is None
                or record.removing
                or record.state
                in (DeviceState.ERROR, DeviceState.REMOVING, DeviceState.REMOVED)
            ):
                raise DeviceUnavailableError(device_id, "removed or being removed")
            if int(generation) != record.generation:
                raise StaleDeviceGenerationError(
                    device_id,
                    int(generation),
                    record.generation,
                )
            record.in_flight += 1
            self._device_calls += 1
        try:
            return callback(*args, **kwargs)
        finally:
            with self._lock:
                record.in_flight -= 1
                self._device_calls -= 1

    def add_device(self, config: DeviceConfig) -> DeviceOperation:
        """Construct on the owner thread and connect or clean up off it."""

        self._require_owner_thread("add_device")
        config = self._canonical_runtime_config(config)
        registration = self._precheck_add(config)
        self._check_external_blockers()
        operation = self._reserve_operation("add", config.id)
        if not self._seal_operation(operation):
            return operation
        self.sig_operation_started.emit(operation)

        try:
            adapter = self._registry.create(config, self._runtime_services)
        except Exception as exc:
            self._finish_uncommitted_operation(operation, exc)
            return operation

        record = _DeviceRecord(
            config=config,
            adapter=adapter,
            state=(
                DeviceState.CONNECTING
                if config.connect_on_start
                else DeviceState.DISCONNECTED
            ),
            generation=self.generation + 1,
            ownership_order=self._take_record_order(),
        )
        context = _MutationContext(
            operation=operation,
            kind="add",
            device_id=config.id,
            base_generation=self.generation,
            record=record,
        )
        with self._lock:
            self._active_operation = context
        try:
            with self._lock:
                proposed_records = dict(self._records)
                proposed_records[config.id] = record
                context.proposal = self._proposal_locked(
                    operation,
                    config.id,
                    proposed_records,
                    state_overrides={
                        config.id: (
                            DeviceState.CONNECTED
                            if config.connect_on_start
                            else DeviceState.DISCONNECTED
                        )
                    },
                )
        except Exception as exc:
            context.primary_error = exc
            self._dispatch_worker(operation, lambda: self._cleanup_staged(record))
            return operation

        try:
            self._prepare_twice_for_dispatch(context)
        except Exception as exc:
            context.primary_error = exc
            self._dispatch_worker(operation, lambda: self._cleanup_staged(record))
            return operation

        assert registration.runtime_mutation_allowed
        self._dispatch_worker(operation, lambda: self._worker_add(record))
        return operation

    def disconnect_device(self, device_id: str) -> DeviceOperation:
        self._require_owner_thread("disconnect_device")
        record = self._precheck_existing_mutation(device_id)
        self._check_external_blockers()
        operation = self._reserve_operation("disconnect", device_id)
        if not self._seal_operation(operation):
            return operation
        with self._lock:
            proposal = self._proposal_locked(
                operation,
                device_id,
                self._records,
                state_overrides={device_id: DeviceState.DISCONNECTED},
            )
            context = _MutationContext(
                operation=operation,
                kind="disconnect",
                device_id=device_id,
                base_generation=proposal.base_generation,
                record=record,
                proposal=proposal,
                previous_state=record.state,
            )
            self._active_operation = context
        self.sig_operation_started.emit(operation)
        try:
            self._prepare_twice_for_dispatch(context)
        except Exception as exc:
            self._finish_uncommitted_operation(operation, exc)
            return operation
        self._dispatch_worker(operation, lambda: self._worker_disconnect(record))
        return operation

    def remove_device(self, device_id: str) -> DeviceOperation:
        self._require_owner_thread("remove_device")
        with self._lock:
            previous = self._removed_operations.get(device_id)
            if previous is not None:
                return previous
            active = self._active_operation
            if (
                isinstance(active, _MutationContext)
                and active.kind == "remove"
                and active.device_id == device_id
            ):
                return active.operation

        record = self._precheck_existing_mutation(device_id)
        self._check_external_blockers()
        operation = self._reserve_operation("remove", device_id)
        if not self._seal_operation(operation):
            return operation
        with self._lock:
            proposed_records = {
                label: candidate
                for label, candidate in self._records.items()
                if label != device_id
            }
            proposal = self._proposal_locked(
                operation,
                device_id,
                proposed_records,
            )
            context = _MutationContext(
                operation=operation,
                kind="remove",
                device_id=device_id,
                base_generation=proposal.base_generation,
                record=record,
                proposal=proposal,
                previous_state=record.state,
            )
            record.removing = True
            record.state = DeviceState.REMOVING
            self._active_operation = context
        self.sig_operation_started.emit(operation)
        try:
            self._prepare_twice_for_dispatch(context)
        except Exception as exc:
            with self._lock:
                record.removing = False
                record.state = context.previous_state
            self._finish_uncommitted_operation(operation, exc)
            return operation
        self._dispatch_worker(operation, lambda: self._worker_remove(record))
        return operation

    def reconcile_catalog(self) -> DeviceOperation:
        """Retry a failed UI acknowledgement without repeating lifecycle work."""

        self._require_owner_thread("reconcile_catalog")
        with self._lock:
            self._require_loaded_locked("reconcile_catalog")
            self._require_runtime_hooks_locked()
            if self._shutdown_intent:
                raise DeviceMutationBusyError(("application shutdown is reserved",))
            if self._mutation_active or self._teardown_in_progress:
                raise DeviceMutationBusyError(("manager operation in progress",))
            blockers = self._manager_idle_blockers_locked()
            if blockers:
                raise DeviceMutationBusyError(blockers)
        self._check_external_blockers()
        operation = self._reserve_operation("reconcile", "catalog")
        with self._lock:
            self._active_operation = _CatalogReconcileContext(operation)
        if not self._seal_operation(operation):
            return operation
        self.sig_operation_started.emit(operation)
        with self._lock:
            base_generation = (
                self._last_acknowledged_snapshot.generation
                if self._last_acknowledged_snapshot is not None
                else self._generation
            )
        acknowledged, error, snapshot, cleanup_failures = (
            self._attempt_reconciliation(operation)
        )
        result = DeviceOperationResult(
            operation="reconcile",
            device_id=None,
            base_generation=base_generation,
            generation=snapshot.generation,
            snapshot=snapshot,
            error=error,
            failures=cleanup_failures,
            committed=True,
            acknowledged=acknowledged,
            quarantined=bool(self.quarantined_device_ids),
        )
        if acknowledged:
            self.sig_catalog_changed.emit(snapshot)
        self._complete_operation(operation, result)
        return operation

    def stop_for_scan(self) -> LifecycleReport:
        return self._run_bulk("stop_for_scan", "stop scan activity", "stop_scan")

    def start_after_scan(self) -> LifecycleReport:
        with self._lock:
            if self._shutdown_intent or self._teardown_in_progress:
                return LifecycleReport("start_after_scan")
        return self._run_bulk(
            "start_after_scan",
            "start scan activity",
            "start_scan",
        )

    def force_stop_all(self) -> LifecycleReport:
        return self._run_bulk("force_stop_all", "force stop", "force_stop")

    def begin_shutdown(self) -> DeviceShutdownReservation:
        """Atomically close admission before the UI quiesces an active scan."""

        self._require_owner_thread("begin_shutdown")
        with self._lock:
            self._require_loaded_locked("begin_shutdown")
            if self._mutation_active or self._teardown_in_progress:
                raise DeviceMutationBusyError(("manager operation in progress",))
            if self._shutdown_intent:
                raise DeviceMutationBusyError(("application shutdown is reserved",))

            blockers = [
                f"{kind} activity: {description}"
                for kind, description in self._activities.values()
                if kind not in {"scan", "queue"}
            ]
            if self._session_calls:
                blockers.append(f"{self._session_calls} in-flight session call(s)")
            if self._device_calls:
                blockers.append(f"{self._device_calls} in-flight device call(s)")
            if blockers:
                raise DeviceMutationBusyError(blockers)

        busy_blockers = self._device_busy_blockers()
        if busy_blockers:
            raise DeviceMutationBusyError(busy_blockers)

        with self._lock:
            self._require_loaded_locked("begin_shutdown")
            if self._mutation_active or self._teardown_in_progress:
                raise DeviceMutationBusyError(("manager operation in progress",))
            if self._shutdown_intent:
                raise DeviceMutationBusyError(("application shutdown is reserved",))
            blockers = [
                f"{kind} activity: {description}"
                for kind, description in self._activities.values()
                if kind not in {"scan", "queue"}
            ]
            if self._session_calls:
                blockers.append(f"{self._session_calls} in-flight session call(s)")
            if self._device_calls:
                blockers.append(f"{self._device_calls} in-flight device call(s)")
            if blockers:
                raise DeviceMutationBusyError(blockers)
            nonce = object()
            self._shutdown_intent = True
            self._shutdown_nonce = nonce
        return DeviceShutdownReservation(self, nonce)

    def _release_shutdown_reservation(
        self,
        reservation: DeviceShutdownReservation,
    ) -> None:
        self._require_owner_thread("release shutdown reservation")
        with self._lock:
            if reservation._nonce is not self._shutdown_nonce:
                return
            if self._teardown_in_progress or self._teardown_report is not None:
                return
            self._shutdown_intent = False
            self._shutdown_nonce = None

    def teardown_all_async(
        self,
        guard: DeviceShutdownReservation | None = None,
    ) -> DeviceOperation:
        """Begin ordered final teardown without slow owner-thread callbacks."""

        self._require_owner_thread("teardown_all_async")
        with self._lock:
            if self._teardown_operation is not None:
                return self._teardown_operation
            if self._teardown_report is not None:
                operation = self._new_operation_locked("teardown_all", None)
                self._teardown_operation = operation
                result = DeviceOperationResult(
                    operation="teardown_all",
                    device_id=None,
                    base_generation=self._generation,
                    generation=self._generation,
                    snapshot=self._snapshot_locked(),
                    error=(
                        None
                        if self._teardown_report.succeeded
                        else DeviceLifecycleError(self._teardown_report)
                    ),
                    failures=self._teardown_report.failures,
                    committed=True,
                    acknowledged=True,
                )
                operation._finish(result)
                return operation

        if guard is None:
            self._precheck_general_mutation()
        else:
            with self._lock:
                if guard.released or guard._nonce is not self._shutdown_nonce:
                    raise DeviceMutationError(
                        "teardown requires the current active shutdown reservation"
                    )
                if not self._shutdown_intent:
                    raise DeviceMutationError("shutdown reservation is no longer active")
                self._require_loaded_locked("teardown_all_async")
                self._require_runtime_hooks_locked()
                if self._mutation_active or self._teardown_in_progress:
                    raise DeviceMutationBusyError(("manager operation in progress",))
        self._check_external_blockers()
        with self._lock:
            blockers = self._manager_idle_blockers_locked()
            if blockers:
                raise DeviceMutationBusyError(blockers)
            self._mutation_active = True
            self._load_attempted = True
            operation = self._new_operation_locked("teardown_all", None)
            self._teardown_operation = operation
        if not self._seal_operation(operation):
            return operation

        try:
            self._check_external_blockers()
            with self._lock:
                blockers = self._manager_idle_blockers_locked()
            if blockers:
                raise DeviceMutationBusyError(blockers)
            busy_blockers = self._device_busy_blockers()
            if busy_blockers:
                raise DeviceMutationBusyError(busy_blockers)
        except Exception as exc:
            self._finish_uncommitted_operation(operation, exc)
            return operation

        with self._lock:
            self._teardown_in_progress = True
            ordered_records = self._ordered_teardown_records_locked()
            previous_public_state = tuple(
                (record.state, record.error, record.removing)
                for record in ordered_records
            )
            for record in ordered_records:
                record.removing = True
                record.state = DeviceState.REMOVING
            context = _AsyncTeardownContext(
                operation=operation,
                base_generation=self._generation,
                records=ordered_records,
                failures=[],
                previous_public_state=previous_public_state,
            )
            self._active_operation = context
        self.sig_operation_started.emit(operation)
        if not ordered_records:
            self._finalize_async_teardown(context)
            return operation
        self._dispatch_worker(
            operation,
            lambda: self._worker_teardown_preamble(ordered_records),
        )
        return operation

    def teardown_all(self) -> LifecycleReport:
        """Synchronous compatibility fallback; normal UI close uses async."""

        with self._lock:
            if self._teardown_report is not None:
                return self._teardown_report
            self._require_owner_thread("teardown_all")
            if self._mutation_active or self._teardown_in_progress:
                raise DeviceMutationBusyError(("manager operation in progress",))
            blockers = self._manager_idle_blockers_locked()
            if blockers:
                raise DeviceMutationBusyError(blockers)
            self._teardown_in_progress = True
            self._load_attempted = True
            records = self._ordered_teardown_records_locked()
            report = self._teardown_records(
                records,
                operation="teardown_all",
                skip_known_disconnected_stop=True,
            )
            self._teardown_report = report
            self._loaded = False
            self._teardown_in_progress = False
            return report

    def _ordered_teardown_records_locked(self) -> tuple[_DeviceRecord, ...]:
        records = (*self._records.values(), *self._quarantined_records.values())
        seen: set[int] = set()
        ordered = []
        for record in records:
            if id(record) in seen:
                continue
            seen.add(id(record))
            ordered.append(record)
        ordered.sort(key=lambda record: record.ownership_order)
        return tuple(ordered)

    def _take_record_order(self) -> int:
        with self._lock:
            return self._take_record_order_locked()

    def _take_record_order_locked(self) -> int:
        order = self._next_record_order
        self._next_record_order += 1
        return order

    def _require_owner_thread(self, operation: str) -> None:
        if get_ident() != self._owner_thread_id:
            raise DeviceManagerThreadError(
                f"manager '{operation}' must run on the thread that created it"
            )

    def _require_loaded_locked(self, operation: str) -> None:
        if self._teardown_report is not None or self._teardown_in_progress:
            raise DeviceManagerTerminatedError(
                f"manager cannot run '{operation}' during or after teardown"
            )
        if not self._loaded:
            raise DeviceManagerLoadError(
                f"manager cannot run '{operation}' before a profile loads"
            )

    def _require_runtime_hooks_locked(self) -> None:
        callbacks = (
            self._blockers_hook,
            self._prepare_hook,
            self._commit_hook,
            self._seal_hook,
            self._unseal_hook,
        )
        if any(callback is None for callback in callbacks):
            raise DeviceMutationHooksError(
                "runtime mutation requires blockers, prepare, commit, seal, "
                "and unseal UI hooks"
            )

    def _prepare_hook_required(self) -> PrepareHook:
        with self._lock:
            self._require_runtime_hooks_locked()
            assert self._prepare_hook is not None
            return self._prepare_hook

    def _precheck_general_mutation(self) -> None:
        with self._lock:
            self._require_loaded_locked("runtime mutation")
            self._require_runtime_hooks_locked()
            if self._shutdown_intent:
                raise DeviceMutationBusyError(("application shutdown is reserved",))
            if self._catalog_desynchronized_error is not None:
                raise DeviceCatalogDesynchronizedError(
                    self._catalog_desynchronized_error
                )
            if self._mutation_active or self._teardown_in_progress:
                raise DeviceMutationBusyError(("manager operation in progress",))
            blockers = self._manager_idle_blockers_locked()
            if blockers:
                raise DeviceMutationBusyError(blockers)

    def _precheck_add(self, config: DeviceConfig):
        if not isinstance(config, DeviceConfig):
            raise TypeError("add_device requires a validated DeviceConfig")
        if not config.enabled:
            raise DeviceMutationError(
                f"device '{config.id}' is disabled; session add requires enabled=true"
            )
        self._precheck_general_mutation()
        with self._lock:
            if config.id in self._records or config.id in self._quarantined_records:
                raise DuplicateDeviceIdError(config.id)
        registration = self._registry.registration(config.driver)
        if not registration.runtime_mutation_allowed:
            raise RuntimeMutationDriverError(config.id, config.driver)
        return registration

    @staticmethod
    def _canonical_runtime_config(config: DeviceConfig) -> DeviceConfig:
        """Validate and detach all public mutable inputs before admission."""

        if not isinstance(config, DeviceConfig):
            raise TypeError("add_device requires a validated DeviceConfig")
        if (
            not isinstance(config.id, str)
            or config.id != config.id.strip()
            or _RUNTIME_DEVICE_ID_PATTERN.fullmatch(config.id) is None
            or config.id in _RUNTIME_RESERVED_DEVICE_IDS
        ):
            raise ValueError(
                "runtime device id must be a non-reserved identifier containing "
                "only letters, digits, underscores, and hyphens"
            )
        if (
            not isinstance(config.driver, str)
            or config.driver != config.driver.strip()
            or _RUNTIME_DRIVER_ID_PATTERN.fullmatch(config.driver) is None
        ):
            raise ValueError("runtime driver must be a lowercase registry identifier")
        if type(config.enabled) is not bool:
            raise TypeError("device enabled must be a boolean")
        if type(config.connect_on_start) is not bool:
            raise TypeError("device connect_on_start must be a boolean")
        if config.connect_on_start and not config.enabled:
            raise ValueError("a disabled runtime device cannot connect on startup")
        if not isinstance(config.connection, Mapping):
            raise TypeError("device connection must be a mapping")
        filters = config.scan_channels
        if not isinstance(filters, ChannelFilters):
            raise TypeError("device scan_channels must be ChannelFilters")
        return DeviceConfig(
            id=config.id,
            driver=config.driver,
            enabled=config.enabled,
            connect_on_start=config.connect_on_start,
            connection=config.connection,
            scan_channels=ChannelFilters(
                setters=filters.setters,
                getters=filters.getters,
            ),
        )

    def _precheck_existing_mutation(self, device_id: str) -> _DeviceRecord:
        self._precheck_general_mutation()
        with self._lock:
            record = self._records.get(device_id)
            if record is None:
                raise UnknownDeviceIdError(device_id)
            if not record.adapter.registration.runtime_mutation_allowed:
                raise RuntimeMutationDriverError(device_id, record.adapter.driver_id)
            return record

    def _manager_idle_blockers_locked(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if self._session_calls:
            blockers.append(f"{self._session_calls} in-flight session call(s)")
        if self._device_calls:
            blockers.append(f"{self._device_calls} in-flight device call(s)")
        blockers.extend(
            f"{kind} activity: {description}"
            for kind, description in self._activities.values()
        )
        return tuple(blockers)

    def _check_external_blockers(self) -> None:
        self._require_owner_thread("runtime preflight")
        with self._lock:
            self._require_runtime_hooks_locked()
            assert self._blockers_hook is not None
            blockers_hook = self._blockers_hook
        blockers = tuple(blockers_hook())
        if blockers:
            raise DeviceMutationBusyError(blockers)

    def _reserve_operation(self, operation: str, device_id: str) -> DeviceOperation:
        with self._lock:
            self._require_loaded_locked(operation)
            if self._mutation_active or self._teardown_in_progress:
                raise DeviceMutationBusyError(("manager operation in progress",))
            blockers = self._manager_idle_blockers_locked()
            if blockers:
                raise DeviceMutationBusyError(blockers)
            self._mutation_active = True
            return self._new_operation_locked(operation, device_id)

    def _new_operation_locked(
        self,
        operation: str,
        device_id: str | None,
    ) -> DeviceOperation:
        operation_id = self._next_operation_id
        self._next_operation_id += 1
        return DeviceOperation(operation_id, operation, device_id, self)

    def _seal_operation(self, operation: DeviceOperation) -> bool:
        self._require_owner_thread("seal runtime mutation")
        with self._lock:
            self._require_runtime_hooks_locked()
            assert self._seal_hook is not None
            seal_hook = self._seal_hook
        try:
            seal_hook(operation)
        except Exception as exc:
            self._finish_uncommitted_operation(operation, exc)
            return False
        return True

    def _proposal_locked(
        self,
        operation: DeviceOperation,
        device_id: str,
        records: Mapping[str, _DeviceRecord],
        *,
        state_overrides: Mapping[str, DeviceState] | None = None,
    ) -> CatalogMutationProposal:
        base = self._snapshot_locked()
        proposed_generation = self._generation + 1
        proposed = self._snapshot_from_records_locked(
            records,
            generation=proposed_generation,
            state_overrides=state_overrides,
            allow_equipment=True,
        )
        return CatalogMutationProposal(
            operation=operation.operation,
            device_id=device_id,
            base_generation=self._generation,
            proposed_generation=proposed_generation,
            before=base,
            proposed=proposed,
            operation_id=operation.operation_id,
            operation_nonce=operation.operation_nonce,
        )

    def _prepare_twice_for_dispatch(self, context: _MutationContext) -> None:
        assert context.proposal is not None
        self._prepare_hook_required()(context.proposal)
        self._prepare_for_dispatch(context)

    def _prepare_for_dispatch(self, context: _MutationContext) -> None:
        assert context.proposal is not None
        self._check_external_blockers()
        busy_blockers = self._device_busy_blockers()
        if busy_blockers:
            raise DeviceMutationBusyError(busy_blockers)
        context.prepared = self._prepare_hook_required()(context.proposal)

    def _device_busy_blockers(self) -> tuple[str, ...]:
        """Probe reviewed device busy callbacks at the final dispatch boundary."""

        blockers = []
        with self._lock:
            candidates = (*self._records.items(), *self._quarantined_records.items())
            seen: set[int] = set()
            records = []
            for device_id, record in candidates:
                if id(record) in seen:
                    continue
                seen.add(id(record))
                records.append((device_id, record))
        for device_id, record in records:
            if record.adapter.terminated:
                continue
            try:
                if record.adapter.busy():
                    blockers.append(f"device '{device_id}' reports active work")
            except Exception as exc:
                blockers.append(
                    f"device '{device_id}' busy probe failed "
                    f"({type(exc).__name__}: {exc})"
                )
        return tuple(blockers)

    def _dispatch_worker(
        self,
        operation: DeviceOperation,
        callback: Callable[[], object],
    ) -> None:
        self._require_owner_thread("dispatch lifecycle worker")
        worker_id = self._next_worker_id
        self._next_worker_id += 1
        thread: QtCore.QThread | None = None
        worker: _LifecycleWorker | None = None
        cleanup_errors: list[Exception] = []
        try:
            thread = QtCore.QThread(self)
            worker = _LifecycleWorker(operation.operation_id, callback)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.finished.connect(
                lambda envelope, worker_id=worker_id: self._capture_worker_result(
                    worker_id,
                    envelope,
                ),
                QtCore.Qt.ConnectionType.DirectConnection,
            )
            worker.finished.connect(
                thread.quit,
                QtCore.Qt.ConnectionType.DirectConnection,
            )
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(
                lambda worker_id=worker_id: self._sig_worker_thread_stopped.emit(
                    worker_id
                )
            )
            self._worker_threads[worker_id] = (thread, worker)
            thread.start()
        except Exception as exc:
            self._worker_threads.pop(worker_id, None)
            self._worker_results.pop(worker_id, None)
            for candidate in (worker, thread):
                if candidate is None:
                    continue
                try:
                    candidate.deleteLater()
                except Exception as cleanup_error:
                    cleanup_errors.append(cleanup_error)
            envelope = _WorkerEnvelope(operation.operation_id, exc)
            if cleanup_errors:
                envelope = self._append_worker_cleanup_failures(
                    envelope,
                    cleanup_errors,
                )
            # Dispatch setup itself is owner-thread work, so completing this
            # failure synchronously cannot run a slow driver callback on the UI.
            self._on_worker_finished(envelope)

    def _capture_worker_result(self, worker_id: int, envelope: object) -> None:
        if not isinstance(envelope, _WorkerEnvelope):
            return
        with self._lock:
            self._worker_results[worker_id] = envelope

    @QtCore.pyqtSlot(int)
    def _worker_thread_finished(self, worker_id: int) -> None:
        pair = self._worker_threads.pop(worker_id, None)
        with self._lock:
            envelope = self._worker_results.pop(worker_id, None)
        cleanup_errors: list[Exception] = []
        if pair is not None:
            try:
                pair[0].deleteLater()
            except Exception as exc:
                cleanup_errors.append(exc)
        if envelope is not None:
            if cleanup_errors:
                envelope = self._append_worker_cleanup_failures(
                    envelope,
                    cleanup_errors,
                )
            self._on_worker_finished(envelope)

    def _append_worker_cleanup_failures(
        self,
        envelope: _WorkerEnvelope,
        errors: Iterable[Exception],
    ) -> _WorkerEnvelope:
        with self._lock:
            active = self._active_operation
            if (
                isinstance(active, _AsyncTeardownContext)
                and active.preamble_complete
                and active.next_terminate_index < len(active.records)
            ):
                device_id = active.records[
                    active.next_terminate_index
                ].config.id
            else:
                device_id = str(getattr(active, "device_id", None) or "manager")
        cleanup_failures = tuple(
            LifecycleFailure.from_exception(
                device_id,
                "worker thread cleanup",
                error,
            )
            for error in errors
        )
        payload = envelope.payload
        if isinstance(payload, _WorkerOutcome):
            payload = _WorkerOutcome(
                payload.phase,
                (*payload.failures, *cleanup_failures),
                payload.terminate_attempted,
            )
        elif isinstance(payload, Exception):
            payload = _WorkerOutcome(
                "worker boundary",
                (
                    LifecycleFailure.from_exception(
                        device_id,
                        "worker execution",
                        payload,
                    ),
                    *cleanup_failures,
                ),
            )
        else:
            payload = _WorkerOutcome(
                "worker boundary",
                cleanup_failures,
            )
        return _WorkerEnvelope(envelope.operation_id, payload)

    @QtCore.pyqtSlot(object)
    def _on_worker_finished(self, envelope: object) -> None:
        self._require_owner_thread("finish lifecycle worker")
        if not isinstance(envelope, _WorkerEnvelope):
            return
        with self._lock:
            active = self._active_operation
        if isinstance(active, _AsyncTeardownContext):
            if active.operation.operation_id == envelope.operation_id:
                self._finish_async_teardown_phase(active, envelope.payload)
            return
        if not isinstance(active, _MutationContext):
            return
        if active.operation.operation_id != envelope.operation_id:
            return
        payload = envelope.payload
        if isinstance(payload, Exception):
            payload = _WorkerOutcome(
                "worker boundary",
                (
                    LifecycleFailure.from_exception(
                        active.device_id,
                        "worker execution",
                        payload,
                    ),
                ),
            )
        if not isinstance(payload, _WorkerOutcome):
            payload = _WorkerOutcome(
                "worker boundary",
                (
                    LifecycleFailure(
                        active.device_id,
                        "worker execution",
                        "InvalidWorkerResult",
                        repr(payload),
                    ),
                ),
            )
        if active.kind == "add":
            self._finish_add(active, payload)
        elif active.kind == "disconnect":
            self._finish_disconnect(active, payload)
        elif active.kind == "remove":
            self._finish_remove(active, payload)

    def _worker_add(self, record: _DeviceRecord) -> _WorkerOutcome:
        failures: list[LifecycleFailure] = []
        if not record.config.connect_on_start:
            return _WorkerOutcome("connection")
        try:
            self._connect_and_confirm(record)
        except Exception as exc:
            failures.append(
                LifecycleFailure.from_exception(record.config.id, "connection", exc)
            )
            cleanup = self._cleanup_staged(record)
            return _WorkerOutcome(
                "connection and rollback",
                (*failures, *cleanup.failures),
                terminate_attempted=cleanup.terminate_attempted,
            )
        return _WorkerOutcome("connection")

    def _cleanup_staged(self, record: _DeviceRecord) -> _WorkerOutcome:
        failures: list[LifecycleFailure] = []
        self._call_adapter(record, "force stop", "force_stop", failures)
        if not self._is_known_disconnected(record):
            self._call_adapter(record, "stop scan activity", "stop_scan", failures)
        self._call_adapter(record, "termination", "terminate", failures)
        return _WorkerOutcome(
            "staged cleanup",
            tuple(failures),
            terminate_attempted=True,
        )

    def _worker_disconnect(self, record: _DeviceRecord) -> _WorkerOutcome:
        try:
            record.adapter.disconnect()
        except Exception as exc:
            return _WorkerOutcome(
                "disconnection",
                (
                    LifecycleFailure.from_exception(
                        record.config.id,
                        "disconnection",
                        exc,
                    ),
                ),
            )
        return _WorkerOutcome("disconnection")

    def _worker_remove(self, record: _DeviceRecord) -> _WorkerOutcome:
        failures: list[LifecycleFailure] = []
        self._call_adapter(record, "force stop", "force_stop", failures)
        if not self._is_known_disconnected(record):
            self._call_adapter(record, "stop scan activity", "stop_scan", failures)
        if failures:
            return _WorkerOutcome("pre-termination", tuple(failures))
        self._call_adapter(record, "termination", "terminate", failures)
        return _WorkerOutcome(
            "termination",
            tuple(failures),
            terminate_attempted=True,
        )

    def _finish_add(
        self,
        context: _MutationContext,
        outcome: _WorkerOutcome,
    ) -> None:
        failures = list(outcome.failures)
        if outcome.terminate_attempted:
            self._close_record(context.record, failures)
        if context.primary_error is not None or failures:
            error = context.primary_error or DeviceMutationLifecycleError(
                "add",
                context.device_id,
                outcome.phase,
                failures,
                quarantined=outcome.terminate_attempted and bool(failures),
            )
            cleanup_never_dispatched = bool(failures) and not outcome.terminate_attempted
            quarantined = (
                cleanup_never_dispatched
                or self._has_unresolved_cleanup(context.record)
            )
            if quarantined:
                with self._lock:
                    context.record.state = DeviceState.ERROR
                    context.record.error = failures[0].describe()
                    self._quarantined_records[context.device_id] = context.record
            if context.manager_committed:
                self._finish_committed_add_cleanup(context, failures)
                return
            self._finish_uncommitted_operation(
                context.operation,
                error,
                failures=failures,
                quarantined=quarantined,
            )
            return

        context.record.state = (
            DeviceState.CONNECTED
            if context.record.config.connect_on_start
            else DeviceState.DISCONNECTED
        )
        context.record.error = None
        self._commit_mutation(context, context.record)

    def _finish_disconnect(
        self,
        context: _MutationContext,
        outcome: _WorkerOutcome,
    ) -> None:
        if outcome.failures:
            context.record.state = DeviceState.ERROR
            context.record.error = outcome.failures[0].describe()
            error: Exception | None = DeviceMutationLifecycleError(
                "disconnect",
                context.device_id,
                outcome.phase,
                outcome.failures,
            )
        else:
            context.record.state = DeviceState.DISCONNECTED
            context.record.error = None
            error = None
        self._commit_mutation(
            context,
            context.record,
            primary_error=error,
            failures=outcome.failures,
        )

    def _finish_remove(
        self,
        context: _MutationContext,
        outcome: _WorkerOutcome,
    ) -> None:
        record = context.record
        failures = list(outcome.failures)
        if not outcome.terminate_attempted:
            with self._lock:
                record.removing = False
                record.state = DeviceState.ERROR
                record.error = failures[0].describe()
            error = DeviceMutationLifecycleError(
                "remove",
                context.device_id,
                outcome.phase,
                failures,
            )
            with self._lock:
                self._generation += 1
                context.manager_committed = True
                self._catalog_desynchronized_error = error
            acknowledged, recovery_error, snapshot, cleanup_failures = (
                self._attempt_reconciliation(context.operation)
            )
            failures.extend(cleanup_failures)
            result_error: Exception = error
            if recovery_error is not None:
                result_error = DeviceHookCallbackError(
                    "remove",
                    error,
                    "reconcile",
                    recovery_error,
                )
            result = DeviceOperationResult(
                operation="remove",
                device_id=context.device_id,
                base_generation=context.base_generation,
                generation=snapshot.generation,
                snapshot=snapshot,
                error=result_error,
                failures=tuple(failures),
                committed=True,
                acknowledged=acknowledged,
                quarantined=False,
            )
            if acknowledged:
                self.sig_catalog_changed.emit(snapshot)
            self._complete_operation(context.operation, result)
            return

        self._close_record(record, failures, schedule_delete=False)
        quarantined = self._has_unresolved_cleanup(record)
        with self._lock:
            self._records.pop(context.device_id, None)
            record.removing = False
            if quarantined:
                record.state = DeviceState.ERROR
                record.error = failures[0].describe()
                self._quarantined_records[context.device_id] = record
            else:
                record.state = DeviceState.REMOVED
                record.error = None
        error = (
            DeviceMutationLifecycleError(
                "remove",
                context.device_id,
                outcome.phase,
                failures,
                quarantined=True,
            )
            if failures
            else None
        )
        self._commit_mutation(
            context,
            None,
            primary_error=error,
            failures=failures,
            quarantined=quarantined,
        )

    def _close_record(
        self,
        record: _DeviceRecord,
        failures: list[LifecycleFailure],
        *,
        schedule_delete: bool = True,
    ) -> None:
        self._require_owner_thread("close device widget")
        if record.adapter.closed:
            if record.adapter.close_error is not None:
                failures.append(
                    LifecycleFailure.from_exception(
                        record.config.id,
                        "widget close",
                        record.adapter.close_error,
                    )
                )
        else:
            self._call_adapter(record, "widget close", "close", failures)

        instance = record.adapter.instance
        if (
            schedule_delete
            and
            record.adapter.termination_error is None
            and
            record.adapter.close_error is None
            and not record.delete_scheduled
            and isinstance(instance, QtCore.QObject)
        ):
            try:
                instance.deleteLater()
                record.delete_scheduled = True
                record.delete_error = None
            except Exception as exc:
                record.delete_error = exc
                failures.append(
                    LifecycleFailure.from_exception(
                        record.config.id,
                        "widget delete scheduling",
                        exc,
                    )
                )

    def _schedule_delete_if_resolved(
        self,
        record: _DeviceRecord,
        failures: list[LifecycleFailure],
    ) -> None:
        self._close_record(record, failures, schedule_delete=True)

    @staticmethod
    def _has_unresolved_cleanup(record: _DeviceRecord) -> bool:
        return (
            record.adapter.termination_error is not None
            or record.adapter.close_error is not None
            or record.delete_error is not None
        )

    def _commit_mutation(
        self,
        context: _MutationContext,
        added_record: _DeviceRecord | None,
        *,
        primary_error: Exception | None = None,
        failures: Iterable[LifecycleFailure] = (),
        quarantined: bool = False,
    ) -> None:
        self._require_owner_thread("commit runtime mutation")
        failures = list(failures)
        with self._lock:
            if self._generation != context.base_generation:
                raise RuntimeError(
                    "manager generation changed during a serialized mutation"
                )
            if context.kind == "add":
                assert added_record is not None
                self._records[context.device_id] = added_record
                self._removed_operations.pop(context.device_id, None)
            self._generation += 1
            context.manager_committed = True
            if context.kind == "add" and added_record is not None:
                added_record.generation = self._generation
            committed_snapshot = self._snapshot_locked()
            prepared = context.prepared
            assert self._commit_hook is not None
            commit_hook = self._commit_hook

        try:
            commit_hook(prepared, committed_snapshot)
        except Exception as commit_error:
            with self._lock:
                self._catalog_desynchronized_error = commit_error

            if context.kind == "add":
                with self._lock:
                    self._records.pop(context.device_id, None)
                    context.record.state = DeviceState.REMOVING
                    context.record.error = (
                        f"catalog commit failed: {type(commit_error).__name__}: "
                        f"{commit_error}"
                    )
                context.primary_error = commit_error
                self._dispatch_worker(
                    context.operation,
                    lambda: self._cleanup_staged(context.record),
                )
                return

            if context.kind == "remove":
                with self._lock:
                    context.record.state = DeviceState.ERROR
                    context.record.error = (
                        f"catalog commit failed: {type(commit_error).__name__}: "
                        f"{commit_error}"
                    )
                    self._quarantined_records[context.device_id] = context.record
                quarantined = True

            acknowledged, recovery_error, committed_snapshot, cleanup_failures = (
                self._attempt_reconciliation(context.operation)
            )
            failures.extend(cleanup_failures)
            if acknowledged and context.kind == "remove" and not (
                self._has_unresolved_cleanup(context.record)
            ):
                with self._lock:
                    self._quarantined_records.pop(context.device_id, None)
                self._schedule_delete_if_resolved(context.record, failures)
                quarantined = False
                committed_snapshot = self.snapshot()
            elif context.kind == "remove":
                quarantined = self._has_unresolved_cleanup(context.record)
            result_error: Exception = commit_error
            if recovery_error is not None:
                result_error = DeviceHookCallbackError(
                    context.kind,
                    commit_error,
                    "reconcile",
                    recovery_error,
                )
            result = DeviceOperationResult(
                operation=context.kind,
                device_id=context.device_id,
                base_generation=context.base_generation,
                generation=committed_snapshot.generation,
                snapshot=committed_snapshot,
                error=result_error,
                failures=tuple(failures),
                committed=True,
                acknowledged=acknowledged,
                quarantined=quarantined,
            )
            with self._lock:
                if context.kind == "remove":
                    self._removed_operations[context.device_id] = context.operation
            if acknowledged:
                self.sig_catalog_changed.emit(committed_snapshot)
            self._complete_operation(context.operation, result)
            return

        with self._lock:
            self._last_acknowledged_snapshot = committed_snapshot
            self._catalog_desynchronized_error = None
            if context.kind == "remove":
                self._removed_operations[context.device_id] = context.operation
        if context.kind == "remove" and not quarantined:
            self._schedule_delete_if_resolved(context.record, failures)
            if self._has_unresolved_cleanup(context.record):
                quarantined = True
                context.record.state = DeviceState.ERROR
                if failures:
                    context.record.error = failures[-1].describe()
                with self._lock:
                    self._quarantined_records[context.device_id] = context.record
                if primary_error is None:
                    primary_error = DeviceMutationLifecycleError(
                        "remove",
                        context.device_id,
                        "widget deletion",
                        failures,
                        quarantined=True,
                    )
            committed_snapshot = self.snapshot()

        result = DeviceOperationResult(
            operation=context.kind,
            device_id=context.device_id,
            base_generation=context.base_generation,
            generation=committed_snapshot.generation,
            snapshot=committed_snapshot,
            error=primary_error,
            failures=tuple(failures),
            committed=True,
            acknowledged=True,
            quarantined=quarantined,
        )
        self.sig_catalog_changed.emit(committed_snapshot)
        self._complete_operation(context.operation, result)

    def _attempt_reconciliation(
        self,
        operation: DeviceOperation,
    ) -> tuple[
        bool,
        Exception | None,
        DeviceSnapshot,
        tuple[LifecycleFailure, ...],
    ]:
        """Try to acknowledge the manager's current safe snapshot while sealed."""

        self._require_owner_thread("reconcile device catalog")
        with self._lock:
            before = self._last_acknowledged_snapshot
            current = self._snapshot_locked()
            if before is None:
                before = current
            proposal = CatalogMutationProposal(
                operation="reconcile",
                device_id=str(operation.device_id or "catalog"),
                base_generation=before.generation,
                proposed_generation=current.generation,
                before=before,
                proposed=current,
                operation_id=operation.operation_id,
                operation_nonce=operation.operation_nonce,
            )
            active = self._active_operation
            if getattr(active, "operation", None) is not operation:
                raise RuntimeError("reconciliation lost its active manager operation")
            active.proposal = proposal
            assert self._prepare_hook is not None
            assert self._commit_hook is not None
            prepare_hook = self._prepare_hook
            commit_hook = self._commit_hook
        try:
            prepare_hook(proposal)
            self._check_external_blockers()
            busy_blockers = self._device_busy_blockers()
            if busy_blockers:
                raise DeviceMutationBusyError(busy_blockers)
            prepared = prepare_hook(proposal)
            commit_hook(prepared, current)
        except Exception as exc:
            with self._lock:
                self._catalog_desynchronized_error = exc
            return False, exc, current, ()

        with self._lock:
            self._last_acknowledged_snapshot = current
            self._catalog_desynchronized_error = None
        cleanup_failures = self._release_resolved_quarantines()
        return True, None, current, cleanup_failures

    def _release_resolved_quarantines(self) -> tuple[LifecycleFailure, ...]:
        failures: list[LifecycleFailure] = []
        with self._lock:
            candidates = tuple(self._quarantined_records.items())
        for device_id, record in candidates:
            if (
                not record.adapter.terminated
                or not record.adapter.closed
                or record.adapter.termination_error is not None
                or record.adapter.close_error is not None
            ):
                continue
            delete_failures: list[LifecycleFailure] = []
            self._schedule_delete_if_resolved(record, delete_failures)
            if delete_failures:
                failures.extend(delete_failures)
                record.state = DeviceState.ERROR
                record.error = delete_failures[0].describe()
                continue
            with self._lock:
                if self._quarantined_records.get(device_id) is record:
                    self._quarantined_records.pop(device_id, None)
        return tuple(failures)

    def _finish_committed_add_cleanup(
        self,
        context: _MutationContext,
        failures: list[LifecycleFailure],
    ) -> None:
        with self._lock:
            already_quarantined = (
                self._quarantined_records.get(context.device_id) is context.record
            )
        quarantined = (
            already_quarantined
            or self._has_unresolved_cleanup(context.record)
        )
        if quarantined:
            with self._lock:
                context.record.state = DeviceState.ERROR
                if failures:
                    context.record.error = failures[0].describe()
                self._quarantined_records[context.device_id] = context.record

        acknowledged, recovery_error, snapshot, cleanup_failures = (
            self._attempt_reconciliation(context.operation)
        )
        failures.extend(cleanup_failures)
        with self._lock:
            quarantined = (
                self._quarantined_records.get(context.device_id) is context.record
                or self._has_unresolved_cleanup(context.record)
            )
        error: Exception = context.primary_error or RuntimeError(
            "catalog commit failed"
        )
        if recovery_error is not None:
            error = DeviceHookCallbackError(
                "add",
                context.primary_error,
                "reconcile",
                recovery_error,
            )
        result = DeviceOperationResult(
            operation="add",
            device_id=context.device_id,
            base_generation=context.base_generation,
            generation=snapshot.generation,
            snapshot=snapshot,
            error=error,
            failures=tuple(failures),
            committed=True,
            acknowledged=acknowledged,
            quarantined=quarantined,
        )
        if acknowledged:
            self.sig_catalog_changed.emit(snapshot)
        self._complete_operation(context.operation, result)
    def _finish_uncommitted_operation(
        self,
        operation: DeviceOperation,
        error: Exception,
        *,
        failures: Iterable[LifecycleFailure] = (),
        quarantined: bool = False,
    ) -> None:
        with self._lock:
            snapshot = self._snapshot_locked()
        result = DeviceOperationResult(
            operation=operation.operation,
            device_id=operation.device_id,
            base_generation=snapshot.generation,
            generation=snapshot.generation,
            snapshot=snapshot,
            error=error,
            failures=tuple(failures),
            committed=False,
            acknowledged=False,
            quarantined=quarantined,
        )
        self._complete_operation(operation, result)

    def _complete_operation(
        self,
        operation: DeviceOperation,
        result: DeviceOperationResult,
    ) -> None:
        with self._lock:
            unseal_hook = self._unseal_hook
        if unseal_hook is not None:
            try:
                unseal_hook(result)
            except Exception as exc:
                result = DeviceOperationResult(
                    operation=result.operation,
                    device_id=result.device_id,
                    base_generation=result.base_generation,
                    generation=result.generation,
                    snapshot=result.snapshot,
                    error=DeviceHookCallbackError(
                        result.operation,
                        result.error,
                        "unseal",
                        exc,
                    ),
                    failures=result.failures,
                    committed=result.committed,
                    acknowledged=result.acknowledged,
                    quarantined=result.quarantined,
                )
        with self._lock:
            self._mutation_active = False
            self._active_operation = None
            if operation.operation == "teardown_all":
                self._teardown_in_progress = False
                if not result.committed:
                    self._teardown_operation = None
        operation._finish(result)
        self.sig_operation_finished.emit(result)

    def _worker_teardown_preamble(
        self,
        records: tuple[_DeviceRecord, ...],
    ) -> _WorkerOutcome:
        failures: list[LifecycleFailure] = []
        for record in records:
            if not record.adapter.terminated:
                self._call_adapter(record, "force stop", "force_stop", failures)
        for record in records:
            if record.adapter.terminated:
                continue
            if not self._is_known_disconnected(record):
                self._call_adapter(
                    record,
                    "stop scan activity",
                    "stop_scan",
                    failures,
                )
        return _WorkerOutcome("teardown preamble", tuple(failures))

    @staticmethod
    def _worker_terminate_one(record: _DeviceRecord) -> _WorkerOutcome:
        failures: list[LifecycleFailure] = []
        DeviceManager._call_termination(record, failures)
        return _WorkerOutcome(
            "teardown termination",
            tuple(failures),
            terminate_attempted=True,
        )

    def _finish_async_teardown_phase(
        self,
        context: _AsyncTeardownContext,
        payload: object,
    ) -> None:
        if isinstance(payload, Exception):
            failure_device_id = "manager"
            if (
                context.preamble_complete
                and context.next_terminate_index < len(context.records)
            ):
                failure_device_id = context.records[
                    context.next_terminate_index
                ].config.id
            payload = _WorkerOutcome(
                "worker boundary",
                (
                    LifecycleFailure.from_exception(
                        failure_device_id,
                        "worker execution",
                        payload,
                    ),
                ),
            )
        if not isinstance(payload, _WorkerOutcome):
            payload = _WorkerOutcome(
                "worker boundary",
                (
                    LifecycleFailure(
                        "manager",
                        "worker execution",
                        "InvalidWorkerResult",
                        repr(payload),
                    ),
                ),
            )
        context.failures.extend(payload.failures)

        if not context.preamble_complete:
            if payload.phase != "teardown preamble":
                self._abort_async_teardown(context)
                return
            context.preamble_complete = True
            context.next_terminate_index = 0
        else:
            index = context.next_terminate_index
            record = context.records[index]
            if payload.terminate_attempted:
                self._close_record(record, context.failures)
            context.next_terminate_index += 1

        if context.next_terminate_index >= len(context.records):
            self._finalize_async_teardown(context)
            return
        record = context.records[context.next_terminate_index]
        self._dispatch_worker(
            context.operation,
            lambda record=record: self._worker_terminate_one(record),
        )

    def _abort_async_teardown(self, context: _AsyncTeardownContext) -> None:
        """Undo admission state when the global force/stop preamble never ran."""

        for record, previous in zip(
            context.records,
            context.previous_public_state,
            strict=True,
        ):
            record.state, record.error, record.removing = previous
        with self._lock:
            self._teardown_in_progress = False
            snapshot = self._snapshot_locked()
        report = LifecycleReport("teardown_all", tuple(context.failures))
        result = DeviceOperationResult(
            operation="teardown_all",
            device_id=None,
            base_generation=context.base_generation,
            generation=snapshot.generation,
            snapshot=snapshot,
            error=DeviceLifecycleError(report),
            failures=report.failures,
            committed=False,
            acknowledged=False,
        )
        self._complete_operation(context.operation, result)

    def _finalize_async_teardown(self, context: _AsyncTeardownContext) -> None:
        failure_ids = {failure.device_id for failure in context.failures}
        for record in context.records:
            record.removing = False
            record.state = (
                DeviceState.ERROR
                if record.config.id in failure_ids
                else DeviceState.REMOVED
            )
        report = LifecycleReport("teardown_all", tuple(context.failures))
        with self._lock:
            self._generation += 1
            self._teardown_report = report
            self._loaded = False
            snapshot = self._snapshot_locked()
        error = None if report.succeeded else DeviceLifecycleError(report)
        result = DeviceOperationResult(
            operation="teardown_all",
            device_id=None,
            base_generation=context.base_generation,
            generation=snapshot.generation,
            snapshot=snapshot,
            error=error,
            failures=report.failures,
            committed=True,
            acknowledged=True,
        )
        self._complete_operation(context.operation, result)

    def _snapshot_locked(self) -> DeviceSnapshot:
        allow_equipment = not (
            self._teardown_in_progress or self._teardown_report is not None
        )
        return self._snapshot_from_records_locked(
            self._records,
            generation=self._generation,
            allow_equipment=allow_equipment,
        )

    def _snapshot_from_records_locked(
        self,
        records: Mapping[str, _DeviceRecord],
        *,
        generation: int,
        state_overrides: Mapping[str, DeviceState] | None = None,
        allow_equipment: bool,
    ) -> DeviceSnapshot:
        state_overrides = state_overrides or {}
        views = tuple(
            DeviceRecordView(
                device_id=device_id,
                driver_id=record.adapter.driver_id,
                state=state_overrides.get(device_id, record.state),
                instance=record.adapter.instance,
                connect_on_start=record.config.connect_on_start,
                setter_filter=record.config.scan_channels.setters,
                getter_filter=record.config.scan_channels.getters,
                error=record.error,
                generation=record.generation,
            )
            for device_id, record in records.items()
        )
        callable_views = (
            tuple(
                view
                for view in views
                if view.state not in (DeviceState.REMOVING, DeviceState.REMOVED)
            )
            if allow_equipment
            else ()
        )
        return DeviceSnapshot(
            profile_name=self._profile_name,
            records=views,
            equipment={view.device_id: view.instance for view in callable_views},
            setter_filters={
                view.device_id: view.setter_filter for view in callable_views
            },
            getter_filters={
                view.device_id: view.getter_filter for view in callable_views
            },
            generation=generation,
        )

    def _require_calls_available_locked(self, device_id: str | None) -> None:
        if self._teardown_report is not None or self._teardown_in_progress:
            raise DeviceUnavailableError(device_id, "manager teardown has begun")
        if not self._loaded:
            raise DeviceUnavailableError(device_id, "manager profile is not loaded")
        if self._shutdown_intent:
            raise DeviceUnavailableError(device_id, "application shutdown is reserved")
        if self._catalog_desynchronized_error is not None:
            raise DeviceUnavailableError(device_id, "device catalog needs reconciliation")
        if self._mutation_active:
            raise DeviceUnavailableError(device_id, "runtime mutation is in progress")

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
            self._require_loaded_locked(operation)
            if self._mutation_active:
                raise DeviceMutationBusyError(("runtime device mutation in progress",))
            failures: list[LifecycleFailure] = []
            for record in self._records.values():
                before = len(failures)
                self._call_adapter(
                    record,
                    action_name,
                    adapter_method_name,
                    failures,
                )
                if len(failures) != before:
                    record.state = DeviceState.ERROR
                    record.error = failures[-1].describe()
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
            if record.adapter.terminated:
                continue
            before = len(failures)
            self._call_adapter(record, "force stop", "force_stop", failures)
            failure_counts[id(record)] += len(failures) - before

        for record in records:
            if record.adapter.terminated:
                continue
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
            before = len(failures)
            self._call_termination(record, failures)
            failure_counts[id(record)] += len(failures) - before

            before = len(failures)
            self._close_record(record, failures)
            failure_counts[id(record)] += len(failures) - before

            record.state = (
                DeviceState.ERROR
                if failure_counts[id(record)]
                else DeviceState.REMOVED
            )

        return LifecycleReport(operation, tuple(failures))

    @staticmethod
    def _connect_and_confirm(record: _DeviceRecord) -> None:
        result = record.adapter.connect()
        if result is not True:
            raise RuntimeError(
                "connection callback must return literal True after a successful "
                f"bounded connection; received {result!r}"
            )
        if (
            record.adapter.registration.is_connected is not None
            and not record.adapter.connected()
        ):
            raise RuntimeError(
                "connection callback returned True without reporting a connected device"
            )

    @staticmethod
    def _is_known_disconnected(record: _DeviceRecord) -> bool:
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
            failures.append(
                LifecycleFailure.from_exception(
                    record.config.id,
                    action_name,
                    exc,
                )
            )

    @staticmethod
    def _call_termination(
        record: _DeviceRecord,
        failures: list[LifecycleFailure],
    ) -> None:
        if record.adapter.terminated:
            if record.adapter.termination_error is not None:
                failures.append(
                    LifecycleFailure.from_exception(
                        record.config.id,
                        "termination",
                        record.adapter.termination_error,
                    )
                )
            return
        DeviceManager._call_adapter(
            record,
            "termination",
            "terminate",
            failures,
        )
