"""Offline checks for the four-tone write/read demo; no hardware access."""

import builtins
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch


FOLDER = Path(__file__).resolve().parents[1]


class FakeServer:
    def __init__(self):
        self.calls = []
        self.samples = {}
        self.stale = False
        self.missing_y = False
        self.xy = (3.0, 4.0)
        self.close_error = False
        self.fail_write = None
        self.settings = {"sigouts/0/range": 1.0, "sigouts/0/offset": 0.0}
        self.allowed_writes = set()
        for index in range(4):
            amplitude = f"sigouts/0/amplitudes/{index}"
            phase = f"demods/{index}/phaseshift"
            self.settings.update({amplitude: 0.0, phase: 0.0,
                                  f"demods/{index}/enable": 1,
                                  f"demods/{index}/rate": 100.0})
            self.allowed_writes.update((amplitude, phase))

    @staticmethod
    def short(path):
        assert path.startswith("/dev12345/")
        return path.removeprefix("/dev12345/")

    def getString(self, path):
        return {"/zi/devices/connected": "DEV12345",
                "/dev12345/features/devtype": "MFLI"}[path]

    def getDouble(self, path):
        self.calls.append(("read", path))
        return self.settings[self.short(path)]

    getInt = getDouble

    def syncSetDouble(self, path, value):
        node = self.short(path)
        if node not in self.allowed_writes:
            raise AssertionError(f"Out-of-scope write: {node}")
        self.calls.append(("write", node, value))
        if node == self.fail_write:
            raise RuntimeError("write failed")
        self.settings[node] = value
        return value

    def getSample(self, path):
        self.calls.append(("sample", path))
        self.samples[path] = self.samples.get(path, 0) + 1
        index = int(self.short(path).split("/")[1])
        result = {"timestamp": [2**60 + (0 if self.stale else self.samples[path])],
                  "x": [self.xy[0]], "y": [self.xy[1]],
                  "frequency": [1000.0 * (index + 1)], "phase": [999.0]}
        if self.missing_y:
            del result["y"]
        return result

    def disconnect(self):
        self.calls.append(("close",))
        if self.close_error:
            raise RuntimeError("close failed")


class WriteReadDemoTests(unittest.TestCase):
    def setUp(self):
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name == "zhinst" or name.startswith("zhinst."):
                raise AssertionError("Offline test attempted vendor import")
            return real_import(name, *args, **kwargs)

        guard = patch("builtins.__import__", side_effect=guarded_import)
        guard.start()
        self.addCleanup(guard.stop)
        with patch.object(sys, "path", [str(FOLDER), *sys.path]):
            spec = importlib.util.spec_from_file_location("write_read_demo", FOLDER / "write_read_demo.py")
            self.demo = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.demo)
        self.server = FakeServer()
        self.factory = Mock(return_value=self.server)
        self.sleep = Mock()
        self.error = io.StringIO()

    def run_demo(self, amplitudes=None, phases=None, settle=1.0):
        with redirect_stdout(io.StringIO()), redirect_stderr(self.error):
            return self.demo.run_demo("dev12345", "192.0.2.1", 8004,
                                      [0.001] * 4 if amplitudes is None else amplitudes,
                                      [0, 45, 90, 135] if phases is None else phases,
                                      settle, server_factory=self.factory, sleep=self.sleep)

    def test_only_eight_requested_writes_and_four_frequency_results(self):
        rows = self.run_demo()
        self.factory.assert_called_once_with("192.0.2.1", 8004, 6, allow_version_mismatch=True)
        writes = [call for call in self.server.calls if call[0] == "write"]
        self.assertEqual(len(writes), 8)
        self.assertEqual({call[1] for call in writes}, self.server.allowed_writes)
        self.assertEqual([row["frequency_hz"] for row in rows], [1000, 2000, 3000, 4000])
        for row in rows:
            self.assertEqual((row["x"], row["y"], row["r"]), (3, 4, 5))
            self.assertAlmostEqual(row["theta_deg"], 53.13010235415598)
        self.sleep.assert_called_once_with(1.0)
        last_write = max(i for i, call in enumerate(self.server.calls) if call[0] == "write")
        first_sample = next(i for i, call in enumerate(self.server.calls) if call[0] == "sample")
        self.assertLess(last_write, first_sample)
        self.assertEqual(self.server.calls[-1], ("close",))

    def test_invalid_settings_fail_before_connection(self):
        for kwargs in ({"amplitudes": [1]}, {"phases": [0]},
                       {"amplitudes": [math.nan] * 4}, {"phases": [181] * 4},
                       {"settle": 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_demo(**kwargs)
        self.factory.assert_not_called()

    def test_disabled_demod_fails_before_all_writes(self):
        self.server.settings["demods/3/enable"] = 0
        with self.assertRaisesRegex(ValueError, "demodulator 4"):
            self.run_demo()
        self.assertFalse(any(call[0] == "write" for call in self.server.calls))
        self.assertEqual(self.server.calls[-1], ("close",))

    def test_missing_fourth_channel_fails_before_all_writes(self):
        del self.server.settings["sigouts/0/amplitudes/3"]
        with self.assertRaises(KeyError):
            self.run_demo()
        self.assertFalse(any(call[0] == "write" for call in self.server.calls))

    def test_sum_of_tones_and_offset_must_fit_range(self):
        self.server.settings["sigouts/0/offset"] = 0.5
        with self.assertRaisesRegex(ValueError, "exceed"):
            self.run_demo(amplitudes=[0.2] * 4)
        self.assertFalse(any(call[0] == "write" for call in self.server.calls))

    def test_stale_samples_fail(self):
        self.server.stale = True
        with self.assertRaisesRegex(ValueError, "No fresh sample"):
            self.run_demo()
        self.assertEqual(self.server.calls[-1], ("close",))

    def test_missing_sample_component_fails(self):
        self.server.missing_y = True
        with self.assertRaisesRegex(ValueError, "no y data"):
            self.run_demo()
        self.assertEqual(self.server.calls[-1], ("close",))

    def test_zero_magnitude_has_undefined_theta(self):
        self.server.xy = (0, 0)
        self.assertTrue(all(math.isnan(row["theta_deg"]) for row in self.run_demo()))

    def test_partial_write_failure_and_cleanup_failure_keep_original_error(self):
        self.server.fail_write = "sigouts/0/amplitudes/2"
        self.server.close_error = True
        with self.assertRaisesRegex(RuntimeError, "write failed"):
            self.run_demo()
        self.assertIn("writes may remain applied", self.error.getvalue())
        self.assertIn("Cleanup also failed", self.error.getvalue())
        self.assertEqual(self.server.calls[-1], ("close",))

    def test_interrupt_during_settling_closes_client(self):
        self.sleep.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_demo()
        self.assertEqual(self.server.calls[-1], ("close",))


if __name__ == "__main__":
    unittest.main()
