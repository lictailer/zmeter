"""Declaration types of the declarative device SDK (ADR 004, decision 2).

These are frozen, Qt-free values. A device class lists them as class
attributes; ``zcore.devices.device.Device`` collects and cross-checks them when
the class is created. Everything a declaration can check on its own is checked
in its constructor, so a mistake fails at the line that declares it.

References to hardware calls (``get``, ``set``, ``call``, an array ``shape``)
are either the name of a method on the device's ``driver_class`` or a callable
that receives the device instance (``get(device)``, ``set(device, value)``,
``call(device)``). A callable is usually a function defined earlier in the
class body, so it can use ``device.driver`` and the device's own helpers.
"""

import math
import numbers
from collections.abc import Callable, Mapping
from dataclasses import KW_ONLY, dataclass
from pathlib import Path
from typing import Any

# A reference to a hardware call: a driver method name or a callable that
# receives the device instance.
Ref = str | Callable[..., Any]

VALUE_TYPES = (float, int, bool, str, Path)
NUMERIC_TYPES = (float, int)
MAX_ARRAY_AXES = 2


class DeclarationError(ValueError):
    """A device declaration is invalid. Raised when the class is created."""


def _is_real(value) -> bool:
    return isinstance(value, numbers.Real) and not isinstance(value, bool)


def _is_finite_real(value) -> bool:
    return _is_real(value) and math.isfinite(value)


def _check_positive(owner, field, value, *, allow_none=False, allow_zero=False):
    if value is None and allow_none:
        return
    ok = _is_finite_real(value) and (value >= 0 if allow_zero else value > 0)
    if not ok:
        bound = ">= 0" if allow_zero else "> 0"
        raise DeclarationError(f"{owner}: {field} must be a finite number {bound}, got {value!r}")


def _check_bool(owner, field, value):
    if not isinstance(value, bool):
        raise DeclarationError(f"{owner}: {field} must be True or False, got {value!r}")


def _check_unit(owner, unit):
    if unit is not None and not (isinstance(unit, str) and unit.strip()):
        raise DeclarationError(f"{owner}: unit must be a non-empty string or None, got {unit!r}")


def _check_ref(owner, field, ref, *, required):
    if ref is None:
        if required:
            raise DeclarationError(f"{owner}: {field} is required")
        return
    if isinstance(ref, str):
        if not ref.isidentifier():
            raise DeclarationError(f"{owner}: {field} must name a driver method, got {ref!r}")
        return
    if not callable(ref):
        raise DeclarationError(
            f"{owner}: {field} must be a driver method name or a callable, got {ref!r}"
        )


def _check_name(owner, what, name):
    if not (isinstance(name, str) and name.isidentifier()):
        raise DeclarationError(f"{owner}: {what} must be an identifier, got {name!r}")


def _names(owner, what, values):
    """Normalize a sequence of identifier names to a tuple; no duplicates."""
    if isinstance(values, str):
        values = (values,)
    try:
        names = tuple(values)
    except TypeError:
        raise DeclarationError(f"{owner}: {what} must be a sequence of names, got {values!r}")
    for name in names:
        _check_name(owner, what, name)
    if len(set(names)) != len(names):
        raise DeclarationError(f"{owner}: {what} must be unique, got {names!r}")
    return names


@dataclass(frozen=True)
class Unlimited:
    """Explicit "this settable parameter has no device limit", with a reason.

    Build it with ``unlimited("reason")``. The Runner logs a warning for it at
    connect (ADR 003, decision 4).
    """

    reason: str

    def __post_init__(self):
        if not (isinstance(self.reason, str) and self.reason.strip()):
            raise DeclarationError("unlimited(): a reason is required")


def unlimited(reason: str) -> Unlimited:
    """State that a settable numeric parameter has no device limit, and why."""
    return Unlimited(reason)


