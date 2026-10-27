from __future__ import annotations

from PyQt6 import QtCore, QtWidgets

from core.device_log import append_device_log, configure_device_log

from .attodry_logic import AttoDryLogic, StabilitySettings


class AttoDry(QtWidgets.QWidget):
    """Operator panel for sample temperature and Z-field control."""

    TERMINATION_TIMEOUT_MS = 15_000
    LIVE_INTERVAL_MS = 1_000

    def __init__(self, logic: AttoDryLogic | None = None) -> None:
        super().__init__()
        self.logic = logic or AttoDryLogic()
        self.setWindowTitle("attoDRY2100")
        self._build_ui()
        self._connect_signals()
        self._set_connected(False, "")
        self._set_waiting(False, "")

        self._live_timer = QtCore.QTimer(self)
        self._live_timer.setInterval(self.LIVE_INTERVAL_MS)
        self._live_timer.timeout.connect(self._schedule_live_read)
        self._live_timer.start()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        connection_row = QtWidgets.QHBoxLayout()
        connection_row.addWidget(QtWidgets.QLabel("Controller address"))
        self.address_lineEdit = QtWidgets.QLineEdit()
        self.address_lineEdit.setPlaceholderText("REPLACE_WITH_ATTODRY_ADDRESS")
        connection_row.addWidget(self.address_lineEdit, 1)
        self.connect_pushButton = QtWidgets.QPushButton("Connect")
        self.disconnect_pushButton = QtWidgets.QPushButton("Disconnect")
        connection_row.addWidget(self.connect_pushButton)
        connection_row.addWidget(self.disconnect_pushButton)
        layout.addLayout(connection_row)

        self.connection_label = QtWidgets.QLabel("Disconnected")
        layout.addWidget(self.connection_label)

        readings = QtWidgets.QFormLayout()
        self.temperature_reading_label = QtWidgets.QLabel("-- K")
        self.field_reading_label = QtWidgets.QLabel("-- T")
        self.field_state_label = QtWidgets.QLabel("--")
        readings.addRow("Sample temperature", self.temperature_reading_label)
        readings.addRow("Magnetic field", self.field_reading_label)
        readings.addRow("Magnet state", self.field_state_label)
        layout.addLayout(readings)

        controls = QtWidgets.QGridLayout()
        self.temperature_spinBox = QtWidgets.QDoubleSpinBox()
        self.temperature_spinBox.setRange(1.8, 300.0)
        self.temperature_spinBox.setDecimals(4)
        self.temperature_spinBox.setSuffix(" K")
        self.temperature_spinBox.setValue(300.0)
        self.set_T_pushButton = QtWidgets.QPushButton("Set T")
        self.set_T_stable_pushButton = QtWidgets.QPushButton("Set T and wait stable")

        self.temperature_tolerance_spinBox = self._make_double_setting(
            minimum=self.logic.MIN_TEMPERATURE_TOLERANCE_K,
            maximum=self.logic.MAX_TEMPERATURE_TOLERANCE_K,
            decimals=3,
            step=0.01,
            suffix=" K",
            value=self.logic.temperature_stability.tolerance,
            tooltip=(
                "Allowed absolute temperature error for set_T_stable. "
                "Applies to the next wait only."
            ),
        )
        self.temperature_stable_samples_spinBox = self._make_sample_setting(
            self.logic.temperature_stability.stable_samples,
            "Required consecutive in-tolerance temperature readings.",
        )
        self.temperature_poll_interval_spinBox = self._make_double_setting(
            minimum=self.logic.MIN_POLL_INTERVAL_S,
            maximum=self.logic.MAX_POLL_INTERVAL_S,
            decimals=1,
            step=0.5,
            suffix=" s",
            value=self.logic.temperature_stability.poll_interval_s,
            tooltip="Seconds between temperature stability readings.",
        )

        self.field_spinBox = QtWidgets.QDoubleSpinBox()
        self.field_spinBox.setRange(-9.0, 9.0)
        self.field_spinBox.setDecimals(6)
        self.field_spinBox.setSuffix(" T")
        self.set_B_pushButton = QtWidgets.QPushButton("Set B")
        self.set_B_stable_pushButton = QtWidgets.QPushButton("Set B and wait stable")

        self.field_tolerance_spinBox = self._make_double_setting(
            minimum=self.logic.MIN_FIELD_TOLERANCE_T,
            maximum=self.logic.MAX_FIELD_TOLERANCE_T,
            decimals=5,
            step=0.001,
            suffix=" T",
            value=self.logic.field_stability.tolerance,
            tooltip=(
                "Allowed absolute field error for set_B_stable. The controller's "
                "field-control sequence must also finish."
            ),
        )
        self.field_stable_samples_spinBox = self._make_sample_setting(
            self.logic.field_stability.stable_samples,
            "Required consecutive in-tolerance magnetic-field readings.",
        )
        self.field_poll_interval_spinBox = self._make_double_setting(
            minimum=self.logic.MIN_POLL_INTERVAL_S,
            maximum=self.logic.MAX_POLL_INTERVAL_S,
            decimals=1,
            step=0.5,
            suffix=" s",
            value=self.logic.field_stability.poll_interval_s,
            tooltip="Seconds between magnetic-field stability readings.",
        )

        controls.addWidget(QtWidgets.QLabel("Temperature target"), 0, 0)
        controls.addWidget(self.temperature_spinBox, 0, 1)
        controls.addWidget(self.set_T_pushButton, 0, 2)
        controls.addWidget(self.set_T_stable_pushButton, 0, 3, 1, 3)
        controls.addWidget(QtWidgets.QLabel("T stability (±)"), 1, 0)
        controls.addWidget(self.temperature_tolerance_spinBox, 1, 1)
        controls.addWidget(QtWidgets.QLabel("Readings"), 1, 2)
        controls.addWidget(self.temperature_stable_samples_spinBox, 1, 3)
        controls.addWidget(QtWidgets.QLabel("Interval"), 1, 4)
        controls.addWidget(self.temperature_poll_interval_spinBox, 1, 5)

        controls.addWidget(QtWidgets.QLabel("Field target"), 2, 0)
        controls.addWidget(self.field_spinBox, 2, 1)
        controls.addWidget(self.set_B_pushButton, 2, 2)
        controls.addWidget(self.set_B_stable_pushButton, 2, 3, 1, 3)
        controls.addWidget(QtWidgets.QLabel("B stability (±)"), 3, 0)
        controls.addWidget(self.field_tolerance_spinBox, 3, 1)
        controls.addWidget(QtWidgets.QLabel("Readings"), 3, 2)
        controls.addWidget(self.field_stable_samples_spinBox, 3, 3)
        controls.addWidget(QtWidgets.QLabel("Interval"), 3, 4)
        controls.addWidget(self.field_poll_interval_spinBox, 3, 5)
        layout.addLayout(controls)

        action_row = QtWidgets.QHBoxLayout()
        self.live_checkBox = QtWidgets.QCheckBox("Live readings")
        self.live_checkBox.setChecked(True)
        self.read_now_pushButton = QtWidgets.QPushButton("Read now")
        self.stop_wait_pushButton = QtWidgets.QPushButton("Stop stable wait")
        action_row.addWidget(self.live_checkBox)
        action_row.addWidget(self.read_now_pushButton)
        action_row.addWidget(self.stop_wait_pushButton)
        action_row.addStretch(1)
        layout.addLayout(action_row)

        self.log_plainTextEdit = QtWidgets.QPlainTextEdit()
        configure_device_log(self.log_plainTextEdit)
        layout.addWidget(self.log_plainTextEdit)

    def _connect_signals(self) -> None:
        self.connect_pushButton.clicked.connect(
            lambda: self._start_job("connect", self.address_lineEdit.text())
        )
        self.disconnect_pushButton.clicked.connect(
            lambda: self._start_job("disconnect")
        )
        self.read_now_pushButton.clicked.connect(
            lambda: self._start_job("read_live")
        )
        self.set_T_pushButton.clicked.connect(
            lambda: self._start_job("set_T", self.temperature_spinBox.value())
        )
        self.set_T_stable_pushButton.clicked.connect(
            lambda: self._start_job(
                "set_T_stable", self.temperature_spinBox.value()
            )
        )
        self.temperature_tolerance_spinBox.editingFinished.connect(
            self._configure_temperature_stability
        )
        self.temperature_stable_samples_spinBox.editingFinished.connect(
            self._configure_temperature_stability
        )
        self.temperature_poll_interval_spinBox.editingFinished.connect(
            self._configure_temperature_stability
        )
        self.set_B_pushButton.clicked.connect(
            lambda: self._start_job("set_B", self.field_spinBox.value())
        )
        self.set_B_stable_pushButton.clicked.connect(
            lambda: self._start_job("set_B_stable", self.field_spinBox.value())
        )
        self.field_tolerance_spinBox.editingFinished.connect(
            self._configure_field_stability
        )
        self.field_stable_samples_spinBox.editingFinished.connect(
            self._configure_field_stability
        )
        self.field_poll_interval_spinBox.editingFinished.connect(
            self._configure_field_stability
        )
        self.stop_wait_pushButton.clicked.connect(self.force_stop)
        self.live_checkBox.toggled.connect(self._set_live_enabled)

        self.logic.sig_connected.connect(self._set_connected)
        self.logic.sig_temperature.connect(
            lambda value: self.temperature_reading_label.setText(f"{value:.6g} K")
        )
        self.logic.sig_field.connect(
            lambda value: self.field_reading_label.setText(f"{value:.7g} T")
        )
        self.logic.sig_field_state.connect(self.field_state_label.setText)
        self.logic.sig_status.connect(lambda message: self._log("info", message))
        self.logic.sig_error.connect(lambda message: self._log("error", message))
        self.logic.sig_waiting.connect(self._set_waiting)

    def _start_job(self, job_name: str, value: object = None) -> bool:
        if job_name != "connect" and not self.logic.is_connected:
            self._log("warning", "attoDRY is not connected")
            return False
        accepted = self.logic.start_job(job_name, value)
        if not accepted and job_name != "read_live":
            self._log("warning", "attoDRY is busy")
        return accepted

    def _start_logic_job(self, job_name: str) -> bool:
        """Registration-compatible entry point for asynchronous startup."""

        value = self.address_lineEdit.text() if job_name == "connect" else None
        return self._start_job(job_name, value)

    def _schedule_live_read(self) -> None:
        if (
            self.live_checkBox.isChecked()
            and self.logic.monitor_enabled
            and self.logic.is_connected
        ):
            self.logic.start_job("read_live")

    def _configure_temperature_stability(self) -> None:
        try:
            accepted = self.logic.configure_temperature_stability(
                self.temperature_tolerance_spinBox.value(),
                self.temperature_stable_samples_spinBox.value(),
                self.temperature_poll_interval_spinBox.value(),
            )
        except (TypeError, ValueError) as exc:
            self._log("error", exc)
            self._show_temperature_stability(self.logic.temperature_stability)
            return
        self._show_temperature_stability(accepted)

    def _configure_field_stability(self) -> None:
        try:
            accepted = self.logic.configure_field_stability(
                self.field_tolerance_spinBox.value(),
                self.field_stable_samples_spinBox.value(),
                self.field_poll_interval_spinBox.value(),
            )
        except (TypeError, ValueError) as exc:
            self._log("error", exc)
            self._show_field_stability(self.logic.field_stability)
            return
        self._show_field_stability(accepted)

    def _show_temperature_stability(self, settings: StabilitySettings) -> None:
        self.temperature_tolerance_spinBox.setValue(settings.tolerance)
        self.temperature_stable_samples_spinBox.setValue(settings.stable_samples)
        self.temperature_poll_interval_spinBox.setValue(settings.poll_interval_s)

    def _show_field_stability(self, settings: StabilitySettings) -> None:
        self.field_tolerance_spinBox.setValue(settings.tolerance)
        self.field_stable_samples_spinBox.setValue(settings.stable_samples)
        self.field_poll_interval_spinBox.setValue(settings.poll_interval_s)

    @QtCore.pyqtSlot(bool)
    def _set_live_enabled(self, enabled: bool) -> None:
        self.logic.monitor_enabled = bool(enabled)

    @QtCore.pyqtSlot(bool, str)
    def _set_connected(self, connected: bool, address: str) -> None:
        self.connection_label.setText(
            f"Connected: {address}" if connected else "Disconnected"
        )
        self.connect_pushButton.setEnabled(not connected)
        self.disconnect_pushButton.setEnabled(connected)

    @QtCore.pyqtSlot(bool, str)
    def _set_waiting(self, waiting: bool, quantity: str) -> None:
        self.stop_wait_pushButton.setEnabled(waiting)
        if quantity == "temperature":
            for control in (
                self.temperature_tolerance_spinBox,
                self.temperature_stable_samples_spinBox,
                self.temperature_poll_interval_spinBox,
            ):
                control.setEnabled(not waiting)
        elif quantity == "field":
            for control in (
                self.field_tolerance_spinBox,
                self.field_stable_samples_spinBox,
                self.field_poll_interval_spinBox,
            ):
                control.setEnabled(not waiting)

    def _make_sample_setting(self, value: int, tooltip: str) -> QtWidgets.QSpinBox:
        control = QtWidgets.QSpinBox()
        control.setRange(
            self.logic.MIN_STABLE_SAMPLES,
            self.logic.MAX_STABLE_SAMPLES,
        )
        control.setValue(value)
        control.setToolTip(tooltip)
        return control

    @staticmethod
    def _make_double_setting(
        *,
        minimum: float,
        maximum: float,
        decimals: int,
        step: float,
        suffix: str,
        value: float,
        tooltip: str,
    ) -> QtWidgets.QDoubleSpinBox:
        control = QtWidgets.QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setSingleStep(step)
        control.setSuffix(suffix)
        control.setValue(value)
        control.setToolTip(tooltip)
        return control

    def _log(self, level: str, message: object) -> None:
        append_device_log(self.log_plainTextEdit, level, message)

    # Manager lifecycle API.
    def connect(self, address: str = "") -> bool:
        return self.logic.connect_device(address)

    def disconnect(self) -> bool:
        return self.logic.disconnect_device()

    def start_scan(self) -> None:
        self.logic.start_scan()

    def stop_scan(self) -> None:
        self.logic.stop_scan()

    def force_stop(self) -> bool:
        return self.logic.request_stop()

    def terminate_dev(self) -> bool:
        self._live_timer.stop()
        self.logic.monitor_enabled = False
        self.logic.request_stop()
        if self.logic.isRunning() and not self.logic.wait(self.TERMINATION_TIMEOUT_MS):
            return False
        return self.logic.close()
