"""Slack notifications: message text, the non-blocking notifier, the token
store, the main-window row and the scan/queue hooks.  No test touches Slack
or the network: every HTTP call goes to a fake session."""

import datetime as dt
import json
import os
import sys
import threading
import time
import types
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from core.slack_notify import SLACK_NOTIFICATION_CHANNEL, messages
from core.slack_notify import notifier as notifier_module
from core.slack_notify.client import SlackClient
from core.slack_notify.notifier import SlackNotifier
from core.slack_notify.settings import SlackTokenStore

T = dt.datetime(2026, 11, 2, 14, 32)
PC = "XuguoOffice"
TOKEN = "xoxb-test-token-never-real"
EMAIL = "someone@example.com"


_APP = None


def app():
    global _APP
    _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _APP


class FakeResponse:
    def __init__(self, body=None, status_code=200):
        self._body = body if body is not None else {"ok": True}
        self.status_code = status_code

    def json(self):
        return self._body


class FakeSession:
    """Records every request; answers like Slack, with optional overrides."""

    def __init__(self, overrides=None, hang=None):
        self.calls = []
        self.overrides = dict(overrides or {})
        self.hang = hang  # threading.Event: block every request until set
        self.lock = threading.Lock()

    def _answer(self, method):
        if method in self.overrides:
            return self.overrides[method]
        defaults = {
            "auth.test": {"ok": True},
            "users.lookupByEmail": {"ok": True, "user": {"id": "U1"}},
            "conversations.open": {"ok": True, "channel": {"id": "D1"}},
            "chat.postMessage": {"ok": True},
            "files.getUploadURLExternal": {
                "ok": True,
                "upload_url": "https://files.slack.test/upload/abc",
                "file_id": "F1",
            },
            "files.completeUploadExternal": {"ok": True},
        }
        return defaults.get(method, {"ok": True})

    def _record(self, http, url, **kwargs):
        if self.hang is not None:
            self.hang.wait(30)
        with self.lock:
            self.calls.append((http, url, kwargs))
        if url.startswith("https://files.slack.test/"):
            return FakeResponse({}, 200)
        method = url.rsplit("/", 1)[-1]
        return FakeResponse(self._answer(method))

    def get(self, url, **kwargs):
        return self._record("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._record("POST", url, **kwargs)

    def methods(self):
        with self.lock:
            return [url.rsplit("/", 1)[-1] for _http, url, _kw in self.calls]

    def posted_texts(self):
        with self.lock:
            out = []
            for _http, url, kw in self.calls:
                data = kw.get("data")
                if url.endswith("chat.postMessage"):
                    out.append(data["text"])
                elif url.endswith("files.completeUploadExternal"):
                    out.append(data["initial_comment"])
            return out


def make_notifier(session=None, *, active=True, interval=15.0, logs=None):
    session = session if session is not None else FakeSession()
    logs = logs if logs is not None else []
    notifier = SlackNotifier(
        log=lambda level, message: logs.append((level, message)),
        client_factory=lambda token: SlackClient(token, session=session),
        now=lambda: T,
        pc=PC,
        ping_interval_s=interval,
    )
    notifier.set_token(TOKEN)
    notifier.set_email(EMAIL)
    notifier.set_active(active)
    return notifier, session, logs


class MessageTextTests(unittest.TestCase):
    """The texts the user reviewed in the plan, word for word."""

    def test_scan_messages(self):
        self.assertEqual(
            messages.scan_text(
                status="completed", name="0123_gate_map", elapsed_seconds=6130,
                completed_points=400, total_points=400, ended=T, pc_name=PC,
            ),
            ":white_check_mark: Scan completed: 0123_gate_map\n"
            "1:42:10 · 400/400 points · ended 14:32 · XuguoOffice",
        )
        self.assertEqual(
            messages.scan_text(
                status="stopped", name="0123_gate_map", elapsed_seconds=723,
                completed_points=87, total_points=400, ended=T, pc_name=PC,
            ),
            ":black_square_for_stop: Scan stopped: 0123_gate_map\n"
            "0:12:03 · 87/400 points · ended 14:32 · XuguoOffice",
        )
        self.assertEqual(
            messages.scan_text(
                status="error", name="0123_gate_map", elapsed_seconds=341,
                completed_points=33, total_points=400, ended=T, pc_name=PC,
                error_message="sr830_0 read timed out\nTraceback ...",
            ),
            ":warning: Scan error: 0123_gate_map\n"
            "0:05:41 · 33/400 points · ended 14:32 · XuguoOffice\n"
            "Error: sr830_0 read timed out",
        )

    def test_long_error_line_is_cut(self):
        text = messages.scan_text(
            status="error", name="s", elapsed_seconds=1, completed_points=0,
            total_points=1, ended=T, pc_name=PC, error_message="x" * 500,
        )
        self.assertEqual(len(text.splitlines()[-1]), len("Error: ") + 200)

    def test_notification_messages(self):
        self.assertEqual(
            messages.notification_text(count=1, when=T, pc_name=PC),
            ":bell: ZMeter notification · 14:32 · XuguoOffice",
        )
        self.assertEqual(
            messages.notification_text(count=4, when=T, pc_name=PC),
            ":bell: ZMeter notification ×4 · 14:32 · XuguoOffice",
        )

    def test_queue_messages(self):
        self.assertEqual(
            messages.queue_text(
                reason="completed", done=7, total=7, failed=[],
                elapsed_seconds=21912, pc_name=PC,
                last_scan=("0129_gate_map", "completed"),
            ),
            ":white_check_mark: Queue completed · 7 items, 0 failed · 6:05:12 · XuguoOffice\n"
            "Last scan: 0129_gate_map (completed)",
        )
        self.assertEqual(
            messages.queue_text(
                reason="completed", done=7, total=7,
                failed=["0125_gate_map", "manual set nidaq_0_AO0 = 0.5"],
                elapsed_seconds=21912, pc_name=PC,
                last_scan=("0129_gate_map", "completed"),
            ),
            ":warning: Queue completed with failures · 7 items, 2 failed · 6:05:12 · XuguoOffice\n"
            "Failed: 0125_gate_map; manual set nidaq_0_AO0 = 0.5\n"
            "Last scan: 0129_gate_map (completed)",
        )
        self.assertEqual(
            messages.queue_text(
                reason="stop_requested", done=4, total=7, failed=[],
                elapsed_seconds=7800, pc_name=PC,
                last_scan=("0126_gate_map", "stopped"),
            ),
            ":black_square_for_stop: Queue stopped by request · 4 of 7 items done, 0 failed · 2:10:00 · XuguoOffice\n"
            "Last scan: 0126_gate_map (stopped)",
        )
        self.assertTrue(
            messages.queue_text(
                reason="stop_after_current", done=1, total=1, failed=[],
                elapsed_seconds=5, pc_name=PC,
            ).startswith(":black_square_for_stop: Queue stopped after current item · 1 of 1 item done")
        )

    def test_check_message(self):
        self.assertEqual(
            messages.check_text(PC),
            "ZMeter test message from XuguoOffice. Scan notifications will arrive here.",
        )


class NotifierTests(unittest.TestCase):
    def setUp(self):
        app()

    def test_nothing_is_sent_unless_active_with_token_and_email(self):
        notifier, session, _logs = make_notifier(active=False)
        notifier.channel_written(1.0)
        notifier.scan_finished(
            name="s", status="completed", elapsed_seconds=1,
            completed_points=1, total_points=1,
        )
        notifier.set_active(True)
        notifier.set_email("")
        self.assertFalse(notifier.active)
        notifier.channel_written(1.0)
        self.assertTrue(notifier._outbox.empty())
        self.assertIsNone(notifier._thread)
        self.assertEqual(session.calls, [])

    def test_channel_write_returns_at_once_while_slack_hangs(self):
        hang = threading.Event()
        notifier, session, _logs = make_notifier(FakeSession(hang=hang), interval=0.0)
        try:
            started = time.perf_counter()
            for _ in range(5):
                notifier.channel_written(1.0)
            notifier.scan_finished(
                name="s", status="completed", elapsed_seconds=1,
                completed_points=1, total_points=1, png=b"png",
            )
            elapsed = time.perf_counter() - started
            self.assertLess(elapsed, 0.05)
        finally:
            hang.set()
        self.assertTrue(notifier.wait_until_idle(5))

    def test_scan_message_uploads_png_with_text_in_one_post(self):
        notifier, session, logs = make_notifier()
        notifier.scan_finished(
            name="0123_gate map", status="completed", elapsed_seconds=6130,
            completed_points=400, total_points=400, png=b"\x89PNGdata",
        )
        self.assertTrue(notifier.wait_until_idle(5))
        self.assertEqual(
            session.methods(),
            [
                "users.lookupByEmail",
                "conversations.open",
                "files.getUploadURLExternal",
                "abc",
                "files.completeUploadExternal",
            ],
        )
        ticket = session.calls[2][2]["data"]
        self.assertEqual(ticket, {"filename": "0123_gate_map.png", "length": "8"})
        self.assertEqual(session.calls[3][2]["data"], b"\x89PNGdata")
        done = session.calls[4][2]["data"]
        self.assertEqual(done["channel_id"], "D1")
        self.assertEqual(json.loads(done["files"]), [{"id": "F1", "title": "0123_gate_map.png"}])
        self.assertTrue(done["initial_comment"].startswith(":white_check_mark: Scan completed: 0123_gate map"))
        for _http, _url, kwargs in session.calls:
            self.assertEqual(kwargs["timeout"], (5, 10))
        self.assertIn(("INFO", "Slack: scan 0123_gate map message sent."), logs)

    def test_scan_without_png_posts_text_and_dm_is_cached(self):
        notifier, session, _logs = make_notifier()
        for _ in range(2):
            notifier.scan_finished(
                name="s", status="stopped", elapsed_seconds=1,
                completed_points=1, total_points=2,
            )
        self.assertTrue(notifier.wait_until_idle(5))
        self.assertEqual(
            session.methods(),
            ["users.lookupByEmail", "conversations.open", "chat.postMessage", "chat.postMessage"],
        )
        self.assertEqual(session.calls[0][2]["params"], {"email": EMAIL})
        self.assertEqual(session.calls[0][2]["headers"], {"Authorization": f"Bearer {TOKEN}"})

    def test_slack_error_becomes_one_log_warning(self):
        session = FakeSession({"users.lookupByEmail": {"ok": False, "error": "users_not_found"}})
        notifier, _session, logs = make_notifier(session)
        notifier.channel_written(1.0)
        self.assertTrue(notifier.wait_until_idle(5))
        self.assertEqual(
            logs,
            [("WARNING", "Slack: notification message not sent (users.lookupByEmail: users_not_found).")],
        )
        # The worker survives and sends the next message once Slack answers.
        session.overrides.clear()
        notifier.ping_interval_s = 0.0
        notifier._next_ping_at = 0.0
        notifier.channel_written(1.0)
        self.assertTrue(notifier.wait_until_idle(5))
        self.assertIn("chat.postMessage", session.methods())

    def test_network_exception_is_caught(self):
        session = FakeSession()

        def broken(*_args, **_kwargs):
            raise ConnectionError("no route")

        session.post = broken
        session.get = broken
        notifier, _session, logs = make_notifier(session)
        notifier.channel_written(1.0)
        self.assertTrue(notifier.wait_until_idle(5))
        self.assertEqual(len(logs), 1)
        self.assertIn("ConnectionError: no route", logs[0][1])

    def test_burst_of_writes_gives_one_ping_then_one_counted_ping(self):
        notifier, session, _logs = make_notifier(interval=0.3)
        for _ in range(10):
            notifier.channel_written(1.0)
        deadline = time.monotonic() + 5
        while len(session.posted_texts()) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(
            session.posted_texts(),
            [
                messages.notification_text(count=1, when=T, pc_name=PC),
                messages.notification_text(count=9, when=T, pc_name=PC),
            ],
        )
        # Nothing more is pending.
        time.sleep(0.4)
        self.assertEqual(len(session.posted_texts()), 2)

    def test_outbox_full_drops_with_one_log_line(self):
        notifier, session, logs = make_notifier()
        with mock.patch.object(SlackNotifier, "_ensure_worker", lambda self: None):
            for _ in range(notifier_module.OUTBOX_SIZE):
                notifier.channel_written(1.0)
            notifier.channel_written(1.0)
        self.assertEqual(logs, [("WARNING", "Slack: outbox full, notification message dropped.")])
        self.assertEqual(session.calls, [])

    def test_queue_scans_are_quiet_and_queue_end_carries_last_png(self):
        notifier, session, _logs = make_notifier()
        notifier.queue_started()
        notifier.scan_finished(
            name="0128_a", status="completed", elapsed_seconds=1,
            completed_points=1, total_points=1, png=b"first", queue_run=True,
        )
        notifier.scan_finished(
            name="0129_b", status="stopped", elapsed_seconds=1,
            completed_points=1, total_points=1, png=b"second", queue_run=True,
        )
        self.assertTrue(notifier._outbox.empty())
        notifier.queue_finished(
            reason="stop_requested", done=2, total=3, failed=[], elapsed_seconds=60,
        )
        self.assertTrue(notifier.wait_until_idle(5))
        self.assertEqual(session.calls[3][2]["data"], b"second")
        self.assertEqual(
            session.posted_texts(),
            [
                ":black_square_for_stop: Queue stopped by request · 2 of 3 items done, 0 failed"
                " · 0:01:00 · XuguoOffice\nLast scan: 0129_b (stopped)"
            ],
        )
        self.assertIsNone(notifier._last_queue_scan)

    def test_queue_of_manual_sets_only_sends_text(self):
        notifier, session, _logs = make_notifier()
        notifier.queue_started()
        notifier.queue_finished(reason="completed", done=2, total=2, failed=[], elapsed_seconds=3)
        self.assertTrue(notifier.wait_until_idle(5))
        self.assertEqual(session.methods()[-1], "chat.postMessage")

    def test_test_button_reports_result_on_signal(self):
        notifier, session, _logs = make_notifier(active=False)
        results = []
        notifier.sig_test_result.connect(lambda ok, text: results.append((ok, text)))
        notifier.test()
        deadline = time.monotonic() + 5
        while not results and time.monotonic() < deadline:
            QtCore.QCoreApplication.processEvents()
            time.sleep(0.01)
        self.assertEqual(results, [(True, "Test message sent.")])
        self.assertEqual(session.methods()[0], "auth.test")
        self.assertEqual(session.posted_texts(), [messages.check_text(PC)])

    def test_test_button_without_email_fails_at_once(self):
        notifier, session, _logs = make_notifier(active=False)
        notifier.set_email("")
        results = []
        notifier.sig_test_result.connect(lambda ok, text: results.append((ok, text)))
        notifier.test()
        self.assertEqual(results, [(False, "Type your Slack email first.")])
        self.assertEqual(session.calls, [])


class TokenStoreTests(unittest.TestCase):
    def _fake_keyring(self):
        store = {}
        module = types.ModuleType("keyring")
        module.get_password = lambda service, user: store.get((service, user))
        module.set_password = lambda service, user, value: store.__setitem__((service, user), value)

        def delete(service, user):
            store.pop((service, user))

        module.delete_password = delete
        return module, store

    def test_token_is_kept_in_keyring_and_cleared(self):
        module, store = self._fake_keyring()
        with mock.patch.dict(sys.modules, {"keyring": module}):
            first = SlackTokenStore()
            self.assertTrue(first.set(" " + TOKEN + " "))
            self.assertEqual(store, {("ZMeter", "slack_bot_token"): TOKEN})
            self.assertEqual(SlackTokenStore().get(), TOKEN)
            first.set("")
            self.assertEqual(store, {})
            self.assertEqual(SlackTokenStore().get(), "")

    def test_without_keyring_token_lives_only_in_memory(self):
        with mock.patch.dict(sys.modules, {"keyring": None}):
            store = SlackTokenStore()
            self.assertFalse(store.keyring_available)
            self.assertFalse(store.set(TOKEN))
            self.assertEqual(store.get(), TOKEN)
            self.assertEqual(SlackTokenStore().get(), "")


class PanelTests(unittest.TestCase):
    def setUp(self):
        app()

    def _panel(self, token):
        from core.slack_notify.widgets import SlackPanel

        store = SimpleNamespace(get=lambda: token, set=lambda value: True, keyring_available=True)
        notifier, _session, _logs = make_notifier(active=False)
        notifier.set_email("")
        notifier.set_token("")
        return SlackPanel(notifier, store), notifier

    def test_active_needs_token_and_email_and_starts_unticked(self):
        panel, notifier = self._panel(TOKEN)
        self.assertEqual(panel.email_edit.text(), "")
        self.assertFalse(panel.active_checkbox.isChecked())
        self.assertFalse(panel.active_checkbox.isEnabled())
        self.assertEqual(panel.token_button.text(), "Bot token ✓")
        panel.email_edit.setText(EMAIL)
        self.assertTrue(panel.active_checkbox.isEnabled())
        panel.active_checkbox.setChecked(True)
        self.assertTrue(notifier.active)
        panel.email_edit.setText("")
        self.assertFalse(panel.active_checkbox.isChecked())
        self.assertFalse(notifier.active)

    def test_without_token_active_stays_disabled(self):
        panel, notifier = self._panel("")
        panel.email_edit.setText(EMAIL)
        self.assertFalse(panel.active_checkbox.isEnabled())
        self.assertEqual(panel.token_button.text(), "Bot token...")


class CaptureTests(unittest.TestCase):
    def setUp(self):
        app()

    def test_widgets_are_stacked_into_one_png(self):
        from PyQt6 import QtGui
        from core.slack_notify.capture import GAP, stacked_png

        first, second = QtWidgets.QLabel("a"), QtWidgets.QLabel("b")
        first.resize(100, 50)
        second.resize(200, 30)
        png = stacked_png([first, second])
        image = QtGui.QImage.fromData(png, "PNG")
        self.assertEqual((image.width(), image.height()), (200, 50 + GAP + 30))
        self.assertIsNone(stacked_png([]))


class ScanAndQueueHookTests(unittest.TestCase):
    """The hooks in Scan and ScanList, on stand-in objects."""

    def setUp(self):
        app()

    def _scan(self, notifier, *, finish="completed", queue_run=False, error=None):
        from core.scan import Scan

        fake = SimpleNamespace(
            main_window=SimpleNamespace(slack_notifier=notifier),
            _slack_result={
                "name": "0123_gate_map",
                "elapsed_seconds": 10,
                "completed_points": 4,
                "total_points": 4,
                "png": b"png",
            },
            _slack_queue_run=queue_run,
            _run_error_message=error,
            _get_finish_status=lambda: finish,
            _log_warning=lambda message: None,
        )
        fake._slack_notifier = lambda: Scan._slack_notifier(fake)
        Scan._send_slack_scan_result(fake)
        return fake

    def test_scan_end_statuses(self):
        cases = [
            ("completed", "completed"),
            ("stopped by user", "stopped"),
            ("error", "error"),
        ]
        for finish, status in cases:
            notifier = mock.Mock()
            fake = self._scan(notifier, finish=finish, error="boom" if status == "error" else None)
            kwargs = notifier.scan_finished.call_args.kwargs
            self.assertEqual(kwargs["status"], status)
            self.assertEqual(kwargs["queue_run"], False)
            self.assertIsNone(fake._slack_result)

    def test_restart_stop_and_queue_run(self):
        notifier = mock.Mock()
        self._scan(notifier, finish="stopped for restart")
        notifier.scan_finished.assert_not_called()
        fake = self._scan(notifier, queue_run=True)
        self.assertTrue(notifier.scan_finished.call_args.kwargs["queue_run"])
        self.assertFalse(fake._slack_queue_run)

    def test_scan_end_with_slack_off_does_nothing(self):
        notifier = mock.Mock()
        from core.scan import Scan

        fake = SimpleNamespace(
            main_window=SimpleNamespace(slack_notifier=notifier),
            _slack_result=None,
            _slack_queue_run=True,
        )
        fake._slack_notifier = lambda: notifier
        Scan._send_slack_scan_result(fake)
        notifier.scan_finished.assert_not_called()
        self.assertFalse(fake._slack_queue_run)

    def test_queue_counts_items_and_failures(self):
        from core.scanlist import ManualSetItem, ScanList

        notifier = mock.Mock()
        warnings = []
        fake = SimpleNamespace(
            main_window=SimpleNamespace(slack_notifier=notifier),
            queue_model=SimpleNamespace(pending_count=2),
            _log_warning=warnings.append,
        )
        fake._slack_notifier = lambda: ScanList._slack_notifier(fake)
        fake._slack_item_label = ScanList._slack_item_label
        ScanList._begin_slack_queue_run(fake)
        notifier.queue_started.assert_called_once()
        manual = ManualSetItem("nidaq_0_AO0", 0.5)
        ScanList._count_slack_queue_item(fake, manual, False)
        ScanList._count_slack_queue_item(fake, manual, True)
        ScanList._send_slack_queue_end(fake, "stop_requested")
        kwargs = notifier.queue_finished.call_args.kwargs
        self.assertEqual(kwargs["reason"], "stop_requested")
        self.assertEqual(kwargs["done"], 2)
        self.assertEqual(kwargs["total"], 4)
        self.assertEqual(kwargs["failed"], ["manual set nidaq_0_AO0 = 0.5"])
        self.assertEqual(warnings, [])
        # A second stop signal without a run sends nothing more.
        ScanList._send_slack_queue_end(fake, "completed")
        self.assertEqual(notifier.queue_finished.call_count, 1)

    def test_channel_name(self):
        self.assertEqual(SLACK_NOTIFICATION_CHANNEL, "default_slack_notification")


if __name__ == "__main__":
    unittest.main()
