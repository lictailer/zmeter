# Reference-map auto-position

Driver ID `auto_position`, widget `position_main.AutoPositionMain`. It owns no
DAQ/stage/input connection and performs no instrument discovery on construction.
The profile address is blank and startup connection is disabled. Connect the
selected physical devices in their own panels first.

## Operator workflow

1. Choose a results directory. All reference and positioning runs create unique
   timestamp/UUID subfolders there; existing files/reference maps are not replaced.
2. In **Reference Map**, select numeric absolute X/Y setters and a numeric input
   getter. Defaults: `nidaq/AO0`, `nidaq/AO1`, `nidaq/AI0`. Any registered device
   channel can be selected, including a Keithley current getter. Coordinates are
   the setters' native units; enter the correct unit labels and map endpoints.
3. Set each map axis using the compact scan-settings row: **Start, End, Step,
   Midpoint, Range (span), Points**. Edit Start/End to update Midpoint/Range, or
   edit Midpoint/Range to update Start/End. Range is the full width:
   `Start = Midpoint - Range/2`, `End = Midpoint + Range/2`. Step is the pixel
   spacing, `(End - Start)/(Points - 1)`. Editing Step selects the nearest whole
   point count, then displays the actual resulting spacing, like the main scan
   editor. A step requiring points outside the existing 7–512 limit is rejected
   without changing endpoints/counts. Editing Points updates Step directly.
   Typed values update on Enter/focus loss, and spin arrows update immediately.
   X and Y are independent. Set settling time, input averaging and measurement
   point X/Y separately; editing the map center does not change the point.
   Defaults are configuration examples, not certified
   mechanical travel limits. Device/global limits remain enforced.
4. **Acquire new reference + go to point** performs a serpentine
   scan and saves raw data/PNG. On success it commands the selected point.
   This is the only acquisition button that intentionally returns to that point.
5. A point can also be picked by clicking the reference image. Clicking only
   fills the point fields: **Save edited point (no motion)** confirms
   it and writes a new reference copy without a new scan or movement.
6. In **Auto Position**, choose the registration technique and its parameters.
   **Auto-position** scans the same grid/channels, compares it with the fixed
   reference, validates the displacement/quality, commands the corrected point
   and saves the new map, point and comparison visuals.

**Load reference.json** restores a reference, geometry and point without motion.
It preserves an already chosen results directory; otherwise it proposes the
loaded file's directory. Review it before starting. Map geometry/channel changes
require a new matching reference. A setup JSON contains configuration, not the
reference image; loading a setup never silently replaces the existing reference.
Channel selectors follow catalog publications and preserve unavailable selected
channels rather than substituting another device. Manual Refresh is available.
The row is only an editor for the existing ascending endpoints and 7–512 points
per axis. Setup/reference schema 1 still stores endpoints and point counts, not
additional midpoint/range values; existing saved setups/references load unchanged.

## Translation techniques and parameters

- **Subpixel phase correlation** (default): scikit-image FFT registration with
  phase normalization and localized upsampled DFT refinement.
- **Subpixel intensity cross-correlation**: the same established DFT refinement
  without phase normalization; compare this option when phase normalization
  amplifies noise. These two methods use `upsample_factor` (default 20), a
  numerical sampling precision, not a physical accuracy guarantee.
- **Bounded normalized overlap correlation**: explicitly searches integer
  translations within the configured displacement limits, using zero-mean
  normalized correlation on non-wrapped overlapping pixels. A local parabola
  refines an interior peak. Its peak-margin control compares the best score with
  separated candidates outside the immediate 3-by-3 neighborhood. Searches above
  10,000 candidates are refused; reduce map resolution or displacement limits.

