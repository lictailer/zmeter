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

## One-click release environments

Download the standalone installer repository linked from the root README, double-click `deploy_zmeter.py`, and choose **Set up Python environment** to create or update the environment belonging to a published release. The tool locates Conda even when it is not on `PATH`, verifies the release ZIP, manifest, tagged commit, and YAML hash, and derives an isolated name such as `zmeter-v1.0` or `zmeter-v1.0-beta.3`.

After the exact `Y` confirmation, new environments use `conda env create --name <name> --file <yaml>`. Existing environments use `conda env update --name <name> --file <yaml> --prune`. Conda output and prompts remain visible in the popup terminal. The exported YAML's `name:` or `prefix:` does not select the destination because `--name` is always explicit.

The installer does not activate the environment, install Windows drivers or vendor runtimes, launch ZMeter, or validate hardware. If Conda fails or is interrupted, review its visible output and the named environment; the tool does not claim rollback or automatically delete it.

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

No instrument driver is required for the checked-in mock profile. Verify `config/profiles/mock.json` enables only the two `mock_device` entries with startup connection disabled, then run:

```powershell
python start_zmeter.py
```

The mock device is an in-process simulator and does not use PyVISA or discover physical resources. Save test output only to a disposable local directory.

## Configuration and paths

The default startup profile is `config/profiles/mock.json`. Select an ignored reviewed local profile with `python start_zmeter.py --profile config/profiles/name.local.json`. Relative profile filenames and configured output paths resolve from the repository root. An invalid selected profile fails without falling back to the mock profile.

Profiles control registered device labels, declared connection values, startup-connection policy, optional channel filters, local save path, and backup root. A code-reviewed registry entry controls actual construction, runtime injection, and lifecycle adaptation; disabled entries are never constructed. Real addresses, serial numbers, NI names, credentials, and lab paths must remain in ignored local profiles and must not be generalized into core code or canonical docs.

`scan_range_limits.json` is loaded from the repository root by default. Core UI files retain their repository/current-working-directory lookup, while device-package UI files resolve relative to their Python modules under `devices/`. The environment YAML contains a machine-specific exported `prefix`; Conda normally creates the named environment from `name`, and maintainers should review/remove hardcoded export prefixes when regenerating the file.

Shared Kinesis does not use an environment variable, global `PATH` mutation,
Program Files fallback, or device-local DLL search. The tracked
`core/shared_runtime/vendor/thorlabs_kinesis/` directory and manifest must come
from one matching reviewed 64-bit release and remain synchronized. Other
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

