from pathlib import Path

from PyQt6 import QtWidgets, uic, QtCore
import sys
from .tlpm_logic import TLPMLogic
import numpy as np
import pyqtgraph as pg


class TLPM(QtWidgets.QWidget):
    TERMINATION_TIMEOUT_MS = 10_000
    SCAN_QUIESCE_TIMEOUT_MS = 10_000

    def __init__(self):
        super(TLPM, self).__init__()
        uic.loadUi(str(Path(__file__).with_name("tlpm.ui")), self)
        self.logic = TLPMLogic()
        self._scan_active = False
        self._monitor_requested = False
        self._scan_monitor_was_active = False
        self._scan_monitor_frequency = None
        self.connect_sig_slot()
        self.power_log = np.zeros(1000)

    def connect_sig_slot(self):
        self.connect_button.clicked.connect(self.connect)
        self.disconnect_button.clicked.connect(self.disconnect)
        self.set_button.clicked.connect(self.set_wavelength)
        self.update_button.clicked.connect(self.read_indef)
        self.stop_button.clicked.connect(self.stop_indef)
        self.logic.sig_power.connect(self.update_power)
        self.logic.sig_info.connect(self.update_info)
        self.logic.sig_connect.connect(self.update_on_off)

    def update_on_off(self, status):
        if status:
            self.label_on_off.setText("ON")
        else:
            self.label_on_off.setText("OFF")

    def update_power(self, power):
        self.power_log[0:-1] = self.power_log[1:]
        self.power_log[-1] = power
        pen1 = pg.mkPen((255, 255, 255), width=3)
        self.input1_PlotWidget.getPlotItem().plot(self.power_log, clear=True, pen=pen1)

        units = ['pw', 'nW', 'uW', 'mW', 'W']
        lv = 3
        if 1e-12 < power and power <= 1e-9:
            power = power*1e12
            lv = 0
        elif 1e-9 < power and power <= 1e-6:
            power = power*1e9
            lv = 1
        elif 1e-6 < power and power <= 1e-3:
            power = power*1e6
            lv = 2
        elif 1e-3 < power and power <= 1e0:
            power = power*1e3
            lv = 3
        self.input1_label.setText(f"{power:.2f} {units[lv]}")

    def update_info(self, info):
        self.info_label.setText(info)

    # actions
    def _start_logic_job(self, flag_name):
        if getattr(self, "_scan_active", False):
            self.update_info("TLPM UI jobs are paused while a scan owns the device.")
            return False
        if self.logic.isRunning():
            self.update_info("TLPM is busy. Try again after the current job finishes.")
            return False
        setattr(self.logic, flag_name, True)
        self.logic.start()
        return True

    def connect(self):
        return self._start_logic_job("do_connect")

    def disconnect(self):
        if self.logic.is_connected is True:
            return self._start_logic_job("do_disconnect")
        return True

    def set_wavelength(self):
        pos = self.nm_to_go_doubleSpinBox.value()
        self.logic.set_wavelength_target(pos)
        return self._start_logic_job("do_change_wavelength")

    def read_power(self):
        return self._start_logic_job("do_read_power")

    def read_indef(self):
        self.logic.freq = self.freq_doubleSpinBox.value()
        started = self._start_logic_job("do_read_indefinitely")
        if started:
            self._monitor_requested = True
        return started

    def stop_indef(self):
        self._monitor_requested = False
        self.logic.request_stop()

    def force_stop(self):
        self.logic.request_stop()
        if not self._scan_active:
            self._monitor_requested = False
        return True

    def stop_scan(self):
        if QtCore.QThread.currentThread() != self.thread():
            QtCore.QMetaObject.invokeMethod(
                self,
                "_stop_scan_on_owner",
                QtCore.Qt.ConnectionType.BlockingQueuedConnection,
            )
        else:
            self._stop_scan_on_owner()
        return self.logic.prepare_scan(self.SCAN_QUIESCE_TIMEOUT_MS)

    @QtCore.pyqtSlot()
    def _stop_scan_on_owner(self):
        if self._scan_active:
            return
        self._scan_monitor_was_active = (
            self._monitor_requested
            and self.logic.isRunning()
            and self.logic.do_read_indefinitely
        )
        self._scan_monitor_frequency = float(self.logic.freq)
        self._scan_active = True
        self.logic.scan_admission_closed = True
        self.logic.request_stop()

    def start_scan(self):
        self.logic.resume_scan()
        if QtCore.QThread.currentThread() != self.thread():
            QtCore.QMetaObject.invokeMethod(
                self,
                "_start_scan_on_owner",
                QtCore.Qt.ConnectionType.BlockingQueuedConnection,
            )
        else:
            self._start_scan_on_owner()
        return True

    @QtCore.pyqtSlot()
    def _start_scan_on_owner(self):
        if not self._scan_active:
            return
        should_resume = self._scan_monitor_was_active and self.logic.is_connected
        resume_frequency = self._scan_monitor_frequency
        self._scan_active = False
        self._scan_monitor_was_active = False
        self._scan_monitor_frequency = None
        self._monitor_requested = False
        if should_resume:
            if resume_frequency is not None:
                self.freq_doubleSpinBox.setValue(resume_frequency)
            self.read_indef()

    def terminate_dev(self):
        print("TLPM terminated.")
        self.logic.request_stop()
        if self.logic.isRunning() and not self.logic.wait(
            self.TERMINATION_TIMEOUT_MS
        ):
            return False
        if self.logic.is_connected:
            self.logic.disconnect()
        return not self.logic.isRunning() and not self.logic.is_connected


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = TLPM()
    window.show()
    app.exec()
