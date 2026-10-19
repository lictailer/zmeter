"""InSight X3 panel using the manufacturer's Main/diagnostics grouping."""

from __future__ import annotations

import sys

from PyQt6 import QtCore, QtWidgets

from .spectraphysicsx3_laser_hardware import SpectraPhysicsX3Hardware, X3Status
from .spectraphysicsx3_laser_logic import SpectraPhysicsX3Logic


class HoldButton(QtWidgets.QPushButton):
    """Emit once only after a continuous, enabled three-second press."""

    held = QtCore.pyqtSignal()

    def __init__(self, label: str) -> None:
        super().__init__(label)
        self._hold_timer = QtCore.QTimer(self)
        self._hold_timer.setSingleShot(True)
        self._hold_timer.setInterval(3_000)
        self.pressed.connect(self._hold_timer.start)
        self.released.connect(self._hold_timer.stop)
        self._hold_timer.timeout.connect(self._on_hold_complete)

    def _on_hold_complete(self) -> None:
        if self.isEnabled() and self.isDown():
            self.held.emit()


class SpectraPhysicsX3Laser(QtWidgets.QWidget):
    def __init__(
        self, hardware: SpectraPhysicsX3Hardware | None = None
    ) -> None:
        super().__init__()
        self.logic = SpectraPhysicsX3Logic(hardware=hardware)
        self._connected = False
        self._last_actual: int | None = None
        self._build_ui()
        self._power_timer = QtCore.QTimer(self)
        self._power_timer.setInterval(1_000)
        self._power_timer.timeout.connect(self._poll_power)
        self._connect_signals()
        self._update_connection(False)

    def _build_ui(self) -> None:
        self.setWindowTitle("Spectra-Physics InSight X3")
        self.resize(900, 720)
        self.setStyleSheet(
            "QWidget#x3Panel { background: #1246a1; color: white; }"
            "QFrame#x3Side { background: #0758b9; border: 1px solid #539de3; }"
            "QTabWidget::pane { background: #d8e8fa; border: 1px solid #5389c8; }"
            "QTabWidget QWidget { color: #1d3551; }"
            "QTabBar::tab { background: #e9eef6; color: #1d3551; "
            "padding: 7px 12px; }"
            "QTabBar::tab:selected { background: white; }"
            "QFrame#x3Card { background: #eff6ff; border: 1px solid #95b9e1; }"
            "QLabel#x3Value { background: white; color: #1d3551; "
            "border: 1px solid #9ab5d7; padding: 5px; }"
        )
        self.setObjectName("x3Panel")
        outer = QtWidgets.QVBoxLayout(self)

        connection = QtWidgets.QHBoxLayout()
        connection.addWidget(QtWidgets.QLabel("COM port"))
        self.address_lineEdit = QtWidgets.QLineEdit()
        self.address_lineEdit.setPlaceholderText("COM port, e.g. COM4")
        connection.addWidget(self.address_lineEdit, 1)
        self.connect_button = QtWidgets.QPushButton("Connect")
        self.disconnect_button = QtWidgets.QPushButton("Disconnect")
        connection.addWidget(self.connect_button)
        connection.addWidget(self.disconnect_button)
        outer.addLayout(connection)

        content = QtWidgets.QHBoxLayout()
        outer.addLayout(content, 1)
        side = QtWidgets.QFrame()
        side.setObjectName("x3Side")
        side.setFixedWidth(185)
        side_layout = QtWidgets.QVBoxLayout(side)
        title = QtWidgets.QLabel("InSight X3")
        title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 22px; font-weight: bold; color: white")
        side_layout.addWidget(title)
        side_layout.addSpacing(30)
        side_layout.addWidget(QtWidgets.QLabel("Laser emission"))
        self.emission_label = self._value("Unknown")
        side_layout.addWidget(self.emission_label)
        self.diode_on_button = HoldButton("Hold 3 s: ON")
        self.diode_off_button = HoldButton("Hold 3 s: OFF")
        side_layout.addWidget(self.diode_on_button)
        side_layout.addWidget(self.diode_off_button)
        side_layout.addWidget(QtWidgets.QLabel("Tunable beam shutter"))
        self.shutter_label = self._value("Unknown")
        side_layout.addWidget(self.shutter_label)
        self.shutter_open_button = HoldButton("Hold 3 s: Open")
        self.shutter_close_button = HoldButton("Hold 3 s: Close")
        side_layout.addWidget(self.shutter_open_button)
        side_layout.addWidget(self.shutter_close_button)
        side_layout.addWidget(QtWidgets.QLabel("Controller state"))
        self.state_label = self._value("Unknown")
        side_layout.addWidget(self.state_label)
        side_layout.addWidget(QtWidgets.QLabel("Operating mode"))
        self.mode_label = self._value("Unknown")
        side_layout.addWidget(self.mode_label)
        self.mode_run_button = HoldButton("Hold 3 s: Run")
        self.mode_align_button = HoldButton("Hold 3 s: Align")
        side_layout.addWidget(self.mode_run_button)
        side_layout.addWidget(self.mode_align_button)
        side_layout.addStretch(1)
        self.refresh_button = QtWidgets.QPushButton("Refresh readbacks")
        side_layout.addWidget(self.refresh_button)
        content.addWidget(side)

        self.tabs = QtWidgets.QTabWidget()
        content.addWidget(self.tabs, 1)
        self._build_main_tab()
        self._build_objectives_tab()
        self._build_diagnostics_tab()
        self._build_about_tab()

        self.message_label = QtWidgets.QLabel("Disconnected")
        self.message_label.setWordWrap(True)
        outer.addWidget(self.message_label)

    def _build_main_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        card = QtWidgets.QFrame()
        card.setObjectName("x3Card")
        grid = QtWidgets.QGridLayout(card)
        grid.addWidget(QtWidgets.QLabel("Set wavelength"), 0, 0)
        self.target_spinBox = QtWidgets.QSpinBox()
        self.target_spinBox.setRange(680, 1300)
        self.target_spinBox.setSuffix(" nm")
        self.set_wavelength_button = QtWidgets.QPushButton("Set")
        grid.addWidget(self.target_spinBox, 0, 1)
        grid.addWidget(self.set_wavelength_button, 0, 2)
        self.target_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.target_slider.setRange(680, 1300)
        grid.addWidget(self.target_slider, 1, 0, 1, 3)
        grid.addWidget(QtWidgets.QLabel("Controller target"), 2, 0)
        self.target_readback_label = self._value("—")
        grid.addWidget(self.target_readback_label, 2, 1, 1, 2)
        grid.addWidget(QtWidgets.QLabel("Actual wavelength"), 3, 0)
        self.actual_wavelength_label = self._value("—")
        grid.addWidget(self.actual_wavelength_label, 3, 1, 1, 2)
        self.actual_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.actual_slider.setRange(680, 1300)
        self.actual_slider.setEnabled(False)
        grid.addWidget(self.actual_slider, 4, 0, 1, 3)
        grid.addWidget(QtWidgets.QLabel("680 nm"), 5, 0)
        grid.addWidget(QtWidgets.QLabel("1300 nm"), 5, 2)
        grid.addWidget(QtWidgets.QLabel("Controller power (reference)"), 6, 0)
        self.power_label = self._value("—")
        self.power_label.setMinimumWidth(160)
        grid.addWidget(self.power_label, 6, 1)
        self.power_meter = QtWidgets.QProgressBar()
        self.power_meter.setOrientation(QtCore.Qt.Orientation.Vertical)
        self.power_meter.setRange(0, 3000)
        self.power_meter.setValue(0)
        self.power_meter.setTextVisible(False)
        self.power_meter.setFixedSize(48, 150)
        self.power_meter.setStyleSheet(
            "QProgressBar { background: white; border: 1px solid #9ab5d7; }"
            "QProgressBar::chunk { background: #16b879; }"
        )
        grid.addWidget(self.power_meter, 6, 2, 2, 1)
        grid.addWidget(
            QtWidgets.QLabel("0–3 W display; use a calibrated meter for critical work"),
            7, 0, 1, 2,
        )
        layout.addWidget(card)
        note = QtWidgets.QLabel(
            "Wavelength Set does not change the diode or shutter. Opening the "
            "shutter does not turn on the diode. Wavelength readback alone "
            "does not prove output-power stability. OFF closes the shutter "
            "on the controller. Closing ZMeter changes neither."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.tabs.addTab(tab, "Main")

    def _build_objectives_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(tab)
        layout.addRow(
            "Selected objective",
            QtWidgets.QLabel("Managed in the Spectra-Physics control GUI"),
        )
        self.motor_position_label = self._value("—")
        layout.addRow("Actual DeepSee motor position", self.motor_position_label)
        self.tabs.addTab(tab, "Objectives")

    def _build_diagnostics_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QFormLayout(tab)
        self.pulsing_label = self._value("Unknown")
        self.interlock_label = self._value("Unknown")
        self.warning_label = self._value("Unknown")
        self.fault_label = self._value("Unknown")
        self.humidity_label = self._value("—")
        self.temperature_label = self._value("—")
        self.current_label = self._value("—")
        self.hours_label = self._value("—")
        self.warmup_label = self._value("—")
        self.status_word_label = self._value("—")
        layout.addRow("Ready to take data", self.pulsing_label)
        layout.addRow("Interlocks", self.interlock_label)
        layout.addRow("Warning", self.warning_label)
        layout.addRow("Fault", self.fault_label)
        layout.addRow("Cavity humidity", self.humidity_label)
        layout.addRow("Diode temperature", self.temperature_label)
        layout.addRow("Diode current", self.current_label)
        layout.addRow("Diode operating hours", self.hours_label)
        layout.addRow("Warm-up", self.warmup_label)
        layout.addRow("Raw status word", self.status_word_label)
        self.diagnostics_button = QtWidgets.QPushButton("Refresh diagnostics")
        layout.addRow(self.diagnostics_button)
        self.tabs.addTab(tab, "Diagnostics")

    def _build_about_tab(self) -> None:
        tab = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(tab)
        layout.addWidget(QtWidgets.QLabel("Spectra-Physics InSight X3"))
        self.identity_label = self._value("Not queried")
        self.identity_label.setWordWrap(True)
        layout.addWidget(self.identity_label)
        self.identity_button = QtWidgets.QPushButton("Read controller identification")
        layout.addWidget(self.identity_button)
        note = QtWidgets.QLabel(
            "The controller may return no *IDN? response. The manufacturer's "
            "GUI version is not available from this panel."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        self.tabs.addTab(tab, "About")

    @staticmethod
    def _value(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setObjectName("x3Value")
        label.setMinimumWidth(110)
        return label

    def _connect_signals(self) -> None:
        self.target_spinBox.valueChanged.connect(self.target_slider.setValue)
        self.target_slider.valueChanged.connect(self.target_spinBox.setValue)
        self.connect_button.clicked.connect(lambda: self.request_connect())
        self.disconnect_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.disconnect)
        )
        self.set_wavelength_button.clicked.connect(
            lambda: self.logic.submit_ui_job(
                self.logic.set_wavelenght_stable, self.target_spinBox.value()
            )
        )
        self.diode_on_button.held.connect(
            lambda: self.logic.submit_ui_job(self.logic.turn_diode_on)
        )
        self.diode_off_button.held.connect(
            lambda: self.logic.submit_ui_job(self.logic.turn_diode_off)
        )
        self.shutter_open_button.held.connect(
            lambda: self.logic.submit_ui_job(self.logic.panel_set_shutter, 1)
        )
        self.shutter_close_button.held.connect(
            lambda: self.logic.submit_ui_job(self.logic.panel_set_shutter, 0)
        )
        self.mode_run_button.held.connect(
            lambda: self.logic.submit_ui_job(self.logic.select_mode, "RUN")
        )
        self.mode_align_button.held.connect(
            lambda: self.logic.submit_ui_job(self.logic.select_mode, "ALIGN")
        )
        self.refresh_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self._refresh_main_readbacks)
        )
        self.diagnostics_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.read_diagnostics)
        )
        self.identity_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.read_identity)
        )
        self.logic.sig_connected.connect(self._update_connection)
        self.logic.sig_target_wavelength.connect(self._update_target)
        self.logic.sig_actual_wavelength.connect(self._update_actual)
        self.logic.sig_status_word.connect(self._update_status)
        self.logic.sig_mode.connect(
            lambda value: self.mode_label.setText(value or "Unknown")
        )
        self.logic.sig_power_w.connect(self._update_power)
        self.logic.sig_humidity_percent.connect(
            lambda value: self.humidity_label.setText(f"{value:g} %")
        )
        self.logic.sig_diode_temperature_c.connect(
            lambda value: self.temperature_label.setText(f"{value:g} °C")
        )
        self.logic.sig_diode_current_a.connect(
            lambda value: self.current_label.setText(f"{value:g} A")
        )
        self.logic.sig_diode_hours.connect(
            lambda value: self.hours_label.setText(f"{value:g} h")
        )
        self.logic.sig_warmup_percent.connect(
            lambda value: self.warmup_label.setText(f"{value:g} %")
        )
        self.logic.sig_motor_position_percent.connect(
            lambda value: self.motor_position_label.setText(f"{value:g} %")
        )
        self.logic.sig_identity.connect(
            lambda value: self.identity_label.setText(value or "Not reported")
        )
        self.logic.sig_message.connect(self.message_label.setText)
        self.logic.sig_error.connect(self._update_error)

    def _refresh_main_readbacks(self) -> None:
        self.logic.read_status()
        self.logic.get_target_wavelength()
        self.logic.get_wavelenght_stable()
        self.logic.get_output_power_w()
        self.logic.read_mode()

    def _poll_power(self) -> None:
        if self._connected and self.isVisible() and not self.logic.isRunning():
            self.logic.submit_ui_job(self.logic.get_output_power_w)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._connected:
            self._power_timer.start()
            self._poll_power()

    def hideEvent(self, event) -> None:
        self._power_timer.stop()
        super().hideEvent(event)

    def request_connect(self, address: str | None = None) -> bool:
        selected = self.address_lineEdit.text() if address is None else str(address)
        selected = selected.strip()
        if not selected:
            self._update_error("Enter a COM port first")
            return False
        self.address_lineEdit.setText(selected)
        return self.logic.submit_ui_job(self.logic.connect, selected)

    def connect(self, address: str) -> bool:
        return self.logic.connect(address)

    def disconnect(self) -> None:
        self.logic.disconnect()

    def stop_scan(self) -> None:
        self.logic.stop_scan()

    def start_scan(self) -> None:
        self.logic.start_scan()

    def force_stop(self) -> bool:
        return self.logic.force_stop()

    def terminate_dev(self) -> bool:
        return self.logic.terminate_dev()

    def _update_connection(self, connected: bool) -> None:
        self._connected = bool(connected)
        if connected and self.isVisible():
            self._power_timer.start()
            self._poll_power()
        else:
            self._power_timer.stop()
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        for button in (
            self.set_wavelength_button,
            self.refresh_button,
            self.diagnostics_button,
            self.identity_button,
            self.diode_on_button,
            self.diode_off_button,
            self.shutter_open_button,
            self.shutter_close_button,
            self.mode_run_button,
            self.mode_align_button,
        ):
            button.setEnabled(connected)
        if connected:
            minimum = self.logic.hardware.min_wavelength_nm
            maximum = self.logic.hardware.max_wavelength_nm
            if minimum is not None and maximum is not None:
                self.target_spinBox.setRange(minimum, maximum)
                self.target_slider.setRange(minimum, maximum)
                self.actual_slider.setRange(minimum, maximum)
        else:
            self._last_actual = None
            self._update_target(None)
            self._update_actual(None)
            self._update_status(None)
            self._update_power(None)
            self.humidity_label.setText("—")
            self.motor_position_label.setText("—")
            self.temperature_label.setText("—")
            self.current_label.setText("—")
            self.hours_label.setText("—")
            self.warmup_label.setText("—")
            self.mode_label.setText("Unknown")
        state = "connected" if connected else "disconnected"
        self.setWindowTitle(f"Spectra-Physics InSight X3 ({state})")

    def _update_target(self, value: object) -> None:
        self.target_readback_label.setText("—" if value is None else f"{int(value)} nm")

    def _update_actual(self, value: object) -> None:
        if value is None:
            self.actual_wavelength_label.setText("—")
            return
        self._last_actual = int(value)
        self.actual_wavelength_label.setText(f"{self._last_actual} nm (last read)")
        self.actual_slider.setValue(self._last_actual)

    def _update_power(self, value: object) -> None:
        if value is None:
            self.power_label.setText("—")
            self.power_meter.setValue(0)
            self.power_meter.setEnabled(False)
            return
        power = float(value)
        self.power_label.setText(f"{power:.3f} W (last read)")
        self.power_meter.setEnabled(True)
        self.power_meter.setValue(min(3000, max(0, round(power * 1000))))

    def _update_status(self, value: object) -> None:
        if value is None:
            for label in (
                self.emission_label,
                self.shutter_label,
                self.state_label,
                self.pulsing_label,
                self.interlock_label,
                self.warning_label,
                self.fault_label,
            ):
                label.setText("Unknown")
            self.status_word_label.setText("—")
            return
        status: X3Status = value
        self.emission_label.setText("Diode energized" if status.emission else "Off")
        self.shutter_label.setText("Open" if status.shutter_open else "Closed")
        self.state_label.setText(status.state_label)
        self.pulsing_label.setText("Yes" if status.pulsing else "No")
        self.interlock_label.setText("OPEN" if status.interlock_open else "Closed")
        self.warning_label.setText("Present" if status.warning else "None")
        self.fault_label.setText("Present" if status.fault else "None")
        self.status_word_label.setText(f"{status.word} (0x{status.word:08X})")

    def _update_error(self, message: str) -> None:
        self.message_label.setText(f"InSight X3 error: {message}")
        if self._connected:
            last = (
                f" (last read {self._last_actual} nm)"
                if self._last_actual is not None
                else ""
            )
            self.actual_wavelength_label.setText(f"Unknown now{last}")
            self._update_status(None)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = SpectraPhysicsX3Laser()
    window.show()
    raise SystemExit(app.exec())
