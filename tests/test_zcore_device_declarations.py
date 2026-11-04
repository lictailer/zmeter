"""Declaration types and class-creation validation of zcore.devices (ADR 004).

Every validation rule has a valid case and at least one violating case. The
tests are Qt-free and use fake drivers only; nothing here can reach hardware.
"""

import dataclasses
import math
import unittest
from pathlib import Path

from zcore.devices import (
    Action,
    ArrayParameter,
    Choice,
    Connection,
    DeclarationError,
    Device,
    DeviceSpec,
    MultiParameter,
    Parameter,
    Ramp,
    Stable,
    Trigger,
    Unlimited,
    action,
    unlimited,
)


class FakeDriver:
    """Minimal driver with the default connect/disconnect shape."""

    def __init__(self):
        self.calls = []

    def connect(self, address, timeout_s):
        self.calls.append(("connect", address, timeout_s))

    def disconnect(self):
        self.calls.append(("disconnect",))

    def get_value(self):
        return 1.0

    def set_value(self, value):
        self.calls.append(("set_value", value))

    def get_rate(self):
        return 0.5

    def read_pair(self):
        return (1.0, 2.0)

    def read_frame(self):
        return [[0.0]]

    def frame_shape(self):
        return (1, 1)

    def fire(self):
        self.calls.append(("fire",))

    def needs_argument(self, value):
        return value

    @staticmethod
    def static_read():
        return 3.0

    not_a_method = 5


def declare(*, base=Device, driver=FakeDriver, **attributes):
    """Create a device class with the given class attributes."""
    namespace = dict(attributes)
    if driver is not None or "driver_class" not in namespace:
        namespace.setdefault("driver_class", driver)
    return type("Example", (base,), namespace)


def read_write(**overrides):
    fields = dict(get="get_value", set="set_value", limits=(-1.0, 1.0))
    fields.update(overrides)
    return Parameter(float, **fields)


class ErrorAssertions(unittest.TestCase):
    def assertDeclarationError(self, pattern):
        return self.assertRaisesRegex(DeclarationError, pattern)


