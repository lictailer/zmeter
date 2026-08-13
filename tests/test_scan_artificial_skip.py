import io
import unittest
from contextlib import redirect_stdout

import numpy as np

from core.artificial_channel_logic import ArtificialChannelLogic
from core.scan_logic import ScanLogic


class FakeArtificialChannelLogic:
    artificial_channels = ("n", "E")

    def __init__(self, rejected_values=()):
        self.rejected_values = set(rejected_values)
        self.skip_read = False

    def has_artificial_channel(self, channel):
        return channel == "E"

    def set_channel_value(self, _channel, value, is_scan_write=False):
        self.skip_read = is_scan_write and value in self.rejected_values
        return {"skipped": self.skip_read}

    def consume_skip_read_for_scan(self):
        return self.skip_read


class FakeMainWindow:
    def __init__(self, rejected_values=()):
        self.equips = {"mock": object()}
        self.artificial_channel_logic = FakeArtificialChannelLogic(rejected_values)
        self.writes = []
        self.reads = []

    def write_info(self, value, channel):
        self.writes.append((channel, value))

    def read_info(self, channel):
        self.reads.append(channel)
        return float(len(self.reads))


class CoupledArtificialMainWindow:
    def __init__(self):
        self.equips = {
            "mock_device_1": object(),
            "mock_device_2": object(),
        }
        self.values = {
            "mock_device_1_channel_A": 0.0,
            "mock_device_2_channel_B": 0.0,
        }
        self.artificial_channel_logic = ArtificialChannelLogic(
            write_channel=self.write_info,
            read_channel=self.read_info,
            original_channel_x_name="mock_device_1_channel_A",
            original_channel_y_name="mock_device_2_channel_B",
            artificial_channel_x_name="n",
            artificial_channel_y_name="E",
            original_channel_x_limits=(-1.0, 1.0),
            original_channel_y_limits=(-1.0, 1.0),
            resolve_device_label=lambda _channel: "shared_mock",
        )
        self.artificial_channel_logic.RAMP_INTER_STEP_DELAY_S = 0.0

    def write_info(self, value, channel):
        self.values[channel] = value

    def read_info(self, channel):
        return self.values[channel]


def make_scan_config(outer_channel):
    return {
        "levels": {
            "level0": {
                "setters": {"setter0": {"channel": "mock_inner"}},
                "getters": ["mock_read"],
                "setting_array": np.array([[10.0, 20.0]]),
                "settle_time": 0.0,
                "start_wait_time": 0.0,
                "manual_set_before": [],
                "manual_set_after": [],
            },
            "level1": {
                "setters": {"setter0": {"channel": outer_channel}},
                "getters": ["none"],
                "setting_array": np.array([[0.0, 1.0]]),
                "settle_time": 0.0,
                "start_wait_time": 0.0,
                "manual_set_before": [],
                "manual_set_after": [],
            },
        }
    }


def make_coupled_scan_config():
    targets = np.linspace(-3.0, 3.0, 31)
    return {
        "levels": {
            "level0": {
                "setters": {"setter0": {"channel": "artificial_channel_n"}},
                "getters": [
                    "mock_device_1_channel_A",
                    "mock_device_2_channel_B",
                    "artificial_channel_n",
                ],
                "setting_array": np.array([targets]),
                "settle_time": 0.0,
                "start_wait_time": 0.0,
                "manual_set_before": [],
                "manual_set_after": [],
            },
            "level1": {
                "setters": {"setter0": {"channel": "artificial_channel_E"}},
                "getters": ["none"],
                "setting_array": np.array([targets]),
                "settle_time": 0.0,
                "start_wait_time": 0.0,
                "manual_set_before": [],
                "manual_set_after": [],
            },
        }
    }


class ScanArtificialSkipTests(unittest.TestCase):
    def test_rejected_outer_artificial_write_skips_only_its_inner_slice(self):
        main_window = FakeMainWindow(rejected_values={0.0})
        logic = ScanLogic(main_window=main_window)
        logic.initialize_scan_data(make_scan_config("artificial_channel_E"))

        logic.looping(logic.max_level)

        inner_data = logic.level_data_arrays[0][0]
        self.assertTrue(np.isnan(inner_data[0]).all())
        self.assertTrue(np.isfinite(inner_data[1]).all())
        self.assertEqual(
            main_window.writes,
            [("mock_inner", 10.0), ("mock_inner", 20.0)],
        )
        self.assertEqual(main_window.reads, ["mock_read", "mock_read"])

    def test_non_artificial_outer_write_still_runs_every_inner_slice(self):
        main_window = FakeMainWindow()
        logic = ScanLogic(main_window=main_window)
        logic.initialize_scan_data(make_scan_config("mock_outer"))

        logic.looping(logic.max_level)

        inner_data = logic.level_data_arrays[0][0]
        self.assertTrue(np.isfinite(inner_data).all())
        self.assertEqual(len(main_window.reads), 4)

    def test_nested_artificial_pair_measures_both_halves_without_mislabeling(self):
        main_window = CoupledArtificialMainWindow()
        logic = ScanLogic(main_window=main_window)
        config = make_coupled_scan_config()
        logic.initialize_scan_data(config)

        with redirect_stdout(io.StringIO()):
            logic.looping(logic.max_level)

        channel_a = logic.level_data_arrays[0][0]
        channel_b = logic.level_data_arrays[0][1]
        artificial_n = logic.level_data_arrays[0][2]
        finite_mask = (
            np.isfinite(channel_a)
            & np.isfinite(channel_b)
            & np.isfinite(artificial_n)
        )
        targets = config["levels"]["level0"]["setting_array"][0]
        expected_mask = np.zeros_like(finite_mask)

        for e_index, e_value in enumerate(targets):
            for n_index, n_value in enumerate(targets):
                physical = main_window.artificial_channel_logic._artificial_to_original_coordinate(
                    n_value,
                    e_value,
                )
                expected_mask[e_index, n_index] = (
                    main_window.artificial_channel_logic._is_original_coordinate_within_limits(
                        *physical
                    )
                )

                if not finite_mask[e_index, n_index]:
                    continue
                self.assertAlmostEqual(
                    channel_a[e_index, n_index] + channel_b[e_index, n_index],
                    n_value,
                )
                self.assertAlmostEqual(
                    channel_a[e_index, n_index] - channel_b[e_index, n_index],
                    e_value,
                )
                self.assertAlmostEqual(
                    artificial_n[e_index, n_index],
                    n_value,
                )

        self.assertTrue(np.array_equal(finite_mask, expected_mask))
        self.assertTrue(finite_mask[targets < 0].any())
        self.assertTrue(finite_mask[targets > 0].any())


if __name__ == "__main__":
    unittest.main()
