# from PyQt6 import QtWidgets, uic, QtCore
# import sys
# from anc300_logic import ANC300Logic
# import numpy as np
# import pyqtgraph as pg


# class ANC300(QtWidgets.QWidget):

#     def __init__(self):
#         super(ANC300, self).__init__()
#         uic.loadUi(r"ANC300/anc300.ui", self)
#         self.logic = ANC300Logic()

#         self.connect_sig_slot()


#     def connect_sig_slot(self):
#         self.connect_button.clicked.connect(self.when_connect_button_clicked)
#         self.close_button.clicked.connect(self.when_close_button_clicked)
#         self.set_ground_all_button.clicked.connect(self.when_set_ground_all_button_clicked)
#         self.reset_step_record_button.clicked.connect(self.when_reset_step_record_button_clicked)

#         self.enable_axis1_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(1))
#         self.enable_axis2_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(2))
#         self.enable_axis3_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(3))
#         self.enable_axis4_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(4))
#         self.enable_axis5_button.clicked.connect(lambda: self.when_enable_axis_button_clicked(5))

#         self.gnd_axis1_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(1))
#         self.gnd_axis2_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(2))
#         self.gnd_axis3_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(3))
#         self.gnd_axis4_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(4))
#         self.gnd_axis5_button.clicked.connect(lambda: self.when_gnd_axis_button_clicked(5))

#         self.measure_all_axis_capacitance_button.clicked.connect(self.when_measure_all_cap_button_clicked)

#         self.move_up_button.clicked.connect(lambda: self.when_move_button_clicked("up"))
#         self.move_down_button.clicked.connect(lambda: self.when_move_button_clicked("down"))
#         self.move_left_button.clicked.connect(lambda: self.when_move_button_clicked("left"))
#         self.move_right_button.clicked.connect(lambda: self.when_move_button_clicked("right"))
#         self.move_zup_button.clicked.connect(lambda: self.when_move_button_clicked("zup"))
#         self.move_zdown_button.clicked.connect(lambda: self.when_move_button_clicked("zdown"))

#         # self.logic.sig_name.connect(self.sig_name)
#         self.logic.sig_ANC300_info.connect(self.update_ANC300_info)
#         # self.logic.sig_cap_measurement_info.connect(self.update_cap_measurement_info)
#         # self.logic.sig_anm150_pos_indictor.connect(self.update_anm150_pos_indictor)


#     def connect(self, device=""):
#         if device == "":
#             device = self.port_name_text.toPlainText()
#         else:
#             pass
#         self.logic.initialize(device)
#         self.connect_info.setText("Connected to " + self.logic.port_name)

#     def close(self):
#         self.logic.close()
#         self.connect_info.setText("Not Connected")

#     def when_connect_button_clicked(self):
#         self.connect()

#     def when_close_button_clicked(self):
#         self.close()

#     def when_set_ground_all_button_clicked(self):
#         self.logic.set_ground_all_axis()

#     def when_reset_step_record_button_clicked(self):
#         self.logic.reset_step_record()

#     def when_enable_axis_button_clicked(self, axis):
#         self.logic.enable_axis(axis)

#     def when_gnd_axis_button_clicked(self, axis):
#         self.logic.set_ground_axis(axis)

#     def when_measure_all_cap_button_clicked(self):
#         self.logic.job = "measure_all_capacitance"
#         self.logic.start()

#     def when_move_button_clicked(self, direction):
#         stepMove = self.stepMoveCheckBox.isChecked()
#         if stepMove:
#             self.logic.job = "move_anm150_one_step"
#         else:
#             self.logic.job = "move_anm150_continuesly"

#         if direction == "left":
#             self.logic.target_axis = 1
#             self.logic.direction = False
#         elif direction == "right":
#             self.logic.target_axis = 1
#             self.logic.direction = True
#         elif direction == "down":
#             self.logic.target_axis = 2
#             self.logic.direction = False
#         elif direction == "down":
#             self.logic.target_axis = 2
#             self.logic.direction = True
#         elif direction == "zup":
#             self.logic.target_axis = 3
#             self.logic.direction = True
#         elif direction == "zdown":
#             self.logic.target_axis = 3
#             self.logic.direction = False

#         self.logic.start()

    
#     def update_ANC300_info(self, sig):
#         # print( "ANC300 info updated", info)
#         axis, info, val = sig
#         if info == "mode":
#             self.update_axis_mode(axis, val)

#         elif info == "capacitance":
#             self.update_axis_capacitance(axis, val)

