# Implement Shared VISA and Thorlabs Kinesis Runtime Services

> **Archived 2026-08-21 — Implemented; hardware validation remains pending.**
> Current runtime ownership is documented in `core/shared_runtime/README.md`
> and ADR 001. This checklist is retained as implementation evidence only.

## Status checklist

- [x] Phase 1: baseline, shared-runtime skeleton, vendor manifest, and fake-service tests
- [x] Phase 2: shared VISA service and maintained VISA-device migration
- [x] Phase 3: shared Kinesis service and K10CR1/BBD30X migration
- [x] Phase 4: startup composition, shutdown ownership, and diagnostics
- [x] Phase 5: canonical and device documentation
- [x] Phase 6: static, unit, offscreen, core, and mock-device validation
- [ ] User-executed hardware validation (intentionally pending)

### Local implementation evidence

- Static: 59 changed/relevant Python files compiled under the maintained
  `zmeter_May2026` interpreter with bytecode redirected to a temporary folder.
- Static: the Kinesis 1.14.58.26351 manifest validated all nine local files;
  its JSON and nine affected device UI XML files parsed successfully.
- Unit/offscreen/core: `tests/` passed 42 tests, including shared VISA/Kinesis,
  conflict detection, startup laziness, explicit discovery, migrated VISA
  ownership, K10CR1 fake runtime, existing scan regressions, and widget
  construction.
- Device suites: PEM100 passed 10 tests, SP150 passed 12 tests, and BBD30X
  passed 10 tests.
- Simulation: `mockDevice/tests` passed 18 tests.
- No real ResourceManager, `clr`, Kinesis DLL load, vendor discovery, connection,
  configuration, motion, I/O, or disconnection was executed.

## Summary

Create independent shared-runtime implementations under `core/shared_runtime/` for PyVISA and Thorlabs Kinesis. Shared mode becomes the only maintained path; old runtime loaders and unused compatibility paths will be removed, not retained behind switches.

The services will be lazy, relocatable, independently replaceable, and injected into device layers. Hardware validation remains entirely user-executed.

## Implementation Changes

- Add independent `VisaRuntime` and `KinesisRuntime` modules with no shared mutable state. Update the mock-only startup path to construct both, inject them into enabled devices, and shut them down after device termination.
- Standardize the relative vendor-runtime layout at `core/shared_runtime/vendor/<runtime-name>/`. Track manifests and instructions but ignore vendor DLL binaries. Kinesis defaults to `vendor/thorlabs_kinesis/` relative to its Python module, with an alternate path accepted only for fake tests.
- Add a runtime README defining this location as the standard for future shared native runtimes. Before implementation, inventory the complete matching Kinesis files the user adds under BBD30X, move the local copies into the shared folder, and remove the tracked package-local K10CR1 DLL copies.

### VISA service and migration

- Public infrastructure:
  - `VisaRuntime(backend="", manager_factory=None)`
  - `open_resource(owner, address, **kwargs) -> VisaResourceLease`
  - `list_resources(query="?*::INSTR")`
  - idempotent `shutdown()`
  - `VisaResourceLease.resource` and idempotent `close()`
- Lazily create one manager, reserve normalized addresses, reject duplicate ownership, release reservations after failed opens, and keep the manager alive until runtime shutdown. Device disconnect closes only its lease/instrument.
- Migrate PEM100, SP150, HP34401A, Keithley24xx, SR830 v2, and SR860 while preserving their commands, units, limits, scan channels, timeouts, and device-specific cleanup.
- Replace constructor-time VISA enumeration with an explicit Refresh button. Run discovery through a shared Qt worker so widget construction and the UI thread do not enumerate or block.
- Convert `demoDevice` to injected fake VISA infrastructure and remove its global PyVISA monkey-patch.
- Leave legacy `sr830/` source unchanged and document it as excluded from the shared-runtime contract and unsupported in profiles using the new VISA service.

### Kinesis service and migration

