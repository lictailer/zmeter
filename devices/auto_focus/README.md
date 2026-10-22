# Configurable autofocus

Driver ID: `auto_focus`. This coordinator uses registered devices through the
shared router. It owns no serial port or actuator connection. Its workbook
address must be blank. Connect actuators in their own panels first.

## First use and default experiment

1. Upload/commission/connect the separate
   [arduino_steppers](../arduino_steppers/README.md) device on COM6. Default Z
   setter/getter: `arduino_steppers/stepperA_angle`, native unit `deg`.
2. In **Z actuator**, choose any absolute device position setter and a getter
   reporting the same native coordinate/unit. Arduino angle or full-step
   channels, and other registered stages/piezos, use the same selectors. Speed,
   relative jogs and trigger channels are not Z position channels.
3. Leave conversion off for native coordinates, or enter the measured distance
   mapping below. Review limits, maximum command size, tolerance and search
   offsets in the selected Z unit. **Select Z / read position** validates the
   selection/readback but does not connect or move the actuator.
4. Default acquisition maximizes the mean of five reflection samples on
   `nidaq/AI0`. Galvos are `nidaq/AO0` and `nidaq/AO1`, held at their existing
   position unless **Set XY point** is explicitly checked.
5. Commission a very small bounded profile with **Move to best** unchecked.
   Inspect score versus Z, then enable it for normal focusing. Releasing Z or
   closing autofocus does not disconnect/home/zero its actuator.

Selectors follow ZMeter's catalog publications. Unavailable selected channels
are preserved rather than silently substituted. Manual Refresh is also available.

## Native position or calibrated distance

Conversion disabled: Z is the native channel value. Conversion enabled:

```text
distance = distance_reference + (native - native_reference) * distance_per_native
native_target = native_reference + (distance_target - distance_reference) / distance_per_native
```

Enter `um` or `mm`, a measured nonzero signed scale and reference values. The
scale defaults to zero and must be supplied before conversion can be enabled.
A negative factor reverses direction. References define a mathematical mapping;
they never zero/home hardware. No gearing or travel calibration is guessed.

Illustrative example only: if 360 degrees give 100 um of travel, the scale is
`100/360 = 0.277777778` um/degree. This is **not** the laboratory calibration.
With a step channel, enter distance per full step, not per degree. For mm, use
mm for both scale and distance reference.

Limits, search offsets, command size, tolerance, plots, `get_z()` and result
positions use the selected Z unit. Changing units/calibration does **not**
rescale existing numeric fields: review them before selecting Z. Release Z
before editing its settings. The full search interval is converted back to
native values and checked against global limits before acquisition/motion;
each routed write is checked again. The actuator enforces its own native limits.
Save the focus setup alongside experiment records: ordinary scan JSON does not
embed this calibration, and the `auto_focus_z` channel name alone does not encode
its selected unit.

Tolerance must cover native resolution times the absolute scale. The nominal
2048-full-step motor has 0.17578125-degree resolution; 0.1 degree covers half-step
rounding. For step channels use integer-compatible tolerance (e.g. 0.5 step).
Converted tolerance must cover the corresponding distance rounding. Software
counters cannot detect missed steps, drift or backlash; calibrate real mechanics.

## Acquisition and search

