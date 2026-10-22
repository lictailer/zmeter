# MS laboratory-device integration

## Source and scope

Branch `MS/lab-devices-and-alignment` starts at upstream `v1.0-beta.4`, commit
`9106749104115ded0cf53c508c2878499446694d`, also the `release/beta` head when
compared on 2026-10-19. Changes were selected from the lab's `20261009` working
copy, including work outside the original device chat. That directory was not
overwritten or turned into a Git checkout.

The comparison excluded 250 files differing only in line endings, backup trees
(`core_a`, device `_a`/`_b` variants, `attodry0/1`), alternate workbooks,
measurement data, personal experiment settings, caches, editor files and the
generated deployment manifest. Each added driver has one maintained package.
No new vendor DLLs or licensed API wheels are included.

The exception to ignoring line-ending changes is two existing Kinesis XML
files. Their exact bytes were restored to match the existing manifest hashes.
`.gitattributes` preserves those bytes in checkouts and source/release archives;
the integrity checks and hashes were not relaxed.

## Changes relative to beta.4

| Area | Included changes |
| --- | --- |
| SP150 | Scan-facing wavelength path and empty-response handling with regression tests |
| TLPM | Synchronous scan wavelength setter, queued manual target, serialized power/wavelength access and panel updates |
| Keithley 24xx | Session-only NPLC control/readback for voltage and current, with panel changes |
| SR860 | Confirmed amplitude/DC ramp waypoints, configurable rates, separate target/readback controls, cooperative stop and output validation |
| NI-DAQ | Existing panel layout changes; no DAQ task implementation replaced |
| `mc2000b` | Explicit serial port, frequency/phase, start/stop/state and native inner/outer-wheel controls; no guessed blade-ratio conversion |
| `spectraphysicsx3_laser` | InSight X3 panel, state/readbacks, wavelength stability, shutter and manual diode controls; diode is not a scan channel |
| `arduino_steppers` | Three angle/step/speed interfaces and a host-tested Arduino sketch; motor counters are not independent position feedback |
| `attodry` | Lazy optional vendor API, sample-temperature and single-axis field channels, configurable stable waits and monitor coordination; missing active registration restored |
| `auto_focus` | Routed native/calibrated Z, scalar/raster/camera acquisition, adaptive/grid/sweep/Gaussian methods, plots and opt-in saved run bundles |
| `auto_position` | Reference maps/points, selectable translation registration, corrected-point scan trigger, saved comparisons and linked scan-range controls |
| Shared support | Checked coordinator routing, channel selectors and unique atomic run bundles; no owned hardware transports |

Exact channels, units, limits, stopping and bench procedures belong in the device
READMEs. Legacy XZ and superseded UI/position prototypes are retained once under
`archive/legacy-autofocus/`, outside the active device namespace. Earlier complete
implementations also remain in Git; they are not supported parallel devices.

## Configuration and compatibility

The workbook retains upstream beta.4 rows rather than importing the lab's renamed
devices, addresses and auto-connect selections. Six added rows are disabled with
`connect_on_start=FALSE`. Coordinator addresses are blank; COM ports are editable
examples, not discovery. Guide entries and table/check formulas include all
registered drivers. Runtime add/remove remains disabled for the new integrations.

Matching global attoDRY `T`, `T_stable`, `B` and `B_stable` limits are added without
changing existing global limits. They describe the lab's 9 T installation, not
every attoDRY system. Review controller limits/device ID before enabling a row.
Copy any required lab configuration deliberately; never overwrite an experiment
workbook as an incidental update step.

The scan engine, ordinary scan JSON and data/backup paths are unchanged.
TLPM's scan setter is now `wavelength` (nm), not the former queued
`wavelength_target` helper; update old scan channel selections accordingly.
SR860 `dc_level` readbacks now match its setter/panel in **mV**, rather than the
native query's volts; review old plot labels and analysis conversions.
Autofocus has its own schema-2 setup/result migration contract; auto-position
uses schema 1. Their run bundles are separate from ordinary scan JSON. Laser
hold-to-operate controls and intentional preservation of state on close remain.

The follow-up `auto_focus_run_key` and `auto_position_run_key` getters label each
attempt with its local start time (`YYYYMMDDhhmmss`). Add both to the innermost
measurement getters to link measurement rows with their saved coordinator bundles.
The numeric key is included in folder names and as additive `run.json` metadata;
existing files/settings and ordinary scan JSON are unchanged. Autofocus saving
remains opt-in. See the device READMEs for initial/failed-attempt behavior and
same-second timestamp limitations.

