import sys
from typing import Dict, Optional

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets, uic

try:
    from .ni6423_logic import NI6423Logic
except ImportError:
    from ni6423_logic import NI6423Logic


class NI6423(QtWidgets.QWidget):
    AO_CHANNELS = [f"AO{i}" for i in range(4)]
    AI_CHANNELS = [f"AI{i}" for i in range(32)]
    COUNTER_CHANNELS = ["counter0"]
    MONITOR_PERIOD_MS = 50
    LOG_LENGTH = 300

    def __init__(self):
        super().__init__()
        uic.loadUi("ni6423/ni6423.ui", self)

        self.logic = NI6423Logic()

        self.monitor_mode: Optional[str] = None  # None, "ai", "counter"
        self.active_monitor_channel: Optional[str] = None
        self.scan_paused = False

        self._pen = pg.mkPen((255, 255, 255), width=3)
        self.read_log: Dict[str, np.ndarray] = {}
        for channel in self.AI_CHANNELS + self.COUNTER_CHANNELS:
            self.read_log[channel] = np.zeros((self.LOG_LENGTH,), dtype=float)

        self.ao_feedback_values: Dict[str, Optional[float]] = {
            channel: None for channel in self.AO_CHANNELS
        }

        self.ao_target_spinboxes = [
            self.AO0Target_doubleSpinBox,
            self.AO1Target_doubleSpinBox,
            self.AO2Target_doubleSpinBox,
            self.AO3Target_doubleSpinBox,
        ]
        self.ao_step_spinboxes = [
            self.AO0step_doubleSpinBox,
            self.AO1step_doubleSpinBox,
            self.AO2step_doubleSpinBox,
            self.AO3step_doubleSpinBox,
        ]
        self.ao_read_labels = [
            self.AO0read_label,
            self.AO1read_label,
            self.AO2read_label,
            self.AO3read_label,
        ]

        self.spinBox.setRange(0, 31)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.monitor)
        self.timer.setInterval(self.MONITOR_PERIOD_MS)

        self.connect_sig_slot()

    def connect(self, device=""):
        if device == "":
            device = self.dev_name_lineEdit.text().strip()
        else:
            self.dev_name_lineEdit.setText(device)
        self._connect_device(device)

    def connect_sig_slot(self):
        self.set_button.clicked.connect(self.when_set_button_clicked)
        self.close_button.clicked.connect(self.when_close_button_clicked)

        for index in range(4):
            getattr(self, f"setAO{index}_button").clicked.connect(
                lambda _checked=False, i=index: self.when_set_ao_clicked(i)
            )
            getattr(self, f"getAO{index}_button").clicked.connect(
                lambda _checked=False, i=index: self.when_get_ao_clicked(i)
            )
            getattr(self, f"AO{index}plus_button").clicked.connect(
                lambda _checked=False, i=index: self.when_pm_button_clicked(i, "p")
            )
            getattr(self, f"AO{index}minus_button").clicked.connect(
                lambda _checked=False, i=index: self.when_pm_button_clicked(i, "m")
            )

        self.startAO_pushButton.clicked.connect(self.start_ai_monitor)
        self.startCounter_pushButton.clicked.connect(self.start_counter_monitor)
        self.stop_pushButton.clicked.connect(self.stop_monitor)

        self.spinBox.editingFinished.connect(self.when_ai_index_changed)
        self.setIntegrateTime_button.clicked.connect(self.when_set_integrate_time_clicked)

        self.logic.sig_name.connect(self.setup_name_label)
        self.logic.sig_connected.connect(self.update_connection_label)
        self.logic.sig_new_write.connect(self.update_write_display)
        self.logic.sig_new_read.connect(self.update_read_display)
        self.logic.sig_error.connect(self.update_error_label)

    # ------------------------ connection -------------------------
    def _connect_device(self, name: str):
        if not name:
            self.status_label.setText("OFF (empty device name)")
            return
        try:
            self.logic.initialize(name)
            self.when_set_integrate_time_clicked()
            self.logic.request_all_ao_feedback_async()
            if self.monitor_mode is not None and not self.scan_paused:
                self.start_timer()
        except Exception as exc:
            self.status_label.setText(f"OFF ({exc})")

    def when_set_button_clicked(self):
        self._connect_device(self.dev_name_lineEdit.text().strip())

    def when_close_button_clicked(self):
        self.stop_monitor()
        self.logic.close()

    def setup_name_label(self, name):
        if name == "None":
            self.status_label.setText("OFF")
        else:
            self.status_label.setText(f"ON ({name})")

    def update_connection_label(self, connected):
        if not connected:
            self.status_label.setText("OFF")
        elif self.logic.dev_name:
            self.status_label.setText(f"ON ({self.logic.dev_name})")
        else:
            self.status_label.setText("ON")

    def update_error_label(self, msg):
        self.status_label.setText(f"ERR: {msg}")

    # ---------------------- integration time ---------------------
    def when_set_integrate_time_clicked(self):
        if not self.logic.is_initialized:
            return
        try:
            ao_time = float(self.AOIntgratingTime_doubleSpinBox.value())
            counter_time = float(self.counterIntgratingTime_doubleSpinBox.value())
            self.logic.update_ao_integrating_time(ao_time)
            self.logic.update_counter_integrating_time(counter_time)
        except Exception as exc:
            self.status_label.setText(f"ERR: {exc}")

    # --------------------------- AO ------------------------------
    def _set_ao(self, ao_index: int, value: Optional[float] = None):
        if not self.logic.is_initialized:
            return

        ao_channel = f"AO{ao_index}"
        if value is None:
            value = float(self.ao_target_spinboxes[ao_index].value())
        else:
            self.ao_target_spinboxes[ao_index].setValue(float(value))
            value = float(self.ao_target_spinboxes[ao_index].value())  # clamped by UI

        self.logic.update_ao_target(ao_channel, value)
        self.logic.update_next_ao_channel(ao_channel)

        if self.logic.isRunning():
            self.logic.wait(1000)
        self.logic.job = "write_AO"
        self.logic.start()

    def when_set_ao_clicked(self, ao_index: int):
        self._set_ao(ao_index)

    def when_get_ao_clicked(self, ao_index: int):
        if not self.logic.is_initialized:
            return

        ao_channel = f"AO{ao_index}"
        if self.logic.isRunning():
            self.logic.request_ao_feedback_async(ao_channel)
            return

        self.logic.update_next_feedback_ao_channel(ao_channel)
        self.logic.job = "read_AO_feedback"
        self.logic.start()

    def when_pm_button_clicked(self, ao_index: int, fun: str):
        if not self.logic.is_initialized:
            return

        ao_channel = f"AO{ao_index}"
        step = float(self.ao_step_spinboxes[ao_index].value())
        cached_val = self.ao_feedback_values.get(ao_channel)
        if cached_val is None:
            cached_val = self.logic.target_AO.get(
                ao_channel, float(self.ao_target_spinboxes[ao_index].value())
            )

        if fun == "p":
            target = float(cached_val) + step
        else:
            target = float(cached_val) - step

        self._set_ao(ao_index, target)

    # ------------------------ monitoring -------------------------
    def start_ai_monitor(self):
        if not self.logic.is_initialized:
            return
        ai_index = int(self.spinBox.value())
        channel = f"AI{ai_index}"
        self.logic.update_next_ai_channel(channel)
        self.monitor_mode = "ai"
        self.active_monitor_channel = channel
        self._plot_channel(channel)
        self.start_timer()

    def start_counter_monitor(self):
        if not self.logic.is_initialized:
            return
        channel = "counter0"
        self.logic.update_next_counter_channel("Ctr0")
        self.monitor_mode = "counter"
        self.active_monitor_channel = channel
        self._plot_channel(channel)
        self.start_timer()

    def stop_monitor(self):
        self.monitor_mode = None
        self.active_monitor_channel = None
        self.stop_timer()

    def when_ai_index_changed(self):
        if self.monitor_mode != "ai" or not self.logic.is_initialized:
            return
        self.start_ai_monitor()

    def start_timer(self):
        if self.scan_paused:
            return
        if not self.timer.isActive():
            self.timer.start()

    def stop_timer(self):
        if self.timer.isActive():
            self.timer.stop()

    def monitor(self):
        if not self.logic.is_initialized or self.scan_paused:
            return
        if self.logic.isRunning():
            return

        if self.monitor_mode == "ai":
            self.logic.job = "read_AI"
            self.logic.start()
        elif self.monitor_mode == "counter":
            self.logic.job = "read_counter"
            self.logic.start()

    # ------------------------- updates ---------------------------
    def update_write_display(self, info):
        channel, value = info
        if channel in self.AO_CHANNELS:
            ao_index = int(channel.replace("AO", ""))
            self.ao_target_spinboxes[ao_index].setValue(float(value))

    def update_read_display(self, sig):
        channel, value = sig
        value = float(value)

        if channel in self.AO_CHANNELS:
            ao_index = int(channel.replace("AO", ""))
            self.ao_feedback_values[channel] = value
            self.ao_read_labels[ao_index].setText(f"{value:+.5f} V")
            return

        if channel not in self.read_log:
            self.read_log[channel] = np.zeros((self.LOG_LENGTH,), dtype=float)
        self.read_log[channel][0:-1] = self.read_log[channel][1:]
        self.read_log[channel][-1] = value

        if channel == self.active_monitor_channel:
            self._plot_channel(channel)
            if channel.startswith("counter"):
                self.currentread_label.setText(f"{value:,.5f}")
            else:
                self.currentread_label.setText(f"{value:+.5f}")

    def _plot_channel(self, channel: str):
        if channel not in self.read_log:
            self.read_log[channel] = np.zeros((self.LOG_LENGTH,), dtype=float)
        self.currentread_PlotWidget.getPlotItem().plot(
            self.read_log[channel], clear=True, pen=self._pen
        )

    # ---------------------- scan lifecycle -----------------------
    def stop_scan(self):
        self.scan_paused = True
        self.stop_timer()

    def start_scan(self):
        self.scan_paused = False
        if self.monitor_mode is not None and self.logic.is_initialized:
            self.start_timer()

    def terminate_dev(self):
        self.stop_monitor()
        self.logic.close()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = NI6423()
    window.show()
    app.exec()
