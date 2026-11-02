# Planning examples

Examples of how this lab likes measurements planned. They show reasoning, not
rules: adapt them to the request and the export, and still ask about anything
not confirmed. Device and channel names here are examples; use the export's.

## One scan per cooldown (superlattice / bistable states)

Request: "Measure the gate map after cooling with electron doping and after
cooling with hole doping."

- The sample state depends on the gates applied while cooling, so each cooldown
  is its own condition. Plan one scan per cooldown, not one scan with cooldown
  as an outer level: if the second cooldown fails, the first map is already
  saved, and each data file is one state for analysis.
- Warming up and cooling down is usually done by hand or needs a cryostat
  channel; check the export. If the cryostat is not in the export, say that the
  user must warm up, set the cooling gates and cool down between the scans, and
  plan the gate settings as manual-set items so ZMeter applies them before each
  scan.
- Ask: cooling gate voltages for each case, target temperature, gate map ranges
  and resolution, which lock-in reads which signal, excitation, and whether the
  map should start from the cooling gate values.

## Nonlinear Hall (second harmonic)

Request: "Nonlinear Hall measurement versus gate."

- Typical setup: one lock-in sources the current (sine out) and reads the
  longitudinal first-harmonic voltage; another reads the transverse voltage at
  harmonic 2. Which lock-in is on which contacts is not in the export: ask
  (options: the lock-in device ids in the export). Also confirm the harmonic
  setting of each lock-in, the excitation amplitude and frequency, the series
  resistor, and the time constant (settle_time is usually 3 to 5 time constants).
- The signal scales with the square of the current, so an amplitude dependence
  is a useful outer level or a separate scan; ask whether it is wanted.
- Symmetry checks (current reversed, contacts swapped) need rewiring: list them
  as manual steps between scans, not as something ZMeter does.

## Temperature series as a queue

Request: "Repeat the gate sweep at 3.4, 10, 20 and 50 K."

- Plan one scan per temperature in a queue, each preceded by a manual-set item
  on the cryostat's stable-temperature setter (it waits until stable). Name each
  scan with its temperature (`gate_sweep_10K`).
- If no temperature setter is in the export, say the temperature must be set by
  hand before each scan and plan a single scan instead, or one scan per
  temperature for the user to start after each change.
- Ask about wait time after reaching each temperature and whether the gate
  should return to zero before each temperature change.

## Spectra versus gate (array getter)

Request: "Take a PL spectrum at each back-gate voltage."

- The spectrum getter (for example `andor_0_spectrum`) goes on level0 with the
  gate as level0's setter; ZMeter adds the pixel axis as a locked fixed level
  below it. Do not put the spectrum on an outer level: the script refuses it.
- Each gate point costs one exposure (times the number of accumulations) plus
  readout. Ask for exposure time, accumulations, centre wavelength and grating,
  and set them with manual-set items or `manual_set_before` when the export has
  those setter channels (`andor_0_exposure_time`, `andor_0_center_wavelength`).
- Useful plots: a line plot of the latest spectrum against its axis
  (`"x": "axis"`) and an image of the spectrum against the gate.
- A camera image getter adds two fixed levels (rows and columns); files grow
  quickly, so check the total size (points times pixels) with the user.

## Long maps

A 201 x 201 map at 0.3 s per point takes about 3.4 hours. If a map is that long
and splits naturally (for example by displacement field ranges, or by repeated
passes), suggest separate scans so a failure loses less data, and say how long
each one takes.
