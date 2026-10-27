"""Only fake serial/router objects, temporary files and offscreen widgets."""
from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6 import QtCore, QtWidgets
from devices.arduino_steppers.stepper_hardware import AXES, MotorLimits, MotorStopped, StepperHardware
from devices.arduino_steppers.stepper_logic import StepperLogic
from devices.arduino_steppers.stepper_main import ArduinoSteppers


class FakeSerial:
    def __init__(self, **kwargs):
        self.commands, self.positions, self.speeds = [], dict.fromkeys(AXES, 0), dict(A=12, B=7, C=7)
        self.response, self.closed, self.drop_move = b"", False, False
        self.on_move = None
        self.ping = "OK STEPPERS 1"

    def reset_input_buffer(self): self.response = b""
    def flush(self): pass
    def close(self): self.closed = True
    def readline(self):
        data, self.response = self.response, b""
        return data

    def write(self, payload):
        command = payload.decode().strip()
        self.commands.append(command)
        words = command.split()
        if words == ["PING"]:
            self.response = (self.ping + "\n").encode()
            return
        verb, axis = words[:2]
        if verb == "GET_CONFIG":
            response = f"CFG {axis} 2048 {self.speeds[axis]} 12"
        elif verb == "GET_POS":
            response = f"POS {axis} {self.positions[axis]}"
        elif verb == "MOVE_ABS":
            self.positions[axis] = int(words[2])
            response = f"OK {axis} {self.positions[axis]}"
            if self.on_move: self.on_move()
            if self.drop_move:
                self.response = b""
                return
        elif verb == "SET_SPEED":
            self.speeds[axis] = int(words[2])
            response = f"SPEED {axis} {self.speeds[axis]}"
        else:
            raise AssertionError(command)
        self.response = (response + "\n").encode()


def hardware():
    serial = FakeSerial()
    return StepperHardware(serial_factory=lambda **kw: serial, startup_delay_s=0), serial


