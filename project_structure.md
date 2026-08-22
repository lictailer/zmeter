# ZMeter Project Structure

## Purpose and authority

This file is the maintained source for current project structure, module relationships, and runtime paths. Executable code and tests remain authoritative for what actually runs. `AGENTS.md` governs agent behavior and safety; `documents/` contains technical contracts; device-local README files contain verified device-specific setup. Archived material is historical evidence only.

## Active runtime path

```text
start_zmeter.py
  -> PyQt6 QApplication
  -> core.shared_runtime.RuntimeServices
  -> core.device_management.load_profile()
  -> reviewed DriverRegistry -> DeviceManager
  -> core.mainWindow.MainWindow
       -> core.scanlist.ScanList
            -> core.scan.Scan
                 -> core.scan_logic.ScanLogic
```

The checked-in `config/profiles/mock.json` profile instantiates two disconnected `devices.mockDevice.mock_device_main.MockDevice` widgets through the lazy reviewed registry. `start_zmeter.py` contains no device-specific imports or connection values. `core/scan.py` imports the active `ScanLogic` directly from `core.scan_logic`; `core/scan_logic_old.py` is retained source but is not on the active path.

## Maintained layout

| Path | Current responsibility |
| --- | --- |
| `start_zmeter.py` | Thin command-line profile selection and application/session orchestration |
| `config/` | Validated checked-in mock profile, examples, and ignored local-profile boundary |
| `core/device_management/` | Immutable profile models, validation, reviewed lazy Phase 1/2 registration adapters, generation/call gates, session-only runtime mutation, device ownership, and lifecycle reports |
| `core/device_catalog.py` | Immutable rebuilt channel/catalog snapshots and typed refusal errors |
| `core/mainWindow.py` | App UI, two-phase catalog acknowledgement, dynamic device controls, routing, logged range checks, scan coordination, and shutdown barrier |
| `core/scanlist.py` | Available/queued/manual/past items, sequential queue execution, activity reservations, and runtime-mutation seals |
| `core/scan.py` | Scan editor/window, plot updates, run logging, primary/recovery JSON, save/load/PPT/autosave UI integration |
| `core/scan_logic.py` | Active recursive scan worker, grouped I/O, timing, progress, pause/stop, cleanup |
| `core/device_command_router.py` | Cross-device catalog/read/write routing under whole-request manager leases |
| `core/device_log.py` | Shared in-memory device-log presentation and formatting |
| `core/shared_runtime/` | Lazy typed VISA/Kinesis ownership, leases, VISA discovery watchdog/retention, diagnostics, shutdown, fake injection, and local vendor manifests |
| `core/shared_runtime/vendor/thorlabs_kinesis/` | Tracked, manifest-verified Kinesis 1.14.58.26351 runtime and setup instructions |
| `core/all_level.py`, `core/individual_setter.py`, `core/brakets.py` | Scan-level/setter editing and setting-array construction |
| `core/all_plot_settings.py`, `core/all_plots.py` | Plot configuration and presentation |
| `core/artificial_channel_logic.py` | Transformed two-channel state, range/ramp/skip coordination |
| `devices/` | Flat package namespace for device integrations; it performs no eager device imports |
| `devices/mockDevice/` | Hardware-independent simulator, three-layer reference device, and tests |
| `devices/<device>/` | Device-specific widget/logic/hardware integrations and optional UI/dependencies |
| `tests/` | Hardware-independent core regression tests |
| `documents/` | Canonical contracts, current status/readiness, guides, and decisions |
| `data/` | Default local measurement output; ignored by Git |
| `scan_range_limits.json` | Default global scan-output limit configuration |
| `zmeter_May2026_environment.yml` | Maintained Windows Conda environment |
| `archive/` | Retired documentation/code evidence; not current authority |

The standalone deployment installer is maintained in
`https://github.com/lictailer/zmeter-deploy`. ZMeter retains its release-
packaging workflow and the maintained contract in
`documents/release_deployment.md`.

## Device integration inventory

Source subpackages under `devices/` currently include `mockDevice`, `demoDevice`, `nidaq`, `ni6423`, `keithley24xx`, `hp34401a`, `sr830`, `sr860`, `opticool`, `montana2`, `four9`, `tlpm`, `pem100`, `sp150`, `k10cr1`, `BBD30X`, `auto_focus`, `auto_position`, `autofocus_xuguo`, and `ANC300`. Presence in the tree does not assert readiness, compatibility, or hardware validation. Verify the current matrix in `documents/device_status.md` and the target package documentation before enabling it. The maintained replacement is the sole canonical `devices/sr830/` implementation. `BBD30X` is an optional, disabled-by-default Kinesis/pythonnet integration whose device README records known safety and lifecycle limitations pending remediation.

The Phase 2 startup-only registry entries are `four9`, `montana2`, `opticool`,
and `tlpm`. They are lazy and disabled in tracked profiles; their device-local
READMEs and `documents/device_status.md` record environment-specific accepted
limitations.

Maintained VISA packages (`pem100`, `sp150`, `hp34401a`, `keithley24xx`,
`sr830`, and `sr860`) use `VisaRuntime`. K10CR1 and BBD30X use one injected `KinesisRuntime` and the same local
manifest-validated DLL directory. `devices.demoDevice` uses an injected fake VISA
manager and does not patch PyVISA globally.

## Maintenance rule

Update this file when verified module ownership, import paths, entry points, or runtime relationships change. Keep behavioral details in the relevant canonical document and do not restore archived claims without code/test verification.
