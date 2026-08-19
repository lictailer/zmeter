import os
import threading
import unittest
from unittest import mock

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets

from core.scan_logic import ScanLogic
from core.scanlist import ScanListLogic


class _NoArtificialChannels:
    artificial_channels = ()

    @staticmethod
    def consume_skip_read_for_scan():
        return False

    @staticmethod
    def has_artificial_channel(_channel):
        return False


class _ScalarMainWindow:
    def __init__(self):
        self.equips = {"alpha_device": object(), "beta": object()}
        self.artificial_channel_logic = _NoArtificialChannels()
        self.writes = []
        self.reads = []
        self._read_counts = {}
        self._lock = threading.Lock()

    def write_info(self, value, channel):
        with self._lock:
            self.writes.append((channel, float(value)))

    def read_info(self, channel):
        values = {
            "alpha_device_g1": [11.0, 13.0, 21.0, 23.0],
            "alpha_device_g2": [101.0, 103.0, 201.0, 203.0],
            "beta_g3": [1001.0, 1003.0, 2001.0, 2003.0],
            "beta_outer_read": [9001.0, 9002.0],
        }
        with self._lock:
            index = self._read_counts.get(channel, 0)
            self._read_counts[channel] = index + 1
            self.reads.append(channel)
        return values[channel][index]


def _scalar_scan_config():
    return {
        "levels": {
            "level0": {
                "setters": {
                    "setter0": {"channel": "alpha_device_x"},
                    "setter1": {"channel": "alpha_device_y"},
                    "setter2": {"channel": "beta_z"},
                },
                "getters": [
                    "alpha_device_g1",
                    "alpha_device_g2",
                    "beta_g3",
                ],
                "setting_array": np.array(
                    [[10.0, 20.0], [100.0, 200.0], [1000.0, 2000.0]]
                ),
                "settle_time": 0.0,
                "start_wait_time": 0.0,
                "manual_set_before": [],
                "manual_set_after": [],
            },
            "level1": {
                "setters": {"setter0": {"channel": "beta_outer"}},
                "getters": [
                    "beta_outer_read",
                    "level0_average_alpha_device_g1",
                ],
                "setting_array": np.array([[1.0, 2.0]]),
                "settle_time": 0.0,
                "start_wait_time": 0.0,
                "manual_set_before": [],
                "manual_set_after": [],
            },
        }
    }


class ScanScalarRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_nested_scalar_shape_dtype_order_grouping_average_and_signals(self):
        main_window = _ScalarMainWindow()
        logic = ScanLogic(main_window=main_window)
        payloads = []
        logic.sig_new_data.connect(payloads.append)
        logic.initialize_scan_data(_scalar_scan_config())

        self.assertEqual(
            [array.shape for array in logic.level_data_arrays],
            [(3, 2, 2), (2, 2)],
        )
        self.assertTrue(
            all(array.dtype == np.dtype("float64") for array in logic.level_data_arrays)
        )
        self.assertEqual(
            logic.group_reading_device_channels(0),
            {"alpha_device": ["g1", "g2"], "beta": ["g3"]},
        )

        write_payload = logic._build_write_payload(0, 0)
        self.assertEqual(list(write_payload), ["alpha_device", "beta"])
        self.assertEqual(list(write_payload["alpha_device"]), ["x", "y"])
        self.assertEqual(list(write_payload["beta"]), ["z"])

        logic.looping(logic.max_level)

        np.testing.assert_array_equal(
            logic.level_data_arrays[0][0], [[11.0, 13.0], [21.0, 23.0]]
        )
        np.testing.assert_array_equal(
            logic.level_data_arrays[0][1], [[101.0, 103.0], [201.0, 203.0]]
        )
        np.testing.assert_array_equal(
            logic.level_data_arrays[0][2], [[1001.0, 1003.0], [2001.0, 2003.0]]
        )
        np.testing.assert_array_equal(
            logic.level_data_arrays[1][0], [9001.0, 9002.0]
        )
        np.testing.assert_array_equal(logic.level_data_arrays[1][1], [12.0, 22.0])

        self.assertEqual(main_window.reads.count("alpha_device_g1"), 4)
        self.assertEqual(main_window.reads.count("alpha_device_g2"), 4)
        self.assertEqual(main_window.reads.count("beta_g3"), 4)
        self.assertEqual(main_window.reads.count("beta_outer_read"), 2)
        alpha_writes = [
            channel
            for channel, _value in main_window.writes
            if channel.startswith("alpha_device_")
        ]
        self.assertEqual(alpha_writes, ["alpha_device_x", "alpha_device_y"] * 4)

        metadata = [payload[2] for payload in payloads]
        self.assertEqual(len(metadata), 8)
        self.assertEqual(
            [entry["phase"] for entry in metadata].count("average"),
            2,
        )
        self.assertEqual(
            [
                (entry["source_level"], entry["changed_getter_indices"], entry["phase"])
                for entry in metadata
                if entry["source_level"] == 1
            ],
            [
                (1, [0], "direct"),
                (1, [1], "average"),
                (1, [0], "direct"),
                (1, [1], "average"),
            ],
        )

    def test_duplicate_and_nan_setters_keep_current_payload_rules(self):
        main_window = _ScalarMainWindow()
        logic = ScanLogic(main_window=main_window)
        config = _scalar_scan_config()
        config["levels"]["level0"]["setters"] = {
            "setter0": {"channel": "alpha_device_x"},
            "setter1": {"channel": "alpha_device_x"},
            "setter2": {"channel": "beta_z"},
        }
        config["levels"]["level0"]["setting_array"] = np.array(
            [[1.0, np.nan], [2.0, 3.0], [np.nan, 4.0]]
        )
        logic.initialize_scan_data(config)

        first = logic._build_write_payload(0, 0)
        second = logic._build_write_payload(0, 1)
        self.assertEqual(list(first), ["alpha_device"])
        self.assertEqual(first["alpha_device"], {"x": 1.0})
        self.assertEqual(
            second,
            {"alpha_device": {"x": 3.0}, "beta": {"z": 4.0}},
        )

    def test_pause_resume_stop_and_hourly_autosave_trigger_are_stable(self):
        logic = ScanLogic(main_window=_ScalarMainWindow())
        autosaves = []
        logic.sig_auto_backup.connect(autosaves.append)

        logic.request_pause()
        self.assertTrue(logic.received_pause)
        self.assertFalse(logic.received_stop)
        logic.request_resume()
        self.assertFalse(logic.received_pause)
        self.assertFalse(logic.received_stop)
        logic.request_pause()
        logic.request_stop()
        self.assertFalse(logic.received_pause)
        self.assertTrue(logic.received_stop)

        logic.scan_start_time = 1000.0
        logic.last_auto_hour_triggered = 0
        with mock.patch("core.scan_logic.time.time", return_value=4599.0):
            logic.check_auto_backup_trigger()
        with mock.patch("core.scan_logic.time.time", return_value=4601.0):
            logic.check_auto_backup_trigger()
            logic.check_auto_backup_trigger()
        with mock.patch("core.scan_logic.time.time", return_value=8201.0):
            logic.check_auto_backup_trigger()

        self.assertEqual(autosaves, [True, True])
        self.assertEqual(logic.last_auto_hour_triggered, 2)


class _QueueWorker:
    def __init__(self, name, events):
        self.name = name
        self._events = events

    def start_queue(self):
        self._events.append(("run", self.name))


class ScanQueueRegressionTests(unittest.TestCase):
    def test_queue_preserves_order_and_clears_current_worker(self):
        logic = ScanListLogic()
        events = []
        workers = [_QueueWorker(name, events) for name in ("first", "second", "third")]
        logic.workers = list(workers)
        logic.sig_item_started.connect(
            lambda worker: events.append(("start", worker.name))
        )
        logic.sig_scan_done.connect(lambda worker: events.append(("done", worker.name)))
        logic.sig_item_finished.connect(
            lambda payload: events.append(("finish", payload["worker"].name))
        )
        stop_reasons = []
        logic.sig_queue_stopped.connect(stop_reasons.append)

        with mock.patch.object(QtCore.QThread, "sleep", return_value=None):
            logic.run()

        self.assertEqual(
            events,
            [
                ("start", "first"),
                ("run", "first"),
                ("done", "first"),
                ("finish", "first"),
                ("start", "second"),
                ("run", "second"),
                ("done", "second"),
                ("finish", "second"),
                ("start", "third"),
                ("run", "third"),
                ("done", "third"),
                ("finish", "third"),
            ],
        )
        self.assertEqual(stop_reasons, ["completed"])
        self.assertEqual(logic.workers, [])
        self.assertIsNone(logic.current_worker)


if __name__ == "__main__":
    unittest.main()
