"""PyQt6 widget for the PEM100 photoelastic modulator."""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtWidgets, uic

from core.shared_runtime.visa import VisaRuntime

from .pem100_hardware import PEM100Hardware
from .pem100_logic import PEM100Logic


class PEM100(QtWidgets.QWidget):
    def __init__(
        self,
        hardware: PEM100Hardware | None = None,
        visa_runtime: VisaRuntime | None = None,
    ) -> None:
        super().__init__()
        uic.loadUi(str(Path(__file__).with_name("pem100.ui")), self)
        self.logic = PEM100Logic(
            hardware=hardware or PEM100Hardware(visa_runtime=visa_runtime)
        )
        self._connect_signals()

    def _connect_signals(self) -> None:
        self.pushButton.clicked.connect(self._set_wavelength_from_ui)
        self.pushButton_2.clicked.connect(self._set_retardance_from_ui)
        self.pushButton_3.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.get_wavelength)
        )
        self.pushButton_4.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.get_retardance)
        )
        self.logic.sig_last_retardance.connect(self._update_retardance)
        self.logic.sig_last_wavelength.connect(self._update_wavelength)
        self.logic.sig_connected.connect(self._update_connection)
        self.logic.sig_status.connect(self._update_status)
        self.logic.sig_error.connect(self._update_error)

    def connect(self, address: str, timeout_ms: int = 20_000) -> bool:
        return self.logic.connect(address, timeout_ms=timeout_ms)

    def disconnect(self) -> None:
        self.logic.disconnect()

    def start_scan(self) -> bool:
        return self.logic.start_scan()

    def stop_scan(self) -> bool:
        return self.logic.stop_scan()

    def force_stop(self) -> bool:
        return self.logic.force_stop()

    def terminate_dev(self) -> bool:
        return self.logic.terminate_dev()

    def _set_wavelength_from_ui(self) -> None:
        try:
            value = float(self.lineEdit.text())
        except ValueError:
            self._update_error("Enter a numeric wavelength")
            return
        self.logic.submit_ui_job(self.logic.set_wavelength, value)

    def _set_retardance_from_ui(self) -> None:
        try:
            value = float(self.lineEdit_2.text())
        except ValueError:
            self._update_error("Enter a numeric retardance")
            return
        self.logic.submit_ui_job(self.logic.set_retardance, value)

    def _update_wavelength(self, value: object) -> None:
        self.label_3.setText(f"last read: {value} nm")

    def _update_retardance(self, value: object) -> None:
        self.label_4.setText(f"last read: {value} lambda")

    def _update_connection(self, connected: bool) -> None:
        status = "connected" if connected else "disconnected"
        self.setWindowTitle(f"PEM100 ({status})")

    def _update_status(self, message: str) -> None:
        self.setToolTip(message)

    def _update_error(self, message: str) -> None:
        self.setToolTip(f"PEM100 error: {message}")
