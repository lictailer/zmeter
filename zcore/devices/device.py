"""The ``Device`` base class and its immutable ``DeviceSpec`` (ADR 004, decisions 1 and 3).

A declarative device is a subclass of ``Device`` with a ``driver_class`` and a
table of declarations. When the subclass is created, ``__init_subclass__``
collects the declarations (inherited ones included), checks everything that
needs the whole class, and stores one frozen ``DeviceSpec``. A declaration
mistake therefore fails at import time, not when a scan runs.

The Runner (phase 1, PR 4) owns threads, ordering, limits and lifecycle; this
module only describes the device.
"""

import inspect
from dataclasses import dataclass
from types import FunctionType, MappingProxyType
from typing import Any, ClassVar

from .declarations import (
    ACTION_ATTRIBUTE,
    NUMERIC_TYPES,
    Action,
    ArrayParameter,
    Connection,
    DeclarationError,
    MultiParameter,
    Parameter,
    Trigger,
)

DECLARATION_TYPES = (Parameter, Trigger, ArrayParameter, MultiParameter)

# Optional standard actions, recognized by name, with their number of
# arguments besides ``self``. They get fixed panel buttons.
STANDARD_ACTIONS = MappingProxyType({"reset": 0, "self_test": 0, "set_display": 1})


@dataclass(frozen=True)
class DeviceSpec:
    """Everything the rest of zmeter needs to know about a device class.

    Mappings are read-only and keep declaration order (inherited declarations
    first). ``readouts``, ``controls``, ``arrays`` and ``snapshot`` are the
    names that become scan readout channels, scan control channels, array
    readout channels and setup-capture readings.
    """

    name: str
    driver_class: type | None
    connection: Connection
    parameters: MappingProxyType
    triggers: MappingProxyType
    arrays: MappingProxyType
    multis: MappingProxyType
    actions: MappingProxyType
    standard_actions: tuple[str, ...]
    has_write_many: bool
    has_stop_hardware: bool
    readouts: tuple[str, ...]
    controls: tuple[str, ...]
    snapshot: tuple[str, ...]

    @property
    def names(self) -> tuple[str, ...]:
        """Every name in the device's name space: declarations, components,
        actions."""
        names = []
        names.extend(self.parameters)
        names.extend(self.triggers)
        names.extend(self.arrays)
        for name, multi in self.multis.items():
            names.append(name)
            names.extend(multi.components)
        names.extend(self.actions)
        return tuple(names)


class Device:
    """Base class of a declarative device.

    Subclasses set ``driver_class`` (the hardware layer, reused as is) and
    declare parameters, triggers, arrays, multi-parameters and ``@action``
    methods as class attributes. They may override:

    * ``connect(address, timeout_s)`` and ``disconnect()``. The defaults build
      ``driver_class()`` and call its ``connect(address, timeout_s)`` and
      ``disconnect()``.
    * ``stop_hardware()``: stop motion or ramping at the hardware. Required
      when the device declares a ramp or a long action or trigger. It must be
      safe to call while another driver call is in progress.
    * ``write_many(values)``: optional grouped write of ``{name: value}``.
    * the optional standard actions ``reset()``, ``self_test()`` and
      ``set_display(on)``.

    A driver instance can be injected for tests: ``MyDevice(driver=fake)``.
    """

    driver_class: ClassVar[type | None] = None
    connection: ClassVar[Connection] = Connection()

    def __init__(self, driver: Any = None):
        self.driver = driver
        self._driver_injected = driver is not None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        cls._device_spec = _build_spec(cls)

    @classmethod
    def spec(cls) -> DeviceSpec:
        """The immutable description of this device class, built once when the
        class was created."""
        spec = cls.__dict__.get("_device_spec")
        if spec is None:
            raise TypeError("Device itself has no spec; declare a subclass")
        return spec

    def connect(self, address, timeout_s: float) -> None:
        if self.driver is None:
            self.driver = self.driver_class()
        self.driver.connect(address, timeout_s)

    def disconnect(self) -> None:
        driver = self.driver
        if driver is None:
            return
        try:
            driver.disconnect()
        finally:
            if not self._driver_injected:
                self.driver = None

    def stop_hardware(self) -> None:
        raise NotImplementedError(f"{type(self).__name__} does not implement stop_hardware()")


# Names a declaration may not use: everything the base class defines, the
# instance attributes it sets, and the optional hooks.
RESERVED_NAMES = frozenset(
    {name for name in vars(Device) if not name.startswith("__")}
    | {"driver", "_driver_injected", "_device_spec", "write_many"}
    | set(STANDARD_ACTIONS)
)


