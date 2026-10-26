# Suggested fields

<!-- Ideas only. The model picks, rewords, merges or skips them and adds
its own. When no API key is set or the model call fails, ZMeter shows the
fields below instead.

Format: a "## group" heading (a group named "setup" goes in the Setup
section), an optional "Looks like:" line saying when the group fits, then
one "- field" per line. "- field: a / b / c" offers answers to pick from;
any other answer is still allowed. "(often)" marks a field usually worth
asking. -->

## this scan
- Goal of this scan (often)
- Changed since last scan (often)
- Same sample spot as last scan: yes / no
- Anything unusual

## optics
Looks like: lasers, galvo or stage maps, rotation stages, photon counts, photodiodes.
- Laser power at sample (often)
- Polarization: parallel / crossed / other

## transport
Looks like: lock-ins, source-meters, gate sweeps.
- Excitation contacts and series resistor (often)
- Lock-in reference: internal / chopper / function generator

## photocurrent
Looks like: a waveplate swept 0-360 deg with a lock-in reading.
- Modulation: chopper / PEM / none

## setup
- Laser wavelength
- Objective and filters
- Waveplate or polarizer on each rotation stage
- Lock-in input contacts
