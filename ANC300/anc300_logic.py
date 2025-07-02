# import numpy as np
# from PyQt6 import QtCore, QtWidgets, uic
# import time
# from anc300_hardware import ANC300Hardware
# import sys

# class ANC300Logic(QtCore.QThread):
#     sig_name = QtCore.pyqtSignal(object)
#     sig_ANC300_info =  QtCore.pyqtSignal(object)  #record axis freq, step size, capacitance signal
#     sig_cap_measurement_info = QtCore.pyqtSignal(object)  #record axis capacitance measurement status
#     sig_anm150_pos_indictor = QtCore.pyqtSignal(object)

#     def __init__(self):
#         QtCore.QThread.__init__(self)
#         self.ANC300 = ANC300Hardware()
#         self.dev_name = ""
#         self.reset_flags()
#         self.is_initialized = False
#         self.job = ""
#         self._positioner_refresh_rate = 10 #Hz

#         self.anm150_list = [1, 2, 3]
#         self.anm200_list = [4, 5]

#         self.ANC300_info = {}
#         for axis in self.anm150_list:
#             self.ANC300_info[axis] = {'mode': 'unknown',
#                                       'capacitance': 0.0, 
#                                       'step_volt': 0.0, 
#                                       'freq': 0.0,
#                                       'pos': 0}
#         for axis in self.anm200_list:
#             self.ANC300_info[axis] = {'mode': 'unknown',
#                                       'capacitance': 0.0}

#     def reset_flags(self):
#         self.receieved_stop = False

#     def initialize(self, port_name=""):
#         if self.is_initialized:
#             self.close()
#         self.port_name = port_name

#         self.is_initialized = self.ANC300.initialize(self.port_name)
#         self.reset_flags()

#         if self.is_initialized:
#             self.set_ground_all_axis()
#             self.sig_name.emit(self.port_name)
#             self.reset_pos_indictor()

#     def close(self):
#         self.set_ground_all_axis()
#         self.ANC300.close()
#         self.sig_name.emit("Disconnected")

#     def reset_pos_indictor(self):
#         for axis in self.anm150_list:
#             self.ANC300_info[axis]['pos'] = 0
#             self.sig_ANC300_info.emit([axis, 'pos', 0])

#     #----------------------------- ANM150/200 Mode Switch ----------------------------
#     def set_ground_all_axis(self):
#         for axis in self.anm150_list + self.anm200_list:
#             self.ANC300.set_mode(axis, 'gnd')

#     def set_ground_axis(self, axis):
#         if axis in self.anm150_list + self.anm200_list:
#             self.ANC300.set_mode(axis, 'gnd')
#             self.ANC300_info[axis]['mode'] = 'gnd'
#             self.sig_ANC300_info.emit([axis, 'mode', 'gnd'])
#         else:
#             print(f"Invalid axis: {axis}")
#             return
        
#     def set_enable_axis(self, axis):
#         if axis in self.anm150_list:
#             self.ANC300.set_mode(axis, 'stp')
#             self.ANC300_info[axis]['mode'] = 'stp'
#             self.sig_ANC300_info.emit([axis, 'mode', 'step'])
#         elif axis in self.anm200_list:
#             self.ANC300.set_mode(axis, 'inp')
#             self.ANC300.set_external_input_modes(axis, dcin=True)
#             self.ANC300_info[axis]['mode'] = 'inp'
#             self.sig_ANC300_info.emit([axis, 'mode', 'DC_input'])
#         else:
#             print(f"Invalid axis: {axis}")


#     #----------------------------- ANM150 Position Move ----------------------------
#     def move_anm150_one_step(self, axis, direction = True):
#         if axis not in self.anm150_list:
#             print(f"Invalid axis: {axis}")
#             return
#         self.ANC300.move_by(axis, 1 if direction else -1)
#         self.ANC300_info[axis]['pos'] += 1 if direction else -1
#         self.sig_ANC300_info.emit([axis, 'pos', self.ANC300_info[axis]['pos']])

