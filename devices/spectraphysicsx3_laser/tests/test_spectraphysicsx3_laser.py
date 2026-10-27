from __future__ import annotations

import os
import importlib
import sys
import types
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from devices.spectraphysicsx3_laser.spectraphysicsx3_laser_hardware import (
    SpectraPhysicsX3Hardware,
    X3ConnectionError,
    X3ProtocolError,
    X3Status,
)

try:
    from core.device_management.registry import build_default_registry
except ImportError:
    build_default_registry = None

try:
    from PyQt6 import QtCore, QtTest, QtWidgets
except ImportError:
    QtWidgets = None
else:
    from devices.spectraphysicsx3_laser.spectraphysicsx3_laser_logic import (
        SpectraPhysicsX3Logic,
        X3OperationCancelled,
    )
    from devices.spectraphysicsx3_laser.spectraphysicsx3_laser_main import (
        HoldButton,
        SpectraPhysicsX3Laser,
    )


class FakeX3Serial:
    def __init__(self, *, minimum=680, maximum=1300, **settings):
        self.settings = settings
        self.minimum = minimum
        self.maximum = maximum
        self.target = minimum
        self.actual = minimum
        self.status = 25 << 16
        self.power_w = 0.0
        self.humidity = 0.3
        self.motor = 13.0
        self.diode_temperature_c = 21.79
        self.diode_current_a = 0.0
        self.diode_hours = 16552.2
        self.warmup_percent = 100.0
        self.mode = "RUN"
        self.shutter_command = 0
        self.status_sequence = []
        self.writes = []
        self.responses = []
        self.actual_sequence = []
        self.closed = False
        self.next_response = None

    def reset_input_buffer(self):
        self.responses.clear()

    def write(self, payload):
        self.writes.append(bytes(payload))
        command = bytes(payload).decode("ascii").rstrip("\r")
        if command.startswith("WAVelength "):
            self.target = int(command.partition(" ")[2])
            return len(payload)
        if command.startswith("SHUTter "):
            self.shutter_command = int(command.partition(" ")[2])
            if self.shutter_command:
                self.status |= 1 << 2
            else:
                self.status &= ~(1 << 2)
            return len(payload)
        if command == "ON":
            self.status |= 1
            return len(payload)
        if command == "OFF":
            self.status &= ~(1 | (1 << 2))
            self.shutter_command = 0
            return len(payload)
        if command.startswith("MODE "):
            self.mode = command.partition(" ")[2]
            return len(payload)
        if self.next_response is not None:
            response = self.next_response
            self.next_response = None
        elif command == "WAVelength:MIN?":
            response = str(self.minimum)
        elif command == "WAVelength:MAX?":
            response = str(self.maximum)
        elif command == "WAVelength?":
            response = str(self.target)
        elif command == "READ:WAVelength?":
            if self.actual_sequence:
                self.actual = self.actual_sequence.pop(0)
            response = str(self.actual)
        elif command == "*STB?":
            if self.status_sequence:
                self.status = self.status_sequence.pop(0)
            response = str(self.status)
        elif command == "SHUTter?":
            response = str(self.shutter_command)
        elif command == "MODE?":
            response = self.mode
        elif command == "READ:POWer?":
            response = str(self.power_w)
        elif command == "READ:HUMidity?":
            response = str(self.humidity)
        elif command == "CONTrol:DSMPOSition?":
            response = str(self.motor)
        elif command == "READ:PLASer:DIODe1:TEMPerature?":
            response = str(self.diode_temperature_c)
        elif command == "READ:PLASer:DIODe1:CURRent?":
            response = str(self.diode_current_a)
        elif command == "READ:PLASer:DIODe1:HOURS?":
            response = str(self.diode_hours)
        elif command == "READ:PCTWarmedup?":
            response = str(self.warmup_percent)
        elif command == "*IDN?":
            response = ""
        else:
            response = "UNKNOWN"
        self.responses.append((response + "\n").encode("ascii") if response else b"")
        return len(payload)

    def flush(self):
        return None

    def readline(self):
        return self.responses.pop(0) if self.responses else b""

    def close(self):
        self.closed = True


