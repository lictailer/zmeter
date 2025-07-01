import numpy as np
from PyQt6 import QtCore, QtWidgets, uic
import time
import datetime
from scipy.io import savemat
import random
from copy import deepcopy

ScanInfo = {
    "levels": {
        "level0": {
            "setters": {
                "setter0": {
                    "channel": "lockin_0_f",
                    "explicit": False,
                    "linear_setting": {
                        "start": 0,
                        "end": 10,
                        "step": 1,
                        "mid": 5,
                        "span": 10,
                        "points": 11,
                        "destinations": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
                    },
                    "explicit_setting": [-1, 1, 0],
                    "destinations": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
                },
                "setter1": {
                    "channel": "lockin_0_A",
                    "explicit": True,
                    "linear_setting": {
                        "start": 0,
                        "end": 100,
                        "step": 1,
                        "mid": 50,
                        "span": 100,
                        "points": 101,
                        "destinations": np.linspace(0, 100, 101)
                    },
                    "explicit_setting": [-1, 1, 0],
                    "destinations": [-1, 1, 0]
                }
            },
            "setting_method": "[AB]",
            "getters": ['lockin_0_X'],
            "setting_array": [[0,1,2,3,4,5,6,7,8,9,10],
                              [-1,1,0,np.nan,np.nan,np.nan,np.nan,np.nan,np.nan,np.nan,np.nan]]
        },
        "level1": {
            "setters": {
                "setter0": {
                    "channel": "lockin_1_p",
                    "explicit": False,
                    "linear_setting": {
                        "start": 0,
                        "end": 2,
                        "step": 1,
                        "mid": 1,
                        "span": 2,
                        "points": 3,
                        "destinations": [0, 1, 2]
                    },
                    "explicit_setting": [-2, 2, 0],
                    "destinations": [0, 1, 2]
                }
            },
            "setting_method": "A+B,CL",
            "getters": ['lockin_0_Y'],
            "setting_array": [[0,1,2]]
        }
    },
    'data':{
            },
    "plots": {
        "line_plots": {
            
        },
        "image_plots": {
            
        }
    },
    
    
}


