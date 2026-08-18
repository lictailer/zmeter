from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from k10cr1 import k10cr1_hardware as bindings
from k10cr1.k10cr1_logic import K10CR1Logic
from k10cr1.k10cr1_main import K10CR1


class FakeLease:
    def __init__(self):
        self.close_calls = 0

    def close(self):
        self.close_calls += 1


class FakeRuntime:
    def __init__(self):
        self.load_calls = []
        self.leases = []
        self.ensure_calls = 0
        self.refresh_calls = 0
        self.initialized_components = set()

    def acquire(self, _owner):
        lease = FakeLease()
        self.leases.append(lease)
        return lease

    def load_native(self, component):
        self.load_calls.append(component)
        raise AssertionError("test did not authorize native loading")

    def ensure_device_manager(self, component, callback):
        self.ensure_calls += 1
        if component in self.initialized_components:
            return False
        callback()
        self.initialized_components.add(component)
        return True

    def refresh_device_manager(self, component, callback):
        self.refresh_calls += 1
        result = callback()
        self.initialized_components.add(component)
        return result


class FakeCFunction:
    def __init__(self, result):
        self.result = result
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.result


class K10CR1SharedRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_import_and_widget_construction_do_not_load_vendor_runtime(self):
        runtime = FakeRuntime()
        before_clr = sys.modules.get("clr")
        widget = K10CR1(runtime)
        self.addCleanup(widget.close)
        self.assertEqual(runtime.load_calls, [])
        self.assertIs(sys.modules.get("clr"), before_clr)

    def test_lazy_binding_resolves_only_when_called(self):
        lazy_library = bindings._LazyLibrary()
        function = lazy_library.ISC_Test
        function.argtypes = [int]
        function.restype = int
        real_function = FakeCFunction(7)
        fake_library = mock.Mock(ISC_Test=real_function)
        with mock.patch.object(bindings, "_native_library", return_value=fake_library):
            self.assertEqual(function(1), 7)
        self.assertEqual(real_function.argtypes, [int])
        self.assertIs(real_function.restype, int)

    def test_failed_device_list_releases_runtime_lease(self):
        runtime = FakeRuntime()
        logic = K10CR1Logic(runtime)
        logic.assign_serial("12345678")
        with mock.patch.object(bindings, "configure_runtime"), mock.patch.object(
            bindings, "TLI_BuildDeviceList", return_value=1
        ):
            self.assertFalse(logic.connect())
        self.assertEqual(runtime.ensure_calls, 1)
        self.assertEqual(runtime.leases[0].close_calls, 1)

    @staticmethod
    def _connection_patches(*, open_results):
        return mock.patch.multiple(
            bindings,
            configure_runtime=mock.DEFAULT,
            TLI_BuildDeviceList=mock.Mock(return_value=0),
            ISC_Open=mock.Mock(side_effect=open_results),
            ISC_Close=mock.Mock(return_value=0),
            ISC_GetHardwareInfoBlock=mock.Mock(return_value=1),
            ISC_GetVelParamsBlock=mock.Mock(return_value=0),
            ISC_SetVelParamsBlock=mock.Mock(return_value=0),
        )

    def test_reconnect_uses_cached_device_manager(self):
        runtime = FakeRuntime()
        logic = K10CR1Logic(runtime)
        logic.assign_serial("12345678")

        with self._connection_patches(open_results=[0, 0]):
            self.assertTrue(logic.connect())
            logic.disconnect()
            self.assertTrue(logic.connect())
            build_calls = bindings.TLI_BuildDeviceList.call_count

        self.assertEqual(runtime.ensure_calls, 2)
        self.assertEqual(runtime.refresh_calls, 0)
        self.assertEqual(build_calls, 1)

    def test_failed_open_refreshes_once_and_retries_same_serial(self):
        runtime = FakeRuntime()
        logic = K10CR1Logic(runtime)
        logic.assign_serial("12345678")

        with self._connection_patches(open_results=[7, 0]):
            self.assertTrue(logic.connect())
            open_calls = bindings.ISC_Open.call_count
            build_calls = bindings.TLI_BuildDeviceList.call_count

        self.assertEqual(runtime.ensure_calls, 1)
        self.assertEqual(runtime.refresh_calls, 1)
        self.assertEqual(open_calls, 2)
        self.assertEqual(build_calls, 2)

    def test_failed_open_retry_reports_final_code_and_releases_lease(self):
        runtime = FakeRuntime()
        logic = K10CR1Logic(runtime)
        logic.assign_serial("12345678")
        entries = []
        logic.sig_log.connect(entries.append)

        with self._connection_patches(open_results=[7, 8]):
            self.assertFalse(logic.connect())

        self.assertEqual(runtime.refresh_calls, 1)
        self.assertEqual(runtime.leases[0].close_calls, 1)
        self.assertEqual(entries[-1][0], "ERROR")
        self.assertIn("code 8", entries[-1][1])

    def test_worker_exception_reaches_device_log(self):
        logic = K10CR1Logic(FakeRuntime())
        entries = []
        logic.sig_log.connect(entries.append)
        logic.job = "home"

        with mock.patch.object(logic, "home", side_effect=RuntimeError("failed")):
            logic.run()

        self.assertEqual(entries[-1][0], "ERROR")
        self.assertIn("K10CR1 home failed", entries[-1][1])

    def test_position_signal_updates_label_without_log_entry(self):
        widget = K10CR1(FakeRuntime())
        self.addCleanup(widget.close)

        widget.logic.sig_last_pos.emit(49152000)
        self.app.processEvents()

        self.assertIn("360.000 deg", widget.last_pos_label.text())
        self.assertEqual(widget.log_textEdit.toPlainText(), "")

    def test_widget_log_is_resizable_and_uses_shared_contract(self):
        widget = K10CR1(FakeRuntime())
        self.addCleanup(widget.close)

        self.assertTrue(widget.log_textEdit.isReadOnly())
        self.assertEqual(widget.log_textEdit.maximumBlockCount(), 500)
        self.assertEqual(widget.maximumHeight(), 16777215)
        self.assertEqual(
            widget.sizePolicy().verticalPolicy(),
            QtWidgets.QSizePolicy.Policy.Expanding,
        )
        widget.show()
        self.app.processEvents()
        visible_lines = (
            widget.log_textEdit.height()
            / widget.log_textEdit.fontMetrics().lineSpacing()
        )
        self.assertGreaterEqual(visible_lines, 8)
        self.assertLessEqual(visible_lines, 10)
        initial_log_height = widget.log_textEdit.height()
        widget.resize(widget.width(), widget.height() + 100)
        self.app.processEvents()
        self.assertGreater(widget.log_textEdit.height(), initial_log_height)


if __name__ == "__main__":
    unittest.main()
