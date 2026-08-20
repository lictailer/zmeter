# ZMeter

ZMeter is a Windows desktop application for coordinating nested physics measurements across multiple laboratory instruments. It provides a PyQt6 interface for defining scan levels, setting device channels, reading measurements, plotting results live, queuing scans, and preserving results as JSON and PowerPoint logs.

The project is used by a small number of laboratories and maintained by a small team. Stability, recoverable data, understandable configuration, and safe equipment behavior take priority over rapid feature expansion.

## What ZMeter does

- Builds multi-level nested scans in which higher-numbered levels change more slowly than lower-numbered levels.
- Discovers scan-facing device getters and setters through each device's logic layer.
- Supports linear and explicit setting sequences, multi-setter patterns, settle delays, one-time start waits, and manual actions before or after a scan level.
- Groups device operations during scan execution while keeping the Qt interface responsive.
- Displays configurable line and image plots during acquisition.
- Queues scans and manual set operations for sequential execution.
- Supports pause, resume, clean stop, force-stop propagation, range checks, progress estimates, and scan logging.
- Saves complete scan configuration and acquired data to JSON.
- Appends scan summaries and plot captures to PowerPoint through Windows COM.
- Creates hourly `autosave.json` snapshots during long scans and can copy output to a configured backup location.
- Includes a deterministic mock instrument with simulated channels, ramps, faults, range rejection, and command logging.

## Platform and prerequisites

ZMeter currently targets 64-bit Windows. The maintained environment file pins Python 3.12 and the main Python dependencies, including PyQt6, NumPy, SciPy, PyVISA, NI-DAQmx Python support, `python-pptx`, and `pywin32`.

Required for the mock-only setup:

