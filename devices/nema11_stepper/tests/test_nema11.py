"""Only fake serial/router objects, temporary files and offscreen widgets."""
from dataclasses import asdict, replace
import json
import math
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6 import QtCore, QtWidgets
from devices.nema11_stepper.nema11_hardware import MotorLimits, MotorStopped, Nema11Hardware
from devices.nema11_stepper.nema11_logic import Nema11Logic
from devices.nema11_stepper.nema11_main import Nema11Stepper

ENCODER_DEG = 360 / 4000
STEP_DEG = 360 / 6400


class FakeSerial:
    """Emulates the sketch: commanded microsteps, encoder-quantized readback."""

    def __init__(self, **kwargs):
        self.commands, self.response, self.closed = [], b"", False
        self.steps, self.shaft = 0, 0.0  # Board power-on state may be arbitrary.
        self.ping, self.drop_move, self.stalled, self.on_move = "OK NEMA11 1", False, False, None

    def encoder(self):
        return math.floor(self.shaft / ENCODER_DEG) * ENCODER_DEG

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
            response = self.ping
        elif words == ["ZERO"]:
            self.steps, self.shaft = 0, 0.0
            response = f"OK {self.encoder():.6f}"
        elif words == ["GET_POS"]:
            response = f"POS {self.encoder():.6f}"
        elif words == ["GET_CMD"]:
            response = f"CMD {self.steps * STEP_DEG:.6f}"
        elif words[0] == "MOVE_ABS":
            self.steps = round(float(words[1]) / STEP_DEG)
            if not self.stalled:
                self.shaft = self.steps * STEP_DEG
            response = f"OK {self.encoder():.6f}"
            if self.on_move: self.on_move()
            if self.drop_move:
                return
        else:
            raise AssertionError(command)
        self.response = (response + "\n").encode()


def hardware():
    serial = FakeSerial()
    controller = Nema11Hardware(serial_factory=lambda **kw: serial, startup_delay_s=0)
    return controller, serial


