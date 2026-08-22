# ZMeter Technical Documentation

This directory contains current repository-wide contracts, status pages, and
maintainer guides. Executable code and tests remain authoritative for what runs.
Device-specific dependencies, channels, limits, and bench procedures belong in
the device package README. Completed plans and investigations live under
`archive/` and are historical evidence only.

## Reading routes

| Need | Read first | Then inspect |
| --- | --- | --- |
| Understand the completed reconstruction and remaining release gates | [reconstruction_status.md](reconstruction_status.md) | [ADR 002](decisions/002-profile-driven-device-management-reconstruction.md), `project_structure.md` |
| Understand ownership, startup, catalogs, or shutdown | [architecture.md](architecture.md) | `start_zmeter.py`, affected modules and tests |
| Check device registration or readiness | [device_status.md](device_status.md) | [device contract](device_contract.md), target device README, local profile |
| Review incomplete or partially available behavior | [known_issues.md](known_issues.md) | affected canonical document, code, and tests |
| Change shared vendor runtimes | [ADR 001](decisions/001-shared-runtime-services.md) | [shared runtime README](../core/shared_runtime/README.md), manifest, device hardware layer |
| Change scan traversal, timing, or getters | [scan_engine.md](scan_engine.md) | `core/scan.py`, `core/scan_logic.py`, focused tests |
| Change save, load, autosave, backup, or PPT | [data_format.md](data_format.md) | loaders and isolated round-trip tests |
| Change limits, ramps, stop, abort, or hardware-facing shutdown | [hardware_safety.md](hardware_safety.md) | target device README and affected logic/hardware tests |
| Run validation | [testing.md](testing.md) | affected hardware-independent tests |
| Configure Windows or dependencies | [environment_windows.md](environment_windows.md) | environment YAML and optional runtime documentation |
| Install a published release | [release_deployment.md](release_deployment.md) | standalone installer repository and release workflow |
| Record a durable design choice | [decisions/README.md](decisions/README.md) | affected code, tests, and canonical contracts |

## Current documents

| Document | Maintained purpose |
| --- | --- |
| [reconstruction_status.md](reconstruction_status.md) | Completed reconstruction outcome and remaining release/validation gates |
| [device_status.md](device_status.md) | Registered, startup-only, runtime-mutable, and unregistered device readiness |
| [known_issues.md](known_issues.md) | Confirmed partial behavior, safe workarounds, future fixes, and closure evidence |
| [architecture.md](architecture.md) | Repository-wide runtime architecture and ownership |
| [device_contract.md](device_contract.md) | Device integration and lifecycle contract |
| [scan_engine.md](scan_engine.md) | Scalar scan traversal and runtime contract |
| [data_format.md](data_format.md) | Persisted data, autosave, backup, and output contract |
| [hardware_safety.md](hardware_safety.md) | Hardware-safety and user-executed validation boundary |
| [testing.md](testing.md) | Validation levels and safe commands |
| [environment_windows.md](environment_windows.md) | Windows environment and system prerequisites |
| [release_deployment.md](release_deployment.md) | Published-release installer and packaging boundary |
| [CODEX_CONTRIBUTION_WORKFLOW_TUTORIAL.md](CODEX_CONTRIBUTION_WORKFLOW_TUTORIAL.md) | Maintainer documentation workflow guide |
| [decisions/](decisions/README.md) | Durable architecture decisions |

## Device documentation

The complete readiness matrix is in [device_status.md](device_status.md).
Device-local READMEs remain authoritative for source-verified details and do not
certify hardware compatibility. Start from the matrix rather than inferring
readiness from package presence.

## Historical material

[archive/README.md](../archive/README.md) indexes preserved documentation
snapshots and the completed reconstruction evidence. Archived text may contain
superseded paths, intermediate states, or unverified lab-specific claims. Never
use it as current implementation authority without re-verification.
