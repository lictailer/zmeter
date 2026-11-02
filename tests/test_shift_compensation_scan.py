"""Shift Compensation inside ScanLogic: the two schemes from the plan.

Scheme 1: a single-spot waveplate sweep, either with one
``compensated_source_`` setter (form A) or with the raw angle plus
``compensated_target_`` setters held constant (form B).

Scheme 2: a map scan with the angle as the slowest level and the two
compensated targets as the map axes.
"""

import io
import unittest
from contextlib import redirect_stdout

import numpy as np

from core.scan_logic import ScanLogic
from tests.shift_compensation_fixture import FakeLab, g_x


def level(setters, values, getters):
    return {
        "setters": {
            f"setter{index}": {"channel": channel}
            for index, channel in enumerate(setters)
        },
        "getters": list(getters) or ["none"],
        "setting_array": np.array(values, dtype=float),
        "settle_time": 0.0,
        "start_wait_time": 0.0,
        "manual_set_before": [],
        "manual_set_after": [],
    }


def run(lab, levels):
    logic = ScanLogic(main_window=lab)
    logic.initialize_scan_data({"levels": {f"level{i}": lv for i, lv in enumerate(levels)}})
    with redirect_stdout(io.StringIO()):
        logic.looping(logic.max_level)
    return logic


ANGLES = np.arange(0.0, 181.0, 15.0)


class SchemeOneTests(unittest.TestCase):
    def test_form_a_single_compensated_source_setter(self):
        lab = FakeLab()
        lab.add_xy_mappings()
        lab.values.update(daq_AO0=0.1, daq_AO1=-0.05)
        start = (lab.read_info("spot_x"), lab.read_info("spot_y"))
        logic = run(
            lab,
            [level(["compensated_source_rot_angle"], [ANGLES], ["spot_x", "spot_y", "rot_angle"])],
        )
        spot_x, spot_y, angle = (logic.level_data_arrays[0][i] for i in range(3))
        np.testing.assert_allclose(angle, ANGLES)
        np.testing.assert_allclose(spot_x, start[0], atol=1e-6)
        np.testing.assert_allclose(spot_y, start[1], atol=1e-6)

    def test_form_b_raw_angle_with_constant_compensated_targets(self):
        lab = FakeLab()
        mx, my = lab.add_xy_mappings()
        constant = np.full_like(ANGLES, 0.1)
        logic = run(
            lab,
            [
                level(
                    [
                        "compensated_target_daq_AO0",
                        "rot_angle",
                        "compensated_target_daq_AO1",
                    ],
                    [constant, ANGLES, -constant],
                    ["spot_x", "spot_y", "compensated_target_daq_AO0"],
                )
            ],
        )
        spot_x, spot_y, ao0 = (logic.level_data_arrays[0][i] for i in range(3))
        # Same spot at every angle although the setters sit in one level.
        self.assertLess(np.ptp(spot_x), 1e-6)
        self.assertLess(np.ptp(spot_y), 1e-6)
        # The getter records the physical (compensated) AO value.
        self.assertGreater(np.ptp(ao0), 1e-3)
        self.assertAlmostEqual(
            float(spot_x[0]), 0.1 - float(mx.fit.evaluate(mx.reference_value())), places=6
        )

    def test_form_a_accumulates_readback_noise_form_b_does_not(self):
        spreads = {}
        for form in ("A", "B"):
            lab = FakeLab(readback_noise=1e-4, seed=3)
            lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
            angles = np.tile(ANGLES, 8)
            if form == "A":
                lab.values["daq_AO0"] = 0.1
                levels = [level(["compensated_source_rot_angle"], [angles], ["spot_x"])]
            else:
                levels = [
                    level(
                        ["rot_angle", "compensated_target_daq_AO0"],
                        [angles, np.full_like(angles, 0.1)],
                        ["spot_x"],
                    )
                ]
            logic = run(lab, levels)
            spreads[form] = float(np.ptp(logic.level_data_arrays[0][0]))
        self.assertLess(spreads["B"], 1e-6)
        self.assertGreater(spreads["A"], spreads["B"])


class SchemeTwoTests(unittest.TestCase):
    def test_map_is_the_same_at_every_angle_and_the_angle_is_read_once_per_step(self):
        lab = FakeLab()
        lab.add_xy_mappings()
        outer = [0.0, 45.0, 90.0]
        rows = np.linspace(-0.1, 0.1, 3)
        cols = np.linspace(-0.1, 0.1, 5)
        lab.reads.clear()
        logic = run(
            lab,
            [
                level(["compensated_target_daq_AO0"], [cols], ["spot_x", "spot_y"]),
                level(["compensated_target_daq_AO1"], [rows], []),
                level(["rot_angle"], [outer], []),
            ],
        )
        spot_x = np.asarray(logic.level_data_arrays[0][0])
        spot_y = np.asarray(logic.level_data_arrays[0][1])
        self.assertEqual(spot_x.shape, (3, 3, 5))
        for index in range(1, 3):
            np.testing.assert_allclose(spot_x[index], spot_x[0], atol=1e-9)
            np.testing.assert_allclose(spot_y[index], spot_y[0], atol=1e-9)
        # Map axes still step: columns differ by the requested step.
        np.testing.assert_allclose(np.diff(spot_x[0, 0]), np.diff(cols), atol=1e-9)
        # One fresh angle read per angle step; the rest come from the record.
        self.assertEqual(lab.reads_of("rot_angle"), len(outer))
        self.assertEqual(lab.reads_of("daq_AI0"), 0)

    def test_compensated_writes_run_after_plain_writes(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        lab.writes.clear()
        run(
            lab,
            [level(["compensated_target_daq_AO0", "rot_angle"], [[0.0, 0.0], [10.0, 20.0]], [])],
        )
        self.assertEqual(
            [channel for channel, _value in lab.writes],
            ["rot_angle", "daq_AO0", "rot_angle", "daq_AO0"],
        )

    def test_extract_device_from_channel_knows_the_groups(self):
        logic = ScanLogic(main_window=FakeLab())
        self.assertEqual(
            logic.extract_device_from_channel("compensated_target_daq_AO0"),
            ("compensated_target", "daq_AO0"),
        )
        self.assertEqual(
            logic.extract_device_from_channel("compensated_source_rot_angle"),
            ("compensated_source", "rot_angle"),
        )

    def test_setup_snapshot_feeds_the_record(self):
        lab = FakeLab()
        logic = ScanLogic(main_window=lab)

        class Run:
            def take(self):
                return {"devices": {"rot": {"fields": {"angle": 33.0}}}}

        logic.setup_capture = Run()
        ScanLogic.take_setup_snapshot(logic, "start")
        self.assertEqual(lab.channel_value_record.latest("rot_angle").value, 33.0)


if __name__ == "__main__":
    unittest.main()
