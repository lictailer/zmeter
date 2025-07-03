#!/usr/bin/env python3
import numpy as np
from pathlib import Path
from scipy.io import loadmat, savemat
from scipy.ndimage import shift as ndi_shift
from skimage.registration import phase_cross_correlation
import matplotlib.pyplot as plt
from nidaq_hardware import NIDAQHardWare

# ─── USER PARAMETERS ───────────────────────────────────────────────────────────
GALVO_X    = '/Dev1/AO0'    # DAQ analog‑out channel for X
GALVO_Y    = '/Dev1/AO1'    # DAQ analog‑out channel for Y
PD_IN      = '/Dev1/AI0'    # DAQ analog‑in channel for reflection

# Scan grid parameters (AO volts)
X_CENTER   = 0.483          # initial center voltage for X scan
Y_CENTER   = 0.770          # initial center voltage for Y scan
X_RANGE    = 0.10           # half‑scan width in X
Y_RANGE    = 0.10           # half‑scan width in Y
X_PTS      = 51             # number of X points in scan
Y_PTS      = 51             # number of Y points in scan

# Point of interest (not necessarily center)
X0         = 0.48           # user‑defined target voltage X
Y0         = 0.80           # user‑defined target voltage Y

# Other settings
RESULTS_DIR = 'position_dataa'  # folder for .mat and .png output
UPSAMPLE    = 10               # subpixel accuracy factor in registration
# ────────────────────────────────────────────────────────────────────────────────

class AutoPositionSystem:
    def __init__(self, daq,
                 galvo_x="/Dev1/AO0", galvo_y="/Dev1/AO1",
                 pd_in="/Dev1/AI0"):
        
        self.daq = daq
        self.daq.set_up_single_ao_task(GALVO_X)
        self.daq.set_up_single_ao_task(GALVO_Y)
        self.daq.set_up_single_ai_task(PD_IN)
        self.ao_x, self.ao_y, self.ai = GALVO_X, GALVO_Y, PD_IN

    def measure_map(self, x_center, y_center):
        xs = np.linspace(x_center - X_RANGE/2, x_center + X_RANGE/2, X_PTS) #### CONSIDER DEVIDING RANGE BY 2
        ys = np.linspace(y_center - Y_RANGE/2, y_center + Y_RANGE/2, Y_PTS)
        M = np.zeros((Y_PTS, X_PTS))
        for i, xv in enumerate(xs):
            self.daq.write_single_ao_task(self.ao_x, float(xv))
            for j, yv in enumerate(ys):
                self.daq.write_single_ao_task(self.ao_y, float(yv))
                M[j, i] = self.daq.read_single_ai_task(self.ai)
        return M

    def compute_shift(self, prev_map: np.ndarray, new_map: np.ndarray):
        """
        Estimate pixel shift between prev_map and new_map via
        phase correlation, convert to AO volts, and invert sign.
        Returns (dx_volts, dy_volts).
        """
        (dy_pix, dx_pix), error, _ = phase_cross_correlation(
            prev_map,
            new_map,
            upsample_factor=UPSAMPLE
        )
        # pixel → volts conversion
        volt_per_px_x = (2 * X_RANGE/2) / (X_PTS - 1)
        vol_per_px_y = (2 * Y_RANGE/2) / (Y_PTS - 1)
        # invert: if image moved +dx, galvo must move -dx volts
        return -dx_pix * volt_per_px_x, -dy_pix * vol_per_px_y


def auto_positon(ap: AutoPositionSystem, save_dir: str = None):
    out = Path(save_dir)
    out.mkdir(parents=True, exist_ok=True)

        # look for existing scans
    mats = sorted(out.glob('*.mat'), key=lambda p: int(p.stem))
    if not mats:
        # first run: use user parameters
        x_ctr, y_ctr = X_CENTER, Y_CENTER
        x0, y0 = X0, Y0
        shift_x, shift_y = 0.0, 0.0
        run_idx = 1
        AI0_map = ap.measure_map(x_ctr, y_ctr)
    else:
        # subsequent: load last scan and apply previous shifts
        last = loadmat(str(mats[-1]))
        prev_map = last['AI0_map']
        x_ctr = last['x_center'].item() + last['x_shift'].item()
        y_ctr = last['y_center'].item() + last['y_shift'].item()
        x0    = last['x0'].item()      + last['x_shift'].item()
        y0    = last['y0'].item()      + last['y_shift'].item()
        run_idx = int(mats[-1].stem) + 1
        # acquire map at updated center
        AI0_map = ap.measure_map(x_ctr, y_ctr)
        # compute shift to align with previous
        print("prev map: ", prev_map)
        print("prev map: ", AI0_map)
        shift_x, shift_y = ap.compute_shift(prev_map, AI0_map)
        # update POI by that shift only
        x0    += shift_x
        y0    += shift_y

    # put the laser back at the oint of interest
    ap.daq.write_single_ao_task(ap.ao_x, float(x0))
    ap.daq.write_single_ao_task(ap.ao_y, float(y0))
    # save results
    savemat(str(out / f'{run_idx}.mat'), {
        'x_center': x_ctr,
        'y_center': y_ctr,
        'x0':       x0,
        'y0':       y0,
        'x_range':  X_RANGE,
        'y_range':  Y_RANGE,
        'x_pts':    X_PTS,
        'y_pts':    Y_PTS,
        'AI0_map':  AI0_map,
        'x_shift':  shift_x,
        'y_shift':  shift_y
    })

    print(f"Run {run_idx} → center=({x_ctr:.6f},{y_ctr:.6f}),"
          f" x0,y0=({x0:.6f},{y0:.6f}), shift=({shift_x:.4f},{shift_y:.4f})")

    # plot map with POI
    xs = np.linspace(x_ctr - X_RANGE/2, x_ctr + X_RANGE/2, X_PTS)
    ys = np.linspace(y_ctr - Y_RANGE/2, y_ctr + Y_RANGE/2, Y_PTS)
    fig, ax = plt.subplots()
    im = ax.imshow(AI0_map, origin='lower', extent=[xs[0], xs[-1], ys[0], ys[-1]], aspect='auto')
    ax.plot(x0, y0, 'ro', markersize=8, markeredgecolor='k')
    ax.set_xlabel('Galvo X (V)')
    ax.set_ylabel('Galvo Y (V)')
    ax.set_title(f'Run {run_idx}: POI at ({x0:.3f},{y0:.3f})')
    fig.colorbar(im, ax=ax, label='AI0 (V)')
    path = out / f'{run_idx}.png'
    fig.savefig(str(path), dpi=150)
    print(f"Saved plot to {path}")
# ────────────────────────────────────────────────────────────────────────────────
def main():
    daq= NIDAQHardWare()
    ap = AutoPositionSystem(daq)
    print("Starting autopositioning…")
    auto_positon(ap,save_dir=RESULTS_DIR)
if __name__ == '__main__':
    main()
