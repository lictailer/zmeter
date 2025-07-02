import time
from PyQt6 import QtWidgets, uic, QtCore
import sys
from sr830.sr830_logic import SR830_Logic
import numpy as np
import pyqtgraph as pg
import pyvisa


class SR830(QtWidgets.QWidget):
    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()
    def __init__(self):
        super(SR830, self).__init__()
        uic.loadUi("sr830/sr830.ui", self)
        w = pg.GraphicsLayoutWidget(show=True)
        w.viewport().setAttribute(QtCore.Qt.WidgetAttribute.WA_AcceptTouchEvents, False)
        resource_manager = pyvisa.ResourceManager()
        ls = resource_manager.list_resources()
        self.address_cb.addItems(ls)
        self.plot_x = w.addPlot(row=0, col=0)
        self.plot_y = w.addPlot(row=1, col=0)
        self.plot_r = w.addPlot(row=0, col=1)
        self.plot_t = w.addPlot(row=1, col=1)
        self.plot_x.setTitle('X')
        self.plot_y.setTitle('Y')
        self.plot_r.setTitle('R')
        self.plot_t.setTitle('Theta')
        self.graph_xyrt.addWidget(w)

        self.logic = SR830_Logic()
        self.x_log = np.full(200, np.nan, dtype=float)
        self.y_log = np.full(200, np.nan, dtype=float)
        self.r_log = np.full(200, np.nan, dtype=float)
        self.t_log = np.full(200, np.nan, dtype=float)

        self.logic.sig_frequency.connect(self.update_frequency)
        self.logic.sig_amplitude.connect(self.update_amplitude)
        self.logic.sig_time_constant.connect(self.update_time_constant)
        self.logic.sig_sensitivity.connect(self.update_sensitivity)
        self.logic.sig_phase.connect(self.update_phase)
        self.logic.sig_ref_input.connect(self.update_ref_input)
        self.logic.sig_ext_trigger.connect(self.update_ext_trigger)
        self.logic.sig_sync_filter.connect(self.update_sync_filter)
        self.logic.sig_harmonic.connect(self.update_harmonic)
        self.logic.sig_input_config.connect(self.update_input_config)
        self.logic.sig_input_shield.connect(self.update_input_shield)
        self.logic.sig_input_coupling.connect(self.update_input_coupling)
        self.logic.sig_notch_filter.connect(self.update_notch_filter)
        self.logic.sig_reserve.connect(self.update_reserve)
        self.logic.sig_filter_slope.connect(self.update_filter_slope)
        self.logic.sig_unlocked.connect(self.update_unlocked)
        self.logic.sig_input_overload.connect(self.update_input_overload)
        self.logic.sig_time_constant_overload.connect(self.update_time_constant_overload)
        self.logic.sig_output_overload.connect(self.update_output_overload)
        self.logic.sig_X.connect(self.update_X)
        self.logic.sig_Y.connect(self.update_Y)
        self.logic.sig_R.connect(self.update_R)
        self.logic.sig_Theta.connect(self.update_Theta)

        self.logic.sig_is_changing.connect(self.update_label)
        self.logic.sig_connected.connect(self.update_label)

        self.freq_doubleSpinBox.valueChanged.connect(self.set_frequency)
        self.ampl_doubleSpinBox.valueChanged.connect(self.set_amplitude)
        self.time_constant_comboBox.currentIndexChanged.connect(self.set_time_constant)
        self.sensitivity_comboBox.currentIndexChanged.connect(self.set_sensitivity)
        self.phase_doubleSpinBox.valueChanged.connect(self.set_phase)
        self.ref_comboBox.currentIndexChanged.connect(self.set_ref_input)
        self.trig_comboBox.currentIndexChanged.connect(self.set_ext_trigger)
        self.sync_200hz_checkBox.stateChanged.connect(self.set_sync_filter)
        self.harmonics_spinBox.valueChanged.connect(self.set_harmonic)
        self.input_config_comboBox.currentIndexChanged.connect(self.set_input_config)
        self.input_shield_comboBox.currentIndexChanged.connect(self.set_input_shield)
        self.input_coupling_comboBox.currentIndexChanged.connect(self.set_input_coupling)
        self.notch_filter_comboBox.currentIndexChanged.connect(self.set_notch_filter)
        self.reserve_comboBox.currentIndexChanged.connect(self.set_reserve)
        self.filter_slope_comboBox.currentIndexChanged.connect(self.set_filter_slope)

        self.connect_pushButton.clicked.connect(self.connect_visa)
        self.start_scanning.clicked.connect(self.stop_timer)
        self.stop_scanning.clicked.connect(self.start_timer)
        self.reset_graph.clicked.connect(self.Reset_graph)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.monitor)
        self.timer.start(50)  # time in milliseconds.

        self.stop_signal.connect(self.stop_timer)
    def Reset_graph(self):
        self.x_log = np.full(200, np.nan, dtype=float)
        self.y_log = np.full(200, np.nan, dtype=float)
        self.r_log = np.full(200, np.nan, dtype=float)
        self.t_log = np.full(200, np.nan, dtype=float)
        pen1 = pg.mkPen((255, 255, 255), width=3)
        self.plot_x.plot(self.x_log, clear=True, pen=pen1)
        self.plot_y.plot(self.y_log, clear=True, pen=pen1)
        self.plot_r.plot(self.r_log, clear=True, pen=pen1)
        self.plot_t.plot(self.t_log, clear=True, pen=pen1)

    def force_stop(self):
        self.logic.reject_siginal = True


    def stop_timer(self):
        if self.timer.isActive():
            self.timer.stop()

    def start_timer(self):
        if not self.timer.isActive():
            self.timer.start(50)
            "timer started"

    def stop_scan(self):
        self.stop_signal.emit()
    

    def start_scan(self):
        self.start_signal.emit()
        "started"

    def update_label(self, str):
        self.label_5.setText(str)

    def connect_visa(self, addr = None):
        if addr == None:
            addr = self.address_cb.currentText()
        self.logic.connect_visa(addr)
        self.address_cb.setCurrentText(addr)

    ####### channles with both set and get #######

    def set_frequency(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val==None:
            self.logic.setpoint_frequency = self.freq_doubleSpinBox.value()
        else:
            self.logic.setpoint_frequency=val
            print("frequency set to", val)
        self.logic.job = "set_frequency"
        self.logic.start()
        # self.logic.job = "set_frequency"
        # self.logic.start()

    def get_frequency(self):
        self.logic.job = "get_frequency"
        self.logic.start()

    def update_frequency(self, info):
        self.freq_doubleSpinBox.blockSignals(True)
        self.freq_doubleSpinBox.setValue(float(info))
        self.freq_doubleSpinBox.blockSignals(False)

    def set_amplitude(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val==None:
            self.logic.setpoint_amplitude = self.ampl_doubleSpinBox.value()
            
        else:
            self.logic.setpoint_amplitude = val
            # print("amplitude set to", val)
        self.logic.job = "set_amplitude"
        self.logic.start()
        # self.logic.job = "set_amplitude"
        # self.logic.start()

    def get_amplitude(self):
        self.logic.job = "get_amplitude"
        self.logic.start()

    def update_amplitude(self, info):
        self.ampl_doubleSpinBox.blockSignals(True)
        self.ampl_doubleSpinBox.setValue(float(info))
        self.ampl_doubleSpinBox.blockSignals(False)

    def set_time_constant(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_time_constant = val
            print("time_constant set to", val)
        else:
            self.logic.setpoint_time_constant = self.time_constant_comboBox.currentIndex()
        self.logic.job = "set_time_constant"
        self.logic.start()

    def get_time_constant(self):
        self.logic.job = "get_time_constant"
        self.logic.start()

    def update_time_constant(self, info):
        self.time_constant_comboBox.blockSignals(True)
        self.time_constant_comboBox.setCurrentIndex(int(info))
        self.time_constant_comboBox.blockSignals(False)

    def set_sensitivity(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_sensitivity = val
            print("sensitivity set to", val)
        else:
            self.logic.setpoint_sensitivity = self.sensitivity_comboBox.currentIndex()
        self.logic.job = "set_sensitivity"
        self.logic.start()

    def get_sensitivity(self):
        self.logic.job = "get_sensitivity"
        self.logic.start()

    def update_sensitivity(self, info):
        self.sensitivity_comboBox.blockSignals(True)
        self.sensitivity_comboBox.setCurrentIndex(int(info))
        self.sensitivity_comboBox.blockSignals(False)

    def set_phase(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val==None:
            self.logic.setpoint_phase = self.phase_doubleSpinBox.value()
            
        else:
            self.logic.setpoint_phase = val
            # print("phase set to", val)
        self.logic.job = "set_phase"
        self.logic.start()
        # self.logic.job = "set_phase"
        # self.logic.start()

    def get_phase(self):
        self.logic.job = "get_phase"
        self.logic.start()

    def update_phase(self, info):
        self.phase_doubleSpinBox.blockSignals(True)
        self.phase_doubleSpinBox.setValue(float(info))
        self.phase_doubleSpinBox.blockSignals(False)

    def set_ref_input(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_ref_input = val
        else:
            self.logic.setpoint_ref_input = self.ref_comboBox.currentIndex()
        self.logic.job = "set_ref_input"
        self.logic.start()

    def get_ref_input(self):
        self.logic.job = "get_ref_input"
        self.logic.start()

    def update_ref_input(self, info):
        self.ref_comboBox.blockSignals(True)
        self.ref_comboBox.setCurrentIndex(int(info))
        self.ref_comboBox.blockSignals(False)

    def set_ext_trigger(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_ext_trigger = val
        else:
            self.logic.setpoint_ext_trigger = self.trig_comboBox.currentIndex()
        self.logic.job = "set_ext_trigger"
        self.logic.start()

    def get_ext_trigger(self):
        self.logic.job = "get_ext_trigger"
        self.logic.start()

    def update_ext_trigger(self, info):
        self.trig_comboBox.blockSignals(True)
        self.trig_comboBox.setCurrentIndex(int(info))
        self.trig_comboBox.blockSignals(False)

    def set_sync_filter(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_sync_filter = val
        else:
            self.logic.setpoint_sync_filter = self.sync_200hz_checkBox.isChecked()
        self.logic.job = "set_sync_filter"
        self.logic.start()

    def get_sync_filter(self):
        self.logic.job = "get_sync_filter"
        self.logic.start()

    def update_sync_filter(self, info):
        self.sync_200hz_checkBox.blockSignals(True)
        self.sync_200hz_checkBox.setChecked(int(info))
        self.sync_200hz_checkBox.blockSignals(False)

    def set_harmonic(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_harmonic = val
        else:
            self.logic.setpoint_harmonic = self.harmonics_spinBox.value()
        self.logic.job = "set_harmonic"
        self.logic.start()

    def get_harmonic(self):
        self.logic.job = "get_harmonic"
        self.logic.start()

    def update_harmonic(self, info):
        self.harmonics_spinBox.blockSignals(True)
        self.harmonics_spinBox.setValue(int(info))
        self.harmonics_spinBox.blockSignals(False)

    def set_input_config(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_input_config = val
        else:
            self.logic.setpoint_input_config = self.input_config_comboBox.currentIndex()
        self.logic.job = "set_input_config"
        self.logic.start()

    def get_input_config(self):
        self.logic.job = "get_input_config"
        self.logic.start()

    def update_input_config(self, info):
        self.input_config_comboBox.blockSignals(True)
        self.input_config_comboBox.setCurrentIndex(int(info))
        self.input_config_comboBox.blockSignals(False)

    def set_input_shield(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_input_shield = val
        else:
            self.logic.setpoint_input_shield = self.input_shield_comboBox.currentIndex()
        self.logic.job = "set_input_shield"
        self.logic.start()

    def get_input_shield(self):
        self.logic.job = "get_input_shield"
        self.logic.start()

    def update_input_shield(self, info):
        self.input_shield_comboBox.blockSignals(True)
        self.input_shield_comboBox.setCurrentIndex(int(info))
        self.input_shield_comboBox.blockSignals(False)

    def set_input_coupling(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_input_coupling = val
        else:
            self.logic.setpoint_input_coupling = self.input_coupling_comboBox.currentIndex()
        self.logic.job = "set_input_coupling"
        self.logic.start()

    def get_input_coupling(self):
        self.logic.job = "get_input_coupling"
        self.logic.start()

    def update_input_coupling(self, info):
        self.input_coupling_comboBox.blockSignals(True)
        self.input_coupling_comboBox.setCurrentIndex(int(info))
        self.input_coupling_comboBox.blockSignals(False)

    def set_notch_filter(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_notch_filter = val
        else:
            self.logic.setpoint_notch_filter = self.notch_filter_comboBox.currentIndex()
        self.logic.job = "set_notch_filter"
        self.logic.start()

    def get_notch_filter(self):
        self.logic.job = "get_notch_filter"
        self.logic.start()

    def update_notch_filter(self, info):
        self.notch_filter_comboBox.blockSignals(True)
        self.notch_filter_comboBox.setCurrentIndex(int(info))
        self.notch_filter_comboBox.blockSignals(False)

    def set_reserve(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_reserve = val
        else:
            self.logic.setpoint_reserve = self.reserve_comboBox.currentIndex()
        self.logic.job = "set_reserve"
        self.logic.start()

    def get_reserve(self):
        self.logic.job = "get_reserve"
        self.logic.start()

    def update_reserve(self, info):
        self.reserve_comboBox.blockSignals(True)
        self.reserve_comboBox.setCurrentIndex(int(info))
        self.reserve_comboBox.blockSignals(False)

    def set_filter_slope(self,val=None):
        self.logic.monitoring_receieved_stop = True
        self.logic.stop()
        if val:
            self.logic.setpoint_filter_slope = val
        else:
            self.logic.setpoint_filter_slope = self.filter_slope_comboBox.currentIndex()
        self.logic.job = "set_filter_slope"
        self.logic.start()

    def get_filter_slope(self):
        self.logic.job = "get_filter_slope"
        self.logic.start()

    def update_filter_slope(self, info):
        self.filter_slope_comboBox.blockSignals(True)
        self.filter_slope_comboBox.setCurrentIndex(int(info))
        self.filter_slope_comboBox.blockSignals(False)

    def set_aux_1(self,val=None):
        self.logic.setpoint_aux_1= val
        self.logic.set_aux_1()
        print("aux_1 set to", val)
    
    def get_aux_1(self):
        self.logic.job = "get_aux_1"
        self.logic.start()

    def set_aux_2(self,val=None):
        self.logic.setpoint_aux_2 = val
        self.logic.set_aux_2()
        print("aux_2 set to", val)

    def get_aux_2(self):
        self.logic.job = "get_aux_2"
        self.logic.start()

    ####### channles with with only get #######
#     "unlocked",
#     "input_overload",
#     "time_constant_overload",
#     "output_overload",
#     "X",
#     "Y",
#     "R",
#     "Theta",

    def get_unlocked(self):
        self.logic.job = "get_unlocked"
        self.logic.start()

    def update_unlocked(self, info):
        self.unlocked_radioButton.blockSignals(True)
        self.unlocked_radioButton.setChecked(int(info))
        self.unlocked_radioButton.blockSignals(False)

    def get_input_overload(self):
        self.logic.job = "get_input_overload"
        self.logic.start()

    def update_input_overload(self, info):
        self.input_ovld_radioButton.blockSignals(True)
        self.input_ovld_radioButton.setChecked(int(info))
        self.input_ovld_radioButton.blockSignals(False)

    def get_time_constant_overload(self):
        self.logic.job = "get_time_constant_overload"
        self.logic.start()

    def update_time_constant_overload(self, info):
        self.tc_ovld_radioButton.blockSignals(True)
        self.tc_ovld_radioButton.setChecked(int(info))
        self.tc_ovld_radioButton.blockSignals(False)

    def get_output_overload(self):
        self.logic.job = "get_output_overload"
        self.logic.start()

    def update_output_overload(self, info):
        self.sens_ovld_radioButton.blockSignals(True)
        self.sens_ovld_radioButton.setChecked(int(info))
        self.sens_ovld_radioButton.blockSignals(False)

    #
    def get_X(self):
        self.logic.job = "get_X"
        self.logic.start()

    def update_X(self, info):
        self.x_log[0:-1] = self.x_log[1:]
        self.x_log[-1] = info
        pen1 = pg.mkPen((255, 255, 255), width=3)
        self.plot_x.plot(self.x_log, clear=True, pen=pen1)
        

    #
    def get_Y(self):
        self.logic.job = "get_Y"
        self.logic.start()

    def update_Y(self, info):
        self.y_log[0:-1] = self.y_log[1:]
        self.y_log[-1] = info
        pen1 = pg.mkPen((255, 255, 255), width=3)
        self.plot_y.plot(self.y_log, clear=True, pen=pen1)

    #
    def get_R(self):
        self.logic.job = "get_R"
        self.logic.start()

    def update_R(self, info):
        self.r_log[0:-1] = self.r_log[1:]
        self.r_log[-1] = info
        pen1 = pg.mkPen((255, 255, 255), width=3)
        self.plot_r.plot(self.r_log, clear=True, pen=pen1)

    #
    def get_Theta(self):
        self.logic.job = "get_Theta"
        self.logic.start()

    def update_Theta(self, info):
        self.t_log[0:-1] = self.t_log[1:]
        self.t_log[-1] = info
        pen1 = pg.mkPen((255, 255, 255), width=3)
        self.plot_t.plot(self.t_log, clear=True, pen=pen1)



    ###
    def monitor(self):
        if not self.logic.connected:
            return
        if self.logic.isRunning():
            return
        self.logic.job = 'get_all'
        self.logic.start()

    def terminate_dev(self):
        print("SR830 terminated.")

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = SR830()
    window.connect_visa("GPIB0::7::INSTR")
    window.show()
    app.exec()