class ParameterRuleTests(ErrorAssertions):
    def test_dtype_must_be_a_value_type_or_choice_instance(self):
        for dtype in (float, int, bool, str, Path, Choice([1, 2])):
            with self.subTest(dtype=dtype):
                Parameter(dtype, get="get_value")
        for dtype in (list, complex, "float", None):
            with self.subTest(dtype=dtype), self.assertDeclarationError("dtype must be"):
                Parameter(dtype, get="get_value")
        with self.assertDeclarationError("Choice instance"):
            Parameter(Choice, get="get_value")

    def test_needs_get_or_set(self):
        self.assertTrue(Parameter(float, get="get_value").is_readable)
        self.assertTrue(read_write(get=None).is_settable)
        with self.assertDeclarationError("needs get, set, or both"):
            Parameter(float)

    def test_get_and_set_are_method_names_or_callables(self):
        Parameter(float, get=lambda device: 1.0)
        for bad in (5, "not a name", ""):
            with self.subTest(get=bad), self.assertDeclarationError("get must"):
                Parameter(float, get=bad)

    def test_settable_numeric_needs_limits_or_unlimited(self):
        for dtype in (float, int):
            with self.subTest(dtype=dtype), self.assertDeclarationError("needs limits"):
                Parameter(dtype, set="set_value")
        explicit = Parameter(float, set="set_value", limits=unlimited("software clamp in driver"))
        self.assertEqual(explicit.limits, Unlimited("software clamp in driver"))
        self.assertEqual(read_write(limits=[0, 2]).limits, (0, 2))

    def test_unlimited_needs_a_reason(self):
        for reason in ("", "   ", None):
            with self.subTest(reason=reason), self.assertDeclarationError("reason is required"):
                unlimited(reason)

    def test_limits_only_on_settable_float_or_int(self):
        with self.assertDeclarationError("only to settable"):
            Parameter(float, get="get_value", limits=(0, 1))
        with self.assertDeclarationError("options of a Choice"):
            Parameter(Choice([1, 2]), set="set_value", limits=(0, 1))
        with self.assertDeclarationError("only to float and int"):
            Parameter(str, set="set_value", limits=(0, 1))

    def test_limits_are_finite_with_low_below_high(self):
        for limits in ((0, math.inf), (math.nan, 1), (1, 1), (2, 1), (0, 1, 2), (0,), "01", (True, 2)):
            with self.subTest(limits=limits), self.assertDeclarationError("limits"):
                read_write(limits=limits)

    def test_scan_needs_a_numeric_parameter(self):
        read_write(scan=True)
        Parameter(Choice({"10 ms": 0.01, "30 ms": 0.03}), get="get_value", scan=True)
        for dtype in (str, Path):
            with self.subTest(dtype=dtype), self.assertDeclarationError("never scannable"):
                Parameter(dtype, get="get_value", scan=True)
        with self.assertDeclarationError("scan=True needs a numeric"):
            Parameter(bool, get="get_value", scan=True)
        with self.assertDeclarationError("scan=True needs a numeric"):
            Parameter(Choice(["SINE", "TTL"]), get="get_value", scan=True)

    def test_snapshot_needs_a_numeric_readable_parameter(self):
        Parameter(Choice([1, 2, 3]), get="get_value", snapshot=True)
        with self.assertDeclarationError("snapshot=True needs a numeric"):
            Parameter(str, get="get_value", snapshot=True)
        with self.assertDeclarationError("snapshot=True needs get"):
            read_write(get=None, snapshot=True)

    def test_poll_is_positive_and_needs_get(self):
        self.assertEqual(Parameter(float, get="get_value", poll=0.2).poll, 0.2)
        for poll in (0, -1, math.inf, "1"):
            with self.subTest(poll=poll), self.assertDeclarationError("poll"):
                Parameter(float, get="get_value", poll=poll)
        with self.assertDeclarationError("poll needs get"):
            read_write(get=None, poll=1.0)

    def test_ramp_only_on_settable_readable_float_or_int(self):
        read_write(ramp=Ramp(0.1))
        Parameter(int, get="get_value", set="set_value", limits=(0, 10), ramp=Ramp(1))
        with self.assertDeclarationError("ramp applies only"):
            Parameter(float, get="get_value", ramp=Ramp(0.1))
        with self.assertDeclarationError("ramp applies only"):
            Parameter(Choice([1, 2]), get="get_value", set="set_value", ramp=Ramp(0.1))
        with self.assertDeclarationError("ramp applies only"):
            Parameter(bool, get="get_value", set="set_value", ramp=Ramp(0.1))
        with self.assertDeclarationError("starts from the read value"):
            read_write(get=None, ramp=Ramp(0.1))
        with self.assertDeclarationError("ramp must be a Ramp"):
            read_write(ramp=0.1)

    def test_stable_only_on_readable_float_or_int(self):
        read_write(stable=Stable(0.05, 30, 1800))
        Parameter(float, get="get_value", stable=Stable(0.05, 30, 1800))
        with self.assertDeclarationError("stable applies only"):
            read_write(get=None, stable=Stable(0.05, 30, 1800))
        with self.assertDeclarationError("stable applies only"):
            Parameter(Choice([1, 2]), get="get_value", stable=Stable(0.05, 30, 1800))
        with self.assertDeclarationError("stable must be a Stable"):
            read_write(stable=(0.05, 30, 1800))

    def test_safe_needs_set_and_a_valid_value_inside_limits(self):
        self.assertEqual(read_write(safe=0.0).safe, 0.0)
        read_write(limits=unlimited("bench supply"), safe=5.0)
        Parameter(bool, set="set_value", safe=False)
        Parameter(int, set="set_value", limits=(0, 3), safe=0)
        Parameter(Choice({"open": 0, "closed": 1}), set="set_value", safe=0)
        with self.assertDeclarationError("safe needs set"):
            Parameter(float, get="get_value", safe=0.0)
        with self.assertDeclarationError("outside limits"):
            read_write(safe=2.0)
        bad_values = [
            (Parameter, (bool,), dict(set="set_value", safe=0)),
            (Parameter, (int,), dict(set="set_value", limits=(0, 3), safe=1.5)),
            (Parameter, (float,), dict(set="set_value", limits=unlimited("x"), safe=math.nan)),
            (Parameter, (float,), dict(set="set_value", limits=(0, 1), safe=True)),
            (Parameter, (Choice([1, 2]),), dict(set="set_value", safe=3)),
            (Parameter, (Choice([0, 1]),), dict(set="set_value", safe=False)),
        ]
        for cls, args, kwargs in bad_values:
            with self.subTest(args=args, kwargs=kwargs), self.assertDeclarationError("not a valid"):
                cls(*args, **kwargs)
        with self.assertDeclarationError("does not apply to str"):
            Parameter(str, set="set_value", safe="")

    def test_unit_only_on_numeric_parameters(self):
        self.assertEqual(Parameter(float, get="get_value", unit="V").unit, "V")
        Parameter(Choice([0.01, 0.03]), get="get_value", unit="s")
        with self.assertDeclarationError("unit applies only"):
            Parameter(bool, get="get_value", unit="V")
        with self.assertDeclarationError("unit must be"):
            Parameter(float, get="get_value", unit="")

    def test_timeout_flags_and_panel_fields(self):
        Parameter(float, get="get_value", timeout=2.0, group="Reference", order=1, hidden=True, doc="Hz")
        with self.assertDeclarationError("timeout"):
            Parameter(float, get="get_value", timeout=0)
        for field in ("scan", "snapshot", "hidden"):
            with self.subTest(field=field), self.assertDeclarationError(field):
                Parameter(float, get="get_value", **{field: 1})
        with self.assertDeclarationError("order"):
            Parameter(float, get="get_value", order=True)
        with self.assertDeclarationError("group"):
            Parameter(float, get="get_value", group=3)
        with self.assertDeclarationError("doc"):
            Parameter(float, get="get_value", doc=None)

    def test_parameter_is_frozen(self):
        parameter = read_write()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            parameter.limits = (-100, 100)


