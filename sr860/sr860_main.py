from PyQt6 import QtWidgets, uic, QtCore
import sys
import time
import numpy as np
import pyqtgraph as pg
import pyvisa

from sr860_logic import SR860_Logic


class SR860(QtWidgets.QWidget):
    """Qt GUI wrapper for SR860 lock-in amplifier.

    The class is heavily inspired by *sr830_main.SR830* but follows the
    new **sr860_logic** naming rules (read_*/write_*/setup_*).  Where the
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
        self.logic.sig_input_config.connect(self.update_input_config)
        self.logic.sig_voltage_input_coupling.connect(self.update_voltage_input_coupling)
        self.logic.sig_voltage_input_range.connect(self.update_voltage_input_range)
        self.logic.sig_unlocked.connect(self.update_unlocked)
        self.logic.sig_input_overload.connect(self.update_input_overload)
        self.logic.sig_X.connect(self.update_X)
        self.logic.sig_Y.connect(self.update_Y)
        self.logic.sig_R.connect(self.update_R)
        self.logic.sig_Theta.connect(self.update_Theta)
        self.logic.sig_is_changing.connect(self.update_status)
        self.logic.sig_connected.connect(self.update_status)

        # ----- connect UI widgets to read/write/setup actions -----
        self.freq_doubleSpinBox.valueChanged.connect(self.write_frequency)
        self.ampl_doubleSpinBox.valueChanged.connect(self.write_amplitude)
        self.time_constant_comboBox.currentIndexChanged.connect(self.write_time_constant)
        self.sensitivity_comboBox.currentIndexChanged.connect(self.write_sensitivity)
        self.phase_doubleSpinBox.valueChanged.connect(self.write_phase)
        self.ref_mode_comboBox.currentIndexChanged.connect(self.write_ref_mode)
        self.trig_comboBox.currentIndexChanged.connect(self.write_ext_trigger)
        self.ext_ref_comboBox.currentIndexChanged.connect(self.setup_ref_input)
        self.sync_200hz_checkBox.stateChanged.connect(self.setup_sync_filter)
        self.harmonic_spinBox.valueChanged.connect(self.write_harmonic)
        # voltage / signal input helpers
        self.input_config_comboBox.currentIndexChanged.connect(self.write_signal_input_config)
        self.voltage_range_comboBox.currentIndexChanged.connect(self.write_signal_input_config)
        self.current_range_comboBox.currentIndexChanged.connect(self.write_signal_input_config)

        self.input_coupling_comboBox.currentIndexChanged.connect(self.write_voltage_input_coupling)
        # self.input_range_comboBox.currentIndexChanged.connect(self.write_voltage_input_range)

        self.connect_pushButton.clicked.connect(self.connect_visa)
        self.pause_graph_button.clicked.connect(self.stop_timer)
        self.resume_graph_button.clicked.connect(self.start_timer)
        self.reset_graph_button.clicked.connect(self.reset_graph)

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
    def connect_visa(self, addr: str | None = None):
        if addr is None or False:
            addr = self.address_cb.currentText()
        print(f"Connecting to {addr}")
        self.logic.connect_visa(addr)
        self.address_cb.setCurrentText(addr)

    # ------------------------------------------------------------------
    # read_/write_/setup_ wrappers (naming follows sr860_logic)
    # ------------------------------------------------------------------
    def write_frequency(self, val: float | None = None):
        self.logic.stop()
        self.logic.setpoint_frequency = val if val is not None else self.freq_doubleSpinBox.value()
        self.logic.job = "write_frequency"
        self.logic.start()

    def read_frequency(self):
        self.logic.job = "read_frequency"
        self.logic.start()

    def update_frequency(self, val):
        self.freq_doubleSpinBox.blockSignals(True)
        self.freq_doubleSpinBox.setValue(float(val))
        self.freq_doubleSpinBox.blockSignals(False)

    # -- amplitude -----------------------------------------------------
    def write_amplitude(self, val: float | None = None):
        self.logic.stop()
        self.logic.setpoint_amplitude = val if val is not None else self.ampl_doubleSpinBox.value()
        self.logic.job = "write_amplitude"
        self.logic.start()

    def read_amplitude(self):
        self.logic.job = "read_amplitude"
        self.logic.start()

    def update_amplitude(self, val):
        self.ampl_doubleSpinBox.blockSignals(True)
        self.ampl_doubleSpinBox.setValue(float(val))
        self.ampl_doubleSpinBox.blockSignals(False)

    # -- time-constant -------------------------------------------------
    def write_time_constant(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_time_constant = idx if idx is not None else self.time_constant_comboBox.currentIndex()
        self.logic.job = "write_time_constant"
        self.logic.start()

    def read_time_constant(self):
        self.logic.job = "read_time_constant"
        self.logic.start()

    def update_time_constant(self, idx):
        self.time_constant_comboBox.blockSignals(True)
        print("idx", idx)
        self.time_constant_comboBox.setCurrentText(idx)
        self.time_constant_comboBox.blockSignals(False)

    # -- sensitivity ---------------------------------------------------
    def write_sensitivity(self, idx: int | None = None):
        self.logic.stop()
        print("isRunning", self.logic.isRunning())
        self.logic.setpoint_sensitivity = idx if idx is not None else self.sensitivity_comboBox.currentIndex()
        print("setpoint_sensitivity", self.logic.setpoint_sensitivity)
        self.logic.job = "write_sensitivity"
        self.logic.start()
        self.start_timer()

    def read_sensitivity(self):
        self.logic.job = "read_sensitivity"
        self.logic.start()

    def update_sensitivity(self, idx):
        self.sensitivity_comboBox.blockSignals(True)
        self.sensitivity_comboBox.setCurrentText(idx)
        self.sensitivity_comboBox.blockSignals(False)

    # -- phase ---------------------------------------------------------
    def write_phase(self, val: float | None = None):
        self.logic.stop()
        self.logic.setpoint_phase = val if val is not None else self.phase_doubleSpinBox.value()
        self.logic.job = "write_phase"
        self.logic.start()

    def read_phase(self):
        self.logic.job = "read_phase"
        self.logic.start()

    def update_phase(self, val):
        self.phase_doubleSpinBox.blockSignals(True)
        self.phase_doubleSpinBox.setValue(float(val))
        self.phase_doubleSpinBox.blockSignals(False)

    # -- reference mode -----------------------------------------------
    def write_ref_mode(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_ref_mode = idx if idx is not None else self.ref_mode_comboBox.currentIndex()
        self.logic.job = "write_ref_mode"
        self.logic.start()

    def read_ref_mode(self):
        self.logic.job = "read_ref_mode"
        self.logic.start()

    def update_ref_mode(self, idx):
        self.ref_mode_comboBox.blockSignals(True)
        self.ref_mode_comboBox.setCurrentText(idx)
        self.ref_mode_comboBox.blockSignals(False)

    # -- external trigger ---------------------------------------------
    def write_ext_trigger(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_ext_trigger = idx if idx is not None else self.trig_comboBox.currentIndex()
        self.logic.job = "write_ext_trigger"
        self.logic.start()

    def read_ext_trigger(self):
        self.logic.job = "read_ext_trigger"
        self.logic.start()

    def update_ext_trigger(self, idx):
        self.trig_comboBox.blockSignals(True)
        self.trig_comboBox.setCurrentText(idx)
        self.trig_comboBox.blockSignals(False)

    # -- reference input (boolean) ------------------------------------
    def setup_ref_input(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_ref_input = idx if idx is not None else self.ext_ref_comboBox.currentIndex()
        self.logic.job = "setup_ref_input"
        self.logic.start()

    def read_ref_input(self):
        self.logic.job = "read_ref_input"
        self.logic.start()

    def update_ref_input(self, val):
        self.ref_input_checkBox.blockSignals(True)
        self.ref_input_checkBox.setChecked(bool(val))
        self.ref_input_checkBox.blockSignals(False)

    # -- sync filter (boolean) ----------------------------------------
    def setup_sync_filter(self, state: int | None = None):
        self.logic.stop()
        self.logic.setpoint_sync_filter = bool(state) if state is not None else self.sync_200hz_checkBox.isChecked()
        self.logic.job = "setup_sync_filter"
        self.logic.start()

    def read_sync_filter(self):
        self.logic.job = "read_sync_filter"
        self.logic.start()

    def update_sync_filter(self, val):
        self.sync_200hz_checkBox.blockSignals(True)
        self.sync_200hz_checkBox.setChecked(bool(val))
        self.sync_200hz_checkBox.blockSignals(False)

    # -- harmonic ------------------------------------------------------
    def write_harmonic(self, h: int | None = None):
        self.logic.stop()
        self.logic.setpoint_harmonic = h if h is not None else self.harmonic_spinBox.value()
        self.logic.job = "write_harmonic"
        self.logic.start()

    def read_harmonic(self):
        self.logic.job = "read_harmonic"
        self.logic.start()

    def update_harmonic(self, h):
        self.harmonic_spinBox.blockSignals(True)
        self.harmonic_spinBox.setValue(int(h))
        self.harmonic_spinBox.blockSignals(False)

    # -- signal-input type / mode -------------------------------------
    def read_signal_input_type(self):
        self.logic.job = "read_signal_input_type"
        self.logic.start()

    def update_signal_input_type(self, idx):
        self.input_type_comboBox.blockSignals(True)
        self.input_type_comboBox.setCurrentText(idx)
        self.input_type_comboBox.blockSignals(False)

    def write_signal_input_config(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_input_config = idx if idx is not None else self.input_config_comboBox.currentText()
        self.logic.setpoint_voltage_input_range = idx if idx is not None else self.voltage_range_comboBox.currentText()
        self.logic.setpoint_current_input_range = idx if idx is not None else self.current_range_comboBox.currentText()
        self.logic.job = "write_signal_input_config"
        self.logic.start()

    def read_signal_input_mode(self):
        self.logic.job = "read_signal_input_mode"
        self.logic.start()

    def update_signal_input_mode(self, idx):
        self.input_mode_comboBox.blockSignals(True)
        self.input_mode_comboBox.setCurrentText(idx)
        self.input_mode_comboBox.blockSignals(False)

    # -- voltage input coupling / range --------------------------------
    def write_voltage_input_coupling(self, idx: int | None = None):
        self.logic.stop()
        self.logic.setpoint_voltage_input_coupling = idx if idx is not None else self.input_coupling_comboBox.currentIndex()
        self.logic.job = "write_voltage_input_coupling"
        self.logic.start()

    def read_voltage_input_coupling(self):
        self.logic.job = "read_voltage_input_coupling"
        self.logic.start()

    def update_voltage_input_coupling(self, idx):
        self.input_coupling_comboBox.blockSignals(True)
        self.input_coupling_comboBox.setCurrentText(idx)
        self.input_coupling_comboBox.blockSignals(False)

    # def write_voltage_input_range(self, idx: int | None = None):
    #     self.logic.stop()
    #     self.logic.setpoint_voltage_input_range = idx if idx is not None else self.input_range_comboBox.currentIndex()
    #     self.logic.job = "write_voltage_input_range"
    #     self.logic.start()

    def read_voltage_input_range(self):
        self.logic.job = "read_voltage_input_range"
        self.logic.start()

    def update_voltage_input_range(self, idx):
        self.voltage_range_comboBox.blockSignals(True)
        self.voltage_range_comboBox.setCurrentText(idx)
        self.voltage_range_comboBox.blockSignals(False)

    # -- unlocked & overload flags ------------------------------------
    def read_unlocked(self):
        self.logic.job = "read_unlocked"
        self.logic.start()

    def update_unlocked(self, val):
        self.unlocked_radioButton.blockSignals(True)
        self.unlocked_radioButton.setChecked(bool(val))
        self.unlocked_radioButton.blockSignals(False)

    def read_input_overload(self):
        self.logic.job = "read_input_overload"
        self.logic.start()

    def update_input_overload(self, val):
        self.input_ovld_radioButton.blockSignals(True)
        self.input_ovld_radioButton.setChecked(bool(val))
        self.input_ovld_radioButton.blockSignals(False)

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
    def write_input_config(self, *_):
        pass

    def read_input_config(self):
        pass

    def update_input_config(self, *_):
        pass

    def write_input_shield(self, *_):
        pass

    def read_input_shield(self):
        pass

    def update_input_shield(self, *_):
        pass

    def write_notch_filter(self, *_):
        pass

    def read_notch_filter(self):
        pass

    def update_notch_filter(self, *_):
        pass

    def write_reserve(self, *_):
        pass

    def read_reserve(self):
        pass

    def update_reserve(self, *_):
        pass

    def write_filter_slope(self, *_):
        pass

    def read_filter_slope(self):
        pass

    def update_filter_slope(self, *_):
        pass

    def write_aux_1(self, *_):
        pass

    def read_aux_1(self):
        pass

    def update_aux_1(self, *_):
        pass

    def write_aux_2(self, *_):
        pass

    def read_aux_2(self):
        pass

    def update_aux_2(self, *_):
        pass

    def read_time_constant_overload(self):
        pass

    def update_time_constant_overload(self, *_):
        pass

    def read_output_overload(self):
        pass

    def update_output_overload(self, *_):
        pass


# ----------------------------------------------------------------------
# Stand-alone entry-point
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = SR860()
    # Optionally auto-connect to a default VISA address here
    window.connect_visa("GPIB0::7::INSTR")
    window.show()
    sys.exit(app.exec())
