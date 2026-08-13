# Stanford Research Systems SR830 (Legacy)

## Purpose and status

This is the original PyVISA integration for the SRS SR830 lock-in amplifier. The checked-in startup profile explicitly recommends `sr830_v2` instead. Keep this module for comparison or lab-specific compatibility; do not select it for new profiles without a concrete reason.

Constructing the widget enumerates VISA resources and starts a 50 ms UI monitor timer. Do not instantiate it during hardware-independent tests.

## Current scan discovery

The `.logic` object exposes getter signatures for:

- measurements: `X`, `Y`, `R`, `Theta`, `aux_1`, and `aux_2`;
- configuration/readback: `frequency`, `amplitude`, `phase`, `time_constant`, `sensitivity`, reference/input/filter/reserve settings;
- status: `unlocked`, `input_overload`, `time_constant_overload`, and `output_overload`.

It exposes no scan setters: logic-layer `set_*` methods use stored setpoints and take no value argument. Widget methods with value arguments are not inspected by `MainWindow`.

Several configuration getters return labels or codes rather than measurement scalars. Use explicit profile getter filters; for ordinary acquisition, expose only the intended numeric channels.

## Setup and units

- Python: PyQt6, PyVISA, NumPy, and pyqtgraph;
- system: compatible VISA backend/interface driver;
- configuration: exact VISA address, input mode, reference, sensitivity, time constant, harmonic, filters, and auxiliary-channel use.

Frequency is in hertz, sine amplitude and X/Y/R/aux values are in volts for voltage-mode operation, and `Theta`/phase are in degrees. Verify current-input interpretation separately.

## Lifecycle and limitations

The widget can pause/resume monitoring around scans and disconnect on termination. Its `force_stop` writes a misspelled attribute (`reject_siginal`) and does not constitute a reliable stop path. There are no focused tests or recorded hardware validation.

Agents must not enumerate VISA resources, connect, configure, read, write auxiliary outputs, reset, or disconnect the SR830. See [hardware_safety.md](../documents/hardware_safety.md). Prefer [sr830_v2](../sr830_v2/README.md) for maintained work.

## Validation

Hardware-independent syntax check: `python -B -m py_compile sr830/sr830_hardware.py sr830/sr830_logic.py sr830/sr830_main.py`.

No production bench test is recommended for this legacy path while its force-stop defect remains. If continued use is required, the **User-executed hardware test** must first use a disconnected/dummy signal path: verify SR830 identity; record existing settings; read X/Y/R/Theta; pause/resume monitoring; write only a reviewed low sine amplitude and 0 V auxiliary output; terminate; and confirm the VISA session closes without changing unrelated settings.
