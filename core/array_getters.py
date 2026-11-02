"""Array-valued scan getters.

A device logic declares which of its ``get_*`` methods return arrays (a
spectrum, a camera frame) with an ``ARRAY_GETTERS`` class attribute::

    ARRAY_GETTERS = {
        "spectrum": ArrayGetter(
            axes=("pixel",),
            shape="spectrum_shape",
            axis_values="spectrum_axis",
            units="counts",
        ),
        "image": ArrayGetter(axes=("row", "column"), shape="image_shape"),
    }

``axes`` names the array axes in array order (``arr.shape[i]`` belongs to
``axes[i]``).  ``shape`` names a logic method that returns the current shape
as a tuple of ints, one per axis.  ``axis_values`` optionally names a logic
method that returns the coordinate of each point: a 1-D sequence for a
one-axis getter, or a mapping ``{axis name: 1-D sequence}``.  An axis without
values uses its point index.

The scan turns every axis into a locked "fixed" level below the user's levels
(see ``core.array_levels``), so the scan data, plots and JSON keep their
scalar layout.  The engine reads the getter once per outer point and stores
the whole array.  Nothing here is specific to two axes: ``MAX_ARRAY_DIMS`` is
the only limit, and raising it is the upgrade path once plots can show more
dimensions.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Mapping

import numpy as np


MAX_ARRAY_DIMS = 2

# Largest number of values one array read may hold.  A 2048 x 2048 frame is
# about 4.2 M points; anything larger would not fit a JSON scan file anyway.
MAX_ARRAY_POINTS = 4_194_304


@dataclass(frozen=True)
class ArrayGetter:
    """Static declaration of one array getter on a device logic."""

    axes: tuple[str, ...]
    shape: str
    axis_values: str | None = None
    units: str = ""

    def __post_init__(self):
        axes = tuple(str(axis) for axis in self.axes)
        if not axes:
            raise ValueError("An array getter needs at least one axis.")
        if len(set(axes)) != len(axes):
            raise ValueError(f"Array getter axes must be unique: {axes}")
        object.__setattr__(self, "axes", axes)


@dataclass(frozen=True)
class ArrayInfo:
    """Live description of one array getter (shape read from the device)."""

    channel: str
    axes: tuple[str, ...]
    shape: tuple[int, ...]
    axis_values: tuple[tuple[float, ...], ...]
    units: str = ""

    @property
    def ndim(self) -> int:
        return len(self.axes)

    @property
    def size(self) -> int:
        return int(math.prod(self.shape))

    def label(self) -> str:
        """Short display text such as ``andor_0_spectrum [1024]``."""
        dims = " x ".join(str(n) for n in self.shape)
        return f"{self.channel} [{dims}]"


class ArrayShapeError(ValueError):
    """An array read did not match the declared or expected shape."""


def array_getter_specs(logic) -> dict[str, ArrayGetter]:
    """Return the validated ``ARRAY_GETTERS`` declaration of a logic object."""
    declared = getattr(type(logic), "ARRAY_GETTERS", None)
    if declared is None:
        declared = getattr(logic, "ARRAY_GETTERS", None)
    if not declared:
        return {}
    specs = {}
    for name, spec in dict(declared).items():
        if not isinstance(spec, ArrayGetter):
            raise TypeError(
                f"ARRAY_GETTERS[{name!r}] must be an ArrayGetter, got {type(spec).__name__}"
            )
        if len(spec.axes) > MAX_ARRAY_DIMS:
            raise ValueError(
                f"Array getter {name!r} has {len(spec.axes)} axes; "
                f"at most {MAX_ARRAY_DIMS} are supported."
            )
        specs[str(name)] = spec
    return specs


def is_array_variable(logic, variable) -> bool:
    """Whether ``get_<variable>`` is declared as an array getter (no device call)."""
    try:
        return str(variable) in array_getter_specs(logic)
    except (TypeError, ValueError):
        return False


def _normalise_shape(raw, spec: ArrayGetter, channel: str) -> tuple[int, ...]:
    try:
        shape = tuple(int(n) for n in raw)
    except TypeError:
        shape = (int(raw),)
    if len(shape) != len(spec.axes):
        raise ArrayShapeError(
            f"{channel}: shape {shape} does not match axes {spec.axes}"
        )
    if any(n < 1 for n in shape):
        raise ArrayShapeError(f"{channel}: shape {shape} has an empty axis")
    if math.prod(shape) > MAX_ARRAY_POINTS:
        raise ArrayShapeError(
            f"{channel}: shape {shape} holds more than {MAX_ARRAY_POINTS} points"
        )
    return shape


def _normalise_axis_values(raw, spec: ArrayGetter, shape, channel):
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        if len(spec.axes) != 1:
            raise ArrayShapeError(
                f"{channel}: axis values for a {len(spec.axes)}-axis getter "
                "must be a mapping of axis name to values"
            )
        raw = {spec.axes[0]: raw}
    values = []
    for axis, length in zip(spec.axes, shape):
        axis_raw = raw.get(axis)
        if axis_raw is None:
            values.append(tuple(float(i) for i in range(length)))
            continue
        axis_array = np.asarray(axis_raw, dtype=float).ravel()
        if axis_array.size != length or not np.all(np.isfinite(axis_array)):
            # A calibration that does not fit the shape is not trusted.
            values.append(tuple(float(i) for i in range(length)))
            continue
        values.append(tuple(float(v) for v in axis_array))
    return tuple(values)


def describe_array_getter(logic, variable, channel=None) -> ArrayInfo | None:
    """Read the live shape (and axis values) of an array getter.

    Returns ``None`` when the variable is not an array getter.  Raises
    ``ArrayShapeError`` when the device reports an unusable shape.
    """
    specs = array_getter_specs(logic)
    spec = specs.get(str(variable))
    if spec is None:
        return None
    channel = channel or str(variable)
    shape_method = getattr(logic, spec.shape, None)
    if not callable(shape_method):
        raise ArrayShapeError(f"{channel}: shape method {spec.shape!r} is missing")
    shape = _normalise_shape(shape_method(), spec, channel)
    raw_values = None
    if spec.axis_values:
        values_method = getattr(logic, spec.axis_values, None)
        if callable(values_method):
            raw_values = values_method()
    return ArrayInfo(
        channel=channel,
        axes=spec.axes,
        shape=shape,
        axis_values=_normalise_axis_values(raw_values, spec, shape, channel),
        units=spec.units,
    )


def validate_array(value, expected_shape, channel="") -> np.ndarray:
    """Return ``value`` as a float array of ``expected_shape`` or raise."""
    expected_shape = tuple(int(n) for n in expected_shape)
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ArrayShapeError(
            f"{channel}: array read is not numeric ({type(exc).__name__}: {exc})"
        ) from exc
    if array.shape != expected_shape:
        raise ArrayShapeError(
            f"{channel}: array read has shape {array.shape}, expected {expected_shape}"
        )
    return array


class ArrayCatalog:
    """Answers array questions about full scan channel names.

    ``resolve`` maps a channel such as ``andor_0_spectrum`` to
    ``(logic, variable)`` or ``None``.  The main window builds one from its
    device table; tests can pass any callable.
    """

    def __init__(self, resolve: Callable[[str], tuple[object, str] | None] | None = None):
        self._resolve = resolve

    def _lookup(self, channel):
        if self._resolve is None or not isinstance(channel, str):
            return None
        try:
            return self._resolve(channel)
        except Exception:  # noqa: BLE001 - a bad device must not break menus
            return None

    def is_array(self, channel) -> bool:
        resolved = self._lookup(channel)
        if resolved is None:
            return False
        logic, variable = resolved
        return is_array_variable(logic, variable)

    def info(self, channel) -> ArrayInfo | None:
        resolved = self._lookup(channel)
        if resolved is None:
            return None
        logic, variable = resolved
        try:
            return describe_array_getter(logic, variable, channel)
        except Exception:  # noqa: BLE001 - offline device: shape unknown
            return None

    def info_or_error(self, channel):
        """Like ``info`` but returns ``(info, error_text)`` for start checks."""
        resolved = self._lookup(channel)
        if resolved is None:
            return None, None
        logic, variable = resolved
        try:
            return describe_array_getter(logic, variable, channel), None
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"


EMPTY_CATALOG = ArrayCatalog()
