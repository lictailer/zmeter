#!/usr/bin/env python3
import time
import sys

import numpy as np
import matplotlib.pyplot as plt
import serial

from nidaq_hardware import NIDAQHardWare
import cv2
import os

#
# ─── CONFIG ────────────────────────────────────────────────────────────────────
#
COM_PORT      = "COM7"      # e.g. "COM3" or "/dev/ttyUSB0"
MOTOR_RPM     = 7.0         # your stepperC speed (RPM)
INITIAL_RANGE = 1000.0      # initial search span (deg)
THRESHOLD     = 50.0        # stop when span < this (deg)

# Galvo‑scan parameters
X_CENTER, Y_CENTER = 0.483, 0.77
X_RANGE,  Y_RANGE  = 0.1, 0.1
X_PTS,    Y_PTS    = 51, 51
#
# ────────────────────────────────────────────────────────────────────────────────
#

class AutofocusSystem:
    def __init__(self, motor_rpm, daq,ser,
                 galvo_x="/Dev1/AO0", galvo_y="/Dev1/AO1",
                 pd_in="/Dev1/AI0"):
        #self.ser = serial.Serial(com_port, 115200, timeout=1)
        # self.ser.close()
        self.ser=ser
        time.sleep(2)
        self.current_angle = 0.0
        self.motor_rpm = motor_rpm

        self.daq = daq
        self.daq.set_up_single_ao_task(galvo_x)
        self.daq.set_up_single_ao_task(galvo_y)
        self.daq.set_up_single_ai_task(pd_in)
        self.ao_x, self.ao_y, self.ai = galvo_x, galvo_y, pd_in

    def move_focus(self, angle: float):
        delta = angle - self.current_angle
        self.ser.write(f"stepperA {delta}\n".encode())
        t_move = abs(delta)/360.0 * (60.0/self.motor_rpm)
        time.sleep(t_move + 0.2)
        self.current_angle = angle

    def measure_map(self) -> np.ndarray:
        xs = np.linspace(X_CENTER - X_RANGE/2,  #### CONSIDER DEVIDING RANGE BY 2
                         X_CENTER + X_RANGE/2, X_PTS)
        ys = np.linspace(Y_CENTER - Y_RANGE/2,
                         Y_CENTER + Y_RANGE/2, Y_PTS)
        M = np.zeros((len(xs), len(ys)))
        for i, xv in enumerate(xs):
            self.daq.write_single_ao_task(self.ao_x, float(xv))
            for j, yv in enumerate(ys):
                self.daq.write_single_ao_task(self.ao_y, float(yv))
                M[i, j] = self.daq.read_single_ai_task(self.ai)
        return M

    @staticmethod
    def gradient_metric(M: np.ndarray) -> float:
        gx = cv2.Sobel(M, cv2.CV_64F, 1, 0, ksize=3)
        gy = cv2.Sobel(M, cv2.CV_64F, 0, 1, ksize=3)
        return float(np.sum(gx*gx + gy*gy))


def iterative_focus_search(af: AutofocusSystem,
                           init_center=0.0,
                           span=INITIAL_RANGE,
                           thresh=THRESHOLD,
                           save_dir: str = None,
                           run_idx: int = None): #center and span is the stepper steps/angle
    center = init_center
    history_centers = []
    history_metrics = []
    histroy_xymaps=[]

    iteration = 0

    while span > thresh:
        angles = [center - span/2, center, center + span/2]
        gvals = []
        M_vals= []
        print(f"\nScanning ±{span/2:.1f}° around {center:.1f}°")

        for ang in angles:
            af.move_focus(ang)

            # acquire and display map
            M = af.measure_map()

            # metric
            g = af.gradient_metric(M)
            print(f"  {ang:.1f}° → ∇max = {g:.4g}")
            gvals.append(g)
            M_vals.append(M)

        # pick best and narrow span
        best = int(np.argmax(gvals))
        center = angles[best]
        span /= 2.0

        # update history
        history_centers.append(center)
        history_metrics.append(gvals[best])
        histroy_xymaps.append(M_vals[best])
        iteration += 1

        # save metric‐history plot
        if save_dir and run_idx is not None:
            # interactive plots: map + metric
            fig = plt.figure(figsize=(8, 8))

            ax_map = fig.add_subplot(2, 1, 1)
            im = ax_map.imshow(histroy_xymaps[-1],
                            origin='lower',
                            extent=[X_CENTER-X_RANGE/2, X_CENTER+X_RANGE/2,
                                    Y_CENTER-Y_RANGE/2, Y_CENTER+Y_RANGE/2],
                            aspect='auto')
            ax_map.set_title("Live Reflected Map")
            ax_map.set_xlabel("Galvo X (V)")
            ax_map.set_ylabel("Galvo Y (V)")
            cbar = fig.colorbar(im, ax=ax_map)
            cbar.set_label("Photodiode Signal")
            im.set_clim(np.min(histroy_xymaps[-1]), np.max(histroy_xymaps[-1]))

            ax_metric = fig.add_subplot(2, 1, 2)
            ax_metric.plot(history_centers, history_metrics, 'o-')
            ax_metric.set_title("Autofocus Gradient Metric")
            ax_metric.set_xlabel("angle")
            ax_metric.set_ylabel("Max Gradient")
            ax_metric.grid(True)

            fname = f"{run_idx:02d}_{iteration:02d}.png"
            fig.savefig(os.path.join(save_dir, fname))

    return center, history_centers, history_metrics, histroy_xymaps


def main():
    daq= NIDAQHardWare()
    af = AutofocusSystem(COM_PORT, MOTOR_RPM,daq)
    print("Starting autofocus search…")
    best_angle, centers, metrics, xy_maps = iterative_focus_search(af)
    focused_map=xy_maps[-1]
    # Move to final best focus angle
    print(f"\nMoving to final focus angle: {best_angle:.2f}°")
    af.move_focus(best_angle)
    print(f"✔ Final focus set at {best_angle:.2f}°")

if __name__ == "__main__":
    main()
