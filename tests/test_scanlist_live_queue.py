import collections
import os
import threading
import time
import unittest
from unittest import mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from core.queue_model import LiveQueueModel, QueueItemState
from core.scanlist import (
    ManualSetItem,
    ScanItem,
    ScanList,
    ScanListLogic,
    ScanListShutdownTimeoutError,
    ScanListWidget,
)


class _ControlledManualItem(ManualSetItem):
    """Manual-set card with deterministic, device-free queue work."""

    def __init__(self, name, run_order, *, block=False, error=None):
        super().__init__(name, 0.0)
        self.run_order = run_order
        self.started = threading.Event()
        self.release = threading.Event() if block else None
        self.error = error

    def start_queue(self):
        self.run_order.append(self.channel_name)
        self.started.set()
        if self.release is not None and not self.release.wait(timeout=3.0):
            raise TimeoutError(f"test did not release queue item {self.channel_name}")
        if self.error is not None:
            raise self.error


class _GatedManualItem(ManualSetItem):
    def __init__(self, channel_name, value, main_window):
        super().__init__(channel_name, value, main_window=main_window)
        self.queue_start_reached = threading.Event()
        self.queue_start_release = threading.Event()

    def start_queue(self):
        self.queue_start_reached.set()
        if not self.queue_start_release.wait(timeout=3.0):
            raise TimeoutError("test did not release the queued manual start")
        return super().start_queue()


class _FakeQueuedScanLogic:
    def __init__(self):
        self.running = False

    def isRunning(self):
        return self.running


class _FakeQueuedScan:
    def __init__(self):
        self.logic = _FakeQueuedScanLogic()
        self._shutdown_requested = False
        self._start_new_scan_after_stop = False
        self.outputs_finalized = True
        self.start_calls = 0
        self.lock_states = []
        self.current_lock_observed = threading.Event()

    def set_queue_configuration_locked(self, locked):
        self.lock_states.append(bool(locked))
        if locked:
            self.current_lock_observed.set()

    def showMaximized(self):
        return None

    def raise_(self):
        return None

    def activateWindow(self):
        return None

    def when_scan_clicked(self):
        if self._shutdown_requested:
            return False
        self.start_calls += 1
        self.logic.running = True
        return True

    def when_stop_clicked(self):
        self.logic.running = False


class _GatedScanItem(ScanItem):
    def __init__(self, name, main_window):
        QtWidgets.QLabel.__init__(self)
        self.name = name
        self.main_window = main_window
        self.queue_entry_id = None
        self._queue_model = None
        self._queue_state = None
        self._queue_stop_requested = False
        self._scan_start_accepted = False
        self._scan_start_error = None
        self.scan = _FakeQueuedScan()
        self.queue_start_reached = threading.Event()
        self.queue_start_release = threading.Event()

    def start_queue(self):
        self.queue_start_reached.set()
        if not self.queue_start_release.wait(timeout=3.0):
            raise TimeoutError("test did not release the queued scan start")
        return super().start_queue()


class _ActivityReservation:
    def __init__(self):
        self.release_count = 0

    def release(self):
        self.release_count += 1


class _BlockingMainWindow:
    def __init__(self, *, error=None):
        self.scanlist = None
        self.error = error
        self.write_started = threading.Event()
        self.write_release = threading.Event()
        self.write_thread_ids = []
        self.write_calls = []
        self.reserve_calls = []
        self.reservation = _ActivityReservation()

    def reserve_runtime_activity(self, kind, description):
        self.reserve_calls.append((kind, description))
        return self.reservation

    def write_info(self, value, channel_name):
        self.write_calls.append((value, channel_name))
        self.write_thread_ids.append(threading.get_ident())
        self.write_started.set()
        if not self.write_release.wait(timeout=3.0):
            raise TimeoutError("test did not release the manual setter")
        if self.error is not None:
            raise self.error


