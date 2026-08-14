from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.shared_runtime.visa import VisaRuntime
from demoDevice.demoDevice_main import DemoDevice
from hp34401a.hp34401a_main import HP34401A
from keithley24xx.keithley24xx_main import Keithley24xx
from sr830_v2.sr830_main import SR830
from sr860.sr860_main import SR860


class VisaWidgetConstructionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_widgets_have_explicit_refresh_without_constructor_discovery(self):
        factory_calls = []

        def forbidden_factory():
            factory_calls.append(True)
            raise AssertionError("widget construction must not create a manager")

        runtime = VisaRuntime(manager_factory=forbidden_factory)
        widgets = [
            HP34401A(runtime),
            Keithley24xx(runtime),
            SR830(runtime),
            SR860(runtime),
            DemoDevice(runtime),
        ]
        self.addCleanup(lambda: [widget.close() for widget in widgets])
        self.assertEqual(factory_calls, [])
        for widget in widgets:
            button = widget.findChild(
                QtWidgets.QPushButton, "refresh_visa_button"
            )
            self.assertIsNotNone(button, type(widget).__name__)
            self.assertEqual(button.text(), "Refresh VISA")


if __name__ == "__main__":
    unittest.main()
