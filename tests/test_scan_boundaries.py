import copy
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from core.scan import (
    Scan,
    _OutputJobResult,
    _ScanOutputSnapshot,
    _persist_scan_outputs,
)
from core.scan_hooks import ScanHooks
from core.scan_info import ScanInfo
from core.slack_notify.scan_hook import register_slack_scan_hook
from devices.mfli.MFLI_logic import MFLILogic


class _Reservation:
    def __init__(self):
        self.release_count = 0

    def release(self):
        self.release_count += 1


class _ProbeLogic:
    def __init__(self):
        self.go_scan = False
        self.started = False
        self.completed_points = 0
        self.total_points = 0
        self.level_target_counts = []
        self.level_setters = []
        self.level_getters = []
        self.participating_device_ids = ()

    def reset_flags(self):
        return None

    def initialize_scan_data(self, _info):
        return None

    def start(self):
        self.started = True

    def isRunning(self):
        return self.started


class _BoundaryMainWindow(QtWidgets.QWidget):
    def __init__(self, output_root):
        super().__init__()
        self.save_info_path = QtWidgets.QPlainTextEdit(str(output_root), self)
        self.ppt_path = QtWidgets.QPlainTextEdit(
            str(output_root / "scan-boundary.pptx"), self
        )
        self.backup_path = QtWidgets.QPlainTextEdit("", self)
        self.scanlist = SimpleNamespace(serial=QtWidgets.QSpinBox(self))
        self.equips = {}
        self.reservations = []
        self.stop_callback = lambda _device_ids: None
        self.start_callback = lambda _device_ids: None

    def reserve_runtime_activity(self, _kind, _description):
        reservation = _Reservation()
        self.reservations.append(reservation)
        return reservation

    def stop_equipments_for_scanning(self, device_ids):
        return self.stop_callback(device_ids)

    def start_equipments(self, device_ids):
        return self.start_callback(device_ids)


class ScanBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory(prefix="zmeter_boundary_")
        self.addCleanup(self.temp_directory.cleanup)
        self.output_root = Path(self.temp_directory.name)
        self.main_window = _BoundaryMainWindow(self.output_root)
        info = copy.deepcopy(ScanInfo)
        info["plots"] = {"line_plots": {}, "image_plots": {}}
        self.scan = Scan(
            name="boundary",
            info=info,
            setter_equipment_info={},
            getter_equipment_info={},
            main_window=self.main_window,
        )
        self.logic = _ProbeLogic()
        self.scan.logic = self.logic
        self.scan.update_alllevel_setting_array = lambda: None
        self.scan.update_all_plots = lambda: None

    def tearDown(self):
        self._wait_until(
            lambda: self.scan._boundary_thread is None,
            timeout=2.0,
            fail=False,
        )
        if self.scan._runtime_activity_reservation is not None:
            self.scan._release_runtime_activity_reservation()
        self.scan.close()
        self.main_window.close()
        self.scan.deleteLater()
        self.main_window.deleteLater()
        self.app.processEvents()

    def _wait_until(self, predicate, *, timeout=2.0, fail=True):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents(QtCore.QEventLoop.ProcessEventsFlag.AllEvents, 20)
            if predicate():
                return True
            time.sleep(0.002)
        if fail:
            self.fail("timed out waiting for asynchronous scan boundary")
        return False

    def _participants(self, device_ids):
        def capture():
            self.scan._participating_device_ids = tuple(device_ids)
            self.logic.participating_device_ids = tuple(device_ids)
            return tuple(device_ids)

        self.scan._capture_participating_device_ids = capture

    def test_slow_prepare_keeps_gui_heartbeat_and_runs_off_owner(self):
        self._participants(("slow",))
        worker_threads = []
        prepare_started = threading.Event()

        def slow_prepare(device_ids):
            self.assertEqual(device_ids, ("slow",))
            worker_threads.append(QtCore.QThread.currentThread())
            prepare_started.set()
            time.sleep(0.08)

        self.main_window.stop_callback = slow_prepare
        heartbeat = []
        QtCore.QTimer.singleShot(0, lambda: heartbeat.append("alive"))

        self.assertTrue(self.scan._start_scan_now())
        self.assertEqual(self.scan.scan_state, "preparing")
        self.assertTrue(self._wait_until(prepare_started.is_set))
        self.app.processEvents()
        self.assertEqual(heartbeat, ["alive"])
        self.assertFalse(self.logic.started)

        self.assertTrue(self._wait_until(lambda: self.logic.started))
        self.assertEqual(self.scan.scan_state, "running")
        self.assertNotEqual(worker_threads, [self.scan.thread()])

    def test_prepare_failure_restores_same_devices_and_releases_reservation(self):
        self._participants(("device-a", "device-b"))
        restore_calls = []

        def fail_prepare(_device_ids):
            time.sleep(0.03)
            raise RuntimeError("prepare failed")

        self.main_window.stop_callback = fail_prepare
        self.main_window.start_callback = lambda ids: restore_calls.append(ids)

        self.assertTrue(self.scan._start_scan_now())
        self.assertTrue(
            self._wait_until(
                lambda: self.scan.outputs_finalized
                and self.scan.scan_state == "idle"
            )
        )

        self.assertFalse(self.logic.started)
        self.assertEqual(restore_calls, [("device-a", "device-b")])
        self.assertIsInstance(self.scan._last_start_error, RuntimeError)
        self.assertEqual(self.main_window.reservations[0].release_count, 1)

    def test_missing_scan_limit_warning_is_logged_before_device_preparation(self):
        self._participants(("nidaq_0",))
        self.scan.info["levels"]["level0"]["manual_set_before"] = [
            {"keithley_0_voltage": 0.0}
        ]
        checked = []

        def channels_without_scan_limit(channels):
            checked.append(list(channels))
            return [channel for channel in channels if channel == "keithley_0_voltage"]

        self.main_window.channels_without_scan_limit = channels_without_scan_limit
        log_at_prepare = []
        self.main_window.stop_callback = lambda _ids: log_at_prepare.append(
            list(self.scan.info["scan_log"])
        )

        self.assertTrue(self.scan._start_scan_now())
        self.assertTrue(self._wait_until(lambda: self.logic.started))

        self.assertEqual(len(checked), 1)
        self.assertIn("nidaq_0_AO0", checked[0])
        self.assertIn("keithley_0_voltage", checked[0])
        self.assertNotIn("nidaq_0_AI0", checked[0])
        line = (
            "[ScanRange] No scan limit for keithley_0_voltage; "
            "these writes are not range-checked."
        )
        self.assertEqual(
            sum(line in entry for entry in self.scan.info["scan_log"]), 1
        )
        self.assertTrue(any(line in entry for entry in log_at_prepare[0]))

    def test_slow_restore_and_output_keep_finalizing_and_gui_responsive(self):
        self._participants(("device-a",))
        self.scan._acquire_runtime_activity_reservation()
        self.scan._outputs_finalized = False
        self.scan._finalize_outputs_scheduled = True
        self.scan._set_scan_state("finalizing")
        snapshot = object()
        self.scan._build_output_snapshot = lambda: snapshot
        worker_started = threading.Event()
        worker_threads = []

        def slow_finalize(received):
            self.assertIs(received, snapshot)
            worker_threads.append(QtCore.QThread.currentThread())
            worker_started.set()
            time.sleep(0.08)
            return _OutputJobResult(
                messages=(), timings=(("JSON write", 0.08),)
            )

        self.scan._restore_and_persist = slow_finalize
        heartbeat = []
        QtCore.QTimer.singleShot(0, lambda: heartbeat.append("alive"))

        self.scan._finalize_scan_outputs()
        self.assertTrue(self._wait_until(worker_started.is_set))
        self.app.processEvents()
        self.assertEqual(heartbeat, ["alive"])
        self.assertEqual(self.scan.scan_state, "finalizing")
        self.assertFalse(self.scan.outputs_finalized)

        self.assertTrue(self._wait_until(lambda: self.scan.outputs_finalized))
        self.assertEqual(self.scan.scan_state, "idle")
        self.assertNotEqual(worker_threads, [self.scan.thread()])
        self.assertEqual(self.main_window.reservations[0].release_count, 1)
        self.assertNotIn("Scan boundary timing", self.scan.logStatus_textEdit.toPlainText())

    def _use_slack(self, notifier):
        self.main_window.scan_hooks = ScanHooks()
        register_slack_scan_hook(self.main_window.scan_hooks, notifier)

    def _finalize_with_hooks(self, *, json_path=None, stop_reason=None):
        self.scan._acquire_runtime_activity_reservation()
        self.scan._outputs_finalized = False
        self.scan._finalize_outputs_scheduled = True
        self.scan._set_scan_state("finalizing")
        self.scan._run_stop_reason = stop_reason
        self.scan._build_output_snapshot = lambda: None
        self.scan._restore_and_persist = lambda _snapshot: _OutputJobResult(
            messages=(), timings=(), json_path=json_path
        )
        self.scan._finalize_scan_outputs()
        self.assertTrue(self._wait_until(lambda: self.scan.outputs_finalized))

    def test_failing_hook_is_logged_and_later_hooks_still_run(self):
        hooks = ScanHooks()
        events = []

        def broken(_event):
            raise RuntimeError("hook exploded")

        hooks.register_scan_finished(broken, name="broken")
        hooks.register_scan_finished(events.append, name="recorder")
        self.main_window.scan_hooks = hooks

        self._finalize_with_hooks(json_path="C:/data/0000_boundary.json")

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].json_path, "C:/data/0000_boundary.json")
        self.assertEqual(self.scan.scan_state, "idle")
        self.assertEqual(self.main_window.reservations[0].release_count, 1)
        self.assertIn(
            "Scan-finished hook 'broken' failed: RuntimeError: hook exploded",
            self.scan.logStatus_textEdit.toPlainText(),
        )

    def test_no_plot_screenshot_when_no_hook_wants_one(self):
        events = []
        hooks = ScanHooks()
        hooks.register_scan_finished(events.append, wants_plot_png=lambda: False)
        hooks.register_scan_finished(events.append)
        self.main_window.scan_hooks = hooks
        self.scan._capture_plot_png = mock.Mock(return_value=b"png")

        self._finalize_with_hooks()

        self.scan._capture_plot_png.assert_not_called()
        self.assertEqual([event.plot_png for event in events], [None, None])

    def test_plot_screenshot_captured_when_a_hook_wants_it(self):
        events = []
        hooks = ScanHooks()
        hooks.register_scan_finished(events.append, wants_plot_png=lambda: True)
        self.main_window.scan_hooks = hooks
        self.scan._capture_plot_png = mock.Mock(return_value=b"png")

        self._finalize_with_hooks()

        self.scan._capture_plot_png.assert_called_once_with()
        self.assertEqual(events[0].plot_png, b"png")

    def test_stopped_for_restart_emits_nothing(self):
        events = []
        hooks = ScanHooks()
        hooks.register_scan_finished(events.append)
        self.main_window.scan_hooks = hooks
        self.scan._queue_run = True

        self._finalize_with_hooks(stop_reason="restart_requested")

        self.assertEqual(events, [])
        self.assertFalse(self.scan._queue_run)

    def test_finalization_hands_scan_to_slack_before_outputs_finalized(self):
        calls = []
        notifier = SimpleNamespace(
            active=True,
            scan_finished=lambda **kwargs: calls.append(
                (kwargs, self.scan.outputs_finalized)
            ),
        )
        self._use_slack(notifier)
        self.main_window.scanlist.serial.setValue(7)
        self.logic.completed_points, self.logic.total_points = 3, 4
        self.scan._acquire_runtime_activity_reservation()
        self.scan._outputs_finalized = False
        self.scan._finalize_outputs_scheduled = True
        self.scan._set_scan_state("finalizing")
        self.scan._run_stop_reason = "user_stop"
        self.scan._queue_run = True
        self.scan._build_output_snapshot = lambda: None
        self.scan._restore_and_persist = lambda _snapshot: _OutputJobResult(
            messages=(), timings=()
        )

        self.scan._finalize_scan_outputs()
        self.assertTrue(self._wait_until(lambda: self.scan.outputs_finalized))
        self.assertEqual(len(calls), 1)
        kwargs, finalized_at_call = calls[0]
        self.assertFalse(finalized_at_call)
        self.assertEqual(kwargs["name"], "0007_boundary")
        self.assertEqual(kwargs["status"], "stopped")
        self.assertEqual(
            (kwargs["completed_points"], kwargs["total_points"]), (3, 4)
        )
        self.assertTrue(kwargs["queue_run"])
        self.assertIsNone(kwargs["png"])  # no plots in this scan
        self.assertFalse(self.scan._queue_run)

    def test_finalization_with_slack_off_sends_nothing(self):
        calls = []
        self._use_slack(
            SimpleNamespace(
                active=False, scan_finished=lambda **kwargs: calls.append(kwargs)
            )
        )
        self.scan._acquire_runtime_activity_reservation()
        self.scan._outputs_finalized = False
        self.scan._finalize_outputs_scheduled = True
        self.scan._set_scan_state("finalizing")
        self.scan._build_output_snapshot = lambda: None
        self.scan._restore_and_persist = lambda _snapshot: _OutputJobResult(
            messages=(), timings=()
        )
        self.scan._finalize_scan_outputs()
        self.assertTrue(self._wait_until(lambda: self.scan.outputs_finalized))
        self.assertEqual(calls, [])

    def test_completion_snapshot_uses_name_and_comments_edited_during_scan(self):
        self.scan._set_scan_configuration_locked(True)

        self.assertTrue(self.scan.lineEdit.isEnabled())
        self.assertTrue(self.scan.comments_textEdit.isEnabled())
        self.scan.lineEdit.setText("renamed at completion")
        self.scan.comments_textEdit.setPlainText("latest operator comment")

        snapshot = self.scan._build_output_snapshot()

        self.assertEqual(snapshot.json_name, "0000_renamed at completion.json")
        self.assertEqual(snapshot.json_payload["name"], "renamed at completion")
        # The output snapshot (primary, backup and recovery copies) is stamped;
        # the in-memory scan info is not.
        self.assertEqual(list(snapshot.json_payload)[:2], ["format_version", "software"])
        self.assertEqual(snapshot.json_payload["format_version"], 2)
        self.assertNotIn("format_version", self.scan.info)
        self.assertNotIn("software", self.scan.info)
        self.assertEqual(
            snapshot.json_payload["comments"], "latest operator comment"
        )

    def test_output_job_resolves_collision_and_keeps_schema_payload(self):
        original = self.output_root / "0000_boundary.json"
        original.write_text("{}", encoding="utf-8")
        payload = {"name": "boundary", "data": {"value": [1.0, float("nan")]}}
        snapshot = _ScanOutputSnapshot(
            ppt_path=None,
            slides=(),
            json_path=str(original),
            json_payload=payload,
            json_name=original.name,
            backup_dir="",
            recovery_dir=str(self.output_root / "recovery"),
        )

        result = _persist_scan_outputs(snapshot)

        written = self.output_root / "0000_boundary_1.json"
        self.assertTrue(written.is_file())
        self.assertEqual(original.read_text(encoding="utf-8"), "{}")
        self.assertIn('"name":"boundary"', written.read_text(encoding="utf-8"))
        self.assertTrue(
            any(str(written) in message for _level, message in result.messages)
        )

    def test_ppt_capture_failure_still_builds_json_recovery_snapshot(self):
        with mock.patch.object(
            self.scan, "_capture_png", side_effect=RuntimeError("capture failed")
        ):
            snapshot = self.scan._build_output_snapshot()

        self.assertIsNone(snapshot.ppt_path)
        self.assertEqual(snapshot.slides, ())
        self.assertIsNotNone(snapshot.json_path)
        self.assertEqual(snapshot.json_payload["name"], "boundary")
        self.assertTrue(
            any("PPT capture failed" in line for line in self.scan._current_scan_log)
        )

    def test_mfli_lifecycle_waits_for_worker_barrier_and_resume(self):
        calls = []

        class _Future:
            def __init__(self, action):
                self.action = action

            def result(self, timeout):
                calls.append((self.action, timeout))
                return f"{self.action}-complete"

        probe = SimpleNamespace(
            request=lambda action: _Future(action)
        )

        self.assertEqual(
            MFLILogic.stop_scan(probe, timeout_ms=2_500),
            "prepare_scan-complete",
        )
        self.assertEqual(
            MFLILogic.start_scan(probe, timeout_ms=3_000),
            "resume-complete",
        )
        self.assertEqual(calls, [("prepare_scan", 2.5), ("resume", 3.0)])


if __name__ == "__main__":
    unittest.main()
