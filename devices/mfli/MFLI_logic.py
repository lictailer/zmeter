"""Serialized MFLI jobs, Qt notifications, and explicit scalar scan channels."""
from __future__ import annotations

from collections import deque
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass
import threading
import time

from PyQt6 import QtCore

if __package__:
    from .MFLI_hardware import MFLIHardware, TransportError
else:
    from MFLI_hardware import MFLIHardware, TransportError


@dataclass(frozen=True)
class Job:
    action: str
    args: tuple
    future: Future
    deadline: float | None = None


@dataclass(frozen=True)
class Completion:
    job: Job
    result: object
    error: Exception | None
    connected: bool
    cleanup_needed: bool


class _Worker(QtCore.QThread):
    completed = QtCore.pyqtSignal(object)
    state_changed = QtCore.pyqtSignal()

    def __init__(self, hardware: MFLIHardware):
        super().__init__()
        self.hardware = hardware
        self._condition = threading.Condition()
        self._jobs: deque[Job] = deque()
        self._active = False
        self._accepting = True
        self.ready = False
        self.client_present = False
        self.scan_active = False
        self.stopped = False
        self.monitor_enabled = False
        self._resume_monitor = False
        self._active_job: Job | None = None
        self._abandoned_connections: set[Future] = set()
        self._shutdown_future: Future | None = None

    def snapshot(self):
        with self._condition:
            return (self.ready, self.client_present, self.scan_active,
                    self.monitor_enabled, self.stopped, not self._accepting)

    def monitoring(self, enabled: bool):
        with self._condition:
            if enabled and (self.scan_active or self.stopped or not self.ready or not self._accepting):
                raise RuntimeError("Monitoring is unavailable while disconnected, scanning, or stopping.")
            self.monitor_enabled = enabled
        self.state_changed.emit()

    def _cancel_pending(self):
        retained = deque()
        while self._jobs:
            pending = self._jobs.popleft()
            if pending.action in {"disconnect", "shutdown"}:
                retained.append(pending)
                continue
            pending.future.cancel()
            self.completed.emit(Completion(
                pending, None, InterruptedError("Pending command cancelled."),
                self.ready, self.client_present,
            ))
        self._jobs = retained

    def force_stop(self):
        with self._condition:
            self.stopped = True
            self.monitor_enabled = False
            self.hardware.cancel.set()
            self._cancel_pending()
            if self._active_job and self._active_job.action == "connect":
                self._abandoned_connections.add(self._active_job.future)
        self.state_changed.emit()

    def abandon_connection(self, future):
        with self._condition:
            if future.done():
                return
            self._abandoned_connections.add(future)
            self.hardware.cancel.set()
        self.state_changed.emit()

    def submit(self, action: str, *args, origin="panel", timeout_ms=10_000) -> Future:
        future = Future()
        with self._condition:
            if action == "shutdown" and self._shutdown_future is not None:
                return self._shutdown_future
            if not self._accepting:
                raise RuntimeError("MFLI is disconnecting or closing.")
            lifecycle = action in {"prepare_scan", "resume", "disconnect", "shutdown"}
            if self.scan_active and origin == "panel" and action not in {"prepare_scan", "resume", "shutdown"}:
                raise RuntimeError("MFLI panel operations are suspended during the scan.")
            if not lifecycle and self.stopped:
                raise RuntimeError("MFLI is stopped; finish scan cleanup or reconnect first.")
            if action == "connect" and (self._active or self._jobs or self.ready or self.client_present):
                raise RuntimeError("MFLI is busy or already connected; disconnect first.")
            if len(self._jobs) >= 64:
                raise RuntimeError("MFLI command queue is full.")
            if action == "monitor" and (self._active or self._jobs):
                future.cancel()  # Skip this tick instead of building a backlog.
                return future
            if action == "prepare_scan":
                if not self.scan_active:
                    self._resume_monitor = self.monitor_enabled
                self.scan_active = True
                self.monitor_enabled = False
                self.hardware.cancel.set()
                self._cancel_pending()
            if action in {"disconnect", "shutdown"}:
                self._accepting = False
                self.hardware.cancel.set()
                self.monitor_enabled = False
                self._cancel_pending()
                if self._active_job and self._active_job.action == "connect":
                    self._abandoned_connections.add(self._active_job.future)
                if action == "shutdown":
                    self._shutdown_future = future
            deadline = time.monotonic() + timeout_ms / 1000 if action == "connect" else None
            self._jobs.append(Job(action, args, future, deadline))
            self._condition.notify()
        self.state_changed.emit()
        return future

    def busy(self, *, include_monitor=True) -> bool:
        with self._condition:
            if not include_monitor:
                active = self._active_job is not None and self._active_job.action != "monitor"
                return active or any(job.action != "monitor" for job in self._jobs)
            return self._active or bool(self._jobs)

    def _execute(self, job: Job):
        action, args = job.action, job.args
        if action == "connect":
            if time.monotonic() >= job.deadline:
                raise TimeoutError("MFLI connection expired before execution.")
            return self.hardware.connect(*args)
        if action == "prepare_scan":
            # Barrier: earlier operations have finished before cancellation clears.
            if not self.stopped:
                self.hardware.cancel.clear()
            return None
        if action == "resume":
            with self._condition:
                self.hardware.cancel.clear()
                self.scan_active = False
                self.stopped = False
                self.monitor_enabled = self._resume_monitor and self.ready
                self._resume_monitor = False
            return None
        if action in {"disconnect", "shutdown"}:
            with self._condition:
                self.ready = False
            return self.hardware.disconnect()
        if not self.ready:
            raise RuntimeError("MFLI is disconnected; connect before issuing commands.")
        operations = {
            "refresh": self.hardware.refresh_settings,
            "monitor": self.hardware.monitor,
            "amplitude": self.hardware.write_amplitude,
            "phase": self.hardware.write_phase,
            "offset": self.hardware.write_offset,
            "read": self.hardware.read_fresh,
        }
        if action not in operations:
            raise ValueError(f"Unknown MFLI action: {action}")
        return operations[action](*args)

    def run(self):
        while True:
            with self._condition:
                while not self._jobs:
                    self._condition.wait()
                job = self._jobs.popleft()
                self._active = True
                self._active_job = job
            result, error = None, None
            if job.future.set_running_or_notify_cancel():
                try:
                    result = self._execute(job)
                    if job.action == "connect":
                        # Publish completion atomically with the deadline check.
                        # A manager timeout can abandon the attempt under this lock.
                        with self._condition:
                            abandoned = (job.future in self._abandoned_connections
                                         or time.monotonic() >= job.deadline)
                            if not abandoned:
                                self.ready = True
                                self.client_present = True
                                job.future.set_result(result)
                        if abandoned:
                            self.hardware.disconnect()
                            raise TimeoutError("MFLI connection cancelled or timed out; late client closed.")
                except Exception as exc:
                    error = exc
                    if isinstance(exc, TransportError):
                        with self._condition:
                            self.ready = False
                            self.monitor_enabled = False
                        # Do not retry a setting write: it may already have applied.
                        try:
                            self.hardware.disconnect()
                        except Exception as cleanup:
                            error = TransportError(f"{exc}; client cleanup also failed: {cleanup}")
                    if job.action == "connect":
                        with self._condition:
                            self.ready = False
            else:
                error = InterruptedError("Command cancelled before execution.")
            with self._condition:
                self._active = False
                self._active_job = None
                self.client_present = self.hardware.connected
                self._abandoned_connections.discard(job.future)
                if job.action in {"disconnect", "shutdown"}:
                    self._accepting = job.action == "disconnect" or error is not None
                    self.hardware.cancel.clear()
                    self.stopped = False
                    if error is not None:
                        self._shutdown_future = None
                if not job.future.done():
                    if error is None:
                        job.future.set_result(result)
                    else:
                        job.future.set_exception(error)
            self.completed.emit(Completion(
                job, result, error, self.ready, self.hardware.connected,
            ))
            self.state_changed.emit()
            if job.action == "shutdown" and error is None:
                return


