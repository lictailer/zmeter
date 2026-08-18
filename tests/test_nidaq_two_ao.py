from __future__ import annotations

import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6 import QtCore, QtWidgets


def _install_pydaqmx_import_stub():
    """Allow importing the legacy module without loading an NI driver."""
    pydaqmx = types.ModuleType("PyDAQmx")
    pydaqmx.Task = type("Task", (), {})
    sys.modules["PyDAQmx"] = pydaqmx


_install_pydaqmx_import_stub()

from nidaq import nidaq_logic, nidaq_main


class FakeDAQ:
    def __init__(self):
        self.setup_ao = []
        self.closed_ao = []
        self.setup_ai = []
        self.closed_ai = []
        self.counter_channels = []
        self.counter_close_count = 0

    def setup_single_AO_task(self, channel):
        self.setup_ao.append(channel)

    def close_single_AO_task(self, channel):
        self.closed_ao.append(channel)

    def setup_single_AI_task(self, channel):
        self.setup_ai.append(channel)

    def close_single_AI_task(self, channel):
        self.closed_ai.append(channel)

    def setup_sample_counter(self, chan):
        self.counter_channels.append(chan)

    def close_sample_counter(self):
        self.counter_close_count += 1


class FakeWidgetLogic(QtCore.QObject):
    sig_new_write = QtCore.pyqtSignal(object)
    sig_new_read = QtCore.pyqtSignal(object)
    sig_name = QtCore.pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.AO_channels = ["AO0", "AO1"]
        self.target_AO = {"AO0": 0.0, "AO1": 0.0}
        self.next_channel = "AO0"
        self.job = ""

    def wait(self):
        return True

    def setup_channel(self, channel):
        self.next_channel = channel

    def assign_AO_target(self, channel, value):
        self.target_AO[channel] = value

    def start(self):
        if self.job == "write_AO":
            channel_index = self.AO_channels.index(self.next_channel)
            self.sig_new_write.emit(
                [channel_index, self.target_AO[self.next_channel]]
            )

    def initialize(self, _device):
        pass

    def close(self):
        pass


class NIDAQTwoAOLogicTests(unittest.TestCase):
    def test_initialize_and_close_use_only_supported_outputs(self):
        with mock.patch.object(nidaq_logic, "NIDAQHardWare", FakeDAQ):
            logic = nidaq_logic.NIDAQLogic()

        logic.initialize("DevTest")

        self.assertEqual(logic.AO_channels, ["AO0", "AO1"])
        self.assertEqual(set(logic.target_AO), {"AO0", "AO1"})
        self.assertEqual(set(logic.hold_AO), {"AO0", "AO1"})
        self.assertEqual(logic.daq.setup_ao, ["/DevTest/AO0", "/DevTest/AO1"])
        self.assertEqual(logic.daq.counter_channels, ["/DevTest/Ctr0"])
        self.assertFalse(hasattr(logic, "emit_pulse"))
        self.assertFalse(hasattr(logic, "setup_wait_sec"))

        logic.close()

        self.assertEqual(logic.daq.closed_ao, ["/DevTest/AO0", "/DevTest/AO1"])
        self.assertEqual(logic.daq.counter_close_count, 1)


class NIDAQTwoAOInterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        patcher = mock.patch.object(nidaq_main, "NIDAQLogic", FakeWidgetLogic)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.widget = nidaq_main.NIDAQ()
        self.addCleanup(self.widget.close)

    def test_canonical_ui_contains_only_two_output_rows(self):
        ui_path = Path(nidaq_main.__file__).with_name("nidaq.ui")
        strings = {
            element.text
            for element in ElementTree.parse(ui_path).iter("string")
            if element.text
        }

        self.assertTrue(ui_path.is_file())
        self.assertFalse(ui_path.with_name("nidaq_new.ui").exists())
        self.assertIn("AO0", strings)
        self.assertIn("AO1", strings)
        self.assertNotIn("AO2", strings)
        self.assertNotIn("AO3", strings)
        self.assertIsNone(
            self.widget.findChild(QtWidgets.QDoubleSpinBox, "pos_to_go_doubleSpinBox_3")
        )
        self.assertIsNone(
            self.widget.findChild(QtWidgets.QDoubleSpinBox, "pos_to_go_doubleSpinBox_4")
        )

    def test_go_step_and_status_paths_work_for_both_outputs(self):
        targets = [
            self.widget.pos_to_go_doubleSpinBox,
            self.widget.pos_to_go_doubleSpinBox_2,
        ]
        steps = [self.widget.step_doubleSpinBox, self.widget.step_doubleSpinBox_2]
        labels = [self.widget.last_set_pos_label, self.widget.last_set_pos_label_2]

        for index, channel in enumerate(("AO0", "AO1")):
            targets[index].setValue(0.25 + index)
            self.widget.when_go_button_clicked(index)
            self.assertEqual(self.widget.logic.next_channel, channel)
            self.assertIn("last set to:", labels[index].text())

            steps[index].setValue(0.1)
            before_step = self.widget.logic.target_AO[channel]
            self.widget.when_pm_button_clicked(index, "p")
            self.assertAlmostEqual(
                self.widget.logic.target_AO[channel], before_step + 0.1
            )


if __name__ == "__main__":
    unittest.main()
