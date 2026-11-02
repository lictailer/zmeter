import math
import os
import tempfile
import unittest

import numpy as np

from core.shift_compensation.fitting import (
    MODEL_COSINE,
    MODEL_POLYNOMIAL,
    FitResult,
    MappingCsvError,
    MappingFitError,
    fit_cosine,
    fit_mapping,
    fit_polynomial,
    load_mapping_csv,
    parse_mapping_rows,
)


class ParseMappingRowsTests(unittest.TestCase):
    def test_header_and_blank_rows_are_skipped(self):
        x, y = parse_mapping_rows(
            [["angle_deg", "shift_V"], [], ["0", "0.1"], ["", ""], ["10", "0.2"]]
        )
        np.testing.assert_allclose(x, [0.0, 10.0])
        np.testing.assert_allclose(y, [0.1, 0.2])

    def test_numeric_first_row_is_data(self):
        x, _y = parse_mapping_rows([["1", "2"], ["3", "4"]])
        np.testing.assert_allclose(x, [1.0, 3.0])

    def test_later_text_row_is_an_error(self):
        with self.assertRaises(MappingCsvError):
            parse_mapping_rows([["a", "b"], ["1", "2"], ["x", "3"]])

    def test_non_finite_values_are_errors(self):
        with self.assertRaises(MappingCsvError):
            parse_mapping_rows([["1", "2"], ["nan", "3"]])

    def test_needs_two_rows(self):
        with self.assertRaises(MappingCsvError):
            parse_mapping_rows([["angle", "shift"], ["1", "2"]])


class LoadMappingCsvTests(unittest.TestCase):
    def _write(self, text):
        handle, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
        self.addCleanup(os.unlink, path)
        return path

    def test_comma_semicolon_and_tab(self):
        for sep in (",", ";", "\t"):
            path = self._write(f"angle{sep}shift\n0{sep}1.5\n90{sep}-0.5\n180{sep}2\n")
            x, y = load_mapping_csv(path)
            np.testing.assert_allclose(x, [0, 90, 180])
            np.testing.assert_allclose(y, [1.5, -0.5, 2])

    def test_utf8_bom_header(self):
        path = self._write("﻿angle,shift\n0,1\n1,2\n")
        x, _y = load_mapping_csv(path)
        np.testing.assert_allclose(x, [0, 1])

    def test_missing_file(self):
        with self.assertRaises(MappingCsvError):
            load_mapping_csv(os.path.join(tempfile.gettempdir(), "no_such_mapping.csv"))


class FitTests(unittest.TestCase):
    def test_fixed_period_cosine_recovers_parameters(self):
        x = np.arange(0.0, 360.0, 10.0)
        y = 0.02 * np.cos(2 * np.pi * x / 180.0 + 0.7) - 0.003
        result = fit_cosine(x, y, period=180.0)
        self.assertEqual(result.model, MODEL_COSINE)
        self.assertAlmostEqual(result.params["A"], 0.02, places=9)
        self.assertAlmostEqual(result.params["C"], 0.7, places=9)
        self.assertAlmostEqual(result.params["D"], -0.003, places=9)
        self.assertEqual(result.params["P"], 180.0)
        self.assertLess(result.rms, 1e-12)
        self.assertAlmostEqual(result.r2, 1.0)
        self.assertAlmostEqual(result.evaluate(37.0), 0.02 * math.cos(2 * math.pi * 37 / 180 + 0.7) - 0.003)

    def test_negative_amplitude_is_folded_into_phase(self):
        x = np.linspace(0, 2 * np.pi, 20)
        y = -1.0 * np.cos(x)
        result = fit_cosine(x, y, period=2 * np.pi)
        self.assertGreater(result.params["A"], 0)
        np.testing.assert_allclose(result.evaluate(x), y, atol=1e-9)

    def test_free_period_fits_the_period(self):
        x = np.linspace(0, 400, 60)
        y = 0.5 * np.cos(2 * np.pi * x / 170.0 + 0.3) + 0.1
        result = fit_cosine(x, y, period=180.0, free_period=True)
        self.assertAlmostEqual(result.params["P"], 170.0, places=4)
        self.assertEqual(result.options, {"period": 180.0, "free_period": True})
        np.testing.assert_allclose(result.evaluate(x), y, atol=1e-6)

    def test_cosine_needs_enough_points_and_valid_period(self):
        with self.assertRaises(MappingFitError):
            fit_cosine([0, 1], [0, 1], period=360)
        with self.assertRaises(MappingFitError):
            fit_cosine([0, 1, 2, 3], [0, 1, 0, 1], period=0)
        with self.assertRaises(MappingFitError):
            fit_cosine([0, 1, 2], [0, 1, 0], period=360, free_period=True)

    def test_polynomial_recovers_coefficients(self):
        x = np.linspace(-2, 3, 25)
        y = 0.5 - 1.5 * x + 0.25 * x**2
        result = fit_polynomial(x, y, order=2)
        self.assertEqual(result.model, MODEL_POLYNOMIAL)
        np.testing.assert_allclose(result.params["coefficients"], [0.5, -1.5, 0.25], atol=1e-10)

    def test_polynomial_order_limits(self):
        with self.assertRaises(MappingFitError):
            fit_polynomial([0, 1, 2], [0, 1, 2], order=0)
        with self.assertRaises(MappingFitError):
            fit_polynomial([0, 1, 2], [0, 1, 2], order=3)

    def test_round_trip_and_dispatch(self):
        x = np.arange(0, 360, 15.0)
        y = 0.1 * np.cos(np.radians(x)) + 0.01
        for model, options in (
            (MODEL_COSINE, {"period": 360.0}),
            (MODEL_POLYNOMIAL, {"order": 3}),
        ):
            result = fit_mapping(x, y, model, options)
            again = FitResult.from_dict(result.to_dict())
            np.testing.assert_allclose(again.evaluate(x), result.evaluate(x))
            self.assertTrue(again.describe().startswith("y = "))
        with self.assertRaises(MappingFitError):
            fit_mapping(x, y, "spline", {})


if __name__ == "__main__":
    unittest.main()
