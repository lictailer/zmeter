from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.device_management.config import ProfileValidationError, load_profile
from core.device_management.manager import (
    DeviceManager,
    StartupDeviceStatus,
)
from core.device_management.models import (
    ChannelFilters,
    DeviceConfig,
    ProfileConfig,
    ProfilePaths,
)
from core.device_management.registry import (
    DriverAdapter,
    DriverRegistry,
    build_default_registry,
)


DEFERRED_DRIVER_IDS = (
    "autofocus_xz",
    "auto_focus",
    "auto_position",
    "anc300",
)

PHASE2_DRIVER_IDS = ("four9", "montana2", "opticool", "tlpm")


class Phase2RegistrationTests(unittest.TestCase):
    def test_tracked_phase2_profile_is_disabled_and_never_auto_connects(self):
        repository_root = Path(__file__).resolve().parents[1]
        registry = build_default_registry()
        profile = load_profile(
            repository_root / "config" / "profiles" / "phase2_lab.json",
            driver_specs=registry.config_specs,
            repository_root=repository_root,
        )

        self.assertEqual(profile.profile, "phase2_lab")
        self.assertEqual(
            tuple(device.driver for device in profile.devices), PHASE2_DRIVER_IDS
        )
        self.assertTrue(all(not device.enabled for device in profile.devices))
        self.assertTrue(
            all(not device.connect_on_start for device in profile.devices)
        )

    def test_default_registry_adds_phase2_without_importing_devices(self):
        repository_root = Path(__file__).resolve().parents[1]
        script = r"""
import sys
from pathlib import Path
from core.device_management.config import load_profile
from core.device_management.registry import build_default_registry

registry = build_default_registry()
assert registry.driver_ids[-4:] == ("four9", "montana2", "opticool", "tlpm")
for driver_id in registry.driver_ids[-4:]:
    assert driver_id in registry.config_specs
profile = load_profile(
    Path("config/profiles/phase2_lab.json"),
    driver_specs=registry.config_specs,
    repository_root=Path.cwd(),
)
assert all(not device.enabled for device in profile.devices)
loaded = sorted(
    name for name in sys.modules
    if name == "devices" or name.startswith("devices.")
    or name in {"clr", "QuantumDesign", "System"}
)
if loaded:
    raise SystemExit("unexpected device import: " + ", ".join(loaded))
print("phase2 registry remained lazy")
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

    def test_montana2_schema_requires_an_explicit_address(self):
        registry = build_default_registry()
        payload = {
            "schema_version": 1,
            "profile": "montana_schema",
            "paths": {"save": "./data", "backup": None},
            "devices": [
                {
                    "id": "montana2",
                    "driver": "montana2",
                    "enabled": False,
                    "connect_on_start": False,
                    "connection": {},
                    "scan_channels": {"set": None, "get": None},
                }
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "phase2.json"
            profile_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ProfileValidationError) as raised:
                load_profile(
                    profile_path,
                    driver_specs=registry.config_specs,
                    repository_root=root,
                )

        self.assertIn("connection.address is required", str(raised.exception))

    def test_montana2_ui_retains_the_existing_default_address(self):
        repository_root = Path(__file__).resolve().parents[1]
        root = ET.parse(
            repository_root / "devices" / "montana2" / "montana2.ui"
        ).getroot()
        address_widget = root.find(".//widget[@name='ipaddress_lineEdit']")
        self.assertIsNotNone(address_widget)
        text = address_widget.find("./property[@name='text']/string")
        self.assertIsNotNone(text)
        self.assertEqual(text.text, "136.167.55.165")

    def test_four9_schema_validates_without_import_or_construction(self):
        registry = build_default_registry()
        payload = {
            "schema_version": 1,
            "profile": "phase2_schema",
            "paths": {"save": "./data", "backup": None},
            "devices": [
                {
                    "id": "four9_1",
                    "driver": "four9",
                    "enabled": False,
                    "connect_on_start": False,
                    "connection": {
                        "host": "four9.invalid",
                        "port": 5050,
                        "socket_timeout_s": 2.5,
                    },
                    "scan_channels": {"set": None, "get": None},
                }
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "phase2.json"
            profile_path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch(
                "core.device_management.registrations.import_module"
            ) as import_device:
                profile = load_profile(
                    profile_path,
                    driver_specs=registry.config_specs,
                    repository_root=root,
                )

        self.assertEqual(profile.devices[0].driver, "four9")
        self.assertFalse(profile.devices[0].enabled)
        import_device.assert_not_called()

    def test_four9_factory_configuration_and_startup_use_panel_worker_path(self):
        registration = build_default_registry().registration("four9")
        imported = SimpleNamespace(Four9=mock.Mock(return_value=object()))
        with mock.patch(
            "core.device_management.registrations.import_module",
            return_value=imported,
        ) as import_device:
            registration.factory()

        import_device.assert_called_once_with("devices.four9.four9_main")

        hardware = SimpleNamespace(
            host="old-host",
            port=1,
            socket_timeout_s=10.0,
        )
        logic = SimpleNamespace(
            hardware=hardware,
            host="old-host",
            port=1,
            socket_timeout_s=10.0,
            is_connected=False,
        )
        instance = SimpleNamespace(
            logic=logic,
            host_lineEdit=SimpleNamespace(setText=mock.Mock()),
            port_spinBox=SimpleNamespace(setValue=mock.Mock()),
            _start_logic_job=mock.Mock(return_value=True),
        )
        config = DeviceConfig(
            id="four9_1",
            driver="four9",
            enabled=True,
            connect_on_start=True,
            connection={
                "host": "four9.invalid",
                "port": 5051,
                "socket_timeout_s": 3.5,
            },
            scan_channels=ChannelFilters(setters=None, getters=None),
        )

        registration.configure_instance(instance, dict(config.connection))
        self.assertEqual(logic.host, "four9.invalid")
        self.assertEqual(logic.port, 5051)
        self.assertEqual(logic.socket_timeout_s, 3.5)
        self.assertEqual(hardware.host, "four9.invalid")
        self.assertEqual(hardware.port, 5051)
        self.assertEqual(hardware.socket_timeout_s, 3.5)
        instance.host_lineEdit.setText.assert_called_once_with("four9.invalid")
        instance.port_spinBox.setValue.assert_called_once_with(5051)

        adapter = DriverAdapter(registration, config, instance)
        self.assertIsNone(adapter.startup_connect())
        instance._start_logic_job.assert_called_once_with("connect")

        instance._start_logic_job.reset_mock(return_value=True)
        instance._start_logic_job.return_value = False
        self.assertIs(adapter.startup_connect(), False)

    def test_four9_lifecycle_callbacks_preserve_existing_hooks(self):
        registration = build_default_registry().registration("four9")
        logic = SimpleNamespace(
            is_connected=True,
            disconnect=mock.Mock(),
        )
        instance = SimpleNamespace(
            logic=logic,
            force_stop=mock.Mock(),
            terminate_dev=mock.Mock(),
        )
        config = DeviceConfig(
            id="four9_1",
            driver="four9",
            enabled=True,
            connect_on_start=False,
            connection={"host": "four9.invalid", "port": 5050},
            scan_channels=ChannelFilters(setters=None, getters=None),
        )
        adapter = DriverAdapter(registration, config, instance)

        adapter.force_stop()
        adapter.stop_scan()
        adapter.disconnect()
        adapter.terminate()

        instance.force_stop.assert_called_once_with()
        logic.disconnect.assert_called_once_with()
        instance.terminate_dev.assert_called_once_with()
        self.assertTrue(adapter.terminated)
        self.assertFalse(registration.runtime_mutation_allowed)

    def test_new_phase2_adapters_map_configuration_and_pending_jobs(self):
        registry = build_default_registry()

        line_edit = SimpleNamespace(setText=mock.Mock())
        combo = SimpleNamespace(setCurrentText=mock.Mock())
        montana_logic = SimpleNamespace(
            ipaddress="",
            is_connected=False,
            isRunning=mock.Mock(return_value=False),
        )
        montana = SimpleNamespace(
            logic=montana_logic,
            quickConnect_comboBox=combo,
            ipaddress_lineEdit=line_edit,
            _on_connect_clicked=mock.Mock(),
        )
        montana_registration = registry.registration("montana2")
        montana_registration.configure_instance(
            montana, {"address": "192.0.2.10"}
        )
        self.assertEqual(montana_logic.ipaddress, "192.0.2.10")
        combo.setCurrentText.assert_called_once_with("Other")
        line_edit.setText.assert_called_once_with("192.0.2.10")

        montana_adapter = DriverAdapter(
            montana_registration,
            DeviceConfig(
                id="montana2",
                driver="montana2",
                enabled=True,
                connect_on_start=True,
                connection={"address": "192.0.2.10"},
                scan_channels=ChannelFilters(setters=None, getters=None),
            ),
            montana,
        )
        self.assertIsNone(montana_adapter.startup_connect())
        montana._on_connect_clicked.assert_called_once_with()

        for driver_id in ("opticool", "tlpm"):
            with self.subTest(driver_id=driver_id):
                if driver_id == "opticool":
                    instance = SimpleNamespace(
                        logic=SimpleNamespace(is_connected=False),
                        _start_logic_job=mock.Mock(return_value=True),
                    )
                else:
                    instance = SimpleNamespace(
                        logic=SimpleNamespace(is_connected=False),
                        connect=mock.Mock(return_value=True),
                    )
                registration = registry.registration(driver_id)
                adapter = DriverAdapter(
                    registration,
                    DeviceConfig(
                        id=driver_id,
                        driver=driver_id,
                        enabled=True,
                        connect_on_start=True,
                        connection={},
                        scan_channels=ChannelFilters(
                            setters=None, getters=None
                        ),
                    ),
                    instance,
                )
                self.assertIsNone(adapter.startup_connect())
                self.assertFalse(registration.runtime_mutation_allowed)

        opticool = SimpleNamespace(
            logic=SimpleNamespace(is_connected=False),
            _start_logic_job=mock.Mock(return_value=False),
        )
        registration = registry.registration("opticool")
        adapter = DriverAdapter(
            registration,
            DeviceConfig(
                id="opticool_busy",
                driver="opticool",
                enabled=True,
                connect_on_start=True,
                connection={},
                scan_channels=ChannelFilters(setters=None, getters=None),
            ),
            opticool,
        )
        self.assertIs(adapter.startup_connect(), False)

    def test_four9_manager_startup_is_pending_and_teardown_owns_only_client(self):
        events = []
        hardware = SimpleNamespace(
            host="old-host",
            port=1,
            socket_timeout_s=10.0,
        )
        logic = SimpleNamespace(
            hardware=hardware,
            host="old-host",
            port=1,
            socket_timeout_s=10.0,
            is_connected=False,
            disconnect=lambda: events.append("disconnect"),
        )
        instance = SimpleNamespace(
            logic=logic,
            host_lineEdit=SimpleNamespace(setText=lambda _value: None),
            port_spinBox=SimpleNamespace(setValue=lambda _value: None),
            _start_logic_job=lambda job: events.append(f"job:{job}") or True,
            force_stop=lambda: events.append("force_stop"),
            terminate_dev=lambda: events.append("terminate"),
            close=lambda: events.append("close"),
        )
        registration = replace(
            build_default_registry().registration("four9"),
            factory=lambda: instance,
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())
        config = DeviceConfig(
            id="four9_1",
            driver="four9",
            enabled=True,
            connect_on_start=True,
            connection={
                "host": "four9.invalid",
                "port": 5050,
                "socket_timeout_s": 0.1,
            },
            scan_channels=ChannelFilters(setters=None, getters=None),
        )
        profile = ProfileConfig(
            schema_version=1,
            profile="phase2",
            paths=ProfilePaths(save=Path("data"), backup=None),
            devices=(config,),
            source_path=Path("phase2.json"),
            repository_root=Path.cwd(),
        )

        snapshot = manager.load_profile(profile)
        report = manager.request_startup_connections()

        self.assertEqual(tuple(snapshot.equipment), ("four9_1",))
        self.assertIs(
            report.results[0].status,
            StartupDeviceStatus.PENDING,
        )
        self.assertEqual(events, ["job:connect"])

        shutdown = manager.teardown_all()
        self.assertTrue(shutdown.succeeded)
        self.assertEqual(
            events,
            ["job:connect", "force_stop", "terminate", "close"],
        )

    def test_phase2_construction_failure_skips_only_that_device(self):
        events = []

        def fail_factory():
            raise RuntimeError("optional environment is unavailable")

        tlpm = SimpleNamespace(
            logic=SimpleNamespace(is_connected=False, disconnect=mock.Mock()),
            connect=mock.Mock(return_value=True),
            force_stop=lambda: events.append("force_stop") or True,
            terminate_dev=lambda: events.append("terminate") or True,
            close=lambda: events.append("close"),
        )
        registry = build_default_registry()
        registrations = (
            replace(
                registry.registration("opticool"), factory=fail_factory
            ),
            replace(registry.registration("tlpm"), factory=lambda: tlpm),
        )
        manager = DeviceManager(DriverRegistry(registrations), SimpleNamespace())
        devices = (
            DeviceConfig(
                id="opticool",
                driver="opticool",
                enabled=True,
                connect_on_start=False,
                connection={},
                scan_channels=ChannelFilters(setters=None, getters=None),
            ),
            DeviceConfig(
                id="tlpm",
                driver="tlpm",
                enabled=True,
                connect_on_start=False,
                connection={},
                scan_channels=ChannelFilters(setters=None, getters=None),
            ),
        )
        profile = ProfileConfig(
            schema_version=1,
            profile="phase2_best_effort",
            paths=ProfilePaths(save=Path("data"), backup=None),
            devices=devices,
            source_path=Path("phase2.json"),
            repository_root=Path.cwd(),
        )

        snapshot = manager.load_profile(profile)

        self.assertEqual(tuple(snapshot.equipment), ("tlpm",))
        self.assertEqual(
            tuple(result.status for result in manager.startup_report.results),
            (
                StartupDeviceStatus.CONSTRUCTION_SKIPPED,
                StartupDeviceStatus.READY,
            ),
        )
        self.assertTrue(manager.teardown_all().succeeded)
        self.assertEqual(events, ["force_stop", "terminate", "close"])

    def test_deferred_phase2_ids_remain_visibly_unregistered(self):
        registry = build_default_registry()
        for driver_id in DEFERRED_DRIVER_IDS:
            with self.subTest(driver_id=driver_id):
                payload = {
                    "schema_version": 1,
                    "profile": "deferred",
                    "paths": {"save": "./data", "backup": None},
                    "devices": [
                        {
                            "id": f"{driver_id}_1",
                            "driver": driver_id,
                            "enabled": False,
                            "connect_on_start": False,
                            "connection": {},
                            "scan_channels": {"set": None, "get": None},
                        }
                    ],
                }
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    profile_path = root / "deferred.json"
                    profile_path.write_text(json.dumps(payload), encoding="utf-8")
                    with self.assertRaises(ProfileValidationError) as raised:
                        load_profile(
                            profile_path,
                            driver_specs=registry.config_specs,
                            repository_root=root,
                        )

                self.assertIn(
                    f"driver '{driver_id}' is not registered", str(raised.exception)
                )


if __name__ == "__main__":
    unittest.main()
