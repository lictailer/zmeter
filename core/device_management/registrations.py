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


def _address_spec() -> ConnectionFieldSpec:
    """Return the common, intentionally optional Excel address contract."""

    return ConnectionFieldSpec((str,))


def _connection_address(connection: Mapping[str, object]) -> str:
    """Return the address exactly as configured, including an empty string."""

    return str(connection.get("address", ""))


def _call(instance, method_name: str):
    return getattr(instance, method_name)()


def _call_logic(instance, method_name: str):
    return getattr(instance.logic, method_name)()


def _prefill_text(instance, widget_name: str, connection) -> None:
    getattr(instance, widget_name).setText(_connection_address(connection))


def _prefill_combo(instance, widget_name: str, connection) -> None:
    combo_box = getattr(instance, widget_name)
    value = _connection_address(connection)
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
    instance.connect(_connection_address(connection))
    return _logic_flag(instance, "is_initialized")


def ni6423_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="ni6423",
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory("devices.ni6423.ni6423_main", "NI6423"),
        configure_instance=lambda instance, connection: _prefill_text(
            instance, "dev_name_lineEdit", connection
        ),
        startup_connect=_ni_startup_connect,
        disconnect=lambda instance: _call_logic(instance, "close"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _call_logic(instance, "close"),
        is_busy=lambda instance: instance.logic.lifecycle_busy(),
        is_connected=_ni6423_connected,
    )


def nidaq_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="nidaq",
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory("devices.nidaq.nidaq_main", "NIDAQ"),
        configure_instance=lambda instance, connection: _prefill_text(
            instance, "dev_name_lineEdit", connection
        ),
        startup_connect=_ni_startup_connect,
        disconnect=lambda instance: _call_logic(instance, "close"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _call_logic(instance, "close"),
        is_busy=lambda instance: instance.logic.isRunning(),
        is_connected=lambda instance: _logic_flag(instance, "is_initialized"),
    )


def _pem100_connect(instance, connection, _timeout_ms: int) -> bool:
    return instance.connect(_connection_address(connection)) is True


def pem100_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="pem100",
            connection_fields={"address": _address_spec()},
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
        disconnect=lambda instance: _call(instance, "disconnect"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _terminate_with_true_result(
            instance, "terminate_dev"
        ),
        is_connected=lambda instance: bool(instance.logic.connected),
    )


def _sp150_connect(instance, connection, _timeout_ms: int) -> bool:
    return instance.connect(_connection_address(connection)) is True


def sp150_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="sp150",
            connection_fields={"address": _address_spec()},
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
    address = _connection_address(connection)
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
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory(
            "devices.hp34401a.hp34401a_main",
            "HP34401A",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_comboBox", connection
        ),
        connect=_visa_logic_connect,
        startup_connect=_visa_logic_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _call_logic(instance, "disconnect"),
        is_busy=lambda instance: instance.logic.isRunning(),
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
    instance.connect_visa(_connection_address(connection))


def keithley24xx_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="keithley24xx",
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory(
            "devices.keithley24xx.keithley24xx_main",
            "Keithley24xx",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_cb", connection
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
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory(
            "devices.sr860.sr860_main",
            "SR860",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_cb", connection
        ),
        connect=_visa_logic_connect,
        startup_connect=_visa_logic_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _call_logic(instance, "disconnect"),
        is_busy=lambda instance: instance.logic.isRunning(),
        is_connected=lambda instance: bool(instance.logic.connected),
    )


def mfli_registration() -> DriverRegistration:
    """Startup-only Zurich client with worker-owned I/O and scalar scan channels."""
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="mfli", connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory("devices.mfli.MFLI_main", "MFLI"),
        configure_instance=lambda instance, connection: instance.configure_address(
            _connection_address(connection)
        ),
        connect=lambda instance, connection, timeout: instance.connect(
            _connection_address(connection), timeout
        ),
        startup_connect=lambda instance, connection, timeout: instance.startup_connect(
            _connection_address(connection), timeout
        ),
        disconnect=lambda instance: instance.disconnect(),
        start_scan=lambda instance: instance.start_scan(),
        stop_scan=lambda instance: instance.stop_scan(),
        force_stop=lambda instance: instance.force_stop(),
        terminate=lambda instance: _terminate_with_true_result(instance, "terminate_dev"),
        close_widget=lambda instance: instance.close_managed(),
        is_busy=lambda instance: instance.logic.lifecycle_busy(),
        is_connected=lambda instance: instance.logic.connected,
    )


def sr830_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="sr830",
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory(
            "devices.sr830.sr830_main",
            "SR830",
            runtime_service="visa",
            constructor_keyword="visa_runtime",
        ),
        runtime_services=("visa",),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_cb", connection
        ),
        connect=_visa_logic_connect,
        startup_connect=_visa_logic_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _call_logic(instance, "disconnect"),
        is_busy=lambda instance: instance.logic.isRunning(),
        is_connected=lambda instance: bool(instance.logic.connected),
    )