#         elif info == "position":
#             self.update_axis_position(axis, val)
        

#     def update_axis_mode(self, axis, val):
#         if axis == 1:
#             self.axis1_status.setText(val)
#         elif axis == 2:
#             self.axis2_status.setText(val)
#         elif axis == 3:
#             self.axis3_status.setText(val)
#         elif axis == 4:
#             self.axis4_status.setText(val)
#         elif axis == 5:
#             self.axis5_status.setText(val)
    
#     def update_axis_capacitance(self, axis, val):  
#         val = float(val) * 1e9
#         if axis == 1:
#             self.axis1_cap.setText(f"{val:.2f} nF")
#         elif axis == 2:
#             self.axis2_cap.setText(f"{val:.2f} nF")
#         elif axis == 3:
#             self.axis3_cap.setText(f"{val:.2f} nF")
#         elif axis == 4:
#             self.axis4_cap.setText(f"{val:.2f} nF")
#         elif axis == 5:
#             self.axis5_cap.setText(f"{val:.2f} nF")

#     def update_axis_position(self, axis, val):
#         if axis == 1:
#             self.x_position.setText(f"x = {val}")
#         elif axis == 2:
#             self.y_position.setText(f"y = {val}")
#         elif axis == 3:
#             self.z_position.setText(f"z = {val}")
    

# if __name__ == "__main__":
#     app = QtWidgets.QApplication(sys.argv)
#     window = ANC300()
#     window.show()
#     sys.exit(app.exec())


from PyQt6 import QtWidgets, uic, QtCore
import sys
from anc300_logic import ANC300Logic


