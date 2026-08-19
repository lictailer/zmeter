from __future__ import annotations

import os
import subprocess
import sys
import threading
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.device_management.config import load_profile
from core.device_management.manager import (
    DeviceManager,
    DeviceManagerLoadError,
    DeviceManagerThreadError,
    DeviceManagerTerminatedError,
    DeviceStartupError,
    DeviceState,
)
from core.device_management.models import (
    ChannelFilters,
    DeviceConfig,
    DriverConfigSpec,
    ProfileConfig,
    ProfilePaths,
)
from core.device_management.registry import (
    DriverRegistration,
    DriverRegistry,
    build_default_registry,
)


def make_config(
    device_id: str,
    *,
    enabled: bool = True,
    connect_on_start: bool = False,
    driver: str = "fake_driver",
    setters: tuple[str, ...] | None = None,
    getters: tuple[str, ...] | None = None,
) -> DeviceConfig:
    return DeviceConfig(
        id=device_id,
        driver=driver,
        enabled=enabled,
        connect_on_start=connect_on_start,
        connection={},
        scan_channels=ChannelFilters(setters=setters, getters=getters),
    )


def make_profile(*devices: DeviceConfig) -> ProfileConfig:
    root = Path(__file__).resolve().parents[1]
    return ProfileConfig(
        schema_version=1,
        profile="unit",
        paths=ProfilePaths(save=root / "data", backup=None),
        devices=tuple(devices),
        source_path=root / "unit-profile.json",
        repository_root=root,
    )


def make_registration(**overrides) -> DriverRegistration:
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


