"""zcore.runner: the device Runner core (phase 1, PR 4). Qt-free, fake drivers.

Threading tests use events and barriers with bounded waits, never long sleeps.
The fake driver records every call and fails the test if two driver calls ever
overlap. No device package is imported and no hardware is touched.
"""

import math
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from zcore import runner as runner_module
from zcore.devices import (
    ArrayParameter,
    Choice,
    Device,
    MultiParameter,
    Parameter,
    Ramp,
    Trigger,
    action,
    unlimited,
)
from zcore.events import ERROR, WARNING, EventBus, LogEntry, StateChanged, ValueChanged
from zcore.results import Status
from zcore.runner import (
    DeviceState,
    Operation,
    Priority,
    ResultFuture,
    Runner,
    Source,
    check_write,
)

WAIT_S = 5.0  # upper bound for anything that should happen promptly


class FakeDriver:
    """Records calls; ``gate`` blocks until released, when armed."""

    def __init__(self):
        self.calls = []
        self.values = {"bias": 0.0, "gain": 1, "mode": 1, "enabled": False, "gate": 1.0}
        self.xy = (0.1, 0.2)
        self.gate_armed = False
        self.gate_entered = threading.Event()
        self.gate_release = threading.Event()
        self.connect_armed = False
        self.connect_entered = threading.Event()
        self.connect_release = threading.Event()
        self.fail = {}  # method name -> exception to raise
        self._active = 0
        self._active_lock = threading.Lock()
        self.overlaps = 0

    def _enter(self, name, *args):
        with self._active_lock:
            self._active += 1
            if self._active > 1:
                self.overlaps += 1
        self.calls.append((name, *args))
        if name in self.fail:
            self._leave()
            raise self.fail[name]

    def _leave(self):
        with self._active_lock:
            self._active -= 1

    def _simple(self, name, *args, result=None):
        self._enter(name, *args)
        try:
            return result
        finally:
            self._leave()

    def connect(self, address, timeout_s):
        self._enter("connect", address, timeout_s)
        try:
            if self.connect_armed:
                self.connect_entered.set()
                self.connect_release.wait(WAIT_S)
        finally:
            self._leave()

    def disconnect(self):
        self._simple("disconnect")

    def get_bias(self):
        return self._simple("get_bias", result=self.values["bias"])

    def set_bias(self, value):
        self._simple("set_bias", value)
        self.values["bias"] = value

    def get_gain(self):
        return self._simple("get_gain", result=self.values["gain"])

    def set_gain(self, value):
        self._simple("set_gain", value)
        self.values["gain"] = value

    def get_mode(self):
        return self._simple("get_mode", result=self.values["mode"])

    def set_mode(self, value):
        self._simple("set_mode", value)
        self.values["mode"] = value

    def get_enabled(self):
        return self._simple("get_enabled", result=self.values["enabled"])

    def set_enabled(self, value):
        self._simple("set_enabled", value)

    def set_label(self, value):
        self._simple("set_label", value)

    def set_folder(self, value):
        self._simple("set_folder", value)

    def set_free(self, value):
        self._simple("set_free", value)

    def get_ramped(self):
        return self._simple("get_ramped", result=0.0)

    def set_ramped(self, value):
        self._simple("set_ramped", value)

    def wait_gate(self):
        self._enter("gate")
        try:
            if self.gate_armed:
                self.gate_entered.set()
                self.gate_release.wait(WAIT_S)
            return self.values["gate"]
        finally:
            self._leave()

    def do_ping(self):
        self._simple("ping")

    def read_xy(self):
        return self._simple("read_xy", result=self.xy)

    def read_spectrum(self):
        return self._simple("read_spectrum", result=[1.0, 2.0, 3.0, 4.0])


class FakeDevice(Device):
    driver_class = FakeDriver

    bias = Parameter(float, unit="V", limits=(-10.0, 10.0), get="get_bias", set="set_bias", scan=True)
    gain = Parameter(int, limits=(1, 100), get="get_gain", set="set_gain")
    mode = Parameter(Choice({"A": 1, "B": 2}), get="get_mode", set="set_mode")
    enabled = Parameter(bool, get="get_enabled", set="set_enabled")
    label = Parameter(str, set="set_label")
    folder = Parameter(Path, set="set_folder")
    free = Parameter(float, limits=unlimited("wiring-dependent"), set="set_free")
    ramped = Parameter(float, limits=(0.0, 1.0), get="get_ramped", set="set_ramped", ramp=Ramp(0.1))
    gate = Parameter(float, get="wait_gate")
    ping = Trigger("do_ping")
    outputs = MultiParameter(("X", "Y"), get="read_xy", unit="V")
    spectrum = ArrayParameter(("wavelength",), (4,), get="read_spectrum")

    @action("Home")
    def home(self):
        self.driver._simple("home")
        return "homed"

    @action("Probe")
    def probe(self):
        # Reads through the Runner from the Runner's own thread (inline).
        return self.runner.get("bias", source="test").value

    def reset(self):
        self.driver._simple("reset")

    def set_display(self, on):
        self.driver._simple("set_display", on)

    def stop_hardware(self):
        pass


