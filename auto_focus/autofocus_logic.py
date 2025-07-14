#!/usr/bin/env python3
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import time

import numpy as np
import matplotlib.pyplot as plt
import serial

import cv2
import scipy.io as sio

class ANC_and_DAQ_xyz:
    '''
    xyz and scanning system class that combines a stepper motor for Z-axis control
    '''
    def __init__(self, daq, ANC):
        self.com_port = "COM 7" #this may  be used in this class but can be used in the stepper_and_galvo_xyz class
        # daq class variables
        self.daq = daq # I will keep this as input for the class to allow using the same instant used somewhere else
        self.ao_x = "/Dev1/AO0"
        self.ao_y = "/Dev1/AO1"
        self.ai = "/Dev1/AI0"

        #ANC class variables
        self.ANC = ANC # this is an instance of the ANC class that will be used

    def move_z(self, z: float):
        return 0
    def move_x(self, x: float):
        return 0
    def move_y(self, y: float):
        return 0
    def read_pd(self) -> float:
        """Read the photodiode value."""
        return self.daq.read_single_ai_task(self.ai)
    def measure_map(self,x_center,y_center,x_range,y_range,x_pts,y_pts) -> np.ndarray:   #
        return 0


class stepper_and_galvo_xyz:
    '''
    xyz and scanning system class that combines a stepper motor for Z-axis control
    '''
    def __init__(self, daq):
        # galvo class variables
        self.daq = daq # I will keep this as input for the class to allow using the same instant used somewhere else
        self.ao_x = "/Dev1/AO0"
        self.ao_y = "/Dev1/AO1"
        self.ai = "/Dev1/AI0"

        #arduino stepper class variables
        self.com_port = "COM 7"
        self.baud_rate = 115200
        self.motor_rpm = 7
        self.ser = None

    def connect_system(self): #it is just connect stepper for my case
        """Connect to the stepper motor via serial port."""
        self.ser = serial.Serial(self.com_port, self.baud_rate, timeout=1)
        time.sleep(2)  # Allow time for the serial connection to establish
    
    def disconnect_system(self):
        """Disconnect from the stepper motor."""
        if self.ser:
            self.ser.close()
            self.ser = None
    def move_z(self, z: float):
        """Move the stepper motor to a specified angle."""
        if self.ser:
            self.ser.write(f"stepperA {z}\n".encode())
            t_move = abs(z)/360.0 * (60.0/self.motor_rpm)
            time.sleep(t_move + 0.2)

    def move_x(self, x: float):
        """Move the galvo X axis to a specified position."""
        self.daq.write_single_ao_task(self.ao_x, float(x))
    def move_y(self, y: float):
        """Move the galvo Y axis to a specified position."""
        self.daq.write_single_ao_task(self.ao_y, float(y))

    def read_pd(self) -> float:
        """Read the photodiode value."""
        return self.daq.read_single_ai_task(self.ai)
    # Additional methods can be added here for further functionality

    def measure_map(self,x_center,y_center,x_range,y_range,x_pts,y_pts) -> np.ndarray:   #
        xs = np.linspace(x_center - x_range/2,
                         x_center + x_range/2, x_pts)
        ys = np.linspace(y_center - y_range/2,
                         y_center + y_range/2, y_pts)
        M = np.zeros((len(xs), len(ys)))
        for i, xv in enumerate(xs):
            self.move_x(float(xv))
            for j, yv in enumerate(ys):
                self.move_y(float(yv))
                M[i, j] = self.daq.read_single_ai_task(self.ai)
        return M