class ANC300(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        uic.loadUi(r"ANC300/anc300.ui", self)
        self._ctrls = [
            self.set_ground_all_button, self.reset_step_record_button,
            self.enable_axis1_button, self.enable_axis2_button,
            self.enable_axis3_button, self.enable_axis4_button,
            self.enable_axis5_button, self.gnd_axis1_button,
            self.gnd_axis2_button, self.gnd_axis3_button,
            self.gnd_axis4_button, self.gnd_axis5_button,
            self.measure_all_axis_capacitance_button,
            self.move_up_button, self.move_down_button,
            self.move_left_button, self.move_right_button,
            self.move_zup_button, self.move_zdown_button,
            self.axis12_freq_val, self.axis12_stepvolt_val,
            self.axis3_freq_val,  self.axis3_stepvolt_val
        ]
        self.enable_controls(False) 

        self.logic = ANC300Logic()
        self.connect_sig_slot()
        self.axis_dir = {
            "left":  (1, False),
            "right": (1, True),
            "down":  (2, False),
            "up":    (2, True),                                                   # ★ fixed duplicate
            "zdown": (3, False),
            "zup":   (3, True)
        }

    # ------------------------------------------------------
    #  Signal / slot wiring
    # ------------------------------------------------------
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

        # live-updates
        self.logic.sig_name.connect(self.update_connection_label)                 # ★
        self.logic.sig_ANC300_info.connect(self.update_ANC300_info)
        self.axis12_freq_val.valueChanged.connect(self.on_axis12_freq_changed)
        self.axis12_stepvolt_val.valueChanged.connect(self.on_axis12_stepvolt_changed)
        self.axis3_freq_val.valueChanged.connect(self.on_axis3_freq_changed)
        self.axis3_stepvolt_val.valueChanged.connect(self.on_axis3_stepvolt_changed)

    # ------------------------------------------------------
    #  Connection helpers
    # ------------------------------------------------------

    def enable_controls(self, state: bool):
        """Enable/disable every control that requires a live connection."""
        for w in self._ctrls:
            w.setEnabled(state)

    def connect(self, device=""):
        if not device:
            device = self.port_name_text.toPlainText()

        try:
            self.logic.initialize(device)
        except Exception as err:                 # ★ NEW guard — no crash
            print(
                "Connection error",
                f"Could not open ANC300 on ‘{device}’:\n{err}"
            )
            self.update_connection_label("Not Connected")
            self.enable_controls(False)
            return

        if not getattr(self.logic, "is_initialized", False):  # ★ extra safety
            print(
                "Connection error",
                f"ANC300 refused connection on ‘{device}’.")
            self.update_connection_label("Not Connected")
            self.enable_controls(False)
            return

        # ---------------- after successful init  ★ NEW
        for ax in (1, 2):                        # X & Y
            self.logic.change_anm150_freq(ax, 500)
            self.logic.change_anm150_step_volt(ax, 50)
        self.axis12_freq_val.setValue(500)       # ★ sync UI
        self.axis12_stepvolt_val.setValue(50)

        self.logic.change_anm150_freq(3, 300)    # Z
        self.logic.change_anm150_step_volt(3, 40)
        self.axis3_freq_val.setValue(300)        # ★ sync UI
        self.axis3_stepvolt_val.setValue(40)

        self.logic.read_all_axis_info()      # pull modes / volt / freq …
        self.logic.reset_pos_indictor()      # zero x-y-z counters
        self.set_all_capacitance_zero()      # display “0.00 nF” for all axes

        self.enable_controls(True)  

    def close(self):
        self.logic.close()
        self.update_connection_label("Not Connected")
        self.enable_controls(False)   

    def update_connection_label(self, txt):                                       # ★
        self.connect_info.setText(txt if txt != "Disconnected" else "Not Connected")

    # ------------------------------------------------------
    #  Button handlers
    # ------------------------------------------------------
    def when_connect_button_clicked(self):
        self.connect()

    def when_close_button_clicked(self):
        self.close()

    def when_set_ground_all_button_clicked(self):
        self.logic.set_ground_all_axis()

    def when_reset_step_record_button_clicked(self):
        self.logic.reset_pos_indictor()                                           # ★ name change

    def when_enable_axis_button_clicked(self, axis):
        self.logic.set_enable_axis(axis)                                          # ★ name change

    def when_gnd_axis_button_clicked(self, axis):
        self.logic.set_ground_axis(axis)

    def when_measure_all_cap_button_clicked(self):
        self.logic.job = "read_all_axis_capacitance"                              # ★ correct job token
        self.logic.start()

    # ------------------------------------------------------
    #  Motion handler
    # ------------------------------------------------------
    def when_move_button_clicked(self, direction):
        # choose job
        self.logic.job = "move_anm150_one_step" if self.stepMoveCheckBox.isChecked() \
                         else "move_anm150_continuously"

        # map button → axis / direction

        axis, d = self.axis_dir[direction]
        self.logic.target_axis = axis                                             # ★ attribute names
        self.logic.target_direction = d                                           # ★
        self.logic.start()

    # ------------------------------------------------------
    #  Slot to handle every update coming from ANC300Logic
    # ------------------------------------------------------
    def update_ANC300_info(self, sig):
        axis, key, val = sig
        if key == "mode":
            self.update_axis_mode(axis, val)
        elif key == "capacitance":
            self.update_axis_capacitance(axis, val)
        elif key == "pos":
            self.update_axis_position(axis, val)
        elif key == "freq":                      # ★ new
            self.update_axis_freq(axis, val)
        elif key == "step_volt":                 # ★ new
            self.update_axis_stepvolt(axis, val)

    # individual label updates ----------------------------------------------------
    def update_axis_mode(self, axis, val):
        getattr(self, f"axis{axis}_status").setText(str(val))

    def update_axis_capacitance(self, axis, val):
        # val is in Farads; show nF
        getattr(self, f"axis{axis}_cap").setText(f"{val*1e9:.2f} nF")

    def update_axis_position(self, axis, val):
        coord = {1: "x", 2: "y", 3: "z"}.get(axis, f"axis{axis}")
        getattr(self, f"{coord}_position").setText(f"{coord} = {val}")

    # -------- frequency ----------
    def on_axis12_freq_changed(self, v):
        self.logic.change_anm150_freq(1, v)
        self.logic.change_anm150_freq(2, v)

    def on_axis3_freq_changed(self, v):
        self.logic.change_anm150_freq(3, v)

    def update_axis_freq(self, axis, val):
        if axis in (1, 2):
            self.axis12_freq_val.setValue(int(val))
        elif axis == 3:
            self.axis3_freq_val.setValue(int(val))

    # -------- step-voltage ----------
    def on_axis12_stepvolt_changed(self, v):
        self.logic.change_anm150_step_volt(1, v)
        self.logic.change_anm150_step_volt(2, v)

    def on_axis3_stepvolt_changed(self, v):
        self.logic.change_anm150_step_volt(3, v)

    def update_axis_stepvolt(self, axis, val):
        if axis in (1, 2):
            self.axis12_stepvolt_val.setValue(int(val))
        elif axis == 3:
            self.axis3_stepvolt_val.setValue(int(val))

    # ------------------------------------------------------
    def set_all_capacitance_zero(self):
        for ax in range(1, 6):
            self.update_axis_capacitance(ax, 0)

# --------------------------------------------------------------------------
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = ANC300()
    window.show()
    sys.exit(app.exec())