Selectable sources: scalar point (reflection/photocurrent/other input), routed
XY raster (galvos or analog-driven XY piezos), or OpenCV camera. Metrics: mean,
image gradient energy and image Laplacian variance, with maximize/minimize.
For single-point acquisition, **Average input signal (at each Z)** is the
arithmetic mean of `Input readings per point` samples at that Z, separated by
`Between input readings`. For 5 readings: `score = (v1 + v2 + v3 + v4 + v5) / 5`.
It keeps the input channel's units and is not an image-sharpness metric. With one
reading the score is that reading. Image-only metrics are disabled in point mode.
Single-point maximum reflection is the requested experimental focus proxy, not
a universal focus criterion. Saturation, interference, illumination and texture
can mislead it. Compare with known focus. Image scoring also depends on noise,
texture/exposure; see [Pertuz et al.](https://doi.org/10.1016/j.patcog.2012.11.011).

Raster validates the entire rectangle, samples serpentine rows and returns to
its chosen center after a successful image. Stop/error issues no cleanup XY move.
No new DAQ task/connection is created. Camera opens the explicitly selected
OpenCV index for the run, validates a frame/ROI before Z motion and releases it
afterward. ROI is `x,y,width,height`, all zeros for full frame. Vendor SDK cameras
need an adapter; a driver call may block until its own timeout.

**Z optimization method** selects the search independently of acquisition/metric:

- **Adaptive peak search + bounded Brent** (new default): measure at the initial
  Z and one probe on either side, within the validated search interval. If the
  best probe improves on the center, follow that direction, doubling the probe
  distance until the score stops improving or the interval ends. Once a peak is
  bracketed, SciPy's bounded Brent minimizer optimizes the signed score, combining
  parabolic interpolation with golden-section steps. It selects each next Z from
  the measurements, not from a predetermined grid. If the initial probes tie,
  bounded Brent searches the full interval; three equal readings do not establish
  a flat curve. No Gaussian shape or analytic derivative is required.
- **Coarse grid + refinement**: retains the previous search unchanged: 9 coarse
  points, 5 points per refinement, 2 refinement rounds by default. Keep this for
  inspecting the wider curve or comparing search methods.
- **Full Z sweep → measured maximum / minimum**: measure evenly spaced positions
  from the lower to upper Z bound (both included), plot each score live and select
  the best measured Z. No adaptive search or refinement is performed.
- **Full Z sweep → Gaussian fit peak / dip**: perform the same full sweep, then
  fit `signal(Z) = baseline + amplitude * exp(-0.5 * ((Z - center) / sigma)**2)`
  with SciPy's bounded nonlinear least-squares
  [curve_fit](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.curve_fit.html).
  Maximize fits a positive peak; Minimize fits a negative dip. The selected Z is
  the fitted center, which may lie between measured positions. Blue shows measured
  points, orange shows the fitted curve and a dashed line marks its center. Status
  reports measured best Z/score separately from fitted center, sigma and R².

All methods read the initial Z and validate the entire interval before acquisition
or motion. **Search bounds coordinates** selects relative or absolute coordinates.
In relative mode, **Search lower bound (relative to starting Z)** and **Search upper bound
(relative to starting Z)** define the interval as `starting_Z + lower_bound`
through `starting_Z + upper_bound`. The starting Z is read once per run. These
are not XY image boundaries. Adaptive search chooses positions within the interval;
full sweeps explicitly travel lower-to-upper. Relative JSON keys remain
`start_offset` and `stop_offset`. Absolute mode uses `absolute_lower` and
`absolute_upper` directly, without adding the starting Z. Switching coordinate
modes does not translate the numeric entries; review the newly shown values.

For the requested scalar sweep, choose point acquisition, average input signal,
Maximize, a **Full Z sweep** method, **Absolute Z coordinates**, endpoints -100
and +100 and (for example) 41 Z positions. This measures -100, -95, ..., +100 in
the selected Z unit, averaging input readings at each position. These example
endpoints are **not** a declaration of safe travel: the actuator, global limits
and existing autofocus Z limits must all permit the reviewed range. No limits
are expanded automatically. The sweep count defaults to 41, configurable 3–1001;
Gaussian mode requires at least 7 distinct acknowledged positions.

Gaussian acceptance is explicit: minimum R² defaults to 0.8 and is adjustable in
the panel; parameters/covariance must be finite, the center must be interior,
and sigma must be resolved between half the smallest measured spacing and the
full sweep width (solutions at these width bounds are rejected). Duplicate
acknowledged positions are averaged for the fit. Both axes are normalized before
fitting to accommodate distance units and signal scales. A fit assumes a Gaussian
with constant baseline, not arbitrary/multipeaked data; high R² alone does not
prove physical focus. `fit_failed` records the reason and leaves the last completed
Z, without a final fitted-position move or a silent measured-maximum fallback.

Adaptive defaults:
initial probe step 1 selected Z unit, requested precision 0.2 unit, maximum 40
focus evaluations. Effective precision is `max(requested_precision, 2 * Z_tolerance)`
to avoid resolving below the position-confirmation uncertainty. The initial step
is at least that precision; **review these values when changing units/calibration**.
These are numerical defaults, not calibrated mechanical safety limits. Only the
chosen method's controls are shown. Settling remains 0.1 s, with 5 reads per scalar
point by default. The budget counts acquired focus scores (each may be an entire
XY raster), not pixels, input averages or segmented motor commands. Revisited
targets reuse scores; adaptive search also reuses identical acknowledged positions
from quantized actuators. Measurements are cached only within a single run.

Adaptive search is a **local optimizer** for a reasonably single-peaked,
repeatable curve. It can miss other peaks or a narrow peak in a flat region;
neither it nor the grid guarantees the global optimum of an arbitrary function.
Noise, exposure changes, motor backlash and missed steps still affect focus.
Smaller requested precision is not a guarantee of optical accuracy. Reference:
[SciPy scalar optimization](https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.minimize_scalar.html).

`flat_signal`, `boundary_peak`, `fit_failed` and adaptive `max_evaluations` return normally
without a final best move; inspect them before unattended measurements. A complete
interior selection can be applied when **Move to selected focus Z** is checked.
The selected position is the measured best for all methods except Gaussian mode,
which uses the accepted fitted center. Its readback is confirmed, but no extra
focus acquisition is performed there. Exceptions propagate
to scan error handling. No implicit grid fallback or search-range expansion is added.

Stop/error retains completed samples and the last completed position, with no
automatic return/home/zero. Autofocus Stop waits for any in-flight routed command
to return; the actuator's own Stop controls its internal segmentation. Termination
waits instead of destroying a live worker. Settings freeze during active work.
Requests are protected individually, not exclusively for an entire experiment:
do not manually change shared channels while autofocus/scans use them.

## Temperature -> autofocus -> measurement scan

| Level | Setter | Points |
| --- | --- | --- |
| 2, slowest | Stable temperature setter or appropriate settling wait | Temperatures |
| 1 | `auto_focus_focus` | One explicit value, e.g. `[1]` |
| 0, fastest | Measurement sweep | Measurement targets |

The existing engine waits for each level before entering its child. Autofocus
therefore completes once per temperature before the inner sweep. Do not place
temperature and autofocus on the same level: different devices can run in parallel.

Scan channels: `focus` accepts any finite numeric trigger, including 0; value
and sign are ignored. NaN retains existing scan skip semantics. `z` reads the
selected native/distance coordinate. `focus_score` returns the recorded best
score for a completed run or latest completed sample after interruption, not a
fresh reflection read. Scan engine and scan JSON formats are unchanged.
Gaussian fitting does not replace `focus_score` with a prediction: it still returns
the measured best score. The `focus` setter's numeric return is the selected Z
(fitted center after a successful Gaussian fit, measured best otherwise); `z`
reports the actual current coordinate, including actuator quantization.

### Relating focus runs to measurement data

Add the read channel **`auto_focus_run_key`** to the innermost measurement level
(alongside `auto_position_run_key` when using both coordinators). It returns the
latest autofocus attempt's start time as a numeric **local-computer-time**
`YYYYMMDDhhmmss`, for example `20261022181250`. Repeated reads do not create a
new key or run autofocus. Before the first attempt it returns NaN. An attempt
that stops/fails keeps its key; a key alone does not mean focus succeeded.

With automatic saving enabled, search the results directory for
`autofocus-20261022181250-*`. The same integer is stored as `run_key` in its
`run.json` and manual result export. Enable **Saving** if you need the linked
data/visuals: a key is still generated when saving is off, but no folder is made.
Keys are local to each operation, not a shared outer-scan ID. An inner sweep
records the same key until the next autofocus attempt. The 14-digit integer is
exact in the scan's float64 arrays; format it without decimals/scientific notation
when searching. Runs starting in the same local second can share this time label;
the existing UTC microsecond/UUID suffix still keeps their folders distinct.

## Settings, migration and developer guide

### Optional automatic data and visual saving

In **Saving**, check **Automatically save autofocus data and curve PNG for every
run** and choose a results directory. This is off by default. Each enabled run
reserves a unique timestamp/UUID subfolder before acquisition/motion, then saves
`run.json` with actual settings, completed samples, outcome/error and result, plus
`focus_curve.png` (including a Gaussian curve when applicable). Stopped/failed
runs save completed samples and their curve; no automatic return move is added.
If **Also save every acquired image** is checked, each image is saved as raw
non-pickled `.npy` plus a `.png`. Otherwise only the score data/curve are saved.
Image saving can be large and adds acquisition latency. Single-point runs do not
produce image frames. Individual file updates are atomic and existing run folders
are not overwritten. An invalid/unwritable directory fails before motion; a later
saving error is reported without pretending a completed move was undone.

The added `output` settings group is part of schema 2. Older schema-2 setups
without it load with automatic saving disabled. Explicit manual setup/result
exports remain available independently. Saving uses `core/measurement_records.py`
with a serialized, headless Matplotlib renderer, never Qt widget access in workers.
`run_key` is additive result metadata, not a new settings/schema requirement.
Existing settings and saved files need no migration; older runs have no key and
are not renamed or rewritten.

Explicit Save/Load setup uses schema-version-2 JSON with channels, native units,
calibration, acquisition/search and limits. Result/partial export also uses
version 2, records actual run settings/completed samples and omits full images.
New files explicitly record `search.method`, bounds coordinate mode, absolute
endpoints, sweep count, Gaussian acceptance threshold and adaptive parameters. Earlier
schema-2 files without `method` load as **grid**, preserving their previous motion
plan; choose adaptive explicitly and save if desired. Loading never silently
switches a saved experiment to the new default. These added search keys require
the updated application; older application builds cannot read new setup files.
Older schema-2 setups without bounds mode retain relative bounds. Result exports
add `selected_position`, `gaussian_fit` (baseline/amplitude/center/sigma/R²) and
`fit_error`, while `best_position` and `best_score` remain measured values. Images
remain omitted; completed scalar samples are exported, including partial sweeps.
Writes use QSaveFile; loading never connects or moves. No automatic MAT/PPT
output is added; run-bundle saving is opt-in as described above. Version-1 setups are rejected with a migration message and left
untouched: re-enter settings, select standalone actuator channels, review units
and calibration, then save a new file. No automatic port transfer is attempted.

`autofocus_engine.py`: pure frozen settings, metrics, search. `autofocus_hardware.py`:
RouterIO, bounded routed Z, point/raster/camera sources. Add actuators as normal
registered devices, not autofocus-specific hardware branches. Source factories and
metrics provide measurement extension points. `autofocus_logic.py` owns worker,
scan and lifecycle coordination; `autofocus_main.py` owns UI and explicit files.
No production autofocus import depends on the Arduino or auto-position driver.
Shared channel references/router validation and selectors now live in
`core/measurement_io.py` and `core/measurement_widgets.py`; existing autofocus
imports of these names remain valid. Their routing/limit behavior is unchanged.

Old Xuguo code, original supplied sketch and superseded single-motor firmware
are in [the archive](../../archive/legacy-autofocus/README.md).

## Validation

```text
python -B -m unittest discover -s devices/auto_focus/tests -p 'test_*.py' -v
python -B -m unittest discover -s devices/arduino_steppers/tests -p 'test_*.py' -v
```

Coverage: adaptive/grid and both full sweeps, off-grid Gaussian peaks/dips,
poor/numerically failed fits, absolute/relative bounds, fit/measurement export
distinction, both travel directions, initial peak, boundary/flat
signals, budget exhaustion, small synthetic image noise, quantized positions,
legacy method migration, signed/offset conversion, native limits before motion,
settings round trips, partial export, cancellation/teardown, responsiveness,
construction without connections, and nested scan ordering. See the standalone
device guide for the **User-executed hardware test**. The agent has not performed
board upload, physical mechanics tests or native Windows PowerPoint validation.

**User-executed hardware test — new sweep methods (not performed by the agent):**

1. Use a small, previously reviewed permitted Z range, correct units, known
   actuator position and stable input. Do not expand mechanical limits simply
   to reproduce the -100/+100 example. Save the setup explicitly.
2. Select point acquisition, average input signal, Maximize and full sweep /
   measured maximum. Uncheck the final focus move. Run and verify the endpoints,
   plotted Z coordinates and signal against an independent input readout.
3. Select Gaussian sweep, review the point count and minimum R², and repeat.
   Inspect the raw curve and fit, center/width and any fit failure message.
   Export the result and check measured values versus fitted parameters.
4. After reviewing the result and travel path, enable the final focus move if
   wanted; independently verify the achieved focus/position. Test Stop on a
   reviewed small-range sweep: no automatic return/home move should occur.