class autofocus_logic:
    def __init__(self, xyz_sys): # the input is an instance of the xyz system
        # in the main window, self.my_xyz_sys = autofocus(stepper_and_galvo_xyz(self.my_daq))
        self.xyz_sys = xyz_sys # this instance have it's default values no need to redifine motor rpm or com port for example

        #auto_focus parameters
        self.initial_z_step = 1200
        self.threshold_z_step = 10
        self.threshold_metric_step = None # maybe for some cases converge based on focus metric is better

        self.current_z = 0.0

        # measure map paraeters
        self.x_center, self.y_center = 0.483, 0.77
        self.x_range,  self.y_range  = 0.1, 0.1
        self.x_pts,    self.y_pts    = 51, 51

        #saving parameters
        self.save_dir = None  # Directory to save results, can be set later

    def measure_map(self) -> np.ndarray:   #
        M= None
        if self.xyz_sys:
            M = self.xyz_sys.measure_map(self.x_center, self.y_center,
                                    self.x_range, self.y_range,
                                    self.x_pts, self.y_pts)
        return M
    
    @staticmethod
    def focus_metric(M: np.ndarray) -> float:
        gx = cv2.Sobel(M, cv2.CV_64F, 1, 0, ksize=3)
        gy = cv2.Sobel(M, cv2.CV_64F, 0, 1, ksize=3)
        return float(np.sum(gx*gx + gy*gy))
    
    def get_run_idx(self): #this will give the right number to use based on what exist in the save driectory
        """Get the next run index based on existing files in the save directory."""
        if self.save_dir:
            os.makedirs(self.save_dir, exist_ok=True)
            run_idx = 1
            while os.path.exists(os.path.join(self.save_dir, f"{run_idx:02d}.mat")):
                run_idx += 1
        return run_idx
    
    def save_iteration(self,M,history_z_centers, history_metrics,iteration):
        """Save the current as png image"""
        if self.save_dir is None:
            print("Save directory not set. Skipping save.")
            return
        # interactive plots: map + metric
        fig = plt.figure(figsize=(8, 8))
        ax_map = fig.add_subplot(2, 1, 1)
        im = ax_map.imshow(M,
                        origin='lower',
                        extent=[self.x_center-self.x_range/2, self.x_center+self.x_range/2,
                                self.y_center-self.y_range/2, self.y_center+self.y_range/2],
                        aspect='auto')
        ax_map.set_title("Live Reflected Map")
        ax_map.set_xlabel("Galvo X (V)")
        ax_map.set_ylabel("Galvo Y (V)")
        cbar = fig.colorbar(im, ax=ax_map)
        cbar.set_label("Photodiode Signal")
        im.set_clim(np.min(M), np.max(M))

        ax_metric = fig.add_subplot(2, 1, 2)
        ax_metric.plot(history_z_centers, history_metrics, 'o-')
        ax_metric.set_title("Autofocus Gradient Metric")
        ax_metric.set_xlabel("angle")
        ax_metric.set_ylabel("Max Gradient")
        ax_metric.grid(True)
        
        run_idx = self.get_run_idx()  # Get the next run index
        fname = f"{run_idx:02d}_{iteration:02d}.png"
        fig.savefig(os.path.join(self.save_dir, fname))

    def save_run(self,histroy_xymaps, history_metrics):
        """Save the entire autofocus run's data to a file."""
        if self.save_dir is None:
            print("Save directory not set. Skipping save.")
            return
        # Save all history data to a text file
        run_idx = self.get_run_idx()  # Get the next run index
        mat_name = f"{run_idx:02d}.mat"
        mat_path = os.path.join(self.save_dir, mat_name)
        sio.savemat(mat_path, {"xy_maps": histroy_xymaps, "metrics": history_metrics})

        print(f"Run data saved to {mat_path}")

    def set_AutoFocus(self):
        """Perform autofocus by iteratively adjusting the stepper motor position."""
        #for data saving
        history_z_centers = []
        history_metrics = []
        histroy_xymaps=[]

        #for while loop initiaiotn
        iteration = 0
        center_z=0
        curr_z_step=self.initial_z_step 

        while curr_z_step>self.threshold_z_step:
            z_pos = [center_z - curr_z_step, center_z, center_z + curr_z_step]
            f_vals = [] # the values for the focus metric for each Z_position
            M_vals= []

            print(f"\nScanning ±{curr_z_step:.1f}° around {center_z:.1f}°")

            for z in z_pos:
                self.xyz_sys.move_z(z) # this is a relative motion if Z is 1000 it will move 1000 from the current position
                # acquire and display map
                M = self.measure_map()

                # metric
                f = self.focus_metric(M)
                print(f"  {z:.1f}° → focus metric = {f:.4g}")
                f_vals.append(f)
                M_vals.append(M)

                # pick best and narrow span
            best = int(np.argmax(f_vals))
            center_z = z_pos[best]
            curr_z_step /= 2.0

            # update history
            history_z_centers.append(center_z)
            history_metrics.append(f_vals[best])
            histroy_xymaps.append(M_vals[best])
            iteration += 1

            self.save_iteration(M_vals[best], history_z_centers, history_metrics, iteration)
        
        self.xyz_sys.move_z(center_z)  # Move to the best focus position
        self.save_run(histroy_xymaps, history_metrics)


if __name__ == "__main__":
    from nidaq.nidaq_hardware import NIDAQHardWare  # Ensure this module is available

    # Initialize hardware system
    my_daq = NIDAQHardWare()
    xyz = stepper_and_galvo_xyz(my_daq)
    '''
    class variables that can be set before connection:
    xyz.com_port = "COM 7"  # Serial port for stepper motor
    xyz.baud_rate = 115200  # Baud rate for serial communication
    xyz.motor_rpm = 7  # RPM for the stepper motor
    '''
    xyz.connect_system()
    '''
    other class parameters that better for the scanning system
    xyz.x_center, xyz.y_center = 0.483, 0.77  # Center coordinates for scanning
    xyz.x_range, xyz.y_range = 0.1, 0.1  # Range for scanning in X and Y
    xyz.x_pts, xyz.y_pts = 51, 51  # Number of points
    '''

    # Run autofocus logic
    autofocus = autofocus_logic(xyz)
    autofocus.save_dir = "./autofocus_results"  # optional path to save output

    print("🔍 Starting autofocus search...")
    autofocus.set_AutoFocus()
    print("✅ Autofocus complete.")