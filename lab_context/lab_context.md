# ZMeter lab context  (version 0.5, 2026-10-26)

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
- Many quantum materials remember their past: the same gate voltage can
  give a different state after a different cooldown or sweep direction.
  When a scan depends on that, ask how the state was prepared.
- Keep it easy: short field labels, likely answers to pick from, nothing
  the settings or snapshot already show. Answer options are examples; the
  user can always type something else.
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
What usually matters for each kind of measurement. Use what fits; most
scans touch only one or two of these.
- Transport (resistance, Hall): lock-ins + an excitation source, 2- or
  4-probe, Hall bar. Which contacts carry current and which measure voltage,
  excitation amplitude and frequency, series resistor, preamp gain, filters.
- Edge / topological transport (quantum spin Hall and similar): local vs
  nonlocal configuration, which edge or contact pair, channel length,
  whether the plateau or quantized value is the point of the scan.
- Correlated or charge-ordered states (insulating states at finite doping,
  charge density waves, superlattices): carrier density n and displacement
  field D, sweep direction and rate, hold time, cooldown protocol (gates set
  while cooling), whether the state is bistable or hysteretic, how long the
  sample has sat in this state.
- Nonlinear transport (nonlinear Hall, Berry curvature dipole, 2nd
  harmonic): lock-in on harmonic 2, current direction relative to the
  crystal axis, excitation amplitude (the signal scales with its square),
  symmetry checks such as reversing current or swapping contacts.
- Gate maps: two gates swept (dual gate), or n and D (E) channels built from
  them; how n and D are calibrated; gate leakage.
- Optical mapping (reflection, PL, photocurrent, SHG): galvo or stage x/y
  sweep; spot size, objective, power at sample, which flake or region.
- Photocurrent (incl. circular / linear photogalvanic, CPGE / LPGE):
  photon energy or wavelength (visible to mid-IR), polarization state and
  which waveplate is rotating, incidence angle, chopper or other modulation,
  bias and gate voltages, which contacts collect the current.
- Polarization-resolved optics (SHG, Kerr, polarimetry): excitation and
  detection polarization, analyzer, waveplate angles, crystal-axis angle,
  detector and its integration time.
- Spectroscopy (Raman, PL, spectral photocurrent): laser line, grating or
  monochromator setting, filters, accumulation time.
- Ultrafast / time-resolved (pump-probe, two-pulse correlation): pulse
  width, repetition rate, pump and probe energies and powers, delay stage
  setting, which beam is chopped.
- Tunnelling or vertical heterostructures: interlayer bias, barrier,
  which layer is grounded.
- Temperature, field, power or wavelength dependence: one slow variable
  stepped by manual sets between scans; field direction (in- or
  out-of-plane) and sweep rate.

## 5. Things people forget
- Laser wavelength and power at the sample; filters and objective.
- Which waveplate or polarizer sits on each rotation stage.
- Contacts used by each lock-in input and by the source.
- Series resistor or current-limiting path.
- Sample state: cooldown history, gate bias during cooldown, illumination,
  sweep direction, time since the last change of state.
- What changed on purpose since the previous scan, and what was checked
  but left the same.

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
- Group background (for context, not a checklist): monolayer TaIrTe4 is a
  dual quantum spin Hall insulator, with a correlated (likely CDW)
  insulating state at finite electron doping (Nature 628, 515 (2024)) and a
  bistable superlattice that switches with doping and cooling protocol and
  persists for days (Nature 652, 68 (2026); transport, nonlinear Hall,
  Raman, STM). Earlier work: gate-switchable Berry curvature dipole seen as
  circular photogalvanic current in monolayer WTe2 under mid-IR, normal
  incidence (Nat. Phys. 14, 900 (2018)); spatial, spectral and two-pulse
  ultrafast photocurrent in graphene-BN-graphene (Nat. Phys. 12, 455 (2016)).
