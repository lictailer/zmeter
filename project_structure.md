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
            -> core.queue_model.LiveQueueModel
            -> core.scan.Scan
                 -> core.scan_logic.ScanLogic
```

The checked-in root `device_config.xlsx` workbook supplies the ordered device rows to the lazy reviewed registry. `start_zmeter.py` contains no device-specific imports or connection values. `core/scan.py` imports the active `ScanLogic` directly from `core.scan_logic`; the retired `scan_logic_old.py` is kept in `archive/legacy-scan-engine/` and is not on the active path.

## Maintained layout

| Path | Current responsibility |
| --- | --- |
| `start_zmeter.py` | Thin command-line workbook selection and application/session orchestration |
| `device_config.xlsx` | Default Excel-only device configuration beside the launcher |
| `core/device_management/` | Immutable configuration models, Excel validation, reviewed lazy registration adapters for every driver including the mock (`registrations.py`; the core `registry.py` never imports `devices`), generation/call gates, session-only runtime mutation, device ownership, truthful scan-lifecycle completion, and lifecycle reports |
| `core/device_catalog.py` | Immutable rebuilt channel/catalog snapshots and typed refusal errors |
| `core/mainWindow.py` | App UI, two-phase catalog acknowledgement, dynamic device controls, routing, logged range checks and the scan-start list of written channels without a scan limit, scan coordination, and shutdown barrier |
| `core/scanlist.py` | Available/queue/manual/past item widgets, queue orchestration, per-item manual-set workers, UI state transitions, and runtime-mutation seals |
| `core/queue_files.py`, `core/channel_check.py` | Saved-queue folders (`queue.json` plus scan setting files); hardware-free lookup and replacement of scan/queue channels missing from the device catalog, and the queue pre-start level checks |
| `core/queue_model.py` | Thread-safe live queue entries with stable IDs, ordered pending mutations, current-item ownership, and atomic run completion |
| `core/scan.py` | Scan editor/window, explicit prepare/run/finalize state, bounded lifecycle/output worker, GUI-owned image capture, plot updates, run logging, primary/recovery JSON, save/load/PPT/autosave UI integration |
| `core/scan_file_info.py` | `format_version` and `software` stamped into every scan JSON ZMeter writes (output, recovery/backup, manual save, autosave, setting and queue scan files), read from `deployment-manifest.json` or `.git` without running git; load-time version check; see `documents/data_format.md#format-version-and-software` |
| `core/scan_hooks.py` | Scan-finished hooks: the frozen `ScanFinished` record (name, status, elapsed time, points, JSON path, error, queue run, optional plot PNG) and `ScanHooks`, owned by the main window as `scan_hooks` (moves to the session in v2 phase 2). `Scan._emit_scan_finished` calls every hook once per finished scan after the files are written and before the scan is marked finalized; a failing hook is a warning in the scan log and never affects saving, device restore or the queue. The plot screenshot is captured only when a hook asks for it. Standard library only |
| `core/scan_logic.py` | Active recursive scan worker, grouped I/O, timing, progress, pause/stop, and terminal-result publication; it does not restore device widgets or persist final outputs |
| `core/setup_capture/` | Setup capture: start/end instrument snapshots (`SNAPSHOT_GETTERS` on device logic classes, optional `lab_context/snapshot_channels.json`), the scan window's Questionnaire tab, the queue questionnaire pop-up, the AI model call through the openai SDK (Claude, DeepSeek or any OpenAI-compatible provider) with suggestion fallback, per-PC settings (one API key per provider in the OS keyring), and the "Export system info" Markdown file for AI scan planning (`system_export.py`) |
| `skills/zmeter-scan-planner/` | Self-contained AI scan-planning skill installed into Claude or Codex, outside ZMeter: instructions, plan-format and example references, and a standard-library build script that checks a plan against the system export and writes scan setting files or queue folders. It copies the file formats of `core/scan.py` and `core/queue_files.py`; `tests/test_scan_planner_skill.py` loads its output with ZMeter's code |
| `lab_context/` | Hand-edited lab knowledge read by the questionnaire model (`lab_context.md`), suggested questions (`suggested_questions.md`), and an example snapshot-channel override |
| `core/device_command_router.py` | Cross-device catalog/read/write routing under whole-request manager leases |
| `core/device_log.py` | Shared in-memory device-log presentation and formatting |
| `core/measurement_io.py`, `measurement_widgets.py`, `measurement_records.py` | Checked cross-device coordinator routing, channel selectors and unique atomic data/PNG bundles with numeric local-time run keys; no instrument ownership |
| `core/shared_runtime/` | Lazy typed VISA/Kinesis ownership, leases, VISA discovery watchdog/retention, diagnostics, shutdown, fake injection, and local vendor manifests |
| `core/shared_runtime/vendor/thorlabs_kinesis/` | Tracked, manifest-verified Kinesis 1.14.58.26351 runtime and setup instructions |
| `core/all_level.py`, `core/individual_setter.py`, `core/brakets.py` | Scan-level/setter editing and setting-array construction; locked fixed levels for array getters |
| `core/array_getters.py`, `core/array_levels.py` | Array getters: the `ARRAY_GETTERS` declaration (`ArrayGetter`, at most 2 axes), the `ArrayCatalog` the main window provides, shape validation, and the fixed-level sync with level/average/plot-token renumbering; see `documents/scan_engine.md#array-getters` |
| `core/all_plot_settings.py`, `core/all_plots.py` | Plot configuration and presentation |
| `core/scan_info.py`, `core/widget_helpers.py`, `core/plot_config.py` | Default `ScanInfo` template for new scan windows (imports only NumPy); `clearLayout`/`is_float` Qt helpers; `configure_pyqtgraph()`, the global row-major image setting applied when `core.mainWindow` and `core.all_plots` are imported |
| `core/append_to_ppt.py` | PowerPoint slide export through Windows COM; `pywin32` is imported inside the COM function, so `core.scan` imports on any OS |
| `core/artificial_channel_logic.py` | Transformed two-channel state, range/ramp/skip coordination |
| `core/slack_notify/` | Slack direct messages: the main-window row and bot-token dialog (`widgets.py`; token in the OS keyring, email never saved), message texts (`messages.py`), the Web API calls (`client.py`), the stacked plot screenshot (`capture.py`) and `SlackNotifier` (`notifier.py`): a bounded outbox drained by one daemon thread, so scans never wait on Slack. Scan end (the first scan-finished hook, registered by `scan_hook.py`), queue end (`ScanList.on_queue_stopped`) and the built-in `default_slack_notification` setter feed it. `capture.py` also renders the plot screenshot any scan-finished hook can ask for |
| `core/shift_compensation/` | Shift Compensation: mapping CSV loading and cosine/polynomial fits (`fitting.py`), mappings and the `compensated_source_`/`compensated_target_` scan channels (`logic.py`), set files (`persistence.py`) and the mapping-block window (`window.py`); see `documents/shift_compensation.md` |
| `core/channel_value_record.py` | Main-window last-value record of channels written/read through `write_info`/`read_info` and the scan setup snapshots; Shift Compensation's source-readback cache |
| `devices/` | Flat package namespace for device integrations; it performs no eager device imports |
| `devices/mockDevice/` | Hardware-independent simulator, three-layer reference device (including the reference `spectrum`/`frame` array getters), and tests |
| `devices/mfli/` | Maintained lazy `mfli` driver: worker-owned Zurich Core client, 25 scalar scan channels, global amplitude/DC ramping (10 V/s, 100 Hz), scan/monitor coordination, managed panel and standalone `MFLI_main.py`, pure address/interface helpers |
| `devices/andor/` | Lazy `andor` driver (pylablib): Andor SDK2 camera with optional Shamrock spectrograph; `spectrum` and `image` array getters, nm centre wavelength, bounded non-retried snaps, ported from the Mfork |
| `devices/auto_focus/`, `devices/auto_position/` | Routed focus search and fixed-reference map registration; separate worker/panels, settings contracts and optional/required run bundles |
| `devices/arduino_steppers/` | Standalone three-motor serial controller and maintained Arduino sketch; routed Z is selected by autofocus |
| `devices/attodry/`, `devices/mc2000b/`, `devices/spectraphysicsx3_laser/` | Lazy startup-only cryostat, chopper and laser integrations; device-local requirements and commissioning procedures |
| `devices/<device>/` | Device-specific widget/logic/hardware integrations, including driver-owned scan/monitor admission, and optional UI/dependencies |
| `zcore/`, `zcore/data/`, `zui/` | Empty packages for the v2 transition ([ADR 003](documents/decisions/003-v2-architecture.md)); not on the active runtime path. `zcore` holds Qt-free, hardware-free code (file formats in `zcore/data/`); `zui` holds the Qt interface. `zcore` never imports `PyQt6`, `core`, `devices`, or `zui` |
| `tests/` | Hardware-independent core regression tests, including `tests/test_layering.py` (import rules for `core/`, `zcore/` and the core device registry; left out of release ZIPs by `.gitattributes`) |
| `skills/` | Claude Code / Codex agent skills for zmeter work outside the app (`skills/README.md` lists them and how to install); `zmeter-shift-mapping` and `zmeter-scan-planner` |
| `documents/` | Canonical contracts, current status/readiness, guides, and decisions |
| `data/` | Default local measurement output; ignored by Git |
| `scan_range_limits.json` | Default global scan-output limit configuration |
| `zmeter_Sept2026_environment.yml` | Current Windows Conda environment, including openpyxl, Python.NET, and the pinned optional MFLI Core dependency |
| `archive/` | Retired documentation/code evidence; not current authority (left out of release ZIPs by `.gitattributes`) |

