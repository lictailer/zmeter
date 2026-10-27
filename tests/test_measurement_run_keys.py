"""Numeric scan links and temporary run bundles only; no hardware imports."""
from datetime import datetime
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from core.measurement_records import RunRecord, new_run_key


class RunKeyTests(unittest.TestCase):
    def test_local_timestamp_format_and_scan_float_round_trip(self):
        for when, expected in ((datetime(2026, 10, 22, 18, 12, 50), 20261022181250),
                               (datetime(2027, 1, 1, 0, 0, 0), 20270101000000)):
            with self.subTest(when=when), mock.patch("core.measurement_records.datetime") as clock:
                clock.now.return_value = when
                key = new_run_key()
                clock.now.assert_called_once_with()
                self.assertEqual(key, expected)
                self.assertEqual(int(float(key)), key)

    def test_key_survives_run_json_updates_without_mutating_caller(self):
        with tempfile.TemporaryDirectory() as directory:
            record = RunRecord(directory, "autofocus", run_key=20261022181250)
            self.assertIn("autofocus-20261022181250-", record.path.name)
            for status in ("running", "complete", "stopped", "error"):
                payload = {"status": status}
                record.json("run.json", payload)
                self.assertEqual(payload, {"status": status})
                self.assertEqual(json.loads((record.path / "run.json").read_text()),
                                 {"status": status, "run_key": 20261022181250})
            record.json("settings.json", {"schema_version": 1})
            self.assertNotIn("run_key", json.loads((record.path / "settings.json").read_text()))

    def test_runs_in_same_second_keep_distinct_folders(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch(
                "core.measurement_records.new_run_key", return_value=20261022181250):
            first, second = RunRecord(directory, "auto-position"), RunRecord(directory, "auto-position")
            self.assertEqual(first.run_key, second.run_key)
            self.assertNotEqual(first.path, second.path)
            self.assertEqual(len(list(Path(directory).iterdir())), 2)
            for record in (first, second):
                self.assertEqual(json.loads((record.path / "run.json").read_text())["run_key"], record.run_key)


if __name__ == "__main__":
    unittest.main()