class X3HardwareTests(unittest.TestCase):
    def setUp(self):
        self.serials = []

        def factory(**settings):
            serial_port = FakeX3Serial(**settings)
            self.serials.append(serial_port)
            return serial_port

        self.hardware = SpectraPhysicsX3Hardware(
            serial_factory=factory, timeout_s=0.1
        )

    def test_connect_is_explicit_and_read_only(self):
        self.assertEqual(self.serials, [])
        self.hardware.connect("COM4")
        port = self.serials[0]
        self.assertEqual(port.settings["baudrate"], 115200)
        self.assertEqual(port.settings["port"], "COM4")
        self.assertEqual(
            port.writes,
            [
                b"WAVelength:MIN?\r",
                b"WAVelength:MAX?\r",
                b"READ:WAVelength?\r",
                b"*STB?\r",
            ],
        )
        self.assertEqual(self.hardware.min_wavelength_nm, 680)
        self.assertEqual(self.hardware.max_wavelength_nm, 1300)
        self.assertIsNone(self.hardware.read_identity())
        self.hardware.disconnect()
        self.assertTrue(port.closed)
        self.assertFalse(self.hardware.connected)
        self.assertFalse(any(b"SHUT" in item or item == b"ON\r" for item in port.writes))

    def test_invalid_wavelength_never_writes(self):
        self.hardware.connect("COM4")
        port = self.serials[0]
        before = list(port.writes)
        for bad in (679, 1301, 800.5, float("nan"), True, "not a number"):
            with self.subTest(bad=bad):
                with self.assertRaises((TypeError, ValueError)):
                    self.hardware.command_wavelength(bad)
        self.assertEqual(port.writes, before)

    def test_shutter_values_are_strict_and_diagnostics_are_read_only(self):
        self.hardware.connect("COM4")
        port = self.serials[0]
        before = list(port.writes)
        for bad in (-1, 2, 0.5, True, "open", float("nan")):
            with self.subTest(bad=bad):
                with self.assertRaises((TypeError, ValueError)):
                    self.hardware.command_shutter(bad)
        self.assertEqual(port.writes, before)
        self.assertEqual(self.hardware.read_diode_temperature_c(), 21.79)
        self.assertEqual(self.hardware.read_diode_current_a(), 0.0)
        self.assertEqual(self.hardware.read_diode_hours(), 16552.2)
        self.assertEqual(self.hardware.read_warmup_percent(), 100.0)
        self.assertEqual(self.hardware.read_mode(), "RUN")

    def test_bad_limits_close_port(self):
        ports = []

        def factory(**settings):
            port = FakeX3Serial(minimum=200, maximum=1300, **settings)
            ports.append(port)
            return port

        hardware = SpectraPhysicsX3Hardware(serial_factory=factory)
        with self.assertRaisesRegex(X3ConnectionError, "Unexpected X3"):
            hardware.connect("COM8")
        self.assertTrue(ports[0].closed)
        self.assertFalse(hardware.connected)

    def test_empty_and_invalid_response_are_errors(self):
        self.hardware.connect("COM4")
        port = self.serials[0]
        port.next_response = ""
        with self.assertRaisesRegex(X3ProtocolError, "no response"):
            self.hardware.read_actual_wavelength()
        port.next_response = "garbage"
        with self.assertRaisesRegex(X3ProtocolError, "actual wavelength"):
            self.hardware.read_actual_wavelength()

    def test_status_bits_keep_emission_and_shutter_independent(self):
        status = X3Status((50 << 16) | 1 | (1 << 2))
        self.assertTrue(status.emission)
        self.assertTrue(status.shutter_open)
        self.assertEqual(status.state_label, "Run")
        closed = X3Status((50 << 16) | 1)
        self.assertTrue(closed.emission)
        self.assertFalse(closed.shutter_open)
        self.assertTrue(X3Status((25 << 16) | (1 << 15)).fault)

    @unittest.skipIf(build_default_registry is None, "ZMeter GUI dependencies unavailable")
    def test_registry_is_lazy_and_contains_driver(self):
        registration = build_default_registry().registration(
            "spectraphysicsx3_laser"
        )
        self.assertEqual(registration.driver_id, "spectraphysicsx3_laser")
        self.assertEqual(registration.runtime_services, ())
        self.assertFalse(registration.runtime_mutation_allowed)


