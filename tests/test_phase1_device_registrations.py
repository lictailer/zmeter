from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.device_management.config import ProfileValidationError, load_profile
from core.device_management.models import ChannelFilters, DeviceConfig
from core.device_management.registry import DriverAdapter, build_default_registry


EXPECTED_DRIVER_IDS = (
    "mock_device",
    "ni6423",
    "nidaq",
    "pem100",
    "sp150",
    "hp34401a",
    "keithley24xx",
    "sr860",
    "sr830",
    "demo_device",
    "bbd30x",
    "k10cr1",
)

FACTORIES = {
    "ni6423": ("devices.ni6423.ni6423_main", "NI6423", None, None),
    "nidaq": ("devices.nidaq.nidaq_main", "NIDAQ", None, None),
    "pem100": (
        "devices.pem100.pem100_main", "PEM100", "visa", "visa_runtime"
    ),
    "sp150": (
        "devices.sp150.sp150_main", "SP150", "visa", "visa_runtime"
    ),
    "hp34401a": (
        "devices.hp34401a.hp34401a_main", "HP34401A", "visa", "visa_runtime"
    ),
    "keithley24xx": (
        "devices.keithley24xx.keithley24xx_main",
        "Keithley24xx",
        "visa",
        "visa_runtime",
    ),
    "sr860": (
        "devices.sr860.sr860_main", "SR860", "visa", "visa_runtime"
    ),
    "sr830": (
        "devices.sr830.sr830_main", "SR830", "visa", "visa_runtime"
    ),
    "demo_device": (
        "devices.demoDevice.demoDevice_main", "DemoDevice", None, None
    ),
    "bbd30x": (
        "devices.BBD30X.BBD30X_main", "BBD30X", "kinesis", "kinesis_runtime"
    ),
    "k10cr1": (
        "devices.k10cr1.k10cr1_main", "K10CR1", "kinesis", "kinesis_runtime"
    ),
}

CONNECTIONS = {
    "ni6423": {"device_name": "Dev1"},
    "nidaq": {"device_name": "Dev1"},
    "pem100": {"address": "TEST::PEM", "timeout_ms": 1},
    "sp150": {
        "address": "TEST::SP150",
        "timeout_ms": 1,
        "query_delay_s": 0,
    },
    "hp34401a": {"address": "TEST::HP"},
    "keithley24xx": {"address": "TEST::K24XX"},
    "sr860": {"address": "TEST::SR860"},
    "sr830": {"address": "TEST::SR830"},
    "demo_device": {"address": "DUMMY::INSTR"},
    "bbd30x": {"serial": "TEST_BBD30X"},
    "k10cr1": {"serial": "TEST_K10CR1"},
}


