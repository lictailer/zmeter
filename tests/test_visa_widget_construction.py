from __future__ import annotations

import os
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtTest, QtWidgets

from core.shared_runtime.visa import VisaRuntime
from devices.demoDevice.demoDevice_main import DemoDevice
from devices.hp34401a.hp34401a_main import HP34401A
from devices.keithley24xx.keithley24xx_main import Keithley24xx
from devices.sr830_v2.sr830_main import SR830
from devices.sr860.sr860_main import SR860


class VisaWidgetConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_dropdown_widgets_automatically_refresh_without_opening_resources(self):
        factory_calls = []

        class FakeManager:
            def __init__(self):
                self.list_calls = 0
                self.open_calls = 0

            def list_resources(self, _query="?*::INSTR"):
                self.list_calls += 1
                return ("GPIB0::1::INSTR",)

            def open_resource(self, *_args, **_kwargs):
                self.open_calls += 1
                raise AssertionError("startup refresh must not open resources")

            def close(self):
                pass

        manager = FakeManager()

        def manager_factory():
            factory_calls.append(True)
            return manager

        runtime = VisaRuntime(manager_factory=manager_factory)
        widget_combos = [
            (HP34401A(runtime), "address_comboBox"),
            (Keithley24xx(runtime), "address_cb"),
            (SR830(runtime), "address_cb"),
            (SR860(runtime), "address_cb"),
            (DemoDevice(runtime), "address_comboBox"),
        ]
        widgets = [widget for widget, _combo_name in widget_combos]
        self.addCleanup(lambda: [widget.close() for widget in widgets])

        self.assertEqual(factory_calls, [])
        deadline = time.monotonic() + 3
        while (
            (
                manager.list_calls < len(widgets)
                or any(widget.visa_refresh.controller.busy for widget in widgets)
            )
            and time.monotonic() < deadline
        ):
            QtWidgets.QApplication.processEvents()
            QtTest.QTest.qWait(5)

        self.assertEqual(factory_calls, [True])
        self.assertEqual(manager.list_calls, len(widgets))
        self.assertEqual(manager.open_calls, 0)
        for widget, combo_name in widget_combos:
            button = widget.findChild(
                QtWidgets.QPushButton, "refresh_visa_button"
            )
            self.assertIsNotNone(button, type(widget).__name__)
            self.assertEqual(button.text(), "Refresh VISA")
            combo = getattr(widget, combo_name)
            self.assertEqual(combo.currentText(), "GPIB0::1::INSTR")
            self.assertGreaterEqual(combo.minimumWidth(), 320)

        runtime.shutdown()


if __name__ == "__main__":
    unittest.main()
