import copy
import os
import threading
import time
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from core.scan import Scan
from core.scan_info import ScanInfo
from core.scanlist import (
    ScanItem,
    ScanList,
    ScanListShutdownInProgressError,
    ScanListShutdownStopError,
    ScanListShutdownThreadError,
    ScanListShutdownTimeoutError,
)


class _ProbeLogic:
    def __init__(self, owner):
        self.owner = owner
        self.go_scan = False
        self.flag_seen_at_start = None

    def reset_flags(self):
        return None

    def initialize_scan_data(self, _info):
        return None

    def start(self):
        self.flag_seen_at_start = self.owner._outputs_finalized


class _StopThread(QtCore.QThread):
    def __init__(self):
        super().__init__()
        self._stop_requested = False

    def request_test_stop(self):
        self._stop_requested = True

    def run(self):
        while not self._stop_requested:
            self.msleep(1)


class _FakeScan(QtCore.QObject):
    def __init__(self, item_thread, *, stop_error=None):
        super().__init__()
        self.logic = _StopThread()
        self.item_thread = item_thread
        self._start_new_scan_after_stop = True
        self._outputs_finalized = True
        self._finalize_outputs_scheduled = False
        self.stop_calls = 0
        self.close_calls = 0
        self.stop_thread_matches = []
        self.closed_after_quiescence = []
        self.stop_error = stop_error
        self.logic.finished.connect(self._finish_outputs)

    def start(self):
        self._outputs_finalized = False
        self.logic.start()

    def when_stop_clicked(self):
        self._start_new_scan_after_stop = False
        if not self.logic.isRunning():
            return
        self.stop_calls += 1
        self.stop_thread_matches.append(
            QtCore.QThread.currentThread() == self.item_thread
        )
        self.logic.request_test_stop()
        if self.stop_error is not None:
            error = self.stop_error
            self.stop_error = None
            raise error

    @QtCore.pyqtSlot()
    def _finish_outputs(self):
        self._outputs_finalized = True

    def close(self):
        self.close_calls += 1
        self.closed_after_quiescence.append(
            not self.logic.isRunning() and self._outputs_finalized
        )
        return True


class _QueueThread(_StopThread):
    sig_ui_update = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()
        self.stop_now_calls = 0
        self.stop_now_requested = False
        self.current_worker = None
        self.workers = []

    def request_stop_now(self):
        self.stop_now_calls += 1
        self.stop_now_requested = True
        self.request_test_stop()

    def run(self):
        super().run()
        self.sig_ui_update.emit()


class _AlwaysRunningQueue:
    def __init__(self):
        self.running = True
        self.stop_now_calls = 0
        self.stop_now_requested = False
        self.current_worker = None
        self.workers = []

    def request_stop_now(self):
        self.stop_now_calls += 1
        self.stop_now_requested = True

    def isRunning(self):
        return self.running


class _Container:
    def __init__(self, widgets):
        self.widgets = widgets

    def get_widgets(self):
        return list(self.widgets)


def _make_item(name="scan"):
    item = ScanItem.__new__(ScanItem)
    QtWidgets.QLabel.__init__(item)
    item.name = name
    item.setText(name)
    item.scan = _FakeScan(item.thread())
    return item


def _make_scan_list(logic, available=(), queue=(), past=()):
    scan_list = ScanList.__new__(ScanList)
    QtWidgets.QWidget.__init__(scan_list)
    scan_list.logic = logic
    scan_list.list_available = _Container(available)
    scan_list.list_queue = _Container(queue)
    scan_list.list_past = _Container(past)
    scan_list._shutdown_complete = False
    scan_list._shutdown_in_progress = False
    scan_list._shutdown_sealed = False
    scan_list._queue_run_started = False
    scan_list._queue_completion_delivered = True
    scan_list._log_ready = False
    finished = getattr(logic, "finished", None)
    if finished is not None:
        finished.connect(scan_list._on_queue_thread_finished)
    return scan_list