@dataclass(frozen=True)
class Choice:
    """A fixed set of discrete states with labels; used as a ``Parameter`` dtype.

    ``options`` is a mapping ``{label: value}`` or a sequence of values (each
    labelled ``str(value)``). Values are all numbers or all strings. The option
    set is the parameter's limit, so a ``Choice`` parameter takes no
    ``limits``. ``settle_s`` is the wait after a change (relays, switch
    matrices).

    Stored normalized: ``options`` is a tuple of ``(label, value)`` pairs.
    """

    options: Any
    settle_s: float = 0.0

    def __post_init__(self):
        owner = "Choice"
        raw = self.options
        if isinstance(raw, Mapping):
            pairs = tuple(raw.items())
        elif isinstance(raw, (str, bytes)):
            raise DeclarationError(f"{owner}: options must be a sequence or mapping, got {raw!r}")
        else:
            try:
                pairs = tuple((str(value), value) for value in raw)
            except TypeError:
                raise DeclarationError(
                    f"{owner}: options must be a sequence or mapping, got {raw!r}"
                )
        if not pairs:
            raise DeclarationError(f"{owner}: options must not be empty")
        labels = [label for label, _ in pairs]
        values = [value for _, value in pairs]
        for label in labels:
            if not (isinstance(label, str) and label.strip()):
                raise DeclarationError(f"{owner}: labels must be non-empty strings, got {label!r}")
        for value in values:
            if not (_is_finite_real(value) or isinstance(value, str)):
                raise DeclarationError(
                    f"{owner}: values must be finite numbers or strings, got {value!r}"
                )
        if len({_is_real(value) for value in values}) > 1:
            raise DeclarationError(f"{owner}: values must be all numbers or all strings")
        if len(set(values)) != len(values):
            raise DeclarationError(f"{owner}: values must be unique, got {values!r}")
        _check_positive(owner, "settle_s", self.settle_s, allow_zero=True)
        object.__setattr__(self, "options", pairs)

    @property
    def labels(self) -> tuple:
        return tuple(label for label, _ in self.options)

    @property
    def values(self) -> tuple:
        return tuple(value for _, value in self.options)

    @property
    def is_numeric(self) -> bool:
        return _is_real(self.options[0][1])


@dataclass(frozen=True)
class Ramp:
    """Stepped write. ``rate`` is in parameter units per second, either a
    number or the name of another (readable, numeric) parameter of the same
    device; ``interval`` is the time between steps in seconds."""

    rate: float | str
    interval: float = 0.05

    def __post_init__(self):
        owner = "Ramp"
        if isinstance(self.rate, str):
            _check_name(owner, "rate", self.rate)
        else:
            _check_positive(owner, "rate", self.rate)
        _check_positive(owner, "interval", self.interval)


@dataclass(frozen=True)
class Stable:
    """The readout must stay within ``tolerance`` for ``duration_s`` seconds;
    give up after ``timeout_s`` seconds."""

    tolerance: float
    duration_s: float
    timeout_s: float

    def __post_init__(self):
        owner = "Stable"
        _check_positive(owner, "tolerance", self.tolerance)
        _check_positive(owner, "duration_s", self.duration_s, allow_zero=True)
        _check_positive(owner, "timeout_s", self.timeout_s)
        if self.timeout_s <= self.duration_s:
            raise DeclarationError(
                f"{owner}: timeout_s ({self.timeout_s}) must be longer than "
                f"duration_s ({self.duration_s})"
            )


@dataclass(frozen=True)
class Connection:
    """How a device is addressed: the address type (``str`` or ``int``) and the
    connect timeout in seconds. Generates the registry's driver config, the
    panel's address field and the connect timeout."""

    address: type = str
    timeout_s: float = 10.0

    def __post_init__(self):
        owner = "Connection"
        if self.address not in (str, int):
            raise DeclarationError(f"{owner}: address must be str or int, got {self.address!r}")
        _check_positive(owner, "timeout_s", self.timeout_s)