class Phase1RegistrationTests(unittest.TestCase):
    def test_default_registry_is_lazy_and_contains_phase1_ids(self):
        repository_root = Path(__file__).resolve().parents[1]
        script = f"""
import sys
from core.device_management.registry import build_default_registry

expected = {EXPECTED_DRIVER_IDS!r}
registry = build_default_registry()
assert registry.driver_ids == expected
watched = (
    "devices", "pyvisa", "clr", "System", "nidaqmx", "PyDAQmx",
)
loaded = sorted(
    name for name in sys.modules
    if any(name == prefix or name.startswith(prefix + ".") for prefix in watched)
)
if loaded:
    raise SystemExit("unexpected device/vendor import: " + ", ".join(loaded))
print("phase1 registry remained lazy")
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

    def test_lazy_factories_map_shared_runtimes_without_importing_early(self):
        registry = build_default_registry()
        selected_runtime = object()

        for driver_id, (
            module_name,
            class_name,
            service_name,
            constructor_keyword,
        ) in FACTORIES.items():
            with self.subTest(driver_id=driver_id):
                received = []

                class FakeWidget:
                    def __init__(self, **kwargs):
                        received.append(kwargs)

                fake_module = SimpleNamespace(**{class_name: FakeWidget})
                registration = registry.registration(driver_id)
                runtime_kwargs = (
                    {} if service_name is None else {service_name: selected_runtime}
                )
                with mock.patch(
                    "core.device_management.registrations.import_module",
                    return_value=fake_module,
                ) as import_device:
                    registration.factory(**runtime_kwargs)

                import_device.assert_called_once_with(module_name)
                expected_kwargs = (
                    {}
                    if constructor_keyword is None
                    else {constructor_keyword: selected_runtime}
                )
                self.assertEqual(received, [expected_kwargs])

    def test_all_phase1_schemas_validate_while_disabled(self):
        registry = build_default_registry()
        payload = {
            "schema_version": 1,
            "profile": "phase1_schema",
            "paths": {"save": "./data", "backup": None},
            "devices": [
                {
                    "id": f"{driver_id}_1",
                    "driver": driver_id,
                    "enabled": False,
                    "connect_on_start": False,
                    "connection": connection,
                    "scan_channels": {"set": None, "get": None},
                }
                for driver_id, connection in CONNECTIONS.items()
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "phase1.json"
            profile_path.write_text(json.dumps(payload), encoding="utf-8")
            profile = load_profile(
                profile_path,
                driver_specs=registry.config_specs,
                repository_root=root,
            )

        self.assertEqual(
            tuple(device.driver for device in profile.devices), tuple(CONNECTIONS)
        )
        self.assertTrue(all(not device.enabled for device in profile.devices))

    def test_ni_drivers_require_device_name_not_address(self):
        registry = build_default_registry()
        payload = {
            "schema_version": 1,
            "profile": "bad_ni",
            "paths": {"save": "./data", "backup": None},
            "devices": [
                {
                    "id": "ni_1",
                    "driver": "ni6423",
                    "enabled": True,
                    "connect_on_start": False,
                    "connection": {"address": "Dev1"},
                    "scan_channels": {"set": None, "get": None},
                }
            ],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile_path = root / "bad.json"
            profile_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(ProfileValidationError) as raised:
                load_profile(
                    profile_path,
                    driver_specs=registry.config_specs,
                    repository_root=root,
                )

        message = str(raised.exception)
        self.assertIn("unsupported field 'address'", message)
        self.assertIn("connection.device_name is required", message)

    def test_real_drivers_are_startup_only(self):
        registry = build_default_registry()
        self.assertTrue(registry.registration("mock_device").runtime_mutation_allowed)
        for driver_id in EXPECTED_DRIVER_IDS[1:]:
            with self.subTest(driver_id=driver_id):
                self.assertFalse(
                    registry.registration(driver_id).runtime_mutation_allowed
                )

        manual_startup_connect = (
            "ni6423", "nidaq", "keithley24xx", "bbd30x", "k10cr1"
        )
        for driver_id in manual_startup_connect:
            self.assertFalse(
                registry.config_specs[driver_id].supports_startup_connection
            )

    def test_reviewed_synchronous_visa_connection_mapping(self):
        registry = build_default_registry()

        pem = SimpleNamespace(
            logic=SimpleNamespace(connected=True),
            connect=mock.Mock(return_value=True),
        )
        config = DeviceConfig(
            id="pem_1",
            driver="pem100",
            enabled=True,
            connect_on_start=True,
            connection={"address": "TEST::PEM", "timeout_ms": 1234},
            scan_channels=ChannelFilters(setters=None, getters=None),
        )
        adapter = DriverAdapter(registry.registration("pem100"), config, pem)
        self.assertIs(adapter.connect(), True)
        pem.connect.assert_called_once_with("TEST::PEM", timeout_ms=1234)

        sp = SimpleNamespace(
            logic=SimpleNamespace(connected=True),
            connect=mock.Mock(return_value=True),
        )
        config = DeviceConfig(
            id="sp_1",
            driver="sp150",
            enabled=True,
            connect_on_start=True,
            connection={
                "address": "TEST::SP150",
                "timeout_ms": 2345,
                "query_delay_s": 0,
            },
            scan_channels=ChannelFilters(setters=None, getters=None),
        )
        adapter = DriverAdapter(registry.registration("sp150"), config, sp)
        self.assertIs(adapter.connect(), True)
        sp.connect.assert_called_once_with(
            "TEST::SP150", timeout_ms=2345, query_delay_s=0.0
        )

    def test_profile_identifiers_prefill_manual_connection_panels(self):
        registry = build_default_registry()
        text_cases = (
            ("ni6423", "dev_name_lineEdit", "device_name", "Dev1"),
            ("nidaq", "dev_name_lineEdit", "device_name", "Dev2"),
            ("bbd30x", "serial_lineEdit", "serial", "BBD123"),
            ("k10cr1", "lineEdit", "serial", "K10123"),
        )

        for driver_id, widget_name, field, value in text_cases:
            with self.subTest(driver_id=driver_id):
                control = SimpleNamespace(setText=mock.Mock())
                instance = SimpleNamespace(**{widget_name: control})
                registry.registration(driver_id).configure_instance(
                    instance, {field: value}
                )
                control.setText.assert_called_once_with(value)

        combo = SimpleNamespace(
            findText=mock.Mock(return_value=-1),
            addItem=mock.Mock(),
            setCurrentText=mock.Mock(),
        )
        registry.registration("keithley24xx").configure_instance(
            SimpleNamespace(address_cb=combo), {"address": "K::1"}
        )
        combo.findText.assert_called_once_with("K::1")
        combo.addItem.assert_called_once_with("K::1")
        combo.setCurrentText.assert_called_once_with("K::1")

    def test_official_sr830_factory_uses_only_canonical_package(self):
        registration = build_default_registry().registration("sr830")
        fake_runtime = object()

        class FakeSR830:
            def __init__(self, *, visa_runtime):
                self.visa_runtime = visa_runtime

        with mock.patch(
            "core.device_management.registrations.import_module",
            return_value=SimpleNamespace(SR830=FakeSR830),
        ) as import_device:
            instance = registration.factory(visa=fake_runtime)

        import_device.assert_called_once_with("devices.sr830.sr830_main")
        self.assertIs(instance.visa_runtime, fake_runtime)


if __name__ == "__main__":
    unittest.main()
