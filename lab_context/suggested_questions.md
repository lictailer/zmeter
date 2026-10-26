# Suggested fields

<!-- Ideas only. The model picks the few that fit this scan, rewords,
merges or skips them, and adds its own. When no API key is set or the model
call fails, ZMeter shows the first 30 fields below instead, so the most
general ones come first.

Format: a "## group" heading (a group whose name contains "setup" goes in
the Setup section), an optional "Looks like:" line saying when the group
fits, then one "- field" per line. "- field: a / b / c" offers example
answers to pick from; any other answer is always allowed. "(often)" marks a
field usually worth asking. -->

## this scan
- Goal of this scan (often)
- Changed since last scan: nothing / sample spot / power / wavelength / polarization / gate / temperature / field (often)
- Same sample spot as last scan: yes / no
- Expected result or what to compare with
- Anything unusual (often)

## sample state and history
Looks like: gate sweeps, doping maps, correlated or charge-ordered states, anything hysteretic.
- Sample or flake ID
- Cooldown protocol: gates at zero / gates set while cooling / field cooled / unknown
- Gate voltages during cooldown
- Sweep direction: up / down / both / from a prepared state
- Time held in this state before the scan
- Light on the sample before the scan: none / laser / room light

## environment
Looks like: cryostat or magnet devices, temperature or field in the scan name.
- Sample temperature (often)
- Magnetic field and direction: zero / out-of-plane / in-plane
- Temperature stable: yes / drifting / ramping

## transport
Looks like: lock-ins, source-meters, gate sweeps.
- Measurement configuration: 2-probe / 4-probe / Hall / nonlocal (often)
- Current contacts and voltage contacts (often)
- Excitation amplitude and frequency
- Series resistor or preamplifier
- Lock-in harmonic: 1f / 2f / 3f

## nonlinear transport
Looks like: a lock-in reading harmonic 2, "NLH" or "2w" in the scan name.
- Current direction relative to crystal axis
- Symmetry check done: none / current reversed / contacts swapped

## gates and density
Looks like: two gates, or n and E (D) channels.
- How n and D are calibrated: geometric capacitance / quantum oscillations / Hall / not yet
- Gate leakage checked: yes / no

## optics
Looks like: lasers, galvo or stage maps, rotation stages, photon counts, photodiodes.
- Laser power at sample (often)
- Polarization: parallel / crossed / circular / other
- Spot size
- Incidence: normal / oblique
- Detector and integration time

## photocurrent
Looks like: a waveplate swept 0-360 deg with a lock-in reading, or a map read as current.
- Modulation: chopper / PEM / none
- Bias across the sample
- Contacts collecting the photocurrent

## spectroscopy
Looks like: monochromator, spectrometer, wavelength swept.
- Spectral range or grating
- Accumulation or integration time

## ultrafast
Looks like: a delay stage or "pump", "probe", "delay" in the scan name.
- Pulse width and repetition rate
- Pump and probe wavelength and power
- Which beam is chopped: pump / probe / both

## setup
- Laser and wavelength
- Objective and filters
- Waveplate or polarizer on each rotation stage
- Lock-in input contacts
- Cryostat or stage in use
