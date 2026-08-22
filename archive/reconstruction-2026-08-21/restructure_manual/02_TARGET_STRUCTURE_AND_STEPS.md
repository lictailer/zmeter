# Target Structure and Implementation Steps

> **Archived 2026-08-21 — Reconstruction procedure completed.** Preserved as
> historical implementation evidence. See `documents/reconstruction_status.md`
> and ADR 002 for the maintained outcome and remaining work.

## Minimal target layout

This project deliberately avoids a full packaging rewrite. Keep current core module names and runtime relationships while removing device-package clutter from the repository root.

```text
zmeter/
├── start_zmeter.py
├── config/
│   ├── profiles/
│   │   ├── mock.json
│   │   └── example_lab.json
│   └── profile.schema.json              # optional if actively validated/tested
├── core/
│   ├── device_management/
│   │   ├── __init__.py
│   │   ├── config.py                    # load and validate profile data
│   │   ├── models.py                    # immutable configuration/record models
│   │   ├── registry.py                  # reviewed driver ID -> factory adapter
│   │   └── manager.py                   # instance/catalog/lifecycle ownership
│   ├── mainWindow.py
│   ├── scanlist.py
│   ├── scan.py
│   ├── scan_logic.py
│   ├── shared_runtime/
│   └── ...existing core modules...
├── devices/
│   ├── __init__.py
│   ├── mockDevice/
│   ├── sr860/
│   ├── sr830_v2/
│   ├── keithley24xx/
│   ├── ni6423/
│   └── ...existing device packages...
├── tests/
├── documents/
├── archive/
└── project_structure.md
```

Use one flat `devices/` parent in this update. Do not add category subdirectories unless the number of packages later makes them necessary. This keeps import changes and move risk small.

Do not move `core/shared_runtime/` into a device package. It owns process-wide typed runtime services, not one instrument.

Do not move `documents/`, `tests/`, `archive/`, environment files, or measurement configuration unrelated to devices merely for visual symmetry.

## Runtime ownership after restructure

```text
start_zmeter.py
  -> QApplication
  -> RuntimeServices
  -> profile loader/validator
  -> driver registry
  -> DeviceManager
       -> device instances and lifecycle
       -> readable/writable catalog snapshot
       -> add/update/remove signals
  -> MainWindow
       -> existing ScanList -> Scan -> ScanLogic path
```

### Component rules

#### `start_zmeter.py`

- Parse only the selected profile path and general launch options.
- Create `QApplication` before QWidget-based devices.
- Create one `RuntimeServices` provider.
- Create the registry and manager, load the profile, then create `MainWindow`.
- Shut devices down through the manager before shutting down shared runtimes.
- Contain no device-specific imports, addresses, serials, connection commands, or channel lists.

#### Configuration loader

- Parse configuration without importing a vendor SDK or constructing a device.
- Validate schema version, duplicate IDs, driver IDs, types, required fields, connection keys, and channel filters.
- Resolve relative paths against a documented profile/repository boundary rather than arbitrary current working directory state.
- Return validated models; do not return partially accepted dictionaries with warnings for safety-critical fields.
- Report all safe-to-collect validation errors together where practical.

#### Driver registry

- Use stable reviewed IDs such as `mock_device`, `sr860`, or `ni6423`.
- Do not accept arbitrary Python module/class paths from JSON.
- Centralize constructor/runtime injection and existing connection-method differences.
- Do not change driver behavior. An adapter may call the driver's existing constructor/connect/disconnect method, but must not invent retries, fallback addresses, or new cleanup semantics.
- Registering a driver type is a code review event; adding another instance of a registered driver is a configuration change.

#### Device manager

- Be the single owner of registered device instances and their lifecycle records.
- Maintain explicit states such as disabled, disconnected, connecting, connected, error, and removing.
- Generate complete catalog snapshots from current records instead of incrementally mutating parallel dictionaries.
- Publish Qt-safe signals for device/catalog changes.
- Inject router metadata for newly added devices using the existing contract.
- Reject duplicate labels and removal during active scans/queue execution.
- Use one ordered removal transaction: block new calls, confirm idle, request stop/force-stop as applicable, terminate, close/delete widget on the UI thread, release leases, remove record, rebuild catalog, refresh consumers.
- Keep “disconnect,” “remove from session,” “disable in profile,” and “delete profile entry” as distinct actions.

#### `MainWindow`

- Continue to own the existing application UI, routing, range behavior, artificial channels, scan list, and shutdown coordination unless ownership is explicitly transferred to the manager in one focused step.
- Observe device-manager snapshots/signals instead of treating the initial device dictionary as permanently fixed.
- Build/remove device buttons dynamically without changing their appearance or open/focus behavior.
- Refresh scan menus, manual-set choices, artificial-channel choices, and router catalogs from one authoritative snapshot.
- Never keep a removed device's bound getter/setter method in a catalog.

## Profile rules

The exact schema should remain small. A representative profile is:

```json
{
  "schema_version": 1,
  "profile": "mock",
  "paths": {
    "save": "./data",
    "backup": null
  },
  "devices": [
    {
      "id": "mock_device_1",
      "driver": "mock_device",
      "enabled": true,
      "connection": {
        "address": "MOCK::INSTR"
      },
      "scan_channels": {
        "set": null,
        "get": null
      }
    }
  ]
}
```

