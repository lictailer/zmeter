"""Reviewed lazy registrations for non-mock device integrations.

This module intentionally imports no device package.  Factories resolve their
widget class only when an enabled profile entry is constructed.
"""

from __future__ import annotations

from importlib import import_module
from typing import Callable, Mapping

from .models import ConnectionFieldSpec, DriverConfigSpec
from .registry import DriverRegistration


def _widget_factory(
    module_name: str,
    class_name: str,
    *,
    runtime_service: str | None = None,
    constructor_keyword: str | None = None,
) -> Callable[..., object]:
    def create(**runtime_services):
        widget_class = getattr(import_module(module_name), class_name)
        if runtime_service is None:
            return widget_class()
        return widget_class(
            **{constructor_keyword: runtime_services[runtime_service]}
        )

    create.__name__ = f"create_{module_name.rsplit('.', 1)[-1]}"
    return create


def _required_text() -> ConnectionFieldSpec:
    return ConnectionFieldSpec((str,), required=True)


def _positive_integer(value: object, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _nonnegative_number(value: object, field_name: str) -> float:
    if type(value) not in (int, float) or value < 0:
        raise ValueError(f"{field_name} must be a nonnegative number")
    return float(value)


def _required_connection_text(connection: Mapping[str, object], field: str) -> str:
    value = str(connection[field]).strip()
    if not value:
        raise ValueError(f"connection field '{field}' must not be empty")
    return value


def _call(instance, method_name: str):
    return getattr(instance, method_name)()


def _call_logic(instance, method_name: str):
    return getattr(instance.logic, method_name)()


def _prefill_text(instance, widget_name: str, connection, field: str) -> None:
    getattr(instance, widget_name).setText(
        _required_connection_text(connection, field)
    )


def _prefill_combo(instance, widget_name: str, connection, field: str) -> None:
    combo_box = getattr(instance, widget_name)
    value = _required_connection_text(connection, field)
    if combo_box.findText(value) < 0:
        combo_box.addItem(value)
    combo_box.setCurrentText(value)


def _terminate_with_true_result(instance, method_name: str):
    result = _call(instance, method_name)
    if result is False:
        raise RuntimeError(f"{type(instance).__name__}.{method_name} did not finish")
    return result


def _terminate_logic_with_true_result(instance, method_name: str):
    result = _call_logic(instance, method_name)
    if result is False:
        raise RuntimeError(
            f"{type(instance.logic).__name__}.{method_name} did not finish"
        )
    return result


def _logic_flag(instance, name: str) -> bool:
    return bool(getattr(instance.logic, name))


def _ni6423_connected(instance) -> bool:
    return _logic_flag(instance, "is_initialized")


def _ni_startup_connect(instance, connection, _timeout_ms: int) -> bool:
    instance.connect(_required_connection_text(connection, "device_name"))
    return _logic_flag(instance, "is_initialized")


def ni6423_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="ni6423",
            connection_fields={"device_name": _required_text()},
        ),
        factory=_widget_factory("devices.ni6423.ni6423_main", "NI6423"),
        configure_instance=lambda instance, connection: _prefill_text(
            instance, "dev_name_lineEdit", connection, "device_name"
        ),
        startup_connect=_ni_startup_connect,
        disconnect=lambda instance: _call_logic(instance, "close"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        terminate=lambda instance: _call_logic(instance, "close"),
        is_connected=_ni6423_connected,
    )


def nidaq_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="nidaq",
            connection_fields={"device_name": _required_text()},
        ),
        factory=_widget_factory("devices.nidaq.nidaq_main", "NIDAQ"),
        configure_instance=lambda instance, connection: _prefill_text(
            instance, "dev_name_lineEdit", connection, "device_name"
        ),
        startup_connect=_ni_startup_connect,
        disconnect=lambda instance: _call_logic(instance, "close"),
        terminate=lambda instance: _call_logic(instance, "close"),
        is_connected=lambda instance: _logic_flag(instance, "is_initialized"),
    )


def _pem100_connect(instance, connection, timeout_ms: int) -> bool:
    address = _required_connection_text(connection, "address")
    configured_timeout = _positive_integer(
        connection.get("timeout_ms", timeout_ms), "timeout_ms"
    )
    return instance.connect(address, timeout_ms=configured_timeout) is True


def pem100_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="pem100",
            connection_fields={
                "address": _required_text(),
                "timeout_ms": ConnectionFieldSpec((int,)),
            },
        ),
        factory=_widget_factory(
            "devices.pem100.pem100_main",
            "PEM100",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        connect=_pem100_connect,
        startup_connect=_pem100_connect,
        connect_timeout_ms=20_000,
        disconnect=lambda instance: _call(instance, "disconnect"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _terminate_with_true_result(
            instance, "terminate_dev"
        ),
        is_connected=lambda instance: bool(instance.logic.connected),
    )


def _sp150_connect(instance, connection, timeout_ms: int) -> bool:
    address = _required_connection_text(connection, "address")
    configured_timeout = _positive_integer(
        connection.get("timeout_ms", timeout_ms), "timeout_ms"
    )
    query_delay_s = _nonnegative_number(
        connection.get("query_delay_s", 1.0), "query_delay_s"
    )
    return (
        instance.connect(
            address,
            timeout_ms=configured_timeout,
            query_delay_s=query_delay_s,
        )
        is True
    )


def sp150_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="sp150",
            connection_fields={
                "address": _required_text(),
                "timeout_ms": ConnectionFieldSpec((int,)),
                "query_delay_s": ConnectionFieldSpec((int, float)),
            },
        ),
        factory=_widget_factory(
            "devices.sp150.sp150_main",
            "SP150",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        connect=_sp150_connect,
        startup_connect=_sp150_connect,
        connect_timeout_ms=10_000,
        disconnect=lambda instance: _call(instance, "disconnect"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _terminate_with_true_result(
            instance, "terminate_dev"
        ),
        is_connected=lambda instance: bool(instance.logic.connected),
    )


def _visa_logic_connect(instance, connection, _timeout_ms: int) -> bool:
    address = _required_connection_text(connection, "address")
    result = instance.logic.connect_visa(address)
    if result is False:
        return False
    return bool(
        getattr(instance.logic, "connected", getattr(instance.logic, "_connected", False))
    )


def hp34401a_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="hp34401a",
            connection_fields={"address": _required_text()},
        ),
        factory=_widget_factory(
            "devices.hp34401a.hp34401a_main",
            "HP34401A",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_comboBox", connection, "address"
        ),
        connect=_visa_logic_connect,
        startup_connect=_visa_logic_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        terminate=lambda instance: _call_logic(instance, "disconnect"),
        is_connected=lambda instance: bool(instance.logic._connected),
    )


