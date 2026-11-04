"""ScanHooks and ScanFinished on their own (no Qt, no scan window)."""

import dataclasses
import unittest

from core.scan_hooks import ScanFinished, ScanHooks


def _event(**overrides):
    fields = dict(
        name="0007_gate_map",
        status="completed",
        elapsed_seconds=12.5,
        completed_points=4,
        total_points=4,
        json_path="C:/data/0007_gate_map.json",
        error_message=None,
        queue_run=False,
    )
    fields.update(overrides)
    return ScanFinished(**fields)


class ScanFinishedTests(unittest.TestCase):
    def test_record_is_frozen_and_png_defaults_to_none(self):
        event = _event()
        self.assertIsNone(event.plot_png)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            event.status = "error"


class ScanHooksTests(unittest.TestCase):
    def setUp(self):
        self.warnings = []
        self.hooks = ScanHooks()

    def test_hooks_run_in_registration_order(self):
        calls = []
        self.hooks.register_scan_finished(lambda event: calls.append(("a", event)))
        self.hooks.register_scan_finished(lambda event: calls.append(("b", event)))
        event = _event()

        self.hooks.emit_scan_finished(event, self.warnings.append)

        self.assertEqual(calls, [("a", event), ("b", event)])
        self.assertEqual(self.warnings, [])

    def test_failing_hook_is_reported_by_name_and_others_still_run(self):
        calls = []

        def broken(_event):
            raise ValueError("bad")

        self.hooks.register_scan_finished(broken)
        self.hooks.register_scan_finished(calls.append, name="recorder")
        self.hooks.emit_scan_finished(_event(), self.warnings.append)

        self.assertEqual(len(calls), 1)
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("'ScanHooksTests.test_failing_hook_is_reported_by_name", self.warnings[0])
        self.assertIn("ValueError: bad", self.warnings[0])

    def test_unregister_removes_the_hook_once(self):
        calls = []
        unregister = self.hooks.register_scan_finished(calls.append)
        self.assertTrue(self.hooks.has_scan_finished_hooks)

        unregister()
        unregister()
        self.hooks.emit_scan_finished(_event(), self.warnings.append)

        self.assertEqual(calls, [])
        self.assertFalse(self.hooks.has_scan_finished_hooks)

    def test_hooks_are_per_object(self):
        other = ScanHooks()
        other.register_scan_finished(lambda event: None)
        self.assertFalse(self.hooks.has_scan_finished_hooks)

    def test_plot_png_wanted_only_when_a_hook_says_so(self):
        self.assertFalse(self.hooks.wants_plot_png(self.warnings.append))
        self.hooks.register_scan_finished(lambda event: None)
        self.assertFalse(self.hooks.wants_plot_png(self.warnings.append))
        wanted = [False]
        self.hooks.register_scan_finished(
            lambda event: None, wants_plot_png=lambda: wanted[0]
        )
        self.assertFalse(self.hooks.wants_plot_png(self.warnings.append))
        wanted[0] = True
        self.assertTrue(self.hooks.wants_plot_png(self.warnings.append))

    def test_failing_plot_question_counts_as_no_and_is_reported(self):
        def broken():
            raise RuntimeError("no answer")

        self.hooks.register_scan_finished(
            lambda event: None, wants_plot_png=broken, name="asker"
        )
        self.assertFalse(self.hooks.wants_plot_png(self.warnings.append))
        self.assertEqual(len(self.warnings), 1)
        self.assertIn("'asker'", self.warnings[0])
        self.assertIn("RuntimeError: no answer", self.warnings[0])

    def test_register_rejects_non_callables(self):
        with self.assertRaises(TypeError):
            self.hooks.register_scan_finished(None)
        with self.assertRaises(TypeError):
            self.hooks.register_scan_finished(lambda event: None, wants_plot_png=True)


if __name__ == "__main__":
    unittest.main()