class Recorder:
    """EventBus subscriber that can wait for an event."""

    def __init__(self, bus):
        self.events = []
        self._cond = threading.Condition()
        bus.subscribe(self)

    def __call__(self, event):
        with self._cond:
            self.events.append(event)
            self._cond.notify_all()

    def of(self, kind):
        with self._cond:
            return [e for e in self.events if isinstance(e, kind)]

    def wait_for(self, predicate, timeout=WAIT_S):
        with self._cond:
            ok = self._cond.wait_for(lambda: any(predicate(e) for e in self.events), timeout)
        if not ok:
            raise AssertionError("expected event did not arrive")

    def clear(self):
        with self._cond:
            self.events.clear()


class RunnerTestCase(unittest.TestCase):
    device_class = FakeDevice

    def setUp(self):
        self.driver = FakeDriver()
        self.device = self.device_class(driver=self.driver)
        self.bus = EventBus()
        self.recorder = Recorder(self.bus)
        self.runner = Runner(self.device, name="fake_0", bus=self.bus)
        self.device.runner = self.runner
        self.addCleanup(self._shutdown)

    def _shutdown(self):
        self.driver.gate_release.set()
        self.driver.connect_release.set()
        self.assertTrue(self.runner.shutdown(timeout_s=WAIT_S))
        self.assertEqual(self.driver.overlaps, 0, "two driver calls overlapped")

    def connect(self):
        result = self.runner.connect("ADDR::1", source=Source.TEST)
        self.assertTrue(result.is_ok, result)
        self.driver.calls.clear()
        self.recorder.clear()

    def block_worker(self):
        """Arm the gate and occupy the worker with a gate read."""
        self.driver.gate_armed = True
        future = self.runner.submit(Operation.get("gate", source=Source.PANEL, timeout=WAIT_S))
        self.assertTrue(self.driver.gate_entered.wait(WAIT_S))
        self.driver.calls.clear()
        return future

    def driver_calls(self, name):
        return [call for call in self.driver.calls if call[0] == name]


class OrderingTests(RunnerTestCase):
    def test_priority_order_with_a_blocked_worker(self):
        self.connect()
        gate = self.block_worker()
        submit = self.runner.submit
        futures = [
            submit(Operation.get("bias", source=Source.POLL)),
            submit(Operation.set("bias", 5.0, source=Source.PANEL)),
            submit(Operation.set("bias", 2.0, source=Source.SCAN)),
            submit(Operation.set("bias", 6.0, source=Source.PANEL)),
            submit(Operation.set("bias", 3.0, source=Source.SCAN)),
            submit(Operation.set("bias", 4.0, source=Source.TEST), Priority.STOP),
        ]
        self.driver.gate_release.set()
        self.assertTrue(gate.result(WAIT_S).is_ok)
        for future in futures:
            self.assertTrue(future.result(WAIT_S).is_ok)
        self.assertEqual(
            self.driver.calls,
            [
                ("set_bias", 4.0),
                ("set_bias", 2.0),
                ("set_bias", 3.0),
                ("set_bias", 5.0),
                ("set_bias", 6.0),
                ("get_bias",),
            ],
        )

    def test_fifo_within_a_priority(self):
        self.connect()
        gate = self.block_worker()
        values = [float(i) / 10 for i in range(30)]
        futures = [
            self.runner.submit(Operation.set("bias", v, source=Source.PANEL)) for v in values
        ]
        self.driver.gate_release.set()
        gate.result(WAIT_S)
        for future in futures:
            future.result(WAIT_S)
        self.assertEqual(self.driver.calls, [("set_bias", v) for v in values])

    def test_busy_while_working(self):
        self.connect()
        self.assertFalse(self.runner.is_busy)
        gate = self.block_worker()
        self.assertTrue(self.runner.is_busy)
        self.assertIs(self.runner.state, DeviceState.BUSY)
        self.driver.gate_release.set()
        gate.result(WAIT_S)
        self.recorder.wait_for(lambda e: isinstance(e, StateChanged) and e.state == "idle")
        self.assertIs(self.runner.state, DeviceState.IDLE)
        self.assertFalse(self.runner.is_busy)

    def test_many_submitting_threads(self):
        self.connect()
        threads_n, per_thread = 8, 60
        start = threading.Barrier(threads_n)
        results = [[] for _ in range(threads_n)]

        def work(index):
            start.wait()
            for i in range(per_thread):
                if i % 3 == 0:
                    results[index].append(("get", self.runner.get("bias", source=Source.SCAN)))
                elif i % 3 == 1:
                    value = (index + i) % 10
                    results[index].append(("set", self.runner.set("bias", value, source=Source.PANEL)))
                else:
                    results[index].append(("bad", self.runner.set("bias", 50 + i, source=Source.SCAN)))

        threads = [threading.Thread(target=work, args=(i,)) for i in range(threads_n)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)
            self.assertFalse(thread.is_alive())
        flat = [item for chunk in results for item in chunk]
        self.assertEqual(len(flat), threads_n * per_thread)
        for kind, result in flat:
            if kind == "bad":
                self.assertIs(result.status, Status.FAILED)
                self.assertTrue(result.reason.startswith("outside device limit"))
            else:
                self.assertTrue(result.is_ok, result)
        good = sum(1 for kind, _ in flat if kind != "bad")
        self.assertEqual(len(self.recorder.of(ValueChanged)), good)
        self.assertEqual(len(self.driver_calls("set_bias")), sum(1 for k, _ in flat if k == "set"))


