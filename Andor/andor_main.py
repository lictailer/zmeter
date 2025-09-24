from __future__ import annotations

import sys
import time
from typing import Any
import numpy as np

import pyvisa  # type: ignore
from PyQt6 import QtWidgets, QtCore, uic  # type: ignore
import pyqtgraph as pg

from andor_logic import AndorCameraLogic


class Andor(QtWidgets.QWidget):

    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()


    # -------------------------------------------------------------
    def __init__(self) -> None:
        super().__init__()

        # ---------------- load UI from external .ui file ---------------
        uic.loadUi("andor/andor.ui", self)  # type: ignore[arg-type]

        # --- runtime attributes created by Qt Designer (.ui) ---
        # The following type annotations inform static analysers that these
        # attributes exist (they are added dynamically by `uic.loadUi`).
        # self.address_cb: QtWidgets.QComboBox  # type: ignore[attr-defined]
        # self.connect_btn: QtWidgets.QPushButton  # type: ignore[attr-defined]
        # self.disconnect_btn: QtWidgets.QPushButton  # type: ignore[attr-defined]
        # self.idn_edit: QtWidgets.QLineEdit  # type: ignore[attr-defined]
        # self.mode_cb: QtWidgets.QComboBox  # type: ignore[attr-defined]
        # self.volt_spin: QtWidgets.QDoubleSpinBox  # type: ignore[attr-defined]
        # self.status_label: QtWidgets.QLabel  # type: ignore[attr-defined]

        # # Ensure mode combo box has expected entries (extend if necessary)
        # for entry in self.MODES:
        #     if self.mode_cb.findText(entry) == -1:
        #         self.mode_cb.addItem(entry) 

        # ---------------- logic layer -------------
        self.camera_logic = AndorCameraLogic()


        # ---------------- wiring ------------------
        self.connectCamera_pushButton.clicked.connect(self._on_connect_camera_clicked) 
        self.disconnectCamera_pushButton.clicked.connect(self._on_disconnect_camera_clicked)  

        self.setTemperature_pushButton.clicked.connect(self._on_set_temperature_clicked) #finished, wait for test
        self.stopCooling_pushButton.clicked.connect(self._on_stop_cooling_value_changed) #finished, wait for test
        self.setExposureTime_pushButton.clicked.connect(self._on_set_exposure_time_clicked) #working on it
        self.acquisitionMode_comboBox.currentTextChanged.connect(self._on_acquisition_mode_changed) #working on it
        self.readMode_comboBox.currentTextChanged.connect(self._on_read_mode_changed) #working on it
        self.accumFrameNumber_spinBox.valueChanged.connect(self._on_accum_setting_changed)
        self.accumFrequency_spinBox.valueChanged.connect(self._on_accum_setting_changed)

        self.snap_pushButton.clicked.connect(self._on_snap_clicked) #working on it



        # Logic signals
        self.camera_logic.sig_temperature.connect(self._update_temperature)   #finished, test successfully
        self.camera_logic.sig_acquisition_mode.connect(self._update_acquisition_mode)   #finished, test successfully
        self.camera_logic.sig_exposure_time.connect(self._update_exposure_time)   #finished, test successfully    
        self.camera_logic.sig_read_mode.connect(self._update_read_mode)   #finished, test successfully
        self.camera_logic.sig_detector_size.connect(self._update_detector_size)   #finished, test successfully
        self.camera_logic.sig_device_info.connect(self._update_status)   #finished, test successfully
        self.camera_logic.sig_is_changing.connect(self._update_status)   #finished, test successfully
        self.camera_logic.sig_connected.connect(self._update_status)   #finished, test successfully

        # plot data signal
        self.camera_logic.sig_image_acquired.connect(self._update_plot)   #finished, test successfully

        # Periodic monitor timer
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._monitor)
        self.timer.start(5000)

    # -------------------------------------------------------------
    # UI event handlers
    # -------------------------------------------------------------
    # def _on_connect_camera_clicked(self):
    #         self.cameraIndex = self.cameraIndex_spinBox.value()
    #         if self.camera_logic.connected:
    #             self.log_message(f"✅ Already connected to {self.camera_logic.device_info}")
    #             return
    #         self.camera_logic.stop()
    #         self.camera_logic.setpoint_camera_index = self.cameraIndex
    #         self.camera_logic.job = "connect_camera"
    #         self.camera_logic.start()
    #         self.camera_logic.wait()
    #         print(self.camera_logic.connected)
            
    #         # Test query functions (non-scan info)
    #         device_info = self.camera_logic.query_device_info()
    #         detector_size = self.camera_logic.query_detector_size()
            
    #         self.log_message(f"✅ Device Info: {device_info}")
    #         self.log_message(f"✅ Detector Size: {detector_size[0]}x{detector_size[1]}")
    #         self.cameraStatus_label.setText(f"connected to {device_info['head_model']}")

    def _on_connect_camera_clicked(self):
        self.cameraIndex = self.cameraIndex_spinBox.value()
        if self.camera_logic.connected:
            self.log_message(f"✅ Already connected to {self.camera_logic.device_info}")
            return
        
        # Disable the connect button to prevent multiple clicks
        self.connectCamera_pushButton.setEnabled(False)
        self.log_message("🔄 Connecting to camera...")
        
        self.camera_logic.stop()
        self.camera_logic.setpoint_camera_index = self.cameraIndex
        self.camera_logic.job = "connect_camera"
        
        # Connect to the finished signal before starting
        self.camera_logic.finished.connect(self._on_camera_connection_finished)
        
        self.camera_logic.start()
        # Remove the blocking wait() call

    def _on_camera_connection_finished(self):
        # Disconnect the signal to avoid multiple connections
        self.camera_logic.finished.disconnect(self._on_camera_connection_finished)
        
        # Re-enable the connect button
        self.connectCamera_pushButton.setEnabled(True)
        
        print(self.camera_logic.connected)
        
        if not self.camera_logic.connected:
            self.log_message("❌ Failed to connect to camera")
            return
        
        try:
            # Test query functions (non-scan info)
            device_info = self.camera_logic.query_device_info()
            detector_size = self.camera_logic.query_detector_size()
            
            self.log_message(f"✅ Device Info: {device_info}")
            self.log_message(f"✅ Detector Size: {detector_size[0]}x{detector_size[1]}")
            self._update_detector_size(detector_size)
            self.cameraStatus_label.setText(f"connected to {device_info.head_model}")
        except Exception as e:
            self.log_message(f"❌ Error querying camera info: {e}")

    def _on_disconnect_camera_clicked(self):
        if self.camera_logic.connected:
            self.camera_logic.stop()
            self.camera_logic.job = "disconnect"
            self.camera_logic.start()
            self.camera_logic.wait()
            self.cameraStatus_label.setText(f"disconnected")
            self.log_message(f"✅ Disconnected from {self.camera_logic.device_info}")

        else:
            self.log_message(f"❌ Not connected to any camera")

    def _on_mode_changed(self, idx: int):
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.setpoint_operating_mode = self.MODES[idx]
        self.logic.job = "set_operating_mode"
        self.logic.start()

    def _on_voltage_changed(self, value: float):
        if not self.logic.connected:
            return
        self.logic.stop()
        self.logic.setpoint_voltage_level = value
        self.logic.job = "set_voltage_level"
        self.logic.start()

    def _on_set_temperature_clicked(self):
        if not self.camera_logic.connected:
            return
        self.camera_logic.stop()
        self.camera_logic.setpoint_temperature = self.temperature_spinBox.value()
        self.camera_logic.setpoint_cooler = True
        self.camera_logic.job = "set_temperature"
        self.camera_logic.start()

    def _on_stop_cooling_value_changed(self):
        if not self.camera_logic.connected:
            return
        self.camera_logic.stop()
        self.camera_logic.setpoint_cooler = False
        self.camera_logic.job = "setup_cooler"
        self.camera_logic.start()

    def _on_set_exposure_time_clicked(self):
        if not self.camera_logic.connected:
            return
        self.camera_logic.stop()
        self.camera_logic.setpoint_exposure_time = self.exposureTime_spinBox.value()
        self.camera_logic.job = "setup_exposure_time"
        self.camera_logic.start()

    def _on_acquisition_mode_changed(self):
        if not self.camera_logic.connected:
            return
        self.camera_logic.stop()
        acquisition_mode = self.acquisitionMode_comboBox.currentText()
        
        if acquisition_mode == "single":
            acquisition_mode = "single"
            self.accumFrameNumber_spinBox.setEnabled(False)
            self.accumFrequency_spinBox.setEnabled(False)
        elif acquisition_mode == "accumulate":
            acquisition_mode = "accum"
            self.accumFrameNumber_spinBox.setEnabled(True)
            self.accumFrequency_spinBox.setEnabled(True)
        else:
            self.accumFrameNumber_spinBox.setEnabled(False)
            self.accumFrequency_spinBox.setEnabled(False)

        self.camera_logic.setpoint_acquisition_mode = acquisition_mode
        self.camera_logic.job = "setup_acquisition_mode"
        self.camera_logic.start()

    def _on_accum_setting_changed(self):
        print("accumulation mode setting changed")
        if not self.camera_logic.connected:
            print("not connected")
            return
        print("not has focus")
        self.camera_logic.stop()
        self.camera_logic.setpoint_accum_num_frames = self.accumFrameNumber_spinBox.value()
        self.camera_logic.setpoint_accum_cycle_time = self.accumFrequency_spinBox.value()
        print("accumulation mode setting changed")
        self.camera_logic.job = "setup_accumulation_mode"
        self.camera_logic.start()
    
    def _on_read_mode_changed(self, mode: str):
        if not self.camera_logic.connected:
            return
        self.camera_logic.stop()
        self.camera_logic.setpoint_read_mode = self.readMode_comboBox.currentText()
        self.camera_logic.job = "setup_read_mode"
        self.camera_logic.start()

    def _on_snap_clicked(self):
        if not self.camera_logic.connected:
            return
        self.camera_logic.stop()
        self.camera_logic.job = "snap_image"
        self.camera_logic.start()

    

    # -------------------------------------------------------------
    # Logic signal slots
    # -------------------------------------------------------------
    # def _update_mode(self, mode: Any):
    #     if mode in self.MODES:
    #         self.mode_cb.blockSignals(True)  # type: ignore[attr-defined]
    #         self.mode_cb.setCurrentText(str(mode))  # type: ignore[attr-defined]
    #         self.mode_cb.blockSignals(False)  # type: ignore[attr-defined]

    # def _update_voltage(self, val: Any):
    #     try:
    #         fval = float(val)
    #     except Exception:
    #         return
    #     self.volt_spin.blockSignals(True)  # type: ignore[attr-defined]
    #     self.volt_spin.setValue(fval)  # type: ignore[attr-defined]
    #     self.volt_spin.blockSignals(False)  # type: ignore[attr-defined]

    def _update_status(self, txt: Any):
        self.log_message(txt)

    def _update_temperature(self, val: Any):
        if self.temperature_spinBox.hasFocus():
            return
        self.currentTemperature_label.setText(f"{val:.1f} °C")

    def _update_acquisition_mode(self, val: Any):
        print("acquisition mode label updated", val)
        if self.acquisitionMode_comboBox.hasFocus():
            return
        self.acquisitionMode_comboBox.setCurrentText(f"{val}")

    def _update_exposure_time(self, val: Any):
        print("exposure time label updated", val)
        if self.exposureTime_spinBox.hasFocus():
            return
        self.exposureTime_spinBox.setValue(float(val))

    def _update_read_mode(self, val: Any):
        print("read mode label updated", val)
        if self.readMode_comboBox.hasFocus():
            return  
        self.readMode_comboBox.setCurrentText(f"{val}")

    def _update_detector_size(self, val: Any):
        print("detector size label updated", val)
        self.detectorSize_label.setText(f"{val[0]}x{val[1]}")

    # def _update_plot(self, val: Any):
    #     print("plot size", val.shape)
    #     print("plot data", val)
    #     # self.andor_PlotWidget.getPlotItem().plot(val, clear=True)
    #     # self.plot_widget.plot(val)

    #     self.andor_PlotWidget.clear()

    #     if val.shape[0] != 1:
    #         if not hasattr(self, 'img_item'):
    #             self.img_item = pg.ImageItem()
    #             self.andor_PlotWidget.addItem(self.img_item)

    #         # Just update the data without clearing
    #         self.img_item.setImage(val.T)

    #         # Optional: Auto-adjust levels for better contrast
    #         self.img_item.setLevels([val.min(), val.max()])
    #     elif val.shape[0] == 1:
    #         if not hasattr(self, 'line_item'):
    #             self.line_item = pg.PlotDataItem()
    #             self.andor_PlotWidget.addItem(self.line_item)
    #         self.line_item.setData(val[0])

    def _update_plot(self, val: Any):
        print("plot size", val.shape)
        print("plot data", val)
        
        self.andor_PlotWidget.clear()
        
        # Remove existing crosshairs and their connections
        self._remove_crosshairs()
        
        if val.shape[0] != 1:
            # 2D plot
            # if not hasattr(self, 'img_item'):
            self.img_item = pg.ImageItem()
            self.andor_PlotWidget.addItem(self.img_item)
            
            # Update the data
            self.img_item.setImage(val.T)
            print(val.shape)
            self.img_item.setLevels([val.min(), val.max()])
            
            # Store data reference for crosshair
            self._current_2d_data = val
            print(val.shape)
            
            self.andor_PlotWidget.autoRange()

            # Add 2D crosshair
            self._add_2d_crosshair()
            
        elif val.shape[0] == 1:
            # 1D plot
            # if not hasattr(self, 'line_item'):
            self.line_item = pg.PlotDataItem()
            self.andor_PlotWidget.addItem(self.line_item)
            
            self.line_item.setData(val[0])
            
            # Store data reference for crosshair
            self._current_1d_data = val[0]

            self.andor_PlotWidget.autoRange()
            
            # Add 1D crosshair
            self._add_1d_crosshair()

    def _remove_crosshairs(self):
        """Remove all crosshair items and disconnect signals"""
        # Disconnect signals first
        if hasattr(self, 'v_line_2d'):
            self.v_line_2d.sigPositionChanged.disconnect()
            self.h_line_2d.sigPositionChanged.disconnect()
            self.andor_PlotWidget.removeItem(self.v_line_2d)
            self.andor_PlotWidget.removeItem(self.h_line_2d)
            delattr(self, 'v_line_2d')
            delattr(self, 'h_line_2d')
        
        if hasattr(self, 'v_line_1d'):
            self.v_line_1d.sigPositionChanged.disconnect()
            self.andor_PlotWidget.removeItem(self.v_line_1d)
            delattr(self, 'v_line_1d')
        
        # Remove labels
        if hasattr(self, 'value_label_2d'):
            self.andor_PlotWidget.removeItem(self.value_label_2d)
            delattr(self, 'value_label_2d')
        
        if hasattr(self, 'value_label_1d'):
            self.andor_PlotWidget.removeItem(self.value_label_1d)
            delattr(self, 'value_label_1d')

    def _add_2d_crosshair(self):
        """Add movable crosshair for 2D image plot"""
        # Create movable crosshair lines
        self.v_line_2d = pg.InfiniteLine(angle=90, movable=True, pen='r')
        self.h_line_2d = pg.InfiniteLine(angle=0, movable=True, pen='r')
        
        # Set initial position to center
        data_shape = self._current_2d_data.shape
        self.v_line_2d.setPos(data_shape[1] / 2)
        self.h_line_2d.setPos(data_shape[0] / 2)
        
        self.andor_PlotWidget.addItem(self.v_line_2d, ignoreBounds=True)
        self.andor_PlotWidget.addItem(self.h_line_2d, ignoreBounds=True)
        
        # Create text label for value display
        self.value_label_2d = pg.TextItem(anchor=(0, 1), color='r')
        self.andor_PlotWidget.addItem(self.value_label_2d)
        
        # Connect position change signals
        self.v_line_2d.sigPositionChanged.connect(self._update_2d_crosshair_text)
        self.h_line_2d.sigPositionChanged.connect(self._update_2d_crosshair_text)
        
        # Initial text update
        self._update_2d_crosshair_text()

    def _add_1d_crosshair(self):
        """Add movable crosshair for 1D line plot"""
        # Create movable vertical line only for 1D
        self.v_line_1d = pg.InfiniteLine(angle=90, movable=True, pen='r')
        
        # Set initial position to center
        self.v_line_1d.setPos(len(self._current_1d_data) / 2)
        
        self.andor_PlotWidget.addItem(self.v_line_1d, ignoreBounds=True)
        
        # Create text label for value display
        self.value_label_1d = pg.TextItem(anchor=(0, 1), color='r')
        self.andor_PlotWidget.addItem(self.value_label_1d)
        
        # Connect position change signal
        self.v_line_1d.sigPositionChanged.connect(self._update_1d_crosshair_text)
        
        # Initial text update
        self._update_1d_crosshair_text()

    def _update_2d_crosshair_text(self):
        """Update text display for 2D crosshair"""
        if not hasattr(self, '_current_2d_data'):
            return
        
        x_pos = self.v_line_2d.pos().x()
        y_pos = self.h_line_2d.pos().y()
        
        # Convert to integer indices
        x = int(round(x_pos))
        y = int(round(y_pos))
        
        # Check bounds
        data_shape = self._current_2d_data.shape
        if 0 <= x < data_shape[1] and 0 <= y < data_shape[0]:
            value = self._current_2d_data[y, x]
            text = f'x={x}, y={y}\nvalue={value:.4e}'
            
            # Position label near the crosshair
            self.value_label_2d.setPos(x_pos + 1, y_pos + 1)
        else:
            text = 'Out of bounds'
            self.value_label_2d.setPos(x_pos + 1, y_pos + 1)
        
        self.value_label_2d.setText(text)

    def _update_1d_crosshair_text(self):
        """Update text display for 1D crosshair"""
        if not hasattr(self, '_current_1d_data'):
            return
        
        x_pos = self.v_line_1d.pos().x()
        
        # Convert to integer index
        x = int(round(x_pos))
        
        # Check bounds
        if 0 <= x < len(self._current_1d_data):
            value = self._current_1d_data[x]
            text = f'x={x}\nvalue={value:.4e}'
            
            # Position label near the line
            self.value_label_1d.setPos(x_pos + 1, value)
        else:
            text = 'Out of bounds'
            # Position at a reasonable location when out of bounds
            y_pos = np.mean(self._current_1d_data) if len(self._current_1d_data) > 0 else 0
            self.value_label_1d.setPos(x_pos + 1, y_pos)
        
        self.value_label_1d.setText(text)

    

    

    # -------------------------------------------------------------
    # Helper methods
    # -------------------------------------------------------------
    def _refresh_visa_resources(self):
        rm = pyvisa.ResourceManager()
        resources = rm.list_resources()
        self.address_comboBox.clear()  # type: ignore[attr-defined]
        self.address_comboBox.addItems(resources)  # type: ignore[attr-defined]

    # -------------------------------------------------------------
    # Periodic monitor
    # This is used to continuously update the UI with the current value of the parameter
    # See sr860, sr830 or nidaq for examples
    # -------------------------------------------------------------
    def _monitor(self):
        if not self.camera_logic.connected:
            return
        if self.camera_logic.isRunning():
            return
        self.camera_logic.job = "get_all"
        self.camera_logic.start()

    def log_message(self, message):
        '''
        Add message to log display
        '''
        self.log_textEdit.append(message)
        # Auto-scroll to bottom
        self.log_textEdit.verticalScrollBar().setValue(
            self.log_textEdit.verticalScrollBar().maximum()
        )


# ----------------------------------------------------------------------
# Stand-alone entry-point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    win = Andor()
    win.show()
    sys.exit(app.exec())