## Dependencies and installation

The existing Windows YAML already contains PySerial, scikit-image, SciPy and
Matplotlib. It now also pins `opencv-python-headless==4.13.0.92`, previously
missing for the camera autofocus option. Its Windows wheel resolves with the
existing NumPy 2.4.1 pin. The headless build avoids a second GUI toolkit; PyQt6
owns the interface. Do not install multiple OpenCV variants in one environment.
No duplicate device environments were added. Vendor OS drivers remain separate
prerequisites, and a full Windows Conda solve/install is still unverified.

attoDRY needs the vendor `atto_device` 1.12.0 wheel, historically named
`api_atto-device-python_1.0.12.whl`. It is not redistributed without permission.
Companion branch [`MS/optional-attodry-installation`](https://github.com/Mohamed-ShehabEldin/zmeter-deploy/tree/MS/optional-attodry-installation)
in the contributor's fork of `lictailer/zmeter-deploy`
adds explicit opt-in, local discovery/path entry, SHA-256 checks, standards-
compliant filename staging and installation into the exact release environment.
Users without attoDRY can skip it. The optional pip step uses no index/dependency
resolution and does not load the API or contact a controller.

This branch is **not a published release**. The release-only installer must not
misrepresent a moving branch/source ZIP as a verified package. Maintainers must
publish a reviewed release using the existing packaging workflow before the
installer can select these application changes. No release/tag/default branch
is changed by this contribution.

To obtain the development branch on another computer:

```powershell
git clone --branch MS/lab-devices-and-alignment --single-branch https://github.com/lictailer/zmeter.git zmeter-MS
cd zmeter-MS
conda env create --name zmeter-MS-lab --file zmeter_Sept2026_environment.yml
conda activate zmeter-MS-lab
```

Review the workbook before launch. For attoDRY in an unpublished development
checkout, follow its README's deliberate local-wheel procedure; the release-only
installer cannot identify that development environment.

## Validation boundary

Checks use fake serial/VISA/vendor APIs, synthetic maps/signals, offscreen Qt,
temporary output directories and a host-compiled Arduino sketch with fake I/O.
No laboratory device is discovered, connected, moved, read, written, reset or
disconnected by the agent. Tests ran on macOS with Python 3.12.14 and offscreen
Qt, with serial/VISA constructors guarded against accidental real I/O. Windows
COM imports used test stubs, not native Windows automation.

| Check | Result |
| --- | --- |
| Root `tests/test_*.py` discovery | 339 passed |
| Autofocus, auto-position, Arduino, attoDRY, chopper, laser and SP150 device suites | 154 passed, 11 skipped (alternative no-Qt fallback cases) |
| Companion installer offline tests | 14 passed |
| Active application Python compilation / device UI XML parsing | 205 Python files / 16 UI files passed |
| Arduino sketch host compilation | Passed with fake Stepper/serial I/O; not an Arduino-board build |
| Workbook | Existing configuration preserved; added rows, Guide, formulas and table checked; added rows visually reviewed |
| Windows OpenCV/NumPy wheel resolution | Pinned wheels resolve together; no installation performed |

The root and device suites use Python's `unittest` runner. Reproduce in a
development environment with laboratory transports physically unavailable;
the session's temporary guard wrapper is not a production dependency:

```sh
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -p 'test_*.py'
QT_QPA_PLATFORM=offscreen python -m unittest devices.auto_focus.tests.test_autofocus devices.auto_position.tests.test_position devices.arduino_steppers.tests.test_steppers devices.arduino_steppers.tests.test_firmware devices.attodry.tests.test_attodry devices.mc2000b.tests.test_mc2000b devices.spectraphysicsx3_laser.tests.test_spectraphysicsx3_laser devices.sp150.tests.test_sp150
# In the companion installer repository:
python -m unittest discover -s tests -p 'test_*.py'
```

The full application suite needs its platform dependencies (including Windows
COM support on Windows). The dependency-only Windows check used:

```sh
python -m pip install --dry-run --ignore-installed --only-binary=:all: --platform win_amd64 --python-version 3.12 opencv-python-headless==4.13.0.92 numpy==2.4.1
```

Windows/Conda deployment, native vendor drivers, Arduino IDE upload, instrument
timing, optical polarity, laser interlocks and magnet commissioning remain
user-executed hardware tests using device-local checklists. Mocks do not certify
those outcomes.
