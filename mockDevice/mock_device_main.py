from __future__ import annotations

from pathlib import Path

from PyQt6 import QtCore, QtWidgets, uic

from .mock_device_logic import MockDeviceLogic


class MockDevice(QtWidgets.QWidget):
    """Qt widget exposing the fully simulated instrument."""

    def __init__(self, logic: MockDeviceLogic | None = None):
        super().__init__()
        uic.loadUi(Path(__file__).with_name("mock_device.ui"), self)
        self.logic = logic or MockDeviceLogic()
        self._connect_signals()
        self._update_connected((False, ""))
        self._update_ramp_active(False)

    # MainWindow lifecycle API.
    def connect(self, address: str = "MOCK::INSTR") -> str:
        return self.logic.connect_device(address)

    def disconnect(self) -> None:
        self.logic.disconnect_device()

    def start_scan(self) -> None:
        self.logic.start_scan()

    def stop_scan(self) -> None:
        self.logic.stop_scan()

    def force_stop(self) -> bool:
        return self.logic.force_stop()

    def terminate_dev(self) -> None:
        self.logic.close()

    def _connect_signals(self) -> None:
        self.connect_pushButton.clicked.connect(
            lambda: self.logic.start_job("connect", self.address_lineEdit.text())
        )
        self.disconnect_pushButton.clicked.connect(
            lambda: self.logic.start_job("disconnect")
        )

        self.channel_A_set_pushButton.clicked.connect(
            lambda: self.logic.start_job("set_A", self.channel_A_set_doubleSpinBox.value())
        )
        self.channel_B_set_pushButton.clicked.connect(
            lambda: self.logic.start_job("set_B", self.channel_B_set_doubleSpinBox.value())
        )
        self.channel_A_read_pushButton.clicked.connect(
            lambda: self.logic.start_job("read_A")
        )
        self.channel_B_read_pushButton.clicked.connect(
            lambda: self.logic.start_job("read_B")
        )
        self.random_read_pushButton.clicked.connect(
            lambda: self.logic.start_job("read_random")
        )
        self.channel_A_ramp_pushButton.clicked.connect(
            lambda: self.logic.start_job("ramp_A", self.channel_A_set_doubleSpinBox.value())
        )
        self.channel_B_ramp_pushButton.clicked.connect(
            lambda: self.logic.start_job("ramp_B", self.channel_B_set_doubleSpinBox.value())
        )
        self.ramp_stop_pushButton.clicked.connect(self.logic.force_stop)
        self.reset_pushButton.clicked.connect(lambda: self.logic.start_job("reset"))

        self.fail_after_activate_pushButton.clicked.connect(
            lambda: self._set_fault(
                "fail_after_on", self.fail_after_spinBox.value(), self.fail_after_status_label
            )
        )
        self.fail_after_stop_pushButton.clicked.connect(
            lambda: self._stop_fault("fail_after_off", self.fail_after_status_label)
        )
        self.random_failure_activate_pushButton.clicked.connect(
            lambda: self._set_fault(
                "random_fail_on",
                self.random_failure_doubleSpinBox.value(),
                self.random_failure_status_label,
            )
        )
        self.random_failure_stop_pushButton.clicked.connect(
            lambda: self._stop_fault(
                "random_fail_off", self.random_failure_status_label
            )
        )
        self.range_rejection_activate_pushButton.clicked.connect(
            lambda: self._set_fault(
                "range_on", None, self.range_rejection_status_label
            )
        )
        self.range_rejection_stop_pushButton.clicked.connect(
            lambda: self._stop_fault("range_off", self.range_rejection_status_label)
        )

        self.logic.sig_connected.connect(self._update_connected)
        self.logic.sig_status.connect(self.status_label.setText)
        self.logic.sig_error.connect(self.status_label.setText)
        self.logic.sig_last_set_A.connect(
            lambda value: self._set_value_label(self.last_set_A_label, value)
        )
        self.logic.sig_last_set_B.connect(
            lambda value: self._set_value_label(self.last_set_B_label, value)
        )
        self.logic.sig_last_read_A.connect(
            lambda value: self._set_value_label(self.last_read_A_label, value)
        )
        self.logic.sig_last_read_B.connect(
            lambda value: self._set_value_label(self.last_read_B_label, value)
        )
        self.logic.sig_random.connect(
            lambda value: self._set_value_label(self.random_value_label, value)
        )
        self.logic.sig_ramp_active.connect(self._update_ramp_active)
        self.logic.sig_log_updated.connect(self._update_command_log)
        self.logic.sig_reset_completed.connect(self._reset_fault_labels)
        self.logic.sig_fail_after_triggered.connect(
            lambda: self.fail_after_status_label.setText("Off")
        )

    def _set_fault(
        self,
        job_name: str,
        value: float | int | None,
        status_label: QtWidgets.QLabel,
    ) -> None:
        if self.logic.start_job(job_name, value):
            status_label.setText("On")

    def _stop_fault(self, job_name: str, status_label: QtWidgets.QLabel) -> None:
        if self.logic.start_job(job_name):
            status_label.setText("Off")

    @QtCore.pyqtSlot(object)
    def _update_connected(self, payload: object) -> None:
        connected, address = payload
        self.connection_label.setText(
            f"Connected: {address}" if connected else "Disconnected"
        )
        self.connect_pushButton.setEnabled(not connected)
        self.disconnect_pushButton.setEnabled(connected)

    @QtCore.pyqtSlot(bool)
    def _update_ramp_active(self, active: bool) -> None:
        self.ramp_stop_pushButton.setEnabled(active)

    @QtCore.pyqtSlot(object)
    def _update_command_log(self, entries: object) -> None:
        self.command_log_plainTextEdit.setPlainText("\n".join(entries))
        scroll_bar = self.command_log_plainTextEdit.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    @QtCore.pyqtSlot()
    def _reset_fault_labels(self) -> None:
        self.fail_after_status_label.setText("Off")
        self.random_failure_status_label.setText("Off")
        self.range_rejection_status_label.setText("Off")

    @staticmethod
    def _set_value_label(label: QtWidgets.QLabel, value: object) -> None:
        label.setText("--" if value is None else f"{float(value):.9g}")
