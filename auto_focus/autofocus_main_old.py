#!/usr/bin/env python3
import sys
import os
from PyQt5 import QtWidgets, uic
import serial.tools.list_ports
import scipy.io as sio
from nidaq_hardware import NIDAQHardWare
import autofocus_logic
from PyQt5 import QtWidgets, uic, QtTest

class AutofocusApp(QtWidgets.QWidget):
    def __init__(self, daq):
        super().__init__()
        # Load the Qt Designer .ui file
        uic.loadUi('autofocus_GUI.ui', self)
        self.ser=None

        # Store passed-in DAQ
        self.daq = daq

        # Populate COM port combo box
        self.comboComPort.clear()
        for port in serial.tools.list_ports.comports():
            self.comboComPort.addItem(port.device)


        self.connect_ard_btn.clicked.connect(self.connect_arduino)
        self.disconnect_ard_btn.clicked.connect(self.disconnect_arduino)
        # Connect button signal
        self.btnAutofocus.clicked.connect(self.start_autofocus)

    def connect_arduino(self):
        port_name = self.comboComPort.currentText()
        try:
            self.ser = serial.Serial(port_name, 115200, timeout=1)
            QtTest.QTest.qWait(2000)
            self.ard_label_status.setText("Connected")
        except Exception as e:
            self.ard_label_status.setText("Error")
            print(e)

    def disconnect_arduino(self):
        if self.ser:
            self.ser.close()
            self.ard_label_status.setText("disconnected")

    def start_autofocus(self):
        # Read GUI parameters
        motor_rpm     = self.spinMotorRPM.value()
        initial_range = self.spinInitialRange.value()
        threshold     = self.spinThreshold.value()
        x_center      = self.spinXCenter.value()
        y_center      = self.spinYCenter.value()
        x_range       = self.spinXRange.value()
        y_range       = self.spinYRange.value()
        x_pts         = int(self.spinXPts.value())
        y_pts         = int(self.spinYPts.value())
        save_dir      = self.txtSaveDir.toPlainText().strip()

        # Determine overall run index (nn)
        run_idx = None
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            run_idx = 1
            while os.path.exists(os.path.join(save_dir, f"{run_idx:02d}.mat")):
                run_idx += 1

        # Override autofocus logic globals
        autofocus_logic.MOTOR_RPM     = motor_rpm
        autofocus_logic.INITIAL_RANGE = initial_range
        autofocus_logic.THRESHOLD     = threshold
        autofocus_logic.X_CENTER      = x_center
        autofocus_logic.Y_CENTER      = y_center
        autofocus_logic.X_RANGE       = x_range
        autofocus_logic.Y_RANGE       = y_range
        autofocus_logic.X_PTS         = x_pts
        autofocus_logic.Y_PTS         = y_pts

        # Instantiate the autofocus system with external DAQ
        af = autofocus_logic.AutofocusSystem(motor_rpm, self.daq,self.ser)

        # Run the iterative focus search, saving semi-live plots
        best_angle, centers, metrics, xy_maps = autofocus_logic.iterative_focus_search(
            af,
            init_center=x_center,
            span=initial_range,
            thresh=threshold,
            save_dir=save_dir,
            run_idx=run_idx
        )

        # Move to best focus angle
        af.move_focus(best_angle)

        # Save final .mat file
        save_msg = "No save directory specified."
        if save_dir and run_idx:
            mat_name = f"{run_idx:02d}.mat"
            mat_path = os.path.join(save_dir, mat_name)
            sio.savemat(mat_path, {"xy_maps": xy_maps, "metrics": metrics})
            # save_msg = f"Saved metadata to {mat_path}"

        # # Notify the user
        # QtWidgets.QMessageBox.information(
        #     self,
        #     "Autofocus Complete",
        #     f"Best focus angle: {best_angle:.2f}°\n{save_msg}"
        # )

if __name__ == '__main__':
    app = QtWidgets.QApplication(sys.argv)
    # Create and configure the DAQ hardware instance
    daq = NIDAQHardWare()
    window = AutofocusApp(daq)
    window.show()
    sys.exit(app.exec_())
