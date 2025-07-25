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

    # Hardware channel definitions for NI-DAQ analog I/O
    AI = ['AI0', 'AI1', 'AI2', 'AI3', 'AI4', 'AI5', 'AI6', 'AI7']  # Analog input channels
    AO = ['AO0', 'AO1', 'AO2', 'AO3']                              # Analog output channels

    def __init__(self, main_window=None):
        """
        Initialize the scanning logic thread.
        
        Args:
            main_window: Reference to main application window for hardware communication
        """
        QtCore.QThread.__init__(self)
        self.main_window = main_window
        self.reset_flags()
        
        # Progress tracking variables
        self.scan_start_time = None
        self.elapsed_time = None
        self.total_points = 0
        self.completed_points = 0

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
        
        # Calculate total number of measurement points across all levels
        self.total_points = 1
        for level_index in range(len(scan_config['levels'])):
            print(scan_config['levels'][f'level{level_index}']['setting_array'])
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
        self.go_scan = False           # Start scanning flag
        self.go_save = False           # Save data flag  
        self.received_stop = False     # Stop request flag

    def looping(self, current_level):
        """
        Recursively execute scanning loops for all levels.
        
        This is the core scanning algorithm that implements nested parameter sweeps.
        Higher-numbered levels (outer loops) change slower than lower-numbered levels
        (inner loops). The recursion naturally creates the nested loop structure.
        
        Execution order for a 2-level scan:
        1. Set level1 to first value
        2. Set level0 to first value, measure, recurse to level -1 (measure)
        3. Set level0 to second value, measure, recurse to level -1 (measure)
        4. ... continue through all level0 values
        5. Set level1 to second value
        6. Repeat steps 2-4 for all level0 values
        7. Continue until all level1 values are complete
        
        Args:
            current_level: Current recursion level (max_level down to -1)
                          -1 indicates end of recursion (measurement point)
        """
        # Base case: reached the end of recursion
        if current_level == -1:
            return
        
        # Record start time when beginning the outermost level (first call)
        if current_level == self.max_level and self.scan_start_time is None:
            self.scan_start_time = time.time()

        # Execute any manual settings configured to run before this level
        for setting_dict in self.level_manual_settings[current_level][0]:
            for key, value in setting_dict.items():
                if self.received_stop:
                    return
                else:
                    self.main_window.write_info(value, key)

        reading_device_channels = self.group_reading_device_channels(current_level)
        print("reading_device_channels", reading_device_channels)
        # Iterate through all target points at this level
        for target_index in range(self.level_target_counts[current_level]):
            if self.received_stop:
                return
            
            # Set parameter values for all setters at this level
            self.set_level_values(current_level, target_index)
            
            # Skip measurement if no getter channels defined for this level
            if self.level_getter_counts[current_level] == 0:
                break
            
            # Read measurements from all getter channels at this level
            # measurements = self.read_level_measurements(current_level)
            measurements = self.multi_thread_read(reading_device_channels)

            print("measurements", measurements)
            # raise Exception("stop here")

            # Store measurements in the appropriate data array location
            for getter_index in range(len(self.level_getters[current_level])):
                 # Build index tuple for N-dimensional data array access
                getter_channel = self.level_getters[current_level][getter_index]
                indices_slice = slice(self.max_level, current_level, -1)  # Outer level indices
                indices = self.current_target_indices[indices_slice]
                full_index_tuple = (getter_index, *indices, self.current_target_indices[current_level])
                self.level_data_arrays[current_level][full_index_tuple] = measurements[getter_channel]           
            
            # Emit new data signal for real-time GUI updates
            current_target_indices_copy = deepcopy(self.current_target_indices)
            self.sig_new_data.emit([self.level_data_arrays, current_target_indices_copy])

            # Recursively execute lower levels (inner loops)
            self.looping(current_level - 1)

            # Update progress tracking after completing this measurement point
            self.current_target_indices[current_level] += 1
            point_end_time = time.time()
            self.elapsed_time = point_end_time - self.scan_start_time
            self.completed_points += 1
            
            # Update time remaining estimates for user feedback
            self.update_remaining_time_estimate()

        # Execute any manual settings configured to run after this level
        for setting_dict in self.level_manual_settings[current_level][1]:
            for key, value in setting_dict.items():
                self.main_window.write_info(value, key)

        # Reset this level's index counter for next iteration of outer level
        self.current_target_indices[current_level] = 0

    def set_level_values(self, level_index, target_index):
        """
        Set all parameter values for the specified level and target index.
        
        This method writes values to hardware channels or artificial channels
        based on the setter configuration for the current level.
        
        Args:
            level_index: Which scanning level to set values for
            target_index: Which point within that level's parameter array
        """
        artificial_setters_and_vals = {}  # For calculated/artificial channels
        
        # Set each setter channel for this level
        for setter_index, setter_channel in enumerate(self.level_setters[level_index]):
            # Get the value from the 2D parameter array [setter][point]
            value = self.level_target_arrays[level_index][setter_index, target_index]
            
            # Extract variable name from channel identifier (e.g., "device_0_variable" -> "variable")
            variable = self.extract_variable_from_channel(setter_channel)
            
            # Check if this is an artificial/calculated channel
            if variable in self.main_window.equations:
                self.main_window.write_artificial_channel(value, variable)
            else:
                # Write directly to hardware channel
                self.main_window.write_info(value, setter_channel)

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
    
    #### old code sequential reading ####
    # def read_level_measurements(self, level_index):
    #     """
    #     Read measurement values from all getter channels for the specified level.
        
    #     Args:
    #         level_index: Which scanning level to read measurements for
            
    #     Returns:
    #         list: Measurement values from all getter channels at this level
    #     """
    #     measurements = []
        
    #     # Read from each getter channel configured for this level
    #     for getter_index in range(self.level_getter_counts[level_index]):
    #         getter_channel = self.level_getters[level_index][getter_index]
    #         variable = self.extract_variable_from_channel(getter_channel)
            
    #         # Check if this is an artificial/calculated channel
    #         if variable in self.main_window.equations:
    #             measurements.append(self.main_window.read_artificial_channel(variable))
    #         else:
    #             # Read directly from hardware channel
    #             measurements.append(self.main_window.read_info(getter_channel))

    #     return measurements

    # def read_level_measurements(self, level_index):
    #     """
    #     Read measurement values from all getter channels for the specified level.
        
    #     Args:
    #         level_index: Which scanning level to read measurements for
            
    #     Returns:
    #         list: Measurement values from all getter channels at this level
    #     """
    #     measurements = []
        
    #     # Group getter channels by device
    #     # device_channels = {}
        
    #     # # Read from each getter channel configured for this level
    #     # for getter_index in range(self.level_getter_counts[level_index]):
    #     #     getter_channel = self.level_getters[level_index][getter_index]
    #     #     print("getter_channel", getter_channel)
            
    #     #     # Extract device name and variable name
    #     #     device_name = self.extract_device_from_channel(getter_channel)
    #     #     variable = self.extract_variable_from_channel(getter_channel)
    #     #     print("device_name", device_name)
    #     #     print("variable", variable)
            
    #     #     # Group channels by device
    #     #     if device_name not in device_channels:
    #     #         device_channels[device_name] = []
    #     #     device_channels[device_name].append(variable)
            
    #     #     print("Device channels grouped:", device_channels)
    #     device_channels = self.Group_device_channels(level_index)
            
    #         # Check if this is an artificial/calculated channel
    #         if variable in self.main_window.equations:
    #             # measurements.append(self.main_window.read_artificial_channel(variable))
    #             measurements.append(0)
    #         else:
    #             # Read directly from hardware channel
    #             # measurements.append(self.main_window.read_info(getter_channel))
    #             measurements.append(0)

        
    #     return measurements

    def group_reading_device_channels(self, level_index):
        device_channels = {}
        
        # Read from each getter channel configured for this level
        for getter_index in range(self.level_getter_counts[level_index]):
            getter_channel = self.level_getters[level_index][getter_index]
            print("getter_channel", getter_channel)
            
            # Extract device name and variable name
            device_name, variable = self.extract_device_from_channel(getter_channel)
            print("device_name", device_name)
            print("variable", variable)
            
            # Group channels by device
            if device_name not in device_channels:
                device_channels[device_name] = []
            device_channels[device_name].append(variable)
            
        print("Device channels grouped:", device_channels)
        return device_channels
        
    def multi_thread_read(self, device_channels):
        start_time = time.time()
        with ThreadPoolExecutor(max_workers=len(device_channels)) as executor:
            futures = [executor.submit(self.read_single_device_all_channels, device, channel_list) for device, channel_list in device_channels.items()]
            # Combine all dictionary results into a single dictionary
            combined_results = {}
            for future in futures:
                result_dict = future.result()
                combined_results.update(result_dict)
        end_time = time.time()
        print(f"Time taken for multi_thread_read: {end_time - start_time} seconds")
        return combined_results


    def read_single_device_all_channels(self, device, channel_list):
        result = {}
        start_time = time.time()
        for channel in channel_list:
            if channel in self.main_window.equations:
                result[f"{device}_{channel}"] = self.main_window.read_artificial_channel(channel)
            else:
                result[f"{device}_{channel}"] = self.main_window.read_info(f"{device}_{channel}")
        end_time = time.time()
        print(f"Time taken for {device}: {end_time - start_time} seconds")
        print("result", result)
        return result

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
        remaining_points = self.total_points - self.completed_points
        completed_percentage = round(self.completed_points / self.total_points * 100)
        remaining_seconds = remaining_points * avg_time_per_point
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
    
