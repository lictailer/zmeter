#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from PyQt6 import QtWidgets, uic
import serial.tools.list_ports
import scipy.io as sio
from nidaq.nidaq_hardware import NIDAQHardWare
from auto_focus.autofocus_logic import ANC_and_DAQ_xyz, stepper_and_galvo_xyz, autofocus_logic
from PyQt6 import QtWidgets, uic, QtTest

class autofocus_main(QtWidgets.QWidget):
    def __init__(self):
        super(autofocus_main, self).__init__()
        ui_path = os.path.join(os.path.dirname(__file__), "autofocus_GUI.ui")
        uic.loadUi(ui_path, self)
        self.xyz_sys = None
        self.logic = autofocus_logic(self.xyz_sys) ## that specific logic instance will be used in the scan ##

        # connecting to the COM
        for port in serial.tools.list_ports.comports():
            self.comboComPort.addItem(port.device)
        self.connect_com_btn.clicked.connect(self.connect_sys)
        self.disconnect_com_btn.clicked.connect(self.disconnect_sys)

        self.update_settings_btn.clicked.connect(self.update_settings)
        self.btnAutofocus.clicked.connect(self.start_autofocus)
        self.update_settings()

    def connect_sys(self):
        self.logic.xyz_sys.com_port = self.comboComPort.currentText()
        try:
            self.logic.xyz_sys.connect()
            self.label_status.setText("Connected")
        except Exception as e:
            self.label_status.setText("Error")
            print(e)

    def disconnect_sys(self):
        try:
            self.logic.xyz_sys.disconnect()
            self.label_status.setText("Disconnected")
        except Exception as e:
            self.label_status.setText("Error")
            print(e)

    def update_settings(self):
        ''' Update the settings from the GUI inputs to the logic class. '''
        #the daq instance should be passed directly to the class to avoid conflics
        # self.logic.xyz_sys.ao_x = self.txtGalvoX.toPlainText().strip() # I don't have buttons for these yet
        # self.logic.xyz_sys.ao_y = self.txtGalvoY.toPlainText().strip()
        # self.logic.xyz_sys.ai = self.txtPDIn.toPlainText().strip()
        if self.xyz_sys: self.logic.xyz_sys.motor_rpm = self.spinMotorRPM.value()
        self.logic.initial_z_step = self.spinInitialStep.value()
        self.logic.threshold_z_step = self.spinThreshold.value()
        #self.logic.threshold_metric_step = self.spinThresholdMetric.value() #I have no function for this now
        self.logic.x_center = self.spinXCenter.value()
        self.logic.y_center = self.spinYCenter.value()
        self.logic.x_range = self.spinXRange.value()
        self.logic.y_range = self.spinYRange.value()
        self.logic.x_pts = int(self.spinXPts.value())
        self.logic.y_pts = int(self.spinYPts.value())
        self.logic.save_dir = self.txtSaveDir.toPlainText().strip()

    def start_autofocus(self): 
        self.update_settings()
        self.logic.set_AutoFocus()


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    daq = NIDAQHardWare()
    xyz = stepper_and_galvo_xyz(daq)
    window = autofocus_main()
    window.xyz_sys = xyz  # Set the xyz system for the autofocus logic
    window.show()
    sys.exit(app.exec_())
