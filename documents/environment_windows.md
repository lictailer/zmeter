# Windows Environment

## Canonical environment

ZMeter targets 64-bit Windows. The maintained environment is `zmeter_May2026_environment.yml`, which defines `zmeter_May2026` with Python 3.12.12. `zmeter_Mar2026_environment.yml` is an older snapshot and is not the default for a new setup.

Create and activate from a Conda-enabled PowerShell or prompt:

```powershell
conda env create -f zmeter_May2026_environment.yml
conda activate zmeter_May2026
python --version
python -c "import sys; print(sys.executable)"
```

Update an existing environment deliberately:

```powershell
conda env update -f zmeter_May2026_environment.yml --prune
conda activate zmeter_May2026
```

Run ZMeter and validation from the repository root because several Qt Designer files use repository-relative paths.

## Python packages versus system software

The YAML supplies core Python dependencies such as PyQt6, NumPy, SciPy, PyVISA, NI-DAQmx Python bindings, PyDAQmx, PyQtGraph, `python-pptx`, Pillow, `pywin32`, serial, SSH, and scientific utilities. A Python package does not install or validate the corresponding instrument driver.

System-installed components are lab/device specific:

| Component | Needed for | Notes |
| --- | --- | --- |
| NI-VISA and adapter driver | VISA/GPIB/USB/serial/LAN instruments | Match Windows, adapter, architecture, and vendor requirements |
| NI-DAQmx runtime/driver | NI DAQ integrations | Python binding alone is insufficient |
| Vendor SDK/runtime/DLL | Thorlabs, cryostat, motion, and other vendor modules | Confirm supported model, bitness, DLL search path, and redistribution terms |
| Desktop Microsoft PowerPoint | PPT export | ZMeter uses Windows COM through `win32com`; web-only PowerPoint is insufficient |

Install only the components required by the selected lab profile. Device-local README files must record their exact optional dependencies.

## Mock-only setup

No instrument driver is required for the checked-in mock profile. Verify `start_zmeter.py` imports/instantiates only `MockDevice`, leave real-device connection code disabled, then run:

```powershell
python start_zmeter.py
```

The mock device is an in-process simulator and does not use PyVISA or discover physical resources. Save test output only to a disposable local directory.

## Configuration and paths

The current startup profile is `start_zmeter.py`. It controls registered device labels, constructors, optional channel filters, local save path, and backup root. Real addresses, serial numbers, NI names, credentials, and lab paths must remain in profile/configuration boundaries and must not be generalized into core code or canonical docs.

`scan_range_limits.json` is loaded from the repository root by default. UI files are loaded relative to the current working directory. The environment YAML contains a machine-specific exported `prefix`; Conda normally creates the named environment from `name`, and maintainers should review/remove hardcoded export prefixes when regenerating the file.

Shared Kinesis does not use an environment variable, global `PATH` mutation,
Program Files fallback, or device-local DLL search. Populate the ignored
`core/shared_runtime/vendor/thorlabs_kinesis/` directory from one matching
reviewed 64-bit release and keep its tracked manifest synchronized. Other
vendor families remain device-specific until a separate typed adapter is
approved. Do not copy a DLL until origin, architecture, loading rule, and
licensing are understood.

## PowerPoint/COM

PPT export uses Qt screen captures and Windows COM. Confirm:

- desktop PowerPoint is installed and can open the target presentation;
- `pywin32` imports in the active environment;
- the target path is writable and no modal PowerPoint dialog is blocking automation;
- UI execution is available—offscreen/headless validation does not prove COM or screen capture behavior.

JSON saving is separate. If PPT export fails, preserve and verify the JSON result rather than assuming both failed or succeeded.

## Common diagnostics

### Python module missing

```powershell
conda activate zmeter_May2026
python -c "import sys; print(sys.executable)"
python --version
```

Update from the YAML before installing ad hoc packages. A plain system Python may be 3.12 yet still lack PyQt6 and all project dependencies.

### UI file missing

Run from the repository root. Verify the referenced `.ui` path exists; do not work around it with a machine-specific absolute path.

### Driver/vendor import failure

Separate these questions: Is the Python package installed? Is the system driver/SDK installed? Are both the same architecture? Is the DLL/resource path correct? Is the enabled device actually needed for this profile? Keep optional imports guarded so unrelated mock-only operation remains possible.

### VISA/NI resource missing

The user should verify the resource with vendor/NI tooling, driver compatibility, and exact configured address. Agents must not run resource enumeration, discovery, connection, or probing commands.

### PowerPoint export failure

Verify desktop PowerPoint, `pywin32`, write permission, existing file locks, and modal dialogs. Use temporary copies for diagnostics; never overwrite measurement logs casually.

## Environment-change policy

Dependency and driver changes can destabilize multiple labs. Make the smallest justified change, explain why each new dependency is needed, verify mock-only startup and hardware-independent tests, and update the root README, this file, affected device README, and environment manifest together. Real-driver validation remains a user-executed hardware test.

