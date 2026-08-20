from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import redirect_stderr
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

import start_zmeter
from core.mainWindow import MainWindow
from core.device_management import (
    ChannelFilters,
    DeviceLifecycleError,
    DeviceManager,
    DeviceStartupError,
    LifecycleFailure,
    LifecycleReport,
    build_default_registry,
)
from core.scan import Scan, ScanChannelReference
from core.scan_info import ScanInfo
from core.scan_logic import ScanLogic
from core.scanlist import ScanListShutdownTimeoutError
from core.shared_runtime import RuntimeServices


class _ArgumentApplication:
    def __init__(self, argv):
        self._argv = list(argv)

    def arguments(self):
        return list(self._argv)


class DeviceManagerMainWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_directory.cleanup)
        self.services = RuntimeServices()
        self.addCleanup(self.services.shutdown)
        self.profile, self.manager = start_zmeter.create_profile_session(
            self.services,
            start_zmeter.REPOSITORY_ROOT / "config" / "profiles" / "mock.json",
        )
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

    def _wait_operation(self, operation, timeout_ms=5_000):
        timer = QtCore.QElapsedTimer()
        timer.start()
        while not operation.done and timer.elapsed() < timeout_ms:
            self.app.processEvents()
            QtCore.QThread.msleep(1)
        self.assertTrue(operation.done)
        for _ in range(3):
            self.app.processEvents()
        return operation.result

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

    def test_profile_filter_silently_skips_unknown_channels_end_to_end(self):
        filtered_config = replace(
            self.profile.devices[0],
            id="filtered_mock",
            scan_channels=ChannelFilters(
                setters=("missing_setter", "channel_A"),
                getters=("channel_B", "missing_getter"),
            ),
        )
        filtered_profile = replace(
            self.profile,
            profile="filtered",
            devices=(filtered_config,),
        )
        manager = DeviceManager(build_default_registry(), self.services)
        manager.load_profile(filtered_profile)
        window = MainWindow(
            info=ScanInfo,
            save_path=self.temp_directory.name,
            backup_main_path=None,
            device_manager=manager,
        )

        try:
            self.assertEqual(
                manager.snapshot().setter_filters["filtered_mock"],
                ("missing_setter", "channel_A"),
            )
            self.assertEqual(
                window.setter_equipment_info["filtered_mock"],
                ["channel_A"],
            )
            self.assertEqual(
                window.getter_equipment_info["filtered_mock"],
                ["channel_B"],
            )
            self.assertEqual(
                window.get_device_channel_catalog()["filtered_mock"],
                {"readable": ["channel_B"], "writable": ["channel_A"]},
            )
        finally:
            window.shutdown_session()
            window.hide()
            window.deleteLater()
            self.app.processEvents()

    def test_unknown_launcher_option_is_rejected_before_runtime_creation(self):
        stderr = StringIO()
        with (
            mock.patch.object(
                start_zmeter.QtWidgets,
                "QApplication",
                _ArgumentApplication,
            ),
            mock.patch.object(start_zmeter, "RuntimeServices") as runtime_type,
            redirect_stderr(stderr),
        ):
            with self.assertRaises(SystemExit) as caught:
                start_zmeter.main(
                    ["--profle", "config/profiles/session.local.json"]
                )

        self.assertEqual(caught.exception.code, 2)
        runtime_type.assert_not_called()
        self.assertIn("unrecognized arguments", stderr.getvalue())

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

        self.assertFalse(event.accepted)
        self.assertTrue(event.ignored)
        result = self._wait_operation(self.window._shutdown_operation)
        self.assertTrue(result.succeeded)
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
                self.window.scanlist,
                "shutdown",
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

    def test_scan_lifecycle_methods_delegate_selected_devices(self):
        manager = mock.Mock()
        manager.stop_for_scan.return_value = SimpleNamespace(failures=())
        manager.start_after_scan.return_value = SimpleNamespace(failures=())
        manager.force_stop_for_scan.return_value = SimpleNamespace(failures=())
        target = SimpleNamespace(
            device_manager=manager,
            equips={},
            _force_stop_requested=False,
            _raise_lifecycle_failures=lambda _report: None,
        )
        selected = ("mock_device_1",)

        MainWindow.stop_equipments_for_scanning(target, selected)
        MainWindow.force_stop_equipments(target, selected)
        MainWindow.start_equipments(target, selected)

        manager.stop_for_scan.assert_called_once_with(selected)
        manager.force_stop_for_scan.assert_called_once_with(selected)
        manager.force_stop_all.assert_not_called()
        manager.start_after_scan.assert_called_once_with(selected)

    def test_disconnected_unused_mock_does_not_block_selected_scan_lifecycle(self):
        first = self.window.equips["mock_device_1"]
        second = self.window.equips["mock_device_2"]
        first.connect(address="MOCK::ONE::INSTR")
        self.assertTrue(first.logic.hardware.connected)
        self.assertFalse(second.logic.hardware.connected)

        stop_report = self.window.stop_equipments_for_scanning(("mock_device_1",))
        start_report = self.window.start_equipments(("mock_device_1",))

        self.assertTrue(stop_report.succeeded)
        self.assertTrue(start_report.succeeded)
        self.assertFalse(second.logic.hardware.connected)

        with self.assertRaises(DeviceLifecycleError):
            self.window.stop_equipments_for_scanning(("mock_device_2",))

    def test_scan_participants_cover_executable_physical_channels_only(self):
        equipment = {
            "device_b": object(),
            "device_unused": object(),
            "device_a": object(),
            "device_c": object(),
        }

        def resolve(channel):
            for label in equipment:
                if channel.startswith(f"{label}_"):
                    return label
            return channel

        main_window = SimpleNamespace(
            equips=equipment,
            resolve_device_label_for_channel=resolve,
            artificial_channel_logic=SimpleNamespace(
                original_channel_x_name="device_b_output",
                original_channel_y_name="device_a_output",
            ),
        )

        def reference(kind, access, channel):
            return ScanChannelReference(kind, access, "level0", channel, "test")

        references = (
            reference("setter", "set", "device_a_output"),
            reference("getter", "get", "device_b_input"),
            reference("average_getter", "get", "device_c_input"),
            reference("manual_set_before", "set", "artificial_channel_n"),
            reference("getter", "get", "artificial_channel_E"),
            reference("setter", "set", "default_wait"),
            reference("plot_getter", "get", "device_unused_input"),
        )
        scan = SimpleNamespace(
            main_window=main_window,
            channel_references=lambda: references,
        )

        self.assertEqual(
            Scan._resolve_participating_device_ids(scan),
            ("device_b", "device_a", "device_c"),
        )

        getter_only = SimpleNamespace(
            main_window=main_window,
            channel_references=lambda: (
                reference("getter", "get", "artificial_channel_n"),
                reference("setter", "set", "default_count"),
            ),
        )
        self.assertEqual(Scan._resolve_participating_device_ids(getter_only), ())

    def test_monitor_stop_targets_only_scan_participants(self):
        calls = []
        scan = SimpleNamespace(
            main_window=SimpleNamespace(
                equips={
                    "used": SimpleNamespace(
                        stop_monitor=lambda: calls.append("used")
                    ),
                    "unused": SimpleNamespace(
                        stop_monitor=lambda: calls.append("unused")
                    ),
                }
            ),
            _log_warning=lambda _message: None,
        )

        Scan._stop_all_equipment_monitors(scan, ("used",))

        self.assertEqual(calls, ["used"])

    def test_scan_stop_and_cleanup_reuse_captured_participants(self):
        force_stop_calls = []
        scan = SimpleNamespace(
            main_window=SimpleNamespace(
                force_stop_equipments=lambda device_ids: force_stop_calls.append(
                    device_ids
                )
            ),
            _participating_device_ids=("device_a",),
            logic=SimpleNamespace(
                request_stop=lambda: None,
                stop_scan=False,
            ),
        )

        Scan._request_logic_stop(scan)

        self.assertEqual(force_stop_calls, [("device_a",)])
        self.assertTrue(scan.logic.stop_scan)

        restart_calls = []
        errors = []
        finishes = []
        resets = []
        artificial_logic = SimpleNamespace(
            reset_skip_next_scan_read=lambda: resets.append("artificial")
        )
        main_window = SimpleNamespace(
            artificial_channel_logic=artificial_logic,
            reset_skip_next_scan_read_from_global_limit=lambda: resets.append(
                "global"
            ),
            start_equipments=lambda device_ids: restart_calls.append(device_ids),
        )
        logic = SimpleNamespace(
            main_window=main_window,
            max_level=0,
            participating_device_ids=("device_a",),
            looping=lambda _level: (_ for _ in ()).throw(RuntimeError("scan failed")),
            reset_flags=lambda: resets.append("flags"),
            sig_scan_error=SimpleNamespace(emit=errors.append),
            sig_scan_finished=SimpleNamespace(emit=lambda: finishes.append(True)),
        )

        ScanLogic.scan(logic)

        self.assertEqual(restart_calls, [("device_a",)])
        self.assertEqual(len(errors), 1)
        self.assertEqual(finishes, [True])

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
                stop_equipments_for_scanning=lambda _device_ids: (_ for _ in ()).throw(
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
    @staticmethod
    def _profile(*, save="profile-save", backup=None):
        return SimpleNamespace(
            paths=SimpleNamespace(save=Path(save), backup=backup)
        )

    def test_launch_options_select_default_or_explicit_repository_relative_profile(self):
        options = start_zmeter._parse_launch_options([])
        self.assertEqual(options.profile, start_zmeter.DEFAULT_PROFILE_PATH)

        options = start_zmeter._parse_launch_options(
            [
                "--profile",
                "config/profiles/session.local.json",
            ]
        )
        self.assertEqual(
            options.profile,
            Path("config/profiles/session.local.json"),
        )

        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit):
                start_zmeter._parse_launch_options(
                    ["--profle", "config/profiles/session.local.json"]
                )

    def test_invalid_selected_profile_is_visible_and_never_falls_back(self):
        events = []

        class FakeApplication(_ArgumentApplication):
            def __init__(self, _argv):
                super().__init__(_argv)
                events.append("app")

        class FakeRuntimeServices:
            def shutdown(self):
                events.append("runtime_shutdown")
                return {}

        with tempfile.TemporaryDirectory() as directory:
            selected_path = Path(directory) / "missing.local.json"
            stderr = StringIO()
            with (
                mock.patch.object(
                    start_zmeter.QtWidgets,
                    "QApplication",
                    FakeApplication,
                ),
                mock.patch.object(
                    start_zmeter,
                    "RuntimeServices",
                    FakeRuntimeServices,
                ),
                mock.patch.object(start_zmeter, "DeviceManager") as manager_type,
                mock.patch.object(start_zmeter, "MainWindow") as main_window,
                mock.patch.object(
                    start_zmeter.QtWidgets.QMessageBox,
                    "critical",
                ) as critical,
                redirect_stderr(stderr),
            ):
                result = start_zmeter.main(
                    ["--profile", str(selected_path)]
                )

        self.assertEqual(result, 2)
        self.assertEqual(events, ["app", "runtime_shutdown"])
        manager_type.assert_not_called()
        main_window.assert_not_called()
        message = stderr.getvalue()
        self.assertIn("Invalid ZMeter profile", message)
        self.assertIn(str(selected_path), message)
        critical.assert_called_once_with(
            None,
            "Invalid ZMeter Profile",
            message.strip(),
        )

    def _run_launcher_failure(self, *, window_construction_fails):
        events = []

        class FakeApplication(_ArgumentApplication):
            def __init__(self, _argv):
                super().__init__(_argv)
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
        profile = self._profile()

        class FakeWindow:
            def __init__(self, **kwargs):
                if window_construction_fails:
                    raise RuntimeError("window construction failed")
                events.append(
                    (
                        "window_paths",
                        kwargs["save_path"],
                        kwargs["backup_main_path"],
                    )
                )

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
                "create_profile_session",
                return_value=(profile, manager),
            ),
            mock.patch.object(start_zmeter, "MainWindow", FakeWindow),
        ):
            with self.assertRaises(RuntimeError):
                start_zmeter.main([])

        return events

    def test_event_loop_failure_quiesces_window_before_manager_and_runtime(self):
        events = self._run_launcher_failure(window_construction_fails=False)

        self.assertIn(("window_paths", "profile-save", None), events)
        self.assertIn(("title", "Main Window"), events)
        self.assertLess(events.index("window_shutdown"), events.index("manager_teardown"))
        self.assertLess(events.index("manager_teardown"), events.index("runtime_shutdown"))

    def test_window_construction_failure_still_releases_manager_then_runtime(self):
        events = self._run_launcher_failure(window_construction_fails=True)

        self.assertNotIn("window_shutdown", events)
        self.assertLess(events.index("manager_teardown"), events.index("runtime_shutdown"))

    def test_unquiesced_event_loop_exit_skips_manager_and_runtime_teardown(self):
        events = []

        class FakeApplication(_ArgumentApplication):
            def __init__(self, _argv):
                super().__init__(_argv)

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
                "create_profile_session",
                return_value=(self._profile(), manager),
            ),
            mock.patch.object(start_zmeter, "MainWindow", FakeWindow),
        ):
            with self.assertRaises(ScanListShutdownTimeoutError):
                start_zmeter.main([])

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

        class FakeApplication(_ArgumentApplication):
            def __init__(self, _argv):
                super().__init__(_argv)

        class FakeRuntimeServices:
            def shutdown(self):
                events.append("runtime_shutdown")
                return {}

        def fail_load(_services, _profile_path, **_kwargs):
            events.append("manager_load_failed")
            raise RuntimeError("profile load failed")

        with (
            mock.patch.object(start_zmeter.QtWidgets, "QApplication", FakeApplication),
            mock.patch.object(start_zmeter, "RuntimeServices", FakeRuntimeServices),
            mock.patch.object(start_zmeter, "create_profile_session", fail_load),
            mock.patch.object(start_zmeter, "MainWindow") as main_window,
        ):
            with self.assertRaisesRegex(RuntimeError, "profile load failed"):
                start_zmeter.main([])

        main_window.assert_not_called()
        self.assertEqual(events, ["manager_load_failed", "runtime_shutdown"])

    def test_window_construction_teardown_failure_keeps_runtime_alive(self):
        events = []

        class FakeApplication(_ArgumentApplication):
            def __init__(self, _argv):
                super().__init__(_argv)

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
                "create_profile_session",
                return_value=(self._profile(), manager),
            ),
            mock.patch.object(start_zmeter, "MainWindow", FailingWindow),
        ):
            with self.assertRaisesRegex(RuntimeError, "window construction failed"):
                start_zmeter.main([])

        self.assertEqual(events, ["manager_teardown"])

    def test_startup_rollback_failure_keeps_runtime_alive(self):
        events = []

        class FakeApplication(_ArgumentApplication):
            def __init__(self, _argv):
                super().__init__(_argv)

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
                "create_profile_session",
                side_effect=startup_error,
            ),
            mock.patch.object(start_zmeter, "MainWindow") as main_window,
        ):
            with self.assertRaises(DeviceStartupError):
                start_zmeter.main([])

        main_window.assert_not_called()
        self.assertEqual(events, [])

    def test_unexpected_window_shutdown_error_is_not_swallowed(self):
        events = []

        class FakeApplication(_ArgumentApplication):
            def __init__(self, _argv):
                super().__init__(_argv)

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
                "create_profile_session",
                return_value=(self._profile(), manager),
            ),
            mock.patch.object(start_zmeter, "MainWindow", FakeWindow),
        ):
            with self.assertRaisesRegex(ValueError, "auxiliary close failed"):
                start_zmeter.main([])

        self.assertEqual(events, ["unexpected_shutdown_error"])


if __name__ == "__main__":
    unittest.main()