class TimeoutTests(RunnerTestCase):
    def test_timeout_marks_state_unknown_until_next_successful_read(self):
        self.connect()
        self.driver.gate_armed = True
        result = self.runner.get("gate", source=Source.SCAN, timeout=0.1)
        self.assertIs(result.status, Status.TIMEOUT)
        self.assertIn("no retry", result.reason)
        self.assertIs(self.runner.state, DeviceState.UNKNOWN)
        self.recorder.wait_for(lambda e: isinstance(e, StateChanged) and e.state == "unknown")

        # The stuck call finishes later: its result is logged and discarded,
        # and does not clear "state unknown".
        self.driver.gate_release.set()
        self.recorder.wait_for(lambda e: isinstance(e, LogEntry) and "Late result" in e.message)
        self.assertFalse([e for e in self.recorder.of(ValueChanged) if e.name == "gate"])
        self.assertIs(self.runner.state, DeviceState.UNKNOWN)

        # No retry happened.
        self.assertEqual(len(self.driver_calls("gate")), 1)

        # A write does not clear it; a successful read does.
        self.assertTrue(self.runner.set("bias", 1.0, source=Source.PANEL).is_ok)
        self.assertIs(self.runner.state, DeviceState.UNKNOWN)
        self.assertTrue(self.runner.get("bias", source=Source.PANEL).is_ok)
        self.assertIs(self.runner.state, DeviceState.IDLE)

    def test_queued_operation_past_its_deadline_never_runs(self):
        self.connect()
        gate = self.block_worker()
        result = self.runner.set("bias", 1.0, source=Source.SCAN, timeout=0.1)
        self.assertIs(result.status, Status.TIMEOUT)
        self.assertIn("did not start", result.reason)
        # Waiting in the queue is not a device fault.
        self.assertIs(self.runner.state, DeviceState.BUSY)
        self.driver.gate_release.set()
        self.assertTrue(gate.result(WAIT_S).is_ok)
        self.assertTrue(self.runner.get("bias", source=Source.TEST).is_ok)
        self.assertEqual(self.driver_calls("set_bias"), [])
        self.assertEqual(self.driver.values["bias"], 0.0)

    def test_declared_parameter_timeout_is_used(self):
        class Slow(FakeDevice):
            gate = Parameter(float, get="wait_gate", timeout=0.1)

        self.runner.shutdown()
        self.device = Slow(driver=self.driver)
        self.runner = Runner(self.device, bus=self.bus)
        self.connect()
        self.driver.gate_armed = True
        started = time.monotonic()
        result = self.runner.get("gate", source=Source.SCAN)
        self.assertIs(result.status, Status.TIMEOUT)
        self.assertLess(time.monotonic() - started, WAIT_S / 2)


