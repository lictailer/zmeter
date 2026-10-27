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
from devices.nema11_stepper.nema11_hardware import MotorStopped, Nema11Hardware
from devices.nema11_stepper.nema11_logic import Nema11Logic
from devices.nema11_stepper.nema11_main import Nema11Stepper

STEP_DEG = 360 / 6400


class FakeSerial:
    """Emulates the uploaded sketch with no encoder tap: the encoder always reads 0."""

    def __init__(self, **kwargs):
        self.commands, self.response, self.closed = [], b"", False
        self.steps = 500  # Board power-on state may be arbitrary.
        self.ping, self.drop_move, self.on_move, self.reply = "OK NEMA11 1", False, None, None
        self.seconds_per_deg = 0.0

    def commanded(self):
        return self.steps * STEP_DEG

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
            self.steps = 0
            response = "OK 0.000000"
        elif words == ["GET_POS"]:
            response = "POS 0.000000"
        elif words == ["GET_CMD"]:
            response = self.reply or f"CMD {self.commanded():.6f}"
        elif words[0] == "MOVE_ABS":
            before, self.steps = self.steps, round(float(words[1]) / STEP_DEG)
            time.sleep(abs(self.steps - before) * STEP_DEG * self.seconds_per_deg)
            response = "OK 0.000000"
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
    def test_connect_zeroes_origin_and_refuses_other_sketch(self):
        controller, port = hardware()
        self.assertEqual(port.commands, [])
        controller.connect("FAKE", threading.Event())
        self.assertEqual(port.commands, ["PING", "ZERO", "GET_CMD"])
        self.assertEqual(controller.read_angle(), 0)
        before = list(port.commands)
        controller.disconnect()
        self.assertTrue(port.closed)
        self.assertEqual(port.commands, before)
        controller, port = hardware()
        port.ping = "OK PONG"
        with self.assertRaisesRegex(RuntimeError, "nema11_stepper sketch"):
            controller.connect("FAKE", threading.Event())
        self.assertEqual(port.commands, ["PING"])
        self.assertTrue(port.closed)

    def test_z_angle_reports_commanded_position_without_encoder(self):
        controller, port = hardware()
        logic = Nema11Logic(controller)
        logic.connect("FAKE")
        self.assertAlmostEqual(logic.set_z_angle(45), 45)
        self.assertEqual(port.commands[-2:], ["MOVE_ABS 45.000000", "GET_CMD"])
        self.assertAlmostEqual(logic.get_z_angle(), 45)
        self.assertAlmostEqual(logic.set_z_angle(12.34), round(12.34 / STEP_DEG) * STEP_DEG, places=5)
        self.assertEqual(sorted(n for n in dir(logic) if n.startswith(("set_", "get_"))),
                         ["get_z_angle", "set_z_angle"])
        self.assertTrue(logic.terminate_dev())

    def test_no_software_limits_only_finite_numbers(self):
        controller, port = hardware()
        controller.connect("FAKE", threading.Event())
        self.assertAlmostEqual(controller.move_angle(-3600, threading.Event()), -3600)
        self.assertEqual(len([c for c in port.commands if c.startswith("MOVE")]), 11)  # 1 deg, then 360 deg chunks
        moves = len(port.commands)
        for invalid in (True, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                controller.move_angle(invalid, threading.Event())
        self.assertEqual(len(port.commands), moves)
        with self.assertRaises(ValueError):
            controller.configure(0)

    def test_long_move_reports_position_about_every_200_ms_and_stops_between_chunks(self):
        controller, port = hardware()
        port.seconds_per_deg = 0.002  # 500 deg/s, so 0.2 s chunks are about 100 deg.
        logic = Nema11Logic(controller)
        logic.connect("FAKE")
        seen = []
        logic.sig_position.connect(lambda value: seen.append((time.monotonic(), value)))
        self.assertAlmostEqual(logic.set_z_angle(1000), 1000, delta=STEP_DEG / 2)
        moves = [float(c.split()[1]) for c in port.commands if c.startswith("MOVE")]
        self.assertAlmostEqual(moves[0], 1)
        self.assertTrue(8 <= len(moves) <= 14, moves)
        self.assertTrue(all(70 < b - a < 140 for a, b in zip(moves[1:], moves[2:-1])), moves)
        positions = [value for _, value in seen]
        self.assertEqual(positions, sorted(positions))
        gaps = [b - a for (a, _), (b, _) in zip(seen[1:], seen[2:-2])]
        self.assertTrue(all(0.12 < gap < 0.3 for gap in gaps), gaps)
        port.seconds_per_deg = 0.0
        port.commands.clear()
        port.on_move = logic.stop_event.set
        with self.assertRaises(MotorStopped): logic.set_z_angle(0)
        self.assertEqual(len([c for c in port.commands if c.startswith("MOVE")]), 1)
        self.assertAlmostEqual(logic.get_z_angle(), 999, delta=STEP_DEG / 2)
        self.assertTrue(logic.terminate_dev())

    def test_stop_prevents_next_move(self):
        controller, port = hardware()
        stop = threading.Event()
        controller.connect("FAKE", stop)
        stop.set()
        with self.assertRaises(MotorStopped): controller.move_angle(10, stop)
        self.assertFalse(any(c.startswith("MOVE") for c in port.commands))

    def test_malformed_reply_marks_state_uncertain(self):
        controller, port = hardware()
        controller.connect("FAKE", threading.Event())
        port.reply = "POS 1"
        with self.assertRaisesRegex(ValueError, "Unexpected"):
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
        panel.timeout.setValue(30)
        saved = json.loads(json.dumps(panel.setup_dict()))
        self.assertEqual(saved, dict(schema_version=1, address="COM7", timeout_s=30))
        panel.timeout.setValue(5)
        panel.load_setup(saved)
        self.assertEqual(panel.timeout.value(), 30)
        self.assertEqual(controller.command_timeout_s, 30)
        with self.assertRaises(ValueError):
            panel.load_setup(dict(saved, limits={}))
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
                    value = 100 - (port.commanded() * um_per_deg - 2.3) ** 2
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
