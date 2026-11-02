import math
import threading
import unittest

import numpy as np

from core.shift_compensation.fitting import MappingFitError
from core.shift_compensation.logic import (
    Mapping,
    ShiftCompensationError,
    ShiftCompensationLogic,
    evaluate_points,
)
from tests.shift_compensation_fixture import FakeLab, g_x, g_y


class CompensatedSourceTests(unittest.TestCase):
    def test_source_setter_keeps_the_spot_still(self):
        lab = FakeLab()
        lab.add_xy_mappings()
        lab.values.update(rot_angle=10.0, daq_AO0=0.1, daq_AO1=-0.05)
        spot = (lab.read_info("spot_x"), lab.read_info("spot_y"))
        for angle in (25.0, 90.0, 170.0, 300.0):
            self.assertTrue(lab.write_info(angle, "compensated_source_rot_angle"))
            self.assertEqual(lab.values["rot_angle"], angle)
            self.assertAlmostEqual(lab.read_info("spot_x"), spot[0], places=9)
            self.assertAlmostEqual(lab.read_info("spot_y"), spot[1], places=9)

    def test_order_is_read_source_read_targets_set_source_set_targets(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        lab.reads.clear()
        lab.writes.clear()
        lab.write_info(30.0, "compensated_source_rot_angle")
        self.assertEqual(lab.reads, ["rot_angle", "daq_AI0"])
        self.assertEqual([c for c, _v in lab.writes], ["rot_angle", "daq_AO0"])

    def test_corrections_onto_one_target_add_up(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_y)
        lab.values.update(rot_angle=0.0, daq_AO0=0.2)
        lab.write_info(60.0, "compensated_source_rot_angle")
        expected = 0.2 + (g_x(60) - g_x(0)) + (g_y(60) - g_y(0))
        self.assertAlmostEqual(lab.values["daq_AO0"], float(expected), places=6)

    def test_denied_source_write_leaves_targets_alone(self):
        lab = FakeLab()
        lab.add_xy_mappings()
        lab.values.update(daq_AO0=0.1, daq_AO1=0.2)
        lab.denied["rot_angle"] = (0.0, 180.0)
        self.assertFalse(lab.write_info(200.0, "compensated_source_rot_angle"))
        self.assertEqual(lab.values["daq_AO0"], 0.1)
        self.assertEqual(lab.values["daq_AO1"], 0.2)
        self.assertEqual(lab.values["rot_angle"], 0.0)

    def test_denied_target_write_is_reported(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        lab.denied["daq_AO0"] = (-0.001, 0.001)
        self.assertFalse(lab.write_info(45.0, "compensated_source_rot_angle"))
        self.assertEqual(lab.values["rot_angle"], 45.0)

    def test_nan_is_not_written(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        self.assertFalse(lab.logic.write_source("rot_angle", math.nan))
        self.assertFalse(lab.logic.write_target("daq_AO0", math.nan))
        self.assertEqual(lab.writes, [])

    def test_unpublished_source_raises(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x, activate=False)
        with self.assertRaises(ShiftCompensationError):
            lab.logic.write_source("rot_angle", 1.0)
        with self.assertRaises(ShiftCompensationError):
            lab.logic.read_target("daq_AO0")


class CompensatedTargetTests(unittest.TestCase):
    def test_target_setter_adds_correction_from_reference(self):
        lab = FakeLab()
        mapping = lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        lab.values["rot_angle"] = 80.0
        lab.write_info(0.1, "compensated_target_daq_AO0")
        expected = 0.1 + g_x(80.0) - g_x(mapping.source_values[0])
        self.assertAlmostEqual(lab.values["daq_AO0"], float(expected), places=6)
        # The getter returns the physical value, not the requested one.
        self.assertAlmostEqual(
            lab.read_info("compensated_target_daq_AO0"), float(expected), places=6
        )

    def test_reference_value_only_shifts_by_a_constant(self):
        spots = []
        for x_ref in (None, 45.0):
            lab = FakeLab()
            lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x, x_ref=x_ref)
            row = []
            for angle in (0.0, 30.0, 120.0):
                lab.write_info(angle, "rot_angle")
                lab.write_info(0.1, "compensated_target_daq_AO0")
                row.append(lab.read_info("spot_x"))
            spots.append(np.array(row))
        np.testing.assert_allclose(np.ptp(spots[0]), 0.0, atol=1e-6)
        np.testing.assert_allclose(np.ptp(spots[1]), 0.0, atol=1e-6)
        np.testing.assert_allclose(spots[1] - spots[0], (g_x(0) - g_x(45))[()] * np.ones(3), atol=1e-6)

    def test_target_setter_does_not_read_the_target(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        lab.reads.clear()
        lab.write_info(0.1, "compensated_target_daq_AO0")
        self.assertNotIn("daq_AI0", lab.reads)

    def test_source_is_read_once_until_it_is_written(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        lab.write_info(20.0, "rot_angle")
        lab.reads.clear()
        for value in np.linspace(-0.1, 0.1, 10):
            lab.write_info(value, "compensated_target_daq_AO0")
        self.assertEqual(lab.reads_of("rot_angle"), 1)
        lab.write_info(40.0, "rot_angle")
        lab.write_info(0.0, "compensated_target_daq_AO0")
        lab.write_info(0.0, "compensated_target_daq_AO0")
        self.assertEqual(lab.reads_of("rot_angle"), 2)
        lab.logic.mark_sources_stale()
        lab.write_info(0.0, "compensated_target_daq_AO0")
        self.assertEqual(lab.reads_of("rot_angle"), 3)

    def test_compensated_source_write_also_refreshes_the_reading(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        lab.write_info(50.0, "compensated_source_rot_angle")
        lab.reads.clear()
        lab.write_info(0.0, "compensated_target_daq_AO0")
        # The compensated write recorded a write to rot_angle after its read.
        self.assertEqual(lab.reads_of("rot_angle"), 1)

    def test_parallel_target_writes_use_one_lock_per_target(self):
        lab = FakeLab()
        lab.add_xy_mappings()
        errors = []

        def worker(channel):
            try:
                for value in np.linspace(0, 0.1, 50):
                    lab.write_info(value, channel)
            except Exception as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(name,))
            for name in ("compensated_target_daq_AO0", "compensated_target_daq_AO1")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])


class ActivationTests(unittest.TestCase):
    def test_activation_problems(self):
        lab = FakeLab()
        mapping = lab.logic.add_mapping()
        with self.assertRaises(ShiftCompensationError) as caught:
            lab.logic.activate(mapping.mapping_id)
        text = str(caught.exception)
        self.assertIn("no fit yet", text)
        self.assertIn("source set channel not chosen", text)

    def test_unavailable_and_same_channels_are_refused(self):
        lab = FakeLab()
        mapping = lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x, activate=False)
        lab.logic.update_mapping(mapping.mapping_id, target_set="rot_angle")
        problems = lab.logic.activation_problems(
            lab.logic.get(mapping.mapping_id), FakeLab.SETTERS, FakeLab.GETTERS
        )
        self.assertIn("source and target set channels are the same", problems)
        lab.logic.update_mapping(mapping.mapping_id, target_set="daq_AO9")
        problems = lab.logic.activation_problems(
            lab.logic.get(mapping.mapping_id), FakeLab.SETTERS, FakeLab.GETTERS
        )
        self.assertTrue(any("not available" in p for p in problems))
        lab.logic.update_mapping(
            mapping.mapping_id, target_set="compensated_target_daq_AO0"
        )
        problems = lab.logic.activation_problems(
            lab.logic.get(mapping.mapping_id), ["compensated_target_daq_AO0", "rot_angle"], FakeLab.GETTERS
        )
        self.assertTrue(any("compensated channel" in p for p in problems))

    def test_chaining_is_refused_both_ways(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        chained = lab.add_fitted_mapping(
            "daq_AO1", "daq_AI1", g_y, activate=False,
            source_set="daq_AO0", source_read="daq_AI0",
        )
        with self.assertRaisesRegex(ShiftCompensationError, "chaining"):
            lab.logic.activate(chained.mapping_id)
        reverse = lab.add_fitted_mapping(
            "rot_angle", "rot_angle", g_y, activate=False,
            source_set="daq_AO1", source_read="daq_AI1",
        )
        with self.assertRaisesRegex(ShiftCompensationError, "chaining"):
            lab.logic.activate(reverse.mapping_id)

    def test_shared_source_must_use_one_read_channel(self):
        lab = FakeLab()
        lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        other = lab.add_fitted_mapping(
            "daq_AO1", "daq_AI1", g_y, activate=False, source_read="spot_x"
        )
        with self.assertRaisesRegex(ShiftCompensationError, "read through"):
            lab.logic.activate(other.mapping_id)

    def test_active_mapping_is_read_only(self):
        lab = FakeLab()
        mapping = lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        with self.assertRaises(ShiftCompensationError):
            lab.logic.update_mapping(mapping.mapping_id, name="x")
        with self.assertRaises(ShiftCompensationError):
            lab.logic.fit(mapping.mapping_id)
        with self.assertRaises(ShiftCompensationError):
            lab.logic.set_points(mapping.mapping_id, [0, 1], [0, 1])
        lab.logic.deactivate(mapping.mapping_id)
        lab.logic.update_mapping(mapping.mapping_id, name="renamed")
        self.assertEqual(lab.logic.get(mapping.mapping_id).display_name, "renamed")

    def test_lost_channels_deactivate_with_a_note(self):
        lab = FakeLab()
        mapping = lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        messages = lab.logic.set_available_channels(["rot_angle"], FakeLab.GETTERS)
        self.assertEqual(len(messages), 1)
        self.assertFalse(lab.logic.get(mapping.mapping_id).active)
        self.assertIn("not available", lab.logic.get(mapping.mapping_id).note)
        self.assertEqual(lab.logic.published_channels(), ((), ()))

    def test_published_and_physical_channels(self):
        lab = FakeLab()
        lab.add_xy_mappings()
        self.assertEqual(
            lab.logic.published_channels(),
            (("rot_angle",), ("daq_AO0", "daq_AO1")),
        )
        self.assertEqual(
            lab.logic.published_channels(["rot_angle", "daq_AO0"], FakeLab.GETTERS),
            (("rot_angle",), ("daq_AO0",)),
        )
        self.assertEqual(
            set(lab.logic.physical_channels("compensated_source_rot_angle")),
            {"rot_angle", "daq_AO0", "daq_AI0", "daq_AO1", "daq_AI1"},
        )
        self.assertEqual(
            set(lab.logic.physical_channels("compensated_target_daq_AO1")),
            {"rot_angle", "daq_AO1", "daq_AI1"},
        )
        self.assertEqual(lab.logic.physical_channels("rot_angle"), ())

    def test_load_mappings_reactivates_only_valid_ones(self):
        lab = FakeLab()
        good, other = lab.add_xy_mappings()
        lab.logic.deactivate(other.mapping_id)
        lab.logic.update_mapping(other.mapping_id, target_set="daq_AO9")
        saved = [m for m in lab.logic.capture_state()]
        saved[1].active = True
        notes = lab.logic.load_mappings(saved)
        self.assertEqual(len(notes), 1)
        loaded = {m.mapping_id: m for m in lab.logic.mappings()}
        self.assertTrue(loaded[good.mapping_id].active)
        self.assertFalse(loaded[other.mapping_id].active)
        self.assertIn("daq_AO9", loaded[other.mapping_id].note)

    def test_capture_and_restore_state(self):
        lab = FakeLab()
        mapping = lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x)
        state = lab.logic.capture_state()
        lab.logic.deactivate(mapping.mapping_id)
        lab.logic.remove_mapping(mapping.mapping_id)
        lab.logic.restore_state(state)
        self.assertTrue(lab.logic.get(mapping.mapping_id).active)


class RecordTests(unittest.TestCase):
    def test_begin_scan_record_and_summary(self):
        lab = FakeLab()
        lab.add_xy_mappings()
        lab.read_info("rot_angle")
        record = lab.logic.begin_scan(scan_name="qwp_map", serial="0071")
        self.assertEqual(record["scan"], {"name": "qwp_map", "serial": "0071"})
        self.assertEqual(record["channels"]["source"], ["compensated_source_rot_angle"])
        self.assertEqual(
            record["channels"]["target"],
            ["compensated_target_daq_AO0", "compensated_target_daq_AO1"],
        )
        self.assertEqual(len(record["active"]), 2)
        self.assertIn("recorded_at", record)
        self.assertIsNone(lab.channel_value_record.fresh_reading("rot_angle", "rot_angle"))
        lines = lab.logic.summary_lines()
        self.assertEqual(len(lines), 2)
        self.assertIn("rot_angle -> daq_AO0", lines[0])

    def test_mapping_round_trip(self):
        lab = FakeLab()
        mapping = lab.add_fitted_mapping("daq_AO0", "daq_AI0", g_x, x_ref=12.5, name="QWP→X")
        again = Mapping.from_dict(mapping.to_dict())
        self.assertEqual(again.to_dict(), mapping.to_dict())
        self.assertAlmostEqual(again.correction(0, 50), mapping.correction(0, 50))
        x, y = evaluate_points(again, 50)
        self.assertEqual(len(x), 50)
        np.testing.assert_allclose(y, g_x(x), atol=1e-9)

    def test_fit_without_points(self):
        logic = ShiftCompensationLogic(lambda v, c: None, lambda c: 0.0)
        mapping = logic.add_mapping()
        with self.assertRaises(MappingFitError):
            logic.fit(mapping.mapping_id)


if __name__ == "__main__":
    unittest.main()
