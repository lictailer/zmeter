# Device Registration Roadmap

## Implementation status

Phase 1 was implemented on 2026-08-19. The default profile remains mock-only;
all real registrations are startup-only and await user-executed commissioning.
The maintained `sr830_v2` source is now the sole official `devices/sr830`
package and registry ID `sr830`. See
[DEVICE_REGISTRATION_PHASE1_REVIEW.md](DEVICE_REGISTRATION_PHASE1_REVIEW.md)
for the exact registry matrix, admitted limitations, and bench sequence. Phase
2 remains pending.

## Purpose

This roadmap brings the existing device integrations into the reviewed registry in two phases while keeping the reconstruction stable. The default checked-in profile remains mock-only. Real instruments are enabled only through ignored local profiles and are tested on hardware by the user.

The guiding compatibility decision is to preserve each device's established normal-condition behavior during registration. Registration is not the time for broad driver rewrites or special-case hardening. Before a driver is registered, however, its imports, configuration, channel discovery, lifecycle, shutdown, and manager integration must be reviewed. Any conflict that cannot be resolved with a small adapter or documentation change is recorded as future work, and the driver remains unregistered rather than receiving an unsafe compatibility workaround.

## Scope and working rules

- Keep device widget, logic, hardware, commands, timing, ranges, and normal operator workflow unchanged unless a minimal correction is required for registration.
- Use lazy factories so disabled or unrelated devices do not import optional vendor packages, enumerate resources, load SDKs, or open connections.
- Give every registered driver a stable driver ID and an explicit connection schema. Keep addresses, serials, NI names, endpoints, and lab-specific limits in ignored local profiles.
- Initially register every real driver for startup use only with `runtime_mutation_allowed=False`. Runtime add, disconnect, and removal require a later busy/lifecycle/reference review and user bench approval.
- Use `connect_on_start=false` for first commissioning. Construction must not be treated as successful connection.
- Preserve deferred automatic VISA discovery and the current silent skipping of unknown configured scan channels.
- Keep the shared mock profile and mock tests as the baseline throughout both phases.
- Do not add fallback driver selection, implicit first-device selection, duplicate implementations, or compatibility shims.
- Make each family or driver change independently reviewable and reversible. Avoid unrelated cleanup.
- Agents perform only static, unit, fake-runtime, and offscreen GUI validation. All real-device activity is a **User-executed hardware test**.

## Pre-registration review required for every driver

Before editing the registry, record the following in the driver change or progress log:

1. stable driver ID, import path, widget class, and constructor dependencies;
2. accepted connection keys, types, required values, and mapping to the existing connect method;
3. exact scan getter/setter names, units, filters, and applicable global/device limits;
4. import-time behavior, discovery behavior, SDK/DLL requirements, and failure messages;
5. connect, disconnect, scan start/stop, force-stop, termination, close, and partial-initialization behavior;
6. worker/thread ownership and whether any lifecycle call could block or mutate Qt widgets from the wrong thread;
7. conflicts with `DeviceManager`, shared runtime ownership, router attachment, shutdown, or stored catalog references;
8. the smallest fake or stub test that proves registration without importing or operating real hardware;
9. known limitations and the concrete future improvement required.

A conflict is blocking when registration could connect implicitly, select an unspecified real resource, bypass limits, conceal uncertain cleanup, release a shared runtime under a live device, or make mock-only startup depend on a vendor installation. Blocking conflicts are documented and deferred. Other known edge-case limitations may remain when normal behavior and final cleanup are understood, the limitation is visible, and the driver remains startup-only.

## Phase 1: primary acquisition, VISA, and Thorlabs devices

Phase 1 contains roadmap steps 1–3. Complete each step as a separate reviewable batch, in the order below.

### Step 1 — NI DAQ: `ni6423` and legacy `nidaq`

Register both integrations as separate, non-interchangeable drivers:

| Driver ID | Package | Initial policy |
| --- | --- | --- |
| `ni6423` | `devices.ni6423` | Preferred modern NI-DAQmx path; startup-only |
| `nidaq` | `devices.nidaq` | Preserve legacy PyDAQmx implementation; startup-only |

Implementation boundaries:

