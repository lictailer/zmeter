"""PyQt6 widget for the SP150 monochromator."""

from __future__ import annotations

from pathlib import Path

from PyQt6 import QtWidgets, uic

from core.shared_runtime.visa import VisaRuntime

from .sp150_hardware import SP150Hardware
from .sp150_logic import SP150Logic


class SP150(QtWidgets.QWidget):
    def __init__(
        self,
        hardware: SP150Hardware | None = None,
        visa_runtime: VisaRuntime | None = None,
        move_timeout_s: float = 120.0,
        poll_interval_s: float = 0.25,
        completion_tolerance_nm: float = 0.1,
    ) -> None:
        super().__init__()
        uic.loadUi(str(Path(__file__).with_name("sp150.ui")), self)
        self.logic = SP150Logic(
            hardware=hardware or SP150Hardware(visa_runtime=visa_runtime),
            move_timeout_s=move_timeout_s,
            poll_interval_s=poll_interval_s,
            completion_tolerance_nm=completion_tolerance_nm,
        )
        self._connect_signals()
        self.label_3.setText("ready")

    def _connect_signals(self) -> None:
        self.pushButton.clicked.connect(self._set_wavelength_from_ui)
        self.pushButton_3.clicked.connect(
            lambda: self.logic.submit_ui_job(self.logic.get_wavelength)
        )
        self.logic.sig_last_wavelength.connect(self._update_wavelength)
        self.logic.sig_setting_wavelength.connect(self._update_status)
        self.logic.sig_connected.connect(self._update_connection)
        self.logic.sig_status.connect(self._update_status)
        self.logic.sig_error.connect(self._update_error)

    def connect(
        self,
        address: str,
        timeout_ms: int = 10_000,
        query_delay_s: float = 1.0,
    ) -> bool:
        return self.logic.connect(
            address,
            timeout_ms=timeout_ms,
            query_delay_s=query_delay_s,
        )

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

    def _update_wavelength(self, value: object) -> None:
        self.label_3.setText(f"last read: {float(value):.2f} nm")

    def _update_connection(self, connected: bool) -> None:
        status = "connected" if connected else "disconnected"
        self.setWindowTitle(f"SP150 ({status})")

    def _update_status(self, message: str) -> None:
        self.label_3.setText(str(message))

    def _update_error(self, message: str) -> None:
        self.label_3.setText(f"SP150 error: {message}")
