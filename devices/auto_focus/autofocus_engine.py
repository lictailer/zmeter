"""Hardware-independent autofocus contracts, settings, metrics and search.

Extension points: implement ZAxis or FocusSource, or add a FocusMetric to
METRICS. Nothing in this module opens an instrument, camera, file or Qt app.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import threading
from typing import Callable, Protocol

import numpy as np
from core.measurement_io import Channel, count, finite


class FocusStopped(RuntimeError):
    """Cooperative stop; no return/home move is implied."""


def checkpoint(stop: threading.Event) -> None:
    if stop.is_set():
        raise FocusStopped("Autofocus stopped; axes remain at their last completed move")


def pause(stop: threading.Event, seconds: float) -> None:
    if stop.wait(seconds):
        checkpoint(stop)


@dataclass(frozen=True)
class ZSettings:
    backend: str = "routed"
    native_unit: str = "deg"
    convert_to_distance: bool = False
    distance_unit: str = "um"
    distance_per_native: float = 0.0  # Must be calibrated explicitly when enabled.
    native_zero: float = 0.0
    distance_zero: float = 0.0
    minimum: float = -20.0
    maximum: float = 20.0
    max_move: float = 10.0
    tolerance: float = 0.1  # Covers half of one nominal 2048-step motor revolution step.
    command_timeout_s: float = 120.0
    setter: Channel = field(default_factory=lambda: Channel("arduino_steppers", "stepperA_angle"))
    getter: Channel = field(default_factory=lambda: Channel("arduino_steppers", "stepperA_angle"))

    @property
    def unit(self) -> str:
        return self.distance_unit if self.convert_to_distance else self.native_unit

    def from_native(self, position: float) -> float:
        position = finite(position, "Native position")
        return finite(self.distance_zero + (position - self.native_zero) * self.distance_per_native
                      if self.convert_to_distance else position, "Converted Z position")

    def to_native(self, position: float) -> float:
        position = finite(position, "Z position")
        return finite(self.native_zero + (position - self.distance_zero) / self.distance_per_native
                      if self.convert_to_distance else position, "Converted native position")

    def validate(self) -> None:
        lo, hi = finite(self.minimum, "Z minimum"), finite(self.maximum, "Z maximum")
        if lo >= hi or finite(self.max_move, "Maximum Z move") <= 0:
            raise ValueError("Z minimum must be below maximum and maximum move must be positive")
        if finite(self.tolerance, "Z tolerance") <= 0:
            raise ValueError("Z tolerance must be positive")
        if finite(self.command_timeout_s, "Z command timeout") <= 0:
            raise ValueError("Z command timeout must be positive")
        if not self.native_unit.strip():
            raise ValueError("Enter the native Z unit")
        if type(self.convert_to_distance) is not bool:
            raise ValueError("convert_to_distance must be a boolean")
        for name in ("distance_per_native", "native_zero", "distance_zero"):
            finite(getattr(self, name), name)
        if self.convert_to_distance:
            if self.distance_unit not in ("um", "mm") or self.distance_per_native == 0:
                raise ValueError("Enter a nonzero calibrated distance per native unit and select um or mm")

    def validate_target(self, position: float) -> float:
        position = finite(position, "Z position")
        if not self.minimum <= position <= self.maximum:
            raise ValueError(f"Z {position:g} {self.unit} outside [{self.minimum:g}, {self.maximum:g}]")
        return position


@dataclass(frozen=True)
class SourceSettings:
    mode: str = "point"
    signal: Channel = field(default_factory=lambda: Channel("nidaq", "AI0"))
    x: Channel = field(default_factory=lambda: Channel("nidaq", "AO0"))
    y: Channel = field(default_factory=lambda: Channel("nidaq", "AO1"))
    position_xy: bool = False
    x_center: float = 0.0
    y_center: float = 0.0
    x_span: float = 0.1
    y_span: float = 0.1
    x_points: int = 9
    y_points: int = 9
    xy_minimum: float = -1.0
    xy_maximum: float = 1.0
    xy_settle_s: float = 0.01
    samples: int = 5
    sample_interval_s: float = 0.01
    camera_index: int = 0
    discard_frames: int = 2
    roi: tuple[int, int, int, int] = (0, 0, 0, 0)

    def validate(self) -> None:
        if type(self.position_xy) is not bool:
            raise ValueError("position_xy must be a boolean")
        count(self.samples, "Samples", 1, 1000)
        for key in ("xy_settle_s", "sample_interval_s"):
            if finite(getattr(self, key), key) < 0:
                raise ValueError(f"{key} must be nonnegative")
        if self.mode != "camera":
            self.signal.validate()
        if self.mode == "raster" or (self.mode == "point" and self.position_xy):
            self.x.validate()
            self.y.validate()
            if self.x == self.y:
                raise ValueError("X and Y must use different output channels")
            lo, hi = finite(self.xy_minimum, "XY minimum"), finite(self.xy_maximum, "XY maximum")
            if lo >= hi:
                raise ValueError("XY minimum must be below maximum")
            for center, span in ((self.x_center, self.x_span), (self.y_center, self.y_span)):
                center, span = finite(center, "XY center"), finite(span, "XY span")
                if span < 0 or (self.mode == "raster" and span == 0):
                    raise ValueError("Raster spans must be positive")
                radius = span / 2 if self.mode == "raster" else 0
                if center - radius < lo or center + radius > hi:
                    raise ValueError("The full XY path must lie inside the configured XY limits")
        if self.mode == "raster":
            count(self.x_points, "X pixels", 3, 256)
            count(self.y_points, "Y pixels", 3, 256)
        if self.mode == "camera":
            count(self.camera_index, "Camera index", 0, 100)
            count(self.discard_frames, "Discard frames", 0, 100)
            if len(self.roi) != 4 or any(type(v) is not int or v < 0 for v in self.roi):
                raise ValueError("Camera ROI must be four nonnegative integers: x, y, width, height")
            if (self.roi[2] == 0) != (self.roi[3] == 0):
                raise ValueError("Set both ROI dimensions or use 0,0 for the full frame")


@dataclass(frozen=True)
class SearchSettings:
    method: str = "adaptive_brent"
    bounds_mode: str = "relative"
    start_offset: float = -10.0
    stop_offset: float = 10.0
    absolute_lower: float = -10.0
    absolute_upper: float = 10.0
    sweep_points: int = 41
    gaussian_min_r_squared: float = 0.8
    initial_step: float = 1.0
    position_precision: float = 0.2
    max_evaluations: int = 40
    coarse_points: int = 9
    refine_points: int = 5
    refinement_rounds: int = 2
    settle_s: float = 0.1
    metric: str = "mean"
    objective: str = "maximize"
    minimum_score_change: float = 0.0
    move_to_best: bool = True

    def validate(self) -> None:
        if self.method not in ("adaptive_brent", "grid", "sweep_maximum", "sweep_gaussian"):
            raise ValueError("Unknown Z search method")
        if self.bounds_mode not in ("relative", "absolute"):
            raise ValueError("Unknown Z search bounds mode")
        if type(self.move_to_best) is not bool:
            raise ValueError("move_to_best must be a boolean")
        if finite(self.start_offset, "Search start") >= finite(self.stop_offset, "Search stop"):
            raise ValueError("Search start offset must be below stop offset")
        if finite(self.absolute_lower, "Absolute lower Z") >= finite(self.absolute_upper, "Absolute upper Z"):
            raise ValueError("Absolute lower Z must be below absolute upper Z")
        count(self.sweep_points, "Sweep Z points", 3, 1001)
        if self.method == "sweep_gaussian" and self.sweep_points < 7:
            raise ValueError("Gaussian fitting needs at least 7 sweep positions")
        if not 0 <= finite(self.gaussian_min_r_squared, "Minimum Gaussian R squared") <= 1:
            raise ValueError("Minimum Gaussian R squared must be between 0 and 1")
        count(self.coarse_points, "Coarse points", 3, 101)
        count(self.refine_points, "Refinement points", 3, 21)
        count(self.refinement_rounds, "Refinement rounds", 0, 6)
        count(self.max_evaluations, "Maximum focus evaluations", 3, 1000)
        for key in ("initial_step", "position_precision"):
            if finite(getattr(self, key), key) <= 0:
                raise ValueError(f"{key} must be positive")
        if finite(self.settle_s, "Z settling time") < 0:
            raise ValueError("Z settling time must be nonnegative")
        if finite(self.minimum_score_change, "Minimum score change") < 0:
            raise ValueError("Minimum score change must be nonnegative")
        if self.metric not in METRICS or self.objective not in ("maximize", "minimize"):
            raise ValueError("Unknown focus metric or optimization direction")


@dataclass(frozen=True)
class OutputSettings:
    enabled: bool = False
    directory: str = ""
    save_frames: bool = False

    def validate(self):
        if type(self.enabled) is not bool or type(self.save_frames) is not bool:
            raise ValueError("Saving options must be booleans")
        if not isinstance(self.directory, str) or (self.enabled and not self.directory.strip()):
            raise ValueError("Choose an autofocus results directory")


@dataclass(frozen=True)
class AutofocusSettings:
    z: ZSettings = field(default_factory=ZSettings)
    source: SourceSettings = field(default_factory=SourceSettings)
    search: SearchSettings = field(default_factory=SearchSettings)
    output: OutputSettings = field(default_factory=OutputSettings)

    def validate(self) -> None:
        self.z.validate()
        self.source.validate()
        self.search.validate()
        self.output.validate()
        if self.source.mode == "point" and not METRICS[self.search.metric].scalar:
            raise ValueError("Single-point acquisition needs the mean-signal metric")
        if self.z.backend == "routed":
            self.z.setter.validate()
            self.z.getter.validate()
            if self.source.mode != "camera" and self.z.setter == self.source.signal:
                raise ValueError("The Z output cannot also be the focus signal")
            if self.source.mode == "raster" or self.source.position_xy:
                if self.z.setter in (self.source.x, self.source.y):
                    raise ValueError("The Z output cannot also be an XY output")

    def to_dict(self) -> dict:
        return {"schema_version": 2, **asdict(self)}

    @classmethod
    def from_dict(cls, data: dict) -> "AutofocusSettings":
        if data.get("schema_version") != 2 or set(data) not in (
            {"schema_version", "z", "source", "search"}, {"schema_version", "z", "source", "search", "output"}
        ):
            raise ValueError("Autofocus setup schema 2 is required: select the standalone motor device/channel and review units/calibration; old files are not modified")
        z, source = dict(data["z"]), dict(data["source"])
        for name in ("setter", "getter"):
            z[name] = Channel(**z[name])
        for name in ("signal", "x", "y"):
            source[name] = Channel(**source[name])
        source["roi"] = tuple(source["roi"])
        search = dict(data["search"])
        # Pre-optimizer schema-2 files must not silently change their motion plan.
        search.setdefault("method", "grid")
        result = cls(ZSettings(**z), SourceSettings(**source), SearchSettings(**search), OutputSettings(**data.get("output", {})))
        result.validate()
        return result


class ZAxis(Protocol):
    def position(self) -> float: ...
    def move_to(self, target: float, stop: threading.Event) -> float: ...
    def validate_path(self, lower: float, upper: float) -> None: ...


class FocusSource(Protocol):
    def prepare(self, stop: threading.Event) -> None: ...
    def acquire(self, stop: threading.Event): ...
    def close(self) -> None: ...


def image_data(data) -> np.ndarray:
    image = np.asarray(data, dtype=float)
    if image.ndim == 3 and image.shape[2] in (3, 4):
        image = image[:, :, :3].mean(axis=2)
    if image.ndim != 2 or min(image.shape) < 3 or not np.isfinite(image).all():
        raise ValueError("Focus image must be a finite 2D image of at least 3 by 3 pixels")
    return image


def mean_signal(data) -> float:
    values = np.asarray(data, dtype=float)
    if not values.size or not np.isfinite(values).all():
        raise ValueError("Focus signal contains missing or nonfinite values")
    return float(values.mean())


def gradient_energy(data) -> float:
    image = image_data(data)
    return float(np.square(np.diff(image, axis=0)).mean() + np.square(np.diff(image, axis=1)).mean())


def laplacian_variance(data) -> float:
    image = image_data(data)
    lap = (image[:-2, 1:-1] + image[2:, 1:-1] + image[1:-1, :-2]
           + image[1:-1, 2:] - 4 * image[1:-1, 1:-1])
    return float(lap.var())


@dataclass(frozen=True)
class FocusMetric:
    label: str
    score: Callable
    scalar: bool = False


METRICS = {
    "mean": FocusMetric("Average input signal (at each Z)", mean_signal, True),
    "gradient": FocusMetric("Image gradient energy", gradient_energy),
    "laplacian": FocusMetric("Image Laplacian variance", laplacian_variance),
}


@dataclass(frozen=True)
class FocusSample:
    target: float
    position: float
    score: float
    level: int


@dataclass
class GaussianFit:
    baseline: float
    amplitude: float
    center: float
    sigma: float
    r_squared: float

    def values(self, positions):
        return self.baseline + self.amplitude * np.exp(-0.5 * ((np.asarray(positions) - self.center) / self.sigma) ** 2)


def fit_gaussian(samples, search, tolerance, stop):
    """Fit baseline + signed Gaussian to actual acknowledged Z coordinates.

    Normalize both axes for numerical conditioning across native/distance units.
    Fit failures are explicit: there is no automatic measured-maximum fallback.
    """
    from scipy.optimize import curve_fit

    # Average scores at duplicate acknowledged positions, not at nominal targets.
    grouped = {}
    for sample in samples:
        grouped.setdefault(round(sample.position, 12), []).append(sample.score)
    if len(grouped) < 7:
        raise ValueError("Gaussian fitting needs at least 7 distinct acknowledged Z positions")
    positions = np.array(sorted(grouped), dtype=float)
    scores = np.array([np.mean(grouped[p]) for p in positions], dtype=float)
    sign = 1 if search.objective == "maximize" else -1
    width = float(np.ptp(positions))
    x = (positions - positions[0]) / width
    y0, yrange = float(np.min(sign * scores)), float(np.ptp(scores))
    if yrange <= search.minimum_score_change:
        raise ValueError("Signal has insufficient variation for Gaussian fitting")
    y = (sign * scores - y0) / yrange
    min_sigma = float(np.min(np.diff(x))) / 2

    def model(xdata, baseline, amplitude, center, sigma):
        checkpoint(stop)
        return baseline + amplitude * np.exp(-0.5 * ((xdata - center) / sigma) ** 2)

    parameters, covariance = curve_fit(
        model, x, y, p0=(0, 1, float(x[np.argmax(y)]), max(0.15, 2 * min_sigma)),
        bounds=([-np.inf, 0, 0, min_sigma], [np.inf, np.inf, 1, 1]),
        method="trf", max_nfev=2000,
    )
    checkpoint(stop)
    if not np.isfinite(parameters).all() or not np.isfinite(covariance).all():
        raise ValueError("Gaussian fit parameters or covariance are not finite")
    baseline, amplitude, center, sigma = map(float, parameters)
    predicted = model(x, *parameters)
    r_squared = finite(1 - np.sum((y - predicted) ** 2) / np.sum((y - y.mean()) ** 2), "Gaussian R squared")
    if r_squared < search.gaussian_min_r_squared:
        raise ValueError(f"Gaussian fit R squared {r_squared:.4g} is below {search.gaussian_min_r_squared:g}")
    if sigma <= min_sigma * 1.01 or sigma >= 0.99:
        raise ValueError("Gaussian width is unresolved or reaches the fitted width bound; review the Z range/spacing")
    center_z = float(positions[0] + center * width)
    if not positions[0] + tolerance < center_z < positions[-1] - tolerance:
        raise ValueError("Gaussian peak is at the sweep boundary")
    return GaussianFit(finite(sign * (y0 + baseline * yrange), "Gaussian baseline"),
                       finite(sign * amplitude * yrange, "Gaussian amplitude"),
                       center_z, finite(sigma * width, "Gaussian sigma"), r_squared)


@dataclass
class FocusResult:
    origin: float
    best_position: float
    best_score: float
    samples: list[FocusSample]
    status: str
    applied: bool = False
    final_position: float | None = None
    selected_position: float | None = None
    gaussian_fit: GaussianFit | None = None
    fit_error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class _EvaluationBudgetReached(Exception):
    """Internal control flow; completed samples remain available to the caller."""


def _adaptive_brent(evaluate, origin, lower, upper, search, tolerance, sign):
    """Bracket uphill from the starting position, then run bounded Brent.

    This is local, derivative-free optimization, not a global-maximum guarantee.
    All probes are clipped to the already validated interval. The bounded SciPy
    solver (unlike unbounded Brent/bracket) cannot expand outside that interval.
    """
    from scipy.optimize import minimize_scalar

    precision = max(search.position_precision, 2 * tolerance)
    step = max(search.initial_step, precision)
    center = min(upper, max(lower, origin))
    middle = evaluate(center, 0)
    probes = [middle]
    for target in (max(lower, center - step), min(upper, center + step)):
        probes.append(evaluate(target, 0))
    best = max(probes, key=lambda sample: sign * sample.score)
    if best is middle and all(sign * middle.score > sign * p.score
                              for p in probes if p is not middle):
        # Both sides are worse: the initial probes already bracket a peak.
        lower, upper = min(p.target for p in probes), max(p.target for p in probes)
    elif sign * best.score > sign * middle.score:
        direction = 1 if best.target > center else -1
        previous, current = center, best.target
        distance = abs(current - center)
        while True:
            target = min(upper, max(lower, current + direction * 2 * distance))
            if target == current:
                return "complete"  # Improving all the way to a search boundary.
            sample = evaluate(target, 0)
            if sign * sample.score <= sign * best.score:
                lower, upper = sorted((previous, target))
                break
            previous, current, best = current, target, sample
            distance *= 2
    # Equal initial scores do not prove the whole interval is flat. In that case
    # search the original interval rather than claiming an early flat result.
    if upper - lower <= precision:
        return "complete"
    optimized = minimize_scalar(
        lambda target: -sign * evaluate(float(target), 1).score,
        bounds=(lower, upper), method="bounded",
        options={"xatol": precision, "maxiter": search.max_evaluations},
    )
    return "complete" if optimized.success else "max_evaluations"


def run_focus(axis: ZAxis, source: FocusSource, settings: AutofocusSettings,
              stop: threading.Event, on_sample: Callable | None = None,
              history: list[FocusSample] | None = None) -> FocusResult:
    """Adaptive/grid search, or a full sweep with measured/ Gaussian selection.

    Bounds are either relative to one measured starting position or absolute.
    Edge maxima and flat curves are reported without a final best-position move.
    Exceptions/stop leave axes where their last completed command placed them.
    """
    settings.validate()
    checkpoint(stop)
    z, search = settings.z, settings.search
    origin = z.validate_target(axis.position())
    lower = z.validate_target(search.absolute_lower if search.bounds_mode == "absolute" else origin + search.start_offset)
    upper = z.validate_target(search.absolute_upper if search.bounds_mode == "absolute" else origin + search.stop_offset)
    axis.validate_path(lower, upper)
    records = history if history is not None else []
    cache: dict[float, FocusSample] = {}
    position_cache: dict[float, FocusSample] = {}
    score_fn = METRICS[search.metric].score
    sign = 1 if search.objective == "maximize" else -1

    def evaluate(target, level):
        checkpoint(stop)
        target = float(target)
        if not lower <= target <= upper:
            raise ValueError("Optimizer target is outside the validated search interval")
        key = round(target, 12)
        if key in cache:
            return cache[key]
        if search.method == "adaptive_brent" and len(position_cache) >= search.max_evaluations:
            raise _EvaluationBudgetReached
        actual = finite(axis.move_to(target, stop), "Z readback")
        if abs(actual - target) > z.tolerance:
            raise RuntimeError(f"Z failed to reach {target:g}; readback was {actual:g}")
        actual_key = round(actual, 12)
        if search.method == "adaptive_brent" and actual_key in position_cache:
            # Quantized actuators may acknowledge the same position for nearby
            # targets. Do not spend another image evaluating that position.
            cache[key] = position_cache[actual_key]
            return cache[key]
        pause(stop, search.settle_s)
        data = source.acquire(stop)
        score = finite(score_fn(data), "Focus score")
        sample = FocusSample(target, actual, score, level)
        cache[key] = position_cache[actual_key] = sample
        records.append(sample)
        if on_sample:
            on_sample(sample, data)
        return sample

    try:
        source.prepare(stop)
        status = "complete"
        if search.method == "adaptive_brent":
            try:
                status = _adaptive_brent(evaluate, origin, lower, upper, search, z.tolerance, sign)
            except _EvaluationBudgetReached:
                status = "max_evaluations"
        elif search.method.startswith("sweep_"):
            for target in np.linspace(lower, upper, search.sweep_points):
                evaluate(target, 0)
        else:
            grid = np.linspace(lower, upper, search.coarse_points)
            for level in range(search.refinement_rounds + 1):
                for target in grid:
                    evaluate(target, level)
                best = max(cache.values(), key=lambda sample: sign * sample.score)
                if level == search.refinement_rounds:
                    break
                ordered = sorted(cache.values(), key=lambda sample: sample.target)
                index = ordered.index(best)
                left = ordered[max(0, index - 1)].target
                right = ordered[min(len(ordered) - 1, index + 1)].target
                if right - left <= 2 * z.tolerance:
                    break
                grid = np.linspace(left, right, search.refine_points)
        best = max(cache.values(), key=lambda sample: sign * sample.score)
        spread = max(s.score for s in records) - min(s.score for s in records)
        if status == "complete" and spread <= search.minimum_score_change:
            status = "flat_signal"
        elif status == "complete" and (abs(best.target - lower) <= z.tolerance or abs(best.target - upper) <= z.tolerance):
            status = "boundary_peak"
        result = FocusResult(origin, best.position, best.score, list(records), status)
        result.selected_position = best.position
        if search.method == "sweep_gaussian" and status == "complete":
            try:
                result.gaussian_fit = fit_gaussian(records, search, z.tolerance, stop)
                result.selected_position = z.validate_target(result.gaussian_fit.center)
            except FocusStopped:
                raise
            except (RuntimeError, ValueError) as exc:
                result.status = "fit_failed"
                result.fit_error = str(exc)
                result.selected_position = None
        checkpoint(stop)
        if search.move_to_best and result.status == "complete":
            final = finite(axis.move_to(result.selected_position, stop), "Final Z readback")
            if abs(final - result.selected_position) > z.tolerance:
                raise RuntimeError("Final Z position did not confirm the selected focus position")
            result.applied = True
            result.final_position = final
        else:
            result.final_position = finite(axis.position(), "Final Z readback")
        return result
    finally:
        source.close()
