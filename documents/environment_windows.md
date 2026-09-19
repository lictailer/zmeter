# Windows Environment

## Canonical environment

ZMeter targets 64-bit Windows. The maintained environment is `zmeter_Sept2026_environment.yml`, which defines `zmeter_Aug2026` with Python 3.12.12. It includes `zhinst-core==26.7.1.4` for the optional MFLI driver; Zurich Toolkit and Utils are not required.

Create and activate from a Conda-enabled PowerShell or prompt:

```powershell
conda env create -f zmeter_Sept2026_environment.yml
conda activate zmeter_Aug2026
python --version
python -c "import sys; print(sys.executable)"
```

Update an existing environment deliberately:

```powershell
conda env update -f zmeter_Sept2026_environment.yml --prune
conda activate zmeter_Aug2026
```

## Workbook and .NET dependencies

The September YAML explicitly includes `openpyxl=3.1.5` (Conda) and
`pythonnet==3.0.5` (pip). Openpyxl was already present; Python.NET was missing
and is now added. Do not install a separate package named `clr`: Python.NET
provides that import. Its `clr-loader` dependency is resolved by pip. The
manifest retains its exported environment name `zmeter_Aug2026`; use an explicit
`--name` when updating a release-named environment.

[Python.NET 3.0.5](https://pypi.org/project/pythonnet/3.0.5/) declares Python 3.12
support. [Openpyxl 3.1.5](https://pypi.org/project/openpyxl/3.1.5/) handles the
Excel configuration. Python.NET does not supply the instrument vendor DLLs or
Windows .NET runtime; those remain device-specific prerequisites.

For a user whose existing environment lacks these packages, activate that
ZMeter environment and apply the updated YAML to its actual name. Confirm the
interpreter before checking the installed packages:

```powershell
python -c "import sys; from importlib.metadata import version; print(sys.executable); print('openpyxl', version('openpyxl')); print('pythonnet', version('pythonnet'))"
```

### Release cleanup validation (2026-09-19)

On `MFLI_dev2.0_pr`, the MFLI development folder and its two dedicated root test
files were removed from release paths. They remain on `MFLI_dev2.0`; an ignored
local backup is under `.restructure_tmp/mfli_release_cleanup`. Documentation was
updated to use the maintained standalone launcher and September YAML. All
retained executable Python, routing/registration code, and `device_config.xlsx`
were verified unchanged against the starting commit. This changes release
contents and dependency declarations, not device behavior or measurement formats.

The YAML parsed successfully with both dependencies present. The existing
selected environment already has openpyxl 3.1.5 but lacks Python.NET.
`pip install --dry-run --only-binary=:all: pythonnet==3.0.5 openpyxl==3.1.5`
could not resolve Python.NET in this execution environment, including an
isolated retry with an explicit PyPI index. No packages were installed and no
fresh-environment installation is claimed; test the YAML on the target machine.

Offline `python -B -m unittest discover -s tests -p 'test_*.py' -v` ran 326 tests:
323 passed and three existing `test_device_config_workbook` checks failed on
changed row order, flags, and cached status expectations. Those tests and the
workbook were left untouched. No hardware was accessed. Logs and the dependency
preview output are in the ignored cleanup directory.

## One-click release environments

Download the standalone installer repository linked from the root README and [release_deployment.md](release_deployment.md), double-click `deploy_zmeter.py`, and choose **Set up Python environment** to create or update the environment belonging to a published release. The tool locates Conda even when it is not on `PATH`, verifies the release ZIP, manifest, tagged commit, and YAML hash, and derives an isolated name such as `zmeter-v1.0` or `zmeter-v1.0-beta.3`.

After the exact `Y` confirmation, new environments use `conda env create --name <name> --file <yaml>`. Existing environments use `conda env update --name <name> --file <yaml> --prune`. Conda output and prompts remain visible in the popup terminal. The exported YAML's `name:` or `prefix:` does not select the destination because `--name` is always explicit.

The installer does not activate the environment, install Windows drivers or vendor runtimes, launch ZMeter, or validate hardware. If Conda fails or is interrupted, review its visible output and the named environment; the tool does not claim rollback or automatically delete it.

Run ZMeter and validation from the repository root because several Qt Designer files use repository-relative paths.

## Python packages versus system software

The YAML supplies core Python dependencies such as PyQt6, NumPy, SciPy, PyVISA, NI-DAQmx Python bindings, PyDAQmx, PyQtGraph, `openpyxl`, `python-pptx`, Pillow, `pywin32`, serial, SSH, and scientific utilities. A Python package does not install or validate the corresponding instrument driver.

System-installed components are lab/device specific:

| Component | Needed for | Notes |
| --- | --- | --- |
| NI-VISA and adapter driver | VISA/GPIB/USB/serial/LAN instruments | Match Windows, adapter, architecture, and vendor requirements |
| NI-DAQmx runtime/driver | NI DAQ integrations | Python binding alone is insufficient |
| Vendor SDK/runtime/DLL | Thorlabs, cryostat, motion, and other vendor modules | Confirm supported model, bitness, DLL search path, and redistribution terms |
| Desktop Microsoft PowerPoint | PPT export | ZMeter uses Windows COM through `win32com`; web-only PowerPoint is insufficient |

Install only the components required by the selected workbook configuration. Device-local README files must record their exact optional dependencies.

## Launch configuration

Review the root `device_config.xlsx` workbook, including every `enabled` and `connect_on_start` value, then run:

```powershell
python start_zmeter.py
```

## Configuration and paths

The default startup configuration is the root `device_config.xlsx`. Select another reviewed Excel workbook with `python start_zmeter.py --profile name.xlsx`. Relative workbook filenames resolve from the repository root. An invalid selected workbook fails without falling back to the default.

The workbook controls registered device labels, one text address per device, startup-connection policy, and optional channel filters. A code-reviewed registry entry controls actual construction, runtime injection, and lifecycle adaptation; disabled entries are never constructed. Initial data and PPT paths are `<repository>/data` and `<repository>/data/log.pptx`, with backup initially blank; the Main Window fields remain editable for the current session.

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

Current PowerPoint/COM validation status is recorded in
[known_issues.md](known_issues.md).

JSON saving is separate. If PPT export fails, preserve and verify the JSON result rather than assuming both failed or succeeded.

## Common diagnostics

### Python module missing

```powershell
conda activate zmeter_Aug2026
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

