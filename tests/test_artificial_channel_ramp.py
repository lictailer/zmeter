import sys
import threading
import types
import unittest
from types import SimpleNamespace

if "win32com" not in sys.modules:
    win32com_module = types.ModuleType("win32com")
    win32com_client_module = types.ModuleType("win32com.client")
    win32com_module.client = win32com_client_module
    sys.modules["win32com"] = win32com_module
    sys.modules["win32com.client"] = win32com_client_module

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


class ArtificialChannelRampTests(unittest.TestCase):
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
        self.assertTrue(all(-0.05 <= value <= 0.05 for _channel, value in writes))
        self.assertTrue(logic.consume_skip_read_for_scan())

    def test_force_stop_preserves_the_last_completed_waypoint(self):
        writes = []
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

        result = logic.set_channel_value("x", 0.10, is_scan_write=True)

        self.assertTrue(result["aborted"])
        self.assertEqual(logic._commanded_artificial_values, {"x": 0.02, "y": 0.0})
        self.assertEqual(result["state"]["x"], 0.02)
        self.assertEqual(
            [value for channel, value in writes if channel == "device_x_output"],
            [0.0, 0.02],
        )


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


if __name__ == "__main__":
    unittest.main()