class DriverErrorTests(RunnerTestCase):
    def test_driver_exception_becomes_failed_with_context(self):
        self.connect()
        self.driver.fail["get_bias"] = RuntimeError("bus error")
        result = self.runner.get("bias", source=Source.SCAN)
        self.assertIs(result.status, Status.FAILED)
        self.assertEqual(result.reason, "get bias failed: RuntimeError: bus error")
        self.assertIs(self.runner.state, DeviceState.UNKNOWN)
        errors = [e for e in self.recorder.of(LogEntry) if e.level == ERROR]
        self.assertEqual([e.message for e in errors], [result.reason])
        del self.driver.fail["get_bias"]
        self.assertTrue(self.runner.get("bias", source=Source.SCAN).is_ok)
        self.assertIs(self.runner.state, DeviceState.IDLE)

    def test_failed_write_marks_state_unknown(self):
        self.connect()
        self.driver.fail["set_bias"] = OSError("no reply")
        result = self.runner.set("bias", 1.0, source=Source.SCAN)
        self.assertEqual(result.reason, "set bias=1.0 failed: OSError: no reply")
        self.assertIs(self.runner.state, DeviceState.UNKNOWN)

    def test_non_numeric_read_fails(self):
        self.connect()
        self.driver.values["bias"] = None
        result = self.runner.get("bias", source=Source.SCAN)
        self.assertIs(result.status, Status.FAILED)
        self.assertIn("not a number", result.reason)
        self.assertEqual(self.recorder.of(ValueChanged), [])

    def test_failing_subscriber_does_not_affect_the_runner(self):
        self.connect()

        def broken(event):
            raise RuntimeError("panel is gone")

        self.bus.subscribe(broken)
        with self.assertLogs("zcore.events", "ERROR"):
            self.assertTrue(self.runner.get("bias", source=Source.SCAN).is_ok)
            self.recorder.wait_for(lambda e: isinstance(e, StateChanged) and e.state == "idle")
        self.bus.unsubscribe(broken)
        self.assertEqual(len(self.recorder.of(ValueChanged)), 1)


class LimitTests(RunnerTestCase):
    def test_rejections_never_call_the_driver(self):
        self.connect()
        cases = [
            ("bias", 10.5, "outside device limit"),
            ("bias", -11, "outside device limit"),
            ("bias", math.nan, "outside device limit"),
            ("bias", math.inf, "outside device limit"),
            ("bias", -math.inf, "outside device limit"),
            ("bias", "1.0", "invalid value"),
            ("bias", True, "invalid value"),
            ("bias", None, "invalid value"),
            ("gain", 0, "outside device limit"),
            ("gain", 2.5, "invalid value"),
            ("mode", 3, "outside device limit"),
            ("mode", "A", "invalid value"),
            ("enabled", 1, "invalid value"),
            ("label", 5, "invalid value"),
            ("folder", 5, "invalid value"),
            ("free", math.nan, "outside device limit"),
            ("ping", math.nan, "outside device limit"),
            ("ping", "go", "invalid value"),
        ]
        for source in (Source.SCAN, Source.PANEL):
            for name, value, prefix in cases:
                with self.subTest(name=name, value=value, source=source):
                    result = self.runner.set(name, value, source=source)
                    self.assertIs(result.status, Status.FAILED)
                    self.assertTrue(result.reason.startswith(prefix), result.reason)
        self.assertEqual(self.driver.calls, [])
        self.assertEqual(self.recorder.of(ValueChanged), [])
        warnings = [e for e in self.recorder.of(LogEntry) if e.level == WARNING]
        self.assertEqual(len(warnings), 2 * len(cases))
        self.assertIs(self.runner.state, DeviceState.IDLE)  # a rejection is not a device fault

    def test_accepted_values_are_converted_to_the_declared_type(self):
        self.connect()
        cases = [
            ("bias", 10, 10.0, float),
            ("bias", -10.0, -10.0, float),
            ("gain", 3.0, 3, int),
            ("mode", 2.0, 2, int),
            ("enabled", True, True, bool),
            ("label", "sample A", "sample A", str),
            ("folder", "C:/data", Path("C:/data"), Path),
            ("free", 1e9, 1e9, float),
        ]
        for name, value, expected, kind in cases:
            with self.subTest(name=name):
                result = self.runner.set(name, value, source=Source.PANEL)
                self.assertTrue(result.is_ok, result)
                self.assertEqual(result.value, expected)
                self.assertIs(type(result.value), kind if kind is not Path else type(Path("x")))
                self.assertEqual(self.driver.calls[-1], (f"set_{name}", expected))

    def test_ramped_parameter_is_never_written_directly(self):
        self.connect()
        result = self.runner.set("ramped", 0.5, source=Source.PANEL)
        self.assertIs(result.status, Status.FAILED)
        self.assertIn("does not ramp yet", result.reason)
        self.assertEqual(self.driver_calls("set_ramped"), [])

    def test_check_write_reasons(self):
        bias = FakeDevice.spec().parameters["bias"]
        self.assertEqual(check_write(bias, 1), (True, 1.0))
        ok, reason = check_write(bias, 12)
        self.assertFalse(ok)
        self.assertEqual(reason, "outside device limit: 12 is not within [-10.0, 10.0] V")
        self.assertEqual(check_write(bias, math.nan), (False, "outside device limit: nan is not finite"))