class DeviceManagerPureTests(unittest.TestCase):
    def test_manager_module_and_default_registry_lookup_remain_lazy(self):
        repository_root = Path(__file__).resolve().parents[1]
        script = """
import sys
from core.device_management import DeviceManager, build_default_registry

registry = build_default_registry()
assert DeviceManager is not None
assert registry.driver_ids == ("mock_device",)
watched = (
    "devices", "pyvisa", "clr", "nidaqmx", "PyDAQmx",
    "opticool", "sr830", "sr860", "tlpm",
)
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in watched)
)
if loaded:
    raise SystemExit("unexpected device/vendor import: " + ", ".join(loaded))
print("manager import and registry lookup remained lazy")
"""

        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("remained lazy", result.stdout)

    def test_load_preserves_enabled_profile_order_and_snapshot_is_immutable(self):
        instances = iter(
            (
                SimpleNamespace(label="first"),
                SimpleNamespace(label="second"),
            )
        )
        registry = DriverRegistry(
            (make_registration(factory=lambda: next(instances)),)
        )
        manager = DeviceManager(registry, SimpleNamespace())
        profile = make_profile(
            make_config("first", setters=("A", "missing"), getters=()),
            make_config("disabled", enabled=False, driver="not_registered"),
            make_config("second"),
        )

        snapshot = manager.load_profile(profile)

        self.assertEqual(tuple(snapshot.equipment), ("first", "second"))
        self.assertEqual(
            tuple(view.device_id for view in snapshot.records),
            ("first", "second"),
        )
        self.assertEqual(snapshot.setter_filters["first"], ("A", "missing"))
        self.assertEqual(snapshot.getter_filters["first"], ())
        self.assertIsNone(snapshot.setter_filters["second"])
        self.assertEqual(
            tuple(view.state for view in snapshot.records),
            (DeviceState.DISCONNECTED, DeviceState.DISCONNECTED),
        )
        with self.assertRaises(TypeError):
            snapshot.equipment["third"] = object()
        with self.assertRaises(FrozenInstanceError):
            snapshot.records[0].state = DeviceState.ERROR

    def test_connect_on_start_is_opt_in_and_state_is_reported(self):
        instances = iter(
            (SimpleNamespace(label="first"), SimpleNamespace(label="second"))
        )
        calls = []
        registration = make_registration(
            factory=lambda: next(instances),
            connect=lambda instance, connection, timeout_ms: (
                calls.append(
                    ("connect", instance.label, dict(connection), timeout_ms)
                )
                or True
            ),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())

        snapshot = manager.load_profile(
            make_profile(
                make_config("first", connect_on_start=False),
                make_config("second", connect_on_start=True),
            )
        )

        self.assertEqual(calls, [("connect", "second", {}, 10_000)])
        self.assertEqual(snapshot.records[0].state, DeviceState.DISCONNECTED)
        self.assertEqual(snapshot.records[1].state, DeviceState.CONNECTED)

    def test_start_after_scan_is_noop_while_shutdown_is_reserved(self):
        calls = []
        registration = make_registration(
            start_scan=lambda _instance: calls.append("start")
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())
        manager.load_profile(make_profile(make_config("device")))

        reservation = manager.begin_shutdown()
        self.assertTrue(manager.shutdown_started)
        self.assertTrue(manager.start_after_scan().succeeded)
        self.assertEqual(calls, [])

        reservation.release()
        self.assertFalse(manager.shutdown_started)
        self.assertTrue(manager.start_after_scan().succeeded)
        self.assertEqual(calls, ["start"])

    def test_connect_probe_mismatch_rolls_back_as_startup_failure(self):
        events = []
        registration = make_registration(
            factory=lambda: SimpleNamespace(label="probe"),
            connect=lambda _instance, _connection, _timeout_ms: (
                events.append("connect") or True
            ),
            is_connected=lambda _instance: False,
            force_stop=lambda _instance: events.append("force"),
            stop_scan=lambda _instance: events.append("stop"),
            terminate=lambda _instance: events.append("terminate"),
            close_widget=lambda _instance: events.append("close"),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())

        with self.assertRaisesRegex(
            DeviceStartupError,
            "without reporting a connected device",
        ):
            manager.load_profile(
                make_profile(make_config("probe", connect_on_start=True))
            )

        self.assertEqual(events, ["connect", "force", "stop", "terminate", "close"])
        self.assertEqual(tuple(manager.snapshot().equipment), ())

    def test_connection_callback_requires_literal_true(self):
        for result in (False, None, 1, "connected"):
            with self.subTest(result=result):
                registration = make_registration(
                    connect=lambda _instance, _connection, _timeout_ms, value=result: value,
                )
                manager = DeviceManager(
                    DriverRegistry((registration,)), SimpleNamespace()
                )
                with self.assertRaisesRegex(
                    DeviceStartupError,
                    "must return literal True",
                ):
                    manager.load_profile(
                        make_profile(make_config("strict", connect_on_start=True))
                    )
                self.assertEqual(tuple(manager.snapshot().equipment), ())

    def test_teardown_before_load_seals_manager_without_constructing(self):
        factory_calls = []
        registration = make_registration(
            factory=lambda: factory_calls.append(True) or SimpleNamespace(),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())

        self.assertTrue(manager.teardown_all().succeeded)
        with self.assertRaises(DeviceManagerLoadError):
            manager.load_profile(make_profile(make_config("late")))

        self.assertEqual(factory_calls, [])

    def test_bulk_lifecycle_is_rejected_after_teardown(self):
        manager = DeviceManager(
            DriverRegistry((make_registration(),)),
            SimpleNamespace(),
        )
        manager.load_profile(make_profile(make_config("only")))
        manager.teardown_all()

        for action in (
            manager.stop_for_scan,
            manager.start_after_scan,
            manager.force_stop_all,
        ):
            with self.subTest(action=action.__name__):
                with self.assertRaises(DeviceManagerTerminatedError):
                    action()

    def test_bulk_lifecycle_requires_a_successful_profile_load(self):
        fresh = DeviceManager(
            DriverRegistry((make_registration(),)),
            SimpleNamespace(),
        )
        for action in (
            fresh.stop_for_scan,
            fresh.start_after_scan,
            fresh.force_stop_all,
        ):
            with self.subTest(action=action.__name__):
                with self.assertRaises(DeviceManagerLoadError):
                    action()

        empty = DeviceManager(
            DriverRegistry((make_registration(),)),
            SimpleNamespace(),
        )
        empty.load_profile(make_profile())
        self.assertTrue(empty.stop_for_scan().succeeded)
        self.assertTrue(empty.start_after_scan().succeeded)
        self.assertTrue(empty.force_stop_all().succeeded)

    def test_teardown_skips_stop_only_for_a_known_disconnected_device(self):
        events = []
        registration = make_registration(
            factory=lambda: SimpleNamespace(),
            is_connected=lambda _instance: False,
            force_stop=lambda _instance: events.append("force"),
            stop_scan=lambda _instance: events.append("stop"),
            terminate=lambda _instance: events.append("terminate"),
            close_widget=lambda _instance: events.append("close"),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())
        manager.load_profile(make_profile(make_config("offline")))

        report = manager.teardown_all()

        self.assertTrue(report.succeeded)
        self.assertEqual(events, ["force", "terminate", "close"])

    def test_construction_failure_rolls_back_and_leaves_empty_manager(self):
        events = []
        first = SimpleNamespace(label="first")
        factory_calls = 0

        def factory():
            nonlocal factory_calls
            factory_calls += 1
            if factory_calls == 2:
                raise RuntimeError("constructor fault")
            events.append("construct:first")
            return first

        def action(name):
            return lambda instance: events.append(f"{name}:{instance.label}")

        registration = make_registration(
            factory=factory,
            force_stop=action("force"),
            stop_scan=action("stop"),
            terminate=action("terminate"),
            close_widget=action("close"),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())

        with self.assertRaisesRegex(DeviceStartupError, "constructor fault") as caught:
            manager.load_profile(
                make_profile(make_config("first"), make_config("second"))
            )

        self.assertEqual(
            events,
            [
                "construct:first",
                "force:first",
                "stop:first",
                "terminate:first",
                "close:first",
            ],
        )
        self.assertTrue(caught.exception.cleanup_report.succeeded)
        self.assertEqual(tuple(manager.snapshot().equipment), ())
        self.assertFalse(manager.loaded)
        with self.assertRaises(DeviceManagerLoadError):
            manager.load_profile(make_profile(make_config("later")))

    def test_connection_failure_aggregates_rollback_failures_and_cleans_all(self):
        events = []
        instances = iter(
            (SimpleNamespace(label="first"), SimpleNamespace(label="second"))
        )

        def action(name, *, fail_label=None):
            def run(instance):
                events.append(f"{name}:{instance.label}")
                if instance.label == fail_label:
                    raise RuntimeError(f"{name} fault")

            return run

        def connect(instance, _connection, _timeout_ms):
            events.append(f"connect:{instance.label}")
            raise RuntimeError("connection fault")

        registration = make_registration(
            factory=lambda: next(instances),
            connect=connect,
            force_stop=action("force", fail_label="first"),
            stop_scan=action("stop"),
            terminate=action("terminate"),
            close_widget=action("close"),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())

        with self.assertRaises(DeviceStartupError) as caught:
            manager.load_profile(
                make_profile(
                    make_config("first"),
                    make_config("second", connect_on_start=True),
                )
            )

        self.assertIn("connection fault", str(caught.exception))
        self.assertIn("rollback", str(caught.exception))
        self.assertEqual(len(caught.exception.failures), 2)
        self.assertEqual(
            events,
            [
                "connect:second",
                "force:first",
                "force:second",
                "stop:first",
                "stop:second",
                "terminate:first",
                "close:first",
                "terminate:second",
                "close:second",
            ],
        )
        self.assertEqual(tuple(manager.snapshot().equipment), ())

    def test_bulk_lifecycle_continues_and_reports_failures_in_profile_order(self):
        events = []
        instances = iter(
            (SimpleNamespace(label="first"), SimpleNamespace(label="second"))
        )

        def stop(instance):
            events.append(f"stop:{instance.label}")
            if instance.label == "first":
                raise RuntimeError("cannot stop")

        registration = make_registration(
            factory=lambda: next(instances),
            stop_scan=stop,
            start_scan=lambda instance: events.append(f"start:{instance.label}"),
            force_stop=lambda instance: events.append(f"force:{instance.label}"),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())
        manager.load_profile(make_profile(make_config("first"), make_config("second")))

        stop_report = manager.stop_for_scan()
        start_report = manager.start_after_scan()
        force_report = manager.force_stop_all()

        self.assertFalse(stop_report.succeeded)
        self.assertEqual(stop_report.failures[0].device_id, "first")
        self.assertTrue(start_report.succeeded)
        self.assertTrue(force_report.succeeded)
        self.assertEqual(
            events,
            [
                "stop:first",
                "stop:second",
                "start:first",
                "start:second",
                "force:first",
                "force:second",
            ],
        )
        self.assertEqual(manager.snapshot().records[0].state, DeviceState.ERROR)

    def test_teardown_is_ordered_continuing_aggregated_and_idempotent(self):
        events = []
        instances = iter(
            (SimpleNamespace(label="first"), SimpleNamespace(label="second"))
        )

        def action(name, failing=()):
            def run(instance):
                events.append(f"{name}:{instance.label}")
                if instance.label in failing:
                    raise RuntimeError(f"{name} failed")

            return run

        registration = make_registration(
            factory=lambda: next(instances),
            force_stop=action("force", {"first"}),
            stop_scan=action("stop", {"second"}),
            terminate=action("terminate", {"first"}),
            close_widget=action("close", {"second"}),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())
        manager.load_profile(make_profile(make_config("first"), make_config("second")))

        first_report = manager.teardown_all()
        second_report = manager.teardown_all()

        self.assertIs(first_report, second_report)
        self.assertFalse(first_report.succeeded)
        self.assertEqual(len(first_report.failures), 4)
        self.assertEqual(
            events,
            [
                "force:first",
                "force:second",
                "stop:first",
                "stop:second",
                "terminate:first",
                "close:first",
                "terminate:second",
                "close:second",
            ],
        )
        self.assertEqual(
            tuple(view.state for view in manager.snapshot().records),
            (DeviceState.ERROR, DeviceState.ERROR),
        )

    def test_teardown_rejects_non_owner_thread_before_touching_widget(self):
        calls = []
        registration = make_registration(
            terminate=lambda _instance: calls.append("terminate"),
            close_widget=lambda _instance: calls.append("close"),
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())
        manager.load_profile(make_profile(make_config("only")))
        errors = []

        worker = threading.Thread(
            target=lambda: self._capture_exception(manager.teardown_all, errors)
        )
        worker.start()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DeviceManagerThreadError)
        self.assertEqual(calls, [])
        self.assertTrue(manager.teardown_all().succeeded)
        self.assertEqual(calls, ["terminate", "close"])

    @staticmethod
    def _capture_exception(callback, errors):
        try:
            callback()
        except Exception as exc:
            errors.append(exc)


class DeviceManagerMockProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_checked_mock_profile_loads_two_disconnected_widgets_in_order(self):
        repository_root = Path(__file__).resolve().parents[1]
        registry = build_default_registry()
        profile = load_profile(
            repository_root / "config" / "profiles" / "mock.json",
            driver_specs=registry.config_specs,
            repository_root=repository_root,
        )
        manager = DeviceManager(registry, SimpleNamespace())
        self.addCleanup(manager.teardown_all)

        snapshot = manager.load_profile(profile)

        self.assertEqual(
            tuple(snapshot.equipment),
            ("mock_device_1", "mock_device_2"),
        )
        self.assertEqual(
            tuple(view.state for view in snapshot.records),
            (DeviceState.DISCONNECTED, DeviceState.DISCONNECTED),
        )
        self.assertEqual(
            dict(snapshot.setter_filters),
            {"mock_device_1": None, "mock_device_2": None},
        )
        self.assertEqual(
            dict(snapshot.getter_filters),
            {"mock_device_1": None, "mock_device_2": None},
        )
        self.assertTrue(
            all(not record.instance.logic.hardware.connected for record in snapshot.records)
        )

    def test_real_qwidgets_cannot_be_torn_down_from_a_worker_thread(self):
        repository_root = Path(__file__).resolve().parents[1]
        registry = build_default_registry()
        profile = load_profile(
            repository_root / "config" / "profiles" / "mock.json",
            driver_specs=registry.config_specs,
            repository_root=repository_root,
        )
        manager = DeviceManager(registry, SimpleNamespace())
        snapshot = manager.load_profile(profile)
        self.addCleanup(manager.teardown_all)

        self.assertTrue(
            all(record.instance.thread() is self.app.thread() for record in snapshot.records)
        )
        errors = []
        worker = threading.Thread(
            target=lambda: DeviceManagerPureTests._capture_exception(
                manager.teardown_all,
                errors,
            )
        )
        worker.start()
        worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], DeviceManagerThreadError)
        self.assertIsNone(manager.teardown_report)
        self.assertTrue(manager.teardown_all().succeeded)


if __name__ == "__main__":
    unittest.main()
