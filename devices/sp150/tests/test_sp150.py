import inspect
import math
import os
import unittest
import xml.etree.ElementTree as ET
from collections import deque

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.shared_runtime.visa import VisaRuntime

from devices.sp150.sp150_hardware import (
    SP150ConnectionError,
    SP150Hardware,
    SP150ProtocolError,
)
from devices.sp150.sp150_logic import (
    SP150Logic,
    SP150MoveTimeout,
    SP150OperationCancelled,
)
from devices.sp150.sp150_main import SP150


class FakeInstrument:
    def __init__(self, query_responses=()):
        self.query_responses = deque(query_responses)
        self.writes = []
        self.queries = []
        self.closed = 0
        self.read_termination = None
        self.write_termination = None
        self.timeout = None

    def write(self, command):
        self.writes.append(command)

    def query(self, command, delay=0):
        self.queries.append((command, delay))
        if not self.query_responses:
            raise TimeoutError("fake query timeout")
        response = self.query_responses.popleft()
        if isinstance(response, BaseException):
            raise response
        return response

    def close(self):
        self.closed += 1


class FakeResourceManager:
    def __init__(self, instrument=None, open_error=None):
        self.instrument = instrument or FakeInstrument()
        self.open_error = open_error
        self.open_calls = []
        self.closed = 0

    def open_resource(self, address):
        self.open_calls.append(address)
        if self.open_error is not None:
            raise self.open_error
        return self.instrument

    def close(self):
        self.closed += 1


class CountingFactory:
    def __init__(self, manager):
        self.manager = manager
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.manager