class ValueTypeRuleTests(ErrorAssertions):
    def test_choice_options_from_mapping_or_sequence(self):
        mapping = Choice({"internal": 0, "external": 1}, settle_s=0.2)
        self.assertEqual(mapping.labels, ("internal", "external"))
        self.assertEqual(mapping.values, (0, 1))
        self.assertTrue(mapping.is_numeric)
        sequence = Choice(["SINE", "TTL"])
        self.assertEqual(sequence.options, (("SINE", "SINE"), ("TTL", "TTL")))
        self.assertFalse(sequence.is_numeric)

    def test_choice_options_are_non_empty_unique_and_of_one_kind(self):
        cases = [
            ([], "must not be empty"),
            ({}, "must not be empty"),
            ([1, 1], "values must be unique"),
            ({"a": 1, "b": 1}, "values must be unique"),
            ([1, 1.0], "values must be unique"),
            ({"a": 1, "b": "x"}, "all numbers or all strings"),
            ([True, False], "finite numbers or strings"),
            ([math.nan], "finite numbers or strings"),
            ({"": 1}, "labels must be non-empty"),
            ({1: 1}, "labels must be non-empty"),
            ("ab", "sequence or mapping"),
            (5, "sequence or mapping"),
        ]
        for options, message in cases:
            with self.subTest(options=options), self.assertDeclarationError(message):
                Choice(options)
        with self.assertDeclarationError("settle_s"):
            Choice([1, 2], settle_s=-1)

    def test_ramp_rate_and_interval(self):
        self.assertEqual(Ramp(0.5).interval, 0.05)
        Ramp("amplitude_ramp_rate", interval=0.1)
        for rate in (0, -1, math.inf, "not a name"):
            with self.subTest(rate=rate), self.assertDeclarationError("rate"):
                Ramp(rate)
        with self.assertDeclarationError("interval"):
            Ramp(0.5, interval=0)

    def test_stable_fields(self):
        Stable(0.01, 0, 10)
        with self.assertDeclarationError("tolerance"):
            Stable(0, 10, 60)
        with self.assertDeclarationError("duration_s"):
            Stable(0.01, -1, 60)
        with self.assertDeclarationError("longer than duration_s"):
            Stable(0.01, 60, 60)

    def test_trigger_fields(self):
        trigger = Trigger("fire")
        self.assertTrue(trigger.scan)
        self.assertFalse(trigger.long)
        with self.assertDeclarationError("call is required"):
            Trigger(None)
        with self.assertDeclarationError("call must"):
            Trigger(3)
        with self.assertDeclarationError("long"):
            Trigger("fire", long="yes")

    def test_array_axes_unique_and_at_most_two(self):
        self.assertEqual(ArrayParameter("pixel", (1024,), get="read_frame").axes, ("pixel",))
        ArrayParameter(("y", "x"), "frame_shape", "frame_axes", "counts", get="read_frame", timeout=30.0)
        cases = [
            ((), (), "1 to 2 axes"),
            (("a", "b", "c"), (1, 1, 1), "1 to 2 axes"),
            (("x", "x"), (1, 1), "axes must be unique"),
            (("x y",), (1,), "axes must be an identifier"),
            (("x",), (1, 2), "one positive int per axis"),
            (("x",), (0,), "one positive int per axis"),
            (("x",), (1.5,), "one positive int per axis"),
            (("x",), 5, "shape must be a tuple or a reference"),
        ]
        for axes, shape, message in cases:
            with self.subTest(axes=axes, shape=shape), self.assertDeclarationError(message):
                ArrayParameter(axes, shape, get="read_frame")
        with self.assertRaises(TypeError):
            ArrayParameter(("x",), (1,))  # get is required
        with self.assertDeclarationError("timeout"):
            ArrayParameter(("x",), (1,), get="read_frame", timeout=-1)

    def test_multi_parameter_components_and_units(self):
        multi = MultiParameter(("X", "Y", "Theta"), get="read_pair", unit={"X": "V", "Theta": "deg"})
        self.assertEqual(multi.unit_of("X"), "V")
        self.assertIsNone(multi.unit_of("Y"))
        self.assertEqual(MultiParameter(("X", "Y"), get="read_pair", unit="V").unit_of("Y"), "V")
        with self.assertDeclarationError("must not be empty"):
            MultiParameter((), get="read_pair")
        with self.assertDeclarationError("components must be unique"):
            MultiParameter(("X", "X"), get="read_pair")
        with self.assertDeclarationError("unknown components"):
            MultiParameter(("X", "Y"), get="read_pair", unit={"R": "V"})

    def test_connection_fields(self):
        self.assertEqual(Connection(), Connection(str, 10.0))
        Connection(address=int, timeout_s=3)
        with self.assertDeclarationError("address must be"):
            Connection(address=float)
        with self.assertDeclarationError("timeout_s"):
            Connection(timeout_s=0)

    def test_action_marker(self):
        @action("Home", long=True)
        def home(self):
            pass

        self.assertEqual(home.__zmeter_action__, Action("Home", True))
        with self.assertDeclarationError("label"):
            action("")
        with self.assertDeclarationError("long"):
            action("Home", long=1)
        with self.assertDeclarationError("plain methods"):
            action("Home")(staticmethod(lambda: None))