- Keep the original `nidaq` package unchanged except for a minimal registry adapter if necessary.
- Do not migrate `nidaq` from PyDAQmx to `nidaqmx` in this phase.
- Do not treat the two drivers as API- or hardware-compatible. Their channel counts, task routing, dependencies, and lifecycle methods differ.
- Use an explicit NI device-name connection field, verified by the user in NI MAX. Do not guess or silently fall back to another NI device.
- For `ni6423`, review the current AO0–AO3, AI0–AI31, counter, PFI, internal-timebase, and AI28–AI31 feedback assumptions before bench use.
- Keep runtime mutation disabled because neither integration yet satisfies the full reviewed busy/force-stop lifecycle contract.

Required future improvement:

- migrate the legacy `nidaq` integration to the maintained NI-DAQmx API after reconstruction stabilization;
- standardize disconnect, scan hooks, force-stop, bounded task cleanup, and partial-connect rollback;
- make NI channel counts, feedback wiring, counter allocation, and PFI routing explicit configuration where appropriate;
- add a hardware-independent fake NI backend covering task creation, reads/writes, timeouts, and cleanup.

### Step 2 — VISA devices and official SR830 consolidation

Review and register the maintained VISA family one driver at a time:

- `pem100`
- `sp150`
- `hp34401a`
- `keithley24xx`
- `sr860`
- `sr830_v2`, promoted to the sole official `sr830`
- `demoDevice`, retained as a template/simulator and reviewed separately so its dummy-runtime behavior is not accidentally changed

Use the shared `VisaRuntime` where the current package already supports it. Preserve deferred automatic VISA discovery and the existing operator workflow. Registration must remain lazy so mock-only startup does not create a VISA resource manager or enumerate resources.

SR830 consolidation sequence:

1. confirm `sr830_v2` channels, UI resources, lifecycle, tests, and import paths;
2. reserve the stable registry driver ID `sr830` for that implementation;
3. update tests, documentation, and profile examples to the stable ID and final package path;
4. remove the legacy `devices/sr830` implementation;
5. rename or relocate `devices/sr830_v2` to `devices/sr830` without changing its normal behavior;
6. verify no executable import, resource path, registry entry, or documentation link still points to `sr830_v2` or the removed legacy implementation.

The SR830 removal/rename is the only planned source consolidation in this roadmap. Perform it as its own recoverable change after the replacement registration and tests are ready.

Required future improvement:

- standardize bounded connect/disconnect/terminate behavior and connection-state probes;
- separate discovery status from device connection status while preserving deferred discovery;
- review monitor/discovery workers for reliable busy reporting and runtime removal eligibility;
- add fake VISA fault tests for timeouts, malformed responses, partial initialization, and shutdown;
- document exact model-specific commands, units, limits, and safe bench operations.

### Step 3 — Thorlabs motion devices

Review and register:

- `bbd30x` from `devices.BBD30X`;
- `k10cr1` from `devices.k10cr1`.

Preserve the current Kinesis behavior, explicit serial-number selection, local manifest-verified runtime, connection sequence, and operator workflow. Use the shared `KinesisRuntime`; unrelated profiles must not load pythonnet, CLR, Kinesis assemblies, or DLLs.

Keep both drivers startup-only. Do not claim safe runtime removal until all motion, polling, homing, stopping, and device-owned workers are covered by a fast side-effect-free busy probe.

Required future improvement:

- implement and verify a real bounded `force_stop` path for K10CR1;
- verify stop behavior and last-confirmed position after interrupted motion;
- standardize asynchronous connect/disconnect completion and error propagation;
- add fake Kinesis tests for missing DLLs, invalid serials, timeouts, partial connection, active motion, and shutdown.

### Phase 1 exit criteria

- Every admitted driver has a lazy reviewed registration, explicit schema, stable ID, exact channel test, and startup-only policy.
- The default mock profile remains unchanged and mock-only startup imports no NI, VISA, CLR, Kinesis, or device-vendor module.
- Hardware-independent registry, manager, lifecycle-adapter, channel-discovery, and shutdown tests pass.
- The official SR830 transition is complete with no legacy executable path remaining.
- Each driver README contains its dependencies, limitations, connection keys, limits, and a proposed **User-executed hardware test**.
- Open special-condition risks are listed as future improvements rather than folded into broad rewrites.

## Phase 2: environment-specific and ongoing integrations

Phase 2 begins only after Phase 1 is stable. It contains roadmap steps 4–5.

