"""The zmeter-shift-mapping skill writes files the Shift Compensation loader reads."""

import csv
import math
import os
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from core.shift_compensation.fitting import fit_cosine, load_mapping_csv

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPT = os.path.join(ROOT, "skills", "zmeter-shift-mapping", "scripts", "write_mapping_csv.py")


def ellipse_table(path):
    """A shift table shaped like 0066_reflection_shift_vs_QWP.csv."""

    angles = np.arange(0.0, 360.0, 6.0)
    theta = np.radians(angles)
    dx_mV = -6.51 * np.cos(theta) - 0.78 * np.sin(theta)
    dy_mV = 4.34 * np.cos(theta) - 8.01 * np.sin(theta)
    with open(path, "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["angle", "dx_px", "dy_px", "dx_V", "dy_V", "quality_corr"])
        for row in zip(angles, dx_mV / 5, dy_mV / 5, dx_mV / 1000, dy_mV / 1000):
            writer.writerow([*row, 0.9])
        writer.writerow([366.0, "", "", "", "", ""])  # incomplete row is skipped
    return angles, dx_mV / 1000, dy_mV / 1000


class ShiftMappingSkillTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, "-I", SCRIPT, *args],
            capture_output=True,
            text=True,
            cwd=self.folder.name,
            timeout=60,
        )

    def test_one_table_two_mapping_csvs_with_the_sign_flipped(self):
        table = os.path.join(self.folder.name, "0066_reflection_shift_vs_QWP.csv")
        angles, dx_V, dy_V = ellipse_table(table)
        out_x = os.path.join(self.folder.name, "out", "qwp_to_ni6423_AO0.csv")
        out_y = os.path.join(self.folder.name, "out", "qwp_to_ni6423_AO1.csv")
        result = self.run_script(
            "--table", table,
            "--source-column", "angle",
            "--source-name", "k10cr1_0_angle",
            "--map", f"dx_V:{out_x}:-1:ni6423_AO0",
            "--map", f"dy_V:{out_y}:-1:ni6423_AO1",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("skipped 1 row", result.stdout)

        x, y = load_mapping_csv(out_x)
        np.testing.assert_allclose(x, angles)
        np.testing.assert_allclose(y, -dx_V)
        x, y = load_mapping_csv(out_y)
        np.testing.assert_allclose(y, -dy_V)
        with open(out_x, encoding="utf-8") as stream:
            self.assertEqual(stream.readline().strip(), "k10cr1_0_angle,add_to_ni6423_AO0")

        fit = fit_cosine(*load_mapping_csv(out_x), period=360.0)
        self.assertAlmostEqual(fit.params["A"], math.hypot(6.51, 0.78) / 1000, places=9)

        check = self.run_script("--check", out_x, out_y)
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertEqual(check.stdout.count("ok:"), 2)

    def test_unknown_column_and_bad_file_fail_cleanly(self):
        table = os.path.join(self.folder.name, "table.csv")
        ellipse_table(table)
        result = self.run_script(
            "--table", table, "--source-column", "angle",
            "--map", "dz_V:out.csv",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("not found", result.stderr)

        bad = os.path.join(self.folder.name, "bad.csv")
        with open(bad, "w", encoding="utf-8") as stream:
            stream.write("a,b\n1,2\nfoo,bar\n")
        result = self.run_script("--check", bad)
        self.assertEqual(result.returncode, 1)
        self.assertIn("expected two numbers", result.stderr)


if __name__ == "__main__":
    unittest.main()