class ClassValidationTests(ErrorAssertions):
    def test_names_are_unique_across_parameters_components_and_actions(self):
        declare(value=read_write(), pair=MultiParameter(("a", "b"), get="read_pair"))
        with self.assertDeclarationError("component 'value' is already used by 'value'"):
            declare(value=read_write(), pair=MultiParameter(("value", "b"), get="read_pair"))
        with self.assertDeclarationError("already used by 'first'"):
            declare(
                first=MultiParameter(("a", "b"), get="read_pair"),
                second=MultiParameter(("b", "c"), get="read_pair"),
            )
        with self.assertDeclarationError("already used by 'second'"):
            declare(
                first=MultiParameter(("second", "b"), get="read_pair"),
                second=MultiParameter(("c", "d"), get="read_pair"),
            )

        @action("Go")
        def go(self):
            pass

        with self.assertDeclarationError("component 'go' is already used by 'go'"):
            declare(go=go, pair=MultiParameter(("go", "b"), get="read_pair"))

    def test_reserved_and_private_names(self):
        for name in ("connect", "disconnect", "driver", "spec", "stop_hardware",
                     "write_many", "reset", "self_test", "set_display", "_value"):
            with self.subTest(name=name), self.assertDeclarationError("reserved"):
                type("Example", (Device,), {"driver_class": FakeDriver, name: read_write()})
        with self.assertDeclarationError("component name 'driver' is reserved"):
            declare(pair=MultiParameter(("driver", "b"), get="read_pair"))

        @action("Reset")
        def reset(self):
            pass

        with self.assertDeclarationError("standard action; define it without @action"):
            declare(reset=reset)

    def test_driver_method_names_exist_and_accept_the_call(self):
        spec = declare(
            value=read_write(),
            static=Parameter(float, get="static_read"),
            computed=Parameter(float, get=lambda device: device.driver.get_value()),
            written=read_write(get=None, set=lambda device, value: None),
        ).spec()
        self.assertEqual(tuple(spec.parameters), ("value", "static", "computed", "written"))
        cases = [
            (read_write(get="missing"), "'missing' is not a method of FakeDriver"),
            (read_write(set="not_a_method"), "FakeDriver.not_a_method is not a method"),
            (read_write(set="get_value"), "get_value cannot be called with 1 argument"),
            (Parameter(float, get="needs_argument"), "needs_argument cannot be called with 0"),
            (Parameter(float, get=lambda: 1.0), "accept the device and 0 more"),
            (read_write(set=lambda device: None), "accept the device and 1 more"),
        ]
        for declaration, message in cases:
            with self.subTest(message=message), self.assertDeclarationError(message):
                declare(value=declaration)

    def test_every_declaration_kind_checks_its_references(self):
        cases = [
            (Trigger("missing"), "call='missing'"),
            (ArrayParameter(("x",), (4,), get="missing"), "get='missing'"),
            (ArrayParameter(("x",), "missing", get="read_frame"), "shape='missing'"),
            (ArrayParameter(("x",), (4,), "missing", get="read_frame"), "axis_values='missing'"),
            (MultiParameter(("a", "b"), get="missing"), "get='missing'"),
        ]
        for declaration, message in cases:
            with self.subTest(message=message), self.assertDeclarationError(message):
                declare(item=declaration)

    def test_method_names_need_a_driver_class(self):
        class Driverless(Device):
            computed = Parameter(float, get=lambda device: 1.0)

            def connect(self, address, timeout_s):
                pass

            def disconnect(self):
                pass

        self.assertIsNone(Driverless.spec().driver_class)
        with self.assertDeclarationError("driver_class is not set"):
            declare(driver=None, driver_class=None, value=Parameter(float, get="get_value"),
                    connect=Driverless.connect, disconnect=Driverless.disconnect)

    def test_ramp_rate_can_name_another_readable_numeric_parameter(self):
        stop = {"stop_hardware": lambda self: None}
        declare(rate=Parameter(float, get="get_rate"), value=read_write(ramp=Ramp("rate")), **stop)
        cases = [
            dict(value=read_write(ramp=Ramp("missing"))),
            dict(value=read_write(ramp=Ramp("value"))),
            dict(rate=read_write(get=None), value=read_write(ramp=Ramp("rate"))),
            dict(rate=Parameter(Choice([1, 2]), get="get_rate"), value=read_write(ramp=Ramp("rate"))),
            dict(rate=Parameter(bool, get="get_rate"), value=read_write(ramp=Ramp("rate"))),
            dict(pair=MultiParameter(("rate", "b"), get="read_pair"), value=read_write(ramp=Ramp("rate"))),
        ]
        for attributes in cases:
            with self.subTest(attributes=sorted(attributes)), self.assertDeclarationError("ramp rate"):
                declare(**attributes, **stop)

    def test_ramps_and_long_operations_need_stop_hardware(self):
        @action("Home", long=True)
        def home(self):
            pass

        @action("Zero")
        def zero(self):
            pass

        for attributes in (
            dict(value=read_write(ramp=Ramp(0.1))),
            dict(focus=Trigger("fire", long=True)),
            dict(home=home),
        ):
            with self.subTest(attributes=sorted(attributes)):
                with self.assertDeclarationError("must implement stop_hardware"):
                    declare(**attributes)
                spec = declare(stop_hardware=lambda self: None, **attributes).spec()
                self.assertTrue(spec.has_stop_hardware)
        spec = declare(focus=Trigger("fire"), zero=zero).spec()
        self.assertFalse(spec.has_stop_hardware)

    def test_actions_take_no_arguments(self):
        def with_argument(self, speed):
            pass

        def with_varargs(self, *args):
            pass

        def with_keyword(self, *, speed=1):
            pass

        for func in (with_argument, with_varargs, with_keyword):
            with self.subTest(func=func.__name__), self.assertDeclarationError("takes no arguments"):
                declare(home=action("Home")(func))
        with self.assertDeclarationError("plain methods"):
            declare(home=action("Home")(FakeDriver()))

    def test_standard_actions_keep_their_signatures(self):
        spec = declare(
            reset=lambda self: None,
            self_test=lambda self: None,
            set_display=lambda self, on: None,
        ).spec()
        self.assertEqual(spec.standard_actions, ("reset", "self_test", "set_display"))
        self.assertEqual(declare().spec().standard_actions, ())
        for name, func in (
            ("reset", lambda self, hard: None),
            ("self_test", lambda self, level: None),
            ("set_display", lambda self: None),
        ):
            with self.subTest(name=name), self.assertDeclarationError(f"standard action {name}"):
                declare(**{name: func})

    def test_lifecycle_hooks_keep_their_signatures(self):
        self.assertTrue(declare(write_many=lambda self, values: None).spec().has_write_many)
        self.assertFalse(declare().spec().has_write_many)
        for name, func in (
            ("connect", lambda self, address: None),
            ("disconnect", lambda self, now: None),
            ("stop_hardware", lambda self, axis: None),
            ("write_many", lambda self: None),
        ):
            with self.subTest(name=name), self.assertDeclarationError(f"{name}\\(\\) must take"):
                declare(**{name: func})

    def test_default_connect_and_disconnect_need_a_matching_driver(self):
        class NoConnect:
            def disconnect(self):
                pass

        class NoDisconnect:
            def connect(self, address, timeout_s):
                pass

        class NeedsAddress(FakeDriver):
            def __init__(self, address):
                super().__init__()

        with self.assertDeclarationError("set driver_class or override connect"):
            declare(driver=None, driver_class=None)
        with self.assertDeclarationError("default connect"):
            declare(driver=NoConnect)
        with self.assertDeclarationError("default disconnect"):
            declare(driver=NoDisconnect)
        with self.assertDeclarationError("builds NeedsAddress\\(\\) without arguments"):
            declare(driver=NeedsAddress)
        declare(driver=NeedsAddress, connect=lambda self, address, timeout_s: None)

    def test_class_attributes_driver_class_and_connection(self):
        with self.assertDeclarationError("driver_class must be a class"):
            declare(driver=FakeDriver())
        with self.assertDeclarationError("connection must be a Connection"):
            declare(connection=("COM3", 10))
        spec = declare(connection=Connection(int, 3.0)).spec()
        self.assertEqual(spec.connection, Connection(int, 3.0))
        self.assertEqual(declare().spec().connection, Connection())


