import os
import sys
import threading
import types
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if "win32com" not in sys.modules:
    win32com_module = types.ModuleType("win32com")
    win32com_client_module = types.ModuleType("win32com.client")
    win32com_module.client = win32com_client_module
    sys.modules["win32com"] = win32com_module
    sys.modules["win32com.client"] = win32com_client_module

from PyQt6 import QtWidgets

from core.artificial_channel_2d_main import ArtificialChannel2D
from core.artificial_channel_logic import ArtificialChannelLogic
from core.mainWindow import MainWindow
from core.scan_logic import ScanLogic


IDENTITY_COORDINATES = (
    ((0.0, 0.0), (0.0, 0.0)),
    ((1.0, 0.0), (1.0, 0.0)),
    ((0.0, 1.0), (0.0, 1.0)),
)


def make_logic(
    write_channel,
    *,
    limits_x=(-1.5, 2.0),
    limits_y=(-1.0, 1.0),
    should_abort=None,
    resolve_device_label=None,
):
    logic = ArtificialChannelLogic(
        write_channel=write_channel,
        read_channel=lambda _channel: 0.0,
        original_channel_x_name="device_x_output",
        original_channel_y_name="device_y_output",
        artificial_channel_x_name="x",
        artificial_channel_y_name="y",
        coordinate_pairs=IDENTITY_COORDINATES,
        original_channel_x_limits=limits_x,
        original_channel_y_limits=limits_y,
        should_abort_ramp=should_abort,
        resolve_device_label=resolve_device_label,
    )
    logic.RAMP_INTER_STEP_DELAY_S = 0.0
    return logic


def make_coupled_logic(
    write_channel,
    *,
    read_channel=None,
    should_abort=None,
):
    logic = ArtificialChannelLogic(
        write_channel=write_channel,
        read_channel=read_channel or (lambda _channel: 0.0),
        original_channel_x_name="device_A",
        original_channel_y_name="device_B",
        artificial_channel_x_name="n",
        artificial_channel_y_name="E",
        original_channel_x_limits=(-1.0, 1.0),
        original_channel_y_limits=(-1.0, 1.0),
        should_abort_ramp=should_abort,
        resolve_device_label=lambda _channel: "shared_device",
    )
    logic.RAMP_INTER_STEP_DELAY_S = 0.0
    return logic