- 64-bit Windows;
- [Git for Windows](https://git-scm.com/install/windows);
- Conda through [Miniconda, Anaconda, or Miniforge](https://docs.conda.io/projects/conda/en/stable/user-guide/install/windows.html).

Optional components depend on the selected laboratory equipment:

- [NI-VISA](https://www.ni.com/en/support/downloads/drivers/download.ni-visa.html) for VISA resources such as GPIB, serial, USB, or Ethernet instruments;
- [NI-DAQmx](https://www.ni.com/en/support/downloads/drivers/download.ni-daq-mx.html/) for supported NI data-acquisition devices;
- the correct driver for the laboratory's GPIB/USB adapter;
- vendor runtimes for device-specific modules such as Thorlabs or cryostat controllers;
- desktop Microsoft PowerPoint for PPT export; the implementation controls PowerPoint through `win32com`.

Do not install every vendor package by default. Start with the mock configuration, then add only the drivers required by the intended laboratory profile after checking device, driver, Windows, and Python compatibility.

Maintained VISA devices share one lazy `VisaRuntime` manager while retaining
exclusive instrument sessions. K10CR1 and BBD30X share one lazy,
manifest-validated `KinesisRuntime`. The shared Kinesis vendor binaries live in
the tracked `core/shared_runtime/vendor/thorlabs_kinesis/` folder; see its README
before enabling either motion device.

## Installation

Open **Anaconda Prompt**, **Miniconda Prompt**, or a PowerShell session where `conda` is available.

### 1. Clone the repository

```powershell
git clone https://github.com/lictailer/zmeter.git
cd zmeter
```

All launch and validation commands should be run from the repository root because several UI paths are repository-relative.

### 2. Create the maintained environment

```powershell
conda env create -f zmeter_May2026_environment.yml
conda activate zmeter_May2026
```

The older `zmeter_Mar2026_environment.yml` is retained as an earlier environment snapshot. Use the May file for a new setup unless the maintainers designate a newer canonical environment.

For an existing environment after the YAML changes:

```powershell
conda env update -f zmeter_May2026_environment.yml --prune
conda activate zmeter_May2026
```

Confirm that the intended interpreter is active without importing device modules:

```powershell
python --version
python -c "import sys; print(sys.executable)"
```

The expected Python series is 3.12; the current environment file pins Python 3.12.12.

## Safe first launch with mock devices

The following procedure exercises only the simulated devices in the checked-in default profile.

1. Review `config/profiles/mock.json` and confirm that it enables only the two `mock_device` entries with `connect_on_start` set to `false`.
2. Activate `zmeter_May2026`.
3. From the repository root, launch:

   ```powershell
   python start_zmeter.py
   ```

4. In each mock-device window, keep the default mock address and click **Connect**.
5. Use the Scan List window to create a scan. Select mock-device setter/getter channels, use a small number of points, and configure a line plot if desired.
6. Save test output only under a disposable local directory. Do not point a mock run at a laboratory measurement or backup folder.
7. Close ZMeter through the main window so the normal stop and cleanup path runs.

The mock device offers direct and ramped A/B setters, A/B and random getters, deterministic fault injection, optional range rejection, and a bounded command log. It does not use PyVISA or communicate with physical equipment.

To select a different reviewed local profile, pass its repository-relative or absolute path explicitly:

```powershell
python start_zmeter.py --profile config/profiles/my-lab.local.json
```

An invalid selected profile fails visibly and is never replaced silently with the mock profile.

## Configuring a laboratory setup

Session configuration is selected by a validated JSON profile. It includes:

- stable labels for each device instance;
- reviewed registry driver IDs and declared connection fields;
- whether an enabled device may connect during startup;
- optional setter/getter channel filters;
- local measurement and backup paths.

`start_zmeter.py` contains no device imports, addresses, serials, or channel lists. A driver must have a reviewed code-side registry entry before a profile can select it. Disabled entries never construct or connect a device. The checked-in default profile still enables only the hardware-safe `mock_device` path. The registry also recognizes the startup-only Phase 1 IDs `ni6423`, `nidaq`, `pem100`, `sp150`, `hp34401a`, `keithley24xx`, `sr860`, `sr830`, `demo_device`, `bbd30x`, and `k10cr1`; real devices require an ignored local profile and user-executed commissioning.

Runtime device changes are session-only and do not rewrite the selected JSON
profile. The manager can add, disconnect, or remove only a driver whose
registration explicitly opts into runtime mutation and provides a reviewed
busy-state probe; the checked-in registry currently grants that capability only
to `mock_device`. A change is refused while a scan, queue, manual operation,
router request, device call, or device-owned job is active, or while a stored
scan/manual/artificial configuration still references a device proposed for
removal. Successful changes rebuild device buttons and every channel/catalog
consumer together. A removed device's older callable handles fail closed, and
the next launch still uses the unchanged profile.

Before enabling hardware:

1. Copy `config/profiles/example_lab.json` to an ignored `*.local.json` profile without changing the checked-in mock default.
2. Confirm the exact instrument model, interface, address, units, limits, and required vendor runtime.
3. Verify that each enabled device implements coherent connect, scan start/stop, force-stop, disconnect, termination, and close behavior.
4. Review `scan_range_limits.json` and ensure its device labels match the configured equipment labels.
5. Keep addresses, serial numbers, and lab paths out of shared core modules.
6. Have the user review and execute a controlled bench procedure before relying on the configuration for measurements.

Real-hardware operation and validation must be performed directly by the user. Coding agents may prepare code and an exact proposed procedure, but must never execute commands that discover, connect to, configure, move, source, trigger, write to, reset, disconnect, or otherwise affect laboratory instruments.

## Instrument integrations in the repository

The flat `devices/` package contains integrations or experimental work for several equipment families:

| Area | Modules present |
| --- | --- |
| Simulation | `mockDevice`, `demoDevice` |
| NI data acquisition | `nidaq`, `ni6423` |
| Source meters and multimeters | `keithley24xx`, `hp34401a` |
| Lock-in amplifiers | `sr830` (official maintained implementation), `sr860` |
| Cryostats/environment control | `opticool`, `montana2`, `four9` |
| Optical power, modulation, spectroscopy, and motion | `tlpm`, `pem100`, `sp150`, `k10cr1`, `BBD30X` |
| Positioning/autofocus | `auto_focus`, `auto_position`, `autofocus_xuguo`, `ANC300` |

Treat this as a source inventory, not a compatibility or validation matrix. Check the current module, its dependencies, and its lifecycle behavior before selecting it for a lab profile.

## Measurement workflow

A typical operator workflow is:

1. Start ZMeter with the intended equipment profile.
2. Confirm device connection state and safe initial values.
3. Open or create a scan in the Scan List window.
4. Add scan levels. `level0` is the innermost/fastest level; higher-numbered levels form slower outer loops.
5. Assign setters, destinations, getters, timing, and optional manual before/after actions.
6. Configure line or image plots.
7. Review point count, ranges, units, output paths, stop behavior, and backup state.
8. Start the scan and monitor progress and the scan log.
9. Stop safely if device state, data, or limits are unexpected.
10. Confirm that JSON and any requested PPT/backup output were written successfully before changing the setup.

Do not assume a software test proves hardware behavior. Every real setup needs a user-executed bench validation appropriate to the instruments and experiment.

## Data and output behavior

The default local save directory is `data/`.

- JSON filenames begin with a four-digit serial and scan name, for example `0007_gate_sweep.json`.
- Existing names receive a numeric suffix rather than being overwritten.
- JSON stores the scan configuration, setting arrays, acquired data, plot settings, comments, and scan log.
- NumPy arrays are serialized as lists. Current files may contain Python JSON's unquoted `NaN` literal; the loader also accepts the exact string `"NaN"`. See `documents/data_format.md` before changing this compatibility-sensitive representation.
- Long scans overwrite `autosave.json` in the current save directory at each hourly autosave trigger.
- The default PPT path is `data/log.pptx`. PPT output requires desktop PowerPoint and may open it visibly.
- External backup is disabled in the checked-in startup. Current backup handling expects the configured lab backup location and checks for `Z:\` before copying; verify the mapped drive and destination before a measurement.

Measurement JSON, PPT files, autosaves, logs, and temporary captures should not be committed to source control.

## Hardware-independent validation

Run validation only after confirming that the selected command, imports, fixtures, and setup cannot access instruments.

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m unittest discover -s devices/mockDevice/tests -p "test_*.py" -v
```

For changed Python files:

```powershell
python -B -m py_compile <changed-file-1.py> <changed-file-2.py>
```

These checks provide static, unit, mock/simulation, or offscreen-GUI evidence only. They do not validate physical instruments.

## Project layout

```text
start_zmeter.py                 Thin profile-selecting application entry point
config/profiles/                Checked mock profile and ignored local-profile boundary
core/                           Scan UI, queue, execution, plotting, routing, and persistence
core/device_management/         Profile loading, reviewed registry, manager ownership
core/shared_runtime/            Shared VISA/Kinesis ownership and local vendor manifests
devices/                        Flat package namespace for device integrations
devices/mockDevice/             Hardware-independent simulated instrument and its tests
devices/<device>/               Device-specific widget, logic, hardware, and UI files
tests/                          Hardware-independent core regression tests
data/                           Default local measurement output
scan_range_limits.json          Configured scan-output limits
zmeter_May2026_environment.yml  Maintained Conda environment
project_structure.md            Authoritative maintained structure documentation
AGENTS.md                       Coding-agent policy and safety instructions
archive/                        Historical documentation and retired material
```

See `project_structure.md` for the maintained structural reference. Executable code and tests remain authoritative for what actually runs.

## Troubleshooting

### `ModuleNotFoundError` for PyQt6, NumPy, PyVISA, or another dependency

Confirm that `zmeter_May2026` is active and that `python -c "import sys; print(sys.executable)"` points into that environment. Update the environment from the YAML rather than installing isolated packages until the dependency difference is understood.

### A `.ui` file cannot be found

Launch `python start_zmeter.py` from the repository root. Several UI files are loaded with repository-relative paths.

### PowerPoint export fails

Confirm that desktop Microsoft PowerPoint and `pywin32` are available, that the target presentation is writable, and that no modal PowerPoint dialog is blocking COM automation. JSON saving is separate; confirm the JSON result even if PPT export fails.

### VISA or GPIB equipment is missing

The user should confirm the correct NI-VISA and adapter drivers, inspect the resource in NI Measurement & Automation Explorer, and verify the configured address. Do not repeatedly probe an unknown resource from ZMeter.

### NI-DAQ equipment is missing

The user should verify the installed NI-DAQmx version, device support, Windows recognition, and the configured NI device name before launching a hardware profile.

### Data saves locally but not to backup

Check the backup field, mapped drive availability, permissions, and the current `Z:\` requirement. Treat local JSON as the primary recovery artifact until the backup copy is confirmed.

### The GUI freezes or shutdown hangs

Record the active device, operation, and whether a scan or monitor was running. Avoid forcing new commands into an uncertain device state. Use the intended stop/force-stop path, then have the user verify instrument state directly.

## Contributing and maintenance

Before changing the project:

1. Read `AGENTS.md` for engineering, safety, validation, and reporting policy.
2. Read `project_structure.md` and trace the current executable path in code.
3. Preserve pre-existing working-tree changes.
4. Keep hardware I/O in hardware layers, scan coordination in logic, and UI behavior in widgets.
5. Prefer focused, understandable changes and hardware-independent regression coverage.
6. Update maintained documentation when setup, structure, channels, data formats, workflows, limits, or lifecycle behavior changes.
7. Report what was tested, what was not tested, and the user-executed hardware-validation status.

Historical documents are indexed in `archive/README.md`. They are evidence only and may contain stale or lab-specific information.

## License

No license file is currently present in the repository. Do not assume permission for external redistribution, especially for vendor binaries or proprietary SDK components, until the maintainers add an explicit license and confirm third-party terms.