class SpecTests(ErrorAssertions):
    def make_base(self):
        class Base(Device):
            driver_class = FakeDriver
            value = read_write(scan=True, snapshot=True)
            rate = Parameter(float, get="get_rate", scan=True)
            pair = MultiParameter(("a", "b"), get="read_pair")
            frame = ArrayParameter(("y", "x"), "frame_shape", get="read_frame")
            fire = Trigger("fire")
            quiet = Trigger("fire", scan=False)
            path = Parameter(Path, get=lambda device: Path("."), set=lambda device, value: None)

        return Base

    def test_spec_lists_channels_by_role(self):
        spec = self.make_base().spec()
        self.assertIsInstance(spec, DeviceSpec)
        self.assertEqual(spec.name, "Base")
        self.assertEqual(spec.readouts, ("value", "rate", "a", "b"))
        self.assertEqual(spec.controls, ("value", "fire"))
        self.assertEqual(spec.snapshot, ("value",))
        self.assertEqual(tuple(spec.arrays), ("frame",))
        self.assertEqual(tuple(spec.triggers), ("fire", "quiet"))
        self.assertEqual(
            spec.names, ("value", "rate", "path", "fire", "quiet", "frame", "pair", "a", "b")
        )

    def test_spec_is_built_once_and_immutable(self):
        Base = self.make_base()
        spec = Base.spec()
        self.assertIs(Base.spec(), spec)
        # Attributes added after the class was created do not change its spec.
        Base.zero = action("Zero")(lambda self: None)
        Base.extra = read_write()
        self.assertNotIn("zero", Base.spec().actions)
        self.assertNotIn("extra", Base.spec().parameters)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            spec.readouts = ()
        with self.assertRaises(TypeError):
            spec.parameters["new"] = read_write()
        with self.assertRaises(TypeError):
            del spec.multis["pair"]

    def test_device_itself_has_no_spec(self):
        with self.assertRaises(TypeError):
            Device.spec()

    def test_subclass_inherits_overrides_and_hides_declarations(self):
        Base = self.make_base()
        base_spec = Base.spec()

        @action("Calibrate")
        def calibrate_action(self):
            pass

        class Child(Base):
            rate = Parameter(float, get="get_rate", poll=1.0)  # override keeps position
            quiet = None  # hides the inherited trigger
            extra = Parameter(int, get="get_value", scan=True)

        Child.calibrate = calibrate_action  # after creation: not in Child's spec
        self.assertEqual(tuple(Child.spec().actions), ())

        class GrandChild(Child):
            calibrate = calibrate_action

        child = Child.spec()
        self.assertEqual(tuple(child.parameters), ("value", "rate", "path", "extra"))
        self.assertEqual(child.parameters["rate"].poll, 1.0)
        self.assertNotIn("rate", child.readouts)
        self.assertEqual(tuple(child.triggers), ("fire",))
        self.assertEqual(child.readouts, ("value", "a", "b", "extra"))
        self.assertEqual(tuple(GrandChild.spec().actions), ("calibrate",))
        # The base spec is unchanged by the subclasses.
        self.assertIs(Base.spec(), base_spec)
        self.assertEqual(tuple(base_spec.triggers), ("fire", "quiet"))

    def test_subclass_override_without_decorator_removes_the_action(self):
        @action("Home")
        def home(self):
            pass

        Base = declare(home=home)
        self.assertEqual(tuple(Base.spec().actions), ("home",))

        class Child(Base):
            def home(self):
                pass

        self.assertEqual(tuple(Child.spec().actions), ())

    def test_subclass_is_validated_too(self):
        Base = self.make_base()
        with self.assertDeclarationError("already used by 'value'"):
            type("Child", (Base,), {"other": MultiParameter(("value", "c"), get="read_pair")})


