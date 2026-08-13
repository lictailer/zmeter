# ZMeter Project Structure

## Purpose and authority

This file is the maintained source for current project structure, module relationships, and runtime paths. Executable code and tests remain authoritative for what actually runs. `AGENTS.md` governs agent behavior and safety; `documents/` contains technical contracts; device-local README files contain verified device-specific setup. Archived material is historical evidence only.

## Active runtime path

```text
start_zmeter.py
  -> PyQt6 QApplication
  -> create_equipment()
  -> core.mainWindow.MainWindow
       -> core.scanlist.ScanList
            -> core.scan.Scan
                 -> core.scan_logic.ScanLogic
```

The checked-in startup profile instantiates two `mockDevice.MockDevice` widgets. Real-device imports and connection examples are disabled. `core/scan.py` imports the active `ScanLogic` directly from `core.scan_logic`; `core/scan_logic_old.py` is retained source but is not on the active path.

## Maintained layout

| Path | Current responsibility |
| --- | --- |
| `start_zmeter.py` | Startup/profile selection, device instances/labels, filters, save and backup paths |
| `core/mainWindow.py` | App ownership, discovery, routing, range checks, global lifecycle and shutdown |
| `core/scanlist.py` | Available/queued/manual/past items and sequential queue execution |
| `core/scan.py` | Scan editor/window, plot updates, run logging, save/load/PPT/autosave UI integration |
| `core/scan_logic.py` | Active recursive scan worker, grouped I/O, timing, progress, pause/stop, cleanup |
| `core/device_command_router.py` | Cross-device catalog/read/write routing |
| `core/all_level.py`, `core/individual_setter.py`, `core/brakets.py` | Scan-level/setter editing and setting-array construction |
| `core/all_plot_settings.py`, `core/all_plots.py` | Plot configuration and presentation |
| `core/artificial_channel_logic.py` | Transformed two-channel state, range/ramp/skip coordination |
| `mockDevice/` | Hardware-independent simulator, three-layer reference device, and tests |
| `<device>/` | Device-specific widget/logic/hardware integrations and optional UI/dependencies |
| `tests/` | Hardware-independent core regression tests |
| `documents/` | Canonical repository-wide technical documentation and decisions |
| `data/` | Default local measurement output; ignored by Git |
| `scan_range_limits.json` | Default global scan-output limit configuration |
| `zmeter_May2026_environment.yml` | Maintained Windows Conda environment |
| `archive/` | Retired documentation/code evidence; not current authority |

## Device integration inventory

Source packages currently include `mockDevice`, `demoDevice`, `nidaq`, `ni6423`, `keithley24xx`, `hp34401a`, `sr830`, `sr830_v2`, `sr860`, `opticool`, `montana2`, `tlpm`, `pem100`, `sp150`, `k10cr1`, `BBD30X`, `auto_focus`, `auto_position`, `autofocus_xuguo`, and `ANC300`. Presence in the tree does not assert readiness, compatibility, or hardware validation. Verify the target package, dependencies, lifecycle, tests, and device-local documentation before enabling it. `BBD30X` is an optional, disabled-by-default Kinesis/pythonnet integration whose device README records known safety and lifecycle limitations pending remediation.

## Maintenance rule

Update this file when verified module ownership, import paths, entry points, or runtime relationships change. Keep behavioral details in the relevant canonical document and do not restore archived claims without code/test verification.
