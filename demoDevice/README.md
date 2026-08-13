# Demo Device Template

## Status

`demoDevice` is an older template/simulator and is not the maintained reference integration. Use [mockDevice](../mockDevice/README.md) for new device work.

The current files use top-level sibling imports (`demoDevice_hardware`, `dummy_visa`) that do not match normal package imports from the repository root. The hardware module also monkey-patches `pyvisa.ResourceManager` globally at import time. Reconcile those behaviors before enabling the widget.

## Intended behavior

The dummy VISA transport models an identification string, operating mode, and voltage level. `DemoDeviceHardware` demonstrates SCPI-style queries/writes with retry handling; `DemoDeviceLogic` wraps the operations in a `QThread`; the widget exposes connect, disconnect, mode, and voltage controls.

## Current scan discovery

Because `MainWindow` inspects the `.logic` object and requires exact signatures, current discovery finds:

- getters: `get_idn`, `get_operating_mode`, `get_voltage_level`, and `get_all`;
- setters: none—the current `set_*` methods take no value argument and use stored setpoints.

`get_idn` and `get_operating_mode` return text, while `get_all` has no measurement return. They do not satisfy the normal numeric scan-data contract and should be filtered or renamed if this template is retained.

## Dependencies and lifecycle gaps

The module requires PyQt6 and either PyVISA or the included dummy patch. It has logic-level connect/disconnect but no complete widget lifecycle for scan pause, force-stop, or application termination. It has no focused tests in the current tree.

This simulator does not require a hardware bench procedure, but validate any refactor with hardware-independent unit and offscreen-GUI tests. See [device_contract.md](../documents/device_contract.md) and [testing.md](../documents/testing.md).

Hardware-independent syntax check: `python -B -m py_compile demoDevice/demoDevice_hardware.py demoDevice/demoDevice_logic.py demoDevice/demoDevice_main.py demoDevice/dummy_visa.py`. Do not adapt this template to real hardware until package imports, global monkey-patching, numeric channel discovery, lifecycle, and focused tests are fixed.
