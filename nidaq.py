from PyQt6 import QtWidgets, uic, QtCore
import sys
from nidaq_logic import NIDAQLogic
import numpy as np
import pyqtgraph as pg


class NIDAQ(QtWidgets.QWidget):
    AI = ["AI0", "AI1", "AI2", "AI3", "AI4", "AI5", "AI6", "AI7"]

    def __init__(self):
        super(NIDAQ, self).__init__()
        uic.loadUi(r"ui\nidaq.ui", self)
        self.logic = NIDAQLogic()

        self.connect_sig_slot()
        self.read_log = {
            "AI0": np.zeros([300]),
            "AI1": np.zeros([300]),
            "AI2": np.zeros([300]),
            "AI3": np.zeros([300]),
            "AI4": np.zeros([300]),
            "AI5": np.zeros([300]),
            "AI6": np.zeros([300]),
            "AI7": np.zeros([300]),
            "count": np.zeros([300]),
        }

        self.inputMethod_comboBox.clear()
        for c in self.AI:
            self.inputMethod_comboBox.addItem(c)
        self.inputMethod_comboBox.addItem("Sample Counter")

    def connect(self, device=""):
        if device == "":
            device = self.dev_name_lineEdit.text()
        else:
            pass
        self.logic.initialize(device)

    def connect_sig_slot(self):
        self.set_button.clicked.connect(self.when_set_button_clicked)
        self.close_button.clicked.connect(self.when_close_button_clicked)
        self.go_button.clicked.connect(lambda: self.when_go_button_clicked(0))
        self.go_button_2.clicked.connect(lambda: self.when_go_button_clicked(1))
        self.minus_button.clicked.connect(lambda: self.when_pm_button_clicked(0, "m"))
        self.minus_button_2.clicked.connect(lambda: self.when_pm_button_clicked(1, "m"))
        self.plus_button.clicked.connect(lambda: self.when_pm_button_clicked(0, "p"))
        self.plus_button_2.clicked.connect(lambda: self.when_pm_button_clicked(1, "p"))

        self.logic.sig_name.connect(self.setup_name_label)
        self.logic.sig_new_read.connect(self.update_read_display)
        self.logic.sig_new_write.connect(self.update_AO_label)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.monitor)
        # self.timer.start(50)  # time in milliseconds.
        self.update_pushButton.clicked.connect(self.start_timer)
        self.stop_pushButton.clicked.connect(self.stop_timer)

    def when_set_button_clicked(self):
        name = self.dev_name_lineEdit.text()
        self.logic.initialize(name)

    def when_close_button_clicked(self):
        self.logic.close()

    def setup_name_label(self, name):
        self.name_label.setText(f"using {name}")

    def when_stop_clicked(self):
        self.logic.receieved_stop = True

    def when_update_clicked(self):
        pass

    def update_read_display(self, sig):
        channel, val = sig
        self.read_log[channel][0:-1] = self.read_log[channel][1:]
        self.read_log[channel][-1] = val
        pen1 = pg.mkPen((255, 255, 255), width=3)
        self.input1_PlotWidget.getPlotItem().plot(
            self.read_log[channel], clear=True, pen=pen1
        )
        
        if channel=='count':
            self.input1_label.setText(f"{val:,.1f}")
        else:
            self.input1_label.setText(f"{val:+.5f}")

    ######################################
    def update_AO_label(self, info):
        labels = [
            self.last_set_pos_label,
            self.last_set_pos_label_2,
            self.last_set_pos_label_3,
            self.last_set_pos_label_4,
        ]
        id, d = info
        labels[id].setText(f"last set to: {d:+.4f} V")

    def when_go_button_clicked(self, AO_index):
        self.logic.wait()

        val = [
            self.pos_to_go_doubleSpinBox,
            self.pos_to_go_doubleSpinBox_2,
            self.pos_to_go_doubleSpinBox_3,
            self.pos_to_go_doubleSpinBox_4,
        ][AO_index].value()
        ch = self.logic.AO_channels[AO_index]
        self.logic.setup_channel(ch)
        self.logic.assign_AO_target(ch, val)
        self.logic.job = "write_AO"
        self.logic.start()

    def when_pm_button_clicked(self, AO_index, fun):
        self.logic.wait()

        i = AO_index
        ch = self.logic.AO_channels[i]
        self.logic.setup_channel(ch)
        plus_minus_box = [
            self.step_doubleSpinBox,
            self.step_doubleSpinBox_2,
            self.step_doubleSpinBox_3,
            self.step_doubleSpinBox_4,
        ]
        if fun == "m":
            self.logic.assign_AO_target(
                ch, self.logic.target_AO[ch] - plus_minus_box[i].value()
            )
        elif fun == "p":
            self.logic.assign_AO_target(
                ch, self.logic.target_AO[ch] + plus_minus_box[i].value()
            )

        self.logic.job = "write_AO"
        self.logic.start()

    def set_AO0(self, val):
        self.logic.target_AO["AO0"] = val
        self.logic.job = "write_AO0"
        self.logic.start()

    def set_AO1(self, val):
        self.logic.target_AO["AO1"] = val
        self.logic.job = "write_AO1"
        self.logic.start()

    def monitor(self):
        if not self.logic.is_initialized:
            return
        if self.logic.isRunning():
            return

        c = self.inputMethod_comboBox.currentText()

        if c == "Sample Counter":
            self.logic.accumuate_time = self.time_doubleSpinBox.value()
            self.logic.job = "read_single_sample_count"
            self.logic.start()
        elif c in self.AI:
            self.logic.next_AI_channel = c
            self.logic.accumuate_time = self.time_doubleSpinBox.value()
            self.logic.set_accumulate_count_num()
            self.logic.job = "read_AI"
            self.logic.start()

    def start_timer(self):
        if not self.timer.isActive():
            self.timer.start(50)

    def stop_timer(self):
        if self.timer.isActive():
            self.timer.stop()
        # self.logic.receieved_stop = True

    # def closeEvent(self, event: QCloseEvent):
    #     self.logic.close()
    #     print("Nidaq terminated.")
    #     event.accept()  # Accept the event to close the window

    def terminate_dev(self):
        self.logic.close()

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = NIDAQ()
    window.logic.initialize("Dev1")
    center = [0.0, 0.0]
    window.pos_to_go_doubleSpinBox.setValue(center[0])
    window.pos_to_go_doubleSpinBox_2.setValue(center[1])

    window.show()
    app.exec()
