---
name: zmeter-shift-mapping
description: Make zmeter Shift Compensation mapping CSVs (source value, amount to add to the target) from alignment or drift analysis files such as notebooks, shift tables or NumPy arrays; one CSV per source-to-target pair.
---

# zmeter shift mapping

zmeter's Shift Compensation window cancels a reproducible shift that one
channel (the *source*, e.g. a waveplate angle `k10cr1_0_angle`) causes on
another (the *target*, e.g. a galvo voltage `ni6423_AO0`). It needs one
two-column CSV per source → target pair. This skill turns the user's
analysis results into those files.

Read `references/csv_format.md` before writing anything. It defines the
columns, units and the sign convention, with a worked example.

## Rules

- The analysis folder is read-only. Never modify, move or overwrite raw data
  or the user's notebooks. Write the CSVs to a new folder the user names, or
  to `<analysis folder>/outputs/shift_compensation/` if they agree.
- Do not touch lab hardware or zmeter itself. This skill only reads and
  writes files.
- Ask instead of guessing when the sign, units or the source column are not
  clear from the files.

## Steps

1. **Ask for the inputs** if the user has not given them:
   - the analysis files (folder, notebook, CSV table, `.npy`/`.npz`);
   - the source channel as zmeter names it, and its readback units
     (degrees or radians for an angle);
   - the target channels as zmeter names them (e.g. `ni6423_AO0`,
     `ni6423_AO1`) and their units (V for AOs);
   - which table columns hold the source value and each target's shift.
2. **Find the shift data.** Read the notebook to see how the shift was
   measured and what each column means. Typical outputs are a table with an
   angle column and per-axis shifts in pixels and in volts (e.g.
   `dx_px, dy_px, dx_V, dy_V`). Prefer the column already in the target's
   units. If only pixels exist, ask for the volts-per-pixel step of that
   scan.
3. **Decide the sign.** Column 2 of a mapping CSV is the amount to *add* to
   the target command so the beam stays on the same sample spot. Work out
   from the notebook whether its numbers are the shift *seen* in the data
   (feature appears at `p + d`: add `+d`) or the shift *applied to align* an
   image (`skimage.registration.phase_cross_correlation` and
   `scipy.ndimage.shift` style: the table holds `-d`, so add `-1 ×` the
   column). State which one you found and why.
4. **Convert other formats to a table.** For `.npy`/`.npz` or values that
   only exist in a notebook, load them with numpy/pandas in a separate
   script of your own and save a plain CSV with a header row next to the
   outputs (not into the raw data). Then use the helper below.
5. **Write the CSVs** with the helper, one `--map` per target:

   ```bash
   python scripts/write_mapping_csv.py \
     --table 0066_reflection_shift_vs_QWP.csv \
     --source-column angle --source-name k10cr1_0_angle \
     --map dx_V:qwp_to_ni6423_AO0.csv:-1:ni6423_AO0 \
     --map dy_V:qwp_to_ni6423_AO1.csv:-1:ni6423_AO1 \
     --plot shift_mapping_check.png
   ```

   `FACTOR` multiplies the column: `-1` flips the sign, `-0.001` flips it
   and converts mV to V. Name files `<source>_to_<target>.csv` so the user
   can tell them apart in the window.
6. **Check the result.** Run `--check` on the written files and look at the
   plot: the curve should be smooth, about one period per source turn for a
   waveplate, with the peak-to-peak the user expects (a few mV for the QWP
   walk). Report the summary lines.
7. **Tell the user how to use them**: in zmeter open *Shift compensation*,
   add one mapping per CSV, choose source set/read and target set/read,
   fit (cosine with period 360 for an angle in degrees, or a polynomial),
   check the fit plot, then activate. Mention that only differences of the
   fit are used, so an overall offset in column 2 does not matter.

## When the shift is not one-to-one

The window fits y = f(source) for one source per mapping. If the shift
depends on two channels (e.g. angle and temperature), say so and suggest one
mapping per source taken around the working point; corrections from several
sources onto one target add up in zmeter.