class EventTests(RunnerTestCase):
    def test_one_value_event_per_read_and_write(self):
        self.connect()
        self.runner.get("bias", source=Source.SCAN)
        self.runner.set("bias", 2.0, source=Source.PANEL)
        self.assertEqual(
            self.recorder.of(ValueChanged),
            [
                ValueChanged("fake_0", "bias", 0.0, "scan"),
                ValueChanged("fake_0", "bias", 2.0, "panel"),
            ],
        )

    def test_state_events_only_on_change(self):
        self.connect()
        self.runner.get("bias", source=Source.SCAN)
        self.recorder.wait_for(lambda e: isinstance(e, StateChanged) and e.state == "idle")
        states = [e.state for e in self.recorder.of(StateChanged)]
        self.assertEqual(states, ["busy", "idle"])


class InlineTests(RunnerTestCase):
    def test_call_from_the_runner_thread_runs_inline(self):
        self.connect()
        self.driver.values["bias"] = 3.5
        future = self.runner.submit(Operation.call("probe", source=Source.PANEL))
        result = future.result(WAIT_S)  # would deadlock without the inline rule
        self.assertTrue(result.is_ok, result)
        self.assertEqual(result.value, 3.5)

    def test_inline_call_still_checks_limits(self):
        class Probing(FakeDevice):
            @action("Bad write")
            def bad_write(self):
                return self.runner.set("bias", 99.0, source="test")

        self.runner.shutdown()
        self.device = Probing(driver=self.driver)
        self.runner = Runner(self.device, bus=self.bus)
        self.device.runner = self.runner
        self.connect()
        result = self.runner.call("bad_write", source=Source.PANEL)
        self.assertTrue(result.is_ok)
        self.assertTrue(result.value.reason.startswith("outside device limit"))
        self.assertEqual(self.driver_calls("set_bias"), [])


