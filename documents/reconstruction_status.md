# Reconstruction Status

## Current state

The behavior-preserving reconstruction is implemented. It was merged into
`release/beta` by commit `574b186` and is present in the maintained beta line.
The active architecture now uses validated profiles, a lazy driver registry,
manager-owned devices and shared runtimes, transactional catalogs, guarded
session-only runtime mutation, the flat `devices/` namespace, and the Main
Window System Log.

The checked default remains the disconnected mock profile. Real-device entries
in tracked Phase 1 and Phase 2 profile templates remain disabled and keep
`connect_on_start=false`.

## Completed reconstruction work

- Profile validation, repository-relative path handling, and strict selection
  without fallback.
- Lazy driver registration and best-effort ordered startup construction and
  connection requests.
- Manager ownership, lifecycle ordering, shared VISA/Kinesis runtime services,
  activity leases, shutdown sealing, and cleanup reporting.
- Atomic channel-catalog, router, menu, device-button, artificial-channel, and
  range-view reconciliation.
- Session-only add, disconnect, and remove architecture, currently approved
  only for the mock driver.
- Mechanical relocation of all device/source packages under `devices/`, with
  one canonical maintained SR830 package.
- Regression coverage for scalar scan behavior, persistence, autosave, queue
  ordering, lifecycle, catalog mutation, and shutdown.
- Session-only System Log for concise application-level events.

## Remaining completion actions

| Item | Status | Completion evidence required |
| --- | --- | --- |
| Interactive mock workflow | User reported successful mock operation | Exact commit, selected profile, interpreter/environment, operations performed, shutdown result, and limitations were not supplied and must not be inferred |
| Real-device commissioning | Pending for every real driver | One device at a time, ignored local profile, exact environment/runtime/model/configuration, observed logs, cleanup, and independently verified final physical state |
| Office/PPT integration | Pending | User-executed disposable presentation/COM validation on the target Windows installation |
| Stable promotion | Pending | Integrate the reviewed beta line into `release/main`, run the release validation matrix, and publish only through the maintained release workflow |
| Real-driver runtime mutation | Pending and disabled | Per-driver busy/lifecycle/reference review, deterministic fake coverage, and user bench approval |

These actions do not reopen the completed structural implementation. They are
release, environment, or driver-validation gates. See
[device_status.md](device_status.md), [known_issues.md](known_issues.md), and
[hardware_safety.md](hardware_safety.md).

## Deliberately separate future work

Array-valued getters, spectra/images, object-array storage, new persistence
shapes, and corresponding plotting are a separate future project. Autofocus,
auto-position, and ANC300 remain ongoing integrations rather than incomplete
core reconstruction.