def _demo_connect(instance, connection, _timeout_ms: int) -> bool:
    address = _connection_address(connection)
    instance.logic.connect_visa(address)
    return bool(instance.logic.connected)


def demo_device_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="demo_device",
            connection_fields={"address": _address_spec()},
        ),
        # Deliberately do not inject RuntimeServices.visa: the demo keeps its
        # private DummyResourceManager and must never become a real VISA driver.
        factory=_widget_factory("devices.demoDevice.demoDevice_main", "DemoDevice"),
        configure_instance=lambda instance, connection: _prefill_combo(
            instance, "address_comboBox", connection
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
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory(
            "devices.BBD30X.BBD30X_main",
            "BBD30X",
            runtime_service="kinesis",
            constructor_keyword="kinesis_runtime",
        ),
        runtime_services=("kinesis",),
        configure_instance=lambda instance, connection: _prefill_text(
            instance, "serial_lineEdit", connection
        ),
        startup_connect=lambda instance, connection, _timeout_ms: (
            None
            if instance.connect(_connection_address(connection))
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
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory(
            "devices.k10cr1.k10cr1_main",
            "K10CR1",
            runtime_service="kinesis",
            constructor_keyword="kinesis_runtime",
        ),
        runtime_services=("kinesis",),
        configure_instance=lambda instance, connection: _prefill_text(
            instance, "lineEdit", connection
        ),
        startup_connect=lambda instance, connection, _timeout_ms: (
            instance.connect(_connection_address(connection))
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


def _configure_four9(instance, connection) -> None:
    address = _connection_address(connection)
    host = address
    port = int(instance.logic.port)
    candidate_host, separator, candidate_port = address.rpartition(":")
    if separator and candidate_host and candidate_port.isdecimal():
        parsed_port = int(candidate_port)
        if 1 <= parsed_port <= 65_535:
            host = candidate_host
            port = parsed_port

    instance.host_lineEdit.setText(host)
    instance.port_spinBox.setValue(port)
    instance.logic.host = host
    instance.logic.port = port
    instance.logic.hardware.host = host
    instance.logic.hardware.port = port


def _four9_startup_connect(instance, _connection, _timeout_ms: int) -> None | bool:
    if not instance._start_logic_job("connect"):
        return False
    return None


def four9_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="four9",
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory("devices.four9.four9_main", "Four9"),
        configure_instance=_configure_four9,
        startup_connect=_four9_startup_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _call(instance, "terminate_dev"),
        is_connected=lambda instance: bool(instance.logic.is_connected),
    )


def _configure_montana2(instance, connection) -> None:
    address = _connection_address(connection)
    if address != "136.167.55.165":
        instance.quickConnect_comboBox.setCurrentText("Other")
    instance.ipaddress_lineEdit.setText(address)
    instance.logic.ipaddress = address


def _montana2_startup_connect(instance, _connection, _timeout_ms: int):
    if instance.logic.isRunning():
        return False
    instance._on_connect_clicked()
    return None


def montana2_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="montana2",
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory("devices.montana2.montana2_main", "Montana2"),
        configure_instance=_configure_montana2,
        startup_connect=_montana2_startup_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        force_stop=lambda instance: setattr(
            instance.logic, "stable_wait_stop", True
        ),
        terminate=lambda instance: _call(instance, "terminate_dev"),
        is_connected=lambda instance: bool(instance.logic.is_connected),
    )


def _pending_widget_connect(instance, _connection, _timeout_ms: int):
    if not instance._start_logic_job("connect"):
        return False
    return None


def opticool_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="opticool",
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory("devices.opticool.opticool_main", "OptiCool"),
        startup_connect=_pending_widget_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        force_stop=lambda instance: _call(instance, "abort_stable_wait"),
        terminate=lambda instance: _call(instance, "terminate_dev"),
        is_connected=lambda instance: bool(instance.logic.is_connected),
    )


def _tlpm_startup_connect(instance, _connection, _timeout_ms: int):
    if not instance.connect():
        return False
    return None


def tlpm_registration() -> DriverRegistration:
    return DriverRegistration(
        config_spec=DriverConfigSpec(
            driver_id="tlpm",
            connection_fields={"address": _address_spec()},
        ),
        factory=_widget_factory("devices.tlpm.tlpm_main", "TLPM"),
        startup_connect=_tlpm_startup_connect,
        disconnect=lambda instance: _call_logic(instance, "disconnect"),
        start_scan=lambda instance: _call(instance, "start_scan"),
        stop_scan=lambda instance: _call(instance, "stop_scan"),
        force_stop=lambda instance: _call(instance, "force_stop"),
        terminate=lambda instance: _terminate_with_true_result(
            instance, "terminate_dev"
        ),
        is_busy=lambda instance: instance.logic.lifecycle_busy(),
        is_connected=lambda instance: bool(instance.logic.is_connected),
    )


def phase2_device_registrations() -> tuple[DriverRegistration, ...]:
    """Return the reviewed Phase 2 startup-only registrations."""

    return (
        four9_registration(),
        montana2_registration(),
        opticool_registration(),
        tlpm_registration(),
    )
