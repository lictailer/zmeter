"""The device Runner: one worker thread and one priority queue per device
(ADR 004, decision 5).

Every call to a declarative device goes through its Runner, which

* serializes driver calls on one thread, so a driver never sees two calls at
  once;
* orders queued work by priority (stop, scan, panel, poll) and FIFO within a
  priority;
* checks every write against the declared device limit before the driver is
  called, for every source, the panel included;
* bounds every call: each operation has a deadline counted from submission.
  An operation that has not started by its deadline never runs. One that is
  still running gets ``Result.timeout`` and the device becomes "state
  unknown" until the next successful read. The stuck driver call is not
  killed; its late result is logged and discarded. There are no retries;
* owns the lifecycle (connect, disconnect, reset, scan admission, shutdown);
* publishes ``ValueChanged``, ``StateChanged`` and ``LogEntry`` events on an
  ``EventBus``, in the order they happen, from one of its own threads and
  before the caller's future completes. Subscribers must return quickly and
  must not wait on the Runner (the Qt layer re-emits through queued signals).

Callers get a ``Future`` of ``Result`` from ``submit``; ``get``, ``set``,
``call``, ``set_many``, ``connect`` and ``disconnect`` wait for it. A call made
from the Runner's own thread (an action that reads a parameter) runs inline
instead of deadlocking on its own queue.

Not in this module yet (phase 1, PR 5): ramps (a write to a parameter that
declares a ramp is refused, never jumped), ``force_stop``, polling, safe
values, the MultiParameter read cache and ``wait_stable``.

Qt-free and hardware-free, like the rest of ``zcore``.
"""

import heapq
import itertools
import math
import numbers
import os
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any

from .devices import ArrayParameter, Choice, Device, MultiParameter, Parameter, Trigger, Unlimited
from .devices.device import STANDARD_ACTIONS
from .events import ERROR, INFO, WARNING, EventBus, LogEntry, StateChanged, ValueChanged
from .results import Result

DEFAULT_TIMEOUT_S = 10.0
# Extra time the Runner gives a connect beyond the declared connect timeout, so
# a driver that honours its own timeout fails cleanly before the Runner gives up.
CONNECT_GRACE_S = 2.0
# How long begin_scan() and shutdown() wait by default.
DEFAULT_QUIESCE_S = 5.0

LIMIT_REJECTION = "outside device limit"


class Priority(IntEnum):
    """Queue priority; lower runs first."""

    STOP = 0
    SCAN = 1
    PANEL = 2
    POLL = 3


class Source(str, Enum):
    """Who asked for an operation. Recorded on every write and read event."""

    SCAN = "scan"
    PANEL = "panel"
    POLL = "poll"
    TEST = "test"
    RUNNER = "runner"  # reads the Runner makes itself (after connect and reset)


DEFAULT_PRIORITY = {
    Source.SCAN: Priority.SCAN,
    Source.PANEL: Priority.PANEL,
    Source.POLL: Priority.POLL,
    Source.TEST: Priority.PANEL,
    Source.RUNNER: Priority.PANEL,
}


