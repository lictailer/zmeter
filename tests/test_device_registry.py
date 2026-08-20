from __future__ import annotations

import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.device_management.config import load_profile
from core.device_management.models import (
    ChannelFilters,
    ConnectionFieldSpec,
    DeviceConfig,
    DriverConfigSpec,
)
from core.device_management.registry import (
    DisabledDeviceError,
    DriverConstructionError,
    DriverRegistration,
    DriverRegistry,
    DriverConfigurationError,
    DriverTerminatedError,
    DriverUnavailableError,
    DuplicateDriverError,
    UnknownDriverError,
    build_default_registry,
)


def make_config(
    *,
    device_id="device_1",
    driver="fake_driver",
    enabled=True,
    connection=None,
):
    return DeviceConfig(
        id=device_id,
        driver=driver,
        enabled=enabled,
        connect_on_start=False,
        connection=connection or {},
        scan_channels=ChannelFilters(setters=None, getters=None),
    )


def fake_registration(**overrides):
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


class DriverRegistryPureTests(unittest.TestCase):
    def test_default_registry_lookup_is_lazy_in_a_fresh_process(self):
        repository_root = Path(__file__).resolve().parents[1]
        script = """
import sys
from core.device_management.registry import build_default_registry

registry = build_default_registry()
assert registry.driver_ids == (
    "mock_device", "ni6423", "nidaq", "pem100", "sp150",
    "hp34401a", "keithley24xx", "sr860", "sr830", "demo_device",
    "bbd30x", "k10cr1", "four9", "montana2", "opticool", "tlpm",
)
assert "mock_device" in registry.config_specs
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
print("registry lookup remained lazy")
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

    def test_duplicate_and_unknown_driver_ids_are_rejected(self):
        registration = fake_registration()
        registry = DriverRegistry((registration,))

        with self.assertRaises(DuplicateDriverError):
            registry.register(registration)
        with self.assertRaises(UnknownDriverError):
            registry.registration("arbitrary.module:Class")

    def test_factory_receives_only_declared_runtime_services(self):
        selected_visa = object()
        received = []

        def factory(*, visa):
            received.append(visa)
            return SimpleNamespace()

        registration = fake_registration(
            factory=factory,
            runtime_services=("visa",),
        )
        registry = DriverRegistry((registration,))
        services = SimpleNamespace(visa=selected_visa, kinesis=object())

        adapter = registry.create(make_config(), services)

        self.assertEqual(received, [selected_visa])
        self.assertIs(adapter.instance.__class__, SimpleNamespace)

    def test_constructed_instance_is_configured_and_closed_on_configuration_failure(self):
        calls = []

        class Instance:
            def close(self):
                calls.append("close")

        registration = fake_registration(
            factory=lambda: calls.append("factory") or Instance(),
            configure_instance=lambda _instance, connection: (
                calls.append(("configure", dict(connection)))
                or (_ for _ in ()).throw(RuntimeError("bad panel configuration"))
            ),
        )
        registry = DriverRegistry((registration,))

        with self.assertRaisesRegex(
            DriverConstructionError, "bad panel configuration"
        ):
            registry.create(make_config(), SimpleNamespace())

        self.assertEqual(
            calls,
            ["factory", ("configure", {}), "close"],
        )

    def test_runtime_service_declaration_is_frozen(self):
        service_names = ["visa"]
        registration = fake_registration(
            factory=lambda **_kwargs: SimpleNamespace(),
            runtime_services=service_names,
        )

        service_names.append("kinesis")

        self.assertEqual(registration.runtime_services, ("visa",))

    def test_disabled_optional_driver_never_invokes_factory(self):
        calls = []

        def missing_factory():
            calls.append(True)
            raise ModuleNotFoundError("optional_sdk")

        registry = DriverRegistry(
            (fake_registration(factory=missing_factory),)
        )

        with self.assertRaises(DisabledDeviceError):
            registry.create(make_config(enabled=False), SimpleNamespace())
        self.assertEqual(calls, [])

        with self.assertRaisesRegex(DriverUnavailableError, "optional_sdk"):
            registry.create(make_config(enabled=True), SimpleNamespace())
        self.assertEqual(calls, [True])

        healthy = fake_registration(
            config_spec=DriverConfigSpec(
                driver_id="healthy_driver",
                connection_fields={},
            ),
            factory=lambda: SimpleNamespace(healthy=True),
        )
        registry.register(healthy)
        healthy_adapter = registry.create(
            make_config(driver="healthy_driver"),
            SimpleNamespace(),
        )
        self.assertTrue(healthy_adapter.instance.healthy)

    def test_lifecycle_adapter_uses_reviewed_callbacks_and_is_idempotent(self):
        calls = []
        instance = SimpleNamespace()
        registration = fake_registration(
            config_spec=DriverConfigSpec(
                driver_id="fake_driver",
                connection_fields={
                    "nested": ConnectionFieldSpec((list,)),
                },
            ),
            factory=lambda: calls.append("factory") or instance,
            connect=lambda obj, values, timeout_ms: (
                calls.append(("connect", obj, values, timeout_ms)) or True
            ),
            disconnect=lambda obj: calls.append(("disconnect", obj)),
            start_scan=lambda obj: calls.append(("start_scan", obj)),
            stop_scan=lambda obj: calls.append(("stop_scan", obj)),
            force_stop=lambda obj: calls.append(("force_stop", obj)),
            terminate=lambda obj: calls.append(("terminate", obj)),
            close_widget=lambda obj: calls.append(("close", obj)),
            is_busy=lambda _obj: True,
            is_connected=lambda _obj: True,
        )
        registry = DriverRegistry((registration,))
        adapter = registry.create(
            make_config(connection={"nested": [{"value": 1}]}),
            SimpleNamespace(),
        )

        adapter.connect()
        adapter.stop_scan()
        adapter.start_scan()
        adapter.force_stop()
        adapter.disconnect()
        self.assertTrue(adapter.busy())
        self.assertTrue(adapter.connected())
        adapter.terminate()
        adapter.terminate()
        adapter.close()
        adapter.close()

        self.assertFalse(adapter.busy())
        self.assertFalse(adapter.connected())
        self.assertEqual(calls.count(("terminate", instance)), 1)
        self.assertEqual(calls.count(("close", instance)), 1)
        connect_call = next(call for call in calls if isinstance(call, tuple) and call[0] == "connect")
        self.assertEqual(connect_call[2], {"nested": [{"value": 1}]})
        self.assertEqual(connect_call[3], 10_000)

    def test_connection_timeout_must_be_a_positive_integer(self):
        for timeout_ms in (0, -1, True, 1.5):
            with self.subTest(timeout_ms=timeout_ms):
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    fake_registration(connect_timeout_ms=timeout_ms)

    def test_registry_rechecks_connection_schema_before_construction(self):
        calls = []
        registration = fake_registration(
            config_spec=DriverConfigSpec(
                driver_id="fake_driver",
                connection_fields={
                    "address": ConnectionFieldSpec((str,), required=True),
                },
            ),
            factory=lambda: calls.append(True) or SimpleNamespace(),
        )
        registry = DriverRegistry((registration,))

        for connection in (
            {},
            {"address": 4},
            {"address": "SAFE", "fallback": "UNREVIEWED"},
        ):
            with self.subTest(connection=connection):
                with self.assertRaises(DriverConfigurationError):
                    registry.create(
                        make_config(connection=connection),
                        SimpleNamespace(),
                    )
        self.assertEqual(calls, [])

    def test_concurrent_and_failed_termination_are_one_attempt(self):
        calls = []
        started = threading.Event()
        release = threading.Event()

        def terminate(_instance):
            calls.append("terminate")
            started.set()
            self.assertTrue(release.wait(timeout=1))
            raise RuntimeError("partial teardown")

        adapter = DriverRegistry(
            (fake_registration(terminate=terminate),)
        ).create(make_config(), SimpleNamespace())
        errors = []

        def run_terminate():
            try:
                adapter.terminate()
            except RuntimeError as exc:
                errors.append(str(exc))

        first = threading.Thread(target=run_terminate)
        second = threading.Thread(target=run_terminate)
        first.start()
        self.assertTrue(started.wait(timeout=1))
        second.start()
        release.set()
        first.join(timeout=1)
        second.join(timeout=1)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(calls, ["terminate"])
        self.assertEqual(errors, ["partial teardown"])
        self.assertTrue(adapter.terminated)
        self.assertIsInstance(adapter.termination_error, RuntimeError)
        self.assertIsNone(adapter.terminate())

    def test_failed_close_is_not_retried(self):
        calls = []

        def close(_instance):
            calls.append("close")
            raise RuntimeError("partially closed")

        adapter = DriverRegistry(
            (fake_registration(close_widget=close),)
        ).create(make_config(), SimpleNamespace())

        with self.assertRaisesRegex(RuntimeError, "partially closed"):
            adapter.close()

        self.assertIsNone(adapter.close())
        self.assertEqual(calls, ["close"])
        self.assertTrue(adapter.closed)
        self.assertIsInstance(adapter.close_error, RuntimeError)

    def test_terminated_adapter_rejects_further_lifecycle_calls(self):
        registration = fake_registration(
            connect=lambda _obj, _values, _timeout_ms: True,
            disconnect=lambda _obj: None,
        )
        adapter = DriverRegistry((registration,)).create(
            make_config(),
            SimpleNamespace(),
        )
        adapter.terminate()

        for action in (
            adapter.connect,
            adapter.disconnect,
            adapter.start_scan,
            adapter.stop_scan,
            adapter.force_stop,
        ):
            with self.subTest(action=action.__name__):
                with self.assertRaises(DriverTerminatedError):
                    action()
        self.assertFalse(adapter.busy())
        self.assertFalse(adapter.connected())


class DefaultMockRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_checked_profile_constructs_disconnected_mock_through_registry(self):
        repository_root = Path(__file__).resolve().parents[1]
        registry = build_default_registry()
        profile = load_profile(
            repository_root / "config" / "profiles" / "mock.json",
            driver_specs=registry.config_specs,
            repository_root=repository_root,
        )

        adapter = registry.create(profile.devices[0], SimpleNamespace())
        self.addCleanup(adapter.close)
        self.addCleanup(adapter.terminate)

        self.assertEqual(adapter.device_id, "mock_device_1")
        self.assertFalse(adapter.connected())
        self.assertFalse(adapter.busy())
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            adapter.stop_scan()
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            adapter.start_scan()

        self.assertIs(adapter.connect(), True)
        self.assertTrue(adapter.connected())
        adapter.stop_scan()
        adapter.start_scan()
        self.assertFalse(adapter.force_stop())
        adapter.disconnect()
        self.assertFalse(adapter.connected())


if __name__ == "__main__":
    unittest.main()