Source and method limitations:
[scikit-image registration API](https://scikit-image.org/docs/stable/api/skimage.registration.html),
[subpixel registration example](https://scikit-image.org/docs/stable/auto_examples/registration/plot_register_translation.html).

All methods support standardized intensity or gradient magnitude preprocessing,
optional Gaussian smoothing (sigma in pixels). FFT methods optionally use a Hann
window. Alignment is checked on processed, **non-wrapped** overlap using Pearson
correlation. Defaults: correlation >= 0.6, overlap >= 0.5, maximum native-coordinate
shift 0.02 per axis. Maximum shifts must be smaller than half their map spans.
The normalized method's separated-peak margin defaults to 0.01. These are visible,
editable acceptance settings, not proof that a reference is unique or invariant.

The image model is **translation only**. Rotation, magnification changes,
deformation, illumination changes, repeated patterns and featureless maps can
make registration unreliable. Gradient features can help with some intensity
changes; they do not solve arbitrary changes. A failed match raises a scan error
and does not command a final corrected point. There is no silent method fallback,
automatic window expansion or reference replacement.

## Coordinates and fixed-reference behavior

Images use `[row = Y, column = X]`; native coordinates increase with their stored
axes. Registration returns `(shift_Y, shift_X)` **applied to the new image** to
align it with the reference. The feature displacement is the opposite sign:

```text
native_dx = -image_alignment_shift_X * (X_max - X_min) / (X_pixels - 1)
native_dy = -image_alignment_shift_Y * (Y_max - Y_min) / (Y_pixels - 1)
new_point = ORIGINAL_reference_point + (native_dx, native_dy)
```

For example, a feature moving three columns toward larger X means the commanded
point moves three X pixel spacings toward larger X. The implementation does not
assume that galvo polarity equals physical sample polarity; it operates in the
measured output-coordinate map. Repeated runs compare to the same original
reference and original point, not to the last corrected point. Displacements are
not accumulated twice. Changing the reference is an explicit acquire/load/edit
operation. A corrected point outside the scanned rectangle is rejected.

## Scan use

Use separate nested levels, in this order from slowest to fastest:

| Level | Setter | Example values |
| --- | --- | --- |
| 3 | Stable temperature, if used | Experiment temperatures |
| 2 | `auto_focus_focus` | `[1]` |
| 1 | `auto_position_position` | `[1]` |
| 0 | Your measurement setter | Measurement sweep |

Each trigger finishes synchronously before the inner level begins. Do not place
dependent focus/position operations on one level: different devices on the same
level may execute concurrently. No scan-engine ordering/schema changes were made.
An inner measurement that explicitly writes these same X/Y channels will replace
the corrected point normally; leave them untouched if measuring at that point.

The numeric `position` setter accepts any finite numeric value (including 0);
its magnitude/sign are ignored. It returns 1 after successful positioning and
saving; failure propagates instead of reporting success. NaN retains the scan
engine's existing skip semantics. Getters `x`, `y`, `shift_x`, `shift_y` and
`correlation` describe the last successfully completed positioning run. X/Y are
**commanded coordinates**, not independent actuator position feedback. Underlying
device setters must implement their required move completion/settling behavior.

### Relating positioning runs to measurement data

Add **`auto_position_run_key`** and, if used, `auto_focus_run_key` as getters at
the innermost measurement level. Each measurement then records which positioning
and focus attempts preceded it, without changing scan order or scan JSON format.
`run_key` returns the latest positioning attempt's local-computer start time as
a numeric `YYYYMMDDhhmmss`, for example `20261022181250`. It stays fixed until the
next positioning attempt and returns NaN before the first. Acquiring/loading a
reference or saving an edited point does not replace the positioning key.

Find the associated folder using `auto-position-20261022181250-*`; its `run.json`
contains the same integer. Reference bundles also contain their own time label,
but these are not what the positioning getter reports. Failed/stopped attempts
retain their keys/data when a bundle could be created. Preflight/path failures
may prevent a folder from being created. A key is not proof of a successful move.
Keys use seconds, so same-second runs can share a label; the UTC microsecond/UUID
suffix keeps folders distinct. The key is exact in float64 scan data; display it
with zero decimals when searching. Existing folders are not renamed, settings and
reference formats are unchanged, and `run_key` is optional additive run metadata.

## Persistence, limits and lifecycle

Each reference bundle contains `reference.json` (schema 1, raw finite map,
geometry/channels/units, point and ID), `map.png` and `run.json`. Each positioning
bundle contains `run.json` (schema 1, configuration, reference ID/point, raw new
map, completed pixel count, registration/point and status), `map.png` and a
two-panel `comparison.png`. Failed/stopped runs retain completed data; unmeasured
pixels are JSON `null`. Individual writes are atomic. A `ready_to_move` record
precedes the final command; completion records whether both output commands
finished. The reference remains unchanged. PNGs mark the reference/corrected
point and display native X/Y axes. Saving errors are errors, not a successful
"done" message; an already completed move is never represented as undone.

Both map endpoints and final X/Y targets are checked against the router's current
global limits before either output command. Device-local limits remain in force.
X/Y commands are sequential, not atomic: if Y fails after X succeeds, the saved
last-command state records that partial outcome. Stop waits for the current
device call and prevents later commands; it does not issue a return/home/zero.
Closing/hiding the panel causes no output changes. Termination waits for workers
and does not disconnect physical devices. Only a genuinely active job blocks a
new job or reference release; there is no arbitrary "scan locked" state.

Requests are protected individually, not reserved for a whole scan. Do not
manually operate shared X/Y/input channels while autofocus/positioning/measurement
uses them. Use the devices' own physical interlocks and commissioned limits.

The previous direct-DAQ/PyQt5 prototype is preserved under
`archive/legacy-autofocus/auto_position/`. Its MAT files are not automatically
imported because axis/point/channel conventions were not reliable. Acquire a new
reference using the maintained coordinator. No files are deleted by migration.

## Validation and user bench procedure

Hardware-independent checks:

```text
python -B -m unittest discover -s devices/auto_position/tests -p 'test_*.py' -v
python -B -m unittest discover -s devices/auto_focus/tests -p 'test_*.py' -v
```

Coverage includes all three methods/signs/subpixel shifts, independent X/Y pixel
scales, changed brightness, invalid maps/limits, arbitrary routed inputs, fixed
reference reuse, save/load and no-motion point edits, partial saves, route/file
failures, cooperative shutdown, UI/catalog/profile construction and nested
focus -> position -> measurement ordering. Offscreen checks cover bidirectional
scan-row edits, independent axes/measurement point, Step/Points rounding and repeated
setup loading without endpoint drift. These are simulations/offscreen GUI
checks, not bench certification.

**User-executed hardware test (not performed by the agent):**

1. Independently review the selected output/input channels, native units, small
   safe map rectangle, motion/settling behavior and hardware/global limits.
2. Choose a disposable results directory; acquire a low-resolution reference
   and confirm the map orientation and point against known sample features.
3. Run auto-position without introducing drift. Inspect raw maps, correlation,
   overlap and near-zero displacement before using a nested scan.
4. Introduce a known small reviewed displacement yourself. Verify its sign,
   corrected point and physical optical location, then repeat without another
   displacement to check there is no double accumulation.
5. Review poor-match/Stop behavior on that small range, saved partial data,
   reconnect/load (no motion), application close and physical final state.
   Only after acceptance add the trigger as a separate scan level.