@dataclass(frozen=True)
class Parameter:
    """One named value of a device.

    ``dtype`` is ``float``, ``int``, ``bool``, ``str``, ``Path`` or a
    ``Choice``. A parameter with ``get`` only is a readout parameter; with
    ``set`` it is a control parameter. ``scan=True`` exposes it as a readout
    channel (``get``) and/or a control channel (``set``).

    Rules checked here (see ADR 004, decision 3):

    * a settable ``float``/``int`` parameter needs ``limits=(low, high)`` or
      ``limits=unlimited("reason")``; no other parameter takes limits;
    * ``scan`` and ``snapshot`` parameters are numeric (a numeric ``Choice``
      counts); ``str`` and ``Path`` parameters are panel settings only;
    * ``ramp`` only on settable ``float``/``int`` parameters that can be read
      (the ramp starts from the read value);
    * ``safe`` needs ``set`` and is a valid value inside the limits.
    """

    dtype: Any
    _: KW_ONLY
    unit: str | None = None
    limits: tuple | Unlimited | None = None
    get: Ref | None = None
    set: Ref | None = None
    scan: bool = False
    snapshot: bool = False
    poll: float | None = None
    ramp: Ramp | None = None
    stable: Stable | None = None
    safe: Any = None
    timeout: float | None = None
    group: str | None = None
    order: int | None = None
    hidden: bool = False
    doc: str = ""

    def __post_init__(self):
        owner = "Parameter"
        dtype = self.dtype
        if dtype is Choice:
            raise DeclarationError(f"{owner}: use a Choice instance, Choice(options), as dtype")
        if not (isinstance(dtype, Choice) or dtype in VALUE_TYPES):
            raise DeclarationError(
                f"{owner}: dtype must be float, int, bool, str, Path or a Choice, got {dtype!r}"
            )
        _check_ref(owner, "get", self.get, required=False)
        _check_ref(owner, "set", self.set, required=False)
        if self.get is None and self.set is None:
            raise DeclarationError(f"{owner}: needs get, set, or both")
        for field in ("scan", "snapshot", "hidden"):
            _check_bool(owner, field, getattr(self, field))
        if self.unit is not None and not self.is_numeric:
            raise DeclarationError(f"{owner}: unit applies only to numeric parameters")
        _check_unit(owner, self.unit)
        self._check_limits(owner)
        if self.scan and not self.is_numeric:
            if dtype in (str, Path):
                raise DeclarationError(f"{owner}: str and Path parameters are never scannable")
            raise DeclarationError(f"{owner}: scan=True needs a numeric parameter, got {dtype!r}")
        if self.snapshot:
            if not self.is_numeric:
                raise DeclarationError(
                    f"{owner}: snapshot=True needs a numeric parameter, because snapshot "
                    f"values are also scan readouts; got {dtype!r}"
                )
            if self.get is None:
                raise DeclarationError(f"{owner}: snapshot=True needs get")
        if self.poll is not None:
            _check_positive(owner, "poll", self.poll)
            if self.get is None:
                raise DeclarationError(f"{owner}: poll needs get")
        if self.ramp is not None:
            if not isinstance(self.ramp, Ramp):
                raise DeclarationError(f"{owner}: ramp must be a Ramp, got {self.ramp!r}")
            if not (self.is_settable and dtype in NUMERIC_TYPES):
                raise DeclarationError(f"{owner}: ramp applies only to settable float or int parameters")
            if self.get is None:
                raise DeclarationError(f"{owner}: a ramp starts from the read value, so it needs get")
        if self.stable is not None:
            if not isinstance(self.stable, Stable):
                raise DeclarationError(f"{owner}: stable must be a Stable, got {self.stable!r}")
            if dtype not in NUMERIC_TYPES or self.get is None:
                raise DeclarationError(f"{owner}: stable applies only to readable float or int parameters")
        self._check_safe(owner)
        _check_positive(owner, "timeout", self.timeout, allow_none=True)
        if self.group is not None and not isinstance(self.group, str):
            raise DeclarationError(f"{owner}: group must be a string or None, got {self.group!r}")
        if self.order is not None and not (isinstance(self.order, int) and not isinstance(self.order, bool)):
            raise DeclarationError(f"{owner}: order must be an int or None, got {self.order!r}")
        if not isinstance(self.doc, str):
            raise DeclarationError(f"{owner}: doc must be a string, got {self.doc!r}")

    def _check_limits(self, owner):
        limits = self.limits
        needs_limits = self.is_settable and self.dtype in NUMERIC_TYPES
        if not needs_limits:
            if limits is not None:
                if isinstance(self.dtype, Choice):
                    reason = "the options of a Choice are its limits"
                elif not self.is_settable:
                    reason = "limits apply only to settable parameters"
                else:
                    reason = "limits apply only to float and int parameters"
                raise DeclarationError(f"{owner}: unexpected limits; {reason}")
            return
        if limits is None:
            raise DeclarationError(
                f"{owner}: a settable numeric parameter needs limits=(low, high) "
                f'or limits=unlimited("reason")'
            )
        if isinstance(limits, Unlimited):
            return
        if isinstance(limits, (str, bytes)) or not hasattr(limits, "__len__") or len(limits) != 2:
            raise DeclarationError(f"{owner}: limits must be (low, high), got {limits!r}")
        low, high = limits
        if not (_is_finite_real(low) and _is_finite_real(high)):
            raise DeclarationError(f"{owner}: limits must be finite numbers, got {limits!r}")
        if not low < high:
            raise DeclarationError(f"{owner}: limits need low < high, got {limits!r}")
        object.__setattr__(self, "limits", (low, high))

    def _check_safe(self, owner):
        safe = self.safe
        if safe is None:
            return
        if not self.is_settable:
            raise DeclarationError(f"{owner}: safe needs set")
        dtype = self.dtype
        if isinstance(dtype, Choice):
            ok = safe in dtype.values and _is_real(safe) == dtype.is_numeric
        elif dtype is bool:
            ok = isinstance(safe, bool)
        elif dtype is int:
            ok = _is_real(safe) and isinstance(safe, numbers.Integral)
        elif dtype is float:
            ok = _is_finite_real(safe)
        else:
            raise DeclarationError(f"{owner}: safe does not apply to str or Path parameters")
        if not ok:
            raise DeclarationError(f"{owner}: safe value {safe!r} is not a valid {dtype!r} value")
        if isinstance(self.limits, tuple):
            low, high = self.limits
            if not low <= safe <= high:
                raise DeclarationError(f"{owner}: safe value {safe!r} is outside limits {self.limits!r}")

    @property
    def is_readable(self) -> bool:
        return self.get is not None

    @property
    def is_settable(self) -> bool:
        return self.set is not None

    @property
    def is_numeric(self) -> bool:
        if isinstance(self.dtype, Choice):
            return self.dtype.is_numeric
        return self.dtype in NUMERIC_TYPES