class LifecycleTests(RunnerTestCase):
    def test_connect_reads_every_readable_parameter_and_warns_about_unlimited(self):
        self.assertIs(self.runner.state, DeviceState.DISCONNECTED)
        result = self.runner.connect("ADDR::1", source=Source.PANEL)
        self.assertTrue(result.is_ok)
        self.assertTrue(self.runner.is_connected)
        self.assertEqual(self.driver.calls[0], ("connect", "ADDR::1", 10.0))
        reads = {e.name for e in self.recorder.of(ValueChanged) if e.source == "runner"}
        self.assertEqual(reads, {"bias", "gain", "mode", "enabled", "ramped", "gate", "X", "Y"})
        self.assertEqual(self.driver_calls("read_spectrum"), [])  # arrays are not read at connect
        warnings = [e.message for e in self.recorder.of(LogEntry) if e.level == WARNING]
        self.assertEqual(warnings, ["[Limits] free has no device limit: wiring-dependent"])
        self.recorder.wait_for(lambda e: isinstance(e, StateChanged) and e.state == "idle")
        states = [e.state for e in self.recorder.of(StateChanged)]
        self.assertEqual(states[0], "connecting")
        self.assertEqual(states[-1], "idle")

    def test_connect_twice_is_harmless(self):
        self.connect()
        self.assertTrue(self.runner.connect("ADDR::1", source=Source.PANEL).is_ok)
        self.assertEqual(self.driver_calls("connect"), [])

    def test_connect_failure_gives_error_and_can_be_retried(self):
        self.driver.fail["connect"] = OSError("VI_ERROR_RSRC_NFOUND")
        result = self.runner.connect("ADDR::9", source=Source.PANEL)
        self.assertIs(result.status, Status.FAILED)
        self.assertIn("VI_ERROR_RSRC_NFOUND", result.reason)
        self.assertIs(self.runner.state, DeviceState.ERROR)
        self.assertFalse(self.runner.is_connected)
        del self.driver.fail["connect"]
        self.assertTrue(self.runner.connect("ADDR::1", source=Source.PANEL).is_ok)
        self.assertIs(self.runner.state, DeviceState.IDLE)

    def test_connect_timeout_gives_error_and_undoes_a_late_connect(self):
        self.driver.connect_armed = True
        with mock.patch.object(runner_module, "CONNECT_GRACE_S", 0.0):
            result = self.runner.connect("ADDR::1", source=Source.PANEL, timeout=0.1)
        self.assertIs(result.status, Status.TIMEOUT)
        self.assertIs(self.runner.state, DeviceState.ERROR)
        self.driver.connect_release.set()
        self.recorder.wait_for(lambda e: isinstance(e, LogEntry) and "Late connect undone" in e.message)
        self.assertEqual(self.driver_calls("disconnect"), [("disconnect",)])
        self.assertIs(self.runner.state, DeviceState.ERROR)
        self.assertFalse(self.runner.is_connected)

    def test_operations_need_a_connection(self):
        for operation in (
            Operation.get("bias", source=Source.SCAN),
            Operation.set("bias", 1.0, source=Source.SCAN),
            Operation.set_many({"bias": 1.0}, source=Source.SCAN),
            Operation.call("home", source=Source.PANEL),
        ):
            with self.subTest(kind=operation.kind):
                result = self.runner.submit(operation).result(WAIT_S)
                self.assertEqual(result.reason, "device is not connected")
        self.assertEqual(self.driver.calls, [])

    def test_disconnect_drops_queued_work(self):
        self.connect()
        gate = self.block_worker()
        queued = self.runner.submit(Operation.set("bias", 1.0, source=Source.SCAN))
        disconnect = self.runner.submit(Operation.disconnect(source=Source.PANEL))
        self.assertIs(queued.result(WAIT_S).status, Status.CANCELLED)
        self.driver.gate_release.set()
        gate.result(WAIT_S)
        self.assertTrue(disconnect.result(WAIT_S).is_ok)
        self.assertIs(self.runner.state, DeviceState.DISCONNECTED)
        self.assertEqual(self.driver.calls, [("disconnect",)])

    def test_disconnect_failure_gives_error(self):
        self.connect()
        self.driver.fail["disconnect"] = OSError("port busy")
        result = self.runner.disconnect(source=Source.PANEL)
        self.assertIs(result.status, Status.FAILED)
        self.assertIs(self.runner.state, DeviceState.ERROR)

    def test_reset_reads_everything_again(self):
        self.connect()
        self.driver.values["bias"] = 0.0
        result = self.runner.call("reset", source=Source.PANEL)
        self.assertTrue(result.is_ok)
        self.assertEqual(self.driver.calls[0], ("reset",))
        reads = {e.name for e in self.recorder.of(ValueChanged) if e.source == "runner"}
        self.assertIn("bias", reads)

    def test_actions(self):
        self.connect()
        self.assertEqual(self.runner.call("home", source=Source.PANEL).value, "homed")
        self.assertTrue(self.runner.call("set_display", False, source=Source.PANEL).is_ok)
        self.assertEqual(self.driver.calls, [("home",), ("set_display", False)])
        for name, args, text in (
            ("nope", (), "not an action"),
            ("home", (1,), "takes 0 argument"),
            ("set_display", (), "takes 1 argument"),
            ("set_display", (1,), "True or False"),
        ):
            with self.subTest(name=name, args=args):
                result = self.runner.call(name, *args, source=Source.PANEL)
                self.assertIs(result.status, Status.FAILED)
                self.assertIn(text, result.reason)

    def test_trigger_runs_once_and_records_the_value(self):
        self.connect()
        result = self.runner.set("ping", 1.0, source=Source.SCAN)
        self.assertTrue(result.is_ok)
        self.assertEqual(self.driver.calls, [("ping",)])
        self.assertEqual(self.recorder.of(ValueChanged), [ValueChanged("fake_0", "ping", 1.0, "scan")])

    def test_unknown_names(self):
        self.connect()
        self.assertIn("not a readable name", self.runner.get("label", source=Source.PANEL).reason)
        self.assertIn("not a readable name", self.runner.get("home", source=Source.PANEL).reason)
        self.assertIn("not a settable name", self.runner.set("gate", 1.0, source=Source.PANEL).reason)
        self.assertEqual(self.driver.calls, [])

    def test_shutdown_disconnects_and_refuses_new_work(self):
        self.connect()
        self.assertTrue(self.runner.shutdown(timeout_s=WAIT_S))
        self.assertEqual(self.driver.calls, [("disconnect",)])
        self.assertIs(self.runner.state, DeviceState.DISCONNECTED)
        result = self.runner.get("bias", source=Source.PANEL)
        self.assertIn("shut down", result.reason)
        self.assertTrue(self.runner.shutdown(timeout_s=WAIT_S))  # again: harmless

    def test_shutdown_cancels_pending_and_is_bounded(self):
        self.connect()
        gate = self.block_worker()
        pending = [
            self.runner.submit(Operation.set("bias", 1.0, source=Source.SCAN)),
            self.runner.submit(Operation.get("bias", source=Source.POLL)),
        ]
        started = time.monotonic()
        self.assertFalse(self.runner.shutdown(timeout_s=0.2))  # worker is stuck in the gate
        self.assertLess(time.monotonic() - started, WAIT_S / 2)
        for future in pending:
            result = future.result(WAIT_S)
            self.assertIs(result.status, Status.CANCELLED)
            self.assertIn("shut down", result.reason)
        self.driver.gate_release.set()
        self.assertTrue(gate.result(WAIT_S).is_ok)
        self.assertTrue(self.runner.shutdown(timeout_s=WAIT_S))
        self.assertEqual(self.driver.calls, [("disconnect",)])

    def test_shutdown_from_the_runner_thread_is_refused(self):
        class SelfStopping(FakeDevice):
            @action("Stop runner")
            def stop_runner(self):
                self.runner.shutdown()

        self.runner.shutdown()
        self.device = SelfStopping(driver=self.driver)
        self.runner = Runner(self.device, bus=self.bus)
        self.device.runner = self.runner
        self.connect()
        result = self.runner.call("stop_runner", source=Source.PANEL)
        self.assertIs(result.status, Status.FAILED)
        self.assertIn("RuntimeError", result.reason)


