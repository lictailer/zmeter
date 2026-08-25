from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core.device_management.manager import DeviceManager, StartupDeviceStatus
from core.device_management.models import (
    ChannelFilters,
    ConnectionFieldSpec,
    DeviceConfig,
    DriverConfigSpec,
    ProfileConfig,
    ProfilePaths,
)
from core.device_management.registry import (
    DriverAdapter,
    DriverRegistration,
    DriverRegistry,
    UnknownDriverError,
    build_default_registry,
)


def _config(
    driver: str,
    address: str = "",
    *,
    device_id: str | None = None,
    connect_on_start: bool = True,
    connection: dict[str, object] | None = None,
) -> DeviceConfig:
    return DeviceConfig(
        id=device_id or driver,
        driver=driver,
        enabled=True,
        connect_on_start=connect_on_start,
        connection={"address": address} if connection is None else connection,
        scan_channels=ChannelFilters(setters=None, getters=None),
    )


def _profile(*devices: DeviceConfig) -> ProfileConfig:
    root = Path.cwd()
    return ProfileConfig(
        schema_version=1,
        profile="generic-address",
        paths=ProfilePaths(save=root / "data", backup=None),
        devices=devices,
        source_path=root / "device_config.xlsx",
        repository_root=root,
    )


class GenericAddressRegistrationTests(unittest.TestCase):
    def test_every_registered_driver_accepts_one_optional_address(self):
        registry = build_default_registry()

        for driver_id, spec in registry.config_specs.items():
            with self.subTest(driver_id=driver_id):
                self.assertEqual(tuple(spec.connection_fields), ("address",))
                address = spec.connection_fields["address"]
                self.assertEqual(address.value_types, (str,))
                self.assertFalse(address.required)

    def test_ni_and_kinesis_adapters_translate_address_to_existing_argument(self):
        registry = build_default_registry()

        for driver_id in ("ni6423", "nidaq"):
            with self.subTest(driver_id=driver_id):
                instance = SimpleNamespace(
                    logic=SimpleNamespace(is_initialized=True),
                    connect=mock.Mock(),
                )
                adapter = DriverAdapter(
                    registry.registration(driver_id),
                    _config(driver_id, "Dev42"),
                    instance,
                )
                self.assertIs(adapter.startup_connect(), True)
                instance.connect.assert_called_once_with("Dev42")

        bbd = SimpleNamespace(
            logic=SimpleNamespace(is_connected=False),
            connect=mock.Mock(return_value=True),
        )
        bbd_adapter = DriverAdapter(
            registry.registration("bbd30x"),
            _config("bbd30x", "000035995686"),
            bbd,
        )
        self.assertIsNone(bbd_adapter.startup_connect())
        bbd.connect.assert_called_once_with("000035995686")

        k10 = SimpleNamespace(
            logic=SimpleNamespace(is_connected=True),
            connect=mock.Mock(return_value=True),
        )
        k10_adapter = DriverAdapter(
            registry.registration("k10cr1"),
            _config("k10cr1", "000043755678"),
            k10,
        )
        self.assertIs(k10_adapter.startup_connect(), True)
        k10.connect.assert_called_once_with("000043755678")

    def test_prefill_adapters_keep_blank_or_leading_zero_address_text(self):
        registry = build_default_registry()
        cases = (
            ("ni6423", "dev_name_lineEdit", ""),
            ("nidaq", "dev_name_lineEdit", "Dev2"),
            ("bbd30x", "serial_lineEdit", "000035995686"),
            ("k10cr1", "lineEdit", "000043755678"),
        )

        for driver_id, widget_name, address in cases:
            with self.subTest(driver_id=driver_id):
                line_edit = SimpleNamespace(setText=mock.Mock())
                instance = SimpleNamespace(**{widget_name: line_edit})
                registry.registration(driver_id).configure_instance(
                    instance, {"address": address}
                )
                line_edit.setText.assert_called_once_with(address)

    def test_pem_and_sp_use_driver_owned_connection_defaults(self):
        registry = build_default_registry()

        for driver_id, address in (
            ("pem100", "GPIB2::10::INSTR"),
            ("sp150", "GPIB2::11::INSTR"),
        ):
            with self.subTest(driver_id=driver_id):
                instance = SimpleNamespace(
                    logic=SimpleNamespace(connected=True),
                    connect=mock.Mock(return_value=True),
                )
                adapter = DriverAdapter(
                    registry.registration(driver_id),
                    _config(driver_id, address),
                    instance,
                )
                self.assertIs(adapter.startup_connect(), True)
                instance.connect.assert_called_once_with(address)

    def test_visa_adapters_forward_address_without_validating_it(self):
        registry = build_default_registry()

        for driver_id in ("hp34401a", "sr860", "sr830"):
            with self.subTest(driver_id=driver_id):
                logic = SimpleNamespace(
                    connected=True,
                    _connected=True,
                    connect_visa=mock.Mock(),
                )
                adapter = DriverAdapter(
                    registry.registration(driver_id),
                    _config(driver_id, "not-a-visa-address"),
                    SimpleNamespace(logic=logic),
                )
                self.assertIs(adapter.startup_connect(), True)
                logic.connect_visa.assert_called_once_with("not-a-visa-address")

        keithley = SimpleNamespace(
            is_connected=False,
            connect_visa=mock.Mock(),
        )
        adapter = DriverAdapter(
            registry.registration("keithley24xx"),
            _config("keithley24xx", ""),
            keithley,
        )
        self.assertIsNone(adapter.startup_connect())
        keithley.connect_visa.assert_called_once_with("")

    def test_four9_parses_host_port_and_keeps_driver_timeout(self):
        registration = build_default_registry().registration("four9")
        hardware = SimpleNamespace(
            host="old-host",
            port=5050,
            socket_timeout_s=17.5,
        )
        logic = SimpleNamespace(
            hardware=hardware,
            host="old-host",
            port=5050,
            socket_timeout_s=17.5,
        )
        instance = SimpleNamespace(
            logic=logic,
            host_lineEdit=SimpleNamespace(setText=mock.Mock()),
            port_spinBox=SimpleNamespace(setValue=mock.Mock()),
        )

        registration.configure_instance(
            instance, {"address": "127.0.0.1:5051"}
        )

        self.assertEqual((logic.host, logic.port), ("127.0.0.1", 5051))
        self.assertEqual((hardware.host, hardware.port), ("127.0.0.1", 5051))
        self.assertEqual(logic.socket_timeout_s, 17.5)
        self.assertEqual(hardware.socket_timeout_s, 17.5)

    def test_four9_malformed_endpoint_remains_editable_with_existing_port(self):
        registration = build_default_registry().registration("four9")
        hardware = SimpleNamespace(host="old-host", port=5050)
        logic = SimpleNamespace(hardware=hardware, host="old-host", port=5050)
        host_edit = SimpleNamespace(setText=mock.Mock())
        port_edit = SimpleNamespace(setValue=mock.Mock())
        instance = SimpleNamespace(
            logic=logic,
            host_lineEdit=host_edit,
            port_spinBox=port_edit,
        )

        registration.configure_instance(instance, {"address": "bad:port"})

        self.assertEqual((logic.host, logic.port), ("bad:port", 5050))
        self.assertEqual((hardware.host, hardware.port), ("bad:port", 5050))
        host_edit.setText.assert_called_once_with("bad:port")
        port_edit.setValue.assert_called_once_with(5050)

    def test_opticool_and_tlpm_ignore_blank_address_on_startup(self):
        registry = build_default_registry()
        opticool = SimpleNamespace(
            logic=SimpleNamespace(is_connected=False),
            _start_logic_job=mock.Mock(return_value=True),
        )
        opticool_adapter = DriverAdapter(
            registry.registration("opticool"),
            _config("opticool", ""),
            opticool,
        )
        self.assertIsNone(opticool_adapter.startup_connect())
        opticool._start_logic_job.assert_called_once_with("connect")

        tlpm = SimpleNamespace(
            logic=SimpleNamespace(is_connected=False),
            connect=mock.Mock(return_value=True),
        )
        tlpm_adapter = DriverAdapter(
            registry.registration("tlpm"),
            _config("tlpm", ""),
            tlpm,
        )
        self.assertIsNone(tlpm_adapter.startup_connect())
        tlpm.connect.assert_called_once_with()


