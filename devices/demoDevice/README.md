# Demo Device Template

## Status

`demoDevice` is an older template/simulator and is not the maintained reference integration. Use [mockDevice](../mockDevice/README.md) for new device work.

It is registered under driver ID `demo_device` with required dummy `address`. Its factory deliberately keeps the private `DummyResourceManager` instead of receiving the application's real shared VISA runtime. Runtime mutation remains disabled.

The package now uses normal relative imports and an injected `VisaRuntime` backed by `DummyResourceManager`. It never imports or monkey-patches the real PyVISA manager. After construction, its address selector schedules dummy-resource discovery for the next Qt event-loop turn; the manual Refresh button remains available.

## Intended behavior

The dummy VISA transport models an identification string, operating mode, and voltage level. `DemoDeviceHardware` demonstrates SCPI-style queries/writes with retry handling; `DemoDeviceLogic` wraps the operations in a `QThread`; the widget exposes connect, disconnect, mode, and voltage controls.

## Current scan discovery

Because `MainWindow` inspects the `.logic` object and requires exact signatures, current discovery finds:

- getters: `get_idn`, `get_operating_mode`, `get_voltage_level`, and `get_all`;
- setters: none—the current `set_*` methods take no value argument and use stored setpoints.

`get_idn` and `get_operating_mode` return text, while `get_all` has no measurement return. They do not satisfy the normal numeric scan-data contract and should be filtered or renamed if this template is retained.

## Dependencies and lifecycle gaps

The module requires PyQt6 and the shared runtime infrastructure; the injected dummy manager requires no VISA driver. It retains logic-level connect/disconnect but no complete widget lifecycle for scan pause, force-stop, or application termination. Shared-runtime and offscreen-construction tests cover removal of global transport side effects.

This simulator does not require a hardware bench procedure, but validate any refactor with hardware-independent unit and offscreen-GUI tests. See [device_contract.md](../../documents/device_contract.md) and [testing.md](../../documents/testing.md).

Hardware-independent syntax check: `python -B -m py_compile devices/demoDevice/demoDevice_hardware.py devices/demoDevice/demoDevice_logic.py devices/demoDevice/demoDevice_main.py devices/demoDevice/dummy_visa.py`. Do not adapt this template to real hardware until numeric channel discovery and lifecycle gaps are fixed.
