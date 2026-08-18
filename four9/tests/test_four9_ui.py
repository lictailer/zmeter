import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from four9.four9_logic import Four9Logic
from four9.four9_main import Four9
from four9.tests.test_four9_logic import _FakeHardware


class Four9UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = (
            QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        )

    def setUp(self):
        self.logic = Four9Logic(hardware=_FakeHardware())
        self.widget = Four9(logic=self.logic)

    def tearDown(self):
        self.widget.close()
        self.widget.deleteLater()
        self.application.processEvents()

    def test_defaults_range_and_no_timeout_control(self):
        self.assertEqual(self.widget.host_lineEdit.text(), "127.0.0.1")
        self.assertEqual(self.widget.port_spinBox.value(), 5050)
        self.assertEqual(self.widget.targetTemperature_doubleSpinBox.minimum(), 0)
        self.assertEqual(self.widget.targetTemperature_doubleSpinBox.maximum(), 300)
        timeout_widgets = [
            child
            for child in self.widget.findChildren(QtWidgets.QWidget)
            if "timeout" in child.objectName().lower()
            or "stabili" in child.objectName().lower()
            and "wait" in child.objectName().lower()
        ]
        self.assertEqual(timeout_widgets, [])

    def test_passive_signals_update_all_status_labels(self):
        self.logic.sig_target_temperature.emit(100.0)
        self.logic.sig_temperature.emit(99.875)
        self.logic.sig_temperature_stable.emit(True, "timeout_override")
        self.application.processEvents()

        self.assertEqual(self.widget.targetTemperature_label.text(), "100.00000 K")
        self.assertEqual(self.widget.currentTemperature_label.text(), "99.87500 K")
        self.assertEqual(
            self.widget.temperatureStatus_label.text(),
            "Stable (timeout override)",
        )

    def test_buttons_are_wired_and_disabled_while_disconnected(self):
        self.assertTrue(self.widget.connect_pushButton.isEnabled())
        self.assertFalse(self.widget.disconnect_pushButton.isEnabled())
        self.assertFalse(self.widget.setTemperature_pushButton.isEnabled())
        self.assertFalse(self.widget.getTemperature_pushButton.isEnabled())
        self.assertIn("Four9 ready", self.widget.logStatus_textEdit.toPlainText())

    def test_buttons_dispatch_background_connect_set_get_and_disconnect(self):
        hardware = self.logic.hardware
        self.widget.connect_pushButton.click()
        self.assertTrue(self.logic.wait(1000))
        self.application.processEvents()
        self.assertTrue(self.logic.is_connected)
        self.assertEqual(self.widget.connectionStatus_label.text(), "Connected")

        self.widget.targetTemperature_doubleSpinBox.setValue(42)
        self.widget.setTemperature_pushButton.click()
        self.assertTrue(self.logic.wait(1000))
        self.application.processEvents()
        self.assertEqual(hardware.set_calls, [42.0])
        self.assertEqual(self.widget.targetTemperature_label.text(), "42.00000 K")

        self.widget.getTemperature_pushButton.click()
        self.assertTrue(self.logic.wait(1000))
        self.application.processEvents()
        self.assertNotEqual(self.widget.currentTemperature_label.text(), "Unknown")

        self.widget.disconnect_pushButton.click()
        self.assertTrue(self.logic.wait(1000))
        self.application.processEvents()
        self.assertFalse(self.logic.is_connected)
        self.assertEqual(self.widget.connectionStatus_label.text(), "Disconnected")


if __name__ == "__main__":
    unittest.main()