class ArtificialChannelRampTests(unittest.TestCase):
    def test_artificial_getters_return_commanded_values_without_hardware_reads(self):
        def unexpected_read(_channel):
            raise AssertionError("Artificial getter must not read original channels")

        logic = make_coupled_logic(
            lambda _value, _channel: None,
            read_channel=unexpected_read,
        )

        self.assertEqual(logic.read_channel_value("n"), 0.0)
        self.assertEqual(logic.read_channel_value("E"), 0.0)

        logic.set_artificial_channel_values(0.4, -0.2)

        self.assertEqual(logic.read_channel_value("n"), 0.4)
        self.assertEqual(logic.read_channel_value("E"), -0.2)

    def test_noisy_boundary_read_cannot_corrupt_the_next_ramp(self):
        writes = []
        read_count = 0

        def noisy_boundary_read(channel):
            nonlocal read_count
            read_count += 1
            return {
                "device_A": -0.999565,
                "device_B": 1.000435,
            }[channel]

        logic = make_coupled_logic(
            lambda value, channel: writes.append((channel, value)),
            read_channel=noisy_boundary_read,
        )
        logic.set_artificial_channel_values(0.0, -2.0)
        writes.clear()

        measured_n = logic.read_channel_value("n")
        result = logic.set_artificial_channel_values(0.0, -1.9, is_scan_write=True)

        self.assertEqual(measured_n, 0.0)
        self.assertEqual(read_count, 0)
        self.assertFalse(result["skipped"])
        self.assertTrue(writes)
        self.assertEqual(logic._commanded_artificial_values, {"n": 0.0, "E": -1.9})

    def test_target_is_emitted_before_each_applied_waypoint(self):
        logic = make_logic(
            lambda _value, _channel: None,
            resolve_device_label=lambda _channel: "shared_device",
        )
        events = []
        logic.sig_target_changed.connect(
            lambda target: events.append(("target", dict(target)))
        )
        logic.sig_state_changed.connect(
            lambda state: events.append(("state", dict(state)))
        )

        logic.set_artificial_channel_values(0.08, 0.04)

        self.assertEqual(events[0], ("target", {"x": 0.08, "y": 0.04}))
        applied_states = [payload for event, payload in events if event == "state"]
        self.assertGreater(len(applied_states), 1)
        for state in applied_states:
            self.assertEqual(state["x"], state["device_x_output"])
            self.assertEqual(state["y"], state["device_y_output"])
        self.assertEqual(applied_states[-1]["x"], 0.08)
        self.assertEqual(applied_states[-1]["y"], 0.04)

    def test_rejected_target_emits_no_applied_state(self):
        writes = []
        logic = make_logic(
            lambda value, channel: writes.append((channel, value)),
            limits_x=(-0.05, 0.05),
            limits_y=(-0.05, 0.05),
        )
        targets = []
        applied_states = []
        logic.sig_target_changed.connect(lambda target: targets.append(dict(target)))
        logic.sig_state_changed.connect(lambda state: applied_states.append(dict(state)))

        result = logic.set_artificial_channel_values(0.10, 0.0)

        self.assertTrue(result["skipped"])
        self.assertEqual(targets, [{"x": 0.10, "y": 0.0}])
        self.assertEqual(applied_states, [])
        self.assertEqual(writes, [])
        self.assertEqual(logic.read_channel_value("x"), 0.0)

    def test_single_axis_write_uses_current_position_as_ramp_start(self):
        writes = []
        logic = make_logic(lambda value, channel: writes.append((channel, value)))
        logic.set_artificial_channel_values(0.155, 0.0)
        writes.clear()

        result = logic.set_channel_value("x", 0.41)

        x_values = [value for channel, value in writes if channel == "device_x_output"]
        self.assertEqual(x_values, [0.155, 0.2, 0.24, 0.28, 0.32, 0.36, 0.41])
        self.assertFalse(result["skipped"])
        self.assertEqual(logic._commanded_artificial_values, {"x": 0.41, "y": 0.0})

    def test_dual_axis_waypoints_follow_the_longer_axis(self):
        logic = make_logic(lambda _value, _channel: None)

        waypoints = logic._build_artificial_ramp_waypoints(
            0.0, 0.0, 0.20, 0.09, 0.04, 0.02
        )

        self.assertEqual(
            waypoints,
            [
                (0.0, 0.0),
                (0.04, 0.02),
                (0.08, 0.04),
                (0.12, 0.05),
                (0.16, 0.07),
                (0.20, 0.09),
            ],
        )

    def test_same_device_writes_are_sequential(self):
        write_order = []
        logic = make_logic(
            lambda _value, channel: write_order.append(channel),
            resolve_device_label=lambda _channel: "shared_device",
        )

        logic.set_artificial_channel_values(0.0, 0.0)

        self.assertEqual(write_order, ["device_x_output", "device_y_output"])

    def test_different_device_writes_run_concurrently(self):
        barrier = threading.Barrier(2)
        thread_ids = set()
        lock = threading.Lock()

        def write_channel(_value, _channel):
            with lock:
                thread_ids.add(threading.get_ident())
            barrier.wait(timeout=1.0)

        logic = make_logic(
            write_channel,
            resolve_device_label=lambda channel: channel,
        )

        logic.set_artificial_channel_values(0.0, 0.0)

        self.assertEqual(len(thread_ids), 2)

    def test_out_of_limit_ramp_never_writes_an_unsafe_value(self):
        writes = []
        logic = make_logic(
            lambda value, channel: writes.append((channel, value)),
            limits_x=(-0.05, 0.05),
            limits_y=(-0.05, 0.05),
            resolve_device_label=lambda _channel: "shared_device",
        )

        result = logic.set_channel_value("x", 0.10, is_scan_write=True)

        self.assertTrue(result["skipped"])
        self.assertEqual(result["reason"], "original_limit_exceeded")
        self.assertEqual(writes, [])
        self.assertEqual(logic._commanded_artificial_values, {"x": 0.0, "y": 0.0})
        self.assertTrue(logic.consume_skip_read_for_scan())

    def test_scan_skip_retains_target_for_complementary_channel(self):
        writes = []
        logic = make_coupled_logic(
            lambda value, channel: writes.append((channel, value))
        )
        logic.set_artificial_channel_values(2.0, 0.0)
        writes.clear()

        skipped = logic.set_channel_value("E", 0.2, is_scan_write=True)

        self.assertTrue(skipped["skipped"])
        self.assertEqual(writes, [])
        self.assertEqual(logic._commanded_artificial_values, {"n": 2.0, "E": 0.0})
        self.assertEqual(
            logic._scan_target_artificial_values,
            {"n": 2.0, "E": 0.2},
        )

        completed = logic.set_channel_value("n", -1.8, is_scan_write=True)

        self.assertFalse(completed["skipped"])
        self.assertEqual(logic._commanded_artificial_values, {"n": -1.8, "E": 0.2})
        self.assertEqual(
            logic._scan_target_artificial_values,
            logic._commanded_artificial_values,
        )

    def test_manual_skip_discards_the_rejected_target(self):
        writes = []
        logic = make_coupled_logic(
            lambda value, channel: writes.append((channel, value))
        )
        logic.set_artificial_channel_values(2.0, 0.0)
        writes.clear()

        skipped = logic.set_channel_value("E", 0.2)

        self.assertEqual(writes, [])
        self.assertEqual(logic._commanded_artificial_values, {"n": 2.0, "E": 0.0})

        completed = logic.set_channel_value("n", -1.8)

        self.assertTrue(skipped["skipped"])
        self.assertFalse(completed["skipped"])
        self.assertEqual(logic._commanded_artificial_values, {"n": -1.8, "E": 0.0})
        self.assertEqual(
            logic._scan_target_artificial_values,
            logic._commanded_artificial_values,
        )

    def test_read_reset_and_configuration_clear_pending_target(self):
        readings = {"device_A": 0.25, "device_B": -0.25}
        logic = make_coupled_logic(
            lambda _value, _channel: None,
            read_channel=lambda channel: readings[channel],
        )
        logic.set_artificial_channel_values(2.0, 0.0)
        logic.set_channel_value("E", 0.2, is_scan_write=True)

        logic.read_all_channel_values()

        self.assertEqual(logic._commanded_artificial_values, {"n": 0.0, "E": 0.5})
        self.assertEqual(
            logic._scan_target_artificial_values,
            logic._commanded_artificial_values,
        )

        logic.set_channel_value("E", 2.0, is_scan_write=True)
        logic.apply_configuration(
            original_channel_x_name="device_A",
            original_channel_y_name="device_B",
            artificial_channel_x_name="n",
            artificial_channel_y_name="E",
            coordinate_pairs=logic.default_coordinate_pairs,
            original_channel_x_limits=(-1.0, 1.0),
            original_channel_y_limits=(-1.0, 1.0),
        )
        self.assertEqual(logic._commanded_artificial_values, {"n": 0.0, "E": 0.0})
        self.assertEqual(
            logic._scan_target_artificial_values,
            logic._commanded_artificial_values,
        )

        logic.set_channel_value("n", 2.0, is_scan_write=True)
        logic.reset_skip_next_scan_read()
        self.assertEqual(
            logic._scan_target_artificial_values,
            logic._commanded_artificial_values,
        )

    def test_force_stop_preserves_the_last_completed_waypoint(self):
        writes = []
        applied_states = []
        abort_checks = 0

        def should_abort():
            nonlocal abort_checks
            abort_checks += 1
            return abort_checks == 3

        logic = make_logic(
            lambda value, channel: writes.append((channel, value)),
            limits_x=(-1.0, 1.0),
            should_abort=should_abort,
            resolve_device_label=lambda _channel: "shared_device",
        )
        logic.sig_state_changed.connect(
            lambda state: applied_states.append(dict(state))
        )

        result = logic.set_channel_value("x", 0.10, is_scan_write=True)

        self.assertTrue(result["aborted"])
        self.assertEqual(logic._commanded_artificial_values, {"x": 0.02, "y": 0.0})
        self.assertEqual(
            logic._scan_target_artificial_values,
            logic._commanded_artificial_values,
        )
        self.assertEqual(result["state"]["x"], 0.02)
        self.assertEqual(logic.read_channel_value("x"), 0.02)
        self.assertEqual(applied_states[-1], result["state"])
        self.assertEqual(
            [value for channel, value in writes if channel == "device_x_output"],
            [0.0, 0.02],
        )


class ArtificialChannelWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_target_and_current_labels_update_independently(self):
        logic = make_logic(lambda _value, _channel: None)
        widget = ArtificialChannel2D(
            logic,
            {"device_x": ["output"], "device_y": ["output"]},
        )
        try:
            logic.sig_target_changed.emit({"x": 0.5, "y": -0.25})
            logic.sig_state_changed.emit(
                {
                    "x": 0.1,
                    "y": -0.05,
                    "device_x_output": 0.1,
                    "device_y_output": -0.05,
                }
            )

            self.assertEqual(widget.ACx_value_label.text(), "0.500000")
            self.assertEqual(widget.ACy_value_label.text(), "-0.250000")
            self.assertEqual(widget.ACx_currentvalue_label.text(), "0.100000")
            self.assertEqual(widget.ACy_currentvalue_label.text(), "-0.050000")
            self.assertEqual(widget.OCx_value_label.text(), "0.100000")
            self.assertEqual(widget.OCy_value_label.text(), "-0.050000")
        finally:
            widget.close()

    def test_standard_log_reports_ready_state_and_limit_skip(self):
        logic = make_logic(lambda _value, _channel: None)
        widget = ArtificialChannel2D(
            logic,
            {"device_x": ["output"], "device_y": ["output"]},
        )
        try:
            logic.set_artificial_channel_values(3.0, 0.0)
            self.app.processEvents()
            log_text = widget.log_plainTextEdit.toPlainText()
            self.assertRegex(
                log_text,
                r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\] \[INFO\]",
            )
            self.assertIn("Artificial channel ready", log_text)
            self.assertIn("[WARNING]", log_text)
            self.assertIn("mapped original channels out of limit", log_text)
        finally:
            widget.close()