class DeviceInstanceTests(unittest.TestCase):
    def test_default_connect_builds_the_driver_and_disconnect_drops_it(self):
        Example = declare(value=read_write())
        device = Example()
        self.assertIsNone(device.driver)
        device.connect("GPIB0::8::INSTR", 5.0)
        driver = device.driver
        self.assertIsInstance(driver, FakeDriver)
        self.assertEqual(driver.calls, [("connect", "GPIB0::8::INSTR", 5.0)])
        device.disconnect()
        self.assertEqual(driver.calls[-1], ("disconnect",))
        self.assertIsNone(device.driver)
        device.disconnect()  # nothing connected: no error

    def test_injected_driver_is_used_and_kept(self):
        fake = FakeDriver()
        device = declare(value=read_write())(driver=fake)
        device.connect("COM3", 1.0)
        device.disconnect()
        self.assertIs(device.driver, fake)
        self.assertEqual(fake.calls, [("connect", "COM3", 1.0), ("disconnect",)])

    def test_default_stop_hardware_is_not_implemented(self):
        device = declare()(driver=FakeDriver())
        with self.assertRaises(NotImplementedError):
            device.stop_hardware()

    def test_declarations_are_shared_class_values(self):
        Example = declare(value=read_write())
        self.assertIs(Example().value, Example.spec().parameters["value"])


if __name__ == "__main__":
    unittest.main()