@unittest.skipIf(QtWidgets is not None, "real Qt tests cover the logic")
class X3LogicWithoutQtTests(unittest.TestCase):
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

            def start(self):
                self.run()

            def wait(self, _milliseconds):
                return True

        qtcore = types.ModuleType("PyQt6.QtCore")
        qtcore.QThread = Thread
        qtcore.pyqtSignal = lambda *_args: SignalDescriptor()
        qt = types.ModuleType("PyQt6")
        qt.QtCore = qtcore
        module_name = (
            "devices.spectraphysicsx3_laser.spectraphysicsx3_laser_logic"
        )
        with mock.patch.dict(sys.modules, {"PyQt6": qt, "PyQt6.QtCore": qtcore}):
            cls.logic_module = importlib.import_module(module_name)
        sys.modules.pop(module_name, None)

    def setUp(self):
        self.port = None

        def factory(**settings):
            self.port = FakeX3Serial(**settings)
            return self.port

        hardware = SpectraPhysicsX3Hardware(serial_factory=factory, timeout_s=0.1)
        self.logic = self.logic_module.SpectraPhysicsX3Logic(
            hardware=hardware, move_timeout_s=0.03,
            poll_interval_s=0.001, stable_reads=2,
        )
        self.logic.connect("COM4")

    def tearDown(self):
        self.logic.terminate_dev()

    def test_scan_move_reads_actual_twice_after_target(self):
        self.port.actual_sequence = [690, 700, 700]
        self.assertEqual(self.logic.set_wavelength_stable(700), 700)
        self.assertEqual(self.logic.get_wavelength_stable(), 700)
        self.assertEqual(self.port.writes.count(b"WAVelength 700\r"), 1)
        self.assertFalse(any(b"SHUT" in write for write in self.port.writes))

    def test_output_power_is_read_only_scan_getter(self):
        self.port.power_w = 1.234
        before = list(self.port.writes)
        self.assertEqual(self.logic.get_output_power_w(), 1.234)
        self.assertEqual(self.port.writes, before + [b"READ:POWer?\r"])
        self.assertFalse(hasattr(self.logic, "set_output_power_w"))

    def test_fault_and_cancel_prevent_writes(self):
        self.port.status |= 1 << 15
        before = list(self.port.writes)
        with self.assertRaisesRegex(RuntimeError, "fault/interlock"):
            self.logic.set_wavelength_stable(700)
        self.assertEqual(self.port.writes.count(b"WAVelength 700\r"), 0)
        self.port.status &= ~(1 << 15)
        self.logic.force_stop()
        with self.assertRaises(self.logic_module.X3OperationCancelled):
            self.logic.set_wavelength_stable(700)
        self.assertEqual(self.port.writes, before + [b"*STB?\r"])

    def test_timeout_does_not_repeat_target_or_change_shutter(self):
        with self.assertRaises(self.logic_module.X3MoveTimeout):
            self.logic.set_wavelength_stable(700)
        self.assertEqual(self.port.writes.count(b"WAVelength 700\r"), 1)
        self.assertFalse(any(b"SHUT" in write for write in self.port.writes))

    def test_shutter_open_requires_emission_and_close_survives_stop(self):
        before = list(self.port.writes)
        with self.assertRaisesRegex(RuntimeError, "diode is off"):
            self.logic.set_shutter(1)
        self.assertNotIn(b"SHUTter 1\r", self.port.writes)
        self.port.status |= 1
        self.assertEqual(self.logic.set_shutter(1), 1)
        self.assertEqual(self.logic.get_shutter(), 1)
        self.logic.force_stop()
        self.assertEqual(self.logic.set_shutter(0), 0)
        self.assertEqual(self.logic.get_shutter(), 0)
        self.assertEqual(self.port.writes.count(b"SHUTter 1\r"), 1)
        self.assertEqual(self.port.writes.count(b"SHUTter 0\r"), 1)
        self.assertGreater(len(self.port.writes), len(before))

    def test_diode_and_mode_are_panel_only_methods(self):
        scan_setters = {
            name[4:] for name in dir(self.logic) if name.startswith("set_")
        }
        self.assertEqual(scan_setters, {"wavelength_stable", "shutter"})
        self.port.warmup_percent = 90.0
        with self.assertRaisesRegex(RuntimeError, "warm-up"):
            self.logic.turn_diode_on()
        self.assertNotIn(b"ON\r", self.port.writes)
        self.port.warmup_percent = 100.0
        self.assertTrue(self.logic.turn_diode_on())
        self.assertEqual(self.logic.select_mode("ALIGN"), "ALIGN")
        self.assertEqual(self.logic.read_mode(), "ALIGN")
        self.assertTrue(self.logic.turn_diode_off())
        self.assertFalse(self.port.status & 1)
        self.assertFalse(self.port.status & (1 << 2))

    def test_disconnect_does_not_change_diode_or_shutter(self):
        self.port.status |= 1 | (1 << 2)
        before = list(self.port.writes)
        self.logic.disconnect()
        self.assertEqual(self.port.writes, before)
        self.assertTrue(self.port.status & 1)
        self.assertTrue(self.port.status & (1 << 2))

    def test_termination_only_releases_port(self):
        self.port.status |= 1 | (1 << 2)
        before = list(self.port.writes)
        self.assertTrue(self.logic.terminate_dev())
        self.assertEqual(self.port.writes, before)
        self.assertTrue(self.port.closed)
        self.assertTrue(self.port.status & 1)
        self.assertTrue(self.port.status & (1 << 2))

    def test_new_panel_hold_action_can_follow_cancelled_scan(self):
        self.logic.force_stop()
        self.assertTrue(self.logic.turn_diode_on())
        self.assertEqual(self.logic.panel_set_shutter(1), 1)
        self.logic.force_stop()
        self.assertEqual(self.logic.select_mode("ALIGN"), "ALIGN")
        self.assertEqual(self.logic.panel_set_shutter(0), 0)

    def test_failed_refresh_after_connect_releases_port(self):
        self.logic.disconnect()

        class DropSecondActual(FakeX3Serial):
            def __init__(self, **settings):
                super().__init__(**settings)
                self.actual_queries = 0

            def write(self, payload):
                if payload == b"READ:WAVelength?\r":
                    self.actual_queries += 1
                    if self.actual_queries == 2:
                        self.next_response = ""
                return super().write(payload)

        ports = []

        def factory(**settings):
            port = DropSecondActual(**settings)
            ports.append(port)
            return port

        hardware = SpectraPhysicsX3Hardware(serial_factory=factory)
        logic = self.logic_module.SpectraPhysicsX3Logic(hardware=hardware)
        with self.assertRaises(X3ProtocolError):
            logic.connect("COM4")
        self.assertTrue(ports[0].closed)
        self.assertFalse(logic.connected)