class ScanLogic(QtCore.QThread):
    sig_new_data = QtCore.pyqtSignal(object)
    sig_new_pos = QtCore.pyqtSignal(object)
    sig_update_line = QtCore.pyqtSignal()
    sig_set_image_source = QtCore.pyqtSignal(object)
    sig_scan_finished = QtCore.pyqtSignal()
    sig_update_remaining_time = QtCore.pyqtSignal(str)
    sig_update_remaining_points = QtCore.pyqtSignal(str)  # New signal for remaining time updates

    AI = ['AI0', 'AI1', 'AI2', 'AI3', 'AI4', 'AI5', 'AI6', 'AI7']
    AO = ['AO0', 'AO1', 'AO2', 'AO3']

    def __init__(self, main_window=None):
        QtCore.QThread.__init__(self)
        self.main_window = main_window
        self.reset_flags()
        self.scan_start_time = None
        self.time_spend = None
        self.total_points = 0
        self.completed_points = 0

    def initilize_data(self, info):
        # Initialize timing variables
        self.scan_start_time = None
        self.time_spend = None
        self.completed_points = 0
        
        # Calculate total number of points in the scan
        self.total_points = 1
        for l in range(len(info['levels'])):
            print(info['levels'][f'level{l}']['setting_array'])
            self.total_points *= info['levels'][f'level{l}']['setting_array'].shape[1]
        

        # FEL: for each level
        self.targets_array_FEL = []
        self.setters_FEL = []
        self.getters_FEL = []
        self.data_FEL = []
        self.setters_targets_len_FEL = []  # FEL, for each setter, how long is the array including nans
        self.getter_number_FEL = []
        self.manual_set_FEL = []
        self.stop_scan = False
        # populate the FEL members
        level_number = len(info['levels'])
        self.max_level = level_number - 1

        for l in range(level_number):
            self.targets_array_FEL.append(info['levels'][f'level{l}']['setting_array'])

            setters = []
            for setter in info['levels'][f'level{l}']['setters'].values():
                setters.append(setter['channel'])
            self.setters_FEL.append(setters)
            if len(info['levels'][f'level{l}']['getters']) == 0:
                info['levels'][f'level{l}']['getters'].append('none')
            self.getters_FEL.append(info['levels'][f'level{l}']['getters'])

            self.setters_targets_len_FEL.append(self.targets_array_FEL[l].shape[1])

            temp_manual_set = [info['levels'][f'level{l}']['manual_set_before'], info['levels'][f'level{l}']['manual_set_after']]
            self.manual_set_FEL.append(temp_manual_set)

        for g in self.getters_FEL:
            self.getter_number_FEL.append(len(g))
        # initialize data array
        for l in range(level_number):

            g = []
            g.append(self.getter_number_FEL[l])
            for i in range(level_number - 1, l - 1, -1):
                g.append(self.setters_targets_len_FEL[i])
            # g = [self.getter_number_FEL[l], *self.setters_targets_len_FEL[0:l]]
            # print("g:",g)
            self.data_FEL.append(np.full(shape=g, fill_value=np.nan))
            # [2,3,3,11][1,3,3][1,3]
            # [11,3,3]
            # [2,1,1]
        #
        self.current_target_indexs = []
        for l in range(self.max_level + 1):
            self.current_target_indexs.append(0)
        # print("\nself.targets_array_FEL:")
        # print(self.targets_array_FEL)
        # print("\nself.setters_FEL:")
        # print(self.setters_FEL)
        # print("\nself.getters_FEL:")
        # print(self.getters_FEL)
        # print("\nself.data_FEL:")
        # print(self.data_FEL)
        # print("\nself.setters_targets_len_FEL:")
        # print(self.setters_targets_len_FEL)
        # print("\nself.getter_number_FEL:")
        # print(self.getter_number_FEL)
        # print("\nself.max_level:")
        # print(self.max_level)
        # print("\nself.current_target_indexs:")
        # print(self.current_target_indexs)

    def reset_flags(self):
        self.go_scan = False
        self.go_save = False
        self.received_stop = False

    def looping(self, l):
        # print("current level:", l)
        """
        higher levels changes slower, but changes earlier
        lower levels are the working ones
        """
        if l == -1:
            return
        
        # Record start time when we begin the first level
        if l == self.max_level and self.scan_start_time is None:
            self.scan_start_time = time.time()

        for setting_dict in self.manual_set_FEL[l][0]:
            for key, value in setting_dict.items():
                if self.received_stop:
                    return
                if 'control' in key:
                    self.main_window.execute_control(value,key)
                else:
                    self.main_window.write_info(value, key)

        # do manual set before
        for i in range(self.setters_targets_len_FEL[l]):
            if self.received_stop:
                return
            self.write(l, i)
            if self.getter_number_FEL[l] == 0:
                break
            r = self.read(l)
            for j in range(self.getter_number_FEL[l]):
                indices_slice = slice(self.max_level, l, -1)

                # Extract the slice as a list of indices
                indices = self.current_target_indexs[indices_slice]

                # Create the full index tuple including the slice as expanded indices
                full_index_tuple = (j, *indices, self.current_target_indexs[l])

                # Use the full index tuple to access and set data in self.data_FEL
                self.data_FEL[l][full_index_tuple] = r[j]
                # new_data_point_location=l,j,*self.current_target_indexs[self.max_level:l:-1],self.current_target_indexs[l]
                # print(self.data_FEL)
                # print("new_data_point_location",new_data_point_location)
                # print('self.current_target_indexs',self.current_target_indexs)
                # time.sleep(0.01)
            current_target_indexs = deepcopy(self.current_target_indexs)

            self.sig_new_data.emit([self.data_FEL, current_target_indexs])
            # time.sleep(0.01)
            # print('emitted')

            self.looping(l - 1)

            # Update timing information after each point
            self.current_target_indexs[l] += 1
            point_end_time = time.time()
            self.time_spend = point_end_time - self.scan_start_time
            self.completed_points += 1
            
            # Calculate and emit remaining time estimate
            self.update_remaining_time_estimate()

        for setting_dict in self.manual_set_FEL[l][1]:
            for key, value in setting_dict.items():
                self.main_window.write_info(value, key)

        self.current_target_indexs[l] = 0

    def write(self, lv, index):
        artificial_setters_and_vals = {}  # {artificial channel name ; val}
        for i, ss in enumerate(self.setters_FEL[lv]):
            val = self.targets_array_FEL[lv][i, index]
            variable = self.get_variable(ss)
            if variable in self.main_window.equations:
                self.main_window.write_artificial_channel(val, variable)
            elif('control' in ss):
                self.main_window.execute_control(val,ss)
            else:
                self.main_window.write_info(val, ss)

    def get_variable(self, name):
        counter = False
        for index, character in enumerate(name):
            if character == '_':
                if counter:
                    return name[index + 1::]
                else:
                    counter = True

    def read(self, lv):
        r = []
        for j in range(self.getter_number_FEL[lv]):
            slave = self.getters_FEL[lv][j]
            variable = self.get_variable(slave)
            if variable in self.main_window.equations:
                r.append(self.main_window.read_artificial_channel(variable))
            else:
                r.append(self.main_window.read_info(slave))

        return r

    def generate_file_for_save(self):
        d = {}
        levels = len(self.setters_FEL)
        for l in range(levels):
            d[f"level{l}_setter"] = self.setters_FEL[l]

            for i in range(len(self.setters_FEL[l])):
                d[f"level{l}_index{i}_targets"] = np.array(
                    self.targets_array_FEL[l][i])  # need array?

            if self.getters_FEL[l]:
                d[f"level{l}_getter"] = self.getters_FEL[l]
                d[f"level{l}_result"] = self.results[l]
        d["comments"] = self.comments
        return d

    def scan(self):
        # self.initilize_data()
        # self.sig_set_image_source.emit(self.results)
        try:
            self.looping(self.max_level)
        finally:
            self.reset_flags()
            print("scan finished here")
            self.main_window.start_equipments()
            self.sig_scan_finished.emit()

    def run(self):
        if self.go_scan:
            print("start scanning")
            self.scan()

        self.reset_flags()

    def update_remaining_time_estimate(self):
        if self.completed_points == 0:
            return
            
        avg_time_per_point = self.time_spend / self.completed_points
        remaining_points = self.total_points - self.completed_points
        completed_precentage = round(self.completed_points / self.total_points * 100)
        remaining_seconds = remaining_points * avg_time_per_point
        total_time = self.total_points * avg_time_per_point
        
        # Format remaining time as HH:MM:SS
        remaining_time_str = f"{datetime.timedelta(seconds=int(remaining_seconds))} / {datetime.timedelta(seconds=int(total_time))}"
        remaining_points_str = f"{self.completed_points} / {self.total_points} ({completed_precentage}%)"
        self.sig_update_remaining_time.emit(remaining_time_str)
        self.sig_update_remaining_points.emit(remaining_points_str)


if __name__ == "__main__":
    
    a = ScanLogic()
    a.initilize_data(ScanInfo)
    a.scan()
    
