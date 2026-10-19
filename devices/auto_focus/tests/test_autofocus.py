"""Only injected instruments/cameras and temporary files are used here."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import time
from types import SimpleNamespace
import unittest

import numpy as np

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from devices.auto_focus.autofocus_engine import (
    AutofocusSettings, Channel, FocusStopped, OutputSettings, SearchSettings, SourceSettings,
    ZSettings, gradient_energy, laplacian_variance, run_focus,
)
from devices.auto_focus.autofocus_hardware import (
    BoundedZAxis, CameraSource, PointSource, RasterSource, RoutedZAxis, RouterIO,
)


def quick_settings(**search):
    return AutofocusSettings(search=replace(SearchSettings(), settle_s=0, **search),
                              source=replace(SourceSettings(), sample_interval_s=0, xy_settle_s=0))


class FakeAxis(BoundedZAxis):
    def __init__(self, settings=ZSettings(), origin=0):
        super().__init__(settings)
        self.current, self.moves, self.connected = origin, [], False

    def connect(self, stop):
        self.connected = True

    def position(self):
        return self.current

    def _move_once(self, target, stop):
        self.moves.append(target)
        self.current = target
        return target

    def disconnect(self):
        self.connected = False


class FakeSource:
    def __init__(self, axis, curve=lambda z: 100 - (z - 2.3) ** 2):
        self.axis, self.curve = axis, curve
        self.reads, self.closed, self.prepared = 0, False, False

    def prepare(self, stop):
        self.prepared = True

    def acquire(self, stop):
        self.reads += 1
        return self.curve(self.axis.position())

    def close(self):
        self.closed = True


class FakeRouter:
    def __init__(self):
        self.main_window = SimpleNamespace(active_scan_range_limits={})
        self.catalog = {
            "arduino_steppers": {"writable": ["stepperA_angle"], "readable": ["stepperA_angle"]},
            "nidaq": {"writable": ["AO0", "AO1"], "readable": ["AI0"]},
            "piezo_stage": {"writable": ["Z"], "readable": ["Z", "photocurrent"]},
        }
        self.values = {("nidaq", "AO0"): 0, ("nidaq", "AO1"): 0, ("piezo_stage", "Z"): 0}
        self.values["arduino_steppers", "stepperA_angle"] = 0
        self.requests, self.writes = [], []
        self.read_value = lambda: 2 * self.values[("nidaq", "AO0")] + 3 * self.values[("nidaq", "AO1")]

    def route_command(self, request):
        self.requests.append(dict(request))
        action = request["action"]
        ref = request["target_device"], request["channel"]
        value = None
        if action == "write":
            value = self.values[ref] = request["value"]
            self.writes.append((ref, value))
        elif action == "read":
            value = self.values[ref] if ref in self.values else self.read_value()
        return {"ok": True, "value": value, "catalog": self.catalog}


class FocusEngineTests(unittest.TestCase):
    def test_full_sweep_absolute_endpoints_plot_samples_and_direct_maximum(self):
        z = replace(ZSettings(), minimum=-120, maximum=120)
        axis = FakeAxis(z, origin=7)
        settings = replace(quick_settings(method="sweep_maximum", bounds_mode="absolute",
                                           absolute_lower=-100, absolute_upper=100, sweep_points=41), z=z)
        seen = []
        source = FakeSource(axis, lambda p: 2 + 5 * np.exp(-0.5 * ((p - 23) / 20) ** 2))
        result = run_focus(axis, source, settings, threading.Event(), lambda s, d: seen.append((s, d)))
        self.assertEqual([s.target for s in result.samples], list(np.linspace(-100, 100, 41)))
        self.assertEqual(len(seen), 41)
        self.assertEqual(source.reads, 41)
        self.assertEqual(result.best_position, 25)
        self.assertEqual(result.selected_position, 25)
        self.assertIsNone(result.gaussian_fit)
        self.assertTrue(result.applied)
        self.assertEqual(axis.position(), 25)

    def test_gaussian_sweep_fits_off_grid_peak_and_preserves_measured_best(self):
        for direction, sign in (("maximize", 1), ("minimize", -1)):
            with self.subTest(direction=direction):
                axis = FakeAxis()
                source = FakeSource(axis, lambda p: 2 + sign * 5 * np.exp(-0.5 * ((p - 2.3) / 2) ** 2))
                settings = quick_settings(method="sweep_gaussian", sweep_points=21, objective=direction)
                result = run_focus(axis, source, settings, threading.Event())
                self.assertEqual(result.status, "complete")
                self.assertEqual(source.reads, 21)
                self.assertEqual(result.best_position, 2)
                self.assertAlmostEqual(result.best_score, source.curve(2))
                self.assertAlmostEqual(result.selected_position, 2.3, places=5)
                self.assertAlmostEqual(axis.position(), 2.3, places=5)
                self.assertAlmostEqual(result.gaussian_fit.baseline, 2, places=5)
                self.assertAlmostEqual(result.gaussian_fit.amplitude, sign * 5, places=5)
                self.assertAlmostEqual(result.gaussian_fit.sigma, 2, places=5)
                self.assertGreater(result.gaussian_fit.r_squared, 0.9999)
                exported = json.loads(json.dumps(result.to_dict(), allow_nan=False))
                self.assertAlmostEqual(exported["gaussian_fit"]["center"], 2.3, places=5)
                self.assertEqual(exported["best_position"], 2)

    def test_gaussian_noisy_negative_baseline_and_small_distance_units(self):
        z = replace(ZSettings(), native_unit="mm", minimum=-0.01, maximum=0.01,
                    max_move=0.002, tolerance=0.000001)
        axis = FakeAxis(z)
        rng = np.random.default_rng(10)
        source = FakeSource(axis, lambda p: -3 + 0.005 * np.exp(-0.5 * ((p - 0.00123) / 0.0015) ** 2)
                            + rng.normal(0, 0.00002))
        settings = replace(quick_settings(method="sweep_gaussian", bounds_mode="absolute",
                                          absolute_lower=-0.005, absolute_upper=0.005), z=z)
        result = run_focus(axis, source, settings, threading.Event())
        self.assertEqual(result.status, "complete")
        self.assertAlmostEqual(result.selected_position, 0.00123, delta=0.00003)
        self.assertGreater(result.gaussian_fit.r_squared, 0.99)

    def test_bad_gaussian_data_reports_failure_without_fallback_move(self):
        axis = FakeAxis()
        source = FakeSource(axis, lambda p: np.cos(p * 2))
        result = run_focus(axis, source, quick_settings(method="sweep_gaussian", gaussian_min_r_squared=0.95), threading.Event())
        self.assertEqual(result.status, "fit_failed")
        self.assertIn("Gaussian", result.fit_error)
        self.assertFalse(result.applied)
        self.assertIsNone(result.selected_position)
        self.assertEqual(axis.position(), result.samples[-1].position)

    def test_gaussian_flat_boundary_and_numerical_failure_never_apply(self):
        from unittest import mock
        for curve, status in ((lambda p: 1, "flat_signal"), (lambda p: p, "boundary_peak")):
            axis = FakeAxis()
            result = run_focus(axis, FakeSource(axis, curve), quick_settings(method="sweep_gaussian"), threading.Event())
            self.assertEqual(result.status, status)
            self.assertFalse(result.applied)
            self.assertIsNone(result.gaussian_fit)
        axis = FakeAxis()
        with mock.patch("scipy.optimize.curve_fit", side_effect=RuntimeError("no convergence")):
            result = run_focus(axis, FakeSource(axis), quick_settings(method="sweep_gaussian"), threading.Event())
        self.assertEqual(result.status, "fit_failed")
        self.assertIn("no convergence", result.fit_error)
        self.assertFalse(result.applied)
        self.assertEqual(axis.position(), 10)

    def test_sweep_cancellation_partial_history_and_fit_cancellation(self):
        from unittest import mock
        for method in ("sweep_maximum", "sweep_gaussian"):
            axis, stop, history = FakeAxis(), threading.Event(), []
            def cancel(sample, data):
                if len(history) == 4:
                    stop.set()
            with self.assertRaises(FocusStopped):
                run_focus(axis, FakeSource(axis), quick_settings(method=method), stop, cancel, history)
            self.assertEqual(len(history), 4)
            self.assertEqual(axis.position(), history[-1].position)
        axis, stop = FakeAxis(), threading.Event()
        def cancel_in_fit(model, x, y, **kwargs):
            stop.set()
            model(x, 0, 1, 0.5, 0.1)
        with mock.patch("scipy.optimize.curve_fit", side_effect=cancel_in_fit):
            with self.assertRaises(FocusStopped):
                run_focus(axis, FakeSource(axis), quick_settings(method="sweep_gaussian"), stop)
        self.assertEqual(axis.position(), 10)

    def test_absolute_and_relative_bounds_round_trip_and_limits_before_motion(self):
        for method in ("sweep_maximum", "sweep_gaussian"):
            settings = quick_settings(method=method, bounds_mode="absolute", absolute_lower=-100, absolute_upper=100)
            self.assertEqual(AutofocusSettings.from_dict(json.loads(json.dumps(settings.to_dict()))), settings)
            axis, source = FakeAxis(), FakeSource(FakeAxis())
            with self.assertRaisesRegex(ValueError, "outside"):
                run_focus(axis, source, settings, threading.Event())
            self.assertEqual(axis.moves, [])
            self.assertFalse(source.prepared)
        old = quick_settings().to_dict()
        for key in ("bounds_mode", "absolute_lower", "absolute_upper", "sweep_points", "gaussian_min_r_squared"):
            del old["search"][key]
        self.assertEqual(AutofocusSettings.from_dict(old).search.bounds_mode, "relative")
        for changes in ({"bounds_mode": "unknown"}, {"absolute_lower": 10, "absolute_upper": -10},
                        {"sweep_points": 2}, {"gaussian_min_r_squared": 1.1},
                        {"method": "sweep_gaussian", "sweep_points": 5}):
            with self.assertRaises(ValueError):
                replace(SearchSettings(), **changes).validate()

    def test_gaussian_fit_uses_actual_quantized_positions_and_honors_no_apply(self):
        class QuantizedAxis(FakeAxis):
            def _move_once(self, target, stop):
                self.moves.append(target)
                self.current = round(target / (360 / 2048)) * (360 / 2048)
                return self.current
        axis = QuantizedAxis()
        source = FakeSource(axis, lambda p: 2 + np.exp(-0.5 * ((p - 2.3) / 2) ** 2))
        result = run_focus(axis, source, quick_settings(method="sweep_gaussian", move_to_best=False), threading.Event())
        self.assertEqual(result.status, "complete")
        self.assertAlmostEqual(result.gaussian_fit.center, 2.3, places=5)
        self.assertFalse(result.applied)
        self.assertEqual(axis.position(), result.samples[-1].position)

    def test_gaussian_rejects_too_few_distinct_acknowledged_positions(self):
        class QuantizedAxis(FakeAxis):
            def _move_once(self, target, stop):
                self.moves.append(target)
                self.current = round(target)
                return self.current
        z = replace(ZSettings(), tolerance=0.5)
        axis = QuantizedAxis(z)
        settings = replace(quick_settings(method="sweep_gaussian", start_offset=-2, stop_offset=2), z=z)
        result = run_focus(axis, FakeSource(axis, lambda p: np.exp(-0.5 * p * p)), settings, threading.Event())
        self.assertEqual(result.status, "fit_failed")
        self.assertIn("distinct acknowledged", result.fit_error)
        self.assertFalse(result.applied)

    def test_gaussian_rejects_unresolved_peak(self):
        axis = FakeAxis()
        source = FakeSource(axis, lambda p: np.exp(-0.5 * (p / 0.01) ** 2))
        result = run_focus(axis, source, quick_settings(method="sweep_gaussian"), threading.Event())
        self.assertEqual(result.status, "fit_failed")
        self.assertFalse(result.applied)
        self.assertEqual(axis.position(), 10)

    def test_default_setup_and_json_round_trip(self):
        settings = AutofocusSettings()
        self.assertEqual((settings.z.backend, settings.source.mode, settings.search.metric), ("routed", "point", "mean"))
        self.assertEqual((settings.source.x.channel, settings.source.y.channel, settings.source.signal.channel), ("AO0", "AO1", "AI0"))
        self.assertFalse(settings.source.position_xy)
        self.assertEqual(settings.search.method, "adaptive_brent")
        self.assertEqual(AutofocusSettings.from_dict(json.loads(json.dumps(settings.to_dict()))), settings)
        with self.assertRaises(ValueError):
            AutofocusSettings.from_dict({**settings.to_dict(), "schema_version": 99})
        with self.assertRaises(ValueError):
            replace(settings.search, move_to_best="false").validate()

    def test_old_schema2_setup_keeps_grid_and_both_methods_round_trip(self):
        old = quick_settings().to_dict()
        for key in ("method", "initial_step", "position_precision", "max_evaluations"):
            del old["search"][key]
        self.assertEqual(AutofocusSettings.from_dict(old).search.method, "grid")
        for method in ("grid", "adaptive_brent"):
            settings = quick_settings(method=method, initial_step=0.7,
                                      position_precision=0.3, max_evaluations=20)
            self.assertEqual(AutofocusSettings.from_dict(json.loads(json.dumps(settings.to_dict()))), settings)
        for changes in ({"method": "magic"}, {"initial_step": 0},
                        {"position_precision": float("nan")}, {"max_evaluations": 2}):
            with self.assertRaises(ValueError):
                replace(SearchSettings(), **changes).validate()

    def test_grid_retains_original_coarse_and_refinement_targets(self):
        axis = FakeAxis()
        source = FakeSource(axis, lambda z: 100 - (z - 6.25) ** 2)
        settings = quick_settings(method="grid", start_offset=-20, stop_offset=20)
        result = run_focus(axis, source, settings, threading.Event())
        self.assertEqual([s.target for s in result.samples],
                         [-20, -15, -10, -5, 0, 5, 10, 15, 20, 2.5, 7.5, 3.75, 6.25])
        self.assertEqual(result.best_position, 6.25)

    def test_adaptive_follows_either_direction_and_handles_already_at_peak(self):
        for peak in (-7.2, -2.3, 0, 2.3, 7.2):
            with self.subTest(peak=peak):
                axis = FakeAxis()
                source = FakeSource(axis, lambda z: 100 - (z - peak) ** 2)
                result = run_focus(axis, source, quick_settings(), threading.Event())
                self.assertEqual(result.status, "complete")
                self.assertAlmostEqual(result.best_position, peak, delta=0.2)
                self.assertEqual([s.target for s in result.samples[:3]], [0, -1, 1])
                self.assertTrue(result.applied)
                self.assertTrue(all(-10 <= p <= 10 for p in axis.moves))

    def test_adaptive_smooth_peak_uses_fewer_images_than_default_grid(self):
        results = {}
        for method in ("grid", "adaptive_brent"):
            axis = FakeAxis()
            source = FakeSource(axis)
            results[method] = run_focus(axis, source, quick_settings(method=method), threading.Event())
        self.assertLess(len(results["adaptive_brent"].samples), len(results["grid"].samples))
        self.assertAlmostEqual(results["adaptive_brent"].best_position, 2.3, delta=0.1)

    def test_adaptive_gaussian_image_peak_with_deterministic_small_noise(self):
        axis = FakeAxis()
        pattern = (np.indices((15, 15)).sum(axis=0) % 2).astype(float)
        rng = np.random.default_rng(42)
        source = FakeSource(axis, lambda z: (np.exp(-((z + 3.4) / 2) ** 2) * pattern
                                             + rng.normal(0, 0.001, pattern.shape)))
        settings = replace(quick_settings(metric="gradient"), source=replace(SourceSettings(), mode="camera"))
        result = run_focus(axis, source, settings, threading.Event())
        self.assertEqual(result.status, "complete")
        self.assertAlmostEqual(result.best_position, -3.4, delta=0.25)
        self.assertLessEqual(source.reads, settings.search.max_evaluations)

    def test_adaptive_budget_stops_without_final_best_move(self):
        axis = FakeAxis()
        source = FakeSource(axis)
        result = run_focus(axis, source, quick_settings(max_evaluations=3), threading.Event())
        self.assertEqual(result.status, "max_evaluations")
        self.assertEqual(source.reads, 3)
        self.assertFalse(result.applied)
        self.assertEqual(axis.current, result.samples[-1].position)
        self.assertTrue(source.closed)

    def test_adaptive_quantized_positions_are_not_measured_twice(self):
        class QuantizedAxis(FakeAxis):
            def _move_once(self, target, stop):
                self.moves.append(target)
                self.current = round(target / (360 / 2048)) * (360 / 2048)
                return self.current

        axis = QuantizedAxis()
        source = FakeSource(axis)
        result = run_focus(axis, source, quick_settings(position_precision=0.001), threading.Event())
        self.assertEqual(result.status, "complete")
        self.assertAlmostEqual(result.best_position, 2.3, delta=0.2)
        self.assertEqual(len({s.position for s in result.samples}), source.reads)

    def test_adaptive_asymmetric_offset_interval_excludes_origin(self):
        axis = FakeAxis()
        source = FakeSource(axis, lambda z: 100 - (z - 4.3) ** 2)
        result = run_focus(axis, source, quick_settings(start_offset=2, stop_offset=8), threading.Event())
        self.assertEqual(result.status, "complete")
        self.assertAlmostEqual(result.best_position, 4.3, delta=0.2)
        self.assertTrue(all(2 <= p <= 8 for p in axis.moves))

    def test_adaptive_plateau_probes_do_not_cause_premature_flat_result(self):
        axis = FakeAxis()
        source = FakeSource(axis, lambda z: max(0, 1 - ((z - 5) / 4) ** 2))
        result = run_focus(axis, source, quick_settings(), threading.Event())
        self.assertEqual([s.score for s in result.samples[:3]], [0, 0, 0])
        self.assertEqual(result.status, "complete")
        self.assertAlmostEqual(result.best_position, 5, delta=0.2)

    def test_stop_error_and_no_apply_contracts_for_both_methods(self):
        for method in ("grid", "adaptive_brent"):
            with self.subTest(method=method):
                axis, stop = FakeAxis(), threading.Event()
                source, history = FakeSource(axis), []
                def stop_after_sample(sample, data):
                    stop.set()
                with self.assertRaises(FocusStopped):
                    run_focus(axis, source, quick_settings(method=method), stop, stop_after_sample, history)
                self.assertEqual(len(history), 1)
                self.assertEqual(axis.position(), history[-1].position)
                self.assertTrue(source.closed)
                source = FakeSource(axis, lambda z: float("nan"))
                with self.assertRaisesRegex(ValueError, "nonfinite"):
                    run_focus(axis, source, quick_settings(method=method), threading.Event())
                self.assertTrue(source.closed)
                axis = FakeAxis()
                result = run_focus(axis, FakeSource(axis), quick_settings(method=method, move_to_best=False), threading.Event())
                self.assertFalse(result.applied)
                self.assertEqual(result.final_position, result.samples[-1].position)

    def test_maximum_with_nonzero_origin_uses_absolute_targets_and_reuses_samples(self):
        axis = FakeAxis(origin=5)
        source = FakeSource(axis, lambda z: 100 - (z - 7.3) ** 2)
        result = run_focus(axis, source, quick_settings(), threading.Event())
        self.assertEqual(result.status, "complete")
        self.assertAlmostEqual(result.best_position, 7.3, delta=0.32)  # final grid spacing / 2
        self.assertEqual(axis.current, result.best_position)
        self.assertTrue(result.applied)
        self.assertTrue(source.closed)
        self.assertLessEqual(source.reads, 15)
        self.assertEqual(len({s.target for s in result.samples}), len(result.samples))
        self.assertTrue(all(-5 <= p <= 15 for p in axis.moves))

    def test_minimum_and_no_apply_option(self):
        axis = FakeAxis()
        source = FakeSource(axis, lambda z: (z + 1.7) ** 2)
        result = run_focus(axis, source, quick_settings(objective="minimize", move_to_best=False), threading.Event())
        self.assertAlmostEqual(result.best_position, -1.7, delta=0.2)
        self.assertFalse(result.applied)

    def test_boundary_and_flat_signal_do_not_apply_final_move(self):
        for curve, status in ((lambda z: z, "boundary_peak"), (lambda z: 3, "flat_signal")):
            with self.subTest(status=status):
                axis = FakeAxis()
                source = FakeSource(axis, curve)
                result = run_focus(axis, source, quick_settings(), threading.Event())
                self.assertEqual(result.status, status)
                self.assertFalse(result.applied)

    def test_invalid_complete_path_is_rejected_before_motion_or_acquisition(self):
        axis = FakeAxis(origin=15)
        source = FakeSource(axis)
        with self.assertRaisesRegex(ValueError, "outside"):
            run_focus(axis, source, quick_settings(), threading.Event())
        self.assertEqual(axis.moves, [])
        self.assertFalse(source.prepared)

    def test_stop_retains_partial_history_and_never_returns_home(self):
        axis, stop = FakeAxis(), threading.Event()
        source, history = FakeSource(axis), []

        def on_sample(sample, data):
            if len(history) == 3:
                stop.set()

        with self.assertRaises(FocusStopped):
            run_focus(axis, source, quick_settings(), stop, on_sample, history)
        self.assertEqual(len(history), 3)
        self.assertEqual(axis.current, history[-1].position)
        self.assertEqual(source.reads, 3)
        self.assertTrue(source.closed)

    def test_prepare_and_measurement_errors_close_source_and_stop_further_moves(self):
        axis = FakeAxis()
        source = FakeSource(axis, lambda z: float("nan"))
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            run_focus(axis, source, quick_settings(), threading.Event())
        self.assertTrue(source.closed)
        self.assertEqual(source.reads, 1)
        first_move_count = len(axis.moves)
        self.assertGreater(first_move_count, 0)

        class BadPrepare(FakeSource):
            def prepare(self, stop):
                raise RuntimeError("acquisition unavailable")

        source = BadPrepare(axis)
        with self.assertRaisesRegex(RuntimeError, "unavailable"):
            run_focus(axis, source, quick_settings(), threading.Event())
        self.assertTrue(source.closed)
        self.assertEqual(len(axis.moves), first_move_count)

    def test_image_metrics_prefer_sharper_synthetic_image(self):
        grid = (np.indices((30, 30)).sum(axis=0) % 2).astype(float)
        blurred = np.full_like(grid, 0.5)
        for score in (gradient_energy, laplacian_variance):
            self.assertGreater(score(grid), score(blurred))
        with self.assertRaises(ValueError):
            replace(AutofocusSettings(), search=replace(SearchSettings(), metric="gradient")).validate()

    def test_image_source_and_metric_can_replace_scalar_source_without_changing_z_search(self):
        axis = FakeAxis()
        pattern = (np.indices((15, 15)).sum(axis=0) % 2).astype(float)
        source = FakeSource(axis, lambda z: np.exp(-((z - 1.5) / 3) ** 2) * pattern)
        settings = replace(quick_settings(metric="gradient"), source=replace(SourceSettings(), mode="camera"))
        result = run_focus(axis, source, settings, threading.Event())
        self.assertAlmostEqual(result.best_position, 1.5, delta=0.32)
        self.assertTrue(result.applied)


class HardwareAdapterTests(unittest.TestCase):
    def test_conversion_round_trip_signed_scale_offset_and_native_global_limits(self):
        for scale, unit in ((2, "um"), (-0.002, "mm")):
            settings = replace(ZSettings(), convert_to_distance=True, distance_unit=unit,
                               distance_per_native=scale, native_zero=1.5, distance_zero=0.25,
                               minimum=-20, maximum=20)
            settings.validate()
            self.assertAlmostEqual(settings.to_native(settings.from_native(4.25)), 4.25)
            self.assertEqual(settings.unit, unit)
            self.assertEqual(AutofocusSettings.from_dict(AutofocusSettings(z=settings).to_dict()).z, settings)
            router = FakeRouter()
            ref = settings.setter
            router.main_window.active_scan_range_limits[ref.device, ref.channel] = (-2, 2)
            axis = RoutedZAxis(settings, RouterIO(router))
            axis.connect(threading.Event())
            with self.assertRaisesRegex(ValueError, "global limits"):
                axis.validate_path(settings.from_native(-3), settings.from_native(3))
            self.assertEqual(router.writes, [])
        with self.assertRaisesRegex(ValueError, "nonzero calibrated"):
            replace(ZSettings(), convert_to_distance=True).validate()
        with self.assertRaisesRegex(ValueError, "schema 2"):
            AutofocusSettings.from_dict({"schema_version": 1})

    def test_point_default_holds_xy_and_averages_selected_signal(self):
        router = FakeRouter()
        readings = iter((0, 1, 2, 3))
        router.read_value = lambda: next(readings)
        source = PointSource(replace(SourceSettings(), samples=3, sample_interval_s=0), RouterIO(router))
        source.prepare(threading.Event())
        self.assertEqual(source.acquire(threading.Event()), 2)
        self.assertEqual(router.writes, [])
        self.assertEqual(len([r for r in router.requests if r["action"] == "read"]), 4)

    def test_set_point_and_raster_are_routed_and_serpentine_values_have_consistent_axes(self):
        router = FakeRouter()
        settings = replace(SourceSettings(), mode="raster", x_points=5, y_points=3,
                           samples=1, xy_settle_s=0, x_span=0.4, y_span=0.2)
        source = RasterSource(settings, RouterIO(router))
        source.prepare(threading.Event())
        image = source.acquire(threading.Event())
        expected = 2 * np.linspace(-0.2, 0.2, 5)[None, :] + 3 * np.linspace(-0.1, 0.1, 3)[:, None]
        np.testing.assert_allclose(image, expected)
        self.assertEqual(router.values[("nidaq", "AO0")], 0)
        self.assertEqual(router.values[("nidaq", "AO1")], 0)

    def test_global_raster_bounds_and_channel_failures_prevent_z_motion(self):
        router = FakeRouter()
        router.main_window.active_scan_range_limits[("nidaq", "AO0")] = (-0.01, 0.01)
        settings = replace(quick_settings(metric="gradient"), source=replace(SourceSettings(), mode="raster"))
        axis = FakeAxis()
        with self.assertRaisesRegex(ValueError, "global limits"):
            run_focus(axis, RasterSource(settings.source, RouterIO(router)), settings, threading.Event())
        self.assertEqual(axis.moves, [])
        self.assertEqual(router.writes, [])

    def test_self_routed_channel_is_refused_instead_of_deadlocking(self):
        router = FakeRouter()
        router.catalog["auto_focus"] = {"writable": ["focus"], "readable": ["z"]}
        io = RouterIO(router, "auto_focus")
        io.refresh()
        with self.assertRaisesRegex(ValueError, "own scan channels"):
            io.read(Channel("auto_focus", "z"))
        self.assertFalse(any(r["action"] == "read" for r in router.requests))

    def test_routed_z_uses_configured_units_getter_and_global_bounds(self):
        router, stop = FakeRouter(), threading.Event()
        io = RouterIO(router)
        settings = replace(ZSettings(), native_unit="um",
                           setter=Channel("piezo_stage", "Z"), getter=Channel("piezo_stage", "Z"))
        axis = RoutedZAxis(settings, io)
        axis.connect(stop)
        self.assertEqual(axis.move_to(1.5, stop), 1.5)
        router.main_window.active_scan_range_limits[("piezo_stage", "Z")] = (-1, 1)
        before = list(router.writes)
        with self.assertRaisesRegex(ValueError, "global limits"):
            axis.validate_path(-2, 2)
        self.assertEqual(router.writes, before)
        axis.disconnect()
        self.assertEqual(router.values[("piezo_stage", "Z")], 1.5)

    def test_camera_is_lazy_and_roi_is_checked_before_motion(self):
        class Capture:
            released = False
            def isOpened(self): return True
            def read(self): return True, np.arange(300).reshape(10, 10, 3)
            def release(self): self.released = True

        capture, opened = Capture(), []
        def factory(index):
            opened.append(index)
            return capture
        settings = replace(SourceSettings(), mode="camera", roi=(2, 2, 4, 4))
        source = CameraSource(settings, capture_factory=factory)
        self.assertEqual(opened, [])
        source.prepare(threading.Event())
        self.assertEqual(source.acquire(threading.Event()).shape, (4, 4, 3))
        source.close()
        self.assertTrue(capture.released)
        source = CameraSource(replace(settings, roi=(8, 8, 4, 4)), capture_factory=factory)
        axis = FakeAxis()
        with self.assertRaisesRegex(ValueError, "ROI"):
            run_focus(axis, source, replace(quick_settings(metric="gradient"), source=source.settings), threading.Event())
        self.assertEqual(axis.moves, [])
        self.assertTrue(capture.released)


try:
    from PyQt6 import QtCore, QtWidgets
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, "PyQt6 unavailable")
class AutofocusQtTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def make_logic(self):
        from devices.auto_focus.autofocus_logic import AutofocusLogic
        axis = FakeAxis()
        logic = AutofocusLogic(
            z_factories={"routed": ("Fake device channel", lambda settings, io: axis)},
            source_factories={"point": ("Fake reflection", lambda settings, io: FakeSource(axis))},
        )
        logic.apply_settings(quick_settings())
        return logic, axis

    def test_panel_defaults_construction_and_settings_round_trip(self):
        from devices.auto_focus.autofocus_main import AutofocusMain
        logic, axis = self.make_logic()
        panel = AutofocusMain(logic)
        self.addCleanup(panel.close)
        self.assertFalse(axis.connected)
        self.assertEqual(axis.moves, [])
        self.assertEqual(panel.read_settings(), quick_settings())
        panel.configure_command_router(FakeRouter(), "focus_tool")
        self.assertEqual(panel.read_settings().source.signal, Channel("nidaq", "AI0"))
        logic.connect_z()
        self.assertFalse(panel.z_backend.isEnabled())
        self.assertTrue(panel.run_button.isEnabled())
        self.assertTrue(panel.terminate_dev())

    def test_search_bound_labels_explain_interval_without_changing_saved_keys(self):
        from devices.auto_focus.autofocus_main import AutofocusMain
        logic, axis = self.make_logic()
        panel = AutofocusMain(logic)
        self.addCleanup(panel.close)
        for key, side, value in (("start_offset", "lower", -10), ("stop_offset", "upper", 10)):
            widget = panel.fields["search." + key]
            label = widget.parentWidget().layout().labelForField(widget)
            self.assertEqual(label.text(), f"Search {side} bound (relative to starting Z)")
            self.assertIn("not an XY image boundary or a prescribed move", widget.toolTip())
            self.assertEqual(panel.read_settings().to_dict()["search"][key], value)
        self.assertEqual(panel.read_settings(), quick_settings())
        self.assertEqual(axis.moves, [])
        self.assertFalse(logic.connected)

    def test_panel_optimizer_selection_updates_controls_and_round_trips(self):
        from devices.auto_focus.autofocus_main import AutofocusMain
        logic, axis = self.make_logic()
        panel = AutofocusMain(logic)
        self.addCleanup(panel.close)
        for method in ("grid", "adaptive_brent", "sweep_maximum", "sweep_gaussian"):
            panel.search_method.setCurrentIndex(panel.search_method.findData(method))
            settings = panel.read_settings()
            self.assertEqual(settings.search.method, method)
            self.assertEqual(panel.fields["search.initial_step"].isHidden(), method != "adaptive_brent")
            self.assertEqual(panel.fields["search.coarse_points"].isHidden(), method != "grid")
            self.assertEqual(panel.fields["search.sweep_points"].isHidden(), not method.startswith("sweep_"))
            self.assertEqual(panel.fields["search.gaussian_min_r_squared"].isHidden(), method != "sweep_gaussian")
            panel.load_controls(settings)
            self.assertEqual(panel.read_settings(), settings)
        self.assertEqual(axis.moves, [])
        self.assertFalse(logic.connected)

    def test_absolute_sweep_ui_and_single_point_score_explanation(self):
        from devices.auto_focus.autofocus_main import AutofocusMain
        panel = AutofocusMain()
        self.addCleanup(panel.close)
        panel.search_method.setCurrentIndex(panel.search_method.findData("sweep_gaussian"))
        panel.bounds_mode.setCurrentIndex(panel.bounds_mode.findData("absolute"))
        panel.fields["search.absolute_lower"].setValue(-100)
        panel.fields["search.absolute_upper"].setValue(100)
        settings = panel.read_settings()
        self.assertEqual((settings.search.absolute_lower, settings.search.absolute_upper), (-100, 100))
        self.assertEqual(settings.search.bounds_mode, "absolute")
        self.assertTrue(panel.fields["search.start_offset"].isHidden())
        self.assertFalse(panel.fields["search.absolute_lower"].isHidden())
        self.assertIn("average of the input readings at this Z", panel.mean_note.text())
        self.assertFalse(panel.mean_note.isHidden())
        for key in ("gradient", "laplacian"):
            self.assertFalse(panel.metric.model().item(panel.metric.findData(key)).isEnabled())
        panel.source_mode.setCurrentIndex(panel.source_mode.findData("raster"))
        self.assertTrue(panel.mean_note.isHidden())
        self.assertTrue(panel.metric.model().item(panel.metric.findData("gradient")).isEnabled())
        panel.load_controls(settings)
        self.assertEqual(panel.read_settings(), settings)
        self.assertFalse(panel.logic.connected)

    def test_gaussian_result_return_plot_and_export_keep_prediction_distinct(self):
        import tempfile
        from unittest import mock
        from devices.auto_focus.autofocus_main import AutofocusMain
        logic, axis = self.make_logic()
        curve = lambda p: 2 + 5 * np.exp(-0.5 * ((p - 2.3) / 2) ** 2)
        logic.source_factories["point"] = ("Fake Gaussian", lambda settings, io: FakeSource(axis, curve))
        logic.apply_settings(quick_settings(method="sweep_gaussian"))
        panel = AutofocusMain(logic)
        self.addCleanup(panel.close)
        messages = []
        logic.sig_status.connect(messages.append)
        logic.connect_z()
        selected = logic.set_focus(1)
        self.assertAlmostEqual(selected, 2.3, places=5)
        self.assertEqual(logic.result.best_position, 2.5)
        self.assertAlmostEqual(logic.get_focus_score(), curve(2.5))
        self.assertEqual(panel.plot.gaussian_fit, logic.result.gaussian_fit)
        self.assertEqual(panel.plot.y_label, "Mean signal")
        self.assertIn("measured best Z 2.5", messages[-1])
        self.assertIn("Gaussian center 2.3", messages[-1])
        self.assertFalse(panel.plot.grab().isNull())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gaussian_result.json"
            with mock.patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(path), "")):
                panel._export_result()
            data = json.loads(path.read_text())
            self.assertEqual(AutofocusSettings.from_dict(data["settings"]), logic.run_settings)
            self.assertEqual(data["result"]["best_position"], 2.5)
            self.assertAlmostEqual(data["result"]["selected_position"], 2.3, places=5)
            self.assertAlmostEqual(data["result"]["gaussian_fit"]["center"], 2.3, places=5)
        self.assertTrue(logic.terminate_dev())

    def test_optional_saving_success_disabled_partial_and_legacy_settings(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            logic, axis = self.make_logic()
            logic.apply_settings(replace(quick_settings(), output=OutputSettings(False, directory)))
            logic.connect_z()
            logic.set_focus(1)
            self.assertEqual(list(Path(directory).iterdir()), [])
            logic.apply_settings(replace(logic.settings, output=OutputSettings(True, directory)))
            logic.set_focus(1)
            path = Path(logic.last_output_directory)
            saved = json.loads((path / "run.json").read_text())
            self.assertEqual(saved["outcome"], "complete")
            self.assertTrue((path / "focus_curve.png").is_file())
            self.assertEqual(AutofocusSettings.from_dict(saved["settings"]), logic.run_settings)
            logic.sig_sample.connect(lambda item: logic.force_stop() if item is not None else None)
            with self.assertRaises(FocusStopped): logic.set_focus(1)
            partial = Path(logic.last_output_directory)
            self.assertNotEqual(partial, path)
            saved = json.loads((partial / "run.json").read_text())
            self.assertEqual(saved["outcome"], "stopped")
            self.assertEqual(len(saved["samples"]), 1)
            self.assertTrue((partial / "focus_curve.png").is_file())
            legacy = quick_settings().to_dict()
            del legacy["output"]
            self.assertFalse(AutofocusSettings.from_dict(legacy).output.enabled)
            self.assertTrue(logic.terminate_dev())

    def test_optional_saving_bad_directory_prevents_motion_and_image_files_round_trip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            logic, axis = self.make_logic()
            bad = Path(directory) / "not-a-directory"
            bad.write_text("existing data")
            logic.apply_settings(replace(quick_settings(), output=OutputSettings(True, str(bad))))
            logic.connect_z()
            with self.assertRaises(OSError): logic.set_focus(1)
            self.assertEqual(axis.moves, [])
            self.assertEqual(bad.read_text(), "existing data")
            pattern = (np.indices((15, 15)).sum(axis=0) % 2).astype(float)
            logic.source_factories["camera"] = ("Fake image", lambda settings, io: FakeSource(axis, lambda z: np.exp(-z*z/10) * pattern))
            settings = replace(quick_settings(method="grid", coarse_points=3, refinement_rounds=0, metric="gradient"),
                               source=replace(SourceSettings(), mode="camera"), output=OutputSettings(True, directory, True))
            logic.apply_settings(settings)
            logic.set_focus(1)
            path = Path(logic.last_output_directory)
            self.assertEqual(len(list(path.glob("frame-*.npy"))), 3)
            self.assertEqual(len(list(path.glob("frame-*.png"))), 3)
            np.testing.assert_allclose(np.load(path / "frame-0002.npy", allow_pickle=False), pattern)
            self.assertTrue(logic.terminate_dev())

    def test_saving_panel_round_trip_is_no_io(self):
        from devices.auto_focus.autofocus_main import AutofocusMain
        logic, axis = self.make_logic()
        panel = AutofocusMain(logic)
        self.addCleanup(panel.close)
        settings = replace(quick_settings(), output=OutputSettings(True, "chosen-results", True))
        panel.load_controls(settings)
        self.assertEqual(panel.read_settings(), settings)
        self.assertEqual(axis.moves, [])
        self.assertFalse(logic.connected)

    def test_worker_runs_without_blocking_ui_and_scan_methods_return_numeric_results(self):
        logic, axis = self.make_logic()
        logic.connect_z()
        ticks = []
        timer = QtCore.QTimer()
        timer.setInterval(1)
        timer.timeout.connect(lambda: ticks.append(1))
        timer.start()
        logic.settings = replace(logic.settings, search=replace(logic.settings.search, settle_s=0.005))
        self.assertTrue(logic.submit(logic.set_focus, 1))
        deadline = time.monotonic() + 2
        while logic.isRunning() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        timer.stop()
        self.assertFalse(logic.isRunning())
        self.assertGreater(len(ticks), 2)
        self.assertAlmostEqual(logic.get_z(), 2.3, delta=0.32)
        self.assertEqual(logic.get_focus_score(), logic.result.best_score)
        self.assertTrue(logic.terminate_dev())

    def test_trigger_ignores_finite_value_and_router_detach_is_idempotent(self):
        logic, axis = self.make_logic()
        logic.configure_command_router(FakeRouter(), "focus_tool")
        self.assertEqual(logic.find_catalog_references(removed_getters={"nidaq_AI0"}),
                         ("autofocus uses nidaq/AI0",))
        logic.detach_command_router()
        logic.detach_command_router()
        self.assertIsNone(logic.router)
        logic.connect_z()
        for value in (0, -7, 42.5):
            logic.set_focus(value)
            self.assertEqual(logic.last_outcome, "complete")
        before = list(axis.moves)
        for value in (float("nan"), float("inf"), True, "not numeric"):
            with self.assertRaises(ValueError):
                logic.set_focus(value)
        self.assertEqual(axis.moves, before)
        self.assertTrue(logic.terminate_dev())

    def test_temperature_autofocus_measurement_levels_block_until_focus_completes(self):
        from core.scan_logic import ScanLogic
        logic, axis = self.make_logic()
        logic.connect_z()
        events = []

        class Window:
            equips = {"cryostat": object(), "auto_focus": object(), "measurement": object()}
            artificial_channel_logic = SimpleNamespace(
                artificial_channels=(), has_artificial_channel=lambda channel: False,
                consume_skip_read_for_scan=lambda: False,
            )
            def write_info(self, value, channel):
                if channel == "cryostat_temperature":
                    events.append(("temperature", value))
                elif channel == "auto_focus_focus":
                    events.append(("focus_start", value))
                    logic.set_focus(value)
                    events.append(("focus_done", logic.last_outcome))
                else:
                    self_value = logic.get_z()
                    self_test.assertAlmostEqual(self_value, 2.3, delta=0.32)
                    events.append(("measurement", value))
            def read_info(self, channel):
                return logic.get_focus_score() if channel == "auto_focus_focus_score" else 123.0

        self_test = self
        def level(channel, values, getters=()):
            return {"setters": {"setter0": {"channel": channel}}, "getters": list(getters),
                    "setting_array": np.array([values]), "settle_time": 0, "start_wait_time": 0,
                    "manual_set_before": [], "manual_set_after": []}
        scan = ScanLogic(main_window=Window())
        scan.initialize_scan_data({"levels": {
            "level2": level("cryostat_temperature", [100, 110]),
            "level1": level("auto_focus_focus", [0], ["auto_focus_focus_score"]),
            "level0": level("measurement_bias", [1, 2], ["measurement_signal"]),
        }})
        scan.looping(scan.max_level)
        self.assertEqual([event[0] for event in events],
                         ["temperature", "focus_start", "focus_done", "measurement", "measurement"] * 2)
        self.assertTrue(np.isfinite(scan.level_data_arrays[1]).all())
        self.assertTrue(logic.terminate_dev())

    def test_termination_waits_for_inflight_move_without_disconnecting_under_worker(self):
        logic, axis = self.make_logic()
        entered, release = threading.Event(), threading.Event()
        def blocked_move(target, stop):
            entered.set()
            release.wait(1)
            axis.current = target
            return target
        axis._move_once = blocked_move
        logic.connect_z()
        self.assertTrue(logic.submit(logic.set_focus, 1))
        self.assertTrue(entered.wait(1))
        self.assertFalse(logic.terminate_dev(wait_ms=5))
        self.assertTrue(axis.connected)
        release.set()
        self.assertTrue(logic.wait(1000))
        self.assertEqual(logic.history, [])
        self.assertTrue(logic.terminate_dev())
        self.assertFalse(axis.connected)

    def test_setup_and_result_files_use_explicit_temporary_paths(self):
        import tempfile
        from unittest import mock
        from devices.auto_focus.autofocus_main import AutofocusMain
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "setup.json"
            AutofocusMain.write_json(str(path), quick_settings().to_dict())
            self.assertEqual(AutofocusSettings.from_dict(json.loads(path.read_text())), quick_settings())
            # Rejected serialization must not damage an existing setup.
            original = path.read_bytes()
            with self.assertRaises(ValueError):
                AutofocusMain.write_json(str(path), {"bad": float("nan")})
            self.assertEqual(path.read_bytes(), original)

            logic, axis = self.make_logic()
            panel = AutofocusMain(logic)
            self.addCleanup(panel.close)
            logic.connect_z()
            logic.sig_sample.connect(lambda item: logic.force_stop() if item is not None else None)
            with self.assertRaises(FocusStopped):
                logic.set_focus(1)
            self.assertEqual(logic.last_outcome, "stopped")
            self.assertEqual(len(logic.history), 1)
            self.assertIsNone(logic.result)
            export = Path(directory) / "partial.json"
            with mock.patch.object(QtWidgets.QFileDialog, "getSaveFileName", return_value=(str(export), "")):
                panel._export_result()
            saved = json.loads(export.read_text())
            self.assertEqual(saved["outcome"], "stopped")
            self.assertIsNone(saved["result"])
            self.assertEqual(AutofocusSettings.from_dict(saved["settings"]), logic.run_settings)
            self.assertEqual(saved["samples"][0]["score"], logic.history[0].score)
            self.assertIn("stopped", saved["error"])
            self.assertTrue(logic.terminate_dev())

    def test_real_panel_construction_and_mode_selection_are_side_effect_free(self):
        from unittest import mock
        from devices.auto_focus.autofocus_main import AutofocusMain
        with mock.patch("devices.auto_focus.autofocus_hardware.RoutedZAxis.connect", side_effect=AssertionError("hardware access")):
            panel = AutofocusMain()
        self.addCleanup(panel.close)
        self.assertFalse(panel.logic.connected)
        panel.source_mode.setCurrentIndex(panel.source_mode.findData("raster"))
        self.assertEqual(panel.read_settings().search.metric, "gradient")
        panel.z_backend.setCurrentIndex(panel.z_backend.findData("routed"))
        panel.pickers["z.setter"].set_ref(Channel("piezo_stage", "Z"))
        panel.pickers["z.getter"].set_ref(Channel("piezo_stage", "Z"))
        panel.fields["z.native_unit"].setText("V")
        self.assertEqual(panel.read_settings().z.unit, "V")
        self.assertTrue(panel.terminate_dev())

    def test_registration_is_lazy_and_new_profile_entry_is_manual(self):
        from core.device_management.registry import build_default_registry
        registration = build_default_registry().registration("auto_focus")
        self.assertEqual(registration.runtime_services, ())
        from unittest import mock
        with mock.patch("core.device_management.registrations.import_module") as importer:
            registration.factory()
            importer.assert_called_once_with("devices.auto_focus.autofocus_main")
        import subprocess
        import sys
        script = (
            "import sys; from core.device_management.registry import build_default_registry; "
            "assert 'auto_focus' in build_default_registry().driver_ids; "
            "assert not any(k == 'devices' or k.startswith('devices.') for k in sys.modules)"
        )
        process = subprocess.run([sys.executable, "-B", "-c", script],
                                 cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_profile_parses_and_manager_constructs_panel_without_connecting_hardware(self):
        from unittest import mock
        from core.device_management.config import load_profile
        from core.device_management.manager import DeviceManager
        from core.device_management.registry import build_default_registry
        registry = build_default_registry()
        root = Path(__file__).resolve().parents[3]
        profile = load_profile(root / "device_config.xlsx", driver_specs=registry.config_specs, repository_root=root)
        config = next(c for c in profile.devices if c.driver == "auto_focus")
        self.assertFalse(config.enabled)
        self.assertFalse(config.connect_on_start)
        self.assertEqual(config.connection["address"], "")
        self.assertEqual(config.scan_channels.setters, ("focus",))
        self.assertEqual(config.scan_channels.getters, ("z", "focus_score"))
        config = replace(config, enabled=True)  # Enable only the isolated test coordinator.
        with mock.patch("devices.auto_focus.autofocus_hardware.RoutedZAxis.connect", side_effect=AssertionError("real hardware")) as connect:
            manager = DeviceManager(registry, SimpleNamespace())
            snapshot = manager.load_profile(replace(profile, devices=(config,)))
            manager.request_startup_connections()
            self.assertEqual(tuple(snapshot.equipment), (config.id,))
            self.assertFalse(snapshot.equipment[config.id].logic.connected)
            self.assertTrue(manager.teardown_all().succeeded)
            connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