class ScanAbortTests(unittest.TestCase):
    def test_aborted_ramp_stops_remaining_artificial_channel_writes(self):
        calls = []

        class ArtificialChannel:
            @staticmethod
            def has_artificial_channel(_channel):
                return True

            @staticmethod
            def set_channel_value(channel, _value, is_scan_write=False):
                calls.append((channel, is_scan_write))
                return {"aborted": True}

        scan_logic = SimpleNamespace(
            main_window=SimpleNamespace(artificial_channel_logic=ArtificialChannel()),
            received_stop=False,
        )

        ScanLogic.write_single_device_all_channels(
            scan_logic,
            "artificial_channel",
            {"x": 0.1, "y": 0.2},
            level_index=0,
            target_index=0,
        )

        self.assertEqual(calls, [("x", True)])
        self.assertTrue(scan_logic.received_stop)


class ForceStopFlagTests(unittest.TestCase):
    def test_force_stop_stays_set_until_equipment_restart(self):
        class Equipment:
            def force_stop(self):
                pass

            def stop_scan(self):
                pass

            def start_scan(self):
                pass

        main_window = SimpleNamespace(
            _force_stop_requested=False,
            equips={"device": Equipment()},
        )

        MainWindow.force_stop_equipments(main_window)
        MainWindow.stop_equipments_for_scanning(main_window)
        self.assertTrue(main_window._force_stop_requested)

        MainWindow.start_equipments(main_window)
        self.assertFalse(main_window._force_stop_requested)

    def test_equipment_restart_is_suppressed_during_shutdown(self):
        class Manager:
            shutdown_started = True

            def __init__(self):
                self.start_calls = 0

            def start_after_scan(self):
                self.start_calls += 1

        manager = Manager()
        main_window = SimpleNamespace(
            _force_stop_requested=True,
            _session_shutdown_in_progress=True,
            _shutdown_retry_required=False,
            _session_shutdown_complete=False,
            device_manager=manager,
            equips={},
        )

        self.assertIsNone(MainWindow.start_equipments(main_window))
        self.assertTrue(main_window._force_stop_requested)
        self.assertEqual(manager.start_calls, 0)


if __name__ == "__main__":
    unittest.main()
