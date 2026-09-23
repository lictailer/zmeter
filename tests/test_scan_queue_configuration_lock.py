import copy
import os
import unittest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtWidgets

from core.scan import Scan
from core.scan_info import ScanInfo


class ScanQueueConfigurationLockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.scan = Scan(
            name="queue lock probe",
            info=copy.deepcopy(ScanInfo),
            setter_equipment_info={},
            getter_equipment_info={},
            main_window=None,
        )

    def tearDown(self):
        self.scan.close()
        self.scan.deleteLater()
        self.app.processEvents()

    def _configuration_widgets(self):
        return (
            self.scan.lineEdit,
            self.scan.comments_textEdit,
            self.scan.PlotsPerPage,
            self.scan.all_level_setting,
            self.scan.all_plot_setting,
            self.scan.load_button,
            self.scan.save_button,
            self.scan.scan_button,
            self.scan.scan_button_1,
            self.scan.scan_button_2,
            self.scan.scan_button_3,
        )

    def _runtime_widgets(self):
        return (
            self.scan.stop_button,
            self.scan.stop_button_1,
            self.scan.stop_button_2,
            self.scan.stop_button_3,
            self.scan.pause_button_1,
            self.scan.pause_button_2,
            self.scan.pause_button_3,
            self.scan.resume_button_1,
            self.scan.resume_button_2,
            self.scan.resume_button_3,
            self.scan.update_plots_button_1,
            self.scan.update_plots_button_2,
            self.scan.update_plots_button_3,
            self.scan.save_plots_button_1,
            self.scan.save_plots_button_2,
            self.scan.save_plots_button_3,
            *self.scan.graphing_plots,
        )

    def test_lock_disables_configuration_but_leaves_runtime_controls_enabled(self):
        runtime_states = tuple(
            (widget, widget.isEnabled()) for widget in self._runtime_widgets()
        )

        self.scan.set_queue_configuration_locked(True)

        self.assertTrue(self.scan._queue_configuration_locked)
        self.assertTrue(
            all(not widget.isEnabled() for widget in self._configuration_widgets())
        )
        self.assertEqual(
            tuple((widget, widget.isEnabled()) for widget, _enabled in runtime_states),
            runtime_states,
        )

        self.scan.set_queue_configuration_locked(False)

        self.assertFalse(self.scan._queue_configuration_locked)
        self.assertTrue(all(widget.isEnabled() for widget in self._configuration_widgets()))

    def test_lock_is_idempotent_and_restores_each_prior_enabled_state(self):
        self.scan.save_button.setEnabled(False)
        self.scan.scan_button_2.setEnabled(False)
        expected_states = tuple(
            (widget, widget.isEnabled()) for widget in self._configuration_widgets()
        )

        self.scan.set_queue_configuration_locked(True)
        self.scan.set_queue_configuration_locked(True)
        self.assertTrue(
            all(not widget.isEnabled() for widget in self._configuration_widgets())
        )

        self.scan.set_queue_configuration_locked(False)
        self.assertEqual(
            tuple((widget, widget.isEnabled()) for widget, _enabled in expected_states),
            expected_states,
        )

        self.scan.load_button.setEnabled(False)
        self.scan.set_queue_configuration_locked(False)
        self.assertFalse(self.scan.load_button.isEnabled())

    def test_unlock_does_not_reenable_a_scan_disabled_by_an_outer_seal(self):
        self.scan.set_queue_configuration_locked(True)
        self.scan.setEnabled(False)

        self.scan.set_queue_configuration_locked(False)

        self.assertFalse(self.scan.isEnabled())
        self.assertTrue(
            all(not widget.isEnabled() for widget in self._configuration_widgets())
        )

        self.scan.setEnabled(True)
        self.assertTrue(all(widget.isEnabled() for widget in self._configuration_widgets()))

    def test_lock_during_an_outer_seal_does_not_make_that_seal_permanent(self):
        self.scan.setEnabled(False)

        self.scan.set_queue_configuration_locked(True)
        self.scan.set_queue_configuration_locked(False)

        self.assertFalse(self.scan.isEnabled())
        self.assertTrue(
            all(not widget.isEnabled() for widget in self._configuration_widgets())
        )

        self.scan.setEnabled(True)
        self.assertTrue(all(widget.isEnabled() for widget in self._configuration_widgets()))

    def test_scan_and_queue_locks_release_independently(self):
        self.scan._set_scan_configuration_locked(True)
        self.scan.set_queue_configuration_locked(True)

        self.scan._set_scan_configuration_locked(False)
        self.assertTrue(
            all(not widget.isEnabled() for widget in self._configuration_widgets())
        )

        self.scan.set_queue_configuration_locked(False)
        self.assertTrue(all(widget.isEnabled() for widget in self._configuration_widgets()))


if __name__ == "__main__":
    unittest.main()
