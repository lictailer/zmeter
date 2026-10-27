from __future__ import annotations

import inspect
import importlib
import os
import sys
import types
import unittest
from dataclasses import replace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from devices.mc2000b.mc2000b_hardware import (
    MC2000BConnectionError,
    MC2000BHardware,
    MC2000BProtocolError,
)

try:
    from core.device_management.models import ChannelFilters, DeviceConfig
    from core.device_management.registry import DriverAdapter, build_default_registry
except ImportError:
    ChannelFilters = DeviceConfig = DriverAdapter = build_default_registry = None

try:
    from PyQt6 import QtWidgets
except ImportError:
    QtWidgets = None
    MC2000BLogic = None
    MC2000B = None
else:
    from devices.mc2000b.mc2000b_logic import MC2000BLogic
    from devices.mc2000b.mc2000b_main import MC2000B


class FakeSerial:
    def __init__(self, *, identity="THORLABS MC2000B Optical Chopper vers 4.17", **settings):
        self.settings = settings
        self.identity = identity
        self.frequency = 100
        self.blade_index = 6
        self.reference_input = 0
        self.phase = 0
        self.enabled = False
        self.writes = []
        self.closed = False
        self._incoming = bytearray(b"> ")
        self.next_response = None
        self.input_resets = 0

    def reset_input_buffer(self):
        self._incoming.clear()
        self.input_resets += 1

    def write(self, payload):
        self.writes.append(bytes(payload))
        command = bytes(payload).decode("ascii").rstrip("\r")
        response = self._response(command)
        self._incoming.extend(f"{command}\r{response}\r> ".encode("ascii"))
        return len(payload)

    def flush(self):
        return None

    def read(self, size=1):
        if not self._incoming:
            return b""
        chunk = bytes(self._incoming[:size])
        del self._incoming[:size]
        return chunk

    def close(self):
        self.closed = True

    def _response(self, command):
        if command and self.next_response is not None:
            response = self.next_response
            self.next_response = None
            return response
        if command == "":
            return "CMD_NOT_DEFINED"
        if command == "id?":
            return self.identity
        if command == "freq?":
            return str(self.frequency)
        if command == "blade?":
            return str(self.blade_index)
        if command == "ref?":
            return str(self.reference_input)
        if command == "phase?":
            return str(self.phase)
        if command == "enable?":
            return str(int(self.enabled))
        if command.startswith("freq="):
            self.frequency = int(command.partition("=")[2])
            return ""
        if command.startswith("ref="):
            self.reference_input = int(command.partition("=")[2])
            return ""
        if command.startswith("phase="):
            self.phase = int(command.partition("=")[2])
            return ""
        if command.startswith("enable="):
            self.enabled = bool(int(command.partition("=")[2]))
            return ""
        return "CMD_NOT_DEFINED"


