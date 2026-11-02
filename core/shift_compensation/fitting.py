"""CSV loading and fit models for Shift Compensation mappings.

Pure numerical code: no Qt, no device access.

A mapping CSV has two numeric columns.  Column 1 is the source value in the
units of the source readback.  Column 2 is the amount that must be *added*
to the target channel so the target stays on the same physical position when
the source sits at that value.  One optional header row is skipped.
"""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

MODEL_COSINE = "cosine"
MODEL_POLYNOMIAL = "polynomial"
MODELS = (MODEL_COSINE, MODEL_POLYNOMIAL)

MAX_POLYNOMIAL_ORDER = 10


class MappingCsvError(ValueError):
    """The CSV file cannot be used as a mapping."""


class MappingFitError(ValueError):
    """The requested fit cannot be computed from the mapping points."""


def _parse_float(text: str) -> float | None:
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def parse_mapping_rows(rows: Iterable[Sequence[str]]) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(source, shift)`` arrays from CSV rows.

    Blank rows are ignored.  Only the first non-blank row may be a header;
    any later row that does not hold two finite numbers is an error.
    """

    xs: list[float] = []
    ys: list[float] = []
    seen_first = False
    for line_number, row in enumerate(rows, start=1):
        cells = [str(cell).strip() for cell in row]
        if not any(cells):
            continue
        values = [_parse_float(cell) for cell in cells[:2]]
        is_numeric = len(values) == 2 and None not in values
        if not seen_first:
            seen_first = True
            if not is_numeric:
                continue  # header row
        if not is_numeric:
            raise MappingCsvError(
                f"line {line_number}: expected two numbers, got {row!r}"
            )
        xs.append(float(values[0]))
        ys.append(float(values[1]))
    if len(xs) < 2:
        raise MappingCsvError("a mapping needs at least two data rows")
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def load_mapping_csv(path: str | os.PathLike) -> tuple[np.ndarray, np.ndarray]:
    """Read a two-column mapping CSV file."""

    try:
        with open(path, "r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            return parse_mapping_rows(csv.reader(handle, dialect))
    except OSError as exc:
        raise MappingCsvError(f"cannot read '{path}': {exc}") from exc


@dataclass(frozen=True)
class FitResult:
    """A fitted model.  ``evaluate`` gives the target shift at a source value."""

    model: str
    options: Mapping[str, Any]
    params: Mapping[str, Any]
    rms: float
    r2: float
    n_points: int

    def evaluate(self, x):
        return evaluate_model(self.model, self.params, x)

    def describe(self) -> str:
        if self.model == MODEL_COSINE:
            p = self.params
            return (
                f"y = {p['A']:.6g} cos(2πx/{p['P']:.6g} + {p['C']:.6g}) "
                f"+ {p['D']:.6g}"
            )
        coeffs = list(self.params["coefficients"])
        terms = [f"{c:.6g}" + (f" x^{k}" if k else "") for k, c in enumerate(coeffs)]
        return "y = " + " + ".join(terms)

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "options": dict(self.options),
            "params": _json_params(self.params),
            "rms": float(self.rms),
            "r2": float(self.r2),
            "n_points": int(self.n_points),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FitResult":
        model = str(payload["model"])
        if model not in MODELS:
            raise MappingFitError(f"unknown fit model '{model}'")
        params = dict(payload["params"])
        if model == MODEL_COSINE:
            params = {key: float(params[key]) for key in ("A", "P", "C", "D")}
        else:
            params = {
                "coefficients": [float(c) for c in params["coefficients"]]
            }
        return cls(
            model=model,
            options=dict(payload.get("options", {})),
            params=params,
            rms=float(payload.get("rms", float("nan"))),
            r2=float(payload.get("r2", float("nan"))),
            n_points=int(payload.get("n_points", 0)),
        )


def _json_params(params: Mapping[str, Any]) -> dict:
    result = {}
    for key, value in params.items():
        if isinstance(value, (list, tuple, np.ndarray)):
            result[key] = [float(v) for v in value]
        else:
            result[key] = float(value)
    return result


def evaluate_model(model: str, params: Mapping[str, Any], x):
    x_arr = np.asarray(x, dtype=float)
    if model == MODEL_COSINE:
        value = params["A"] * np.cos(
            2.0 * np.pi * x_arr / params["P"] + params["C"]
        ) + params["D"]
    elif model == MODEL_POLYNOMIAL:
        value = np.polynomial.polynomial.polyval(x_arr, params["coefficients"])
    else:
        raise MappingFitError(f"unknown fit model '{model}'")
    if np.ndim(value) == 0:
        return float(value)
    return value


def _quality(y: np.ndarray, y_fit: np.ndarray) -> tuple[float, float]:
    residual = y - y_fit
    rms = float(np.sqrt(np.mean(residual**2)))
    total = float(np.sum((y - y.mean()) ** 2))
    r2 = float(1.0 - np.sum(residual**2) / total) if total > 0 else float("nan")
    return rms, r2


def _cosine_linear(x, y, period):
    w = 2.0 * np.pi / period
    design = np.column_stack([np.cos(w * x), np.sin(w * x), np.ones_like(x)])
    (a, b, d), *_ = np.linalg.lstsq(design, y, rcond=None)
    amplitude = float(math.hypot(a, b))
    # A cos(wx + C) = A cos C cos wx - A sin C sin wx
    phase = float(math.atan2(-b, a))
    return amplitude, phase, float(d)


def fit_cosine(x, y, period: float, free_period: bool = False) -> FitResult:
    """Fit ``y = A cos(2 pi x / P + C) + D``.

    With ``free_period`` False the period is fixed to ``period`` and the fit
    is linear least squares.  With ``free_period`` True the period is fitted
    as well, starting from ``period``.
    """

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    try:
        period = float(period)
    except (TypeError, ValueError) as exc:
        raise MappingFitError("the cosine period must be a number") from exc
    if not math.isfinite(period) or period == 0:
        raise MappingFitError("the cosine period must be a finite non-zero number")
    needed = 4 if free_period else 3
    if x.size < needed:
        raise MappingFitError(f"a cosine fit needs at least {needed} points")

    amplitude, phase, offset = _cosine_linear(x, y, period)
    fitted_period = period
    if free_period:
        from scipy.optimize import curve_fit

        def model(xv, a, p, c, d):
            return a * np.cos(2.0 * np.pi * xv / p + c) + d

        try:
            popt, _ = curve_fit(
                model,
                x,
                y,
                p0=[amplitude if amplitude > 0 else float(np.std(y)) or 1.0,
                    period, phase, offset],
                maxfev=20000,
            )
        except Exception as exc:  # scipy raises RuntimeError / OptimizeWarning
            raise MappingFitError(f"free-period cosine fit failed: {exc}") from exc
        amplitude, fitted_period, phase, offset = (float(v) for v in popt)
        if not math.isfinite(fitted_period) or fitted_period == 0:
            raise MappingFitError("free-period cosine fit gave an invalid period")
        if amplitude < 0:
            amplitude = -amplitude
            phase += math.pi
    phase = float(math.atan2(math.sin(phase), math.cos(phase)))
    params = {"A": amplitude, "P": float(fitted_period), "C": phase, "D": offset}
    rms, r2 = _quality(y, evaluate_model(MODEL_COSINE, params, x))
    return FitResult(
        model=MODEL_COSINE,
        options={"period": period, "free_period": bool(free_period)},
        params=params,
        rms=rms,
        r2=r2,
        n_points=int(x.size),
    )


def fit_polynomial(x, y, order: int) -> FitResult:
    """Fit ``y = sum_k c_k x^k`` up to ``order``."""

    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    try:
        order = int(order)
    except (TypeError, ValueError) as exc:
        raise MappingFitError("the polynomial order must be an integer") from exc
    if order < 1 or order > MAX_POLYNOMIAL_ORDER:
        raise MappingFitError(
            f"the polynomial order must be between 1 and {MAX_POLYNOMIAL_ORDER}"
        )
    if x.size < order + 1:
        raise MappingFitError(
            f"a polynomial of order {order} needs at least {order + 1} points"
        )
    poly = np.polynomial.Polynomial.fit(x, y, order)
    coefficients = [float(c) for c in poly.convert().coef]
    coefficients += [0.0] * (order + 1 - len(coefficients))
    params = {"coefficients": coefficients}
    rms, r2 = _quality(y, evaluate_model(MODEL_POLYNOMIAL, params, x))
    return FitResult(
        model=MODEL_POLYNOMIAL,
        options={"order": order},
        params=params,
        rms=rms,
        r2=r2,
        n_points=int(x.size),
    )


def fit_mapping(x, y, model: str, options: Mapping[str, Any]) -> FitResult:
    if model == MODEL_COSINE:
        return fit_cosine(
            x,
            y,
            options.get("period", 360.0),
            bool(options.get("free_period", False)),
        )
    if model == MODEL_POLYNOMIAL:
        return fit_polynomial(x, y, options.get("order", 1))
    raise MappingFitError(f"unknown fit model '{model}'")