class DeviceState(str, Enum):
    """What the device is doing, as shown in the panel. ``UNKNOWN`` is shown
    as "state unknown": a call timed out or failed, and the device has not
    been read successfully since."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    IDLE = "idle"
    BUSY = "busy"
    ERROR = "error"
    UNKNOWN = "unknown"


class Kind(str, Enum):
    GET = "get"
    SET = "set"
    SET_MANY = "set_many"
    CALL = "call"
    CONNECT = "connect"
    DISCONNECT = "disconnect"


def _check_timeout(timeout):
    if timeout is None:
        return
    if not (
        isinstance(timeout, numbers.Real)
        and not isinstance(timeout, bool)
        and math.isfinite(timeout)
        and timeout > 0
    ):
        raise ValueError(f"timeout must be a finite number of seconds > 0, got {timeout!r}")


def _check_name(name):
    if not (isinstance(name, str) and name):
        raise ValueError(f"operation name must be a non-empty string, got {name!r}")


@dataclass(frozen=True)
class Operation:
    """One request to a device. Build it with the constructors
    (``Operation.get("bias", source="scan")``) and pass it to
    ``Runner.submit``. ``timeout`` overrides the declared or default timeout,
    in seconds, counted from submission."""

    kind: Kind
    name: str | None = None
    value: Any = None
    args: tuple = ()
    source: Source = Source.TEST
    timeout: float | None = None

    def __post_init__(self):
        object.__setattr__(self, "kind", Kind(self.kind))
        object.__setattr__(self, "source", Source(self.source))
        object.__setattr__(self, "args", tuple(self.args))
        _check_timeout(self.timeout)

    @classmethod
    def get(cls, name, *, source, timeout=None):
        _check_name(name)
        return cls(Kind.GET, name, source=source, timeout=timeout)

    @classmethod
    def set(cls, name, value, *, source, timeout=None):
        _check_name(name)
        return cls(Kind.SET, name, value, source=source, timeout=timeout)

    @classmethod
    def set_many(cls, values, *, source, timeout=None):
        pairs = tuple(dict(values).items())
        if not pairs:
            raise ValueError("set_many needs at least one value")
        for name, _value in pairs:
            _check_name(name)
        return cls(Kind.SET_MANY, None, pairs, source=source, timeout=timeout)

    @classmethod
    def call(cls, name, *args, source, timeout=None):
        _check_name(name)
        return cls(Kind.CALL, name, args=args, source=source, timeout=timeout)

    @classmethod
    def connect(cls, address, *, source, timeout=None):
        """``timeout`` is the connect timeout passed to the device; by default
        the device's ``Connection.timeout_s``."""
        return cls(Kind.CONNECT, None, address, source=source, timeout=timeout)

    @classmethod
    def disconnect(cls, *, source, timeout=None):
        return cls(Kind.DISCONNECT, source=source, timeout=timeout)

    def describe(self) -> str:
        if self.kind is Kind.GET:
            return f"get {self.name}"
        if self.kind is Kind.SET:
            return f"set {self.name}={self.value!r}"
        if self.kind is Kind.SET_MANY:
            return "set " + ", ".join(f"{name}={value!r}" for name, value in self.value)
        if self.kind is Kind.CALL:
            return f"{self.name}({', '.join(repr(arg) for arg in self.args)})"
        if self.kind is Kind.CONNECT:
            return f"connect to {self.value!r}"
        return "disconnect"


class ResultFuture(Future):
    """A ``concurrent.futures.Future`` that always ends with a ``Result``.

    It cannot be cancelled from outside: a queued operation ends as
    ``Result.cancelled`` only when the Runner cancels it (disconnect, scan
    start, shutdown), so ``result()`` never raises ``CancelledError``.
    """

    def cancel(self):
        return False


def _is_number(value) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


def check_write(parameter: Parameter, value) -> tuple[bool, Any]:
    """Check a value for a write to ``parameter`` before any driver call.

    Returns ``(True, value)`` with the value converted to the declared type
    (``3.0`` becomes ``3`` for an ``int``, ``8.0`` the option ``8`` of a numeric
    ``Choice``), or ``(False, reason)``. Out-of-range, non-finite and
    not-an-option values give a reason that starts with "outside device
    limit"; a value of the wrong type gives "invalid value".
    """
    dtype = parameter.dtype
    original = value
    if isinstance(dtype, Choice):
        if dtype.is_numeric:
            if not _is_number(value):
                return False, f"invalid value: {value!r} is not a number"
            if not math.isfinite(value):
                return False, f"{LIMIT_REJECTION}: {value!r} is not finite"
        elif not isinstance(value, str):
            return False, f"invalid value: {value!r} is not a string"
        for option in dtype.values:
            if option == value:
                return True, option
        return False, f"{LIMIT_REJECTION}: {value!r} is not one of {list(dtype.values)!r}"
    if dtype in (float, int):
        if not _is_number(value):
            return False, f"invalid value: {value!r} is not a number"
        if not math.isfinite(value):
            return False, f"{LIMIT_REJECTION}: {value!r} is not finite"
        if dtype is int:
            if not float(value).is_integer():
                return False, f"invalid value: {value!r} is not an integer"
            value = int(value)
        else:
            value = float(value)
        limits = parameter.limits
        if not isinstance(limits, Unlimited):
            low, high = limits
            if not low <= value <= high:
                unit = f" {parameter.unit}" if parameter.unit else ""
                return False, f"{LIMIT_REJECTION}: {original!r} is not within [{low!r}, {high!r}]{unit}"
        return True, value
    if dtype is bool:
        if not isinstance(value, bool):
            return False, f"invalid value: {value!r} is not True or False"
        return True, value
    if dtype is str:
        if not isinstance(value, str):
            return False, f"invalid value: {value!r} is not a string"
        return True, value
    if dtype is Path:
        if not isinstance(value, (str, os.PathLike)):
            return False, f"invalid value: {value!r} is not a path"
        return True, Path(value)
    return False, f"invalid value: unsupported type {dtype!r}"


# Job states.
_QUEUED = "queued"
_RUNNING = "running"
_DONE = "done"

# Connection states kept by the Runner; "connected" shows as idle, busy or
# state unknown.
_CONNECTED = "connected"


