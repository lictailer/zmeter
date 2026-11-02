# Shift Compensation

Shift Compensation cancels a reproducible cross-talk between two scan
channels while a scan runs. The first use is a quarter-wave plate
(`k10cr1_0_angle`) whose rotation walks the beam on the sample, seen as a
shift of the galvo voltages (`ni6423_AO0`, `ni6423_AO1`). Nothing in the
code is specific to that case: any channel with a setter and a getter can be
a source or a target.

Code: `core/shift_compensation/` (fits, logic, set files, window) and
`core/channel_value_record.py`. Tests: `tests/test_shift_compensation_*.py`,
`tests/test_channel_value_record.py`, `tests/test_shift_mapping_skill.py`.

## Terms

- **Source**: the channel that is moved and causes the shift.
- **Target**: the channel that is corrected.
- **Mapping**: one CSV of (source value, amount to add to the target) and
  its fit f. Moving the source from x₁ to x₂ needs a target correction of
  f(x₂) − f(x₁). Only differences of f are used.

## Window

Main window → **Shift compensation**. The window is a stack of mapping
blocks with **Add mapping**, **Save set...**, **Load set...**, **Value record**
and a line listing the compensated channels currently published.

Each block has:

1. Name, **Load CSV...** and a summary of the points (hover for a preview).
2. Four channel menus: source set, source read, target set, target read. The
   menus list raw channels only (no `default_*`, no `compensated_*`).
3. Fit: **Cosine** `y = A cos(2πx/P + C) + D` with a **Period** box (360 for
   degrees, 6.2832 for radians) and **Free period** (fit P too, starting from
   the box), or **Polynomial** with **Order**. Then **Fit** and **Show plot**
   (points, fit, reference line and residuals).
4. **Reference source value** x_ref; empty means the first CSV source value.
   It moves a whole compensated scan by one constant and does not change
   alignment.
5. **Active** (enabled once a fit exists) and **Delete**.

An active block is read-only; deactivate it to edit. The whole window is
locked while a scan, queue item or catalog change runs. Activation,
deactivation, deleting an active mapping and loading a set republish the
scan catalog through the same path as Artificial Channel 2D, so they are
refused while scan work runs or while a queued item still uses a
`compensated_*` channel that would disappear.

Activation is refused when: there is no fit; a channel is not chosen or not
in the catalog; a channel is itself a `compensated_*` channel; source set
and target set are the same; the mapping would chain with another active
mapping (its target is another mapping's source or the reverse); or the same
source or target is read through a different read channel in another active
mapping. Raw channels stay available and scannable as before.

If a raw channel leaves the catalog (device removed or profile changed), its
active mappings are deactivated with a note in the block. Active mappings do
not block device removal themselves.

## Compensated scan channels

For every distinct source S and target T of the active mappings, the scan
channel menus get:

| Channel | Setter | Getter |
| --- | --- | --- |
| `compensated_source_<S>` | read S, read every coupled target, set S, then set each target to its old value + Σ [f(new) − f(old)] | S readback |
| `compensated_target_<T>` | get every coupled source (value record or fresh read, below), set T = requested + Σ [f(x_now) − f(x_ref)] | T readback, the physical value |

Several mappings with the same source all fire together; several sources
onto one target add up. The target setter does not read the target.

Example: requested 0.10 V, correction +0.03 V. The device goes to 0.13 V and
the getter records 0.13 V. Plot against the setter axis to see the
compensated (aligned) picture, against the getter for the physical one.

Every underlying write goes through `MainWindow.write_info`, so
`scan_range_limits.json` applies to the raw source and target. If the source
write is denied, the targets are left alone. A denied target write marks the
point skipped as usual and logs the mapping. The source is not rolled back.

In a scan point, plain writes run first (in parallel per device), then the
`compensated_source_*` group, then the `compensated_target_*` group; each
target channel has its own lock. Compensated getters are read after the
plain getters.

Participating devices: a compensated channel pauses its source and all
coupled target devices during the scan.

## Value record and readback cache

`MainWindow.channel_value_record` keeps the newest value of every channel
written or read through `write_info` / `read_info` (denied writes do not
count) and of the scan start and end setup snapshots. Values set from a
device's own panel are not seen. The **Value record** button shows it.

A compensated target setter reuses the recorded source reading unless the
source's set channel was written through the main window after that reading
(raw or compensated), or the reading predates scan start (every source is
marked stale when a scan starts; the start snapshot then counts as a fresh
reading). Inside a map at a fixed waveplate angle this means one angle read
per angle, not per pixel.

## Choosing a scan form

Single spot, source sweep:

- **Form A**: one setter `compensated_source_<S>`. Each step re-reads the
  targets, so their readback noise is added into the target every step and
  can drift over a long sweep.
- **Form B** (recommended for long sweeps): the raw source setter plus
  `compensated_target_<T>` setters held constant in the same level. Each
  step recomputes the target from the source; nothing accumulates.

Map against the source: source in the slowest level (raw or compensated),
`compensated_target_*` as the map axes. Each map lands on the same sample
area without post-alignment.

## Saving

**Save set...** writes all mappings to one JSON file; **Load set...**
replaces the window's mappings and re-activates the ones saved active when
they pass the checks. Nothing is restored automatically at startup.

Each scan output JSON gets a `shift_compensation` record with the scan name,
serial, time and every active mapping, and the scan log gets one line per
active mapping. Formats: [data_format.md](data_format.md).

## Making mapping CSVs

`skills/zmeter-shift-mapping/` is an agent skill that turns analysis
results into mapping CSVs, one per source → target pair, with the sign
convention "column 2 = amount to add to the target". See
[`skills/README.md`](../skills/README.md).

## Limits of the design

- No guard for source values outside the CSV range; polynomials are
  evaluated as fitted. Target scan range limits are the only backstop.
- `k10cr1` angles are not wrapped to 0-360. Cosine fits do not care; for a
  polynomial in angle, CSV and readback must use the same convention.
- The record misses moves made from device panels outside scans.
- The `nidaq` driver has no AO getter yet; use `ni6423` (AO read back through
  AI28-AI31) or another target with a real readback.

## User-executed bench checks

Agents never run these; they need the real K10CR1 and NI6423.

1. Load the QWP → AO0 and QWP → AO1 CSVs, fit cosine with period 360, check
   the plots and activate both. Check that the four `compensated_*` channels
   appear in the scan setter and getter menus.
2. Scheme 1, form B: one level with `k10cr1_0_angle` 0 to 360 in 30° steps
   and both `compensated_target_ni6423_AO*` held constant. The reflection
   should stay on one feature.
3. Scheme 2: a small map (for example 21 × 21) at 3 to 4 QWP angles with the
   compensated AO setters. The maps should overlay without post-alignment.
4. Check the output JSON's `shift_compensation` entry and the scan log lines.
5. Try a target value outside its scan range limit and check that the point
   is skipped and the log names the mapping.