class _QueueUiHarness(ScanList):
    """Only the real queue-facing portion of ScanList, without scan hardware UI."""

    def __init__(self, main_window=None):
        QtWidgets.QWidget.__init__(self)
        self.queue_model = LiveQueueModel()
        self.logic = ScanListLogic(self.queue_model)
        self.main_window = main_window
        self._shutdown_sealed = False
        self._runtime_mutation_sealed = False
        self._queue_run_started = False
        self._queue_completion_delivered = True
        self._queue_activity_reservation = None
        self._active_manual_operations = {}
        self._shutdown_complete = False
        self._shutdown_in_progress = False
        self._log_ready = True

        self.logStatus_textEdit = QtWidgets.QTextEdit(self)
        self.list_queue = ScanListWidget(queue_owner=self)
        self.list_past = ScanListWidget(allow_swap=False, allow_add=False)
        layout = QtWidgets.QHBoxLayout(self)
        layout.addWidget(self.list_queue)
        layout.addWidget(self.list_past)
        layout.addWidget(self.logStatus_textEdit)

        self.signal_events = []
        self.finished_payloads = []
        self.past_move_counts = collections.Counter()
        self.manual_begin_counts = collections.Counter()
        self.manual_end_counts = collections.Counter()

        self.logic.sig_scan_done.connect(self.add_to_past_scans)
        self.logic.sig_item_started.connect(self.on_queue_item_started)
        self.logic.sig_item_finished.connect(self.on_queue_item_finished)
        self.logic.sig_queue_stopped.connect(self.on_queue_stopped)
        self.logic.finished.connect(self._on_queue_thread_finished)
        if main_window is not None:
            main_window.scanlist = self

    def _begin_manual_operation(self, item):
        self.manual_begin_counts[id(item)] += 1
        super()._begin_manual_operation(item)

    def _end_manual_operation(self, item):
        self.manual_end_counts[id(item)] += 1
        super()._end_manual_operation(item)

    @staticmethod
    def item_name(item):
        return getattr(item, "channel_name", getattr(item, "name", type(item).__name__))

    def add_to_past_scans(self, worker):
        self.signal_events.append(("done", self.item_name(worker)))
        was_in_past = self.list_past.layout.indexOf(worker) >= 0
        super().add_to_past_scans(worker)
        is_in_past = self.list_past.layout.indexOf(worker) >= 0
        if not was_in_past and is_in_past:
            self.past_move_counts[self.item_name(worker)] += 1

    def on_queue_item_started(self, worker):
        self.signal_events.append(("started", self.item_name(worker)))
        super().on_queue_item_started(worker)

    def on_queue_item_finished(self, payload):
        payload_copy = dict(payload)
        self.finished_payloads.append(payload_copy)
        self.signal_events.append(
            ("finished", self.item_name(payload_copy["worker"]))
        )
        super().on_queue_item_finished(payload)

    def on_queue_stopped(self, reason):
        self.signal_events.append(("stopped", reason))
        super().on_queue_stopped(reason)


class ScanListLiveQueueIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.sleep_patch = mock.patch.object(
            QtCore.QThread,
            "sleep",
            return_value=None,
        )
        self.sleep_patch.start()
        self.addCleanup(self.sleep_patch.stop)
        self.run_order = []
        self.items = []
        self.queue = _QueueUiHarness()

    def tearDown(self):
        for item in self.items:
            release = getattr(item, "release", None)
            if release is not None:
                release.set()
            main_window = getattr(item, "main_window", None)
            write_release = getattr(main_window, "write_release", None)
            if write_release is not None:
                write_release.set()
            queue_start_release = getattr(item, "queue_start_release", None)
            if queue_start_release is not None:
                queue_start_release.set()
        if self.queue.logic.isRunning():
            self.queue.logic.request_stop_now()
            self.queue.logic.wait(3_000)
        self._process_events()
        self.queue.close()
        self.queue.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(
            None,
            QtCore.QEvent.Type.DeferredDelete,
        )
        self._process_events()

    def _item(self, name, *, block=False, error=None):
        item = _ControlledManualItem(
            name,
            self.run_order,
            block=block,
            error=error,
        )
        self.items.append(item)
        return item

    def _process_events(self):
        self.app.processEvents(
            QtCore.QEventLoop.ProcessEventsFlag.AllEvents,
            20,
        )

    def _wait_until(self, predicate, message, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._process_events()
            if predicate():
                return
            time.sleep(0.005)
        self._process_events()
        self.assertTrue(predicate(), message)

    def _wait_for_active_item(self, item):
        self.assertTrue(item.started.wait(1.0), f"{item.channel_name} did not start")
        self._wait_until(
            lambda: item._queue_state is QueueItemState.CURRENT,
            f"{item.channel_name} did not receive its CURRENT UI state",
        )

    def _wait_for_queue_completion(self):
        self._wait_until(
            lambda: (
                not self.queue.logic.isRunning()
                and self.queue._queue_completion_delivered
            ),
            "queue thread or queued Qt completion signals did not finish",
        )

    def _queue_names(self):
        return [item.channel_name for item in self.queue.list_queue.get_widgets()]

    def _past_names(self):
        return [
            self.queue.item_name(item)
            for item in self.queue.list_past.get_widgets()
        ]

    def _pending_names(self):
        return [
            entry.item.channel_name
            for entry in self.queue.queue_model.pending_entries()
        ]

    def test_add_during_active_run_is_claimed_by_that_run(self):
        first = self._item("A", block=True)
        second = self._item("B")
        self.assertTrue(self.queue.insert_queue_item(first))
        self.assertTrue(self.queue.insert_queue_item(second))

        self.queue.start_queue()
        self._wait_for_active_item(first)

        added = self._item("C")
        self.assertTrue(self.queue.insert_queue_item(added))
        self.assertEqual(self._pending_names(), ["B", "C"])
        self.assertEqual(self._queue_names(), ["A", "B", "C"])

        first.release.set()
        self._wait_for_queue_completion()

        self.assertEqual(self.run_order, ["A", "B", "C"])
        self.assertEqual(self._queue_names(), [])
        self.assertEqual(self._past_names(), ["A", "B", "C"])
        self.assertEqual(
            [
                self.queue.queue_model.entry_for_item(item).state
                for item in (first, second, added)
            ],
            [QueueItemState.COMPLETED] * 3,
        )

    def test_duplicate_insert_rejection_does_not_cancel_existing_pending_item(self):
        item = self._item("A")
        self.assertTrue(self.queue.insert_queue_item(item))

        with self.assertRaisesRegex(ValueError, "already retained"):
            self.queue.insert_queue_item(item)

        entry = self.queue.queue_model.entry_for_item(item)
        self.assertIsNotNone(entry)
        self.assertIs(entry.state, QueueItemState.PENDING)
        self.assertEqual(self._pending_names(), ["A"])
        self.assertEqual(self._queue_names(), ["A"])

    def test_pending_delete_and_reorder_apply_live_while_current_is_protected(self):
        current = self._item("A", block=True)
        removed = self._item("B")
        third = self._item("C")
        fourth = self._item("D")
        for item in (current, removed, third, fourth):
            self.assertTrue(self.queue.insert_queue_item(item))

        self.queue.start_queue()
        self._wait_for_active_item(current)

        self.assertEqual(self._queue_names(), ["A", "B", "C", "D"])
        self.assertEqual(self.queue.list_queue.layout.indexOf(current), 0)
        self.assertFalse(current.queue_editable())
        self.assertFalse(current.commit_value(99.0))
        self.assertEqual(current.parsed_value(), 0.0)

        self.assertFalse(
            self.queue.reorder_queue_item(
                current,
                origin_index=0,
                drop_index=4,
            )
        )
        self.queue.handle_delete_request(current)
        self._process_events()
        self.assertEqual(self.queue.list_queue.layout.indexOf(current), 0)
        self.assertIs(
            self.queue.queue_model.current_entry.item,
            current,
        )

        removed_entry = self.queue.queue_model.entry_for_item(removed)
        self.queue.handle_delete_request(removed)
        self.assertEqual(removed_entry.state, QueueItemState.CANCELLED)
        self.assertEqual(self._queue_names(), ["A", "C", "D"])

        self.assertTrue(
            self.queue.reorder_queue_item(
                fourth,
                origin_index=2,
                drop_index=1,
            )
        )
        self.assertEqual(self._pending_names(), ["D", "C"])
        self.assertEqual(self._queue_names(), ["A", "D", "C"])

        current.release.set()
        self._wait_for_queue_completion()

        self.assertEqual(self.run_order, ["A", "D", "C"])
        self.assertNotIn("B", self.run_order)
        self.assertEqual(self._past_names(), ["A", "D", "C"])
        self.assertEqual(self.queue.past_move_counts["A"], 1)
        self.assertEqual(
            sum(event == ("done", "A") for event in self.queue.signal_events),
            1,
        )

    def test_reorder_is_safe_when_an_item_boundary_claim_wins_the_race(self):
        first = self._item("A", block=True)
        second = self._item("B", block=True)
        third = self._item("C")
        fourth = self._item("D")
        for item in (first, second, third, fourth):
            self.assertTrue(self.queue.insert_queue_item(item))

        self.queue.start_queue()
        self._wait_for_active_item(first)
        reorder_pending = self.queue.queue_model.reorder_pending_at_queue_indices

        def claim_next_before_reorder(*args, **kwargs):
            first.release.set()
            deadline = time.monotonic() + 1.0
            while time.monotonic() < deadline:
                current = self.queue.queue_model.current_entry
                if current is not None and current.item is second:
                    break
                time.sleep(0.002)
            self.assertIs(self.queue.queue_model.current_entry.item, second)
            return reorder_pending(*args, **kwargs)

        with mock.patch.object(
            self.queue.queue_model,
            "reorder_pending_at_queue_indices",
            side_effect=claim_next_before_reorder,
        ):
            self.assertTrue(
                self.queue.reorder_queue_item(
                    fourth,
                    origin_index=3,
                    drop_index=1,
                )
            )

        self.assertEqual(self._pending_names(), ["D", "C"])
        self.assertEqual(self._queue_names(), ["B", "D", "C"])
        second.release.set()
        self._wait_for_queue_completion()
        self.assertEqual(self.run_order, ["A", "B", "D", "C"])

    def test_queue_adopts_an_already_running_pending_scan_without_restart(self):
        main_window = type("_QueueScanMainWindow", (), {})()
        self.queue.main_window = main_window
        main_window.scanlist = self.queue
        scan_item = _GatedScanItem("manual-scan", main_window)
        scan_item.queue_start_release.set()
        scan_item.scan.logic.running = True
        scan_item.scan.outputs_finalized = False
        scan_item.scan._start_new_scan_after_stop = True
        following = self._item("following")
        self.items.append(scan_item)
        self.assertTrue(self.queue.insert_queue_item(scan_item))
        self.assertTrue(self.queue.insert_queue_item(following))

        self.queue.start_queue()
        self._wait_until(
            scan_item.scan.current_lock_observed.is_set,
            "existing scan was not adopted as the current queue item",
        )

        self.assertEqual(scan_item.scan.start_calls, 0)
        self.assertFalse(scan_item.scan._start_new_scan_after_stop)
        self.assertFalse(following.started.is_set())

        scan_item.scan.logic.running = False
        time.sleep(0.02)
        self._process_events()
        self.assertFalse(following.started.is_set())

        scan_item.scan.outputs_finalized = True
        self._wait_for_queue_completion()

        self.assertEqual(self.run_order, ["following"])
        self.assertEqual(self._past_names(), ["manual-scan", "following"])
        self.assertEqual(
            self.queue.queue_model.entry_for_item(scan_item).state,
            QueueItemState.COMPLETED,
        )

    def test_stop_preserves_pending_items_and_the_next_run_executes_them(self):
        first = self._item("A", block=True)
        second = self._item("B")
        third = self._item("C")
        for item in (first, second, third):
            self.assertTrue(self.queue.insert_queue_item(item))

        self.queue.start_queue()
        self._wait_for_active_item(first)
        self.queue.stop_current_scan()
        self.assertTrue(self.queue.queue_model.stop_now_requested)

        first.release.set()
        self._wait_for_queue_completion()

        self.assertEqual(self.run_order, ["A"])
        self.assertEqual(self.queue.queue_model.run_stop_reason, "stop_requested")
        self.assertEqual(self._pending_names(), ["B", "C"])
        self.assertEqual(self._queue_names(), ["B", "C"])
        self.assertEqual(self._past_names(), ["A"])
        self.assertTrue(second.queue_editable())
        self.assertTrue(third.queue_editable())

        self.queue.start_queue()
        self._wait_for_queue_completion()

        self.assertEqual(self.run_order, ["A", "B", "C"])
        self.assertEqual(self.queue.queue_model.run_stop_reason, "completed")
        self.assertEqual(self._queue_names(), [])
        self.assertEqual(self._past_names(), ["A", "B", "C"])
        self.assertEqual(
            self.queue.past_move_counts,
            collections.Counter({"A": 1, "B": 1, "C": 1}),
        )

    def test_failure_continues_and_preserves_signal_and_payload_order(self):
        failed = self._item("A", error=RuntimeError("injected failure"))
        succeeded = self._item("B")
        self.assertTrue(self.queue.insert_queue_item(failed))
        self.assertTrue(self.queue.insert_queue_item(succeeded))

        with mock.patch("core.scanlist.traceback.print_exc"):
            self.queue.start_queue()
            self._wait_for_queue_completion()

        self.assertEqual(self.run_order, ["A", "B"])
        self.assertEqual(
            self.queue.signal_events,
            [
                ("started", "A"),
                ("done", "A"),
                ("finished", "A"),
                ("started", "B"),
                ("done", "B"),
                ("finished", "B"),
                ("stopped", "completed"),
            ],
        )

        self.assertEqual(len(self.queue.finished_payloads), 2)
        failed_payload, succeeded_payload = self.queue.finished_payloads
        self.assertEqual(
            list(failed_payload),
            ["worker", "elapsed_seconds", "failed", "error_message"],
        )
        self.assertIs(failed_payload["worker"], failed)
        self.assertGreaterEqual(failed_payload["elapsed_seconds"], 0.0)
        self.assertTrue(failed_payload["failed"])
        self.assertEqual(
            failed_payload["error_message"],
            "RuntimeError: injected failure",
        )
        self.assertIs(succeeded_payload["worker"], succeeded)
        self.assertGreaterEqual(succeeded_payload["elapsed_seconds"], 0.0)
        self.assertFalse(succeeded_payload["failed"])
        self.assertEqual(succeeded_payload["error_message"], "")

        self.assertEqual(
            self.queue.queue_model.entry_for_item(failed).state,
            QueueItemState.FAILED,
        )
        self.assertEqual(
            self.queue.queue_model.entry_for_item(succeeded).state,
            QueueItemState.COMPLETED,
        )
        self.assertEqual(self._past_names(), ["A", "B"])
        self.assertEqual(
            self.queue.past_move_counts,
            collections.Counter({"A": 1, "B": 1}),
        )

    def test_real_manual_worker_keeps_gui_responsive_and_stop_preserves_pending(self):
        main_window = _BlockingMainWindow()
        self.queue.main_window = main_window
        main_window.scanlist = self.queue
        current = ManualSetItem("default_wait", 1.25, main_window=main_window)
        pending = self._item("pending")
        self.items.append(current)
        self.assertTrue(self.queue.insert_queue_item(current))
        self.assertTrue(self.queue.insert_queue_item(pending))
        gui_thread_id = threading.get_ident()

        self.queue.start_queue()
        self._wait_until(
            main_window.write_started.is_set,
            "manual setter did not start",
        )
        self.assertTrue(current.logic.isRunning())

        heartbeat = []
        QtCore.QTimer.singleShot(0, lambda: heartbeat.append("gui-alive"))
        self._wait_until(lambda: bool(heartbeat), "GUI heartbeat was blocked")
        self.queue.stop_current_scan()

        self.assertTrue(self.queue.queue_model.stop_now_requested)
        self.assertEqual(self._pending_names(), ["pending"])
        self.assertNotEqual(main_window.write_thread_ids, [gui_thread_id])
        self.assertEqual(self.run_order, [])

        main_window.write_release.set()
        self._wait_for_queue_completion()

        self.assertEqual(main_window.write_calls, [(1.25, "default_wait")])
        self.assertEqual(self.run_order, [])
        self.assertEqual(self._pending_names(), ["pending"])
        self.assertEqual(self._past_names(), ["default_wait"])
        self.assertEqual(self.queue.manual_begin_counts[id(current)], 1)
        self.assertEqual(self.queue.manual_end_counts[id(current)], 1)
        self.assertEqual(self.queue._active_manual_operations, {})
        self.assertEqual(
            main_window.reserve_calls,
            [("queue", "2 queued item(s)")],
        )
        self.assertEqual(main_window.reservation.release_count, 1)

    def test_real_manual_exception_cleans_up_once_and_queue_continues(self):
        main_window = _BlockingMainWindow(error=ValueError("setter failed"))
        self.queue.main_window = main_window
        main_window.scanlist = self.queue
        failed = ManualSetItem("default_wait", 2.5, main_window=main_window)
        succeeded = self._item("next")
        self.items.append(failed)
        self.assertTrue(self.queue.insert_queue_item(failed))
        self.assertTrue(self.queue.insert_queue_item(succeeded))

        with mock.patch("core.scanlist.traceback.print_exc"):
            self.queue.start_queue()
            self._wait_until(main_window.write_started.is_set, "setter did not start")
            main_window.write_release.set()
            self._wait_for_queue_completion()

        self.assertEqual(self.run_order, ["next"])
        self.assertEqual(
            self.queue.queue_model.entry_for_item(failed).state,
            QueueItemState.FAILED,
        )
        failed_payload = next(
            payload
            for payload in self.queue.finished_payloads
            if payload["worker"] is failed
        )
        self.assertTrue(failed_payload["failed"])
        self.assertEqual(
            failed_payload["error_message"],
            "ValueError: setter failed",
        )
        self.assertEqual(self.queue.manual_begin_counts[id(failed)], 1)
        self.assertEqual(self.queue.manual_end_counts[id(failed)], 1)
        self.assertEqual(self.queue._active_manual_operations, {})
        self.assertEqual(len(main_window.reserve_calls), 1)
        self.assertEqual(main_window.reserve_calls[0][0], "queue")
        self.assertEqual(main_window.reservation.release_count, 1)

    def test_terminal_manual_card_can_be_cloned_for_replay_with_a_fresh_id(self):
        main_window = _BlockingMainWindow()
        main_window.write_release.set()
        self.queue.main_window = main_window
        main_window.scanlist = self.queue
        original = ManualSetItem("default_wait", 7.5, main_window=main_window)
        self.items.append(original)
        self.assertTrue(self.queue.insert_queue_item(original))
        original_entry = self.queue.queue_model.entry_for_item(original)

        self.queue.start_queue()
        self._wait_for_queue_completion()

        self.assertFalse(original.queue_editable())
        self.assertTrue(original.queue_cloneable())
        self.assertEqual(self._past_names(), ["default_wait"])
        clone = self.queue.list_queue.clone_supported_item(original)
        self.assertIsInstance(clone, ManualSetItem)
        self.items.append(clone)
        self.assertEqual(clone.parsed_value(), 7.5)
        self.assertTrue(self.queue.insert_queue_item(clone))
        clone_entry = self.queue.queue_model.entry_for_item(clone)
        self.assertNotEqual(clone_entry.entry_id, original_entry.entry_id)

        self.queue.start_queue()
        self._wait_for_queue_completion()

        self.assertEqual(
            main_window.write_calls,
            [(7.5, "default_wait"), (7.5, "default_wait")],
        )
        self.assertEqual(self._past_names(), ["default_wait", "default_wait"])

    def test_shutdown_seal_before_manual_worker_start_reports_failure(self):
        main_window = _BlockingMainWindow()
        self.queue.main_window = main_window
        main_window.scanlist = self.queue
        item = _GatedManualItem("default_wait", 4.0, main_window)
        self.items.append(item)
        self.assertTrue(self.queue.insert_queue_item(item))

        with mock.patch("core.scanlist.traceback.print_exc"):
            self.queue.start_queue()
            self.assertTrue(item.queue_start_reached.wait(1.0))
            self.queue._shutdown_sealed = True
            item.queue_start_release.set()
            self._wait_for_queue_completion()

        self.assertFalse(main_window.write_started.is_set())
        self.assertEqual(main_window.write_calls, [])
        self.assertEqual(
            self.queue.queue_model.entry_for_item(item).state,
            QueueItemState.FAILED,
        )
        payload = self.queue.finished_payloads[0]
        self.assertTrue(payload["failed"])
        self.assertIn("ScanListShutdownInProgressError", payload["error_message"])
        self.assertEqual(self._past_names(), ["default_wait"])
        self.assertEqual(main_window.reservation.release_count, 1)

    def test_shutdown_seal_before_scan_start_reports_failure(self):
        main_window = type("_QueueScanMainWindow", (), {})()
        self.queue.main_window = main_window
        main_window.scanlist = self.queue
        item = _GatedScanItem("late-scan", main_window)
        self.items.append(item)
        self.assertTrue(self.queue.insert_queue_item(item))

        with mock.patch("core.scanlist.traceback.print_exc"):
            self.queue.start_queue()
            self.assertTrue(item.queue_start_reached.wait(1.0))
            self.queue._shutdown_sealed = True
            item.scan._shutdown_requested = True
            item.queue_start_release.set()
            self._wait_for_queue_completion()

        self.assertEqual(item.scan.start_calls, 0)
        self.assertEqual(
            self.queue.queue_model.entry_for_item(item).state,
            QueueItemState.FAILED,
        )
        payload = self.queue.finished_payloads[0]
        self.assertTrue(payload["failed"])
        self.assertIn("ScanListShutdownInProgressError", payload["error_message"])
        self.assertEqual(self._past_names(), ["late-scan"])

    def test_shutdown_times_out_without_deleting_a_live_manual_worker(self):
        main_window = _BlockingMainWindow()
        self.queue.main_window = main_window
        main_window.scanlist = self.queue
        current = ManualSetItem("default_wait", 3.0, main_window=main_window)
        pending = self._item("pending")
        self.items.append(current)
        self.assertTrue(self.queue.insert_queue_item(current))
        self.assertTrue(self.queue.insert_queue_item(pending))

        self.queue.start_queue()
        self._wait_until(main_window.write_started.is_set, "setter did not start")
        with self.assertRaises(ScanListShutdownTimeoutError):
            self.queue.shutdown(timeout_ms=0)

        self.assertTrue(current.logic.isRunning())
        self.assertGreaterEqual(self.queue.list_queue.layout.indexOf(current), 0)
        self.assertEqual(self._pending_names(), ["pending"])
        self.assertFalse(self.queue._shutdown_complete)

        main_window.write_release.set()
        self.queue.shutdown(timeout_ms=3_000)

        self.assertFalse(current.logic.isRunning())
        self.assertTrue(self.queue._shutdown_complete)
        self.assertEqual(self._pending_names(), ["pending"])
        self.assertEqual(main_window.reservation.release_count, 1)

    def test_scan_stop_latched_before_start_is_applied_after_start(self):
        class _FakeLogic:
            def __init__(self):
                self.running = False

            def isRunning(self):
                return self.running

        class _FakeScan:
            def __init__(self):
                self.logic = _FakeLogic()
                self.start_calls = 0
                self.stop_calls = 0
                self.lock_states = []

            def set_queue_configuration_locked(self, locked):
                self.lock_states.append(bool(locked))

            def showMaximized(self):
                return None

            def raise_(self):
                return None

            def activateWindow(self):
                return None

            def when_scan_clicked(self):
                self.start_calls += 1
                self.logic.running = True

            def when_stop_clicked(self):
                self.stop_calls += 1
                self.logic.running = False

        item = ScanItem.__new__(ScanItem)
        QtWidgets.QLabel.__init__(item)
        item.scan = _FakeScan()
        item.queue_entry_id = None
        item._queue_model = None
        item._queue_state = None
        item._queue_stop_requested = False
        model = LiveQueueModel()
        entry = model.add_pending(item)
        item.bind_queue_entry(model, entry.entry_id)
        self.assertTrue(model.begin_run())
        self.assertIs(model.claim_next().item, item)

        item._request_stop_from_queue()
        item._start_scan_from_queue()

        self.assertEqual(item.scan.start_calls, 1)
        self.assertEqual(item.scan.stop_calls, 1)
        self.assertFalse(item.scan.logic.isRunning())
        model.finish_current(entry.entry_id)
        self.assertIsNone(model.claim_next())
        item.deleteLater()


if __name__ == "__main__":
    unittest.main()