### Step 4 — Cryostat and environment-specific devices

Review these integrations independently because they can be validated only in specific laboratory environments:

- `four9`
- `montana2`
- `opticool`

Preserve current normal behavior, protocols, timing, UI, and environment assumptions. Keep endpoints and local installation details out of the shared repository. Each driver must fail clearly when its environment or vendor dependency is unavailable, without affecting mock-only or unrelated-device startup.

Initial policy:

- register only after lazy import and final teardown can be demonstrated with a fake/stub boundary;
- keep `connect_on_start=false` and runtime mutation disabled;
- commission one environment and one device at a time using an ignored local profile;
- if import-time vendor loading, sleeps, fixed endpoints, or incomplete lifecycle behavior conflicts with the manager contract, document the conflict and leave that driver unregistered until a minimal safe boundary exists.

Required future improvement:

- `four9`: standardize connect/disconnect and scan lifecycle hooks, network timeout/cancellation, and fake-socket fault coverage;
- `montana2`: move remaining endpoint/install assumptions to configuration and standardize stop/termination behavior;
- `opticool`: remove import-time vendor DLL loading and delays, make runtime acquisition explicit/lazy, and provide bounded async lifecycle handling;
- all three: add environment-specific dependency manifests and user bench records tied to exact installations.

### Step 5 — Autofocus, ANC300, and other ongoing integrations

Treat the following as ongoing work rather than production-ready registrations:

- `autofocus_xuguo`
- `auto_focus`
- `auto_position`
- `ANC300`
- `tlpm`
- any remaining experimental or incomplete device package discovered during the review

Keep current source behavior and preserve these packages for continued development. Do not advertise them as ready merely because a registry entry can be written. Register a package only when a minimal startup adapter can satisfy lazy import, explicit resource selection, channel discovery, and final cleanup without concealing its incomplete state. Otherwise document it and leave it unregistered.

Required future improvement:

- unify autofocus ownership, explicit serial/DAQ configuration, router references, busy reporting, and lifecycle cleanup;
- replace constructor-time COM/resource discovery with a reviewed explicit or deferred workflow;
- reconcile PyQt and optional scientific dependency requirements;
- turn ANC300 into a coherent importable device package with a defined widget, connection schema, channels, and lifecycle;
- make TLPM resource selection explicit instead of selecting the first device, and implement reliable force-stop, disconnect, and termination;
- add deterministic fake backends before any user bench procedure.

### Phase 2 exit criteria

- Each environment-specific device is either safely registered startup-only or explicitly deferred with a documented blocking conflict.
- Ongoing packages have an owner-visible future-work record and are not presented as production-ready without evidence.
- Optional vendor imports remain isolated from mock-only and unrelated-device startup.
- No checked-in profile contains real addresses, serials, endpoints, or lab-specific enablement.
- Hardware-independent tests pass, and user-provided environment/bench results are recorded narrowly without generalizing beyond the tested installation.

## Lightweight implementation pattern for each batch

Each batch should normally contain only:

1. one lazy registry registration and its small adapter callbacks;
2. connection-schema validation for that driver;
3. fake/stub tests for disabled laziness, construction, connection mapping, channels, failure propagation, and teardown order;
4. minimal updates to the device README, central inventory, and a sanitized profile example if useful;
5. a short future-improvement entry for known but intentionally deferred edge cases.

Avoid rewriting device internals during registration. If a minimal adapter cannot satisfy startup ownership and safe final teardown, stop that driver, record the conflict, and continue with the next independently reviewable driver.

## Validation and evidence

For each batch, run only hardware-independent checks:

- static import review and `py_compile` for changed Python;
- JSON/profile validation without constructing disabled drivers;
- fake-runtime or fake-transport unit tests;
- offscreen GUI construction, channel catalog, scan start/stop coordination, and application shutdown tests;
- full core and mock regression suites after focused tests pass;
- scans for direct vendor imports in startup/core and for committed addresses or serials.

For real hardware, prepare a device-specific **User-executed hardware test** following `documents/hardware_safety.md`. Record the exact commit, ignored profile hash, interpreter/environment, vendor runtime, model/firmware, connection identifier, approved limits, initial state, observed logs, cleanup result, final physical state, and limitations. Passing normal-condition hardware operation does not close the documented special-condition backlog.