#     def move_an150_continuesly(self, axis, direction = True):
#         if axis not in self.anm150_list:
#             print(f"Invalid axis: {axis}")
#             return
#         step_count = int(round(self.ANC300_info[axis]['freq'] / self._positioner_refresh_rate))
#         self.ANC300.move_by(axis, step_count if direction else -step_count)
#         self.ANC300_info[axis]['pos'] += step_count if direction else -step_count
#         self.sig_ANC300_info.emit([axis, 'pos', self.ANC300_info[axis]['pos']])


#     #----------------------------- ANM150 Properties Change (not for scan) ----------------------------
#     def change_anm150_freq(self, axis, freq):
#         if axis in self.anm150_list:
#             self.ANC300.set_frequency(axis, freq)
#             self.ANC300_info[axis]['freq'] = freq
#             self.sig_ANC300_info.emit([axis, 'freq', freq])
#         else:
#             print(f"Invalid axis: {axis}")

#     def change_anm150_step_volt(self, axis, volt):
#         if axis in self.anm150_list:
#             self.ANC300.set_anm150_step_volt(axis, volt)
#             self.ANC300_info[axis]['step_volt'] = volt
#             self.sig_ANC300_info.emit([axis, 'step_volt', volt])
#         else:
#             print(f"Invalid axis: {axis}")


#     #----------------------------- Read ANC300 Info ----------------------------
#     def read_all_axis_info(self):
#         for axis in self.anm150_list:
#             self.ANC300_info[axis]['mode'] = self.ANC300.get_mode(axis)
#             self.ANC300_info[axis]['step_volt'] =  self.ANC300.get_voltage(axis)
#             self.ANC300_info[axis]['freq'] = self.ANC300.get_frequency(axis)
#         for axis in self.anm200_list:
#             self.ANC300_info[axis]['mode'] = self.ANC300.get_mode(axis)
#         print(self.ANC300_info)
#         # self.sig_ANC300_info.emit(self.ANC300_info)

#     def read_all_axis_capacitance(self):
#         self.sig_cap_measurement_info.emit("Please wait till capacitance measurement is done.")

#         # for axis in self.anm150_list:
#         #     self.ANC300_info[axis]['capacitance'] = self.ANC300.get_anm150_capacitance(axis)
#         # for axis in self.anm200_list:
#         #     self.ANC300_info[axis]['capacitance'] = self.ANC300.get_anm200_capacitance(axis)
#         for axis in self.anm150_list + self.anm200_list:
#             self.ANC300_info[axis]['capacitance'] = self.ANC300.get_capacitance(axis, measure=True)
#         print(self.ANC300_info)
#         self.sig_ANC300_info.emit(self.ANC300_info)
#         self.sig_cap_measurement_info.emit("")

#     def run(self):
#         if self.job == "enable_axis":
#             self.set_enable_axis(self.target_axis)
#             self.target_axis = None

#         elif self.job == "ground_axis":
#             self.set_ground_axis(self.target_axis)

#         elif self.job == "ground_all_axis":
#             self.set_ground_all_axis()

#         elif self.job == "read_all_axis_capacitance":
#             self.read_all_axis_capacitance()
        
#         elif self.job == 'read_all_axis_info':
#             self.read_all_axis_info()
        
#         elif self.job == 'reset_scan_center':
#             self.reset_pos_indictor()

#         elif self.job == 'move_anm150_one_step':
#             self.move_anm150_one_step(self.target_axis, self.target_direction)
#             self.target_axis = None
#             self.target_direction = None

#         elif self.job == 'move_anm150_continuesly':
#             self.move_an150_continuesly(self.target_axis, self.target_direction)
#             self.target_axis = None
#             self.target_direction = None

#         self.reset_flags()
#         self.job = ""


    
# if __name__ == "__main__":
#     anc300_logic = ANC300Logic()
#     # anc300_logic.initialize("COM6")  # Example port name