class Nema11Tests(unittest.TestCase):
    def test_connect_zeroes_origin_and_refuses_old_sketch(self):
        controller, port = hardware()
        self.assertEqual(port.commands, [])
        port.steps, port.shaft = 500, 31.0
        controller.connect("FAKE", threading.Event())
        self.assertEqual(port.commands, ["PING", "ZERO"])
        self.assertEqual(controller.read_angle(), 0)
        before = list(port.commands)
        controller.disconnect()
        self.assertTrue(port.closed)
        self.assertEqual(port.commands, before)
        controller, port = hardware()
        port.ping = "OK PONG"
        with self.assertRaisesRegex(RuntimeError, "encoder sketch"):
            controller.connect("FAKE", threading.Event())
        self.assertEqual(port.commands, ["PING"])
        self.assertTrue(port.closed)

    def test_z_angle_channel_returns_encoder_reading(self):
        controller, port = hardware()
        logic = Nema11Logic(controller)
        logic.connect("FAKE")
        result = logic.set_z_angle(12.34)
        self.assertAlmostEqual(result, 12.34, delta=MotorLimits().tolerance_deg)
        self.assertEqual(result, port.encoder())
        self.assertEqual(logic.get_z_angle(), port.encoder())
        self.assertAlmostEqual(logic.set_z_angle(-7), -7, delta=MotorLimits().tolerance_deg)
        self.assertEqual(sorted(n for n in dir(logic) if n.startswith(("set_", "get_"))),
                         ["get_z_angle", "set_z_angle"])
        self.assertTrue(logic.terminate_dev())

    def test_limits_and_input_validation_fail_before_any_move(self):
        controller, port = hardware()
        controller.connect("FAKE", threading.Event())
        for invalid in (50.1, -50.1, True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                controller.move_angle(invalid, threading.Event())
        for bad in (dict(minimum_deg=1, maximum_deg=0), dict(segment_deg=0), dict(tolerance_deg=0)):
            with self.assertRaises(ValueError):
                controller.configure(replace(MotorLimits(), **bad), 1)
        self.assertFalse(any(c.startswith("MOVE") for c in port.commands))

    def test_moves_are_segmented_and_stop_waits_for_ack(self):
        controller, port = hardware()
        stop = threading.Event()
        controller.connect("FAKE", stop)
        controller.move_angle(25, stop)
        self.assertEqual([c for c in port.commands if c.startswith("MOVE")],
                         ["MOVE_ABS 10.000000", "MOVE_ABS 19.990000", "MOVE_ABS 25.000000"])
        port.commands.clear()
        port.on_move = stop.set
        with self.assertRaises(MotorStopped): controller.move_angle(0, stop)
        self.assertEqual([c for c in port.commands if c.startswith("MOVE")], ["MOVE_ABS 14.930000"])

    def test_encoder_mismatch_marks_state_uncertain(self):
        controller, port = hardware()
        controller.configure(replace(MotorLimits(), settle_timeout_s=0.05), 1)
        controller.connect("FAKE", threading.Event())
        port.stalled = True
        with self.assertRaisesRegex(RuntimeError, "Encoder reads 0 deg, not 5 deg"):
            controller.move_angle(5, threading.Event())
        before = list(port.commands)
        with self.assertRaisesRegex(RuntimeError, "uncertain"): controller.read_angle()
        self.assertEqual(port.commands, before)

    def test_missing_ack_refuses_more_commands_no_blind_retry(self):
        controller, port = hardware()
        controller.command_timeout_s = 0.001
        controller.connect("FAKE", threading.Event())
        port.drop_move = True
        with self.assertRaises(TimeoutError): controller.move_angle(2, threading.Event())
        before = list(port.commands)
        with self.assertRaisesRegex(RuntimeError, "uncertain"): controller.read_angle()
        self.assertEqual(port.commands, before)


class QtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_panel_setup_round_trip_never_connects(self):
        controller, port = hardware()
        panel = Nema11Stepper(controller)
        self.addCleanup(panel.close)
        panel.address_lineEdit.setText("COM7")
        panel.limit_controls["maximum_deg"].setValue(40)
        saved = json.loads(json.dumps(panel.setup_dict()))
        self.assertEqual(saved["limits"], asdict(replace(MotorLimits(), maximum_deg=40)))
        panel.limit_controls["maximum_deg"].setValue(1)
        panel.load_setup(saved)
        self.assertEqual(panel.limit_controls["maximum_deg"].value(), 40)
        self.assertEqual(controller.limits.maximum_deg, 40)
        with self.assertRaises(ValueError):
            panel.load_setup(dict(saved, schema_version=2))
        self.assertEqual(port.commands, [])
        panel.logic.connect("COM7")
        panel.target.setValue(8)
        panel.logic.get_z_angle()
        self.assertEqual(panel.target.value(), 8)
        self.assertEqual(panel.readback.text(), "0")
        self.assertTrue(panel.terminate_dev())

    def test_worker_responsive_and_termination_preserves_inflight_connection(self):
        controller, port = hardware()
        logic = Nema11Logic(controller)
        logic.connect("FAKE")
        entered, release = threading.Event(), threading.Event()
        port.on_move = lambda: (entered.set(), release.wait(1))
        ticks = []
        timer = QtCore.QTimer()
        timer.setInterval(1); timer.timeout.connect(lambda: ticks.append(1)); timer.start()
        self.assertTrue(logic.submit(logic.set_z_angle, 5))
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

    def test_registration_constructs_panel_without_serial_access(self):
        from core.device_management.registrations import nema11_stepper_registration
        registration = nema11_stepper_registration()
        with mock.patch.object(Nema11Hardware, "connect", side_effect=AssertionError("Real port forbidden")) as connect:
            panel = registration.factory()
            self.addCleanup(panel.close)
            registration.configure_instance(panel, {"address": "COM7"})
            self.assertEqual(panel.address_lineEdit.text(), "COM7")
            self.assertFalse(registration.is_connected(panel))
            self.assertTrue(registration.terminate(panel))
            connect.assert_not_called()

    def test_autofocus_routes_calibrated_z_through_encoder_channel(self):
        from devices.auto_focus.autofocus_engine import (
            AutofocusSettings, Channel, SearchSettings, SourceSettings, ZSettings)
        from devices.auto_focus.autofocus_logic import AutofocusLogic
        controller, port = hardware()
        motor = Nema11Logic(controller)
        motor.connect("FAKE")
        um_per_deg = 500 / (360 * 100 / 30)  # Previous autofocus gear/translator defaults.

        class Router:
            def route_command(self, request):
                action, channel = request["action"], request["channel"]
                if action == "list_catalog":
                    return dict(ok=True, catalog={"nema11_stepper": {"readable": ["z_angle"], "writable": ["z_angle"]},
                                                  "nidaq": {"readable": ["AI0"], "writable": []}})
                if request["target_device"] == "nidaq":
                    value = 100 - (port.encoder() * um_per_deg - 2.3) ** 2
                elif action == "write": value = getattr(motor, "set_" + channel)(request["value"])
                else: value = getattr(motor, "get_" + channel)()
                return dict(ok=True, value=value)

        z = Channel("nema11_stepper", "z_angle")
        logic = AutofocusLogic()
        logic.configure_command_router(Router())
        logic.apply_settings(AutofocusSettings(
            z=replace(ZSettings(), setter=z, getter=z, convert_to_distance=True, distance_per_native=um_per_deg,
                      minimum=-20, maximum=20, max_move=4, tolerance=0.2 * um_per_deg),
            source=replace(SourceSettings(), sample_interval_s=0),
            search=replace(SearchSettings(), start_offset=-10, stop_offset=10, settle_s=0)))
        logic.connect_z()
        logic.set_focus(0)
        self.assertEqual(logic.last_outcome, "complete")
        self.assertAlmostEqual(logic.get_z(), 2.3, delta=0.25)
        before = list(port.commands)
        self.assertTrue(logic.terminate_dev())
        self.assertTrue(motor.connected)  # Autofocus does not own the serial session.
        self.assertEqual(port.commands, before)
        self.assertTrue(motor.terminate_dev())


if __name__ == "__main__": unittest.main()
