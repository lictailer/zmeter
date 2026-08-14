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
        self.initialize_calls = 0

    def acquire(self, _owner):
        lease = FakeLease()
        self.leases.append(lease)
        return lease

    def load_native(self, component):
        self.load_calls.append(component)
        raise AssertionError("test did not authorize native loading")

    def initialize_device_manager(self, callback):
        self.initialize_calls += 1
        return callback()


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
        self.assertEqual(runtime.initialize_calls, 1)
        self.assertEqual(runtime.leases[0].close_calls, 1)


if __name__ == "__main__":
    unittest.main()
