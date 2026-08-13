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

The following procedure exercises only the simulated devices in the current startup configuration.

1. Review `start_zmeter.py` and confirm that only `MockDevice` imports and instances are active. Real instrument imports and connection calls must remain commented for this first launch.
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

## Configuring a laboratory setup

Laboratory equipment is currently selected in `start_zmeter.py`. Configuration includes:

- imports for the device widgets used in that setup;
- stable labels for each device instance;
- connection calls and addresses or serial numbers;
- optional setter/getter channel filters;
- local measurement and backup paths.

Before enabling hardware:

1. Create or update a laboratory-specific startup/profile change without deleting the mock setup.
2. Confirm the exact instrument model, interface, address, units, limits, and required vendor runtime.
3. Verify that each enabled device implements coherent connect, scan start/stop, force-stop, disconnect, termination, and close behavior.
4. Review `scan_range_limits.json` and ensure its device labels match the configured equipment labels.
5. Keep addresses, serial numbers, and lab paths out of shared core modules.
6. Have the user review and execute a controlled bench procedure before relying on the configuration for measurements.

Real-hardware operation and validation must be performed directly by the user. Coding agents may prepare code and an exact proposed procedure, but must never execute commands that discover, connect to, configure, move, source, trigger, write to, reset, disconnect, or otherwise affect laboratory instruments.

## Instrument integrations in the repository

The source tree contains integrations or experimental work for several equipment families:

| Area | Modules present |
| --- | --- |
| Simulation | `mockDevice`, `demoDevice` |
| NI data acquisition | `nidaq`, `ni6423` |
| Source meters and multimeters | `keithley24xx`, `hp34401a` |
| Lock-in amplifiers | `sr830`, `sr830_v2`, `sr860` |
| Cryostats/environment control | `opticool`, `montana2` |
| Optical power and motion | `tlpm`, `k10cr1` |
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
python -B -m unittest discover -s mockDevice/tests -p "test_*.py" -v
```

For changed Python files:

```powershell
python -B -m py_compile <changed-file-1.py> <changed-file-2.py>
```

These checks provide static, unit, mock/simulation, or offscreen-GUI evidence only. They do not validate physical instruments.

## Project layout

```text
start_zmeter.py                 Startup configuration and application entry point
core/                           Scan UI, queue, execution, plotting, routing, and persistence
mockDevice/                     Hardware-independent simulated instrument and its tests
<device>/                       Device-specific widget, logic, hardware, and UI files
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
