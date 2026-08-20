from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

import start_zmeter
from core.device_management import (
    ChannelFilters,
    DeviceConfig,
    DeviceManager,
    DeviceManagerLoadError,
    DeviceManagerThreadError,
    DeviceStartupError,
    DriverConfigSpec,
    DriverRegistration,
    DriverRegistry,
    LifecycleReport,
    ProfileConfig,
    ProfilePaths,
    StartupDeviceResult,
    StartupDeviceStatus,
    StartupReport,
    UnknownDriverError,
)
from core.mainWindow import MainWindow
from core.scan_info import ScanInfo


def _config(
    device_id: str,
    *,
    enabled: bool = True,
    connect_on_start: bool = False,
) -> DeviceConfig:
    return DeviceConfig(
        id=device_id,
        driver="fake_driver",
        enabled=enabled,
        connect_on_start=connect_on_start,
        connection={},
        scan_channels=ChannelFilters(setters=None, getters=None),
    )


def _profile(*devices: DeviceConfig) -> ProfileConfig:
    root = Path(__file__).resolve().parents[1]
    return ProfileConfig(
        schema_version=1,
        profile="best_effort",
        paths=ProfilePaths(save=root / "data", backup=None),
        devices=tuple(devices),
        source_path=root / "best-effort.json",
        repository_root=root,
    )


def _registration(**overrides) -> DriverRegistration:
    values = {
        "config_spec": DriverConfigSpec(
            driver_id="fake_driver",
            connection_fields={},
        ),
        "factory": lambda: SimpleNamespace(),
        "terminate": lambda _instance: None,
    }
    values.update(overrides)
    return DriverRegistration(**values)


class BestEffortManagerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_construction_failures_are_skipped_without_rolling_back_successes(self):
        calls = []
        attempt = 0

        def factory():
            nonlocal attempt
            attempt += 1
            if attempt in (1, 3):
                raise RuntimeError(f"factory failure {attempt}")
            instance = SimpleNamespace(label=f"instance-{attempt}")
            calls.append(("construct", instance.label))
            return instance

        registration = _registration(
            factory=factory,
            force_stop=lambda instance: calls.append(("force", instance.label)),
            stop_scan=lambda instance: calls.append(("stop", instance.label)),
            terminate=lambda instance: calls.append(("terminate", instance.label)),
            close_widget=lambda instance: calls.append(("close", instance.label)),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())

        snapshot = manager.load_profile(
            _profile(
                _config("failed-first"),
                _config("kept-second"),
                _config("failed-third"),
                _config("kept-fourth"),
                _config("disabled", enabled=False),
            )
        )

        self.assertEqual(tuple(snapshot.equipment), ("kept-second", "kept-fourth"))
        self.assertEqual(
            tuple(result.status for result in manager.startup_report.results),
            (
                StartupDeviceStatus.CONSTRUCTION_SKIPPED,
                StartupDeviceStatus.READY,
                StartupDeviceStatus.CONSTRUCTION_SKIPPED,
                StartupDeviceStatus.READY,
                StartupDeviceStatus.DISABLED,
            ),
        )
        self.assertEqual(
            calls,
            [("construct", "instance-2"), ("construct", "instance-4")],
        )

        report = manager.teardown_all()
        self.assertTrue(report.succeeded)
        self.assertEqual(
            calls[2:],
            [
                ("force", "instance-2"),
                ("force", "instance-4"),
                ("stop", "instance-2"),
                ("stop", "instance-4"),
                ("terminate", "instance-2"),
                ("close", "instance-2"),
                ("terminate", "instance-4"),
                ("close", "instance-4"),
            ],
        )

    def test_all_construction_failures_still_produce_loaded_empty_session(self):
        registration = _registration(
            factory=lambda: (_ for _ in ()).throw(RuntimeError("unavailable"))
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())

        snapshot = manager.load_profile(_profile(_config("first"), _config("second")))

        self.assertTrue(manager.loaded)
        self.assertEqual(tuple(snapshot.equipment), ())
        self.assertEqual(
            tuple(result.status for result in manager.startup_report.results),
            (
                StartupDeviceStatus.CONSTRUCTION_SKIPPED,
                StartupDeviceStatus.CONSTRUCTION_SKIPPED,
            ),
        )
        self.assertTrue(manager.teardown_all().succeeded)

    def test_duplicate_ids_and_unknown_drivers_remain_fatal(self):
        factory = mock.Mock(return_value=SimpleNamespace())
        manager = DeviceManager(
            DriverRegistry((_registration(factory=factory),)),
            SimpleNamespace(),
        )
        with self.assertRaises(DeviceStartupError):
            manager.load_profile(
                _profile(
                    _config("duplicate", enabled=False),
                    _config("duplicate"),
                )
            )
        factory.assert_not_called()

        unknown = DeviceConfig(
            id="unknown",
            driver="not_registered",
            enabled=True,
            connect_on_start=False,
            connection={},
            scan_channels=ChannelFilters(setters=None, getters=None),
        )
        second_manager = DeviceManager(
            DriverRegistry((_registration(),)),
            SimpleNamespace(),
        )
        with self.assertRaises(UnknownDriverError):
            second_manager.load_profile(_profile(unknown))
        self.assertFalse(second_manager.loaded)

    def test_startup_requests_continue_in_order_and_are_one_shot(self):
        instances = iter(
            SimpleNamespace(label=label, connected=(label == "connected"))
            for label in ("connected", "pending", "false", "raised", "manual")
        )
        calls = []

        def startup_connect(instance, _connection, _timeout_ms):
            calls.append(instance.label)
            if instance.label == "connected":
                return True
            if instance.label == "pending":
                return None
            if instance.label == "false":
                return False
            raise RuntimeError("injected startup failure")

        registration = _registration(
            factory=lambda: next(instances),
            startup_connect=startup_connect,
            is_connected=lambda instance: instance.connected,
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())
        manager.load_profile(
            _profile(
                _config("connected", connect_on_start=True),
                _config("pending", connect_on_start=True),
                _config("false", connect_on_start=True),
                _config("raised", connect_on_start=True),
                _config("manual", connect_on_start=False),
            )
        )

        report = manager.request_startup_connections()

        self.assertEqual(calls, ["connected", "pending", "false", "raised"])
        self.assertEqual(
            tuple(result.status for result in report.results),
            (
                StartupDeviceStatus.CONNECTED,
                StartupDeviceStatus.PENDING,
                StartupDeviceStatus.CONNECTION_FAILED,
                StartupDeviceStatus.CONNECTION_FAILED,
                StartupDeviceStatus.READY,
            ),
        )
        with self.assertRaisesRegex(DeviceManagerLoadError, "only once"):
            manager.request_startup_connections()

    def test_startup_request_rejects_non_owner_thread(self):
        manager = DeviceManager(
            DriverRegistry((_registration(startup_connect=lambda *_args: True),)),
            SimpleNamespace(),
        )
        manager.load_profile(_profile(_config("device", connect_on_start=True)))
        errors = []

        worker = threading.Thread(
            target=lambda: self._capture_error(
                errors,
                manager.request_startup_connections,
            )
        )
        worker.start()
        worker.join(2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DeviceManagerThreadError)
        self.assertEqual(
            manager.request_startup_connections().results[0].status,
            StartupDeviceStatus.CONNECTED,
        )

    def test_pending_startup_request_remains_owned_until_normal_teardown(self):
        calls = []
        instance = SimpleNamespace()
        registration = _registration(
            factory=lambda: instance,
            startup_connect=lambda *_args: calls.append("request") or None,
            force_stop=lambda _instance: calls.append("force"),
            stop_scan=lambda _instance: calls.append("stop"),
            terminate=lambda _instance: calls.append("terminate"),
            close_widget=lambda _instance: calls.append("close"),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())
        manager.load_profile(_profile(_config("pending", connect_on_start=True)))

        report = manager.request_startup_connections()
        self.assertEqual(report.results[0].status, StartupDeviceStatus.PENDING)
        self.assertEqual(calls, ["request"])

        teardown = manager.teardown_all()
        self.assertTrue(teardown.succeeded)
        self.assertEqual(
            calls,
            ["request", "force", "stop", "terminate", "close"],
        )

    @staticmethod
    def _capture_error(errors, callback):
        try:
            callback()
        except Exception as exc:
            errors.append(exc)


class StartupLogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_mainwindow_log_is_ordered_read_only_and_sanitized(self):
        report = StartupReport(
            "lab",
            (
                StartupDeviceResult(
                    "connected",
                    "sr830",
                    StartupDeviceStatus.CONNECTED,
                ),
                StartupDeviceResult(
                    "pending",
                    "bbd30x",
                    StartupDeviceStatus.PENDING,
                ),
                StartupDeviceResult(
                    "failed",
                    "keithley24xx",
                    StartupDeviceStatus.CONNECTION_FAILED,
                ),
                StartupDeviceResult(
                    "skipped",
                    "nidaq",
                    StartupDeviceStatus.CONSTRUCTION_SKIPPED,
                ),
            ),
        )
        with tempfile.TemporaryDirectory() as directory:
            window = MainWindow(
                info=ScanInfo,
                save_path=directory,
                backup_main_path=None,
                equips={},
                startup_report=report,
            )
            try:
                text = window.startup_log.toPlainText()
                self.assertTrue(window.startup_log.isReadOnly())
                self.assertLess(text.index("connected"), text.index("pending"))
                self.assertIn("manual retry is available", text)
                self.assertIn("device construction failed", text)
                self.assertIn("Total configured=4", text)
                self.assertFalse(hasattr(report.results[2], "message"))
                self.assertFalse(hasattr(report.results[2], "connection"))
            finally:
                window.shutdown_session()
                window.hide()
                window.deleteLater()


class LauncherStartupWindowTests(unittest.TestCase):
    def test_startup_window_closes_before_mainwindow_and_report_is_passed(self):
        events = []
        report = StartupReport(
            "launcher",
            (
                StartupDeviceResult(
                    "failed",
                    "fake_driver",
                    StartupDeviceStatus.CONNECTION_FAILED,
                ),
            ),
        )
        root = Path(__file__).resolve().parents[1]
        profile = ProfileConfig(
            schema_version=1,
            profile="launcher",
            paths=ProfilePaths(save=root / "data", backup=None),
            devices=(),
            source_path=root / "launcher.json",
            repository_root=root,
        )

        class FakeApplication:
            def __init__(self, _arguments):
                events.append("application")

            def arguments(self):
                return ["zmeter"]

            def processEvents(self):
                events.append("process_events")

            def exec(self):
                events.append("event_loop")
                return 0

        class FakeStartupWindow:
            def __init__(self):
                events.append("startup_construct")

            def show(self):
                events.append("startup_show")

            def set_stage(self, message):
                events.append(("stage", message))

            def close(self):
                events.append("startup_close")

            def deleteLater(self):
                events.append("startup_delete")

        class FakeRuntimeServices:
            def __init__(self):
                events.append("runtime_construct")

            def shutdown(self):
                events.append("runtime_shutdown")
                return {}

        class FakeManager:
            def request_startup_connections(self):
                events.append("startup_connections")
                return report

            def teardown_all(self):
                events.append("manager_teardown")
                return LifecycleReport("teardown")

        manager = FakeManager()

        class FakeWindow:
            def __init__(self, **kwargs):
                self.received_report = kwargs["startup_report"]
                events.append("mainwindow_construct")

            def setWindowTitle(self, _title):
                events.append("mainwindow_title")

            def show(self):
                events.append("mainwindow_show")

            def shutdown_session(self):
                events.append("mainwindow_shutdown")

        def create_session(_services, _path, *, before_device_load=None):
            events.append("create_session")
            before_device_load()
            return profile, manager

        with (
            mock.patch.object(start_zmeter.QtWidgets, "QApplication", FakeApplication),
            mock.patch.object(start_zmeter, "StartupWindow", FakeStartupWindow),
            mock.patch.object(start_zmeter, "RuntimeServices", FakeRuntimeServices),
            mock.patch.object(start_zmeter, "create_profile_session", create_session),
            mock.patch.object(start_zmeter, "MainWindow", FakeWindow),
        ):
            self.assertEqual(start_zmeter.main([]), 0)

        stages = [item[1] for item in events if isinstance(item, tuple)]
        self.assertEqual(
            stages,
            [
                "Loading profile…",
                "Loading devices…",
                "Connecting configured devices…",
                "Loading main window…",
            ],
        )
        self.assertLess(events.index("startup_show"), events.index("create_session"))
        self.assertLess(
            events.index("startup_connections"),
            events.index("mainwindow_construct"),
        )
        self.assertLess(
            events.index("mainwindow_construct"),
            events.index(("stage", "Loading main window…")),
        )
        self.assertLess(events.index("startup_close"), events.index("mainwindow_show"))
        self.assertIn("mainwindow_show", events)
        self.assertIn("mainwindow_shutdown", events)
        self.assertIn("manager_teardown", events)
        self.assertIn("runtime_shutdown", events)


if __name__ == "__main__":
    unittest.main()