class MC2000BHardwareTests(unittest.TestCase):
    def setUp(self):
        self.created = []

        def factory(**settings):
            serial_port = FakeSerial(**settings)
            self.created.append(serial_port)
            return serial_port

        self.hardware = MC2000BHardware(serial_factory=factory, timeout_s=0.2)

    def test_construction_is_side_effect_free_and_connect_is_explicit(self):
        self.assertEqual(self.created, [])

        self.assertTrue(self.hardware.connect("COM17"))

        self.assertEqual(len(self.created), 1)
        serial_port = self.created[0]
        self.assertEqual(
            serial_port.settings,
            {
                "port": "COM17",
                "baudrate": 115200,
                "bytesize": 8,
                "parity": "N",
                "stopbits": 1,
                "timeout": 0.2,
                "write_timeout": 0.2,
                "xonxoff": False,
                "rtscts": False,
                "dsrdtr": False,
            },
        )
        self.assertEqual(serial_port.input_resets, 1)
        self.assertEqual(serial_port.writes, [b"id?\r"])
        self.assertEqual(
            self.hardware.identity,
            "THORLABS MC2000B Optical Chopper vers 4.17",
        )

    def test_set_and_get_use_reviewed_commands(self):
        self.hardware.connect("COM17")
        serial_port = self.created[0]

        self.assertEqual(self.hardware.set_frequency(321), 321)
        self.assertEqual(self.hardware.get_frequency(), 321)
        self.assertEqual(self.hardware.set_phase(47), 47)
        self.assertEqual(self.hardware.get_phase(), 47)

        self.assertEqual(
            serial_port.writes,
            [
                b"id?\r",
                b"freq=321\r",
                b"freq?\r",
                b"phase=47\r",
                b"phase?\r",
            ],
        )

    def test_invalid_values_are_rejected_before_serial_write(self):
        self.hardware.connect("COM17")
        serial_port = self.created[0]
        writes_before = list(serial_port.writes)

        invalid_calls = (
            (self.hardware.set_frequency, 0),
            (self.hardware.set_frequency, 10001),
            (self.hardware.set_frequency, 10.5),
            (self.hardware.set_phase, -1),
            (self.hardware.set_phase, 361),
            (self.hardware.set_phase, float("nan")),
        )
        for operation, value in invalid_calls:
            with self.subTest(operation=operation.__name__, value=value):
                with self.assertRaises((TypeError, ValueError)):
                    operation(value)
        self.assertEqual(serial_port.writes, writes_before)

    def test_enable_commands_and_readback(self):
        self.hardware.connect("COM17")
        serial_port = self.created[0]

        self.assertIs(self.hardware.get_enabled(), False)
        self.hardware.set_enabled(True)
        self.assertIs(self.hardware.get_enabled(), True)
        self.hardware.set_enabled(False)
        self.assertIs(self.hardware.get_enabled(), False)
        self.assertEqual(
            serial_port.writes[-5:],
            [b"enable?\r", b"enable=1\r", b"enable?\r",
             b"enable=0\r", b"enable?\r"],
        )

    def test_native_inner_outer_reference_selection_requires_standby(self):
        self.hardware.connect("COM17")
        port = self.created[0]
        self.assertEqual(self.hardware.get_blade_index(), 6)
        self.assertEqual(self.hardware.get_reference_input(), 0)
        self.assertEqual(self.hardware.select_internal_reference(1), 1)
        self.assertEqual(self.hardware.get_reference_input(), 1)
        self.assertEqual(self.hardware.select_internal_reference(0), 0)
        self.assertEqual(port.writes.count(b"ref=1\r"), 1)
        self.assertEqual(port.writes.count(b"ref=0\r"), 1)
        self.assertNotIn(b"output=1\r", port.writes)
        self.assertNotIn(b"output=2\r", port.writes)
        self.assertFalse(any(write.startswith(b"freq=") for write in port.writes))

        self.hardware.set_enabled(True)
        before = list(port.writes)
        with self.assertRaisesRegex(Exception, "requires standby"):
            self.hardware.select_internal_reference(1)
        self.assertNotIn(b"ref=1\r", port.writes[len(before):])
        self.assertTrue(port.enabled)

    def test_reference_selection_refuses_other_blade_and_bad_input(self):
        self.hardware.connect("COM17")
        port = self.created[0]
        before = list(port.writes)
        for value in (2, -1, True, 1.0, "1"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.hardware.select_internal_reference(value)
        self.assertEqual(port.writes, before)
        port.blade_index = 1
        with self.assertRaisesRegex(Exception, "not MC1F10HP"):
            self.hardware.select_internal_reference(1)
        self.assertNotIn(b"ref=1\r", port.writes)

    def test_reference_selection_requires_confirmed_readback(self):
        class IgnoringReferenceSerial(FakeSerial):
            def _response(self, command):
                if command == "ref=1":
                    return ""
                return super()._response(command)

        port = IgnoringReferenceSerial()
        hardware = MC2000BHardware(serial_factory=lambda **_settings: port)
        hardware.connect("COM17")
        with self.assertRaisesRegex(MC2000BProtocolError, "did not confirm"):
            hardware.select_internal_reference(1)
        self.assertEqual(port.writes.count(b"ref=1\r"), 1)
        self.assertNotIn(b"enable=0\r", port.writes)
        self.assertNotIn(b"output=2\r", port.writes)

    def test_invalid_enable_response_is_not_reported_as_a_known_state(self):
        self.hardware.connect("COM17")
        serial_port = self.created[0]
        serial_port.next_response = "2"
        with self.assertRaisesRegex(MC2000BProtocolError, "expected 0 or 1"):
            self.hardware.get_enabled()
        with self.assertRaises(TypeError):
            self.hardware.set_enabled(1)

    def test_device_error_and_invalid_query_are_visible(self):
        self.hardware.connect("COM17")
        serial_port = self.created[0]
        serial_port.next_response = "ERROR: OUT OF RANGE"
        with self.assertRaisesRegex(MC2000BProtocolError, "rejected"):
            self.hardware.set_frequency(400)

        serial_port.next_response = "not-a-number"
        with self.assertRaisesRegex(MC2000BProtocolError, "frequency response"):
            self.hardware.get_frequency()

    def test_wrong_identity_closes_the_port(self):
        created = []

        def factory(**settings):
            serial_port = FakeSerial(identity="SOME OTHER DEVICE", **settings)
            created.append(serial_port)
            return serial_port

        hardware = MC2000BHardware(serial_factory=factory)
        with self.assertRaisesRegex(MC2000BConnectionError, "did not identify"):
            hardware.connect("COM18")
        self.assertTrue(created[0].closed)
        self.assertFalse(hardware.connected)

    def test_disconnect_is_idempotent(self):
        self.hardware.connect("COM17")
        serial_port = self.created[0]
        self.hardware.disconnect()
        self.hardware.disconnect()
        self.assertTrue(serial_port.closed)
        self.assertFalse(self.hardware.connected)


@unittest.skipIf(QtWidgets is not None, "real Qt tests cover the logic")
class MC2000BLogicWithoutQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Signal:
            def __init__(self):
                self.receivers = []

            def connect(self, receiver):
                self.receivers.append(receiver)

            def emit(self, *args):
                for receiver in self.receivers:
                    receiver(*args)

        class SignalDescriptor:
            def __set_name__(self, owner, name):
                self.name = name

            def __get__(self, instance, owner):
                if instance is None:
                    return self
                return instance.__dict__.setdefault(self.name, Signal())

        class Thread:
            def __init__(self):
                pass

            def isRunning(self):
                return False

            def wait(self, _milliseconds):
                return True

            def start(self):
                self.run()

        qtcore = types.ModuleType("PyQt6.QtCore")
        qtcore.QThread = Thread
        qtcore.pyqtSignal = lambda *_args: SignalDescriptor()
        qt = types.ModuleType("PyQt6")
        qt.QtCore = qtcore
        module_name = "devices.mc2000b.mc2000b_logic"
        with mock.patch.dict(sys.modules, {"PyQt6": qt, "PyQt6.QtCore": qtcore}):
            cls.logic_module = importlib.import_module(module_name)
        sys.modules.pop(module_name, None)

    def test_reference_action_is_explicit_and_not_a_scan_setter(self):
        port = FakeSerial()
        hardware = MC2000BHardware(serial_factory=lambda **_settings: port)
        logic = self.logic_module.MC2000BLogic(hardware=hardware)
        blades, references, frequencies = [], [], []
        logic.sig_blade_index.connect(blades.append)
        logic.sig_reference_input.connect(references.append)
        logic.sig_frequency.connect(frequencies.append)
        logic.connect("COM17")
        self.assertEqual((blades[-1], references[-1]), (6, 0))
        self.assertEqual(
            {name for name in dir(logic) if name.startswith("set_")},
            {"set_frequency", "set_phase"},
        )
        logic.start_chopper()
        with self.assertRaisesRegex(Exception, "requires standby"):
            logic.select_internal_reference(1)
        self.assertNotIn(b"ref=1\r", port.writes)
        logic.stop_chopper()
        self.assertEqual(logic.select_internal_reference(1), 1)
        self.assertEqual(references[-1], 1)
        self.assertIsNone(frequencies[-1])
        self.assertEqual(logic.get_frequency(), 100)
        logic.disconnect()


@unittest.skipIf(
    QtWidgets is None or build_default_registry is None,
    "PyQt6 or ZMeter registry dependencies are unavailable",
)
class MC2000BLogicAndRegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_scan_channel_signatures_are_exact(self):
        logic = MC2000BLogic(hardware=mock.Mock())
        self.assertEqual(len(inspect.signature(logic.set_frequency).parameters), 1)
        self.assertEqual(len(inspect.signature(logic.get_frequency).parameters), 0)
        self.assertEqual(len(inspect.signature(logic.set_phase).parameters), 1)
        self.assertEqual(len(inspect.signature(logic.get_phase).parameters), 0)

    def test_logic_reads_run_state_on_connect_and_verifies_start_stop(self):
        serial_port = FakeSerial()
        hardware = MC2000BHardware(serial_factory=lambda **_settings: serial_port)
        logic = MC2000BLogic(hardware=hardware)
        states = []
        logic.sig_enabled.connect(states.append)

        self.assertTrue(logic.connect("COM17"))
        self.assertEqual(states, [False])
        self.assertEqual(serial_port.writes[-3:], [b"enable?\r", b"blade?\r", b"ref?\r"])
        self.assertTrue(logic.start_chopper())
        self.assertEqual(states[-2:], [None, True])
        self.assertFalse(logic.stop_chopper())
        self.assertEqual(states[-2:], [None, False])
        logic.disconnect()
        self.assertIsNone(states[-1])

    def test_start_rejects_unconfirmed_run_mode(self):
        class IgnoringEnableSerial(FakeSerial):
            def _response(self, command):
                if command == "enable=1":
                    return ""
                return super()._response(command)

        serial_port = IgnoringEnableSerial()
        hardware = MC2000BHardware(serial_factory=lambda **_settings: serial_port)
        logic = MC2000BLogic(hardware=hardware)
        states = []
        logic.sig_enabled.connect(states.append)
        logic.connect("COM17")

        with self.assertRaisesRegex(MC2000BProtocolError, "did not match"):
            logic.start_chopper()
        self.assertEqual(states[-2:], [None, False])
        logic.disconnect()

    def test_scan_lifecycle_does_not_block_panel_commands(self):
        serial_port = FakeSerial()
        hardware = MC2000BHardware(serial_factory=lambda **_settings: serial_port)
        panel = MC2000B(hardware=hardware)
        self.addCleanup(panel.close)
        registration = build_default_registry().registration("mc2000b")
        config = DeviceConfig(
            id="chopper",
            driver="mc2000b",
            enabled=True,
            connect_on_start=False,
            connection={"address": "COM17"},
            scan_channels=ChannelFilters(
                setters=("frequency", "phase"),
                getters=("frequency", "phase"),
            ),
        )
        adapter = DriverAdapter(registration, config, panel)

        self.assertIsNone(adapter.stop_scan())
        self.assertTrue(panel.request_connect("COM17"))
        self.assertTrue(panel.logic.wait(2_000))
        self.assertTrue(hardware.connected)

        self.assertIsNone(adapter.start_scan())
        self.assertTrue(panel.logic.submit_ui_job(panel.logic.start_chopper))
        self.assertTrue(panel.logic.wait(2_000))
        self.assertTrue(serial_port.enabled)
        panel.logic.disconnect()

    def test_old_scan_callbacks_are_harmless_on_current_panel(self):
        """An older registry may still invoke the MC2000B scan hooks."""
        panel = MC2000B(hardware=mock.Mock(connected=False))
        self.addCleanup(panel.close)
        registration = replace(
            build_default_registry().registration("mc2000b"),
            stop_scan=lambda instance: instance.stop_scan(),
            start_scan=lambda instance: instance.start_scan(),
        )
        config = DeviceConfig(
            id="chopper",
            driver="mc2000b",
            enabled=True,
            connect_on_start=False,
            connection={"address": "COM17"},
            scan_channels=ChannelFilters(setters=(), getters=()),
        )
        adapter = DriverAdapter(registration, config, panel)

        self.assertIsNone(adapter.stop_scan())
        self.assertIsNone(adapter.start_scan())
        self.assertFalse(panel.logic.hardware.connected)

    def test_panel_updates_values_from_logic_signals(self):
        panel = MC2000B(hardware=mock.Mock(connected=False))
        self.addCleanup(panel.close)
        panel.frequency_spinBox.setValue(600)
        panel.phase_spinBox.setValue(20)
        panel.logic.sig_frequency.emit(725)
        panel.logic.sig_phase.emit(90)
        self.app.processEvents()
        self.assertEqual(panel.frequency_readback_label.text(), "725 Hz")
        self.assertEqual(panel.phase_readback_label.text(), "90 degrees")
        self.assertEqual(panel.frequency_spinBox.value(), 600)
        self.assertEqual(panel.phase_spinBox.value(), 20)

    def test_panel_reference_selection_is_explicit_and_standby_only(self):
        port = FakeSerial()
        panel = MC2000B(
            hardware=MC2000BHardware(serial_factory=lambda **_settings: port)
        )
        self.addCleanup(panel.close)
        panel.logic.connect("COM17")
        self.assertEqual(panel.blade_readback_label.text(), "MC1F10HP (6)")
        self.assertEqual(panel.reference_input_readback_label.text(), "Internal outer")
        self.assertTrue(panel.set_reference_input_button.isEnabled())
        panel.reference_input_comboBox.setCurrentIndex(1)
        self.assertEqual(panel.logic.select_internal_reference(1), 1)
        self.assertEqual(panel.reference_input_readback_label.text(), "Internal inner")
        self.assertEqual(panel.logic.get_frequency(), 100)
        self.assertNotIn(b"output=2\r", port.writes)
        panel.logic.start_chopper()
        self.assertFalse(panel.set_reference_input_button.isEnabled())
        panel.logic.stop_chopper()
        self.assertTrue(panel.set_reference_input_button.isEnabled())
        panel.logic.disconnect()

    def test_get_updates_only_readback_and_set_clears_old_readback(self):
        serial_port = FakeSerial()
        hardware = MC2000BHardware(serial_factory=lambda **_settings: serial_port)
        panel = MC2000B(hardware=hardware)
        self.addCleanup(panel.close)
        panel.logic.connect("COM17")
        panel.frequency_spinBox.setValue(600)
        panel.phase_spinBox.setValue(20)

        panel.logic.get_frequency()
        panel.logic.get_phase()
        self.assertEqual(panel.frequency_readback_label.text(), "100 Hz")
        self.assertEqual(panel.phase_readback_label.text(), "0 degrees")
        self.assertEqual(panel.frequency_spinBox.value(), 600)
        self.assertEqual(panel.phase_spinBox.value(), 20)

        panel.logic.set_frequency(600)
        panel.logic.set_phase(20)
        self.assertEqual(panel.frequency_readback_label.text(), "—")
        self.assertEqual(panel.phase_readback_label.text(), "—")
        panel.logic.get_frequency()
        panel.logic.get_phase()
        self.assertEqual(panel.frequency_readback_label.text(), "600 Hz")
        self.assertEqual(panel.phase_readback_label.text(), "20 degrees")
        self.assertEqual(panel.frequency_spinBox.value(), 600)
        self.assertEqual(panel.phase_spinBox.value(), 20)

    def test_panel_run_mode_buttons_follow_device_readback(self):
        panel = MC2000B(hardware=mock.Mock(connected=False))
        self.addCleanup(panel.close)
        self.assertFalse(panel.start_button.isEnabled())
        panel._update_connection(True)

        panel.logic.sig_enabled.emit(False)
        self.app.processEvents()
        self.assertEqual(panel.run_state_label.text(), "Standby")
        self.assertTrue(panel.start_button.isEnabled())
        self.assertTrue(panel.stop_button.isEnabled())
        with mock.patch.object(panel.logic, "submit_ui_job") as submit_ui_job:
            panel.start_button.click()
            submit_ui_job.assert_called_once_with(panel.logic.start_chopper)

        panel.logic.sig_enabled.emit(True)
        self.app.processEvents()
        self.assertEqual(panel.run_state_label.text(), "Run mode")
        self.assertFalse(panel.start_button.isEnabled())
        self.assertTrue(panel.stop_button.isEnabled())
        with mock.patch.object(panel.logic, "submit_ui_job") as submit_ui_job:
            panel.stop_button.click()
            submit_ui_job.assert_called_once_with(panel.logic.stop_chopper)

        panel._update_connection(False)
        self.assertEqual(panel.run_state_label.text(), "Not connected")

    def test_connect_button_keeps_typed_address_and_ignores_checked_state(self):
        panel = MC2000B(hardware=mock.Mock(connected=False))
        self.addCleanup(panel.close)
        panel.address_lineEdit.setText("COM3")

        with mock.patch.object(
            panel.logic, "submit_ui_job", return_value=True
        ) as submit_ui_job:
            panel.connect_button.click()

        self.assertEqual(panel.address_lineEdit.text(), "COM3")
        submit_ui_job.assert_called_once_with(panel.logic.connect, "COM3")

    def test_registration_prefills_address_and_uses_pending_startup(self):
        registration = build_default_registry().registration("mc2000b")
        instance = mock.Mock()
        instance.logic.connected = False
        instance.request_connect.return_value = True
        config = DeviceConfig(
            id="chopper",
            driver="mc2000b",
            enabled=True,
            connect_on_start=True,
            connection={"address": "COM17"},
            scan_channels=ChannelFilters(
                setters=("frequency", "phase"),
                getters=("frequency", "phase"),
            ),
        )

        registration.configure_instance(instance, dict(config.connection))
        instance.address_lineEdit.setText.assert_called_once_with("COM17")
        adapter = DriverAdapter(registration, config, instance)
        self.assertIsNone(adapter.startup_connect())
        instance.request_connect.assert_called_once_with("COM17")


if __name__ == "__main__":
    unittest.main()