class GenericAddressManagerTests(unittest.TestCase):
    def test_invalid_connection_mapping_skips_only_that_panel(self):
        registration = DriverRegistration(
            config_spec=DriverConfigSpec(
                driver_id="driver",
                connection_fields={"address": ConnectionFieldSpec((str,))},
            ),
            factory=lambda: SimpleNamespace(),
            terminate=lambda _instance: None,
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())

        snapshot = manager.load_profile(
            _profile(
                _config(
                    "driver",
                    device_id="bad",
                    connect_on_start=False,
                    connection={"old_port": 5050},
                ),
                _config("driver", "usable", device_id="good", connect_on_start=False),
            )
        )

        self.assertEqual(tuple(snapshot.equipment), ("good",))
        self.assertEqual(
            tuple(result.status for result in manager.startup_report.results),
            (
                StartupDeviceStatus.CONSTRUCTION_SKIPPED,
                StartupDeviceStatus.READY,
            ),
        )
        self.assertTrue(manager.teardown_all().succeeded)

    def test_connection_failure_keeps_panel_and_unknown_driver_is_fatal(self):
        instance = SimpleNamespace()
        registration = DriverRegistration(
            config_spec=DriverConfigSpec(
                driver_id="driver",
                connection_fields={"address": ConnectionFieldSpec((str,))},
            ),
            factory=lambda: instance,
            startup_connect=lambda *_args: (_ for _ in ()).throw(
                RuntimeError("bad address")
            ),
            terminate=lambda _instance: None,
        )
        manager = DeviceManager(DriverRegistry((registration,)), SimpleNamespace())
        snapshot = manager.load_profile(_profile(_config("driver", "bad address")))

        report = manager.request_startup_connections()

        self.assertIs(snapshot.equipment["driver"], instance)
        self.assertIs(
            report.results[0].status,
            StartupDeviceStatus.CONNECTION_FAILED,
        )
        self.assertEqual(tuple(manager.snapshot().equipment), ("driver",))
        self.assertTrue(manager.teardown_all().succeeded)

        unknown_manager = DeviceManager(
            DriverRegistry((registration,)), SimpleNamespace()
        )
        with self.assertRaises(UnknownDriverError):
            unknown_manager.load_profile(_profile(_config("unknown", "")))


if __name__ == "__main__":
    unittest.main()