def _signature(func):
    try:
        return inspect.signature(func)
    except (TypeError, ValueError):
        # Builtins without a signature: cannot check, do not reject.
        return None


def _accepts(func, count) -> bool:
    """Whether ``func`` can be called with ``count`` positional arguments."""
    signature = _signature(func)
    if signature is None:
        return True
    try:
        signature.bind(*([None] * count))
    except TypeError:
        return False
    return True


def _plural(count):
    return "argument" if count == 1 else "arguments"


def _check_ref(where, field, ref, driver_class, nargs):
    """Check one hardware reference. ``nargs`` is the number of arguments the
    call takes besides the driver or device (0 for get, 1 for set)."""
    if ref is None:
        return
    if isinstance(ref, str):
        if driver_class is None:
            raise DeclarationError(
                f"{where}: {field}={ref!r} names a driver method, but driver_class is not set"
            )
        raw = inspect.getattr_static(driver_class, ref, None)
        if raw is None:
            raise DeclarationError(
                f"{where}: {field}={ref!r} is not a method of {driver_class.__name__}"
            )
        if isinstance(raw, (staticmethod, classmethod)):
            func, extra = getattr(driver_class, ref), 0
        elif callable(raw):
            func, extra = raw, 1
        else:
            raise DeclarationError(
                f"{where}: {driver_class.__name__}.{ref} is not a method"
            )
        if not _accepts(func, nargs + extra):
            raise DeclarationError(
                f"{where}: {driver_class.__name__}.{ref} cannot be called with "
                f"{nargs} {_plural(nargs)}"
            )
        return
    # A callable receives the device instance first.
    if not _accepts(ref, nargs + 1):
        raise DeclarationError(
            f"{where}: {field} callable must accept the device and {nargs} more "
            f"{_plural(nargs)}"
        )


def _collect(cls):
    """Declarations and actions in attribute-lookup order: base classes first,
    a subclass attribute overrides or hides an inherited one."""
    declarations = {}
    actions = {}
    for klass in reversed(cls.__mro__):
        if klass is object:
            continue
        for name, value in vars(klass).items():
            marker = getattr(value, ACTION_ATTRIBUTE, None) if callable(value) else None
            if isinstance(value, DECLARATION_TYPES):
                actions.pop(name, None)
                declarations[name] = value
            elif isinstance(marker, Action):
                declarations.pop(name, None)
                actions[name] = (value, marker)
            else:
                declarations.pop(name, None)
                actions.pop(name, None)
    return declarations, actions


def _implements(cls, name):
    return callable(getattr(cls, name, None))