class ScanAdmissionTests(RunnerTestCase):
    def test_scan_closes_panel_writes_and_actions(self):
        self.connect()
        self.assertTrue(self.runner.begin_scan())
        self.assertTrue(self.runner.in_scan)
        refused = [
            Operation.set("bias", 1.0, source=Source.PANEL),
            Operation.set_many({"bias": 1.0}, source=Source.PANEL),
            Operation.call("home", source=Source.PANEL),
            Operation.disconnect(source=Source.PANEL),
            Operation.call("reset", source=Source.SCAN),
            Operation.call("self_test", source=Source.TEST),
        ]
        for operation in refused:
            with self.subTest(operation=operation.describe(), source=operation.source):
                result = self.runner.submit(operation).result(WAIT_S)
                self.assertIs(result.status, Status.FAILED)
                self.assertTrue(result.reason.startswith("refused"), result.reason)
        self.assertTrue(self.runner.get("bias", source=Source.PANEL).is_ok)  # reads stay allowed
        self.assertTrue(self.runner.set("bias", 2.0, source=Source.SCAN).is_ok)
        self.assertEqual(self.driver.calls, [("get_bias",), ("set_bias", 2.0)])

        self.assertTrue(self.runner.begin_scan())  # idempotent
        self.runner.end_scan()
        self.runner.end_scan()
        self.assertFalse(self.runner.in_scan)
        self.assertTrue(self.runner.set("bias", 1.0, source=Source.PANEL).is_ok)

    def test_begin_scan_cancels_queued_panel_writes(self):
        self.connect()
        gate = self.block_worker()
        panel_write = self.runner.submit(Operation.set("bias", 1.0, source=Source.PANEL))
        panel_read = self.runner.submit(Operation.get("bias", source=Source.PANEL))
        # The gate read in progress is a panel call, so the scan cannot start yet.
        self.assertFalse(self.runner.begin_scan(timeout_s=0.1))
        self.assertIs(panel_write.result(WAIT_S).status, Status.CANCELLED)
        self.driver.gate_release.set()
        gate.result(WAIT_S)
        self.assertTrue(panel_read.result(WAIT_S).is_ok)
        self.assertTrue(self.runner.begin_scan(timeout_s=WAIT_S))
        self.assertEqual(self.driver_calls("set_bias"), [])


