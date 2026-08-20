from __future__ import annotations

import os
import subprocess
import sys
import unittest
from ctypes import c_bool
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from devices.opticool import opticool_dll
from devices.opticool.opticool_hardware import OptiCool_Hardware
from devices.opticool.opticool_logic import OptiCool_Logic
from devices.tlpm.tlpm_logic import TLPMLogic
from devices.tlpm.tlpm_main import TLPM
from PyQt6 import QtWidgets

from core.device_management.registry import build_default_registry


class Phase2ConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_registered_widgets_construct_without_runtime_or_hardware_access(self):
        registry = build_default_registry()
        with (
            mock.patch(
                "devices.montana2.montana_libs.instrument.requests.get",
                side_effect=AssertionError("Montana network access"),
            ) as montana_get,
            mock.patch.object(
                opticool_dll,
                "load_vendor_runtime",
                side_effect=AssertionError("OptiCool runtime load"),
            ) as opticool_load,
            mock.patch(
                "devices.tlpm.tlpm_hardware.cdll.LoadLibrary",
                side_effect=AssertionError("TLPM native load"),
            ) as tlpm_load,
        ):
            widgets = [
                registry.registration(driver_id).factory()
                for driver_id in ("montana2", "opticool", "tlpm")
            ]

        montana_get.assert_not_called()
        opticool_load.assert_not_called()
        tlpm_load.assert_not_called()
        self.assertEqual(
            widgets[0].ipaddress_lineEdit.text(), "136.167.55.165"
        )
        for widget in widgets:
            widget.close()


class OptiCoolLazyRuntimeTests(unittest.TestCase):
    def test_widget_module_import_does_not_load_vendor_runtime(self):
        repository_root = Path(__file__).resolve().parents[1]
        script = r"""
import sys
from devices.opticool.opticool_main import OptiCool

unexpected = [name for name in ("clr", "QuantumDesign", "System") if name in sys.modules]
if unexpected:
    raise SystemExit("unexpected vendor import: " + ", ".join(unexpected))
print(OptiCool.__name__)
"""
        result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=repository_root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("OptiCool", result.stdout)

    def test_loader_retains_fixed_path_and_delay_inside_connect_boundary(self):
        dll = object()
        clr = SimpleNamespace(AddReference=mock.Mock(return_value=dll))
        quantum_design = object()
        system = object()

        def import_runtime(name):
            return {
                "clr": clr,
                "QuantumDesign": quantum_design,
                "System": system,
            }[name]

        with (
            mock.patch.object(opticool_dll, "import_module", import_runtime),
            mock.patch.object(opticool_dll.time, "sleep") as sleep,
        ):
            result = opticool_dll.load_vendor_runtime()

        self.assertEqual(result, (dll, quantum_design, system))
        clr.AddReference.assert_called_once_with(
            r"C:\QdOptiCool\LabVIEW\QDInstrument.dll"
        )
        sleep.assert_called_once_with(1)

    @staticmethod
    def _successful_vendor_runtime():
        dll = SimpleNamespace(GetType=mock.Mock(side_effect=lambda name: name))
        activator = SimpleNamespace(
            CreateInstance=mock.Mock(side_effect=lambda handle: f"instance:{handle}")
        )
        system = SimpleNamespace(Activator=activator)
        instrument = object()
        factory = SimpleNamespace(
            GetQDInstrument=mock.Mock(return_value=instrument)
        )
        quantum_design = SimpleNamespace(
            QDInstrument=SimpleNamespace(
                QDInstrumentBase=SimpleNamespace(
                    QDInstrumentType=SimpleNamespace(OptiCool="opticool-type")
                ),
                QDInstrumentFactory=mock.Mock(return_value=factory),
            )
        )
        return (dll, quantum_design, system), instrument

    def test_failed_hardware_load_clears_state_and_next_attempt_retries(self):
        runtime, instrument = self._successful_vendor_runtime()
        hardware = OptiCool_Hardware()

        with mock.patch.object(
            opticool_dll,
            "load_vendor_runtime",
            side_effect=[RuntimeError("vendor unavailable"), runtime],
        ) as load:
            with self.assertRaisesRegex(RuntimeError, "vendor unavailable"):
                hardware.connect_hardware()
            self.assertFalse(hardware.connected)
            self.assertIsNone(hardware.instrument)
            self.assertIsNone(hardware._vendor_dll)

            self.assertTrue(hardware.connect_hardware())

        self.assertEqual(load.call_count, 2)
        self.assertTrue(hardware.connected)
        self.assertIs(hardware.instrument, instrument)
        hardware.disconnect()
        self.assertFalse(hardware.connected)
        self.assertIsNone(hardware._vendor_dll)

    def test_logic_reports_failed_connect_and_allows_manual_retry(self):
        logic = OptiCool_Logic()
        logic.hardware = SimpleNamespace(
            connect_hardware=mock.Mock(
                side_effect=[RuntimeError("load failed"), True]
            )
        )
        statuses = []
        logic.sig_status.connect(statuses.append)

        logic.connect()
        self.assertFalse(logic.is_connected)
        self.assertTrue(any("load failed" in message for message in statuses))

        logic.connect()
        self.assertTrue(logic.is_connected)
        self.assertEqual(logic.hardware.connect_hardware.call_count, 2)


