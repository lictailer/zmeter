# Shift Compensation mapping CSV

One file per source → target pair. UTF-8 text, comma, semicolon or tab
separated. At most one header row (the first non-blank row); every other
non-blank row holds two finite numbers. Do not add comment lines: a second
text row is an error in zmeter's loader. At least two data rows; cosine fits
need 3 (4 with a free period), polynomials order + 1.

| Column | Meaning | Units |
| --- | --- | --- |
| 1 | Source value | Units of the source **readback** channel (e.g. degrees from `k10cr1_0_angle`) |
| 2 | Amount to **add** to the target command so the target stays on the same physical position when the source sits at this value | Units of the target **setter** (e.g. V for `ni6423_AO0`) |

The header the helper writes is `<source>,add_to_<target>`, for example
`k10cr1_0_angle,add_to_ni6423_AO0`.

## How zmeter uses it

zmeter fits column 2 against column 1 (cosine `A cos(2πx/P + C) + D` or a
polynomial) and only ever uses **differences** of the fit,
f(x₂) − f(x₁). An overall offset in column 2 therefore changes nothing; a
wrong sign doubles the shift instead of cancelling it.

- `compensated_source_<S>` moves the source and adds f(new) − f(old) to
  each coupled target.
- `compensated_target_<T>` writes requested + f(x_now) − f(x_ref), where
  x_ref defaults to the first source value of the CSV.

## Sign convention

If moving the source from x_ref to x makes a sample feature appear at
target value p + d(x) instead of p, the target must be commanded to
p + d(x) to look at the same feature. Column 2 is **+d(x)**.

Image registration tools report the shift that *aligns* the moved image
back onto the reference (`skimage.registration.phase_cross_correlation`
returns the shift to apply with `scipy.ndimage.shift`). That is −d(x), so
column 2 is **−1 ×** that table column.

## Worked example: Opticool CO2 alignment (2026-10-23)

Notebook `QWP_dep.ipynb` registers each reflection map (`sr860_0_R`) of
scan 0066 to the angle-averaged map and writes
`outputs/tables/0066_reflection_shift_vs_QWP.csv` with columns
`angle, dx_px, dy_px, dx_V, dy_V, quality_corr`. The `d*_V` columns are the
shifts applied to align, in volts (5 mV per pixel), and map x/y are
`nidaq_AO0`/`nidaq_AO1` (NI6423 `ni6423_AO0`/`AO1` on the new setup).

So:

- `qwp_to_ni6423_AO0.csv`: column 1 = `angle` (degrees), column 2 = −`dx_V`
- `qwp_to_ni6423_AO1.csv`: column 1 = `angle`, column 2 = −`dy_V`

```bash
python scripts/write_mapping_csv.py \
  --table 0066_reflection_shift_vs_QWP.csv \
  --source-column angle --source-name k10cr1_0_angle \
  --map dx_V:qwp_to_ni6423_AO0.csv:-1:ni6423_AO0 \
  --map dy_V:qwp_to_ni6423_AO1.csv:-1:ni6423_AO1
```

The 0066 ellipse fit was dx = −6.51 cos θ − 0.78 sin θ mV and
dy = +4.34 cos θ − 8.01 sin θ mV, so the AO0 CSV shows about ±6.5 mV and
the AO1 CSV about ±9 mV, once per QWP turn. In zmeter fit a cosine with
period 360.