class MFLILogic(QtCore.QObject):
    completed = QtCore.pyqtSignal(object)
    log = QtCore.pyqtSignal(str, str)
    stopped = QtCore.pyqtSignal()
    state_changed = QtCore.pyqtSignal()

    def __init__(self, hardware: MFLIHardware | None = None):
        super().__init__()
        self._problems: dict[int, str] = {}
        self._caller = threading.local()
        self._worker = _Worker(hardware if hardware is not None else MFLIHardware())
        self._worker.completed.connect(self._on_completed)
        self._worker.finished.connect(self.stopped)
        self._worker.state_changed.connect(self.state_changed)
        self._worker.start()  # Idle worker only; no connection or discovery.

    @property
    def connected(self):
        return self._worker.snapshot()[0]

    @property
    def cleanup_needed(self):
        return self._worker.snapshot()[1]

    @property
    def scan_active(self):
        return self._worker.snapshot()[2]

    @property
    def monitoring(self):
        return self._worker.snapshot()[3]

    @property
    def stopping(self):
        state = self._worker.snapshot()
        return state[4] or state[5]

    def monitoring_request(self, enabled: bool):
        self._worker.monitoring(enabled)

    def request(self, action: str, *args, timeout_ms=10_000) -> Future:
        """Nonblocking UI API; completions arrive as signals on the UI thread."""
        if not self._worker.isRunning():
            raise RuntimeError("MFLI worker has stopped.")
        return self._worker.submit(action, *args, timeout_ms=timeout_ms)

    def connect_device(self, device, host, port, timeout_ms=10_000):
        future = self.request("connect", device, host, port, timeout_ms=timeout_ms)
        try:
            future.result(timeout_ms / 1000)
        except TimeoutError:
            self._worker.abandon_connection(future)
            raise
        return self.connected

    def connection_deadline(self, future):
        if not future.done():
            self._worker.abandon_connection(future)
            self.log.emit("ERROR", "Connection timed out; waiting for the active API call and client cleanup.")

    def disconnect_device(self, timeout_ms=10_000):
        return self.request("disconnect").result(timeout_ms / 1000)

    def stop_scan(self, timeout_ms=10_000):
        """Manager calls this BEFORE the scan, not at its completion."""
        # The manager calls scan lifecycle on the boundary worker. Waiting for
        # the FIFO barrier makes preparation completion truthful without
        # blocking Qt event processing.
        return self.request("prepare_scan").result(timeout_ms / 1000)

    def start_scan(self, timeout_ms=10_000):
        """Manager calls this AFTER the scan; restore prior monitor intent."""
        return self.request("resume").result(timeout_ms / 1000)

    def force_stop(self):
        self._worker.force_stop()

    def terminate(self, timeout_ms=10_000):
        if not self._worker.isRunning():
            return True
        deadline = time.monotonic() + timeout_ms / 1000
        self.request("shutdown").result(timeout_ms / 1000)
        remaining = max(0, int((deadline - time.monotonic()) * 1000))
        if not self._worker.wait(remaining):
            raise TimeoutError("MFLI worker has not finished; retain the device for cleanup.")
        return True

    def assert_terminated(self):
        if self._worker.isRunning() or self.cleanup_needed:
            raise RuntimeError("MFLI cleanup is unfinished; the widget/worker must be retained.")

    def busy(self) -> bool:
        return self._worker.busy()

    def lifecycle_busy(self) -> bool:
        # Passive monitoring must not veto application shutdown. Teardown
        # cancels it and waits for its active API call within the normal budget.
        return self._worker.busy(include_monitor=False)

    @contextmanager
    def routed_request(self):
        """Router/manual requests obey the same scan gate as panel commands."""
        previous = getattr(self._caller, "origin", "scan")
        self._caller.origin = "panel"
        try:
            yield
        finally:
            self._caller.origin = previous

    @QtCore.pyqtSlot(object)
    def _on_completed(self, event: Completion):
        action = event.job.action
        if event.error is not None:
            detail = f" {event.job.args}" if event.job.args else ""
            self.log.emit("ERROR", f"{action}{detail}: {type(event.error).__name__}: {event.error}")
        elif action == "connect":
            identity, _ = event.result
            self._problems.clear()
            self.log.emit("INFO", f"Connected {identity['type']} {identity['serial']}; "
                          f"API {identity['api']}, server {identity['server']}; "
                          f"options: {identity['options'] or '(none)'}. Version differences allowed.")
        elif action in {"disconnect", "shutdown"}:
            self._problems.clear()
            self.log.emit("INFO", "Client closed. Instrument settings remain applied.")
        elif action == "monitor":
            batch = event.result
            for channel, message in batch.problems.items():
                if self._problems.get(channel) != message:
                    self.log.emit("WARN", message)
            # Recovery requires a new sample, not merely absence of an error.
            for channel in batch.samples:
                if channel in self._problems:
                    self.log.emit("INFO", f"Demodulator {channel}: fresh data resumed.")
                    self._problems.pop(channel)
            self._problems.update(batch.problems)
        self.completed.emit(event)

    def _sync(self, action: str, *args):
        if not self._worker.isRunning():
            raise RuntimeError("MFLI worker has stopped.")
        app = QtCore.QCoreApplication.instance()
        if app is not None and QtCore.QThread.currentThread() == app.thread():
            raise RuntimeError("Synchronous MFLI channels cannot run on the GUI thread; use request().")
        return self._worker.submit(action, *args, origin=getattr(self._caller, "origin", "scan")).result()

    def _read(self, channel: int, quantity: str) -> float:
        return float(getattr(self._sync("read", channel), quantity))

    # Explicit methods keep scan discovery and tracebacks easy to inspect.
    def set_OSC1_amplitude(self, value):
        return self._sync("amplitude", 1, value)

    def set_OSC2_amplitude(self, value):
        return self._sync("amplitude", 2, value)

    def set_OSC3_amplitude(self, value):
        return self._sync("amplitude", 3, value)

    def set_OSC4_amplitude(self, value):
        return self._sync("amplitude", 4, value)

    def set_OSC1_phase(self, value):
        return self._sync("phase", 1, value)

    def set_OSC2_phase(self, value):
        return self._sync("phase", 2, value)

    def set_OSC3_phase(self, value):
        return self._sync("phase", 3, value)

    def set_OSC4_phase(self, value):
        return self._sync("phase", 4, value)

    def set_output_DCoffset(self, value):
        return self._sync("offset", value)

    def get_DEMOD1_X(self):
        return self._read(1, "X")

    def get_DEMOD1_Y(self):
        return self._read(1, "Y")

    def get_DEMOD1_R(self):
        return self._read(1, "R")

    def get_DEMOD1_theta(self):
        return self._read(1, "theta")

    def get_DEMOD2_X(self):
        return self._read(2, "X")

    def get_DEMOD2_Y(self):
        return self._read(2, "Y")

    def get_DEMOD2_R(self):
        return self._read(2, "R")

    def get_DEMOD2_theta(self):
        return self._read(2, "theta")

    def get_DEMOD3_X(self):
        return self._read(3, "X")

    def get_DEMOD3_Y(self):
        return self._read(3, "Y")

    def get_DEMOD3_R(self):
        return self._read(3, "R")

    def get_DEMOD3_theta(self):
        return self._read(3, "theta")

    def get_DEMOD4_X(self):
        return self._read(4, "X")

    def get_DEMOD4_Y(self):
        return self._read(4, "Y")

    def get_DEMOD4_R(self):
        return self._read(4, "R")

    def get_DEMOD4_theta(self):
        return self._read(4, "theta")