class TlpmLifecycleTests(unittest.TestCase):
    @staticmethod
    def _discovery(count, resource=b"USB0::FIRST::INSTR"):
        discovery = mock.Mock()

        def find_resources(pointer):
            pointer._obj.value = count

        def get_resource(_index, buffer):
            buffer.value = resource

        discovery.findRsrc.side_effect = find_resources
        discovery.getRsrcName.side_effect = get_resource
        return discovery

    @staticmethod
    def _hardware():
        hardware = mock.Mock()
        hardware.getCalibrationMsg.side_effect = (
            lambda buffer: setattr(buffer, "value", b"CALIBRATION")
        )
        return hardware

    def test_connect_preserves_first_resource_selection_and_reset(self):
        discovery = self._discovery(2)
        hardware = self._hardware()
        logic = TLPMLogic()

        with mock.patch(
            "devices.tlpm.tlpm_logic.TLPM_Hardware",
            side_effect=[discovery, hardware],
        ):
            logic.connect()

        discovery.getRsrcName.assert_called_once()
        discovery.close.assert_called_once_with()
        resource, identity_query, reset_device = hardware.open.call_args.args
        self.assertEqual(resource.value, b"USB0::FIRST::INSTR")
        self.assertIsInstance(identity_query, c_bool)
        self.assertIsInstance(reset_device, c_bool)
        self.assertTrue(identity_query.value)
        self.assertTrue(reset_device.value)
        self.assertIs(logic.hardware, hardware)
        self.assertTrue(logic.is_connected)

    def test_zero_resource_failure_cleans_up_and_later_connect_retries(self):
        empty_discovery = self._discovery(0)
        good_discovery = self._discovery(1)
        hardware = self._hardware()
        logic = TLPMLogic()

        with mock.patch(
            "devices.tlpm.tlpm_logic.TLPM_Hardware",
            side_effect=[empty_discovery, good_discovery, hardware],
        ):
            with self.assertRaisesRegex(RuntimeError, "No TLPM device"):
                logic.connect()
            self.assertFalse(logic.is_connected)
            empty_discovery.close.assert_called_once_with()

            logic.connect()

        self.assertTrue(logic.is_connected)
        good_discovery.close.assert_called_once_with()
        hardware.open.assert_called_once()

    def test_run_reports_error_and_resets_all_job_flags(self):
        discovery = self._discovery(0)
        logic = TLPMLogic()
        messages = []
        logic.sig_info.connect(messages.append)
        logic.do_connect = True

        with mock.patch(
            "devices.tlpm.tlpm_logic.TLPM_Hardware",
            return_value=discovery,
        ):
            logic.run()

        self.assertFalse(logic.is_connected)
        self.assertTrue(any("No TLPM device" in message for message in messages))
        self.assertFalse(logic.do_connect)
        self.assertFalse(logic.do_disconnect)
        self.assertFalse(logic.do_read_indefinitely)

    def test_busy_job_is_rejected_without_restarting_thread(self):
        logic = SimpleNamespace(
            isRunning=mock.Mock(return_value=True),
            start=mock.Mock(),
            do_connect=False,
        )
        widget = SimpleNamespace(logic=logic, update_info=mock.Mock())

        result = TLPM._start_logic_job(widget, "do_connect")

        self.assertFalse(result)
        logic.start.assert_not_called()
        self.assertFalse(logic.do_connect)
        widget.update_info.assert_called_once()

    def test_termination_timeout_does_not_disconnect_live_worker(self):
        logic = SimpleNamespace(
            is_connected=True,
            request_stop=mock.Mock(),
            isRunning=mock.Mock(return_value=True),
            wait=mock.Mock(return_value=False),
            disconnect=mock.Mock(),
        )
        widget = SimpleNamespace(
            logic=logic,
            TERMINATION_TIMEOUT_MS=10_000,
        )

        self.assertFalse(TLPM.terminate_dev(widget))
        logic.request_stop.assert_called_once_with()
        logic.wait.assert_called_once_with(10_000)
        logic.disconnect.assert_not_called()

    def test_termination_waits_then_disconnects_and_is_idempotent(self):
        class Logic:
            def __init__(self):
                self.is_connected = True
                self.running = True
                self.stop_requests = 0
                self.disconnect_calls = 0

            def request_stop(self):
                self.stop_requests += 1

            def isRunning(self):
                return self.running

            def wait(self, timeout_ms):
                self.timeout_ms = timeout_ms
                self.running = False
                return True

            def disconnect(self):
                self.disconnect_calls += 1
                self.is_connected = False

        logic = Logic()
        widget = SimpleNamespace(
            logic=logic,
            TERMINATION_TIMEOUT_MS=10_000,
        )

        self.assertTrue(TLPM.terminate_dev(widget))
        self.assertTrue(TLPM.terminate_dev(widget))
        self.assertEqual(logic.timeout_ms, 10_000)
        self.assertEqual(logic.disconnect_calls, 1)
        self.assertEqual(logic.stop_requests, 2)


if __name__ == "__main__":
    unittest.main()
