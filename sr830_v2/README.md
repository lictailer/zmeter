# Stanford Research Systems SR830 (v2)

## Purpose and status

`sr830_v2` is the preferred SR830 integration. It uses the shared `VisaRuntime` while retaining its widget/logic/hardware protocol behavior, identity checking, logging, and monitor coordination. Shared-session lifecycle and offscreen construction have fake coverage; bench validation remains pending.

Constructing the widget does not create a ResourceManager or enumerate. The operator must click **Refresh VISA** for worker-thread discovery. Disconnect closes only its session lease.

## Current scan discovery

The `.logic` object exposes getter signatures for:

- measurements: `X`, `Y`, `R`, `Theta`, `aux_1`, and `aux_2`;
- configuration/readback: `frequency`, `amplitude`, `phase`, `time_constant`, `sensitivity`, reference/input/filter/reserve settings;
- status: `unlocked`, `input_overload`, `time_constant_overload`, and `output_overload`;
- `get_all`, which refreshes values but does not return a measurement.

It exposes no scan setters because its logic-layer `set_*` methods take no value argument. Filter `get_all` and any string-valued configuration getters from measurement scans.

## Setup and units

- Python: PyQt6, PyVISA, NumPy, and pyqtgraph;
- system: compatible VISA backend/interface driver;
- configuration: explicit VISA resource and reviewed input/reference/sensitivity/time-constant/filter/auxiliary settings.

Connection requires a nonempty `*IDN?` response containing `SR830`. VISA timeout is 1000 ms. Frequency is in hertz, sine amplitude and voltage-mode X/Y/R/aux values are in volts, and phase/`Theta` are in degrees.

## Lifecycle and safety

`stop_scan` records whether monitoring was active and stops it; `start_scan` resumes it only when appropriate. `force_stop` stops monitoring and waits for any current logic job to return; termination stops monitoring then disconnects. These methods stop software polling; they do not interrupt an in-flight VISA call or undo instrument settings or auxiliary outputs.

Agents must not enumerate VISA resources, connect, configure, read, write, reset, or disconnect the SR830. Before production use, the user must verify channel filters, timeout/error recovery, aux-output limits, and final instrument state in a **User-executed hardware test**. See [hardware_safety.md](../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile sr830_v2/sr830_hardware.py sr830_v2/sr830_logic.py sr830_v2/sr830_main.py`.

**User-executed hardware test:** use a disconnected/dummy signal path; connect to the explicit VISA address and confirm SR830 identity; record current settings; read X/Y/R/Theta and status; pause/resume monitoring via scan lifecycle calls; set only a user-approved low sine amplitude and 0 V auxiliary output; simulate a VISA timeout; terminate; and confirm monitoring stops and the session closes without altering unrelated settings.