class SetManyTests(RunnerTestCase):
    def test_all_or_nothing(self):
        self.connect()
        result = self.runner.set_many({"bias": 1.0, "gain": 500}, source=Source.SCAN)
        self.assertIs(result.status, Status.FAILED)
        self.assertIn("gain: outside device limit", result.reason)
        self.assertEqual(self.driver.calls, [])
        result = self.runner.set_many({"bias": 1.0, "ping": 1.0}, source=Source.SCAN)
        self.assertIn("not a settable parameter", result.reason)
        result = self.runner.set_many({"ramped": 0.1}, source=Source.SCAN)
        self.assertIn("does not ramp yet", result.reason)
        self.assertEqual(self.driver.calls, [])

    def test_sequential_without_write_many(self):
        self.connect()
        result = self.runner.set_many({"bias": 1.0, "gain": 5}, source=Source.SCAN)
        self.assertTrue(result.is_ok)
        self.assertEqual(result.value, {"bias": 1.0, "gain": 5})
        self.assertEqual(self.driver.calls, [("set_bias", 1.0), ("set_gain", 5)])
        self.assertEqual(len(self.recorder.of(ValueChanged)), 2)

    def test_partial_failure_names_what_was_written(self):
        self.connect()
        self.driver.fail["set_gain"] = OSError("no reply")
        result = self.runner.set_many({"bias": 1.0, "gain": 5}, source=Source.SCAN)
        self.assertIs(result.status, Status.FAILED)
        self.assertIn("already written: bias", result.reason)
        self.assertIs(self.runner.state, DeviceState.UNKNOWN)


class WriteManyDevice(FakeDevice):
    def write_many(self, values):
        self.driver._simple("write_many", dict(values))


class WriteManyTests(RunnerTestCase):
    device_class = WriteManyDevice

    def test_grouped_write_uses_write_many(self):
        self.connect()
        result = self.runner.set_many({"bias": 1, "gain": 5.0}, source=Source.SCAN)
        self.assertTrue(result.is_ok)
        self.assertEqual(self.driver.calls, [("write_many", {"bias": 1.0, "gain": 5})])


class ReadKindTests(RunnerTestCase):
    def test_multi_parameter_read(self):
        self.connect()
        result = self.runner.get("Y", source=Source.SCAN)
        self.assertEqual(result.value, 0.2)
        self.assertEqual(
            [(e.name, e.value) for e in self.recorder.of(ValueChanged)], [("X", 0.1), ("Y", 0.2)]
        )
        self.assertEqual(self.runner.get("outputs", source=Source.PANEL).value, {"X": 0.1, "Y": 0.2})

    def test_multi_parameter_wrong_count_fails(self):
        self.connect()
        self.driver.xy = (0.1,)
        result = self.runner.get("X", source=Source.SCAN)
        self.assertIs(result.status, Status.FAILED)
        self.assertIn("1 values for 2 components", result.reason)

    def test_array_read(self):
        self.connect()
        self.assertEqual(self.runner.get("spectrum", source=Source.SCAN).value, [1.0, 2.0, 3.0, 4.0])


class OperationTests(unittest.TestCase):
    def test_validation(self):
        with self.assertRaises(ValueError):
            Operation.get("bias", source="scan", timeout=0)
        with self.assertRaises(ValueError):
            Operation.get("bias", source="scan", timeout=math.inf)
        with self.assertRaises(ValueError):
            Operation.get("", source="scan")
        with self.assertRaises(ValueError):
            Operation.set_many({}, source="scan")
        with self.assertRaises(ValueError):
            Operation.get("bias", source="somebody")
        with self.assertRaises(TypeError):
            Operation.get("bias")  # the source is required

    def test_describe(self):
        self.assertEqual(Operation.set("bias", 1.5, source="scan").describe(), "set bias=1.5")
        self.assertEqual(Operation.call("set_display", True, source="panel").describe(), "set_display(True)")

    def test_future_cannot_be_cancelled_from_outside(self):
        self.assertFalse(ResultFuture().cancel())

    def test_runner_needs_a_device(self):
        with self.assertRaises(TypeError):
            Runner(object())

    def test_submit_needs_an_operation(self):
        runner = Runner(FakeDevice(driver=FakeDriver()))
        self.addCleanup(runner.shutdown)
        with self.assertRaises(TypeError):
            runner.submit("get bias")


if __name__ == "__main__":
    unittest.main()
