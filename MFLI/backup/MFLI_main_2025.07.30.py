from PyQt6 import QtWidgets, QtCore
from PyQt6.uic.load_ui import loadUi
import sys
import time
import numpy as np
import pyqtgraph as pg


from MFLI_logic import MFLI_Logic


class MFLI(QtWidgets.QWidget):
    """Qt GUI wrapper for MFLI lock-in amplifier.
    """

    stop_signal = QtCore.pyqtSignal()
    start_signal = QtCore.pyqtSignal()


    def __init__(self):
        super().__init__()

        # ----- load UI -----
        loadUi("MFLI/MFLI.ui", self)

        # ----- logic / model layer -----
        self.logic = MFLI_Logic()

        # ----- helper plot widget (X, Y, R, Theta streams) -----
        # ----- connect to MFLI -----
        self.address_comboBox.addItems(self.logic.get_available_devices())  # type: ignore
        #circular buffers for live plot

        # ----- self defined get and set methods -----
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
        print("get_methods")
        print(self.get_methods)
        print(self.set_methods)
        # ----- connect UI signals to logic methods -----   
        self.connect_pushButton.clicked.connect(self.connect_device)  # type: ignore
        self.disconnect_pushButton.clicked.connect(self.disconnect_device)  # type: ignore
        self.output_enable_checkBox.stateChanged.connect(self.set_output_enable)  # type: ignore
        self.differential_output_checkBox.stateChanged.connect(self.set_differential_output)  # type: ignore
        
        self.osc1_output_enable_checkBox.stateChanged.connect(self.set_osc1_output_enable)  # type: ignore
        self.osc2_output_enable_checkBox.stateChanged.connect(self.set_osc2_output_enable)  # type: ignore
        self.osc3_output_enable_checkBox.stateChanged.connect(self.set_osc3_output_enable)  # type: ignore
        self.osc4_output_enable_checkBox.stateChanged.connect(self.set_osc4_output_enable)  # type: ignore
        

        self.frequency1_spinBox.editingFinished.connect(self.set_frequency1)
        self.frequency2_spinBox.editingFinished.connect(self.set_frequency2)
        self.frequency3_spinBox.editingFinished.connect(self.set_frequency3)
        self.frequency4_spinBox.editingFinished.connect(self.set_frequency4)

        self.amplitude1_spinBox.editingFinished.connect(self.set_amplitude1)
        self.amplitude1_spinBox.setKeyboardTracking(False) #type: ignore

        self.amplitude2_spinBox.editingFinished.connect(self.set_amplitude2)
        self.amplitude3_spinBox.editingFinished.connect(self.set_amplitude3)
        self.amplitude4_spinBox.editingFinished.connect(self.set_amplitude4)

        self.phase1_spinBox.editingFinished.connect(self.set_phase1)
        self.phase2_spinBox.editingFinished.connect(self.set_phase2)
        self.phase3_spinBox.editingFinished.connect(self.set_phase3)
        self.phase4_spinBox.editingFinished.connect(self.set_phase4)

        self.dc_offset_spinBox.editingFinished.connect(self.set_dc_offset)
        self.preset_pushButton.clicked.connect(self.preset)
        self.output_autorange_checkBox.stateChanged.connect(self.set_output_autorange)
        self.output_range_comboBox.currentTextChanged.connect(self.set_output_range)

        # ----- connect signals to logic methods -----
        self.logic.sig_is_changing.connect(self.update_status)
        self.logic.sig_connected.connect(self.update_status)
        self.logic.sig_output_enable.connect(self.update_output_enable)
        self.logic.sig_differential_output.connect(self.update_differential_output)
        
        self.logic.sig_osc1_output_enable.connect(self.update_osc1_output_enable)
        self.logic.sig_osc2_output_enable.connect(self.update_osc2_output_enable)
        self.logic.sig_osc3_output_enable.connect(self.update_osc3_output_enable)
        self.logic.sig_osc4_output_enable.connect(self.update_osc4_output_enable)
        
        self.logic.sig_frequency1.connect(self.update_frequency1)
        self.logic.sig_frequency2.connect(self.update_frequency2)
        self.logic.sig_frequency3.connect(self.update_frequency3)
        self.logic.sig_frequency4.connect(self.update_frequency4)
        
        self.logic.sig_amplitude1.connect(self.update_amplitude1)
        self.logic.sig_amplitude2.connect(self.update_amplitude2)
        self.logic.sig_amplitude3.connect(self.update_amplitude3)
        self.logic.sig_amplitude4.connect(self.update_amplitude4)
        
        self.logic.sig_phase1.connect(self.update_phase1)
        self.logic.sig_phase2.connect(self.update_phase2)
        self.logic.sig_phase3.connect(self.update_phase3)
        self.logic.sig_phase4.connect(self.update_phase4)

        self.logic.sig_dc_offset.connect(self.update_dc_offset)
        self.logic.sig_preset_basic.connect(self.preset)
        self.logic.sig_output_autorange.connect(self.update_output_autorange)
        self.logic.sig_output_range.connect(self.update_output_range)


        # ----- periodic monitor -----
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.monitor)
        self.timer.start(50)
        self.stop_signal.connect(self.stop_timer)
        

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    '''def reset_graph(self):
        self.x_log[:] = np.nan
        self.y_log[:] = np.nan
        self.r_log[:] = np.nan
        self.t_log[:] = np.nan
        pen = pg.mkPen((255, 255, 255), width=3)
        self.plot_x.plot(self.x_log, clear=True, pen=pen)
        self.plot_y.plot(self.y_log, clear=True, pen=pen)
        self.plot_r.plot(self.r_log, clear=True, pen=pen)
        self.plot_t.plot(self.t_log, clear=True, pen=pen)
    '''
    def stop_timer(self):
        if self.timer.isActive():
            self.timer.stop()
    def start_timer(self):
        if not self.timer.isActive():
            self.timer.start(50)
    def update_status(self, txt):
        """Generic label updater for *sig_is_changing* & *sig_connected*."""
        self.status_label.setText(str(txt))  # type: ignore

    def monitor(self):
        if not self.logic.connected:
            return
        if self.logic.isRunning():
            return
        self.logic.job = "get_all"  # bulk helper from MFLI_logic
        self.logic.start()

    def connect_device(self, addr=None):
        if addr is None or addr is False:
            addr = self.address_comboBox.currentText()  # type: ignore
        print(f"Connecting to {addr}")
        self.logic.connect_device(device_id = addr) 
        self.address_comboBox.setCurrentText(addr)  # type: ignore

    def disconnect_device(self):
        self.logic.disconnect_device()   
    def terminate_dev(self):
        self.logic.disconnect_device()
        print("MFLI terminated.")

    # get_/set_ wrappers (naming follows MFLI_logic)
    def set_output_enable(self, state = None):
        self.logic.stop()
        self.logic.setpoint_output_enable = bool(state) if state is not None else self.output_enable_checkBox.isChecked()  # type: ignore
        self.logic.job = "set_output_enable"
        self.logic.start()
    def get_output_enable(self):    
        self.logic.job = "get_output_enable"
        self.logic.start() 
    def update_output_enable(self, state):
        self.output_enable_checkBox.blockSignals(True)  # type: ignore
        self.output_enable_checkBox.setChecked(bool(state))  # type: ignore
        self.output_enable_checkBox.blockSignals(False)  # type: ignore

    def set_differential_output(self, state = None):
        self.logic.stop()
        self.logic.setpoint_differential_output = bool(state) if state is not None else self.differential_output_checkBox.isChecked()  # type: ignore
        self.logic.job = "set_differential_output"
        self.logic.start()
    def get_differential_output(self):
        self.logic.job = "get_differential_output"
        self.logic.start()
    def update_differential_output(self, state):
        self.differential_output_checkBox.blockSignals(True)  # type: ignore
        self.differential_output_checkBox.setChecked(bool(state))  # type: ignore
        self.differential_output_checkBox.blockSignals(False)  # type: ignore
    
    def set_osc1_output_enable(self, state = None):
        self.logic.stop()
        if state is not None:
            val = bool(state)
        else:
            val = self.osc1_output_enable_checkBox.isChecked()  # type: ignore
        self.logic.setpoint_osc1_output_enable = val
        self.logic.job = "set_osc1_output_enable"
        self.logic.start()
        
    def get_osc1_output_enable(self):
        self.logic.job = "get_osc1_output_enable"   
        self.logic.start()
    def update_osc1_output_enable(self, state):
        self.osc1_output_enable_checkBox.blockSignals(True)  # type: ignore
        self.osc1_output_enable_checkBox.setChecked(bool(state))  # type: ignore
        self.osc1_output_enable_checkBox.blockSignals(False)  # type: ignore
    def set_osc2_output_enable(self, state = None):
        self.logic.stop()
        self.logic.setpoint_osc2_output_enable = bool(state) if state is not None else self.osc2_output_enable_checkBox.isChecked()  # type: ignore
        self.logic.job = "set_osc2_output_enable"
        self.logic.start()
    def get_osc2_output_enable(self):
        self.logic.job = "get_osc2_output_enable"
        self.logic.start()  
    def update_osc2_output_enable(self, state):
        self.osc2_output_enable_checkBox.blockSignals(True)  # type: ignore
        self.osc2_output_enable_checkBox.setChecked(bool(state))  # type: ignore
        self.osc2_output_enable_checkBox.blockSignals(False)  # type: ignore
    def set_osc3_output_enable(self, state = None): 
        self.logic.stop()
        self.logic.setpoint_osc3_output_enable = bool(state) if state is not None else self.osc3_output_enable_checkBox.isChecked()  # type: ignore
        self.logic.job = "set_osc3_output_enable"
        self.logic.start()
    def get_osc3_output_enable(self):
        self.logic.job = "get_osc3_output_enable"   
        self.logic.start()
    def update_osc3_output_enable(self, state):
        self.osc3_output_enable_checkBox.blockSignals(True)  # type: ignore
        self.osc3_output_enable_checkBox.setChecked(bool(state))  # type: ignore
        self.osc3_output_enable_checkBox.blockSignals(False)  # type: ignore
    def set_osc4_output_enable(self, state = None): 
        self.logic.stop()
        self.logic.setpoint_osc4_output_enable = bool(state) if state is not None else self.osc4_output_enable_checkBox.isChecked()  # type: ignore
        self.logic.job = "set_osc4_output_enable"
        self.logic.start()
    def get_osc4_output_enable(self):
        self.logic.job = "get_osc4_output_enable"
        self.logic.start()
    def update_osc4_output_enable(self, state):
        self.osc4_output_enable_checkBox.blockSignals(True)  # type: ignore
        self.osc4_output_enable_checkBox.setChecked(bool(state))  # type: ignore
        self.osc4_output_enable_checkBox.blockSignals(False)  # type: ignore        
    
    def set_frequency1(self):
        self.logic.stop()
        self.logic.setpoint_frequency1 = self.frequency1_spinBox.value()  # type: ignore
        self.logic.job = "set_frequency1"
        self.logic.start()
    def get_frequency1(self):
        self.logic.job = "get_frequency1"
        self.logic.start()
    def update_frequency1(self, freq):
        if self.frequency1_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.frequency1_spinBox.blockSignals(True)  # type: ignore
        self.frequency1_spinBox.setValue(float(freq))  # type: ignore
        self.frequency1_spinBox.blockSignals(False)  # type: ignore

    def set_frequency2(self):
        self.logic.stop()
        self.logic.setpoint_frequency2 = self.frequency2_spinBox.value()  # type: ignore
        self.logic.job = "set_frequency2"
        self.logic.start()
    def get_frequency2(self):
        self.logic.job = "get_frequency2"   
        self.logic.start()
    def update_frequency2(self, freq):
        if self.frequency2_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.frequency2_spinBox.blockSignals(True)  # type: ignore
        self.frequency2_spinBox.setValue(float(freq))  # type: ignore
        self.frequency2_spinBox.blockSignals(False)  # type: ignore

    def set_frequency3(self):
        self.logic.stop()
        self.logic.setpoint_frequency3 = self.frequency3_spinBox.value()  # type: ignore
        self.logic.job = "set_frequency3"
        self.logic.start()
    def get_frequency3(self):
        self.logic.job = "get_frequency3"   
        self.logic.start()
    def update_frequency3(self, freq):
        if self.frequency3_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.frequency3_spinBox.blockSignals(True)  # type: ignore
        self.frequency3_spinBox.setValue(float(freq))  # type: ignore
        self.frequency3_spinBox.blockSignals(False)  # type: ignore

    def set_frequency4(self):
        self.logic.stop()
        self.logic.setpoint_frequency4 = self.frequency4_spinBox.value()  # type: ignore
        self.logic.job = "set_frequency4"
        self.logic.start()
    def get_frequency4(self):
        self.logic.job = "get_frequency4"   
        self.logic.start()
    def update_frequency4(self, freq):
        if self.frequency4_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.frequency4_spinBox.blockSignals(True)  # type: ignore
        self.frequency4_spinBox.setValue(float(freq))  # type: ignore
        self.frequency4_spinBox.blockSignals(False)  # type: ignore
    
    def set_amplitude1(self):
        self.logic.stop()
        self.logic.setpoint_amplitude1 = self.amplitude1_spinBox.value()  # type: ignore   
        self.logic.job = "set_amplitude1"
        self.logic.start()
    def get_amplitude1(self):
        self.logic.job = "get_amplitude1"   
        self.logic.start()

    def update_amplitude1(self, amp):
        if self.amplitude1_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.amplitude1_spinBox.blockSignals(True)  # type: ignore
        self.amplitude1_spinBox.setValue(float(amp))  # type: ignore
        self.amplitude1_spinBox.blockSignals(False)  # type: ignore
    
    def set_amplitude2(self):
        self.logic.stop()
        self.logic.setpoint_amplitude2 = self.amplitude2_spinBox.value()  # type: ignore
        self.logic.job = "set_amplitude2"
        self.logic.start()
    def get_amplitude2(self):
        self.logic.job = "get_amplitude2"   
        self.logic.start()
    def update_amplitude2(self, amp):
        if self.amplitude2_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.amplitude2_spinBox.blockSignals(True)  # type: ignore
        self.amplitude2_spinBox.setValue(float(amp))  # type: ignore
        self.amplitude2_spinBox.blockSignals(False)  # type: ignore    
    
    def set_amplitude3(self):
        self.logic.stop()
        self.logic.setpoint_amplitude3 = self.amplitude3_spinBox.value()  # type: ignore
        self.logic.job = "set_amplitude3"
        self.logic.start()
    def get_amplitude3(self):
        self.logic.job = "get_amplitude3"   
        self.logic.start()
    def update_amplitude3(self, amp):
        if self.amplitude3_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.amplitude3_spinBox.blockSignals(True)  # type: ignore
        self.amplitude3_spinBox.setValue(float(amp))  # type: ignore
        self.amplitude3_spinBox.blockSignals(False)  # type: ignore
    
    def set_amplitude4(self):
        self.logic.stop()
        self.logic.setpoint_amplitude4 = self.amplitude4_spinBox.value()  # type: ignore
        self.logic.job = "set_amplitude4"
        self.logic.start()
    def get_amplitude4(self):   
        self.logic.job = "get_amplitude4"   
        self.logic.start()
    def update_amplitude4(self, amp):
        if self.amplitude4_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.amplitude4_spinBox.blockSignals(True)  # type: ignore
        self.amplitude4_spinBox.setValue(float(amp))  # type: ignore
        self.amplitude4_spinBox.blockSignals(False)  # type: ignore

    def set_phase1(self):
        self.logic.stop()
        self.logic.setpoint_phase1 = self.phase1_spinBox.value()  # type: ignore
        self.logic.job = "set_phase1"
        self.logic.start()
    def get_phase1(self):
        self.logic.job = "get_phase1"   
        self.logic.start()
    def update_phase1(self, phase):
        if self.phase1_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.phase1_spinBox.blockSignals(True)  # type: ignore
        self.phase1_spinBox.setValue(float(phase))  # type: ignore
        self.phase1_spinBox.blockSignals(False)  # type: ignore
    def set_phase2(self):
        self.logic.stop()
        self.logic.setpoint_phase2 = self.phase2_spinBox.value()  # type: ignore
        self.logic.job = "set_phase2"
        self.logic.start()
    def get_phase2(self):
        self.logic.job = "get_phase2"   
        self.logic.start()
    def update_phase2(self, phase):
        if self.phase2_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.phase2_spinBox.blockSignals(True)  # type: ignore
        self.phase2_spinBox.setValue(float(phase))  # type: ignore
        self.phase2_spinBox.blockSignals(False)  # type: ignore
    def set_phase3(self):
        self.logic.stop()
        self.logic.setpoint_phase3 = self.phase3_spinBox.value()  # type: ignore
        self.logic.job = "set_phase3"
        self.logic.start()
    def get_phase3(self):
        self.logic.job = "get_phase3"   
        self.logic.start()
    def update_phase3(self, phase):
        if self.phase3_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.phase3_spinBox.blockSignals(True)  # type: ignore
        self.phase3_spinBox.setValue(float(phase))  # type: ignore
        self.phase3_spinBox.blockSignals(False)  # type: ignore
    def set_phase4(self):
        self.logic.stop()
        self.logic.setpoint_phase4 = self.phase4_spinBox.value()  # type: ignore
        self.logic.job = "set_phase4"
        self.logic.start()
    def get_phase4(self):
        self.logic.job = "get_phase4"   
        self.logic.start()
    def update_phase4(self, phase):
        if self.phase4_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.phase4_spinBox.blockSignals(True)  # type: ignore
        self.phase4_spinBox.setValue(float(phase))  # type: ignore
        self.phase4_spinBox.blockSignals(False)  # type: ignore
    
    def set_dc_offset(self):
        self.logic.stop()
        self.logic.setpoint_dc_offset = self.dc_offset_spinBox.value()  # type: ignore
        self.logic.job = "set_dc_offset"
        self.logic.start()
    def get_dc_offset(self):
        self.logic.job = "get_dc_offset"   
        self.logic.start()
    def update_dc_offset(self, offset):
        if self.dc_offset_spinBox.lineEdit().hasFocus(): #type: ignore
            return
        self.dc_offset_spinBox.blockSignals(True)  # type: ignore
        self.dc_offset_spinBox.setValue(float(offset))  # type: ignore
        self.dc_offset_spinBox.blockSignals(False)  # type: ignore

    def set_output_autorange(self, state = None):
        self.logic.stop()
        # Set the autorange setpoint based on the provided state or current checkbox state
        if state is not None:
            self.logic.setpoint_output_autorange = bool(state)
        else:
            self.logic.setpoint_output_autorange = self.output_autorange_checkBox.isChecked()  # type: ignore
        self.logic.job = "set_output_autorange"
        self.logic.start()
        val = self.logic.get_output_range()
        self.update_output_range_comboBox(range = val)

        if bool(state):
            self.output_range_comboBox.setEnabled(False) #type: ignore
        else:
            self.output_range_comboBox.setEnabled(True) #type: ignore
            
    def get_output_autorange(self):
        self.logic.job = "get_output_autorange"   
        self.logic.start()
    def update_output_autorange(self, state):
        self.output_autorange_checkBox.blockSignals(True)  # type: ignore
        self.output_autorange_checkBox.setChecked(bool(state))  # type: ignore
        self.output_autorange_checkBox.blockSignals(False)  # type: ignore

    def set_output_range(self):
        self.logic.stop()
        self.logic.setpoint_output_range = self.output_range_comboBox.currentText() #type: ignore
        self.logic.job = "set_output_range"
        self.logic.start()

    def get_output_range(self):
        self.logic.stop()
        self.logic.job = "get_output_range"   
        self.logic.start()
    
    def update_output_range(self, range):
        self.output_range_comboBox.blockSignals(True)  # type: ignore
        self.output_range_comboBox.setCurrentText(str(range))  # type: ignore
        self.output_range_comboBox.blockSignals(False)  # type: ignore

    def update_output_range_comboBox(self, range):
        index = int(2 + np.log10(float(range)))
        self.output_range_comboBox.setCurrentIndex(index) #type: ignore

    def preset(self):
        self.logic.stop()
        self.logic.job = "preset_basic"
        self.logic.start()


    
    #needs only in the testing mode
    def closeEvent(self, event):
        print("MFLI closed.")
        event.accept()
    

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MFLI()
    window.show()
    sys.exit(app.exec())