Required policy:

- `id` is the stable runtime label and must remain compatible with saved scans and range-limit keys.
- `driver` is a stable registry ID, not an import path.
- `enabled: false` must not import/load vendor dependencies, discover, construct, or connect the device.
- `connection` accepts only fields declared by that registry entry.
- `null` channel filters expose all currently valid scan channels; explicit lists must be validated and unknown channels reported.
- Checked-in defaults must remain mock-only and hardware-safe.
- Lab addresses/serials belong in a local profile according to repository policy; credentials and private endpoints must never be committed.
- Configuration loading must not automatically connect unless the profile and existing operator workflow explicitly call for that behavior.

## Phased implementation procedure

Each phase must be a focused commit or PR-ready commit series. Complete its validation and progress-log entry before continuing.

### Phase 0 — Establish the baseline

1. Verify the authorized root, clean status, current branch, upstream, and selected base commit.
2. Confirm the structure branch descends from the approved `main` baseline.
3. Record current tree, runtime path, checked-in startup devices, and exact test environment.
4. Inspect all tests before execution and run only confirmed hardware-independent baseline checks.
5. Capture representative scalar startup/catalog/scan/persistence behavior with mocks and temporary output.
6. Record the recovery tag or request that the user create it.

No code moves occur in this phase.

### Phase 1 — Add configuration models and validation

1. Add pure configuration models and loader tests.
2. Create a checked-in mock profile reproducing current `start_zmeter.py` values.
3. Do not change the active startup path yet.
4. Prove parsing has no device imports, runtime construction, enumeration, or connections.
5. Document validation errors and local-profile policy.

### Phase 2 — Add the reviewed registry

1. Register `mock_device` only.
2. Test constructor/lifecycle adapters with fake services.
3. Add one device type per focused change thereafter.
4. Verify missing optional dependencies affect only an enabled target driver.
5. Do not move package directories in this phase.

### Phase 3 — Add manager ownership without dynamic mutation

1. Create the manager and device record/state model.
2. Load the same two mock instances currently created by startup.
3. Let `MainWindow` receive the manager or its initial snapshot.
4. Route application shutdown through one manager teardown path.
5. Preserve the existing button order, channel catalog, router metadata, scan menus, and shutdown result.

The application must still behave as a static startup system at the end of this phase.

### Phase 4 — Switch the launcher to the profile path

1. Make `start_zmeter.py` a thin launcher.
2. Select the checked-in mock profile by default.
3. Preserve save path, backup-disabled behavior, mock labels, filters, application title, and shutdown order.
4. Remove device-specific imports and commented connection blocks only after their reviewed registry/profile replacements exist.
5. Update startup tests and documentation in the same phase.

### Phase 5 — Make catalogs rebuildable

1. Define one immutable/snapshot catalog representation.
2. Rebuild scan callable mappings, display channel lists, router catalog, and UI choices from current manager records.
3. Generalize the existing artificial-channel refresh path rather than adding separate refresh implementations.
4. Test repeated refresh, add then remove, failed add, and removal rollback.
5. Confirm an open scan editor does not silently retain an invalid selected channel.

Choose and document the policy for a non-running saved/open scan that references a removed device: retain and mark unresolved, or refuse removal. Do not silently rewrite scan definitions.

### Phase 6 — Add idle-only runtime management

1. Add/disconnect/remove mock devices first.
2. Add an explicit idle guard covering active scan logic, queue activity, manual operations, and in-flight router/device calls.
3. Keep configuration persistence separate from session mutation.
4. Test UI button creation/removal, focus behavior, menu/catalog refresh, router access, failure recovery, repeated teardown, and application shutdown.
5. Refuse unsafe removal with a clear operator message.
6. Only after mock behavior is complete, enable existing registered real-device types for user-executed bench review.

### Phase 7 — Move packages under `devices/`

1. Move one device package or closely related family at a time.
2. Perform mechanical moves separately from logic changes.
3. Update registry imports, tests, UI/resource path resolution, README links, and optional dependency tests.
4. Use file-relative resource paths where a move would otherwise change current-working-directory assumptions, while preserving visible behavior.
5. Do not leave duplicate runnable packages or compatibility shims unless a verified external consumer requires one and the user approves it.
6. Move `mockDevice` early as the reference; move highest-risk/vendor-heavy packages only after the pattern is proven.

### Phase 8 — Consolidate and document

1. Remove only code made definitively dead by the completed path, with review evidence.
2. Keep archived historical material separate and non-runnable.
3. Update `project_structure.md`, architecture, device contract, testing, environment/startup documentation, root README, and relevant device READMEs.
4. Run the complete hardware-independent validation matrix.
5. Review final diff for accidental behavior edits, generated files, local profiles, addresses, credentials, data, DLLs, and caches.
6. Prepare the final handoff and user-executed hardware-test plan. Do not merge or push without authorization.

## Work that must remain for the next update

After this restructure is stable, array-valued getter work may begin from the new tested baseline. That future project owns:

- scalar/1D/2D measurement-value abstraction;
- scan buffer changes;
- array `NaN`/skip behavior;
- array persistence and compatibility decisions;
- spectrum/image plotting;
- spectrometer/camera full-array channels.

No placeholder object-array storage, array shape guessing, or partial spectrum support should be introduced here.
