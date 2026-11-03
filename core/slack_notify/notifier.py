"""Sends Slack messages without ever making a scan wait.

Callers (the UI thread, a scan worker or a manual-set thread) only put a job
in a bounded in-memory outbox and return.  One daemon thread takes jobs out
and talks to Slack with short timeouts.  Any failure becomes one line in the
system log; nothing is raised back to the caller.  Unsent jobs are dropped
when ZMeter closes, because the daemon thread is never joined.
"""

from __future__ import annotations

import datetime as _dt
import platform
import queue
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, Sequence

from PyQt6 import QtCore

from . import messages
from .client import SlackClient, SlackError

OUTBOX_SIZE = 50
# At most one default_slack_notification message per this many seconds;
# writes in between are counted into the next message.
PING_INTERVAL_S = 15.0


@dataclass(frozen=True)
class _Job:
    kind: str  # "scan", "queue", "ping", "test" or "stop"
    token: str = ""
    email: str = ""
    text: str = ""
    png: bytes | None = None
    filename: str = ""
    label: str = ""


def pc_name() -> str:
    return platform.node() or "ZMeter PC"


def _png_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("._") or "scan"
    return f"{cleaned[:80]}.png"


class SlackNotifier(QtCore.QObject):
    """One per main window.  Settings are plain attributes set on the UI
    thread; the send methods may be called from any thread."""

    # (ok, message) for the Test button, delivered on the UI thread.
    sig_test_result = QtCore.pyqtSignal(bool, str)

    def __init__(
        self,
        log: Callable[[str, str], object] | None = None,
        parent=None,
        *,
        client_factory: Callable[[str], SlackClient] | None = None,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], _dt.datetime] = _dt.datetime.now,
        pc: str | None = None,
        ping_interval_s: float = PING_INTERVAL_S,
    ):
        super().__init__(parent)
        self._log_callable = log
        self._client_factory = client_factory or SlackClient
        self._clock = clock
        self._now = now
        self.pc_name = pc or pc_name()
        self.ping_interval_s = float(ping_interval_s)

        self._token = ""
        self._email = ""
        self._active = False

        self._outbox: queue.Queue[_Job] = queue.Queue(maxsize=OUTBOX_SIZE)
        self._thread: threading.Thread | None = None
        self._thread_lock = threading.Lock()
        self._busy = False

        # Worker-thread state.
        self._dm_cache: dict[tuple[str, str], str] = {}
        self._next_ping_at = 0.0
        self._carried_pings = 0
        self._carried_job: _Job | None = None

        # The last scan a running queue finished: (name, status, png).
        self._last_queue_scan: tuple[str, str, bytes | None] | None = None

    # ----------------------------------------------------------- settings --
    def set_token(self, token: str) -> None:
        self._token = (token or "").strip()

    def set_email(self, email: str) -> None:
        self._email = (email or "").strip()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)

    @property
    def has_token(self) -> bool:
        return bool(self._token)

    @property
    def ready(self) -> bool:
        """A token and an email are set, so Active may be ticked."""

        return bool(self._token and self._email)

    @property
    def active(self) -> bool:
        return self._active and self.ready

    # -------------------------------------------------------------- sends --
    def scan_finished(
        self,
        *,
        name: str,
        status: str,
        elapsed_seconds,
        completed_points,
        total_points,
        png: bytes | None = None,
        error_message: str | None = None,
        queue_run: bool = False,
    ) -> None:
        """A scan ended.  A scan run by the queue only remembers its result
        for the queue-end message."""

        if queue_run:
            self._last_queue_scan = (str(name), str(status), png)
            return
        if not self.active:
            return
        text = messages.scan_text(
            status=status,
            name=name,
            elapsed_seconds=elapsed_seconds,
            completed_points=completed_points,
            total_points=total_points,
            ended=self._now(),
            pc_name=self.pc_name,
            error_message=error_message,
        )
        self._enqueue(
            self._job("scan", text=text, png=png, filename=_png_name(name), label=f"scan {name}")
        )

    def channel_written(self, _value=None) -> None:
        """``default_slack_notification`` was written.  Returns at once."""

        if not self.active:
            return
        self._enqueue(self._job("ping", label="notification"))

    def queue_started(self) -> None:
        self._last_queue_scan = None

    def queue_finished(
        self,
        *,
        reason: str,
        done: int,
        total: int,
        failed: Sequence[str],
        elapsed_seconds,
    ) -> None:
        last = self._last_queue_scan
        self._last_queue_scan = None
        if not self.active:
            return
        text = messages.queue_text(
            reason=reason,
            done=done,
            total=total,
            failed=failed,
            elapsed_seconds=elapsed_seconds,
            pc_name=self.pc_name,
            last_scan=(last[0], last[1]) if last is not None else None,
        )
        png = last[2] if last is not None else None
        filename = _png_name(last[0]) if last is not None else ""
        self._enqueue(self._job("queue", text=text, png=png, filename=filename, label="queue end"))

    def test(self) -> None:
        """Send the test message; the result arrives on ``sig_test_result``."""

        if not self._token:
            self.sig_test_result.emit(False, "Save a bot token first.")
            return
        if not self._email:
            self.sig_test_result.emit(False, "Type your Slack email first.")
            return
        if not self._enqueue(self._job("test", text=messages.check_text(self.pc_name), label="test")):
            self.sig_test_result.emit(False, "Slack outbox is full; try again later.")

    # ------------------------------------------------------------ helpers --
    def _job(self, kind: str, **fields) -> _Job:
        return _Job(kind=kind, token=self._token, email=self._email, **fields)

    def _log(self, level: str, message: str) -> None:
        if self._log_callable is None:
            return
        try:
            self._log_callable(level, message)
        except Exception:  # noqa: BLE001 - logging must never break a send
            pass

    def _enqueue(self, job: _Job) -> bool:
        try:
            self._outbox.put_nowait(job)
        except queue.Full:
            self._log("WARNING", f"Slack: outbox full, {job.label} message dropped.")
            return False
        self._ensure_worker()
        return True

    def _ensure_worker(self) -> None:
        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, name="SlackNotifier", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        """Ask the worker to end after the jobs already queued (not waited for)."""

        try:
            self._outbox.put_nowait(_Job(kind="stop"))
        except queue.Full:
            pass

    def wait_until_idle(self, timeout: float) -> bool:
        """For tests: wait until the outbox is empty and nothing is sending."""

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._outbox.empty() and not self._busy and not self._carried_pings:
                return True
            time.sleep(0.005)
        return False

    # ------------------------------------------------------- worker thread --
    def _run(self) -> None:
        while True:
            timeout = None
            if self._carried_pings:
                timeout = max(0.0, self._next_ping_at - self._clock())
            try:
                job = self._outbox.get(timeout=timeout)
            except queue.Empty:
                job = None
            self._busy = True
            try:
                if job is None:
                    self._flush_carried_pings()
                elif job.kind == "stop":
                    return
                elif job.kind == "ping":
                    self._handle_ping(job)
                else:
                    self._deliver(job)
            except Exception as exc:  # noqa: BLE001 - the worker must survive
                self._log("WARNING", f"Slack: unexpected {type(exc).__name__}: {exc}")
            finally:
                self._busy = False

    def _handle_ping(self, job: _Job) -> None:
        if self._clock() >= self._next_ping_at and not self._carried_pings:
            self._send_ping(job, count=1)
            return
        self._carried_pings += 1
        self._carried_job = job

    def _flush_carried_pings(self) -> None:
        if not self._carried_pings or self._carried_job is None:
            self._carried_pings = 0
            return
        if self._clock() < self._next_ping_at:
            return
        count, job = self._carried_pings, self._carried_job
        self._carried_pings, self._carried_job = 0, None
        self._send_ping(job, count=count)

    def _send_ping(self, job: _Job, *, count: int) -> None:
        self._next_ping_at = self._clock() + self.ping_interval_s
        text = messages.notification_text(count=count, when=self._now(), pc_name=self.pc_name)
        self._deliver(_Job(kind="ping", token=job.token, email=job.email, text=text, label=job.label))

    def _dm_channel(self, client: SlackClient, email: str) -> str:
        key = (client.token, email.lower())
        channel = self._dm_cache.get(key)
        if channel:
            return channel
        user_id = client.lookup_user_id(email)
        channel = client.open_dm(user_id)
        self._dm_cache[key] = channel
        return channel

    def _deliver(self, job: _Job) -> None:
        try:
            client = self._client_factory(job.token)
            if job.kind == "test":
                client.auth_test()
            channel = self._dm_channel(client, job.email)
            try:
                if job.png:
                    client.upload_png(channel, job.png, job.filename or "zmeter.png", job.text)
                else:
                    client.post_text(channel, job.text)
            except SlackError as exc:
                if exc.code in ("channel_not_found", "not_in_channel", "is_archived"):
                    self._dm_cache.pop((client.token, job.email.lower()), None)
                raise
        except SlackError as exc:
            message = f"Slack: {job.label} message not sent ({exc.method}: {exc.code})."
            self._log("WARNING", message)
            if job.kind == "test":
                self.sig_test_result.emit(False, f"{exc.method}: {exc.code}")
            return
        except Exception as exc:  # noqa: BLE001
            self._log("WARNING", f"Slack: {job.label} message not sent ({type(exc).__name__}: {exc}).")
            if job.kind == "test":
                self.sig_test_result.emit(False, f"{type(exc).__name__}: {exc}")
            return
        self._log("INFO", f"Slack: {job.label} message sent.")
        if job.kind == "test":
            self.sig_test_result.emit(True, "Test message sent.")
