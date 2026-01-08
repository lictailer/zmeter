from PyQt6 import QtWidgets, uic, QtCore
import sys
import time
import numpy as np
import pyqtgraph as pg
import pyvisa

from .sr860_logic import SR860_Logic


class SR860(QtWidgets.QWidget):
    """Qt GUI wrapper for SR860 lock-in amplifier.

    The class is heavily inspired by *sr830_main.SR830* but follows the
    new **sr860_logic** naming rules (get_*/set_*).  Where the
    corresponding method is missing on *SR860_Logic*, a stub is provided
    that simply *pass*es so UI connections still resolve.
    """

    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()

    def __init__(self):
        super().__init__()

        # ----- load UI -----
        uic.loadUi("sr860/sr860.ui", self)

        # ----- helper plot widget (X, Y, R, Theta streams) -----
        w = pg.GraphicsLayoutWidget(show=True)
        w.viewport().setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        self.plot_x = w.addPlot(row=0, col=0)
        self.plot_y = w.addPlot(row=1, col=0)
        self.plot_r = w.addPlot(row=0, col=1)
        self.plot_t = w.addPlot(row=1, col=1)
        self.plot_x.setTitle("X")
        self.plot_y.setTitle("Y")
        self.plot_r.setTitle("R")
        self.plot_t.setTitle("Theta")
        # *graph_xyrt* is a QVBoxLayout placeholder defined in the .ui file
        self.graph_xyrt.addWidget(w)

        # ----- VISA resource list -----
        resource_manager = pyvisa.ResourceManager()
        self.address_cb.addItems(resource_manager.list_resources())

        # ----- logic / model layer -----
        self.logic = SR860_Logic()

        # circular buffers for live plot
        self.x_log = np.full(200, np.nan, dtype=float)
        self.y_log = np.full(200, np.nan, dtype=float)
        self.r_log = np.full(200, np.nan, dtype=float)
        self.t_log = np.full(200, np.nan, dtype=float)

        #----self defined get and set methods-----
        self.get_methods = [
            method
            for method in dir(self.logic)
            if callable(getattr(self.logic, method)) and method.startswith("get_")
        ]
        self.set_methods = [
            method
            for method in dir(self.logic)
            if callable(getattr(self.logic, method)) and method.startswith("set_")
        ]

        # ----- connect logic signals to update-slots -----
        self.logic.sig_frequency.connect(self.update_frequency)
        self.logic.sig_amplitude.connect(self.update_amplitude)
        self.logic.sig_time_constant.connect(self.update_time_constant)
        self.logic.sig_sensitivity.connect(self.update_sensitivity)
        self.logic.sig_phase.connect(self.update_phase)
        self.logic.sig_ref_mode.connect(self.update_ref_mode)
        self.logic.sig_ext_trigger.connect(self.update_ext_trigger)
        # self.logic.sig_ref_input.connect(self.update_ref_input)
        self.logic.sig_sync_filter.connect(self.update_sync_filter)
        self.logic.sig_harmonic.connect(self.update_harmonic)
        # self.logic.sig_signal_input_type.connect(self.update_signal_input_type)
        # self.logic.sig_signal_input_mode.connect(self.update_signal_input_mode)
        # self.logic.sig_signal_input_type.connect(self.update_signal_input_config)
        # self.logic.sig_signal_input_mode.connect(self.update_signal_input_config)
        self.logic.sig_input_config.connect(self.update_signal_input_config)
        self.logic.sig_input_config.connect(self.update_input_config)
        self.logic.sig_voltage_input_coupling.connect(self.update_voltage_input_coupling)
        self.logic.sig_voltage_input_range.connect(self.update_voltage_input_range)
        self.logic.sig_current_input_range.connect(self.update_current_input_range)
        self.logic.sig_unlocked.connect(self.update_unlocked)
        self.logic.sig_input_overload.connect(self.update_input_overload)
        self.logic.sig_sensitivity_overload.connect(self.update_sensitivity_overload)
        self.logic.sig_X.connect(self.update_X)
        self.logic.sig_Y.connect(self.update_Y)
        self.logic.sig_R.connect(self.update_R)
        self.logic.sig_Theta.connect(self.update_Theta)
        self.logic.sig_is_changing.connect(self.update_status)
        self.logic.sig_connected.connect(self.update_status)
        self.logic.sig_input_shield.connect(self.update_input_shield)
        self.logic.sig_dc_level.connect(self.update_dc_level)
        self.logic.sig_dc_level_mode.connect(self.update_dc_level_mode)
        self.logic.sig_filter_slope.connect(self.update_filter_slope)

        # ----- connect UI widgets to get/set actions -----
        self.freq_doubleSpinBox.valueChanged.connect(self.set_frequency)
        self.ampl_doubleSpinBox.valueChanged.connect(self.set_amplitude)
        self.time_constant_comboBox.currentIndexChanged.connect(self.set_time_constant)
        self.sensitivity_comboBox.currentIndexChanged.connect(self.set_sensitivity)
        self.auto_scale_pushButton.clicked.connect(self.set_auto_scale)
        self.phase_doubleSpinBox.valueChanged.connect(self.set_phase)
        self.auto_phase_pushButton.clicked.connect(self.set_auto_phase)
        self.ref_mode_comboBox.currentIndexChanged.connect(self.set_ref_mode)
        self.trig_comboBox.currentIndexChanged.connect(self.set_ext_trigger)
        self.ext_ref_comboBox.currentIndexChanged.connect(self.set_ref_input)
        self.sync_filter_checkBox.stateChanged.connect(self.set_sync_filter)
        self.harmonic_spinBox.valueChanged.connect(self.set_harmonic)
        self.input_shield_comboBox.currentIndexChanged.connect(self.set_input_shield)
        self.dclevel_doubleSpinBox.valueChanged.connect(self.set_dc_level)
        self.dclevel_mode_comboBox.currentIndexChanged.connect(self.set_dc_level_mode)
        self.filter_slope_comboBox.currentIndexChanged.connect(self.set_filter_slope)

        # voltage / signal input helpers
        self.input_config_comboBox.currentIndexChanged.connect(self.set_signal_input_config)
        self.voltage_range_comboBox.currentIndexChanged.connect(self.set_signal_input_config)
        self.current_range_comboBox.currentIndexChanged.connect(self.set_signal_input_config)
        self.auto_range_pushButton.clicked.connect(self.set_auto_range)

        self.input_coupling_comboBox.currentIndexChanged.connect(self.set_voltage_input_coupling)
        # self.input_range_comboBox.currentIndexChanged.connect(self.set_voltage_input_range)

        self.connect_pushButton.clicked.connect(self.connect_visa)
        self.pause_graph_button.clicked.connect(self.stop_timer)
        self.resume_graph_button.clicked.connect(self.start_timer)
        self.disconnect_pushButton.clicked.connect(self.disconnect_device)

        # ----- periodic monitor -----
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.monitor)
        self.timer.start(50)
        self.stop_signal.connect(self.stop_timer)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def reset_graph(self):
        self.x_log[:] = np.nan
        self.y_log[:] = np.nan
        self.r_log[:] = np.nan
        self.t_log[:] = np.nan
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_x.plot(self.x_log, clear=True, pen=pen)
        self.plot_y.plot(self.y_log, clear=True, pen=pen)
        self.plot_r.plot(self.r_log, clear=True, pen=pen)
        self.plot_t.plot(self.t_log, clear=True, pen=pen)

    def stop_timer(self):
        if self.timer.isActive():
            self.timer.stop()

    def start_timer(self):
        if not self.timer.isActive():
            self.timer.start(50)

    def update_status(self, txt):
        """Generic label updater for *sig_is_changing* & *sig_connected*."""
        self.status_label.setText(str(txt))

    # ------------------------------------------------------------------
    # VISA connection
    # ------------------------------------------------------------------
    def connect_visa(self, addr):
        if addr == None or addr == False:
            addr = self.address_cb.currentText()
        print(f"Connecting to {addr}")
        self.logic.connect_visa(addr)
        self.address_cb.setCurrentText(addr)

    # ------------------------------------------------------------------
    # get_/set_ wrappers (naming follows sr860_logic)
    # ------------------------------------------------------------------
    def set_frequency(self, val: float | None = None):
        self.logic.stop()
        self.logic.setpoint_frequency = val if val is not None else self.freq_doubleSpinBox.value()
        self.logic.job = "set_frequency"
        self.logic.start()

    def get_frequency(self):
        self.logic.job = "get_frequency"
        self.logic.start()

    def update_frequency(self, val):
        self.freq_doubleSpinBox.blockSignals(True)
        self.freq_doubleSpinBox.setValue(float(val))
        self.freq_doubleSpinBox.blockSignals(False)

    # -- amplitude -----------------------------------------------------
    def set_amplitude(self, val: float | None = None):
        self.logic.stop()
        self.logic.setpoint_amplitude = val if val is not None else self.ampl_doubleSpinBox.value()
        self.logic.job = "set_amplitude"
        self.logic.start()

    def get_amplitude(self):
        self.logic.job = "get_amplitude"
        self.logic.start()

    def update_amplitude(self, val):
        self.ampl_doubleSpinBox.blockSignals(True)
        self.ampl_doubleSpinBox.setValue(float(val))
        self.ampl_doubleSpinBox.blockSignals(False)

    # -- time-constant -------------------------------------------------
    def set_time_constant(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_time_constant = idx if idx is not None else self.time_constant_comboBox.currentIndex()
        self.logic.job = "set_time_constant"
        self.logic.start()

    def get_time_constant(self):
        self.logic.job = "get_time_constant"
        self.logic.start()

    def update_time_constant(self, text):
        self.time_constant_comboBox.blockSignals(True)
        self.time_constant_comboBox.setCurrentText(str(text))
        self.time_constant_comboBox.blockSignals(False)

    # -- sensitivity ---------------------------------------------------
    def set_sensitivity(self, idx: int | None = None):
        self.logic.stop()
        print("isRunning", self.logic.isRunning())
        self.logic.setpoint_sensitivity = idx if idx is not None else self.sensitivity_comboBox.currentIndex()
        print("setpoint_sensitivity", self.logic.setpoint_sensitivity)
        self.logic.job = "set_sensitivity"
        self.logic.start()
        self.start_timer()

    def get_sensitivity(self):
        self.logic.job = "get_sensitivity"
        self.logic.start()

    def update_sensitivity(self, idx):
        self.sensitivity_comboBox.blockSignals(True)
        self.sensitivity_comboBox.setCurrentText(str(idx))
        self.sensitivity_comboBox.blockSignals(False)

    def set_auto_scale(self):
        self.logic.stop()
        self.logic.job = "set_auto_scale"
        self.logic.start()

    # -- phase ---------------------------------------------------------
    def set_phase(self, val: float | None = None):
        self.logic.stop()
        self.logic.setpoint_phase = val if val is not None else self.phase_doubleSpinBox.value()
        self.logic.job = "set_phase"
        self.logic.start()

    def get_phase(self):
        self.logic.job = "get_phase"
        self.logic.start()
    
    def set_auto_phase(self):
        self.logic.stop()
        self.logic.job = "set_auto_phase"
        self.logic.start()

    def update_phase(self, val):
        self.phase_doubleSpinBox.blockSignals(True)
        self.phase_doubleSpinBox.setValue(float(val))
        self.phase_doubleSpinBox.blockSignals(False)

    # -- reference mode -----------------------------------------------
    def set_ref_mode(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_ref_mode = self.ref_mode_comboBox.currentText() if idx is None else idx
        self.logic.job = "set_ref_mode"
        self.logic.start()

    def get_ref_mode(self):
        self.logic.job = "get_ref_mode"
        self.logic.start()

    def update_ref_mode(self, idx):
        self.ref_mode_comboBox.blockSignals(True)
        self.ref_mode_comboBox.setCurrentText(idx)
        self.ref_mode_comboBox.blockSignals(False)

    # -- external trigger ---------------------------------------------
    def set_ext_trigger(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_ext_trigger = self.trig_comboBox.currentText() if idx is None else idx
        self.logic.job = "set_ext_trigger"
        self.logic.start()

    def get_ext_trigger(self):
        self.logic.job = "get_ext_trigger"
        self.logic.start()

    def update_ext_trigger(self, idx):
        self.trig_comboBox.blockSignals(True)
        self.trig_comboBox.setCurrentText(idx)
        self.trig_comboBox.blockSignals(False)

    # -- reference input (boolean) ------------------------------------
    def set_ref_input(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_ref_input = idx if idx is not None else self.ext_ref_comboBox.currentIndex()
        self.logic.job = "set_ref_input"
        self.logic.start()

    def get_ref_input(self):
        self.logic.job = "get_ref_input"
        self.logic.start()

    def update_ref_input(self, val):
        self.ref_input_checkBox.blockSignals(True)
        self.ref_input_checkBox.setChecked(bool(val))
        self.ref_input_checkBox.blockSignals(False)

    # -- sync filter (boolean) ----------------------------------------
    def set_sync_filter(self, state: int | None = None):
        self.logic.stop()
        self.logic.setpoint_sync_filter = bool(state) if state is not None else self.sync_filter_checkBox.isChecked()
        self.logic.job = "set_sync_filter"
        self.logic.start()

    def get_sync_filter(self):
        self.logic.job = "get_sync_filter"
        self.logic.start()

    def update_sync_filter(self, val):
        self.sync_filter_checkBox.blockSignals(True)
        self.sync_filter_checkBox.setChecked(bool(val))
        self.sync_filter_checkBox.blockSignals(False)

    # -- harmonic ------------------------------------------------------
    def set_harmonic(self, h: int | None = None):
        self.logic.stop()
        self.logic.setpoint_harmonic = h if h is not None else self.harmonic_spinBox.value()
        self.logic.job = "set_harmonic"
        self.logic.start()

    def get_harmonic(self):
        self.logic.job = "get_harmonic"
        self.logic.start()

    def update_harmonic(self, h):
        self.harmonic_spinBox.blockSignals(True)
        self.harmonic_spinBox.setValue(int(h))
        self.harmonic_spinBox.blockSignals(False)

    # -- signal-input type / mode -------------------------------------
    def get_signal_input_type(self):
        self.logic.job = "get_signal_input_type"
        self.logic.start()

    def update_signal_input_type(self, idx):
        self.input_type_comboBox.blockSignals(True)
        self.input_type_comboBox.setCurrentText(idx)
        self.input_type_comboBox.blockSignals(False)

    def set_signal_input_config(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_input_config        = self.input_config_comboBox.currentText()
        self.logic.setpoint_voltage_input_range = self.voltage_range_comboBox.currentText()
        self.logic.setpoint_current_input_range = self.current_range_comboBox.currentText()
        self.logic.job = "set_signal_input_config"
        self.logic.start()

    def update_signal_input_config(self, idx):
        self.input_config_comboBox.blockSignals(True)
        self.input_config_comboBox.setCurrentText(idx)
        self.input_config_comboBox.blockSignals(False)

    def set_auto_range(self):
        self.logic.stop()
        self.logic.job = "set_auto_range"
        self.logic.start()

    def get_signal_input_mode(self):
        self.logic.job = "get_signal_input_mode"
        self.logic.start()

    def update_signal_input_mode(self, idx):
        self.input_mode_comboBox.blockSignals(True)
        self.input_mode_comboBox.setCurrentText(idx)
        self.input_mode_comboBox.blockSignals(False)

    # -- voltage input coupling / range --------------------------------
    def set_voltage_input_coupling(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_voltage_input_coupling = self.input_coupling_comboBox.currentIndex() if idx is None else idx
        self.logic.job = "set_voltage_input_coupling"
        self.logic.start()

    def get_voltage_input_coupling(self):
        self.logic.job = "get_voltage_input_coupling"
        self.logic.start()

    def update_voltage_input_coupling(self, idx):
        self.input_coupling_comboBox.blockSignals(True)
        self.input_coupling_comboBox.setCurrentText(str(idx))
        self.input_coupling_comboBox.blockSignals(False)

    # def set_voltage_input_range(self, idx: int | None = None):
    #     self.logic.stop()
    #     self.logic.setpoint_voltage_input_range = idx if idx is not None else self.input_range_comboBox.currentIndex()
    #     self.logic.job = "set_voltage_input_range"
    #     self.logic.start()

    def get_voltage_input_range(self):
        self.logic.job = "get_voltage_input_range"
        self.logic.start()

    def update_voltage_input_range(self, idx):
        self.voltage_range_comboBox.blockSignals(True)
        self.voltage_range_comboBox.setCurrentText(idx)
        self.voltage_range_comboBox.blockSignals(False)

    def update_current_input_range(self, idx):
        self.current_range_comboBox.blockSignals(True)
        self.current_range_comboBox.setCurrentText(idx)
        self.current_range_comboBox.blockSignals(False)

    # -- unlocked & overload flags ------------------------------------
    def get_unlocked(self):
        self.logic.job = "get_unlocked"
        self.logic.start()

    def update_unlocked(self, val):
        self.unlocked_radioButton.blockSignals(True)
        self.unlocked_radioButton.setChecked(bool(val))
        self.unlocked_radioButton.blockSignals(False)

    def get_input_overload(self):
        self.logic.job = "get_input_overload"
        self.logic.start()

    def update_input_overload(self, val):
        self.input_ovld_radioButton.blockSignals(True)
        self.input_ovld_radioButton.setChecked(bool(val))
        self.input_ovld_radioButton.blockSignals(False)

    def get_sensitivity_overload(self):
        self.logic.job = "get_sensitivity_overload"
        self.logic.start()
    
    def update_sensitivity_overload(self, val):
        self.sens_ovld_radioButton.blockSignals(True)
        self.sens_ovld_radioButton.setChecked(bool(val))
        self.sens_ovld_radioButton.blockSignals(False)

    # -- outputs streaming --------------------------------------------
    def update_X(self, val):
        self.x_log[:-1] = self.x_log[1:]
        self.x_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_x.plot(self.x_log, clear=True, pen=pen)

    def update_Y(self, val):
        self.y_log[:-1] = self.y_log[1:]
        self.y_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_y.plot(self.y_log, clear=True, pen=pen)

    def update_R(self, val):
        self.r_log[:-1] = self.r_log[1:]
        self.r_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_r.plot(self.r_log, clear=True, pen=pen)

    def update_Theta(self, val):
        self.t_log[:-1] = self.t_log[1:]
        self.t_log[-1] = val
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_t.plot(self.t_log, clear=True, pen=pen)

    # ------------------------------------------------------------------
    # periodic monitor
    # ------------------------------------------------------------------
    def monitor(self):
        if not self.logic.connected:
            return
        if self.logic.isRunning():
            return
        self.logic.job = "get_all"  # bulk helper from sr860_logic
        self.logic.start()

    # ------------------------------------------------------------------
    # stubs for functionality not implemented in sr860_logic
    # ------------------------------------------------------------------
    def set_input_config(self, *_):
        pass

    def get_input_config(self):
        pass

    def update_input_config(self, *_):
        pass

    def set_input_shield(self, *_):
        self.logic.stop()
        self.logic.setpoint_input_shield = self.input_shield_comboBox.currentText()
        self.logic.job = "set_input_shield"
        self.logic.start()

    def get_input_shield(self):
        self.logic.job = "get_input_shield"
        self.logic.start()

    def update_input_shield(self, val):
        self.input_shield_comboBox.blockSignals(True)
        self.input_shield_comboBox.setCurrentText(val)
        self.input_shield_comboBox.blockSignals(False)  

    def set_notch_filter(self, *_):
        self.logic.stop()
        self.logic.job = "set_notch_filter"
        self.logic.start()

    def get_notch_filter(self):
        pass

    def update_notch_filter(self, *_):
        pass

    # -- dc level -----------------------------------------------------
    def set_dc_level(self, val: float | None = None):
        self.logic.stop()
        self.logic.setpoint_dc_level = val if val is not None else self.dclevel_doubleSpinBox.value()
        self.logic.job = "set_dc_level"
        self.logic.start()
    
    def get_dc_level(self):
        self.logic.job = "get_dc_level"
        self.logic.start()
    
    def update_dc_level(self, val):
        self.dclevel_doubleSpinBox.blockSignals(True)
        self.dclevel_doubleSpinBox.setValue(float(val))
        self.dclevel_doubleSpinBox.blockSignals(False)

    def set_dc_level_mode(self, idx: int | None = None):
        self.logic.stop()
        print(self.dclevel_mode_comboBox.currentIndex())
        self.logic.setpoint_dc_level_mode = self.dclevel_mode_comboBox.currentText() if idx is None else idx
        self.logic.job = "set_dc_level_mode"
        self.logic.start()

    def get_dc_level_mode(self):
        self.logic.job = "get_dc_level_mode"
        self.logic.start()

    def update_dc_level_mode(self, idx):
        self.dclevel_mode_comboBox.blockSignals(True)
        self.dclevel_mode_comboBox.setCurrentText(str(idx))
        self.dclevel_mode_comboBox.blockSignals(False)

    # -- filter slope -------------------------------------------------
    def set_filter_slope(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_filter_slope = self.filter_slope_comboBox.currentText() if idx is None else idx
        self.logic.job = "set_filter_slope"
        self.logic.start()
    
    def get_filter_slope(self):
        self.logic.job = "get_filter_slope"
        self.logic.start()
    
    def update_filter_slope(self, idx):
        self.filter_slope_comboBox.blockSignals(True)
        self.filter_slope_comboBox.setCurrentText(str(idx))
        self.filter_slope_comboBox.blockSignals(False)

    # -- reserve ----------------------------------------------------- 
    def set_reserve(self, *_):
        pass

    def get_reserve(self):
        pass

    def update_reserve(self, *_):
        pass

    def set_aux_1(self, *_):
        pass

    def get_aux_1(self):
        pass

    def update_aux_1(self, *_):
        pass

    def set_aux_2(self, *_):
        pass

    def get_aux_2(self):
        pass

    def update_aux_2(self, *_):
        pass

    def get_time_constant_overload(self):
        pass

    def update_time_constant_overload(self, *_):
        pass

    def get_output_overload(self):
        pass

    def update_output_overload(self, *_):
        pass

    def disconnect_device(self):
        """
        Disconnect the SR860 device and update UI accordingly.
        """
        self.logic.disconnect()

    def terminate_dev(self):
        self.logic.disconnect()
        

# ----------------------------------------------------------------------
# Stand-alone entry-point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = SR860()
    # Optionally auto-connect to a default VISA address here
    # window.connect_visa("GPIB0::7::INSTR")
    window.show()
    sys.exit(app.exec())
