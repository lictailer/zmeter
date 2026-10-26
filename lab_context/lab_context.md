# ZMeter lab context  (version 0.4, 2026-10-21)

<!-- The AI model reads this whole file before writing each setup record.
Sections 1-5 hold general knowledge that fits most labs; treat them as
background, not rules. Rewrite section 6 for your own lab. Change the
version line at the top when you edit, because it is saved with every
questionnaire. -->

## 1. Your job
Help the user keep a short record of how each measurement was done, so
someone reading the data file later understands it. You get the scan
settings (or a queue of scans), an instrument snapshot, an experiment
description, previous answers and this file. Labs differ, so use judgement;
everything below is a hint, not a rule.
- Write down what you can work out yourself (measurement type, what each
  device and swept axis is for, polarization, temperature from the scan
  name; e.g. SHG = second harmonic generation, NLH = nonlinear Hall,
  3p4K = 3.4 K). Guessing is fine; say how sure you are.
- Ask mostly about this scan: its goal, what changed since the last one,
  sample spot, power, anything set by hand. The setup (wiring, lasers,
  optics) rarely changes, so ask little about it and reuse old answers.
- Keep it easy: short field labels, likely answers to pick from, nothing
  the settings or snapshot already show.
- A queue gets one record for all its scans; the order of scans and
  manual-set steps shows the plan (e.g. a temperature series).
- A snapshot device marked "skipped" was not read; it only matters if the
  scan depends on it.

## 2. How a ZMeter scan is built
- A scan has nested levels. level0 is the innermost (fastest) loop.
- Each level has setters (channels swept), getters (channels read at each
  point), settle_time, and manual_set_before / manual_set_after (values set
  once before / after that level runs).
- Channel names are "<device id>_<variable>", e.g. SR860_0_time_constant.
- setting_method groups setters: "A+B,C+D" means A and B move together in
  segment 1, C and D move together in segment 2.
- default_wait (s) and default_count are timing helpers, not instruments.
- artificial_channel_* are derived channels, e.g. carrier density n and
  displacement field E built as linear combinations of two gate voltages.
- The scan name is free text typed by the user; it often hints at the
  experiment, temperature (3p4K = 3.4 K) or configuration.

## 3. Driver types and their usual roles
- sr830, sr860, mfli: lock-in amplifiers. X/Y/R/Theta are measured
  signals. amplitude = sine-out excitation. harmonic 2 often means a
  nonlinear (2f) measurement. Reference may be internal, a chopper, or a
  function generator. Inputs: A, A-B (differential voltage), I (current).
- keithley24xx: source-meter. Often a gate voltage (current read = leakage),
  or a DC bias / current source on the sample.
- hp34401a: digital multimeter (DC voltage).
- ni6423, nidaq: NI DAQ cards. AO = analog out (galvo mirrors, gate or bias),
  AI = analog in (photodiode, amplified signal), counter = photon counts.
- k10cr1: motorized rotation stage, usually holding a half- or quarter-wave
  plate or a polarizer. A half-wave plate rotated by a turns linear
  polarization by 2a.
- bbd30x: motorized linear stage (sample or objective position).
- tlpm: Thorlabs power meter (optical power, wavelength setting).
- pem100: photoelastic modulator (polarization modulation, often with a
  lock-in at the PEM frequency).
- sp150: monochromator (wavelength selection).
- montana2, opticool, four9: cryostat / temperature controllers.
- nema11_stepper, arduino_steppers, auto_focus: focus or positioning motors.
- mock_device, demo_device: simulators, not real hardware.

## 4. Common experiment families (clues, not rules)
- Transport: lock-ins + an excitation source, gate sweeps, 2- or 4-probe,
  Hall bar. Key unknowns: which contacts each lock-in input and the source
  are on, series resistor, excitation amplitude and frequency, filters.
- Nonlinear transport (nonlinear Hall, 2nd harmonic): lock-in harmonic 2.
- Gate maps: two gates swept (dual gate), or n and E channels.
- Optical mapping (reflection, PL, photocurrent): galvo or stage x/y sweep.
- Polarization-resolved optics (SHG, polarimetry): rotation stages swept.
- Photocurrent (CPGE/LPGE): waveplate rotated through 360 deg, lock-in on
  the photocurrent with a chopper reference.
- Temperature, field or power dependence: one slow variable stepped by
  manual sets between scans.

## 5. Things people forget
- Laser wavelength and power at the sample; filters and objective.
- Which waveplate or polarizer sits on each rotation stage.
- Contacts used by each lock-in input and by the source.
- Series resistor or current-limiting path.
- Sample state: cooldown history, gate bias during cooldown, illumination.

## 6. This lab (replace for your lab)
### Xuguo Zhou, optics (SHG, reflection, photocurrent) on 2D materials
- Device ids: Keithley_bg (back gate), Keithley_tg (top gate); SR860_0,
  SR860_1, SR830_2, SR830_3, SR830_4 (lock-ins, numbered across models);
  HWP_exc, HWP_det (K10CR1, excitation / detection waveplates);
  ni6423 AO0/AO1 = galvo x/y (V), counter0 = SHG photon counts;
  nidaq AI0 = reflection photodiode (?); ni6423 AI9 = TODO.
- Base temperature ~3.4 K (cryostat: TODO). Lasers: 1064 nm, 750 nm (TODO models).
- Scan names: xx = parallel, xy = crossed, xxxy = both; "35exc35det" =
  HWP_exc 35 deg, HWP_det 35 deg (?); e_cooldown / h_cooldown = cooled with
  gates set for electron / hole doping (?); bbb / baa = TODO.
- n and E are defined per device from Vbg and Vtg (TXT15: n = 0.1667 Vbg +
  0.2660 Vtg - 0.0319, E = 0.1667 Vbg - 0.2660 Vtg + 0.0319).
- Samples: TXT series (monolayer TaIrTe4, dual-gated, hBN), 3L TaIrTe4,
  bulk TaIrTe4, AgCrP2S6, Co0.25NbSe2.
