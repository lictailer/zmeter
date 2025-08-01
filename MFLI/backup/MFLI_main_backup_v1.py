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
        
        # Connect oscillator checkboxes using lambda to pass osc_index
        self.osc1_output_enable_checkBox.stateChanged.connect(lambda state: self.set_osc_output_enable(1, state))  # type: ignore
        self.osc2_output_enable_checkBox.stateChanged.connect(lambda state: self.set_osc_output_enable(2, state))  # type: ignore
        self.osc3_output_enable_checkBox.stateChanged.connect(lambda state: self.set_osc_output_enable(3, state))  # type: ignore
        self.osc4_output_enable_checkBox.stateChanged.connect(lambda state: self.set_osc_output_enable(4, state))  # type: ignore
        
        # Connect frequency spinboxes using lambda to pass float value to set_osc_frequency_by_index                    
        self.frequency1_spinBox.valueChanged.connect(self.set_osc1_frequency)  # type: ignore
        self.frequency2_spinBox.valueChanged.connect(self.set_osc2_frequency)  # type: ignore
        self.frequency3_spinBox.valueChanged.connect(self.set_osc3_frequency)  # type: ignore
        self.frequency4_spinBox.valueChanged.connect(self.set_osc4_frequency)  # type: ignore   
        
        # Connect amplitude spinboxes using lambda to pass float value to set_osc_amplitude_by_index
        self.amplitude1_spinBox.valueChanged.connect(self.set_osc1_amplitude)  # type: ignore
        self.amplitude2_spinBox.valueChanged.connect(self.set_osc2_amplitude)  # type: ignore
        self.amplitude3_spinBox.valueChanged.connect(self.set_osc3_amplitude)  # type: ignore
        self.amplitude4_spinBox.valueChanged.connect(self.set_osc4_amplitude)  # type: ignore
        
        # Connect phase spinboxes using lambda to pass float value to set_osc_phase_by_index
        self.phase1_spinBox.valueChanged.connect(self.set_osc1_phase)  # type: ignore
        self.phase2_spinBox.valueChanged.connect(self.set_osc2_phase)  # type: ignore
        self.phase3_spinBox.valueChanged.connect(self.set_osc3_phase)  # type: ignore
        self.phase4_spinBox.valueChanged.connect(self.set_osc4_phase)  # type: ignore
        
        
        # ----- connect signals to logic methods -----
        self.logic.sig_is_changing.connect(self.update_status)
        self.logic.sig_connected.connect(self.update_status)
        self.logic.sig_output_enable.connect(self.update_output_enable)
        self.logic.sig_differential_output.connect(self.update_differential_output)
        

        # ----- periodic monitor -----
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.monitor)
        self.timer.start(50)
        self.stop_signal.connect(self.stop_timer)
        

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
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
        # Only call get_frequency, get_amplitude, get_phase, get_enable as available
        #self.logic.get_frequency(osc_index = 0)
        #self.logic.get_amplitude(osc_index = 0)
        #self.logic.get_phase(demod_index = 0)
        #self.logic.get_output_enable()

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

    # ------------------------------------------------------------------
    # Generic oscillator methods
    # ------------------------------------------------------------------
    def _get_osc_checkbox(self, osc_index):
        """Get the checkbox widget for the specified oscillator."""
        checkbox_map = {
            1: self.osc1_output_enable_checkBox,
            2: self.osc2_output_enable_checkBox,
            3: self.osc3_output_enable_checkBox,
            4: self.osc4_output_enable_checkBox
        }
        return checkbox_map.get(osc_index)

    def set_osc_output_enable(self, osc_index, state=None):
        """Generic method to set oscillator output enable for any oscillator."""
        self.logic.stop()
        
        checkbox = self._get_osc_checkbox(osc_index)
        if checkbox is None:
            print(f"Invalid oscillator index: {osc_index}")
            return
            
        if state is None:
            state = checkbox.isChecked()
        else:
            state = bool(state)
            
        # Set the setpoint in logic based on osc_index
        setattr(self.logic, f'setpoint_osc{osc_index}_output_enable', state)
        self.logic.job = f"set_osc{osc_index}_output_enable"
        self.logic.start()

    def get_osc_output_enable(self, osc_index):
        """Generic method to get oscillator output enable for any oscillator."""
        self.logic.job = f"get_osc{osc_index}_output_enable"
        self.logic.start()

    def update_osc_output_enable(self, osc_index, state):
        """Generic method to update oscillator checkbox state."""
        checkbox = self._get_osc_checkbox(osc_index)
        if checkbox is None:
            print(f"Invalid oscillator index: {osc_index}")
            return
            
        checkbox.blockSignals(True)
        checkbox.setChecked(bool(state))
        checkbox.blockSignals(False)

    # --- Generic Oscillator Frequency Methods ---
    def set_osc_frequency_by_index(self, osc_index, freq):
        self.logic.stop()
 
    # ------------------------------------------------------------------
    # Other methods (output_enable, differential_output)
    # ------------------------------------------------------------------
    def set_output_enable(self, state=None):
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

    def set_differential_output(self, state=None):
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


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MFLI()
    
    window.show()
    sys.exit(app.exec())