@dataclass(frozen=True)
class Trigger:
    """A control channel where writing any finite value runs ``call`` once.

    The value is ignored and only recorded (``auto_focus`` focus, the Slack
    ping). ``long=True`` marks a call that can take a while; the device then
    needs ``stop_hardware``.
    """

    call: Ref
    _: KW_ONLY
    scan: bool = True
    long: bool = False

    def __post_init__(self):
        owner = "Trigger"
        _check_ref(owner, "call", self.call, required=True)
        _check_bool(owner, "scan", self.scan)
        _check_bool(owner, "long", self.long)


@dataclass(frozen=True)
class ArrayParameter:
    """A long array read with at most two axes; a scan readout.

    ``shape`` is a fixed tuple of positive sizes, one per axis, or a reference
    that returns the current shape. ``axis_values`` is ``None`` or a reference
    that returns one sequence of values per axis. ``timeout`` is the read
    timeout in seconds.
    """

    axes: Any
    shape: Any
    axis_values: Ref | None = None
    unit: str | None = None
    _: KW_ONLY
    get: Ref
    timeout: float | None = None

    def __post_init__(self):
        owner = "ArrayParameter"
        axes = _names(owner, "axes", self.axes)
        if not 1 <= len(axes) <= MAX_ARRAY_AXES:
            raise DeclarationError(f"{owner}: needs 1 to {MAX_ARRAY_AXES} axes, got {axes!r}")
        object.__setattr__(self, "axes", axes)
        shape = self.shape
        if isinstance(shape, str) or callable(shape):
            _check_ref(owner, "shape", shape, required=True)
        else:
            try:
                shape = tuple(shape)
            except TypeError:
                raise DeclarationError(f"{owner}: shape must be a tuple or a reference, got {shape!r}")
            if len(shape) != len(axes) or not all(
                isinstance(n, numbers.Integral) and not isinstance(n, bool) and n > 0 for n in shape
            ):
                raise DeclarationError(
                    f"{owner}: shape must have one positive int per axis, got {shape!r}"
                )
            object.__setattr__(self, "shape", shape)
        _check_ref(owner, "axis_values", self.axis_values, required=False)
        _check_unit(owner, self.unit)
        _check_ref(owner, "get", self.get, required=True)
        _check_positive(owner, "timeout", self.timeout, allow_none=True)


