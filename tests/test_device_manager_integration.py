from __future__ import annotations

import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

import start_zmeter
from core.mainWindow import MainWindow
from core.device_management import (
    DeviceLifecycleError,
    DeviceStartupError,
    LifecycleFailure,
    LifecycleReport,
)
from core.scan import Scan
from core.scan_info import ScanInfo
from core.scanlist import ScanListShutdownTimeoutError
from core.shared_runtime import RuntimeServices


class DeviceManagerMainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.services = RuntimeServices()
        self.addCleanup(self.services.shutdown)
        self.manager = start_zmeter.create_device_manager(self.services)
        self.window = MainWindow(
            info=ScanInfo,
            save_path=self.temp_directory.name,
            backup_main_path=None,
            device_manager=self.manager,
        )
        self.addCleanup(self._cleanup_window)

    def _cleanup_window(self):
        if not self.window._session_shutdown_complete:
            self.window.shutdown_session()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()

    def test_manager_snapshot_preserves_exact_static_catalog_and_button_order(self):
        self.assertEqual(
            tuple(self.window.equips),
            ("mock_device_1", "mock_device_2"),
        )
        self.assertEqual(
            [button.text() for button in self.window.open_equipment_buttons],
            ["mock_device_1", "mock_device_2"],
        )
        for label in ("mock_device_1", "mock_device_2"):
            self.assertEqual(self.window.equips[label].windowTitle(), label)
            self.assertFalse(self.window.equips[label].logic.hardware.connected)
            self.assertEqual(
                self.window.setter_equipment_info[label],
                ["channel_A", "channel_B", "ramp_channel_A", "ramp_channel_B"],
            )
            self.assertEqual(
                self.window.getter_equipment_info[label],
                ["channel_A", "channel_B", "random_channel"],
            )
            self.assertIs(
                self.window.equips[label].command_router,
                self.window.command_router,
            )
            self.assertEqual(self.window.equips[label].device_label, label)

        self.assertEqual(
            self.window.get_device_channel_catalog(),
            {
                "artificial_channel": {
                    "readable": ["n", "E"],
                    "writable": ["n", "E"],
                },
                "default": {"readable": [], "writable": ["wait", "count"]},
                "mock_device_1": {
                    "readable": ["channel_A", "channel_B", "random_channel"],
                    "writable": [
                        "channel_A",
                        "channel_B",
                        "ramp_channel_A",
                        "ramp_channel_B",
                    ],
                },
                "mock_device_2": {
                    "readable": ["channel_A", "channel_B", "random_channel"],
                    "writable": [
                        "channel_A",
                        "channel_B",
                        "ramp_channel_A",
                        "ramp_channel_B",
                    ],
                },
            },
        )
        self.assertFalse(self.services.visa.diagnostics["manager_created"])
        self.assertFalse(self.services.kinesis.diagnostics["validated"])

    def test_close_confirmation_no_preserves_session_and_yes_tears_down(self):
        event = SimpleNamespace(
            accepted=False,
            ignored=False,
            accept=lambda: setattr(event, "accepted", True),
            ignore=lambda: setattr(event, "ignored", True),
        )

        with mock.patch.object(
            QtWidgets.QMessageBox,
            "question",
            return_value=QtWidgets.QMessageBox.StandardButton.No,
        ):
            self.window.closeEvent(event)

        self.assertTrue(event.ignored)
        self.assertFalse(event.accepted)
        self.assertFalse(self.window._session_shutdown_complete)
        self.assertIsNone(self.manager.teardown_report)

        event.accepted = False
        event.ignored = False
        with mock.patch.object(
            QtWidgets.QMessageBox,
            "question",
            return_value=QtWidgets.QMessageBox.StandardButton.Yes,
        ):
            self.window.closeEvent(event)

        self.assertTrue(event.accepted)
        self.assertFalse(event.ignored)
        self.assertTrue(self.window._session_shutdown_complete)
        self.assertTrue(self.manager.teardown_report.succeeded)

    def test_close_timeout_refuses_device_teardown_and_ignores_event(self):
        event = SimpleNamespace(
            accepted=False,
            ignored=False,
            accept=lambda: setattr(event, "accepted", True),
            ignore=lambda: setattr(event, "ignored", True),
        )
        timeout = ScanListShutdownTimeoutError(10, ("scan thread 'A'",))

        with (
            mock.patch.object(
                QtWidgets.QMessageBox,
                "question",
                return_value=QtWidgets.QMessageBox.StandardButton.Yes,
            ),
            mock.patch.object(QtWidgets.QMessageBox, "critical") as critical,
            mock.patch.object(
                self.window,
                "shutdown_session",
                side_effect=timeout,
            ),
        ):
            self.window.closeEvent(event)

        self.assertTrue(event.ignored)
        self.assertFalse(event.accepted)
        self.assertIsNone(self.manager.teardown_report)
        critical.assert_called_once()

    def test_failed_manager_teardown_is_not_marked_complete(self):
        failure = LifecycleFailure(
            "mock_device_1",
            "termination",
            "RuntimeError",
            "worker did not stop",
        )
        report = LifecycleReport("teardown_all", (failure,))

        with mock.patch.object(
            self.manager,
            "teardown_all",
            return_value=report,
        ):
            with self.assertRaises(DeviceLifecycleError):
                self.window.shutdown_session()

        self.assertFalse(self.window._session_shutdown_complete)
        self.assertIs(self.window._session_shutdown_report, report)

    def test_scan_lifecycle_methods_delegate_to_manager(self):
        manager = mock.Mock()
        manager.stop_for_scan.return_value = SimpleNamespace(failures=())
        manager.start_after_scan.return_value = SimpleNamespace(failures=())
        manager.force_stop_all.return_value = SimpleNamespace(failures=())
        target = SimpleNamespace(
            device_manager=manager,
            equips={},
            _force_stop_requested=False,
            _report_lifecycle_failures=lambda _report: None,
            _raise_lifecycle_failures=lambda _report: None,
        )

        MainWindow.stop_equipments_for_scanning(target)
        MainWindow.force_stop_equipments(target)
        self.assertTrue(target._force_stop_requested)
        MainWindow.start_equipments(target)

        manager.stop_for_scan.assert_called_once_with()
        manager.force_stop_all.assert_called_once_with()
        manager.start_after_scan.assert_called_once_with()
        self.assertFalse(target._force_stop_requested)

    def test_failed_stop_for_scan_is_surfaced_before_scan_logic_starts(self):
        failure = LifecycleFailure(
            "mock_device_1",
            "stop scan activity",
            "RuntimeError",
            "monitor still active",
        )
        report = LifecycleReport("stop_for_scan", (failure,))
        manager = mock.Mock()
        manager.stop_for_scan.return_value = report
        lifecycle_target = SimpleNamespace(device_manager=manager, equips={})
        lifecycle_target._report_lifecycle_failures = lambda _report: None
        lifecycle_target._raise_lifecycle_failures = (
            lambda returned_report: MainWindow._raise_lifecycle_failures(
                lifecycle_target,
                returned_report,
            )
        )

        with self.assertRaises(DeviceLifecycleError):
            MainWindow.stop_equipments_for_scanning(lifecycle_target)

        probe_logic = SimpleNamespace(
            started=False,
            reset_flags=lambda: None,
            initialize_scan_data=lambda _info: None,
            start=lambda: setattr(probe_logic, "started", True),
        )
        scan = self.window.scanlist.list_available.get_widgets()[0].scan
        original_logic = scan.logic
        original_main_window = scan.main_window
        original_focus = scan._focus_plot_tab_1_for_scan_start
        original_log_start = scan._start_new_scan_log_session
        try:
            scan.logic = probe_logic
            scan.main_window = SimpleNamespace(
                stop_equipments_for_scanning=lambda: (_ for _ in ()).throw(
                    DeviceLifecycleError(report)
                )
            )
            scan._focus_plot_tab_1_for_scan_start = lambda **_kwargs: None
            scan._start_new_scan_log_session = lambda: None

            with self.assertRaises(DeviceLifecycleError):
                Scan._start_scan_now(scan)

            self.assertFalse(probe_logic.started)
        finally:
            scan.logic = original_logic
            scan.main_window = original_main_window
            scan._focus_plot_tab_1_for_scan_start = original_focus
            scan._start_new_scan_log_session = original_log_start


