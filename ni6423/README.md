# NI USB-6423 Integration

## Purpose and status

`ni6423` is the newer NI-DAQmx integration for a four-output, 32-input NI USB-6423 configuration with gated counter measurement and optional pulse generation. The package separates widget, logic, and hardware and dynamically creates its scan-facing channel methods. It depends on real NI-DAQmx resources and has no hardware-independent simulator in this directory.

## Scan channels

| Direction | Channels | Units/meaning |
| --- | --- | --- |
| Set | `AO0` through `AO3` | Analog output target in volts |
| Get | `AI0` through `AI31` | Integrated analog input in volts |
| Get | `AO0` through `AO3` | Output feedback read through `AI28` through `AI31` |
| Get | `counter0` | Gated `Ctr0` count rate in hertz |

Because getter and setter channel names share `AO0` through `AO3`, direction determines whether the operation writes the output or reads its wired feedback. The feedback wiring map is fixed in the current logic and must match the lab installation.

## Timing and routing

Analog-input and counter integration times default to 1 ms. Values must be at least 100 microseconds and exact 100-microsecond steps. Counter measurement uses configured counter/timebase/PFI routing; pulse output uses `Ctr3` and its configured PFI terminal. Confirm all terminal names and counter reservations before use.

The hardware defaults to a `[-10, 10]` V AO/AI range unless constructed otherwise. Repository-wide output limits are separate: the checked-in `scan_range_limits.json` names `ni6423_0`, while the commented startup example registers `ni6423`. A production profile must make those labels and channel limits agree.

## Setup and lifecycle

- Python: PyQt6 and `nidaqmx` from the maintained environment;
- system: NI-DAQmx driver compatible with the device and Python package;
- configuration: NI device name, AO/AI ranges, feedback wiring, counter sources, gate/pulse counters, and PFI terminals.

The widget pauses its monitor during a scan and `terminate_dev` stops monitoring and closes all tasks. There is no widget `force_stop`; review behavior for active writes, reads, counter gates, and pulse tasks before production use.

Agents must not import/run commands that enumerate NI devices, initialize the device, create tasks, write/read channels, route counters, or generate pulses. The executable `__main__` blocks in the logic and hardware files are hardware bench tests and are user-only. See [hardware_safety.md](../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile ni6423/ni6423_hardware.py ni6423/ni6423_logic.py ni6423/ni6423_main.py`. No hardware-independent NI transport test exists yet.

**User-executed hardware test:** disconnect the DAQ from the experiment and use a reviewed breakout/load; verify the NI device name and every PFI/counter route; connect; write 0 V and then +0.1 V to one AO within configured limits; confirm the mapped feedback input; read one grounded AI; measure a known counter source; stop any pulse task; terminate; and confirm all tasks release. Repeat fault cleanup with one deliberately invalid channel name before reconnecting the experiment.
