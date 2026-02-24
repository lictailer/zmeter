"""
Multi-Level Scanning Logic Module

This module implements a hierarchical scanning system that can execute multi-level parameter sweeps
with real-time data acquisition and progress tracking. The system supports nested scanning loops
where higher levels change slower than lower levels, enabling complex measurement sequences.

Key Features:
- Recursive multi-level scanning with configurable setters and getters
- Real-time progress tracking with time estimates
- PyQt6 signal-based communication with GUI
- Support for both linear and explicit parameter settings
- Artificial channel support for calculated parameters
- Manual pre/post level settings
"""

import numpy as np
from PyQt6 import QtCore, QtWidgets, uic
import datetime
import time
from scipy.io import savemat
import random
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor

# Example scan configuration structure showing the expected data format
ScanInfo = {
    "levels": {
        # Level 0: Innermost scanning level (changes fastest)
        "level0": {
            "setters": {
                # Each setter defines a parameter to be swept
                "setter0": {
                    "channel": "lockin_0_f",  # Hardware channel identifier
                    "explicit": False,         # Use linear vs explicit values
                    "linear_setting": {        # Linear sweep parameters
                        "start": 0,
                        "end": 10,
                        "step": 1,
                        "mid": 5,
                        "span": 10,
                        "points": 11,
                        "destinations": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
                    },
                    "explicit_setting": [-1, 1, 0],  # Manual value list
                    "destinations": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]  # Final values to use
                },
                "setter1": {
                    "channel": "lockin_0_A",
                    "explicit": True,  # This setter uses explicit values
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
                    "destinations": [-1, 1, 0]  # Only these 3 values will be used
                }
            },
            "setting_method": "[AB]",  # Method identifier for how to apply settings
            "getters": ['lockin_0_X'],  # Channels to read measurements from
            # 2D array: [setter_values][point_index] - NaN values skip that setter
            "setting_array": [[0,1,2,3,4,5,6,7,8,9,10],
                              [-1,1,0,np.nan,np.nan,np.nan,np.nan,np.nan,np.nan,np.nan,np.nan]]
        },
        # Level 1: Outer scanning level (changes slower)
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
    'data': {
        # This section will be populated with measurement results during scanning
    },
    "plots": {
        "line_plots": {
            # Plot configuration for real-time data visualization
        },
        "image_plots": {
            # 2D plot configuration for multi-dimensional data
        }
    },
}