class SP150HardwareTests(unittest.TestCase):
    def make_hardware(self, responses=()):
        instrument = FakeInstrument(responses)
        manager = FakeResourceManager(instrument)
        factory = CountingFactory(manager)
        return (
            SP150Hardware(VisaRuntime(manager_factory=factory)),
            instrument,
            manager,
            factory,
        )

    def test_explicit_connection_configures_resource(self):
        hardware, instrument, manager, factory = self.make_hardware()
        self.assertEqual(factory.calls, 0)

        hardware.connect("GPIB0::11::INSTR")

        self.assertEqual(factory.calls, 1)
        self.assertEqual(manager.open_calls, ["GPIB0::11::INSTR"])
        self.assertEqual(instrument.read_termination, "\n")
        self.assertEqual(instrument.write_termination, "\r")
        self.assertEqual(instrument.timeout, 10_000)

    def test_goto_and_query_protocol(self):
        hardware, instrument, _manager, _factory = self.make_hardware(["632.80"])
        hardware.connect("GPIB0::11::INSTR", query_delay_s=0.5)
        hardware.command_wavelength(632.8)

        self.assertEqual(hardware.read_wavelength(), 632.8)
        self.assertEqual(instrument.writes, ["632.80 <GOTO>"])
        self.assertEqual(instrument.queries, [("?NM", 0.5)])

    def test_boundaries_and_nonfinite_values(self):
        hardware, instrument, _manager, _factory = self.make_hardware()
        hardware.connect("GPIB0::11::INSTR")
        hardware.command_wavelength(0)
        hardware.command_wavelength(3000)
        writes_after_valid = list(instrument.writes)

        for value in (-0.01, 3000.01, math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                hardware.command_wavelength(value)
        self.assertEqual(instrument.writes, writes_after_valid)

    def test_malformed_and_timeout_query_have_protocol_context(self):
        hardware, _instrument, _manager, _factory = self.make_hardware(
            ["invalid", TimeoutError("visa timeout")]
        )
        hardware.connect("GPIB0::11::INSTR")
        with self.assertRaisesRegex(SP150ProtocolError, "wavelength response"):
            hardware.read_wavelength()
        with self.assertRaisesRegex(SP150ProtocolError, "query failed"):
            hardware.read_wavelength()

    def test_failed_connection_and_repeated_disconnect_clean_up(self):
        manager = FakeResourceManager(open_error=RuntimeError("open failed"))
        runtime = VisaRuntime(manager_factory=CountingFactory(manager))
        hardware = SP150Hardware(runtime)
        with self.assertRaises(SP150ConnectionError):
            hardware.connect("GPIB0::11::INSTR")
        self.assertEqual(manager.closed, 0)
        runtime.shutdown()
        self.assertEqual(manager.closed, 1)

        hardware, instrument, manager, _factory = self.make_hardware()
        hardware.connect("GPIB0::11::INSTR")
        hardware.disconnect()
        hardware.disconnect()
        self.assertEqual(instrument.closed, 1)
        self.assertEqual(manager.closed, 0)
        hardware.visa_runtime.shutdown()
        self.assertEqual(manager.closed, 1)


class SP150LogicTests(unittest.TestCase):
    def make_logic(self, responses=(), **kwargs):
        instrument = FakeInstrument(responses)
        manager = FakeResourceManager(instrument)
        factory = CountingFactory(manager)
        hardware = SP150Hardware(VisaRuntime(manager_factory=factory))
        logic = SP150Logic(
            hardware,
            poll_interval_s=0,
            completion_tolerance_nm=0.1,
            **kwargs,
        )
        return logic, instrument, factory

    def test_scan_discovery_exposes_only_intended_channels(self):
        logic, _instrument, _factory = self.make_logic()
        methods = {
            name
            for name in dir(logic)
            if name.startswith(("get_", "set_"))
            and callable(getattr(logic, name))
            and self._has_scan_signature(getattr(logic, name), name)
        }
        self.assertEqual(methods, {"get_wavelength", "set_wavelength"})

    def test_disconnected_scan_call_does_not_auto_connect(self):
        logic, _instrument, factory = self.make_logic()
        with self.assertRaisesRegex(RuntimeError, "call connect"):
            logic.get_wavelength()
        self.assertEqual(factory.calls, 0)

    def test_move_polls_until_readback_reaches_tolerance(self):
        logic, instrument, _factory = self.make_logic(["499.0", "499.95"])
        logic.connect("GPIB0::11::INSTR", query_delay_s=0)

        self.assertEqual(logic.set_wavelength(500), 499.95)
        self.assertEqual(instrument.writes, ["500.00 <GOTO>"])
        self.assertEqual(len(instrument.queries), 2)

    def test_move_timeout_reports_last_readback(self):
        times = iter([0.0, 1.0])
        logic, _instrument, _factory = self.make_logic(
            ["400.0"], move_timeout_s=0.5, monotonic=times.__next__
        )
        logic.connect("GPIB0::11::INSTR", query_delay_s=0)
        with self.assertRaisesRegex(SP150MoveTimeout, "last readback was 400.00"):
            logic.set_wavelength(500)

    def test_force_stop_is_cooperative_and_start_scan_clears_it(self):
        logic, _instrument, _factory = self.make_logic(["500.0"])
        logic.connect("GPIB0::11::INSTR", query_delay_s=0)
        self.assertFalse(logic.force_stop())
        with self.assertRaises(SP150OperationCancelled):
            logic.get_wavelength()
        self.assertTrue(logic.start_scan())
        self.assertEqual(logic.get_wavelength(), 500.0)
        logic.disconnect()

    @staticmethod
    def _has_scan_signature(method, name):
        positional = [
            parameter
            for parameter in inspect.signature(method).parameters.values()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
        ]
        return len(positional) == (0 if name.startswith("get_") else 1)


class SP150WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_ui_xml_parses(self):
        ET.parse(os.path.join(os.path.dirname(__file__), "..", "sp150.ui"))

    def test_widget_construction_does_not_create_resource_manager(self):
        manager = FakeResourceManager()
        factory = CountingFactory(manager)
        widget = SP150(
            SP150Hardware(VisaRuntime(manager_factory=factory))
        )
        try:
            self.assertEqual(factory.calls, 0)
            self.assertFalse(widget.logic.connected)
        finally:
            widget.terminate_dev()


if __name__ == "__main__":
    unittest.main()