#     time_start = time.time()
#     print("start info reading", time.time())
#     anc300_logic.read_all_axis_info()
#     time_end = time.time()
#     print("Time taken for reading info", time_end - time_start)

#     print("start capacitance reading")
#     time_start = time.time()
#     anc300_logic.read_all_axis_capacitance()
#     time_end = time.time()
#     print("Time taken for reading info and capacitance:", time_end - time_start)
#     anc300_logic.close()

        




import numpy as np
from PyQt6 import QtCore
import time
from anc300_hardware import ANC300Hardware

class ANC300Logic(QtCore.QThread):
    sig_name = QtCore.pyqtSignal(object)
    sig_ANC300_info =  QtCore.pyqtSignal(object)   # [axis, key, value]
    sig_cap_measurement_info = QtCore.pyqtSignal(object)
    sig_anm150_pos_indictor = QtCore.pyqtSignal(object)

    # ------------------------------------------------------------------ #
    #  Init / helpers
    # ------------------------------------------------------------------ #
    def __init__(self):
        super().__init__()
        self.ANC300 = ANC300Hardware()

        self.anm150_list = [1, 2, 3]   # step-mode axes
        self.anm200_list = [4, 5]      # dc-input axes

        # Build one canonical dictionary for *everything* we will ever emit
        self.ANC300_info = {
            **{ax: {'mode': 'unknown',
                    'capacitance': 0.0,
                    'step_volt': 0.0,
                    'freq': 0.0,
                    'pos': 0} for ax in self.anm150_list},
            **{ax: {'mode': 'unknown',
                    'capacitance': 0.0} for ax in self.anm200_list}
        }

        self._positioner_refresh_rate = 10      # Hz
        self.is_initialized = False
        self.port_name = ""

        self.reset_flags()
        self.job = ""

    def _set(self, axis: int, key: str, value):
        """Update local cache and emit exactly once."""
        self.ANC300_info[axis][key] = value
        self.sig_ANC300_info.emit([axis, key, value])

    def reset_flags(self):
        self.receieved_stop = False

    # ------------------------------------------------------------------ #
    #  Connection / initialisation
    # ------------------------------------------------------------------ #
    def initialize(self, port_name=""):
        if self.is_initialized:
            self.close()

        self.port_name = port_name
        self.is_initialized = self.ANC300.initialize(self.port_name)
        self.reset_flags()

        if self.is_initialized:
            self.set_ground_all_axis()      # puts everything in known state
            self.sig_name.emit(self.port_name)
            self.reset_pos_indictor()

    def close(self):
        self.set_ground_all_axis()
        self.ANC300.close()
        self.sig_name.emit("Disconnected")

    # ------------------------------------------------------------------ #
    #  Mode control
    # ------------------------------------------------------------------ #
    def set_ground_all_axis(self):
        for axis in self.anm150_list + self.anm200_list:
            self.ANC300.set_mode(axis, 'gnd')
            self._set(axis, 'mode', 'gnd')

    def set_ground_axis(self, axis):
        if axis not in self.anm150_list + self.anm200_list:
            print(f"Invalid axis: {axis}")
            return
        self.ANC300.set_mode(axis, 'gnd')
        self._set(axis, 'mode', 'gnd')

    def set_enable_axis(self, axis):
        if axis in self.anm150_list:
            self.ANC300.set_mode(axis, 'stp')
            self._set(axis, 'mode', 'stp')
        elif axis in self.anm200_list:
            self.ANC300.set_mode(axis, 'inp')
            self.ANC300.set_external_input_modes(axis, dcin=True)
            self._set(axis, 'mode', 'inp')
        else:
            print(f"Invalid axis: {axis}")

    # ------------------------------------------------------------------ #
    #  Motion
    # ------------------------------------------------------------------ #
    def set_move_anm150_one_step(self, axis, direction=True):
        if axis not in self.anm150_list:
            print(f"Invalid axis: {axis}");  return
        self.ANC300.move_by(axis, 1 if direction else -1)
        new_pos = self.ANC300_info[axis]['pos'] + (1 if direction else -1)
        self._set(axis, 'pos', new_pos)

    def set_move_anm150_continuously(self, axis, direction=True):
        if axis not in self.anm150_list:
            print(f"Invalid axis: {axis}");  return
        step_cnt = int(round(self.ANC300_info[axis]['freq'] /
                             self._positioner_refresh_rate))
        self.ANC300.move_by(axis, step_cnt if direction else -step_cnt)
        new_pos = self.ANC300_info[axis]['pos'] + (step_cnt if direction else -step_cnt)
        self._set(axis, 'pos', new_pos)

    # ------------------------------------------------------------------ #
    #  Parameter setters
    # ------------------------------------------------------------------ #
    def change_anm150_freq(self, axis, freq):
        if axis in self.anm150_list:
            self.ANC300.set_frequency(axis, freq)
            self._set(axis, 'freq', freq)
        else:
            print(f"Invalid axis: {axis}")

    def change_anm150_step_volt(self, axis, volt):
        if axis in self.anm150_list:
            self.ANC300.set_anm150_step_volt(axis, volt)
            self._set(axis, 'step_volt', volt)
        else:
            print(f"Invalid axis: {axis}")

    # ------------------------------------------------------------------ #
    #  Reset helpers
    # ------------------------------------------------------------------ #
    def reset_pos_indictor(self):
        for ax in self.anm150_list:
            self._set(ax, 'pos', 0)

    # ------------------------------------------------------------------ #
    #  Read-back helpers
    # ------------------------------------------------------------------ #
    def read_all_axis_info(self):
        for ax in self.anm150_list:
            self._set(ax, 'mode', self.ANC300.get_mode(ax))
            self._set(ax, 'step_volt', self.ANC300.get_voltage(ax))
            self._set(ax, 'freq', self.ANC300.get_frequency(ax))
        for ax in self.anm200_list:
            self._set(ax, 'mode', self.ANC300.get_mode(ax))

    def read_all_axis_capacitance(self):
        self.sig_cap_measurement_info.emit("Please wait till capacitance measurement is done.")
        for ax in self.anm150_list + self.anm200_list:
            cap = self.ANC300.get_capacitance(ax, measure=True)
            self._set(ax, 'capacitance', cap)
        self.sig_cap_measurement_info.emit("")

    # ------------------------------------------------------------------ #
    #  Thread dispatcher
    # ------------------------------------------------------------------ #
    def run(self):
        if self.job == "enable_axis":
            self.set_enable_axis(self.target_axis)

        elif self.job == "ground_axis":
            self.set_ground_axis(self.target_axis)

        elif self.job == "ground_all_axis":
            self.set_ground_all_axis()

        elif self.job == "read_all_axis_capacitance":
            self.read_all_axis_capacitance()

        elif self.job == 'read_all_axis_info':
            self.read_all_axis_info()

        elif self.job == 'reset_scan_center':
            self.reset_pos_indictor()

        elif self.job == 'move_anm150_one_step':
            self.set_move_anm150_one_step(self.target_axis, self.target_direction)

        elif self.job == 'move_anm150_continuously':
            self.set_move_anm150_continuously(self.target_axis, self.target_direction)
    
        # clean-up
        self.reset_flags()
        self.job = ""

# ---------------------------------------------------------------------- #
#  Stand-alone test
# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    anc300_logic = ANC300Logic()

    t0 = time.time()
    anc300_logic.read_all_axis_info()
    print("info read time:", time.time() - t0, "s")

    print("start capacitance reading")
    t0 = time.time()
    anc300_logic.read_all_axis_capacitance()
    print("capacitance read time:", time.time() - t0, "s")

    anc300_logic.close()
