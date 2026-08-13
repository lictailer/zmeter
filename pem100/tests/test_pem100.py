import inspect
import math
import os
import unittest
import xml.etree.ElementTree as ET
from collections import deque

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from pem100.pem100_hardware import (
    PEM100ConnectionError,
    PEM100Hardware,
    PEM100ProtocolError,
)
from pem100.pem100_logic import PEM100Logic
from pem100.pem100_main import PEM100


class FakeInstrument:
    def __init__(self, read_responses=()):
        self.read_responses = deque(read_responses)
        self.writes = []
        self.closed = 0
        self.read_termination = None
        self.write_termination = None
        self.timeout = None

    def write(self, command):
        self.writes.append(command)

    def read(self):
        if not self.read_responses:
            raise TimeoutError("fake read timeout")
        response = self.read_responses.popleft()
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

    def open_resource(self, address, **kwargs):
        self.open_calls.append((address, kwargs))
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


class PEM100HardwareTests(unittest.TestCase):
    def make_hardware(self, responses=()):
        instrument = FakeInstrument(responses)
        manager = FakeResourceManager(instrument)
        factory = CountingFactory(manager)
        hardware = PEM100Hardware(factory, sleep=lambda _seconds: None)
        return hardware, instrument, manager, factory

    def test_explicit_connection_configures_serial_resource(self):
        hardware, instrument, manager, factory = self.make_hardware()
        self.assertEqual(factory.calls, 0)

        self.assertTrue(hardware.connect("ASRL9::INSTR"))

        self.assertEqual(factory.calls, 1)
        self.assertEqual(manager.open_calls[0][0], "ASRL9::INSTR")
        self.assertEqual(manager.open_calls[0][1]["baud_rate"], 2400)
        self.assertEqual(manager.open_calls[0][1]["data_bits"], 8)
        self.assertEqual(instrument.read_termination, "\n\r*")
        self.assertEqual(instrument.write_termination, "\r\n")
        self.assertEqual(instrument.timeout, 20_000)

    def test_command_formatting_and_numeric_reads(self):
        hardware, instrument, _manager, _factory = self.make_hardware(
            ["OK", "OK", "05500", "0250"]
        )
        hardware.connect("ASRL9::INSTR")

        hardware.set_wavelength(550.09)
        hardware.set_retardance(0.25)
        wavelength = hardware.get_wavelength()
        retardance = hardware.get_retardance()

        self.assertEqual(
            instrument.writes,
            ["W:005500", "R:0250", "W", "R"],
        )
        self.assertEqual(wavelength, 550.0)
        self.assertEqual(retardance, 0.25)

    def test_boundaries_are_allowed_and_invalid_values_do_not_write(self):
        hardware, instrument, _manager, _factory = self.make_hardware(
            ["OK", "OK", "OK", "OK"]
        )
        hardware.connect("ASRL9::INSTR")
        hardware.set_wavelength(170)
        hardware.set_wavelength(2500)
        hardware.set_retardance(0)
        hardware.set_retardance(0.5)
        writes_after_valid = list(instrument.writes)

        for value in (169.9, 2500.1, math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                hardware.set_wavelength(value)
        for value in (-0.001, 0.501, math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                hardware.set_retardance(value)

        self.assertEqual(instrument.writes, writes_after_valid)

    def test_malformed_and_timeout_reads_have_protocol_context(self):
        hardware, _instrument, _manager, _factory = self.make_hardware(
            ["not-a-number", TimeoutError("visa timeout")]
        )
        hardware.connect("ASRL9::INSTR")

        with self.assertRaisesRegex(PEM100ProtocolError, "wavelength response"):
            hardware.get_wavelength()
        with self.assertRaisesRegex(PEM100ProtocolError, "retardance read failed"):
            hardware.get_retardance()

    def test_failed_connection_and_repeated_disconnect_clean_up(self):
        manager = FakeResourceManager(open_error=RuntimeError("open failed"))
        hardware = PEM100Hardware(CountingFactory(manager))
        with self.assertRaises(PEM100ConnectionError):
            hardware.connect("ASRL9::INSTR")
        self.assertEqual(manager.closed, 1)

        hardware, instrument, manager, _factory = self.make_hardware()
        hardware.connect("ASRL9::INSTR")
        hardware.disconnect()
        hardware.disconnect()
        self.assertEqual(instrument.closed, 1)
        self.assertEqual(manager.closed, 1)


class PEM100LogicTests(unittest.TestCase):
    def make_logic(self, responses=()):
        instrument = FakeInstrument(responses)
        manager = FakeResourceManager(instrument)
        factory = CountingFactory(manager)
        hardware = PEM100Hardware(factory, sleep=lambda _seconds: None)
        return PEM100Logic(hardware), instrument, factory

    def test_scan_discovery_exposes_only_intended_channels(self):
        logic, _instrument, _factory = self.make_logic()
        methods = {
            name
            for name in dir(logic)
            if name.startswith(("get_", "set_"))
            and callable(getattr(logic, name))
            and self._has_scan_signature(getattr(logic, name), name)
        }
        self.assertEqual(
            methods,
            {
                "get_wavelength",
                "set_wavelength",
                "get_retardance",
                "set_retardance",
            },
        )

    def test_disconnected_scan_call_does_not_auto_connect(self):
        logic, _instrument, factory = self.make_logic()
        with self.assertRaisesRegex(RuntimeError, "call connect"):
            logic.get_wavelength()
        self.assertEqual(factory.calls, 0)

    def test_logic_round_trip_and_lifecycle(self):
        logic, _instrument, _factory = self.make_logic(["OK", "06000"])
        logic.connect("ASRL9::INSTR")
        self.assertEqual(logic.set_wavelength(600), 600.0)

        self.assertTrue(logic.stop_scan())
        self.assertEqual(logic.get_wavelength.__name__, "get_wavelength")
        self.assertTrue(logic.start_scan())
        self.assertFalse(logic.force_stop())
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            logic.get_wavelength()
        self.assertTrue(logic.start_scan())
        logic.disconnect()
        logic.disconnect()
        self.assertFalse(logic.connected)

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


class PEM100WidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_ui_xml_parses(self):
        ET.parse(os.path.join(os.path.dirname(__file__), "..", "pem100.ui"))

    def test_widget_construction_does_not_create_resource_manager(self):
        manager = FakeResourceManager()
        factory = CountingFactory(manager)
        widget = PEM100(PEM100Hardware(factory, sleep=lambda _seconds: None))
        try:
            self.assertEqual(factory.calls, 0)
            self.assertFalse(widget.logic.connected)
        finally:
            widget.terminate_dev()


if __name__ == "__main__":
    unittest.main()