@dataclass(frozen=True)
class MultiParameter:
    """Several readout values from one hardware read (SR860 X, Y, R, theta).

    ``get`` returns one value per component, in order. Each component is a
    scan readout named after the component itself, so component names share
    the device's name space. ``unit`` is one unit for all components or a
    mapping ``{component: unit}``; it is stored as ``(component, unit)``
    pairs when given as a mapping.
    """

    components: Any
    _: KW_ONLY
    get: Ref
    unit: Any = None

    def __post_init__(self):
        owner = "MultiParameter"
        components = _names(owner, "components", self.components)
        if not components:
            raise DeclarationError(f"{owner}: components must not be empty")
        object.__setattr__(self, "components", components)
        _check_ref(owner, "get", self.get, required=True)
        unit = self.unit
        if isinstance(unit, Mapping):
            unknown = set(unit) - set(components)
            if unknown:
                raise DeclarationError(f"{owner}: unit names unknown components {sorted(unknown)!r}")
            for value in unit.values():
                _check_unit(owner, value)
            object.__setattr__(self, "unit", tuple((c, unit[c]) for c in components if c in unit))
        else:
            _check_unit(owner, unit)

    def unit_of(self, component: str) -> str | None:
        if isinstance(self.unit, tuple):
            return dict(self.unit).get(component)
        return self.unit


@dataclass(frozen=True)
class Action:
    """What ``@action`` attaches to a method: its panel label and whether it is
    long (busy indicator and Stop)."""

    label: str
    long: bool = False

    def __post_init__(self):
        owner = "action"
        if not (isinstance(self.label, str) and self.label.strip()):
            raise DeclarationError(f"{owner}: label must be a non-empty string, got {self.label!r}")
        _check_bool(owner, "long", self.long)


ACTION_ATTRIBUTE = "__zmeter_action__"


def action(label: str, long: bool = False):
    """Mark a device method as a panel-only operation (homing, load reference).

    The method takes no arguments besides ``self`` in phase 1. It stays an
    ordinary method, so other device code can call it::

        @action("Auto phase")
        def auto_phase(self):
            self.driver.set_auto_phase()
    """
    marker = Action(label, long)

    def decorate(func):
        if not callable(func) or isinstance(func, (staticmethod, classmethod)):
            raise DeclarationError(f"@action applies to plain methods, got {func!r}")
        setattr(func, ACTION_ATTRIBUTE, marker)
        return func

    return decorate