class StepperTests(unittest.TestCase):
    def test_connect_queries_three_motors_and_refuses_old_protocol(self):
        controller, port = hardware()
        self.assertEqual(port.commands, [])
        controller.connect("FAKE", threading.Event())
        self.assertEqual(set(controller.info), set(AXES))
        self.assertFalse(any(c.startswith(("MOVE", "SET_")) for c in port.commands))
        before = list(port.commands)
        controller.disconnect()
        self.assertTrue(port.closed)
        self.assertEqual(port.commands, before)
        controller, port = hardware()
        port.ping = "OK PONG"
        with self.assertRaisesRegex(RuntimeError, "three-motor"):
            controller.connect("FAKE", threading.Event())
        self.assertEqual(port.commands, ["PING"])
        self.assertTrue(port.closed)

    def test_nine_scan_channels_are_numeric_absolute_independent_and_quantized(self):
        controller, port = hardware()
        logic = StepperLogic(controller)
        logic.connect("FAKE")
        self.assertAlmostEqual(logic.set_stepperA_angle(1), 6 * 360 / 2048)
        self.assertEqual(logic.get_stepperA_steps(), 6)
        logic.set_stepperA_angle(1)
        self.assertEqual(logic.get_stepperA_steps(), 6)
        self.assertEqual(logic.set_stepperB_steps(-3), -3)
        self.assertEqual(logic.get_stepperB_steps(), -3)
        self.assertEqual(logic.set_stepperC_speed_rpm(4), 4)
        self.assertEqual(logic.get_stepperC_speed_rpm(), 4)
        self.assertEqual(logic.get_stepperC_steps(), 0)
        self.assertEqual(port.positions, dict(A=6, B=-3, C=0))
        self.assertEqual(logic.set_stepperC_steps(1.5), 2)
        self.assertEqual(logic.set_stepperC_steps(-1.5), -2)
        self.assertTrue(logic.terminate_dev())

    def test_limits_and_input_validation_fail_before_any_move(self):
        controller, port = hardware()
        controller.connect("FAKE", threading.Event())
        for invalid in (114, -114, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                controller.move_steps("A", invalid, threading.Event())
        with self.assertRaises(ValueError): controller.move_angle("B", 21, threading.Event())
        with self.assertRaises(ValueError): controller.set_speed("C", 13)
        self.assertFalse(any(c.startswith(("MOVE", "SET_")) for c in port.commands))

    def test_stop_waits_for_ack_then_prevents_next_segment(self):
        controller, port = hardware()
        stop = threading.Event()
        controller.connect("FAKE", stop)
        port.on_move = stop.set
        with self.assertRaises(MotorStopped): controller.move_steps("B", 100, stop)
        self.assertEqual(controller.positions["B"], 56)
        self.assertEqual([c for c in port.commands if c.startswith("MOVE")], ["MOVE_ABS B 56"])

    def test_missing_ack_refuses_more_commands_no_blind_retry(self):
        controller, port = hardware()
        controller.command_timeout_s = 0.001
        controller.connect("FAKE", threading.Event())
        port.drop_move = True
        with self.assertRaises(TimeoutError): controller.move_steps("A", 2, threading.Event())
        before = list(port.commands)
        with self.assertRaisesRegex(RuntimeError, "uncertain"): controller.read_steps("A")
        self.assertEqual(port.commands, before)

    def test_shared_port_operations_are_serialized(self):
        controller, port = hardware()
        controller.connect("FAKE", threading.Event())
        entered, release = threading.Event(), threading.Event()
        port.on_move = lambda: (entered.set(), release.wait(1))
        thread = threading.Thread(target=controller.move_steps, args=("A", 20, threading.Event()))
        thread.start()
        self.assertTrue(entered.wait(1))
        other = threading.Thread(target=controller.read_steps, args=("B",))
        other.start()
        self.assertTrue(other.is_alive())
        release.set()
        thread.join(1); other.join(1)
        self.assertFalse(thread.is_alive() or other.is_alive())
        self.assertEqual(port.commands[-1], "GET_POS B")


class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_panel_readback_is_separate_and_setup_load_never_connects(self):
        controller, port = hardware()
        panel = ArduinoSteppers(controller)
        self.addCleanup(panel.close)
        panel.address_lineEdit.setText("FAKE")
        saved = json.loads(json.dumps(panel.setup_dict()))
        panel.load_setup(saved)
        self.assertEqual(port.commands, [])
        panel.logic.connect("FAKE")
        panel.controls["A"]["angle"].setValue(8)
        panel.logic.get_stepperA_angle()
        self.assertEqual(panel.controls["A"]["angle"].value(), 8)
        self.assertEqual(panel.readbacks["A", "angle"].text(), "0")
        self.assertTrue(panel.terminate_dev())

    def test_worker_responsive_and_termination_preserves_inflight_connection(self):
        controller, port = hardware()
        logic = StepperLogic(controller)
        logic.connect("FAKE")
        entered, release = threading.Event(), threading.Event()
        port.on_move = lambda: (entered.set(), release.wait(1))
        ticks = []
        timer = QtCore.QTimer()
        timer.setInterval(1); timer.timeout.connect(lambda: ticks.append(1)); timer.start()
        self.assertTrue(logic.submit(logic.set_stepperA_steps, 100))
        self.assertTrue(entered.wait(1))
        deadline = time.monotonic() + 0.02
        while time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(0.001)
        self.assertTrue(ticks)
        self.assertFalse(logic.terminate_dev(wait_ms=5))
        self.assertTrue(controller.connected)
        release.set()
        self.assertTrue(logic.wait(1000))
        timer.stop()
        self.assertTrue(logic.terminate_dev())
        self.assertTrue(port.closed)

    def test_profile_manager_constructs_both_panels_without_serial_access(self):
        from core.device_management.config import load_profile
        from core.device_management.manager import DeviceManager
        from core.device_management.registry import build_default_registry
        registry = build_default_registry()
        root = Path(__file__).resolve().parents[3]
        profile = load_profile(root / "device_config.xlsx", driver_specs=registry.config_specs, repository_root=root)
        selected = tuple(c for c in profile.devices if c.driver in ("arduino_steppers", "auto_focus"))
        self.assertEqual(len(selected), 2)
        motor = next(c for c in selected if c.driver == "arduino_steppers")
        self.assertEqual(motor.connection["address"], "COM6")
        self.assertFalse(any(c.connect_on_start for c in selected))
        self.assertFalse(any(c.enabled for c in selected))
        selected = tuple(replace(c, enabled=True) for c in selected)
        with mock.patch.object(StepperHardware, "connect", side_effect=AssertionError("Real port forbidden")) as connect:
            manager = DeviceManager(registry, SimpleNamespace())
            snapshot = manager.load_profile(replace(profile, devices=selected))
            manager.request_startup_connections()
            self.assertEqual(len(snapshot.equipment), 2)
            self.assertTrue(manager.teardown_all().succeeded)
            connect.assert_not_called()

    def test_autofocus_routes_calibrated_z_through_standalone_controller(self):
        from devices.auto_focus.autofocus_engine import AutofocusSettings, SourceSettings, SearchSettings, ZSettings
        from devices.auto_focus.autofocus_logic import AutofocusLogic
        controller, port = hardware()
        motors = StepperLogic(controller)
        motors.connect("FAKE")
        class Router:
            def route_command(self, request):
                action, channel = request["action"], request["channel"]
                if action == "list_catalog":
                    return dict(ok=True, catalog={"arduino_steppers": {"readable": ["stepperA_angle", "stepperA_steps"], "writable": ["stepperA_angle", "stepperA_steps"]},
                                                  "nidaq": {"readable": ["AI0"], "writable": []}})
                if request["target_device"] == "nidaq":
                    value = 100 - (controller.positions["A"] * 360 / 2048 - 2.3) ** 2
                elif action == "write": value = getattr(motors, "set_" + channel)(request["value"])
                else: value = getattr(motors, "get_" + channel)()
                return dict(ok=True, value=value)
        logic = AutofocusLogic()
        logic.configure_command_router(Router())
        # Example test calibration only: 2 um/degree, with a 3 um reference offset.
        settings = AutofocusSettings(z=replace(ZSettings(), convert_to_distance=True, distance_per_native=2,
                                               distance_zero=3, minimum=-30, maximum=30, tolerance=0.2),
                                     source=replace(SourceSettings(), sample_interval_s=0),
                                     search=replace(SearchSettings(), start_offset=-10, stop_offset=10, settle_s=0))
        logic.apply_settings(settings)
        logic.connect_z()
        logic.set_focus(0)
        self.assertEqual(logic.last_outcome, "complete")
        self.assertAlmostEqual(logic.get_z(), 3 + 2 * 2.3, delta=0.65)
        before = list(port.commands)
        self.assertTrue(logic.terminate_dev())
        self.assertTrue(motors.connected) # Autofocus does not own the serial session.
        self.assertEqual(port.commands, before)
        # Same pipeline using a full-step channel and distance conversion.
        from devices.auto_focus.autofocus_engine import Channel
        steps = Channel("arduino_steppers", "stepperA_steps")
        logic = AutofocusLogic()
        logic.configure_command_router(Router())
        logic.apply_settings(replace(settings,
            z=replace(settings.z, setter=steps, getter=steps, native_unit="steps", distance_unit="mm",
                      distance_per_native=0.02, distance_zero=0.5, minimum=-3, maximum=3,
                      max_move=0.2, tolerance=0.011),
            search=replace(settings.search, start_offset=-0.6, stop_offset=0.6)))
        logic.connect_z()
        logic.set_focus(1)
        self.assertEqual(logic.last_outcome, "complete")
        self.assertAlmostEqual(logic.get_z(), 0.5 + 0.02 * (2.3 * 2048 / 360), delta=0.04)
        self.assertTrue(logic.terminate_dev())
        self.assertTrue(motors.terminate_dev())


if __name__ == "__main__": unittest.main()
