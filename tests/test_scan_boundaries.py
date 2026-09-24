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
from core.scan_info import ScanInfo
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
        self.assertIn('"name": "boundary"', written.read_text(encoding="utf-8"))
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