def _terminate_keithley24xx(instance):
    logic = instance.logic
    logic.force_stop = True
    if logic.isRunning() and not logic.wait(2_000):
        raise RuntimeError("Keithley24xx operation did not stop within 2000 ms")
    logic.close()
    instance.is_connected = False


def _keithley_startup_connect(instance, connection, _timeout_ms: int) -> None:
    instance.connect_visa(_required_connection_text(connection, "address"))


def keithley24xx_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="keithley24xx",
            connection_fields={"address": _required_text()},
        ),
        factory=_widget_factory(
            "devices.keithley24xx.keithley24xx_main",
            "Keithley24xx",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_cb", connection, "address"
        ),
        startup_connect=_keithley_startup_connect,
        disconnect=_terminate_keithley24xx,
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=_terminate_keithley24xx,
        is_connected=lambda instance: bool(instance.is_connected),
    )


def sr860_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="sr860",
            connection_fields={"address": _required_text()},
        ),
        factory=_widget_factory(
            "devices.sr860.sr860_main",
            "SR860",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_cb", connection, "address"
        ),
        connect=_visa_logic_connect,
        startup_connect=_visa_logic_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        terminate=lambda instance: _call_logic(instance, "disconnect"),
        is_connected=lambda instance: bool(instance.logic.connected),
    )


def sr830_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="sr830",
            connection_fields={"address": _required_text()},
        ),
        factory=_widget_factory(
            "devices.sr830.sr830_main",
            "SR830",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_cb", connection, "address"
        ),
        connect=_visa_logic_connect,
        startup_connect=_visa_logic_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _call_logic(instance, "disconnect"),
        is_connected=lambda instance: bool(instance.logic.connected),
    )


def _demo_connect(instance, connection, _timeout_ms: int) -> bool:
    address = _required_connection_text(connection, "address")
    instance.logic.connect_visa(address)
    return bool(instance.logic.connected)


def demo_device_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="demo_device",
            connection_fields={"address": _required_text()},
        ),
        # Deliberately do not inject RuntimeServices.visa: the demo keeps its
        # private DummyResourceManager and must never become a real VISA driver.
        factory=_widget_factory("devices.demoDevice.demoDevice_main", "DemoDevice"),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_comboBox", connection, "address"
        ),
        connect=_demo_connect,
        startup_connect=_demo_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        terminate=lambda instance: _call_logic(instance, "disconnect"),
        is_connected=lambda instance: bool(instance.logic.connected),
    )


def bbd30x_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="bbd30x",
            connection_fields={"serial": _required_text()},
        ),
        factory=_widget_factory(
            "devices.BBD30X.BBD30X_main",
            "BBD30X",
            runtime_service="kinesis",
            constructor_keyword="kinesis_runtime",
        ),
        runtime_services=("kinesis",),
        configure_instance=lambda instance, connection: _prefill_text(
            instance, "serial_lineEdit", connection, "serial"
        ),
        startup_connect=lambda instance, connection, _timeout_ms: (
            None
            if instance.connect(_required_connection_text(connection, "serial"))
            else False
        ),
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _terminate_logic_with_true_result(
            instance, "terminate_dev"
        ),
        is_connected=lambda instance: bool(instance.logic.is_connected),
    )


def k10cr1_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="k10cr1",
            connection_fields={"serial": _required_text()},
        ),
        factory=_widget_factory(
            "devices.k10cr1.k10cr1_main",
            "K10CR1",
            runtime_service="kinesis",
            constructor_keyword="kinesis_runtime",
        ),
        runtime_services=("kinesis",),
        configure_instance=lambda instance, connection: _prefill_text(
            instance, "lineEdit", connection, "serial"
        ),
        startup_connect=lambda instance, connection, _timeout_ms: (
            instance.connect(_required_connection_text(connection, "serial"))
        ),
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _call(instance, "terminate_dev"),
        is_connected=lambda instance: bool(instance.logic.is_connected),
    )


def phase1_device_registrations() -> tuple[DriverRegistration, ...]:
    """Return Phase 1 registrations in the roadmap's review order."""

    return (
        ni6423_registration(),
        nidaq_registration(),
        pem100_registration(),
        sp150_registration(),
        hp34401a_registration(),
        keithley24xx_registration(),
        sr860_registration(),
        sr830_registration(),
        demo_device_registration(),
        bbd30x_registration(),
        k10cr1_registration(),
    )