@unittest.skipIf(QtWidgets is None, "PyQt6 is not installed")
class X3LogicAndPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.port = None

        def factory(**settings):
            self.port = FakeX3Serial(**settings)
            return self.port

        self.hardware = SpectraPhysicsX3Hardware(
            serial_factory=factory, timeout_s=0.1
        )

    def test_setter_waits_for_actual_and_does_not_touch_shutter(self):
        logic = SpectraPhysicsX3Logic(
            hardware=self.hardware, poll_interval_s=0.001, stable_reads=2
        )
        logic.connect("COM4")
        self.port.actual_sequence = [690, 700, 700]
        self.assertEqual(logic.set_wavelength_stable(700), 700)
        self.assertEqual(logic.get_wavelength_stable(), 700)
        self.assertEqual(self.port.writes.count(b"WAVelength 700\r"), 1)
        self.assertFalse(any(b"SHUT" in item for item in self.port.writes))
        logic.terminate_dev()

    def test_stop_cancels_without_serial_control_command(self):
        logic = SpectraPhysicsX3Logic(hardware=self.hardware)
        logic.connect("COM4")
        before = list(self.port.writes)
        logic.force_stop()
        with self.assertRaises(X3OperationCancelled):
            logic.set_wavelength_stable(700)
        self.assertEqual(self.port.writes, before)
        logic.terminate_dev()

    def test_panel_keeps_input_and_readback_separate(self):
        panel = SpectraPhysicsX3Laser(hardware=self.hardware)
        self.assertFalse(self.hardware.connected)
        panel.connect("COM4")
        panel.target_spinBox.setValue(900)
        panel.logic.get_target_wavelength()
        self.assertEqual(panel.target_spinBox.value(), 900)
        self.assertEqual(panel.target_readback_label.text(), "680 nm")
        self.assertIn("680 nm", panel.actual_wavelength_label.text())
        self.assertEqual(panel.emission_label.text(), "Off")
        self.assertEqual(panel.shutter_label.text(), "Closed")
        self.assertTrue(panel.terminate_dev())

    def test_power_display_is_read_only_and_tracks_controller_readback(self):
        panel = SpectraPhysicsX3Laser(hardware=self.hardware)
        panel.connect("COM4")
        self.port.power_w = 1.234
        self.assertEqual(panel.logic.get_output_power_w(), 1.234)
        self.assertIn("1.234 W", panel.power_label.text())
        self.assertEqual(panel.power_meter.value(), 1234)
        self.assertTrue(panel.terminate_dev())

    def test_panel_control_requires_continuous_hold(self):
        button = HoldButton("Hold to change")
        self.assertEqual(button._hold_timer.interval(), 3_000)
        button._hold_timer.setInterval(30)
        events = []
        button.held.connect(lambda: events.append(True))
        button.show()
        QtTest.QTest.mousePress(button, QtCore.Qt.MouseButton.LeftButton)
        QtTest.QTest.mouseRelease(button, QtCore.Qt.MouseButton.LeftButton)
        QtTest.QTest.qWait(40)
        self.assertEqual(events, [])
        QtTest.QTest.mousePress(button, QtCore.Qt.MouseButton.LeftButton)
        QtTest.QTest.qWait(40)
        self.assertEqual(events, [True])
        QtTest.QTest.mouseRelease(button, QtCore.Qt.MouseButton.LeftButton)
        button.close()