def _build_spec(cls) -> DeviceSpec:
    owner = cls.__qualname__
    driver_class = cls.driver_class
    if driver_class is not None and not isinstance(driver_class, type):
        raise DeclarationError(f"{owner}: driver_class must be a class, got {driver_class!r}")
    if not isinstance(cls.connection, Connection):
        raise DeclarationError(f"{owner}: connection must be a Connection, got {cls.connection!r}")

    declarations, actions = _collect(cls)

    # Names: one name space for declarations, components and actions.
    seen = {}
    for name in list(declarations) + list(actions):
        where = f"{owner}.{name}"
        if name in STANDARD_ACTIONS and name in actions:
            raise DeclarationError(
                f"{where}: {name}() is a standard action; define it without @action"
            )
        if name.startswith("_") or name in RESERVED_NAMES:
            raise DeclarationError(f"{where}: the name {name!r} is reserved")
        seen[name] = name
    for name, declaration in declarations.items():
        if isinstance(declaration, MultiParameter):
            for component in declaration.components:
                if component.startswith("_") or component in RESERVED_NAMES:
                    raise DeclarationError(
                        f"{owner}.{name}: component name {component!r} is reserved"
                    )
                if component in seen:
                    raise DeclarationError(
                        f"{owner}.{name}: component {component!r} is already used by "
                        f"{seen[component]!r}; names must be unique across parameters, "
                        f"components and actions"
                    )
                seen[component] = name

    # Hardware references.
    for name, declaration in declarations.items():
        where = f"{owner}.{name}"
        if isinstance(declaration, Parameter):
            _check_ref(where, "get", declaration.get, driver_class, 0)
            _check_ref(where, "set", declaration.set, driver_class, 1)
        elif isinstance(declaration, Trigger):
            _check_ref(where, "call", declaration.call, driver_class, 0)
        elif isinstance(declaration, ArrayParameter):
            _check_ref(where, "get", declaration.get, driver_class, 0)
            if not isinstance(declaration.shape, tuple):
                _check_ref(where, "shape", declaration.shape, driver_class, 0)
            _check_ref(where, "axis_values", declaration.axis_values, driver_class, 0)
        elif isinstance(declaration, MultiParameter):
            _check_ref(where, "get", declaration.get, driver_class, 0)

    # Ramp rates that name another parameter.
    for name, declaration in declarations.items():
        if not (isinstance(declaration, Parameter) and declaration.ramp is not None):
            continue
        rate = declaration.ramp.rate
        if not isinstance(rate, str):
            continue
        source = declarations.get(rate)
        if (
            rate == name
            or not isinstance(source, Parameter)
            or source.dtype not in NUMERIC_TYPES
            or not source.is_readable
        ):
            raise DeclarationError(
                f"{owner}.{name}: ramp rate {rate!r} must name another readable "
                f"float or int parameter of this device"
            )

    # Actions take no arguments in phase 1; standard actions keep their signatures.
    for name, (func, _marker) in actions.items():
        if not isinstance(func, FunctionType):
            raise DeclarationError(f"{owner}.{name}: @action applies to plain methods")
        signature = _signature(func)
        params = list(signature.parameters.values()) if signature else []
        if len(params) != 1 or params[0].kind not in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            raise DeclarationError(
                f"{owner}.{name}: an action takes no arguments besides self"
            )
    standard_actions = []
    for name, nargs in STANDARD_ACTIONS.items():
        if not _implements(cls, name):
            continue
        if not _accepts(getattr(cls, name), nargs + 1):
            raise DeclarationError(
                f"{owner}.{name}: the standard action {name}() takes {nargs} "
                f"{_plural(nargs)} besides self"
            )
        standard_actions.append(name)

    # Lifecycle methods.
    hooks = {"connect": 2, "disconnect": 0, "stop_hardware": 0, "write_many": 1}
    for name, nargs in hooks.items():
        if _implements(cls, name) and not _accepts(getattr(cls, name), nargs + 1):
            raise DeclarationError(
                f"{owner}.{name}() must take {nargs} {_plural(nargs)} besides self"
            )
    if cls.connect is Device.connect:
        if driver_class is None:
            raise DeclarationError(
                f"{owner}: set driver_class or override connect(address, timeout_s)"
            )
        if not _accepts(driver_class, 0):
            raise DeclarationError(
                f"{owner}: the default connect() builds {driver_class.__name__}() "
                f"without arguments; override connect(address, timeout_s)"
            )
        _check_ref(f"{owner} (default connect)", "connect", "connect", driver_class, 2)
    if cls.disconnect is Device.disconnect:
        if driver_class is None:
            raise DeclarationError(f"{owner}: set driver_class or override disconnect()")
        _check_ref(f"{owner} (default disconnect)", "disconnect", "disconnect", driver_class, 0)
    has_stop_hardware = cls.stop_hardware is not Device.stop_hardware
    needs_stop = [
        name
        for name, declaration in declarations.items()
        if (isinstance(declaration, Parameter) and declaration.ramp is not None)
        or (isinstance(declaration, Trigger) and declaration.long)
    ] + [name for name, (_func, marker) in actions.items() if marker.long]
    if needs_stop and not has_stop_hardware:
        raise DeclarationError(
            f"{owner}: {', '.join(needs_stop)} ramp or run long, so the device must "
            f"implement stop_hardware()"
        )

    def of_type(kind):
        return MappingProxyType(
            {name: d for name, d in declarations.items() if isinstance(d, kind)}
        )

    readouts, controls, snapshot = [], [], []
    for name, declaration in declarations.items():
        if isinstance(declaration, Parameter):
            if declaration.scan and declaration.is_readable:
                readouts.append(name)
            if declaration.scan and declaration.is_settable:
                controls.append(name)
            if declaration.snapshot:
                snapshot.append(name)
        elif isinstance(declaration, Trigger) and declaration.scan:
            controls.append(name)
        elif isinstance(declaration, MultiParameter):
            readouts.extend(declaration.components)

    return DeviceSpec(
        name=cls.__name__,
        driver_class=driver_class,
        connection=cls.connection,
        parameters=of_type(Parameter),
        triggers=of_type(Trigger),
        arrays=of_type(ArrayParameter),
        multis=of_type(MultiParameter),
        actions=MappingProxyType({name: marker for name, (_f, marker) in actions.items()}),
        standard_actions=tuple(standard_actions),
        has_write_many=_implements(cls, "write_many"),
        has_stop_hardware=has_stop_hardware,
        readouts=tuple(readouts),
        controls=tuple(controls),
        snapshot=tuple(snapshot),
    )
