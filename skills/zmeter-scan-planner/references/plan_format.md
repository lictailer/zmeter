# How a ZMeter scan works and the plan format

## A ZMeter scan

- A scan is a set of nested loops called levels. `level0` is the innermost,
  fastest loop; the highest level is the outermost, slowest loop. For each point
  of a level, every lower level runs completely.
- Each level has:
  - **setters**: channels written at each point. A setter is a linear sweep
    (start, end, number of points; ZMeter spaces them evenly, both ends included)
    or an explicit list of values.
  - **setting method**: how several setters of one level combine. Setters are
    lettered A, B, C... in order. `,` runs segments one after another and `+`
    moves setters together, point by point: `A+B` sweeps A and B together (give
    them the same number of points; a shorter one is simply not written for the
    remaining points), `A,B` sweeps A, then B. With no method the
    setters run one after another (`A,B,C`). While one segment runs, the other
    setters of the level are not written.
  - **getters**: channels read at each point of that level, after the setters
    are written. A level may have none.
  - **averaged getters**: `level<N>_average_<channel>` on a higher level records
    the average of `<channel>` over the whole lower level N for each point of
    the higher level; `<channel>` must be a getter of level N.
  - **settle_time** (s): wait after writing and before reading, at every point of
    a level that has getters.
  - **start_wait_time** (s): one wait before the first reading each time the
    level starts its loop, for example after a large jump back to the start.
  - **manual_set_before / manual_set_after**: single writes done once before the
    level loop starts / after it ends, each time that level runs. Use them to set
    up or restore a condition around a sweep.
- Built-in channels: `default_wait` as a setter waits that many seconds at each
  point; `default_count` as a setter just counts points (use it to repeat lower
  levels N times). Artificial channels (`artificial_channel_<name>`) are derived
  setters such as carrier density and displacement field built from two gate
  voltages; write to them only when the export lists them.
- Shift Compensation channels (`compensated_source_<raw channel>`,
  `compensated_target_<raw channel>`) appear only while the operator has fitted
  and activated a mapping in ZMeter's Shift Compensation window. Setting
  `compensated_source_<S>` moves S and shifts its coupled targets to cancel the
  cross-talk; setting `compensated_target_<T>` writes the requested value plus a
  correction for the current source value, so the value written to T differs
  from the planned one. Range limits apply to the raw channels after
  correction. Typical uses: sweep the raw source with `compensated_target_*`
  held constant in the same level, or map with `compensated_target_*` axes
  under a slower source level.
- Range limits: ZMeter refuses to write a setter value outside the configured
  limit, does not write it, and records that point as NaN. Plans must stay inside
  the limits listed in the export.
- A queue runs items in order: scans and manual-set items (one channel set to
  one value between scans). Each scan is saved as its own data file.
- Time estimate per scan, roughly: number of points of each level multiplied
  together, times (settle_time + instrument read and write time, typically
  0.05 to 0.3 s per point, more for slow devices such as cryostats or stages),
  plus start_wait_time per level start and `default_wait` values. Temperature or
  field setters with `_stable` in the name wait until the value is stable, which
  can take minutes per point.

## Plan format (plan.json)

```json
{
  "name": "nlh_e_cooldown_series",
  "items": [
    {"type": "manual_set", "channel": "Keithley_bg_V", "value": 0.0},
    {
      "type": "scan",
      "name": "NLH_Vbg_sweep_3p4K",
      "comments": "Second-harmonic Hall voltage vs back gate after electron-doped cooldown.",
      "estimated_minutes": 45,
      "levels": [
        {
          "setters": [{"channel": "Keithley_bg_V", "start": -2.0, "end": 2.0, "points": 201}],
          "getters": ["SR860_0_X", "SR860_0_Y", "SR830_2_X"],
          "settle_time": 0.3,
          "start_wait_time": 2.0,
          "manual_set_before": [],
          "manual_set_after": [{"channel": "Keithley_bg_V", "value": 0.0}]
        },
        {
          "setters": [{"channel": "SR860_0_ampl", "values": [0.1, 0.2, 0.4]}],
          "getters": []
        }
      ],
      "plots": [
        {"type": "line", "level": 0, "x": "Keithley_bg_V", "y": "SR860_0_X"},
        {"type": "image", "level": 0, "z": "SR830_2_X"}
      ]
    }
  ]
}
```

The channel names above are examples only; use the names in the export.

- `name` (plan): names the queue folder (`queue_<name>`); optional.
- `items`: in run order. One item that is a scan is written as a single scan
  setting file; anything else as a queue.
- Scan item:
  - `name`: the scan name (used in data file names). Short, no spaces needed,
    e.g. temperature as `3p4K`.
  - `comments`: what the scan is for; saved in the scan's comments.
  - `estimated_minutes`: your estimate; added to the comments.
  - `levels`: a list, `levels[0]` is level0 (innermost).
    - `setters`: at least one. `{"channel", "start", "end", "points"}` or
      `{"channel", "values": [...]}`.
    - `setting_method`: optional, letters with `+` and `,` as above.
    - `getters`: channel names or averaged-getter tokens; may be empty.
    - `settle_time`, `start_wait_time`: seconds, default 0.
    - `manual_set_before`, `manual_set_after`: lists of `{"channel", "value"}`.
  - `plots`: optional.
    - line: `{"type": "line", "level": N, "x": "<setter channel of level N>" or "level", "y": "<getter of level N>"}`
      (`"level"` plots against the point index).
    - image: `{"type": "image", "level": N, "z": "<getter of level N>"}`: x is
      level N, y is level N+1 (so N must not be the top level).
- Manual-set item: `{"type": "manual_set", "channel", "value"}`.

The build script refuses the whole plan, writing nothing, when a channel is not
in the export, a level has no setter or no points, a setting method names a
missing setter, an averaged getter has no source, a value is outside a range
limit, or a plot does not match its level.