def _stop_test_thread(thread):
    thread.request_test_stop()
    thread.wait(1_000)


class ScanOutputFinalizationStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.scan = Scan(
            name="test",
            info=copy.deepcopy(ScanInfo),
            setter_equipment_info={},
            getter_equipment_info={},
            main_window=None,
        )

    def tearDown(self):
        self.scan.close()
        self.app.processEvents()

    def test_scan_starts_finalized_and_marks_outputs_pending_before_logic_start(self):
        self.assertTrue(self.scan._outputs_finalized)

        probe = _ProbeLogic(self.scan)
        self.scan.logic = probe
        self.scan.main_window = type(
            "_MainWindow",
            (),
            {"stop_equipments_for_scanning": lambda _self, _device_ids: None},
        )()
        self.scan._focus_plot_tab_1_for_scan_start = lambda **_kwargs: None
        self.scan._start_new_scan_log_session = lambda: None
        self.scan._stop_all_equipment_monitors = lambda _device_ids: None
        self.scan.update_alllevel_setting_array = lambda: None
        self.scan.update_all_plots = lambda: None
        self.scan._log_info = lambda _message: None

        self.scan._start_scan_now()

        self.assertFalse(probe.flag_seen_at_start)
        self.assertFalse(self.scan._outputs_finalized)

    def test_shutdown_gate_refuses_a_late_scan_button_start(self):
        probe = _ProbeLogic(self.scan)
        self.scan.logic = probe
        self.scan._shutdown_requested = True
        self.scan._start_new_scan_after_stop = True

        self.scan.when_scan_clicked()

        self.assertIsNone(probe.flag_seen_at_start)
        self.assertFalse(self.scan._start_new_scan_after_stop)

    def test_finalizer_marks_complete_before_a_requested_restart(self):
        observed = []
        self.scan._outputs_finalized = False
        self.scan._finalize_outputs_scheduled = True
        self.scan._start_new_scan_after_stop = True
        self.scan.when_save_plots_clicked = lambda: None
        self.scan.when_save_clicked = lambda: None
        serial = type(
            "_Serial",
            (),
            {"value": lambda _self: 1, "setValue": lambda _self, _value: None},
        )()
        self.scan.main_window = type(
            "_MainWindow",
            (),
            {"scanlist": type("_ScanList", (), {"serial": serial})()},
        )()

        def restart():
            observed.append(self.scan._outputs_finalized)
            self.scan._outputs_finalized = False

        self.scan._start_scan_now = restart
        self.scan._finalize_scan_outputs()

        self.assertEqual(observed, [True])
        self.assertFalse(self.scan._outputs_finalized)
        self.assertFalse(self.scan._finalize_outputs_scheduled)

    def test_finalizer_marks_complete_when_output_save_raises(self):
        self.scan._outputs_finalized = False
        self.scan._finalize_outputs_scheduled = True

        def fail_save():
            raise RuntimeError("save failed")

        self.scan.when_save_plots_clicked = fail_save

        with self.assertRaisesRegex(RuntimeError, "save failed"):
            self.scan._finalize_scan_outputs()

        self.assertTrue(self.scan._outputs_finalized)
        self.assertFalse(self.scan._finalize_outputs_scheduled)


class ScanListShutdownTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def tearDown(self):
        self.app.processEvents()

    def test_shutdown_stops_and_finalizes_before_one_deduplicated_close(self):
        item = _make_item("deduplicated")
        detached_item = _make_item("detached-worker")
        queue_logic = _QueueThread()
        queue_logic.current_worker = detached_item
        queue_logic.workers = [item, detached_item]
        ui_updates = []
        queue_logic.sig_ui_update.connect(lambda: ui_updates.append("delivered"))
        scan_list = _make_scan_list(
            queue_logic,
            available=(item,),
            queue=(item,),
            past=(item,),
        )
        item.scan.start()
        detached_item.scan.start()
        queue_logic.start()
        self.addCleanup(_stop_test_thread, item.scan.logic)
        self.addCleanup(_stop_test_thread, detached_item.scan.logic)
        self.addCleanup(_stop_test_thread, queue_logic)
        self.assertFalse(item.scan.logic.wait(0))
        self.assertFalse(detached_item.scan.logic.wait(0))
        self.assertFalse(queue_logic.wait(0))

        scan_list.shutdown(timeout_ms=1_000)

        self.assertEqual(queue_logic.stop_now_calls, 1)
        self.assertEqual(item.scan.stop_calls, 1)
        self.assertEqual(item.scan.stop_thread_matches, [True])
        self.assertFalse(item.scan._start_new_scan_after_stop)
        self.assertEqual(item.scan.close_calls, 1)
        self.assertEqual(item.scan.closed_after_quiescence, [True])
        self.assertEqual(detached_item.scan.stop_calls, 1)
        self.assertEqual(detached_item.scan.close_calls, 1)
        self.assertEqual(detached_item.scan.closed_after_quiescence, [True])
        self.assertEqual(ui_updates, ["delivered"])
        self.assertTrue(scan_list._shutdown_complete)

        scan_list.shutdown(timeout_ms=1_000)
        self.assertEqual(queue_logic.stop_now_calls, 1)
        self.assertEqual(item.scan.close_calls, 1)
        self.app.processEvents()
        self.assertEqual(ui_updates, ["delivered"])

    def test_shutdown_catches_a_scan_started_by_an_already_queued_gui_call(self):
        item = _make_item("late-start")
        queue_logic = _QueueThread()
        queue_logic.request_test_stop()
        scan_list = _make_scan_list(queue_logic, queue=(item,))
        self.addCleanup(_stop_test_thread, item.scan.logic)
        QtCore.QTimer.singleShot(0, item.scan.start)

        scan_list.shutdown(timeout_ms=1_000)

        self.assertEqual(item.scan.stop_calls, 1)
        self.assertEqual(item.scan.closed_after_quiescence, [True])

    def test_shutdown_resnapshots_an_item_inserted_and_started_during_event_pump(self):
        inserted_items = []
        queue_logic = _QueueThread()
        queue_logic.request_test_stop()
        scan_list = _make_scan_list(queue_logic, queue=inserted_items)

        def insert_and_start():
            item = _make_item("inserted-late")
            inserted_items.append(item)
            self.addCleanup(_stop_test_thread, item.scan.logic)
            item.scan.start()

        QtCore.QTimer.singleShot(0, insert_and_start)
        scan_list.shutdown(timeout_ms=1_000)

        self.assertEqual(len(inserted_items), 1)
        item = inserted_items[0]
        self.assertEqual(item.scan.stop_calls, 1)
        self.assertEqual(item.scan.close_calls, 1)
        self.assertEqual(item.scan.closed_after_quiescence, [True])

    def test_queued_queue_and_manual_starts_are_sealed_during_shutdown(self):
        queue_logic = _QueueThread()
        queue_logic.request_test_stop()
        scan_list = _make_scan_list(queue_logic)
        queued_callbacks = []

        def try_late_starts():
            scan_list.start_queue()
            scan_list.add_empty_manual_set_item()
            queued_callbacks.append("ran")

        QtCore.QTimer.singleShot(0, try_late_starts)
        scan_list.shutdown(timeout_ms=1_000)

        self.assertEqual(queued_callbacks, ["ran"])
        self.assertFalse(queue_logic.isRunning())

    def test_timeout_is_typed_does_not_close_and_allows_retry(self):
        item = _make_item("idle")
        queue_logic = _AlwaysRunningQueue()
        scan_list = _make_scan_list(queue_logic, available=(item,))

        with self.assertRaises(ScanListShutdownTimeoutError) as caught:
            scan_list.shutdown(timeout_ms=0)

        self.assertEqual(caught.exception.timeout_ms, 0)
        self.assertIn("queue thread", caught.exception.pending)
        self.assertEqual(item.scan.close_calls, 0)
        self.assertFalse(scan_list._shutdown_complete)
        self.assertFalse(scan_list._shutdown_in_progress)
        self.assertTrue(scan_list._shutdown_sealed)
        self.assertTrue(item.scan._shutdown_requested)

        stop_calls_before = queue_logic.stop_now_calls
        scan_list.start_queue()
        scan_list.add_empty_scan_item()
        scan_list.add_empty_manual_set_item()
        scan_list.add_manual_set_item_from_ui()
        self.assertEqual(queue_logic.stop_now_calls, stop_calls_before)
        self.assertEqual(item.scan.close_calls, 0)

        queue_logic.running = False
        scan_list._queue_completion_delivered = True
        scan_list.shutdown(timeout_ms=100)
        self.assertEqual(item.scan.close_calls, 1)

    def test_stop_request_error_waits_for_quiescence_then_fails_without_close(self):
        item = _make_item("force-stop-error")
        item.scan.stop_error = RuntimeError("force stop failed")
        queue_logic = _QueueThread()
        queue_logic.request_test_stop()
        scan_list = _make_scan_list(queue_logic, available=(item,))
        item.scan.start()
        self.addCleanup(_stop_test_thread, item.scan.logic)

        with self.assertRaises(ScanListShutdownStopError) as caught:
            scan_list.shutdown(timeout_ms=1_000)

        self.assertIn("force stop failed", str(caught.exception))
        self.assertFalse(item.scan.logic.isRunning())
        self.assertTrue(item.scan._outputs_finalized)
        self.assertEqual(item.scan.close_calls, 0)
        self.assertTrue(scan_list._shutdown_sealed)
        self.assertFalse(scan_list._shutdown_complete)

        scan_list.shutdown(timeout_ms=100)
        self.assertEqual(item.scan.close_calls, 1)

    def test_slow_gui_finalizer_times_out_before_close_then_retry_succeeds(self):
        item = _make_item("slow-finalizer")
        item.scan._outputs_finalized = False
        item.scan._finalize_outputs_scheduled = True
        queue_logic = _QueueThread()
        queue_logic.request_test_stop()
        scan_list = _make_scan_list(queue_logic, available=(item,))

        def slow_finalizer():
            time.sleep(0.03)
            item.scan._finalize_outputs_scheduled = False
            item.scan._outputs_finalized = True

        QtCore.QTimer.singleShot(0, slow_finalizer)
        with self.assertRaises(ScanListShutdownTimeoutError) as caught:
            scan_list.shutdown(timeout_ms=1)

        self.assertIn("GUI callback exceeded", str(caught.exception))
        self.assertEqual(item.scan.close_calls, 0)
        self.assertFalse(scan_list._shutdown_complete)

        scan_list.shutdown(timeout_ms=100)
        self.assertEqual(item.scan.close_calls, 1)

    def test_shutdown_rejects_wrong_thread_and_reentrant_calls(self):
        queue_logic = _QueueThread()
        queue_logic.request_test_stop()
        scan_list = _make_scan_list(queue_logic)
        wrong_thread_errors = []

        def call_from_python_thread():
            try:
                scan_list.shutdown(timeout_ms=100)
            except Exception as exc:
                wrong_thread_errors.append(exc)

        thread = threading.Thread(target=call_from_python_thread)
        thread.start()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(wrong_thread_errors), 1)
        self.assertIsInstance(wrong_thread_errors[0], ScanListShutdownThreadError)
        self.assertFalse(scan_list._shutdown_complete)

        reentrant_errors = []

        def call_reentrantly():
            try:
                scan_list.shutdown(timeout_ms=100)
            except Exception as exc:
                reentrant_errors.append(exc)

        QtCore.QTimer.singleShot(0, call_reentrantly)
        scan_list.shutdown(timeout_ms=100)

        self.assertEqual(len(reentrant_errors), 1)
        self.assertIsInstance(
            reentrant_errors[0], ScanListShutdownInProgressError
        )
        self.assertTrue(scan_list._shutdown_complete)


if __name__ == "__main__":
    unittest.main()