- Public infrastructure:
  - `KinesisRuntime()` using the fixed relative vendor folder
  - `acquire(owner) -> KinesisRuntimeLease`
  - cached absolute-path native loading
  - cached managed-reference loading
  - a shared DeviceManager initialization lock
  - diagnostics for path, file versions, loaded components, and owners
  - idempotent `shutdown()` that reports active leases and never attempts to unload live Kinesis assemblies
- Validate the tracked required-file manifest, 64-bit process compatibility, and that every selected component comes from the one shared directory. Retain `os.add_dll_directory` handles and do not search device-local or machine-specific fallback paths.
- Refactor K10CR1 bindings to initialize lazily on `connect()`, preserving its structures, command bindings, polling, motion behavior, units, and public widget class while removing import-time `LoadLibrary` and the hardcoded machine path.
- Make BBD30X acquire the same Kinesis runtime and load its CLI references from that directory. Preserve its current channel-1, DDS220 fallback, polling, movement, and cleanup behavior.
- Release Kinesis ownership leases after failed connection or disconnect, but keep loaded modules process-resident.

## Documentation and Removed Code

- Update ADR 001 to record `core/shared_runtime/`, relative local vendor folders, shared-only operation, the final migration list, and removal of legacy-mode switches.
- Add runtime setup, diagnostics, shutdown, update, restoration, and **User-executed hardware test** procedures. Update architecture, project structure, Windows environment guidance, documentation indexes, startup examples, and each migrated device README.
- Record removal of:
  - direct ResourceManager construction/closure in migrated devices and widgets;
  - PEM100/SP150 resource-manager factory APIs;
  - constructor-time VISA discovery;
  - the demo-device global PyVISA monkey-patch;
  - K10CR1 import-time and machine-specific DLL loading;
  - BBD30X private directory-search/PATH loader;
  - package-local tracked Kinesis binaries;
  - executable real-hardware demonstrations that bypass the shared services.
- Record possible future cleanup after successful bench testing and one stable lab-use cycle: removal of the legacy `sr830/` package, pruning unused K10CR1 C-binding surface, and folding its small binding helper into the maintained adapter.

## Test Plan

- Never instantiate a real PyVISA manager, import `clr`, load a vendor DLL, enumerate instruments, or access hardware.
- VISA unit tests: lazy creation, one manager, multiple independent leases, duplicate-address rejection, partial-open cleanup, explicit discovery, disconnect isolation, shutdown ordering, repeated close/shutdown, injected backend failures, and discovery-worker signals.
- Kinesis unit tests: relative path resolution, manifest/missing-file errors, lazy native/managed loading, both K10CR1/BBD30X load orders, one-time caching, shared initialization locking, partial-load failure state, lease cleanup, active-owner shutdown errors, and retained DLL-directory handles.
- Update existing PEM100, SP150, and BBD30X fake tests; add fake-runtime tests for K10CR1 and focused lifecycle tests for every migrated VISA driver.
- Verify widget construction has no runtime/discovery side effects, Refresh is explicit and off-thread, scan discovery signatures remain unchanged, and all changed UI XML parses offscreen.
- Compile changed Python, run shared-runtime and migrated-device suites, then existing core and mock-device regressions. Add static checks proving direct PyVISA creation remains only in the intentionally excluded legacy SR830 code and real vendor loading remains only inside the shared Kinesis service.
- Leave combined VISA and K10CR1/BBD30X bench validation pending for the user, including separate-process Kinesis load-order tests and proof that disconnecting one VISA device leaves another operational.

## Assumptions

- The complete matching Kinesis runtime is sourced from `C:\Users\Taylo\Documents\GitHub\Kinesis`; implementation inventories it without loading it.
- The reviewed Kinesis DLL/XML set, manifest, and population instructions are
  tracked together; updates replace and verify one matching release as a unit.
- Shared operation is the default and only maintained mode. Restoration of one legacy family, if needed, will be performed later from Git history without changing the other runtime service.
- Public device class names and scan-facing channels remain stable, but obsolete transport factories, module-level binding APIs, and hardware demonstration entry points need not be preserved.
- Changes remain local and unstaged; no commit, push, PR, or hardware access is included.
