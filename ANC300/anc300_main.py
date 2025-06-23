from PyQt6 import QtWidgets, uic, QtCore
import sys
from anc300_logic import ANC300Logic
import numpy as np
import pyqtgraph as pg


class ANC300(QtWidgets.QWidget):

    def __init__(self):
        super(ANC300, self).__init__()
        uic.loadUi(r"ANC300/anc300.ui", self)
        self.logic = ANC300Logic()

        self.connect_sig_slot()


    def connect_sig_slot(self):
        self.connect_button.clicked.connect(self.when_connect_button_clicked)
        self.close_button.clicked.connect(self.when_close_button_clicked)
        self.set_ground_all_button.clicked.connect(self.when_set_ground_all_button_clicked)
        self.reset_step_record_button.clicked.connect(self.when_reset_step_record_button_clicked)

        self.enable_axis1_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(1))
        self.enable_axis2_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(2))
        self.enable_axis3_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(3))
        self.enable_axis4_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(4))
        self.enable_axis5_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(5))

        self.gnd_axis1_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(1))
        self.gnd_axis2_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(2))
        self.gnd_axis3_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(3))
        self.gnd_axis4_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(4))
        self.gnd_axis5_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(5))

        self.measure_all_axis_capacitance_button.clicked.connect(self.when_measure_all_cap_button_clicked)

        self.move_up_button.clicked.connect(lambda: self.when_move_button_clicked("up"))
        self.move_down_button.clicked.connect(lambda: self.when_move_button_clicked("down"))
        self.move_left_button.clicked.connect(lambda: self.when_move_button_clicked("left"))
        self.move_right_button.clicked.connect(lambda: self.when_move_button_clicked("right"))
        self.move_zup_button.clicked.connect(lambda: self.when_move_button_clicked("zup"))
        self.move_zdown_button.clicked.connect(lambda: self.when_move_button_clicked("zdown"))

        # self.logic.sig_name.connect(self.sig_name)
        self.logic.sig_ANC300_info.connect(self.update_ANC300_info)
        # self.logic.sig_cap_measurement_info.connect(self.update_cap_measurement_info)
        # self.logic.sig_anm150_pos_indictor.connect(self.update_anm150_pos_indictor)


    def connect(self, device=""):
        if device == "":
            device = self.port_name_text.toPlainText()
        else:
            pass
        self.logic.initialize(device)
        self.connect_info.setText("Connected to " + self.logic.port_name)

    def close(self):
        self.logic.close()
        self.connect_info.setText("Not Connected")

    def when_connect_button_clicked(self):
        self.connect()

    def when_close_button_clicked(self):
        self.close()

    def when_set_ground_all_button_clicked(self):
        self.logic.set_ground_all_axis()

    def when_reset_step_record_button_clicked(self):
        self.logic.reset_step_record()

    def when_enable_axis_button_clicked(self, axis):
        self.logic.enable_axis(axis)

    def when_gnd_axis_button_clicked(self, axis):
        self.logic.set_ground_axis(axis)

    def when_measure_all_cap_button_clicked(self):
        self.logic.job = "measure_all_capacitance"
        self.logic.start()

    def when_move_button_clicked(self, direction):
        stepMove = self.stepMoveCheckBox.isChecked()
        if stepMove:
            self.logic.job = "move_anm150_one_step"
        else:
            self.logic.job = "move_anm150_continuesly"

        if direction == "left":
            self.logic.target_axis = 1
            self.logic.direction = False
        elif direction == "right":
            self.logic.target_axis = 1
            self.logic.direction = True
        elif direction == "down":
            self.logic.target_axis = 2
            self.logic.direction = False
        elif direction == "down":
            self.logic.target_axis = 2
            self.logic.direction = True
        elif direction == "zup":
            self.logic.target_axis = 3
            self.logic.direction = True
        elif direction == "zdown":
            self.logic.target_axis = 3
            self.logic.direction = False

        self.logic.start()

    
    def update_ANC300_info(self, sig):
        # print( "ANC300 info updated", info)
        axis, info, val = sig
        if info == "mode":
            self.update_axis_mode(axis, val)

        elif info == "capacitance":
            self.update_axis_capacitance(axis, val)

        elif info == "position":
            self.update_axis_position(axis, val)
        

    def update_axis_mode(self, axis, val):
        if axis == 1:
            self.axis1_status.setText(val)
        elif axis == 2:
            self.axis2_status.setText(val)
        elif axis == 3:
            self.axis3_status.setText(val)
        elif axis == 4:
            self.axis4_status.setText(val)
        elif axis == 5:
            self.axis5_status.setText(val)
    
    def update_axis_capacitance(self, axis, val):  
        val = float(val) * 1e9
        if axis == 1:
            self.axis1_cap.setText(f"{val:.2f} nF")
        elif axis == 2:
            self.axis2_cap.setText(f"{val:.2f} nF")
        elif axis == 3:
            self.axis3_cap.setText(f"{val:.2f} nF")
        elif axis == 4:
            self.axis4_cap.setText(f"{val:.2f} nF")
        elif axis == 5:
            self.axis5_cap.setText(f"{val:.2f} nF")

    def update_axis_position(self, axis, val):
        if axis == 1:
            self.x_position.setText(f"x = {val}")
        elif axis == 2:
            self.y_position.setText(f"y = {val}")
        elif axis == 3:
            self.z_position.setText(f"z = {val}")
    

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = ANC300()
    window.show()
    sys.exit(app.exec())