class LauncherTeardownTests(unittest.TestCase):
    def _run_launcher_failure(self, *, window_construction_fails):
        events = []

        class FakeApplication:
            def __init__(self, _argv):
                events.append("app")

            def exec(self):
                events.append("exec")
                raise RuntimeError("event loop failed")

        class FakeRuntimeServices:
            def shutdown(self):
                events.append("runtime_shutdown")
                return {}

        manager = mock.Mock()
        manager.teardown_all.side_effect = lambda: events.append(
            "manager_teardown"
        ) or SimpleNamespace(failures=())
        manager.force_stop_all.side_effect = lambda: events.append(
            "manager_force_stop"
        ) or SimpleNamespace(failures=())

        class FakeWindow:
            def __init__(self, **_kwargs):
                if window_construction_fails:
                    raise RuntimeError("window construction failed")

            def show(self):
                events.append("show")

            def setWindowTitle(self, title):
                events.append(("title", title))

            def shutdown_session(self):
                events.append("window_shutdown")

        with (
            mock.patch.object(start_zmeter.QtWidgets, "QApplication", FakeApplication),
            mock.patch.object(start_zmeter, "RuntimeServices", FakeRuntimeServices),
            mock.patch.object(
                start_zmeter,
                "create_device_manager",
                return_value=manager,
            ),
            mock.patch.object(start_zmeter, "MainWindow", FakeWindow),
        ):
            with self.assertRaises(RuntimeError):
                start_zmeter.main()

        return events

    def test_event_loop_failure_quiesces_window_before_manager_and_runtime(self):
        events = self._run_launcher_failure(window_construction_fails=False)

        self.assertLess(events.index("window_shutdown"), events.index("manager_teardown"))
        self.assertLess(events.index("manager_teardown"), events.index("runtime_shutdown"))

    def test_window_construction_failure_still_releases_manager_then_runtime(self):
        events = self._run_launcher_failure(window_construction_fails=True)

        self.assertNotIn("window_shutdown", events)
        self.assertLess(events.index("manager_teardown"), events.index("runtime_shutdown"))

    def test_unquiesced_event_loop_exit_skips_manager_and_runtime_teardown(self):
        events = []

        class FakeApplication:
            def __init__(self, _argv):
                pass

            def exec(self):
                return 0

        class FakeRuntimeServices:
            def shutdown(self):
                events.append("runtime_shutdown")
                return {}

        manager = mock.Mock()
        manager.teardown_all.side_effect = lambda: events.append(
            "manager_teardown"
        ) or SimpleNamespace(failures=())
        manager.force_stop_all.side_effect = lambda: events.append(
            "manager_force_stop"
        ) or SimpleNamespace(failures=())

        class FakeWindow:
            def __init__(self, **_kwargs):
                pass

            def show(self):
                pass

            def setWindowTitle(self, _title):
                pass

            def shutdown_session(self, **_kwargs):
                events.append("window_shutdown_timeout")
                raise ScanListShutdownTimeoutError(1, ("scan thread",))

        with (
            mock.patch.object(start_zmeter.QtWidgets, "QApplication", FakeApplication),
            mock.patch.object(start_zmeter, "RuntimeServices", FakeRuntimeServices),
            mock.patch.object(
                start_zmeter,
                "create_device_manager",
                return_value=manager,
            ),
            mock.patch.object(start_zmeter, "MainWindow", FakeWindow),
        ):
            with self.assertRaises(ScanListShutdownTimeoutError):
                start_zmeter.main()

        self.assertEqual(
            events,
            [
                "window_shutdown_timeout",
                "manager_force_stop",
                "window_shutdown_timeout",
            ],
        )

    def test_manager_load_failure_still_releases_shared_runtimes(self):
        events = []

        class FakeApplication:
            def __init__(self, _argv):
                pass

        class FakeRuntimeServices:
            def shutdown(self):
                events.append("runtime_shutdown")
                return {}

        def fail_load(_services):
            events.append("manager_load_failed")
            raise RuntimeError("profile load failed")

        with (
            mock.patch.object(start_zmeter.QtWidgets, "QApplication", FakeApplication),
            mock.patch.object(start_zmeter, "RuntimeServices", FakeRuntimeServices),
            mock.patch.object(start_zmeter, "create_device_manager", fail_load),
            mock.patch.object(start_zmeter, "MainWindow") as main_window,
        ):
            with self.assertRaisesRegex(RuntimeError, "profile load failed"):
                start_zmeter.main()

        main_window.assert_not_called()
        self.assertEqual(events, ["manager_load_failed", "runtime_shutdown"])

    def test_window_construction_teardown_failure_keeps_runtime_alive(self):
        events = []

        class FakeApplication:
            def __init__(self, _argv):
                pass

        class FakeRuntimeServices:
            def shutdown(self):
                events.append("runtime_shutdown")
                return {}

        failure = LifecycleFailure(
            "device",
            "termination",
            "RuntimeError",
            "still active",
        )
        manager = mock.Mock()
        manager.teardown_all.side_effect = lambda: events.append(
            "manager_teardown"
        ) or LifecycleReport("teardown_all", (failure,))

        class FailingWindow:
            def __init__(self, **_kwargs):
                raise RuntimeError("window construction failed")

        with (
            mock.patch.object(start_zmeter.QtWidgets, "QApplication", FakeApplication),
            mock.patch.object(start_zmeter, "RuntimeServices", FakeRuntimeServices),
            mock.patch.object(
                start_zmeter,
                "create_device_manager",
                return_value=manager,
            ),
            mock.patch.object(start_zmeter, "MainWindow", FailingWindow),
        ):
            with self.assertRaisesRegex(RuntimeError, "window construction failed"):
                start_zmeter.main()

        self.assertEqual(events, ["manager_teardown"])

    def test_startup_rollback_failure_keeps_runtime_alive(self):
        events = []

        class FakeApplication:
            def __init__(self, _argv):
                pass

        class FakeRuntimeServices:
            def shutdown(self):
                events.append("runtime_shutdown")
                return {}

        primary = LifecycleFailure(
            "device",
            "connection",
            "RuntimeError",
            "connect failed",
        )
        cleanup = LifecycleFailure(
            "device",
            "termination",
            "RuntimeError",
            "cleanup failed",
        )
        startup_error = DeviceStartupError(
            primary,
            LifecycleReport("startup_rollback", (cleanup,)),
        )

        with (
            mock.patch.object(start_zmeter.QtWidgets, "QApplication", FakeApplication),
            mock.patch.object(start_zmeter, "RuntimeServices", FakeRuntimeServices),
            mock.patch.object(
                start_zmeter,
                "create_device_manager",
                side_effect=startup_error,
            ),
            mock.patch.object(start_zmeter, "MainWindow") as main_window,
        ):
            with self.assertRaises(DeviceStartupError):
                start_zmeter.main()

        main_window.assert_not_called()
        self.assertEqual(events, [])

    def test_unexpected_window_shutdown_error_is_not_swallowed(self):
        events = []

        class FakeApplication:
            def __init__(self, _argv):
                pass

            def exec(self):
                return 0

        class FakeRuntimeServices:
            def shutdown(self):
                events.append("runtime_shutdown")
                return {}

        manager = mock.Mock()
        manager.teardown_all.side_effect = lambda: events.append(
            "manager_teardown"
        ) or SimpleNamespace(failures=())
        manager.force_stop_all.side_effect = lambda: events.append(
            "manager_force_stop"
        ) or SimpleNamespace(failures=())

        class FakeWindow:
            def __init__(self, **_kwargs):
                pass

            def show(self):
                pass

            def setWindowTitle(self, _title):
                pass

            def shutdown_session(self):
                events.append("unexpected_shutdown_error")
                raise ValueError("auxiliary close failed")

        with (
            mock.patch.object(start_zmeter.QtWidgets, "QApplication", FakeApplication),
            mock.patch.object(start_zmeter, "RuntimeServices", FakeRuntimeServices),
            mock.patch.object(
                start_zmeter,
                "create_device_manager",
                return_value=manager,
            ),
            mock.patch.object(start_zmeter, "MainWindow", FakeWindow),
        ):
            with self.assertRaisesRegex(ValueError, "auxiliary close failed"):
                start_zmeter.main()

        self.assertEqual(events, ["unexpected_shutdown_error"])


if __name__ == "__main__":
    unittest.main()