The standalone deployment installer is maintained in
`https://github.com/lictailer/zmeter-deploy`. ZMeter retains its release-
packaging workflow and the maintained contract in
`documents/release_deployment.md`.

## Device integration inventory

Source subpackages under `devices/` currently include `mockDevice`, `andor`, `nidaq`, `ni6423`, `keithley24xx`, `hp34401a`, `sr830`, `sr860`, `mfli`, `opticool`, `montana2`, `four9`, `tlpm`, `pem100`, `sp150`, `k10cr1`, `BBD30X`, `attodry`, `mc2000b`, `spectraphysicsx3_laser`, `arduino_steppers`, `auto_focus`, and `auto_position`. Presence does not establish hardware readiness; see `documents/device_status.md` and device-local READMEs. Legacy autofocus XZ and superseded prototypes live only under `archive/legacy-autofocus/`; the retired `demoDevice` simulator and the unregistered `ANC300` fragment live under `archive/legacy-devices/` (see `archive/README.md`). The `demo_device` driver ID stays registered as an unavailable driver (no device code is imported) so older workbooks that still contain the row keep loading; ADR 003 lists its removal at the end of phase 5. `BBD30X` retains its documented optional Kinesis lifecycle limitations.

The Phase 2 startup-only registry entries are `four9`, `montana2`, `opticool`,
`attodry`, `tlpm`, `mc2000b`, `spectraphysicsx3_laser`, `auto_focus`,
`auto_position` and `arduino_steppers`. They are lazy and selected only through the workbook; their device-local
READMEs and `documents/device_status.md` record environment-specific accepted
limitations.

Maintained VISA packages (`pem100`, `sp150`, `hp34401a`, `keithley24xx`,
`sr830`, and `sr860`) use `VisaRuntime`. K10CR1 and BBD30X use one injected `KinesisRuntime` and the same local
manifest-validated DLL directory. The hardware-free VISA runtime tests use the fake manager in `tests/fixtures/dummy_visa.py`, injected into `VisaRuntime` without patching PyVISA globally.

## Maintenance rule

Update this file when verified module ownership, import paths, entry points, or runtime relationships change. Keep behavioral details in the relevant canonical document and do not restore archived claims without code/test verification.

MFLI uses its own single Core API worker rather than VISA. Its maintained package
keeps address validation and connection helpers in `MFLI_hardware.py`, alongside
`MFLI_logic.py` and `MFLI_main.py`. Development demos and dedicated MFLI tests
remain on `MFLI_dev2.0` and are excluded from the release branch. The router
runs requests for this opt-in device in the background while holding a manager
session lease; the MFLI logic treats routed requests as manual panel work so the
scan gate applies. Integrated scan storage uses the existing channel schema.
