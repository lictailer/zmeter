# TLPM - Thorlabs Power Meter Module

A Python interface for Thorlabs power meters with GUI support.

## Overview

This module provides an interface for controlling and reading from Thorlabs power meters.

Verified model: PM100D

## Installation

1. Ensure you have zmeter environment installed
2. **Install the [Thorlabs Optical Power Monitor (Must)](https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=OPM)**
3. Connect your Thorlabs power meter via USB

## Usage

### Standalone GUI Application
```python
python tlpm_main.py
```

### Programmatic Use
```python
from tlpm.tlpm_logic import TLPMLogic

# Create logic instance
logic = TLPMLogic()

# Connect to device
logic.do_connect = True
logic.start()

# Read power measurement
power = logic.get_power()
print(f"Power: {power} W")

# Disconnect
logic.do_disconnect = True
logic.start()
```

## Notes

- Requires Thorlabs power meter hardware connected via USB
- Requires Thorlabs Optical Power Monitor (Not Thorlabs' Power Meter Software)
- Automatic device discovery scans for available instruments
- Supports wavelength calibration for accurate measurements
- Real-time plotting shows last 1000 measurement points