class _Job:
    __slots__ = ("operation", "priority", "seq", "timeout_s", "deadline", "future", "state", "inline")

    def __init__(self, operation, priority, seq, timeout_s, deadline, inline=False):
        self.operation = operation
        self.priority = priority
        self.seq = seq
        self.timeout_s = timeout_s
        self.deadline = deadline
        self.future = ResultFuture()
        self.state = _QUEUED
        self.inline = inline


@dataclass
class _Outcome:
    """What one executed operation produced. The Runner applies the effects
    only if the operation had not timed out meanwhile."""

    result: Result
    events: list
    unknown: bool | None = None  # True: state unknown; False: cleared by a read
    unknown_reason: str = ""
    link: str | None = None  # new connection state
    link_reason: str = ""


class Runner:
    """Serializes every call to one device instance on one worker thread.

    ``Runner(device, name="sim_device_0", bus=bus)`` starts the worker at
    once. ``name`` labels the events (by default the device class name).
    ``default_timeout_s`` bounds an operation whose parameter declares no
    timeout. Call ``shutdown()`` when done.
    """

    def __init__(self, device, *, name=None, bus=None, default_timeout_s=DEFAULT_TIMEOUT_S):
        if not isinstance(device, Device):
            raise TypeError(f"Runner needs a Device instance, got {device!r}")
        _check_timeout(default_timeout_s)
        if default_timeout_s is None:
            raise ValueError("default_timeout_s is required")
        self._device = device
        self._spec = type(device).spec()
        self.name = name or self._spec.name
        self.bus = bus if bus is not None else EventBus()
        self.default_timeout_s = float(default_timeout_s)
        self._build_tables()

        self._lock = threading.Lock()
        self._work = threading.Condition(self._lock)  # worker: new job or stop
        self._watch = threading.Condition(self._lock)  # watchdog: new deadline or stop
        self._finished = threading.Condition(self._lock)  # a running job finished
        self._queue = []  # heap of (priority, seq, job)
        self._deadlines = []  # heap of (deadline, seq, job)
        self._seq = itertools.count()
        self._pending = 0  # jobs in state _QUEUED
        self._running = None  # job whose driver call is in progress on the worker
        self._watch_wake_at = None
        self._link = DeviceState.DISCONNECTED.value
        self._link_reason = ""
        self._unknown = False
        self._unknown_reason = ""
        self._in_scan = False
        self._closed = False  # no new operations accepted
        self._stopping = False  # worker exits when the queue is empty
        self._watch_stop = False
        self._published = (DeviceState.DISCONNECTED, "")
        self._outbox = deque()
        self._flusher = None

        self._thread = threading.Thread(
            target=self._work_loop, name=f"zmeter-runner-{self.name}", daemon=True
        )
        self._watchdog = threading.Thread(
            target=self._watch_loop, name=f"zmeter-runner-{self.name}-watchdog", daemon=True
        )
        self._thread.start()
        self._watchdog.start()

    def __repr__(self):
        return f"<Runner {self.name!r} {self.state.value}>"

    def _build_tables(self):
        spec = self._spec
        readable = {}
        for name, parameter in spec.parameters.items():
            if parameter.is_readable:
                readable[name] = ("parameter", parameter, None)
        for name, multi in spec.multis.items():
            readable[name] = ("multi", multi, None)
            for component in multi.components:
                readable[component] = ("component", multi, component)
        for name, array in spec.arrays.items():
            readable[name] = ("array", array, None)
        self._readable = readable
        settable = {name: p for name, p in spec.parameters.items() if p.is_settable}
        settable.update(spec.triggers)
        self._settable = settable
        actions = {name: 0 for name in spec.actions}
        actions.update({name: STANDARD_ACTIONS[name] for name in spec.standard_actions})
        self._actions = actions

    # --- public state ---

    @property
    def device(self) -> Device:
        return self._device

    @property
    def spec(self):
        return self._spec

    @property
    def state(self) -> DeviceState:
        with self._lock:
            return self._state_locked()[0]

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._link == _CONNECTED

    @property
    def is_busy(self) -> bool:
        """An operation is running or waiting."""
        with self._lock:
            return self._running is not None or self._pending > 0

    @property
    def in_scan(self) -> bool:
        with self._lock:
            return self._in_scan

    # --- submitting work ---

    def submit(self, operation: Operation, priority: Priority | None = None) -> ResultFuture:
        """Queue ``operation`` and return a future of its ``Result``.

        ``priority`` defaults to the operation's source (scan, panel, poll).
        The future always completes: with the result, with
        ``Result.timeout`` at the deadline, or with ``Result.cancelled`` if
        the Runner drops the operation.
        """
        if not isinstance(operation, Operation):
            raise TypeError(f"submit needs an Operation, got {operation!r}")
        priority = DEFAULT_PRIORITY[operation.source] if priority is None else Priority(priority)
        timeout_s = self._timeout_for(operation)
        if threading.get_ident() == self._thread.ident:
            return self._run_inline(operation, priority, timeout_s)
        resolved = []
        with self._lock:
            refusal = self._refusal_locked(operation)
            if self._closed:
                refusal = "the device Runner is shut down"
            if refusal is not None:
                job = _Job(operation, priority, None, timeout_s, None)
                job.state = _DONE
                resolved.append((job, Result.failed(refusal)))
            else:
                job, cancelled = self._enqueue_locked(operation, priority, timeout_s)
                resolved.extend(cancelled)
        self._resolve(resolved)
        return job.future

    def get(self, name, *, source, timeout=None, priority=None) -> Result:
        return self.submit(Operation.get(name, source=source, timeout=timeout), priority).result()

    def set(self, name, value, *, source, timeout=None, priority=None) -> Result:
        operation = Operation.set(name, value, source=source, timeout=timeout)
        return self.submit(operation, priority).result()

    def set_many(self, values, *, source, timeout=None, priority=None) -> Result:
        operation = Operation.set_many(values, source=source, timeout=timeout)
        return self.submit(operation, priority).result()

    def call(self, name, *args, source, timeout=None, priority=None) -> Result:
        operation = Operation.call(name, *args, source=source, timeout=timeout)
        return self.submit(operation, priority).result()

    def connect(self, address, *, source, timeout=None) -> Result:
        return self.submit(Operation.connect(address, source=source, timeout=timeout)).result()

    def disconnect(self, *, source, timeout=None) -> Result:
        return self.submit(Operation.disconnect(source=source, timeout=timeout)).result()

    # --- scan admission and shutdown ---

    def begin_scan(self, timeout_s: float = DEFAULT_QUIESCE_S) -> bool:
        """A scan takes the device: refuse panel writes and actions, cancel the
        queued ones, and wait up to ``timeout_s`` for a panel call already in
        progress. Returns False if that call did not finish in time (the scan
        must not start). Panel reads stay allowed. Calling it again is
        harmless."""
        _check_timeout(timeout_s)
        until = time.monotonic() + timeout_s
        with self._lock:
            self._in_scan = True
            resolved = self._cancel_queued_locked(
                lambda op: self._refusal_locked(op) is not None,
                "cancelled: a scan started",
            )
            quiesced = True
            while self._running is not None and self._running.operation.source is Source.PANEL:
                remaining = until - time.monotonic()
                if remaining <= 0:
                    quiesced = False
                    break
                self._finished.wait(remaining)
        self._resolve(resolved)
        return quiesced

    def end_scan(self) -> None:
        """The scan has released the device; panel writes are accepted again.
        Calling it again is harmless."""
        with self._lock:
            self._in_scan = False

    def shutdown(self, timeout_s: float = DEFAULT_QUIESCE_S) -> bool:
        """Stop the Runner: refuse new operations, cancel queued ones,
        disconnect the device if needed, and join the worker for at most
        ``timeout_s``. Returns False if the worker did not stop in time (a
        driver call is stuck; the thread is a daemon and is left behind).
        Calling it again only waits again."""
        _check_timeout(timeout_s)
        if threading.get_ident() == self._thread.ident:
            raise RuntimeError("Runner.shutdown() cannot be called from the Runner's own thread")
        until = time.monotonic() + timeout_s
        resolved = []
        with self._lock:
            if not self._closed:
                self._closed = True
                resolved = self._cancel_queued_locked(lambda op: True, "cancelled: Runner shut down")
                operation = Operation.disconnect(source=Source.RUNNER)
                self._enqueue_locked(operation, Priority.STOP, self._timeout_for(operation))
                # (the queue is already empty, so the disconnect cancels nothing)
                self._stopping = True
                self._work.notify_all()
        self._resolve(resolved)
        self._thread.join(max(0.0, until - time.monotonic()))
        stopped = not self._thread.is_alive()
        with self._lock:
            self._watch_stop = True
            self._watch.notify_all()
        self._watchdog.join(max(0.0, until - time.monotonic()))
        return stopped

    # --- queue management (call with the lock held) ---

    def _timeout_for(self, operation):
        if operation.kind is Kind.CONNECT:
            return operation.timeout or self._spec.connection.timeout_s
        if operation.timeout is not None:
            return operation.timeout
        declared = None
        if operation.kind is Kind.GET:
            entry = self._readable.get(operation.name)
            if entry is not None and entry[0] in ("parameter", "array"):
                declared = entry[1].timeout
        elif operation.kind is Kind.SET:
            target = self._settable.get(operation.name)
            if isinstance(target, Parameter):
                declared = target.timeout
        return declared or self.default_timeout_s

    def _enqueue_locked(self, operation, priority, timeout_s):
        """Queue one job. Returns ``(job, cancelled)``; ``cancelled`` lists the
        jobs a disconnect dropped, to be resolved once the lock is released."""
        cancelled = []
        seq = next(self._seq)
        bound = timeout_s + (CONNECT_GRACE_S if operation.kind is Kind.CONNECT else 0.0)
        deadline = time.monotonic() + bound
        job = _Job(operation, priority, seq, timeout_s, deadline)
        if operation.kind is Kind.DISCONNECT:
            # A disconnect drops everything still waiting and runs next.
            cancelled = self._cancel_queued_locked(lambda op: True, "cancelled: device disconnecting")
            job.priority = priority = Priority.STOP
        heapq.heappush(self._queue, (priority, seq, job))
        heapq.heappush(self._deadlines, (deadline, seq, job))
        self._pending += 1
        if self._watch_wake_at is None or deadline < self._watch_wake_at:
            self._watch.notify_all()
        self._work.notify_all()
        self._note_state_locked()
        return job, cancelled

    def _cancel_queued_locked(self, predicate, reason):
        resolved = []
        for _priority, _seq, job in self._queue:
            if job.state == _QUEUED and predicate(job.operation):
                job.state = _DONE
                self._pending -= 1
                resolved.append((job, Result.cancelled(reason=reason)))
        if resolved:
            self._note_state_locked()
        return resolved

    def _refusal_locked(self, operation):
        """Why an operation is refused while a scan holds the device, or None."""
        if not self._in_scan:
            return None
        if operation.kind is Kind.CALL and operation.name in ("reset", "self_test"):
            return f"refused: {operation.name}() is not allowed during a scan"
        if operation.source is Source.PANEL and operation.kind is not Kind.GET:
            return "refused: a scan is using the device"
        return None

    # --- state and events ---

    def _state_locked(self):
        if self._link != _CONNECTED:
            return DeviceState(self._link), self._link_reason
        if self._unknown:
            return DeviceState.UNKNOWN, self._unknown_reason
        if self._running is not None or self._pending:
            return DeviceState.BUSY, ""
        return DeviceState.IDLE, ""

    def _note_state_locked(self):
        current = self._state_locked()
        if current != self._published:
            self._published = current
            self._outbox.append(StateChanged(self.name, current[0].value, current[1]))

    def _log(self, level, message):
        return LogEntry(self.name, level, message)

    def _flush(self):
        """Deliver queued events in order. Only one thread delivers at a time;
        a thread that finds another one delivering leaves its events to it.
        The worker therefore never waits for another thread's subscribers,
        and a nested call from a subscriber does not deadlock on delivery."""
        me = threading.get_ident()
        with self._lock:
            if self._flusher is not None:
                return
            self._flusher = me
        try:
            while True:
                with self._lock:
                    if not self._outbox:
                        self._flusher = None
                        return
                    event = self._outbox.popleft()
                self.bus.publish(event)
        except BaseException:
            with self._lock:
                self._flusher = None
            raise

    def _resolve(self, resolved):
        """Deliver events, then complete futures (so a caller that gets its
        result has normally seen its events already)."""
        self._flush()
        for job, result in resolved:
            try:
                job.future.set_result(result)
            except Exception:
                pass  # already resolved: cannot happen, but never crash a Runner thread

    # --- worker thread ---

    def _work_loop(self):
        while True:
            resolved = []
            with self._lock:
                job = None
                while job is None:
                    while self._queue and self._queue[0][2].state != _QUEUED:
                        heapq.heappop(self._queue)
                    if self._queue:
                        _priority, _seq, job = heapq.heappop(self._queue)
                        self._pending -= 1
                        if job.deadline <= time.monotonic():
                            # Never start an operation whose caller already gave up.
                            job.state = _DONE
                            resolved.append((job, self._not_started(job)))
                            self._note_state_locked()
                            job = None
                            break
                    elif self._stopping:
                        break
                    else:
                        self._work.wait()
                if job is not None:
                    job.state = _RUNNING
                    self._running = job
                    if job.operation.kind is Kind.CONNECT and self._link != _CONNECTED:
                        self._link, self._link_reason = DeviceState.CONNECTING.value, ""
                    self._note_state_locked()
                stop = job is None and not resolved and self._stopping
            if resolved:
                self._resolve(resolved)
                continue
            if stop:
                return
            if job is None:
                continue
            self._flush()
            outcome = self._execute(job)
            self._finish(job, outcome)

    def _run_inline(self, operation, priority, timeout_s):
        job = _Job(operation, priority, None, timeout_s, None, inline=True)
        resolved = []
        with self._lock:
            refusal = self._refusal_locked(operation)
            if refusal is not None:
                job.state = _DONE
                resolved.append((job, Result.failed(refusal)))
            else:
                job.state = _RUNNING
        if resolved:
            self._resolve(resolved)
            return job.future
        outcome = self._execute(job)
        self._finish(job, outcome)
        return job.future

    def _finish(self, job, outcome):
        late_connect = False
        with self._lock:
            if not job.inline and self._running is job:
                self._running = None
            late = job.state == _DONE
            if late:
                # The watchdog already answered the caller with a timeout.
                result = outcome.result
                detail = repr(result.value) if result.is_ok else result.reason
                self._outbox.append(
                    self._log(
                        WARNING,
                        f"Late result of {job.operation.describe()} discarded "
                        f"({result.status.value}: {detail})",
                    )
                )
                kind = job.operation.kind
                if kind is Kind.DISCONNECT and outcome.link is not None:
                    # The hardware did disconnect; keep the state truthful.
                    self._link, self._link_reason = outcome.link, outcome.link_reason
                    self._unknown = False
                late_connect = kind is Kind.CONNECT and result.is_ok
                resolved = []
            else:
                job.state = _DONE
                self._outbox.extend(outcome.events)
                if outcome.link is not None:
                    self._link, self._link_reason = outcome.link, outcome.link_reason
                if outcome.unknown is not None:
                    self._unknown = outcome.unknown
                    self._unknown_reason = outcome.unknown_reason if outcome.unknown else ""
                resolved = [(job, outcome.result)]
            self._note_state_locked()
            self._finished.notify_all()
        if late_connect:
            # The connect the caller gave up on succeeded after all. Leave the
            # device disconnected, as the "error" state says.
            try:
                self._device.disconnect()
                message = "Late connect undone: device disconnected again"
                level = INFO
            except Exception as exc:
                message = f"Late connect could not be undone: {type(exc).__name__}: {exc}"
                level = ERROR
            with self._lock:
                self._outbox.append(self._log(level, message))
        self._resolve(resolved)

    # --- watchdog thread ---

    def _watch_loop(self):
        while True:
            with self._lock:
                if self._watch_stop:
                    return
                now = time.monotonic()
                resolved = self._expire_locked(now)
                if not resolved:
                    while self._deadlines and self._deadlines[0][2].state == _DONE:
                        heapq.heappop(self._deadlines)
                    self._watch_wake_at = self._deadlines[0][0] if self._deadlines else None
                    wait = None if self._watch_wake_at is None else max(0.0, self._watch_wake_at - now)
                    self._watch.wait(wait)
                    continue
            self._resolve(resolved)

    def _not_started(self, job):
        message = (
            f"{job.operation.describe()} did not start within {job.timeout_s:g} s; "
            f"the device was busy with an earlier call"
        )
        self._outbox.append(self._log(WARNING, message))
        return Result.timeout(message)

    def _expire_locked(self, now):
        resolved = []
        while self._deadlines and self._deadlines[0][0] <= now:
            _deadline, _seq, job = heapq.heappop(self._deadlines)
            if job.state == _QUEUED:
                job.state = _DONE
                self._pending -= 1
                resolved.append((job, self._not_started(job)))
            elif job.state == _RUNNING:
                job.state = _DONE
                message = (
                    f"{job.operation.describe()} timed out after {job.timeout_s:g} s; "
                    f"no retry"
                )
                if job.operation.kind is Kind.CONNECT:
                    self._link, self._link_reason = DeviceState.ERROR.value, message
                else:
                    self._unknown, self._unknown_reason = True, message
                self._outbox.append(self._log(WARNING, message))
                resolved.append((job, Result.timeout(message)))
        if resolved:
            self._note_state_locked()
        return resolved

    # --- execution (worker thread, lock not held) ---

    def _invoke(self, ref, *args):
        if isinstance(ref, str):
            return getattr(self._device.driver, ref)(*args)
        return ref(self._device, *args)

    def _failure(self, operation, exc, events=None):
        reason = f"{operation.describe()} failed: {type(exc).__name__}: {exc}"
        events = list(events or ())
        events.append(self._log(ERROR, reason))
        return _Outcome(Result.failed(reason), events, unknown=True, unknown_reason=reason)

    def _rejection(self, operation, reason):
        message = f"{operation.describe()} from {operation.source.value} rejected: {reason}"
        return _Outcome(Result.failed(reason), [self._log(WARNING, message)])

    def _execute(self, job) -> _Outcome:
        operation = job.operation
        handler = {
            Kind.GET: self._do_get,
            Kind.SET: self._do_set,
            Kind.SET_MANY: self._do_set_many,
            Kind.CALL: self._do_call,
            Kind.CONNECT: self._do_connect,
            Kind.DISCONNECT: self._do_disconnect,
        }[operation.kind]
        try:
            return handler(job)
        except Exception as exc:  # a bug in the Runner itself; still answer the caller
            return self._failure(operation, exc)

    def _not_connected(self, operation):
        with self._lock:
            connected = self._link == _CONNECTED
        if connected:
            return None
        return _Outcome(Result.failed("device is not connected"), [])

    def _read(self, name, source):
        """Read one readable name. Returns ``(value, events)``; raises on a
        driver error or a value the scan could not store."""
        kind, declaration, component = self._readable[name]
        if kind == "parameter":
            value = self._invoke(declaration.get)
            if declaration.is_numeric and not _is_number(value):
                raise ValueError(f"driver returned {value!r}, not a number")
            return value, [ValueChanged(self.name, name, value, source.value)]
        if kind == "array":
            value = self._invoke(declaration.get)
            return value, [ValueChanged(self.name, name, value, source.value)]
        raw = self._invoke(declaration.get)
        values = tuple(raw)
        if len(values) != len(declaration.components):
            raise ValueError(
                f"driver returned {len(values)} values for {len(declaration.components)} "
                f"components {declaration.components!r}"
            )
        for value in values:
            if not _is_number(value):
                raise ValueError(f"driver returned {value!r}, not a number")
        by_name = dict(zip(declaration.components, values))
        events = [ValueChanged(self.name, c, v, source.value) for c, v in by_name.items()]
        return (by_name[component] if kind == "component" else by_name), events

    def _do_get(self, job):
        operation = job.operation
        refusal = self._not_connected(operation)
        if refusal:
            return refusal
        if operation.name not in self._readable:
            return _Outcome(Result.failed(f"{operation.name!r} is not a readable name of {self.name}"), [])
        try:
            value, events = self._read(operation.name, operation.source)
        except Exception as exc:
            return self._failure(operation, exc)
        return _Outcome(Result.ok(value), events, unknown=False)

    def _refresh(self, source):
        """Read every readable parameter and multi-parameter once (not arrays).
        Returns ``(events, unknown, unknown_reason)`` after the reads."""
        events, unknown, reason = [], False, ""
        names = [n for n, (kind, _d, _c) in self._readable.items() if kind in ("parameter", "multi")]
        for name in names:
            try:
                _value, read_events = self._read(name, source)
            except Exception as exc:
                reason = f"get {name} failed: {type(exc).__name__}: {exc}"
                events.append(self._log(ERROR, reason))
                unknown = True
            else:
                events.extend(read_events)
                unknown, reason = False, ""
        return events, unknown, reason

    def _admission(self, operation):
        with self._lock:
            refusal = self._refusal_locked(operation)
        if refusal is None:
            return None
        return _Outcome(Result.failed(refusal), [])

    def _do_set(self, job):
        operation = job.operation
        refusal = self._not_connected(operation) or self._admission(operation)
        if refusal:
            return refusal
        name, value = operation.name, operation.value
        target = self._settable.get(name)
        if target is None:
            return _Outcome(Result.failed(f"{name!r} is not a settable name of {self.name}"), [])
        if isinstance(target, Trigger):
            if not _is_number(value):
                return self._rejection(operation, f"invalid value: {value!r} is not a number")
            if not math.isfinite(value):
                return self._rejection(operation, f"{LIMIT_REJECTION}: {value!r} is not finite")
            try:
                self._invoke(target.call)
            except Exception as exc:
                return self._failure(operation, exc)
            return _Outcome(Result.ok(value), [ValueChanged(self.name, name, value, operation.source.value)])
        if target.ramp is not None:
            return self._rejection(
                operation,
                "this Runner does not ramp yet; a direct write to a ramped parameter is refused",
            )
        ok, checked = check_write(target, value)
        if not ok:
            return self._rejection(operation, checked)
        try:
            self._invoke(target.set, checked)
            if isinstance(target.dtype, Choice) and target.dtype.settle_s:
                time.sleep(target.dtype.settle_s)
        except Exception as exc:
            return self._failure(operation, exc)
        return _Outcome(Result.ok(checked), [ValueChanged(self.name, name, checked, operation.source.value)])

    def _do_set_many(self, job):
        operation = job.operation
        refusal = self._not_connected(operation) or self._admission(operation)
        if refusal:
            return refusal
        checked, problems = {}, []
        for name, value in operation.value:
            target = self._settable.get(name)
            if not isinstance(target, Parameter):
                problems.append(f"{name!r} is not a settable parameter of {self.name}")
                continue
            if target.ramp is not None:
                problems.append(f"{name}: this Runner does not ramp yet")
                continue
            ok, result = check_write(target, value)
            if ok:
                checked[name] = result
            else:
                problems.append(f"{name}: {result}")
        if problems:
            # All or nothing: no value is written when one is refused.
            return self._rejection(operation, "; ".join(problems))
        source = operation.source.value
        settle = max(
            (
                self._settable[name].dtype.settle_s
                for name in checked
                if isinstance(self._settable[name].dtype, Choice)
            ),
            default=0.0,
        )
        if self._spec.has_write_many:
            try:
                self._device.write_many(dict(checked))
                if settle:
                    time.sleep(settle)
            except Exception as exc:
                return self._failure(operation, exc)
            events = [ValueChanged(self.name, n, v, source) for n, v in checked.items()]
            return _Outcome(Result.ok(dict(checked)), events)
        events, written = [], {}
        for name, value in checked.items():
            target = self._settable[name]
            try:
                self._invoke(target.set, value)
                if isinstance(target.dtype, Choice) and target.dtype.settle_s:
                    time.sleep(target.dtype.settle_s)
            except Exception as exc:
                outcome = self._failure(operation, exc, events)
                done = ", ".join(written) or "nothing"
                reason = f"{outcome.result.reason} (already written: {done})"
                outcome.result = Result.failed(reason)
                return outcome
            written[name] = value
            events.append(ValueChanged(self.name, name, value, source))
        return _Outcome(Result.ok(written), events)

    def _do_call(self, job):
        operation = job.operation
        refusal = self._not_connected(operation) or self._admission(operation)
        if refusal:
            return refusal
        name, args = operation.name, operation.args
        if name not in self._actions:
            return _Outcome(Result.failed(f"{name!r} is not an action of {self.name}"), [])
        expected = self._actions[name]
        if len(args) != expected:
            return _Outcome(Result.failed(f"{name}() takes {expected} argument(s), got {len(args)}"), [])
        if name == "set_display" and not isinstance(args[0], bool):
            return _Outcome(Result.failed(f"set_display() needs True or False, got {args[0]!r}"), [])
        try:
            value = getattr(self._device, name)(*args)
        except Exception as exc:
            return self._failure(operation, exc)
        events = [self._log(INFO, f"{operation.describe()} done ({operation.source.value})")]
        if name == "reset":
            read_events, unknown, reason = self._refresh(Source.RUNNER)
            events.extend(read_events)
            return _Outcome(Result.ok(value), events, unknown=unknown, unknown_reason=reason)
        return _Outcome(Result.ok(value), events)

    def _do_connect(self, job):
        operation = job.operation
        with self._lock:
            already = self._link == _CONNECTED
        if already:
            return _Outcome(Result.ok(), [])
        address = operation.value
        try:
            self._device.connect(address, job.timeout_s)
        except Exception as exc:
            reason = f"{operation.describe()} failed: {type(exc).__name__}: {exc}"
            return _Outcome(
                Result.failed(reason),
                [self._log(ERROR, reason)],
                link=DeviceState.ERROR.value,
                link_reason=reason,
            )
        events = [self._log(INFO, f"Connected to {address!r}")]
        read_events, unknown, reason = self._refresh(Source.RUNNER)
        events.extend(read_events)
        for name, parameter in self._spec.parameters.items():
            if isinstance(parameter.limits, Unlimited):
                events.append(
                    self._log(WARNING, f"[Limits] {name} has no device limit: {parameter.limits.reason}")
                )
        return _Outcome(
            Result.ok(), events, unknown=unknown, unknown_reason=reason, link=_CONNECTED
        )

    def _do_disconnect(self, job):
        operation = job.operation
        with self._lock:
            link = self._link
        if link == DeviceState.DISCONNECTED.value:
            return _Outcome(Result.ok(), [])
        try:
            self._device.disconnect()
        except Exception as exc:
            reason = f"{operation.describe()} failed: {type(exc).__name__}: {exc}"
            return _Outcome(
                Result.failed(reason),
                [self._log(ERROR, reason)],
                link=DeviceState.ERROR.value,
                link_reason=reason,
            )
        return _Outcome(
            Result.ok(),
            [self._log(INFO, "Disconnected")],
            unknown=False,
            link=DeviceState.DISCONNECTED.value,
        )