class ScanLogic(QtCore.QThread):
    """
    Multi-level scanning logic thread that executes hierarchical parameter sweeps.
    
    This class implements a recursive scanning algorithm where multiple levels of parameters
    can be swept simultaneously. Higher-numbered levels change slower than lower-numbered
    levels, creating nested scanning loops. The thread communicates with the main GUI
    through Qt signals for real-time updates.
    
    Signals:
        sig_new_data: Emitted when new measurement data is acquired
        sig_new_pos: Emitted when scan position changes
        sig_update_line: Emitted to update line plots
        sig_set_image_source: Emitted to update image plot data source
        sig_scan_finished: Emitted when entire scan sequence completes
        sig_update_remaining_time: Emitted with time estimate string
        sig_update_remaining_points: Emitted with progress information
    """
    
    # Qt signals for communication with GUI
    sig_new_data = QtCore.pyqtSignal(object)                # New measurement data available
    sig_new_pos = QtCore.pyqtSignal(object)                 # Position update for tracking
    sig_update_line = QtCore.pyqtSignal()                   # Update line plot displays
    sig_set_image_source = QtCore.pyqtSignal(object)        # Set data source for image plots
    sig_scan_finished = QtCore.pyqtSignal()                 # Scan completion notification
    sig_update_remaining_time = QtCore.pyqtSignal(str)      # Time estimate updates
    sig_update_remaining_points = QtCore.pyqtSignal(str)    # Progress tracking updates
    sig_auto_backup = QtCore.pyqtSignal(bool)                   # Auto-backup trigger every hour

    # Hardware channel definitions for NI-DAQ analog I/O
    AI = ['AI0', 'AI1', 'AI2', 'AI3', 'AI4', 'AI5', 'AI6', 'AI7']  # Analog input channels
    AO = ['AO0', 'AO1', 'AO2', 'AO3']                              # Analog output channels

    def __init__(self, main_window=None):
        QtCore.QThread.__init__(self)
        self.main_window = main_window

        # --- NEW: pause primitives ---
        self._pause_mutex = QtCore.QMutex()
        self._pause_cond = QtCore.QWaitCondition()
        self.received_pause = False  # NEW

        self.reset_flags()

        # Progress tracking variables
        self.scan_start_time = None
        self.elapsed_time = None
        self.total_points = 0
        self.completed_points = 0
        self.last_auto_hour_triggered = 0

    def initialize_scan_data(self, scan_config):
        """
        Initialize all data structures and parameters for a new scan.
        
        This method prepares the scanning system by:
        1. Calculating total scan points for progress tracking
        2. Extracting setter/getter configurations for each level
        3. Initializing data arrays with appropriate dimensions
        4. Setting up position tracking arrays
        
        Args:
            scan_config: Dictionary containing complete scan configuration
        """
        # Initialize timing variables for progress tracking
        self.scan_start_time = None
        self.elapsed_time = None
        self.completed_points = 0
        self.last_auto_hour_triggered = 0
        
        # Calculate total number of measurement points across all levels
        self.total_points = 1
        for level_index in range(len(scan_config['levels'])):
            self.total_points *= scan_config['levels'][f'level{level_index}']['setting_array'].shape[1]
        
        # Initialize data structure arrays for each scanning level
        self.level_target_arrays = []      # Parameter values to set at each level
        self.level_setters = []            # Hardware channels to write to
        self.level_getters = []            # Hardware channels to read from
        self.level_data_arrays = []        # Storage for measurement results
        self.level_target_counts = []      # Number of points per level (including NaN)
        self.level_getter_counts = []      # Number of measurement channels per level
        self.level_manual_settings = []    # Manual settings before/after each level
        self.stop_scan = False             # Flag for graceful scan termination
        
        # Extract configuration data for each scanning level
        level_number = len(scan_config['levels'])
        self.max_level = level_number - 1  # Highest level index (outermost loop)

        for level_index in range(level_number):
            # Extract setter parameter arrays (what values to set)
            self.level_target_arrays.append(scan_config['levels'][f'level{level_index}']['setting_array'])

            # Extract setter channel names (where to set values)
            setters = []
            for setter in scan_config['levels'][f'level{level_index}']['setters'].values():
                setters.append(setter['channel'])
            self.level_setters.append(setters)
            
            # Extract getter channel names (where to read measurements)
            if len(scan_config['levels'][f'level{level_index}']['getters']) == 0:
                scan_config['levels'][f'level{level_index}']['getters'].append('none')
            self.level_getters.append(scan_config['levels'][f'level{level_index}']['getters'])

            # Store the number of measurement points for this level
            self.level_target_counts.append(self.level_target_arrays[level_index].shape[1])

            # Extract manual settings that run before/after this level
            temp_manual_set = [scan_config['levels'][f'level{level_index}']['manual_set_before'], 
                              scan_config['levels'][f'level{level_index}']['manual_set_after']]
            self.level_manual_settings.append(temp_manual_set)

        # Count getter channels for each level
        for getters in self.level_getters:
            self.level_getter_counts.append(len(getters))
        
        # Initialize multi-dimensional data arrays for storing measurement results
        # Array dimensions: [getter_channels, level_N_points, level_N-1_points, ..., current_level_points]
        for level_index in range(level_number):
            data_shape = []
            data_shape.append(self.level_getter_counts[level_index])  # Number of measurement channels
            
            # Add dimensions for all levels from outermost to current level
            for i in range(level_number - 1, level_index - 1, -1):
                data_shape.append(self.level_target_counts[i])
            
            # Initialize with NaN values (indicates no measurement taken yet)
            self.level_data_arrays.append(np.full(shape=data_shape, fill_value=np.nan))
        
        # Initialize position tracking arrays for each level
        self.current_target_indices = []
        for level_index in range(self.max_level + 1):
            self.current_target_indices.append(0)

    def reset_flags(self):
        """Reset all control flags to their default states."""
        self.go_scan = False
        self.go_save = False
        self.received_stop = False

        self.received_pause = False
        self._pause_cond.wakeAll()

    @QtCore.pyqtSlot()
    def request_pause(self):
        """Pause the scan (thread will block at safe points)."""
        with QtCore.QMutexLocker(self._pause_mutex):
            self.received_pause = True

    @QtCore.pyqtSlot()
    def request_resume(self):
        """Resume the scan if paused."""
        with QtCore.QMutexLocker(self._pause_mutex):
            self.received_pause = False
            self._pause_cond.wakeAll()

    @QtCore.pyqtSlot()
    def request_stop(self):
        """Stop the scan; also releases any pause wait."""
        with QtCore.QMutexLocker(self._pause_mutex):
            self.received_stop = True
            self.received_pause = False
            self._pause_cond.wakeAll()

    def _pause_gate(self) -> bool:
        """
        Block here while paused.
        Returns True if a stop was requested (caller should exit).
        """
        self._pause_mutex.lock()
        try:
            while self.received_pause and not self.received_stop:
                # Wait with a timeout so the thread can still react quickly
                # even if a wake is missed (rare but safe).
                self._pause_cond.wait(self._pause_mutex, 200)  # ms
            return self.received_stop
        finally:
            self._pause_mutex.unlock()

    def looping(self, current_level):
        # Base case
        if current_level == -1:
            return

        if self._pause_gate() or self.received_stop:
            return

        if current_level == self.max_level and self.scan_start_time is None:
            self.scan_start_time = time.time()

        # Manual set BEFORE
        for setting_dict in self.level_manual_settings[current_level][0]:
            for key, value in setting_dict.items():
                if self._pause_gate() or self.received_stop:
                    return
                self.main_window.write_info(value, key)

        reading_device_channels = self.group_reading_device_channels(current_level)
        writing_device_channels = self.group_writing_device_channels(current_level)

        for target_index in range(self.level_target_counts[current_level]):
            if self._pause_gate() or self.received_stop:
                return

            # write
            self.multi_thread_write(writing_device_channels, current_level, target_index)

            if self._pause_gate() or self.received_stop:
                return

            if self.level_getter_counts[current_level] == 0:
                break

            # read
            skip_lower_level = self.main_window.artificial_channel_logic.consume_skip_read_for_scan()
            if skip_lower_level:
                measurements = self.build_nan_measurements(reading_device_channels)
            else:
                measurements = self.multi_thread_read(reading_device_channels)

            if self._pause_gate() or self.received_stop:
                return

            # store measurements
            for getter_index in range(len(self.level_getters[current_level])):
                getter_channel = self.level_getters[current_level][getter_index]
                if getter_channel == "none":
                    continue
                indices_slice = slice(self.max_level, current_level, -1)
                indices = self.current_target_indices[indices_slice]
                full_index_tuple = (getter_index, *indices, self.current_target_indices[current_level])
                self.level_data_arrays[current_level][full_index_tuple] = measurements[getter_channel]

            current_target_indices_copy = deepcopy(self.current_target_indices)
            self.sig_new_data.emit([self.level_data_arrays, current_target_indices_copy])

            # Skip lower/faster levels when an artificial-channel write was skipped.
            if not skip_lower_level:
                self.looping(current_level - 1)

            # progress updates
            self.current_target_indices[current_level] += 1
            point_end_time = time.time()
            self.elapsed_time = point_end_time - self.scan_start_time
            self.completed_points += 1
            self.update_remaining_time_estimate()
            self.check_auto_backup_trigger()

        # Manual set AFTER
        for setting_dict in self.level_manual_settings[current_level][1]:
            for key, value in setting_dict.items():
                if self._pause_gate() or self.received_stop:
                    return
                self.main_window.write_info(value, key)

        self.current_target_indices[current_level] = 0

    def extract_device_from_channel(self, channel_name):
        """
        Extract device name from channel identifier by comparing against known devices.
        
        This method checks the channel name against the list of devices stored in 
        main_window.equips to find the matching device name. This approach handles
        devices with any number of underscores in their names correctly.
        
        Args:
            channel_name: Full channel identifier string (e.g., "lockin_0_frequency")
            
        Returns:
            tuple: (device_name, variable) where device_name matches a known device
                   and variable is everything after the device name and underscore.
                   If no match found, returns (channel_name, "")
        """
        if self.main_window and hasattr(self.main_window, 'equips'):
            # Check if channel name starts with any known device name
            for device_name in self.main_window.equips.keys():
                if channel_name.startswith(f"{device_name}_"):
                    # Extract the remaining part after device_name_
                    variable = channel_name[len(device_name) + 1:]
                    return device_name, variable
            if channel_name.startswith("artificial_channel_"):
                return "artificial_channel", channel_name[len("artificial_channel_"):]
            elif channel_name.startswith("default_channel_"):
                return "default", channel_name[len("default_")+1:]
        
        # If no pattern matches, return the whole string as device name with empty remaining part
        return channel_name, ""

    def extract_variable_from_channel(self, channel_name):
        """
        Extract variable name from standardized channel naming convention.
        
        Expected format: "device_instance_variable" (e.g., "lockin_0_frequency")
        Returns the variable portion after the second underscore.
        
        Args:
            channel_name: Full channel identifier string
            
        Returns:
            str: Variable name portion of the channel identifier
        """
        underscore_count = 0
        for index, character in enumerate(channel_name):
            if character == '_':
                if underscore_count == 1:  # Found second underscore
                    return channel_name[index + 1:]
                else:
                    underscore_count += 1
    
    def group_reading_device_channels(self, level_index):
        device_channels = {}
        
        # Read from each getter channel configured for this level
        for getter_index in range(self.level_getter_counts[level_index]):
            getter_channel = self.level_getters[level_index][getter_index]
            
            # Extract device name and variable name
            device_name, variable = self.extract_device_from_channel(getter_channel)
            
            # Group channels by device
            if device_name == None or device_name == "none" or device_name == "":
                continue
            elif device_name not in device_channels:
                device_channels[device_name] = []
            device_channels[device_name].append(variable)
            
        return device_channels
        
    def multi_thread_read(self, device_channels):
        start_time = time.time()
        if len(device_channels) == 0:
            return {}
        with ThreadPoolExecutor(max_workers=len(device_channels)) as executor:
            futures = [executor.submit(self.read_single_device_all_channels, device, channel_list) for device, channel_list in device_channels.items()]
            # Combine all dictionary results into a single dictionary
            combined_results = {}
            for future in futures:
                result_dict = future.result()
                combined_results.update(result_dict)
        end_time = time.time()
        return combined_results

    def build_nan_measurements(self, device_channels):
        skipped_measurements = {}
        for device, channel_list in device_channels.items():
            for channel in channel_list:
                skipped_measurements[f"{device}_{channel}"] = np.nan
        return skipped_measurements

    def read_single_device_all_channels(self, device, channel_list):
        result = {}
        start_time = time.time()
        for channel in channel_list:
            if self.main_window.artificial_channel_logic.has_artificial_channel(channel):
                result[f"{device}_{channel}"] = self.main_window.artificial_channel_logic.read_channel_value(channel)
            else:
                result[f"{device}_{channel}"] = self.main_window.read_info(f"{device}_{channel}")
        end_time = time.time()
        return result

    def group_writing_device_channels(self, level_index):
        device_channels = {}
        for setter_index in range(len(self.level_setters[level_index])):
            setter_channel = self.level_setters[level_index][setter_index]
            device_name, variable = self.extract_device_from_channel(setter_channel)
            if device_name not in device_channels:
                device_channels[device_name] = {}
            device_channels[device_name][variable] = 0
        return device_channels

    def write_single_device_all_channels(self, device, channel_value_list):
        for channel, value in channel_value_list.items():
            if self.main_window.artificial_channel_logic.has_artificial_channel(channel):
                self.main_window.artificial_channel_logic.set_channel_value(
                    channel,
                    value,
                    is_scan_write=True,
                )
            else:
                self.main_window.write_info(value, f"{device}_{channel}")

    def multi_thread_write(self, writing_device_channels, level_index, target_index):
        set_value = self.level_target_arrays[level_index][:, target_index]
        print("writing_device_channels.items(): ",writing_device_channels.items())
        for device, channel_list in writing_device_channels.items():
            print("channel_list:", channel_list)
            for channel in channel_list:
                channel_list_index = self.level_setters[level_index].index(f"{device}_{channel}")
                writing_device_channels[device][channel] = set_value[channel_list_index]
        with ThreadPoolExecutor(max_workers=len(writing_device_channels)) as executor:
            futures = [executor.submit(self.write_single_device_all_channels, device, channel_value_list) for device, channel_value_list in writing_device_channels.items()]

    def generate_file_for_save(self):
        """
        Generate a dictionary containing all scan data formatted for file saving.
        
        Returns:
            dict: Complete scan data including setters, targets, getters, and results
        """
        save_data = {}
        num_levels = len(self.level_setters)
        
        # Package data for each scanning level
        for level_index in range(num_levels):
            # Save setter channel names
            save_data[f"level{level_index}_setter"] = self.level_setters[level_index]

            # Save target parameter arrays for each setter
            for setter_index in range(len(self.level_setters[level_index])):
                save_data[f"level{level_index}_index{setter_index}_targets"] = np.array(
                    self.level_target_arrays[level_index][setter_index])

            # Save getter information and measurement results
            if self.level_getters[level_index]:
                save_data[f"level{level_index}_getter"] = self.level_getters[level_index]
                save_data[f"level{level_index}_result"] = self.results[level_index]
                
        save_data["comments"] = self.comments
        return save_data

    def scan(self):
        """
        Execute the complete scanning sequence.
        
        This method starts the recursive scanning process and handles cleanup
        when the scan completes or is interrupted.
        """
        try:
            # Start recursive scanning from the outermost level
            self.looping(self.max_level)
        finally:
            # Ensure proper cleanup regardless of how scan ends
            self.reset_flags()
            print("scan finished here")
            
            # Re-enable equipment that was stopped for scanning
            self.main_window.start_equipments()
            
            # Notify GUI that scan is complete
            self.sig_scan_finished.emit()

    def run(self):
        """
        Main thread execution method (QThread override).
        
        This method is called when the thread starts. It checks the go_scan flag
        and initiates scanning if requested.
        """
        if self.go_scan:
            print("start scanning")
            self.scan()

        # Reset flags when thread execution completes
        self.reset_flags()

    def check_auto_backup_trigger(self):
        """
        Trigger auto-backup once when crossing each elapsed whole-hour mark.
        """
        if self.scan_start_time is None:
            return

        elapsed_hours = int((time.time() - self.scan_start_time) // 3600)
        if elapsed_hours >= 1 and elapsed_hours > self.last_auto_hour_triggered:
            self.last_auto_hour_triggered = elapsed_hours
            self.sig_auto_backup.emit(True)

    def update_remaining_time_estimate(self):
        """
        Calculate and emit time/progress estimates for user feedback.
        
        This method computes:
        - Average time per measurement point
        - Estimated remaining time
        - Percentage completion
        - Total estimated scan time
        
        Results are emitted via Qt signals for GUI display.
        """
        if self.completed_points == 0:
            return
            
        # Calculate timing statistics
        avg_time_per_point = self.elapsed_time / self.completed_points
        remaining_points = max(0, self.total_points - self.completed_points)  # Ensure non-negative
        completed_percentage = round(min(100, self.completed_points / self.total_points * 100))  # Cap at 100%
        remaining_seconds = max(0, remaining_points * avg_time_per_point)  # Ensure non-negative
        total_time = self.total_points * avg_time_per_point
        
        # Format time strings as HH:MM:SS
        remaining_time_str = f"{datetime.timedelta(seconds=int(remaining_seconds))} / {datetime.timedelta(seconds=int(total_time))}"
        remaining_points_str = f"{self.completed_points} / {self.total_points} ({completed_percentage}%)"
        
        # Emit signals for GUI updates
        self.sig_update_remaining_time.emit(remaining_time_str)
        self.sig_update_remaining_points.emit(remaining_points_str)

# Test/demo code for standalone execution
if __name__ == "__main__":
    # Create and test scan logic with sample configuration
    scan_logic = ScanLogic()
    scan_logic.initialize_scan_data(ScanInfo)
    scan_logic.scan()
    
