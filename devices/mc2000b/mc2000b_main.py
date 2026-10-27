"""PyQt6 control panel for the Thorlabs MC2000B optical chopper."""

from __future__ import annotations

import sys

from PyQt6 import QtWidgets

from .mc2000b_hardware import MC2000BHardware
from .mc2000b_logic import MC2000BLogic


class MC2000B(QtWidgets.QWidget):
    def __init__(self, hardware: MC2000BHardware | None = None) -> None:
        super().__init__()
        self.logic = MC2000BLogic(hardware=hardware)
        self._connected = False
        self._blade_index: int | None = None
        self._enabled: bool | None = None
        self._build_ui()
        self._connect_signals()
        self._update_connection(False)

    def _build_ui(self) -> None:
        self.setWindowTitle("Thorlabs MC2000B")
        layout = QtWidgets.QGridLayout(self)

        layout.addWidget(QtWidgets.QLabel("COM port"), 0, 0)
        self.address_lineEdit = QtWidgets.QLineEdit()
        self.address_lineEdit.setPlaceholderText("COM5")
        layout.addWidget(self.address_lineEdit, 0, 1, 1, 2)
        self.connect_button = QtWidgets.QPushButton("Connect")
        self.disconnect_button = QtWidgets.QPushButton("Disconnect")
        layout.addWidget(self.connect_button, 0, 3)
        layout.addWidget(self.disconnect_button, 0, 4)

        layout.addWidget(QtWidgets.QLabel("Controller blade"), 1, 0)
        self.blade_readback_label = self._readback_label("—")
        self.get_blade_button = QtWidgets.QPushButton("Get blade")
        layout.addWidget(self.blade_readback_label, 1, 3)
        layout.addWidget(self.get_blade_button, 1, 4)

        layout.addWidget(QtWidgets.QLabel("Set target"), 2, 1)
        layout.addWidget(QtWidgets.QLabel("Last read"), 2, 3)

        layout.addWidget(QtWidgets.QLabel("MC1F10HP ref in"), 3, 0)
        self.reference_input_comboBox = QtWidgets.QComboBox()
        self.reference_input_comboBox.addItem("Internal outer", 0)
        self.reference_input_comboBox.addItem("Internal inner", 1)
        self.set_reference_input_button = QtWidgets.QPushButton("Set")
        self.reference_input_readback_label = self._readback_label("—")
        self.get_reference_input_button = QtWidgets.QPushButton("Get")
        layout.addWidget(self.reference_input_comboBox, 3, 1)
        layout.addWidget(self.set_reference_input_button, 3, 2)
        layout.addWidget(self.reference_input_readback_label, 3, 3)
        layout.addWidget(self.get_reference_input_button, 3, 4)

        layout.addWidget(QtWidgets.QLabel("Selected ref frequency (Hz)"), 4, 0)
        self.frequency_spinBox = QtWidgets.QSpinBox()
        self.frequency_spinBox.setRange(
            MC2000BHardware.MIN_FREQUENCY_HZ,
            MC2000BHardware.MAX_FREQUENCY_HZ,
        )
        self.frequency_spinBox.setValue(100)
        layout.addWidget(self.frequency_spinBox, 4, 1)
        self.set_frequency_button = QtWidgets.QPushButton("Set")
        self.get_frequency_button = QtWidgets.QPushButton("Get")
        self.frequency_readback_label = self._readback_label("—")
        layout.addWidget(self.set_frequency_button, 4, 2)
        layout.addWidget(self.frequency_readback_label, 4, 3)
        layout.addWidget(self.get_frequency_button, 4, 4)

        layout.addWidget(QtWidgets.QLabel("Phase (degrees)"), 5, 0)
        self.phase_spinBox = QtWidgets.QSpinBox()
        self.phase_spinBox.setRange(
            MC2000BHardware.MIN_PHASE_DEG,
            MC2000BHardware.MAX_PHASE_DEG,
        )
        layout.addWidget(self.phase_spinBox, 5, 1)
        self.set_phase_button = QtWidgets.QPushButton("Set")
        self.get_phase_button = QtWidgets.QPushButton("Get")
        self.phase_readback_label = self._readback_label("—")
        layout.addWidget(self.set_phase_button, 5, 2)
        layout.addWidget(self.phase_readback_label, 5, 3)
        layout.addWidget(self.get_phase_button, 5, 4)

        layout.addWidget(QtWidgets.QLabel("Chopper"), 6, 0)
        self.start_button = QtWidgets.QPushButton("Start")
        self.stop_button = QtWidgets.QPushButton("Stop")
        self.run_state_label = self._readback_label("Not connected")
        self.refresh_state_button = QtWidgets.QPushButton("Refresh state")
        layout.addWidget(self.start_button, 6, 1)
        layout.addWidget(self.stop_button, 6, 2)
        layout.addWidget(self.run_state_label, 6, 3)
        layout.addWidget(self.refresh_state_button, 6, 4)

        note = QtWidgets.QLabel(
            "Inner/outer share one motor. Change Ref In only in standby; "
            "freq? is the selected internal reference target, not two "
            "independent measured frequencies. Ref Out/BNC is unchanged."
        )
        note.setWordWrap(True)
        layout.addWidget(note, 7, 0, 1, 5)

        self.status_label = QtWidgets.QLabel("ready")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label, 8, 0, 1, 5)

    @staticmethod
    def _readback_label(text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        label.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        label.setMargin(4)
        label.setMinimumWidth(120)
        return label

    def _connect_signals(self) -> None:
        self.connect_button.clicked.connect(
            lambda _checked=False: self.request_connect()
        )
        self.disconnect_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.disconnect)
        )
        self.set_frequency_button.clicked.connect(
            lambda: self.logic.submit_ui_job(
                self.logic.set_frequency, self.frequency_spinBox.value()
            )
        )
        self.get_frequency_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.get_frequency)
        )
        self.get_blade_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.get_blade_index)
        )
        self.set_reference_input_button.clicked.connect(
            lambda: self.logic.submit_ui_job(
                self.logic.select_internal_reference,
                self.reference_input_comboBox.currentData(),
            )
        )
        self.get_reference_input_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.get_reference_input)
        )
        self.set_phase_button.clicked.connect(
            lambda: self.logic.submit_ui_job(
                self.logic.set_phase, self.phase_spinBox.value()
            )
        )
        self.get_phase_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.get_phase)
        )
        self.start_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.start_chopper)
        )
        self.stop_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.stop_chopper)
        )
        self.refresh_state_button.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.get_enabled)
        )
        self.logic.sig_frequency.connect(self._update_frequency)
        self.logic.sig_blade_index.connect(self._update_blade_index)
        self.logic.sig_reference_input.connect(self._update_reference_input)
        self.logic.sig_phase.connect(self._update_phase)
        self.logic.sig_enabled.connect(self._update_run_state)
        self.logic.sig_connected.connect(self._update_connection)
        self.logic.sig_status.connect(self.status_label.setText)
        self.logic.sig_error.connect(self._update_error)

    def request_connect(self, address: str | None = None) -> bool:
        selected = self.address_lineEdit.text() if address is None else str(address)
        selected = selected.strip()
        if not selected:
            self._update_error("enter the configured COM port, for example COM5")
            return False
        self.address_lineEdit.setText(selected)
        return self.logic.submit_ui_job(self.logic.connect, selected)

    def connect(self, address: str) -> bool:
        return self.logic.connect(address)

    def disconnect(self) -> None:
        self.logic.disconnect()

    def stop_scan(self) -> None:
        """No panel activity needs pausing when a scan starts."""

    def start_scan(self) -> None:
        """No panel activity needs resuming when a scan ends."""

    def force_stop(self) -> bool:
        return self.logic.force_stop()

    def terminate_dev(self) -> bool:
        return self.logic.terminate_dev()

    def _update_frequency(self, value: object) -> None:
        self.frequency_readback_label.setText("—" if value is None else f"{int(value)} Hz")

    def _update_blade_index(self, value: object) -> None:
        self._blade_index = None if value is None else int(value)
        if value is None:
            label = "—"
        elif self._blade_index == MC2000BHardware.MC1F10HP_BLADE_INDEX:
            label = "MC1F10HP (6)"
        else:
            label = f"Index {self._blade_index} (not MC1F10HP)"
        self.blade_readback_label.setText(label)
        self._update_reference_controls()

    def _update_reference_input(self, value: object) -> None:
        names = {
            0: "Internal outer",
            1: "Internal inner",
            2: "External outer",
            3: "External inner",
        }
        self.reference_input_readback_label.setText(
            "—" if value is None else names.get(int(value), f"Index {int(value)}")
        )

    def _update_phase(self, value: object) -> None:
        self.phase_readback_label.setText(
            "—" if value is None else f"{int(value)} degrees"
        )

    def _update_run_state(self, enabled: object) -> None:
        self._enabled = enabled if isinstance(enabled, bool) else None
        if not self._connected:
            self.run_state_label.setText("Not connected")
        elif enabled is None:
            self.run_state_label.setText("Unknown")
        else:
            self.run_state_label.setText("Run mode" if enabled else "Standby")
        self.start_button.setEnabled(self._connected and enabled is not True)
        self.stop_button.setEnabled(self._connected)
        self._update_reference_controls()

    def _update_reference_controls(self) -> None:
        can_select = (
            self._connected
            and self._blade_index == MC2000BHardware.MC1F10HP_BLADE_INDEX
            and self._enabled is False
        )
        self.reference_input_comboBox.setEnabled(can_select)
        self.set_reference_input_button.setEnabled(can_select)

    def _update_connection(self, connected: bool) -> None:
        self._connected = connected
        if not connected:
            self._update_blade_index(None)
            self._update_reference_input(None)
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        for button in (
            self.set_frequency_button,
            self.get_frequency_button,
            self.set_phase_button,
            self.get_phase_button,
        ):
            button.setEnabled(connected)
        self.refresh_state_button.setEnabled(connected)
        self.get_blade_button.setEnabled(connected)
        self.get_reference_input_button.setEnabled(connected)
        self._update_run_state(None)
        state = "connected" if connected else "disconnected"
        self.setWindowTitle(f"Thorlabs MC2000B ({state})")

    def _update_error(self, message: str) -> None:
        self.status_label.setText(f"MC2000B error: {message}")


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MC2000B()
    window.show()
    raise SystemExit(app.exec())
