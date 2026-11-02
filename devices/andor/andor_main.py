"""Operator panel for the Andor camera and Shamrock spectrograph.

Ported from the bench-tested Mfork ``Andor/andor_main.py``.  Changes: no
device enumeration in the constructor (counts are read when connecting),
panel jobs are refused instead of interrupting a running job, the scan
lifecycle closes panel-job admission and restores the monitor afterwards,
force stop only aborts the exposure, and messages go to the shared device log.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore, QtWidgets, uic

from core.device_log import append_device_log, configure_device_log

from .andor_logic import AndorCameraLogic, parse_address


class Andor(QtWidgets.QWidget):
    MONITOR_INTERVAL_MS = 5000
    SCAN_QUIESCE_TIMEOUT_MS = 10_000
    TERMINATION_TIMEOUT_MS = 10_000
    _UNSUPPORTED_MODES = ("kinetic (not working)", "continue (not working)")

    def __init__(self) -> None:
        super().__init__()
        uic.loadUi(os.path.join(os.path.dirname(__file__), "andor.ui"), self)

        self.camera_logic = AndorCameraLogic()
        self.logic = self.camera_logic
        self._monitor_enabled = True
        self._scan_active = False
        self._scan_monitor_was_enabled = False

        configure_device_log(self.log_textEdit)
        self._wire_controls()
        self._wire_logic_signals()
        self._initialize_status()

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._monitor)
        self.timer.start(self.MONITOR_INTERVAL_MS)

    # ------------------------------------------------------------ wiring
    def _wire_controls(self):
        self.connectCamera_pushButton.clicked.connect(self._on_connect_camera_clicked)
        self.disconnectCamera_pushButton.clicked.connect(self._on_disconnect_camera_clicked)
        self.connectSpectrometer_pushButton.clicked.connect(self._on_connect_spectrometer_clicked)
        self.disconnectSpectrometer_pushButton.clicked.connect(
            self._on_disconnect_spectrometer_clicked
        )
        self.setTemperature_pushButton.clicked.connect(self._on_set_temperature_clicked)
        self.stopCooling_pushButton.clicked.connect(self._on_stop_cooling_clicked)
        self.setExposureTime_pushButton.clicked.connect(self._on_set_exposure_time_clicked)
        self.acquisitionMode_comboBox.currentTextChanged.connect(self._on_acquisition_mode_changed)
        self.readMode_comboBox.currentTextChanged.connect(self._on_read_mode_changed)
        self.accumFrameNumber_spinBox.valueChanged.connect(self._on_accum_setting_changed)
        self.accumFrequency_spinBox.valueChanged.connect(self._on_accum_setting_changed)
        self.startAcquisition_pushButton.clicked.connect(self._on_start_acquisition_clicked)
        self.stopAcquisition_pushButton.clicked.connect(self._on_stop_acquisition_clicked)
        self.snap_pushButton.clicked.connect(self._on_snap_clicked)

    def _wire_logic_signals(self):
        logic = self.camera_logic
        logic.sig_camera_count.connect(self._update_camera_count)
        logic.sig_spectrometer_count.connect(self._update_spectrometer_count)
        logic.sig_connected.connect(self._update_camera_connection_status)
        logic.sig_spectrometer_connected.connect(self._update_spectrometer_connection_status)
        logic.sig_temperature.connect(self._update_temperature)
        logic.sig_acquisition_mode.connect(self._update_acquisition_mode)
        logic.sig_exposure_time.connect(self._update_exposure_time)
        logic.sig_read_mode.connect(self._update_read_mode)
        logic.sig_detector_size.connect(self._update_detector_size)
        logic.sig_image_acquired.connect(self._update_plot)
        logic.sig_log.connect(self.log_message)

    def _initialize_status(self):
        self.cameraStatus_label.setText("disconnected")
        self.spectrometerStatus_label.setText("disconnected")
        self.numCamera_label.setText("-")
        self.numSpectrometer_label.setText("-")

    # --------------------------------------------------------- panel jobs
    def _start_logic_job(self, job: str) -> bool:
        if self._scan_active:
            self.log_message("WARNING", "Andor panel controls are paused while a scan owns the device.")
            return False
        if self.camera_logic.isRunning():
            self.log_message("WARNING", "Andor is busy; try again when the current job finishes.")
            return False
        self.camera_logic.job = job
        self.camera_logic.start()
        return True

    def _on_connect_camera_clicked(self):
        if self.camera_logic.connected:
            self.log_message("INFO", "Camera is already connected")
            return
        self.camera_logic.setpoint_camera_index = int(self.cameraIndex_spinBox.value())
        if self._start_logic_job("connect_camera_job"):
            self.cameraStatus_label.setText("connecting")

    def _on_disconnect_camera_clicked(self):
        if self.camera_logic.isRunning():
            self.log_message("WARNING", "Andor is busy; disconnect after the current job.")
            return
        self.camera_logic.disconnect_camera()

    def _on_connect_spectrometer_clicked(self):
        if self.camera_logic.spectrometer_connected:
            self.log_message("INFO", "Spectrograph is already connected")
            return
        self.camera_logic.setpoint_spectrometer_index = int(self.spectrometerIndex_spinBox.value())
        if self._start_logic_job("connect_spectrometer_job"):
            self.spectrometerStatus_label.setText("connecting")

    def _on_disconnect_spectrometer_clicked(self):
        if self.camera_logic.isRunning():
            self.log_message("WARNING", "Andor is busy; disconnect after the current job.")
            return
        self.camera_logic.disconnect_spectrometer()

    def _require_camera(self, action: str) -> bool:
        if not self.camera_logic.connected:
            self.log_message("WARNING", f"Connect the camera before {action}")
            return False
        return True

    def _on_set_temperature_clicked(self):
        if not self._require_camera("setting the temperature"):
            return
        self.camera_logic.setpoint_temperature = int(self.temperature_spinBox.value())
        self._start_logic_job("apply_temperature_setpoint")

    def _on_stop_cooling_clicked(self):
        if not self._require_camera("changing the cooler"):
            return
        self.camera_logic.setpoint_cooler = False
        self._start_logic_job("setup_cooler")

    def _on_set_exposure_time_clicked(self):
        if not self._require_camera("setting the exposure time"):
            return
        self.camera_logic.setpoint_exposure_time = float(self.exposureTime_spinBox.value())
        self._start_logic_job("setup_exposure_time")

    def _on_acquisition_mode_changed(self, *_):
        mode = self.acquisitionMode_comboBox.currentText()
        accumulate = mode == "accumulate"
        self.accumFrameNumber_spinBox.setEnabled(accumulate)
        self.accumFrequency_spinBox.setEnabled(accumulate)
        if not self.camera_logic.connected:
            return
        if mode in self._UNSUPPORTED_MODES:
            self.log_message("WARNING", f"Acquisition mode '{mode}' is not supported.")
            return
        self.camera_logic.setpoint_acquisition_mode = "accum" if accumulate else mode
        self._start_logic_job("setup_acquisition_mode")

    def _on_accum_setting_changed(self, *_):
        if not self.camera_logic.connected:
            return
        if self.acquisitionMode_comboBox.currentText() != "accumulate":
            return
        self.camera_logic.setpoint_accum_num_frames = int(self.accumFrameNumber_spinBox.value())
        self.camera_logic.setpoint_accum_cycle_time = float(self.accumFrequency_spinBox.value())
        self._start_logic_job("setup_accumulation_mode")

    def _on_read_mode_changed(self, *_):
        if not self.camera_logic.connected:
            return
        self.camera_logic.setpoint_read_mode = self.readMode_comboBox.currentText()
        self._start_logic_job("setup_read_mode")

    def _on_start_acquisition_clicked(self):
        if self._require_camera("starting an acquisition"):
            self._start_logic_job("start_acquisition")

    def _on_stop_acquisition_clicked(self):
        if self.camera_logic.connected:
            self._start_logic_job("stop_acquisition")

    def _on_snap_clicked(self):
        if self._require_camera("snapping an image"):
            self._start_logic_job("snap_image")

    # ----------------------------------------------------------- display
    def _update_camera_count(self, count: Any):
        self.numCamera_label.setText(str(count))

    def _update_spectrometer_count(self, count: Any):
        self.numSpectrometer_label.setText(str(count))

    def _update_camera_connection_status(self, status: Any):
        text = str(status)
        if self.camera_logic.connected:
            head_model = self._get_device_info_value(
                self.camera_logic.device_info,
                "head_model",
                f"camera {self.camera_logic.setpoint_camera_index}",
            )
            self.cameraStatus_label.setText(f"connected to {head_model}")
        elif "failed" in text:
            self.cameraStatus_label.setText("connection failed")
        else:
            self.cameraStatus_label.setText("disconnected")

    def _update_spectrometer_connection_status(self, status: Any):
        text = str(status)
        if self.camera_logic.spectrometer_connected:
            self.spectrometerStatus_label.setText(
                f"connected to {self.camera_logic.setpoint_spectrometer_index}"
            )
        elif "failed" in text:
            self.spectrometerStatus_label.setText("connection failed")
        else:
            self.spectrometerStatus_label.setText("disconnected")

    def _update_temperature(self, val: Any):
        try:
            self.currentTemperature_label.setText(f"{float(val):.1f} C")
        except (TypeError, ValueError):
            self.currentTemperature_label.setText(str(val))

    def _update_acquisition_mode(self, val: Any):
        if self.acquisitionMode_comboBox.hasFocus():
            return
        display = "accumulate" if str(val) == "accum" else str(val)
        self.acquisitionMode_comboBox.blockSignals(True)
        self.acquisitionMode_comboBox.setCurrentText(display)
        self.acquisitionMode_comboBox.blockSignals(False)

    def _update_exposure_time(self, val: Any):
        if self.exposureTime_spinBox.hasFocus():
            return
        self.exposureTime_spinBox.setValue(float(val))

    def _update_read_mode(self, val: Any):
        if self.readMode_comboBox.hasFocus():
            return
        self.readMode_comboBox.blockSignals(True)
        self.readMode_comboBox.setCurrentText(str(val))
        self.readMode_comboBox.blockSignals(False)

    def _update_detector_size(self, val: Any):
        if val is None:
            return
        self.detectorSize_label.setText(f"{val[0]}x{val[1]}")

    def _update_plot(self, val: Any):
        val = np.asarray(val)
        self.andor_PlotWidget.clear()
        self._remove_crosshairs()

        if val.ndim == 2 and val.shape[0] != 1:
            self.img_item = pg.ImageItem()
            self.andor_PlotWidget.addItem(self.img_item)
            self.img_item.setImage(val.T)
            self.img_item.setLevels([float(np.nanmin(val)), float(np.nanmax(val))])
            self._current_2d_data = val
            self.andor_PlotWidget.autoRange()
            self._add_2d_crosshair()
            return

        data = val[0] if val.ndim == 2 else val
        self.line_item = pg.PlotDataItem()
        self.andor_PlotWidget.addItem(self.line_item)
        self.line_item.setData(data)
        self._current_1d_data = data
        self.andor_PlotWidget.autoRange()
        self._add_1d_crosshair()

    def _remove_crosshairs(self):
        for name in ("v_line_2d", "h_line_2d", "v_line_1d"):
            item = getattr(self, name, None)
            if item is not None:
                try:
                    item.sigPositionChanged.disconnect()
                except TypeError:
                    pass
                self.andor_PlotWidget.removeItem(item)
                delattr(self, name)

        for name in ("value_label_2d", "value_label_1d"):
            item = getattr(self, name, None)
            if item is not None:
                self.andor_PlotWidget.removeItem(item)
                delattr(self, name)

    def _add_2d_crosshair(self):
        self.v_line_2d = pg.InfiniteLine(angle=90, movable=True, pen="r")
        self.h_line_2d = pg.InfiniteLine(angle=0, movable=True, pen="r")
        data_shape = self._current_2d_data.shape
        self.v_line_2d.setPos(data_shape[1] / 2)
        self.h_line_2d.setPos(data_shape[0] / 2)
        self.andor_PlotWidget.addItem(self.v_line_2d, ignoreBounds=True)
        self.andor_PlotWidget.addItem(self.h_line_2d, ignoreBounds=True)
        self.value_label_2d = pg.TextItem(anchor=(0, 1), color="r")
        self.andor_PlotWidget.addItem(self.value_label_2d)
        self.v_line_2d.sigPositionChanged.connect(self._update_2d_crosshair_text)
        self.h_line_2d.sigPositionChanged.connect(self._update_2d_crosshair_text)
        self._update_2d_crosshair_text()

    def _add_1d_crosshair(self):
        self.v_line_1d = pg.InfiniteLine(angle=90, movable=True, pen="r")
        self.v_line_1d.setPos(len(self._current_1d_data) / 2)
        self.andor_PlotWidget.addItem(self.v_line_1d, ignoreBounds=True)
        self.value_label_1d = pg.TextItem(anchor=(0, 1), color="r")
        self.andor_PlotWidget.addItem(self.value_label_1d)
        self.v_line_1d.sigPositionChanged.connect(self._update_1d_crosshair_text)
        self._update_1d_crosshair_text()

    def _update_2d_crosshair_text(self):
        if not hasattr(self, "_current_2d_data"):
            return
        x_pos = self.v_line_2d.pos().x()
        y_pos = self.h_line_2d.pos().y()
        x = int(round(x_pos))
        y = int(round(y_pos))
        data_shape = self._current_2d_data.shape
        if 0 <= x < data_shape[1] and 0 <= y < data_shape[0]:
            value = self._current_2d_data[y, x]
            text = f"x={x}, y={y}\nvalue={value:.4e}"
        else:
            text = "Out of bounds"
        self.value_label_2d.setPos(x_pos + 1, y_pos + 1)
        self.value_label_2d.setText(text)

    def _update_1d_crosshair_text(self):
        if not hasattr(self, "_current_1d_data"):
            return
        x_pos = self.v_line_1d.pos().x()
        x = int(round(x_pos))
        if 0 <= x < len(self._current_1d_data):
            value = self._current_1d_data[x]
            text = f"x={x}\nvalue={value:.4e}"
            y_pos = value
        else:
            text = "Out of bounds"
            y_pos = np.nanmean(self._current_1d_data) if len(self._current_1d_data) else 0
        self.value_label_1d.setPos(x_pos + 1, y_pos)
        self.value_label_1d.setText(text)

    @staticmethod
    def _get_device_info_value(device_info, key, default=None):
        if isinstance(device_info, dict):
            return device_info.get(key, default)
        return getattr(device_info, key, default)

    # ------------------------------------------------------------ monitor
    def _monitor(self):
        if not self._monitor_enabled or self._scan_active:
            return
        if not self.camera_logic.connected or self.camera_logic.isRunning():
            return
        self._start_logic_job("monitor_poll")

    @QtCore.pyqtSlot()
    def stop_timer(self):
        self._monitor_enabled = False
        if self.timer.isActive():
            self.timer.stop()

    @QtCore.pyqtSlot()
    def start_timer(self):
        self._monitor_enabled = True
        if not self.timer.isActive():
            self.timer.start(self.MONITOR_INTERVAL_MS)

    def _on_owner(self, slot_name: str):
        if QtCore.QThread.currentThread() != self.thread():
            QtCore.QMetaObject.invokeMethod(
                self, slot_name, QtCore.Qt.ConnectionType.BlockingQueuedConnection
            )
        else:
            getattr(self, slot_name)()

    # ---------------------------------------------------- device lifecycle
    def connect(self, address="", timeout_ms: int = 10_000) -> bool:
        """Startup/runtime connect: literal True once the camera is connected."""
        camera_index, spectrometer_index = parse_address(address)
        return self.camera_logic.connect_with_timeout(
            camera_index, spectrometer_index, timeout_ms
        ) is True

    def disconnect_device(self):
        return self.camera_logic.disconnect_all()

    def stop_scan(self) -> bool:
        self._on_owner("_stop_scan_on_owner")
        return self.camera_logic.prepare_scan(self.SCAN_QUIESCE_TIMEOUT_MS)

    @QtCore.pyqtSlot()
    def _stop_scan_on_owner(self):
        if self._scan_active:
            return
        self._scan_monitor_was_enabled = self._monitor_enabled and self.timer.isActive()
        self._scan_active = True
        self.camera_logic.scan_admission_closed = True
        self.stop_timer()

    def start_scan(self) -> bool:
        self.camera_logic.resume_scan()
        self._on_owner("_start_scan_on_owner")
        return True

    @QtCore.pyqtSlot()
    def _start_scan_on_owner(self):
        if not self._scan_active:
            return
        restore = self._scan_monitor_was_enabled
        self._scan_active = False
        self._scan_monitor_was_enabled = False
        if restore:
            self.start_timer()

    def force_stop(self) -> bool:
        """Abort the running exposure; the camera stays connected."""
        self.camera_logic.abort_exposure()
        return True

    def terminate_dev(self) -> bool:
        self._on_owner("stop_timer")
        return self.camera_logic.shutdown(self.TERMINATION_TIMEOUT_MS)

    def log_message(self, level, message=None):
        if message is None:
            level, message = "INFO", level
        append_device_log(self.log_textEdit, level, message)


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = Andor()
    win.show()
    sys.exit(app.exec())
