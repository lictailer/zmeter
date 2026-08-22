# Known Issues and Future Work

This file lists confirmed incomplete or deliberately partial behavior. It is
not a bug dump or speculative roadmap. Code, tests, and device-local READMEs
remain authoritative; close an item only with the validation named here.

## Runtime device management is partial

- **Current behavior:** `MainWindow` and `DeviceManager` expose guarded,
  session-only add, disconnect, and remove APIs. Only `mock_device` is approved,
  and there is no operator Add/Remove Device UI.
- **Impact:** Real device sets are loaded from a profile and require an
  application restart to add or remove. Editing JSON during a session has no
  effect. Existing device panels may still provide their own manual
  connect/disconnect controls without removing the device from the catalog.
- **Safe workaround:** Edit an ignored local profile while ZMeter is closed and
  restart with exactly the reviewed device set.
- **Future fix:** Add an operator management dialog only after its workflow is
  approved; enable each real driver independently after busy, lifecycle-worker,
  reference-provider, and router-detach review.
- **Validation:** Deterministic idle/refusal tests, full catalog reconciliation,
  failed-lifecycle recovery, and user-executed bench evidence per real driver.

## Real-device support is registered but not commissioned

- **Current behavior:** Phase 1 and admitted Phase 2 real drivers are lazy and
  startup-only. Tracked profiles keep them disabled and do not contain real
  addresses, serials, or endpoints.
- **Impact:** Automated evidence proves configuration, laziness, adapters, and
  simulated behavior, not compatibility with a particular installation.
- **Safe workaround:** Commission one device at a time from an ignored local
  profile using [hardware_safety.md](hardware_safety.md).
- **Future fix:** Record exact installation-specific bench results and address
  the driver-family backlog in [device_status.md](device_status.md).
- **Validation:** Exact commit/profile/environment/runtime/model/limits, safe
  operation, cleanup, application close, and independently verified final state.

## Ongoing device packages are not production integrations

- **Current behavior:** Autofocus XZ, `auto_focus`, `auto_position`, and ANC300
  remain source packages but have no registry IDs.
- **Impact:** They cannot be selected by a validated profile and are not claimed
  safe for normal ZMeter startup or shutdown.
- **Safe workaround:** Do not add ad hoc registry entries or import them from
  core/startup code.
- **Future fix:** Complete the ownership, explicit-resource, threading, limits,
  stop, cleanup, dependency, and simulator work listed in
  [device_status.md](device_status.md).
- **Validation:** Package-specific unit/fake/offscreen tests followed by a
  reviewed user-executed bench procedure.

## Driver hardening remains family-specific

- **Current behavior:** NI, VISA, Thorlabs, Four9, Montana2, OptiCool, and TLPM
  preserve established normal-condition behavior with documented limitations.
- **Impact:** Timeout, partial-connect, connection-loss, interruption, and final
  cleanup behavior is not uniformly proven across every driver.
- **Safe workaround:** Keep runtime mutation disabled, commission individually,
  use established device limits, and inspect final physical/session state after
  any error.
- **Future fix:** Implement the per-driver actions in
  [device_status.md](device_status.md), without broad compatibility shims.
- **Validation:** Fault matrices with fakes plus installation-specific hardware
  evidence; simulated success does not certify hardware.

## Shutdown deadline is cooperative for an executing GUI callback

- **Current behavior:** Shutdown seals new work and waits for scan/queue workers
  and deferred output finalization, but cannot preempt a synchronous GUI
  callback already executing.
- **Impact:** A slow save/export/dialog callback can exceed the nominal shutdown
  deadline. ZMeter detects the delay before device/runtime teardown rather than
  closing resources underneath active work.
- **Safe workaround:** Allow the callback to finish; do not force-kill the
  process while hardware or output state is uncertain.
- **Future fix:** Split long GUI finalization into bounded stages or an approved
  worker design while preserving Qt ownership and persistence ordering.
- **Validation:** Deterministic slow-finalizer shutdown/retry tests and isolated
  persistence round trips.

## Deferred VISA construction test has an intermittent timing race

- **Current behavior:** Enabled legacy VISA widgets schedule discovery on the
  next event-loop turn. One offscreen construction test has intermittently
  stalled or missed a UI-ready transition, then passed in isolation and full
  reruns.
- **Impact:** This is a test-stability limitation; no confirmed runtime hardware
  defect is attributed to it.
- **Safe workaround:** Run the exact test in isolation after a timeout and
  report both results; never weaken the deferred-discovery contract to hide it.
- **Future fix:** Replace timing-sensitive readiness observation with an
  explicit deterministic worker/UI acknowledgement.
- **Validation:** Repeated bounded offscreen runs with a fake VISA manager and
  zero resource opens during construction.

## PowerPoint/COM output lacks current integration evidence

- **Current behavior:** Automated persistence tests intercept presentation and
  COM boundaries and prove they are not reached accidentally.
- **Impact:** They do not prove Office installation, presentation mutation, or
  COM cleanup on a target workstation.
- **Safe workaround:** Treat JSON as the primary recovery artifact until output
  is confirmed; use a disposable presentation for validation.
- **Future fix:** Add a user-executed Windows smoke procedure and record Office
  version, file, result, and cleanup.
- **Validation:** Disposable non-lab presentation, expected slide update,
  process/handle cleanup, and unchanged JSON output.

## Multilevel scan progress can exceed its displayed denominator

- **Current behavior:** The denominator is the coordinate-product point count,
  while completed progress increments at every visited level point, including
  outer levels.
- **Impact:** A multilevel scan can display a numerator that differs from or
  exceeds the denominator even though traversal and stored scalar data remain
  correct.
- **Safe workaround:** Treat the progress count as an estimate and use scan
  indices/data for completion evidence.
- **Future fix:** Choose and migrate to one explicit progress definition without
  changing traversal or persistence.
- **Validation:** Focused nested-level progress/signal tests and manual mock GUI
  confirmation.

## Backup availability still includes a `Z:\` gate

- **Current behavior:** Backup configuration and a retained `Z:\` availability
  check jointly control copy behavior.
- **Impact:** A valid non-`Z:` backup destination may not behave as a fully
  general backup policy, and a local JSON save does not prove backup success.
- **Safe workaround:** Verify the configured destination and copied file; retain
  local JSON as the primary recovery artifact.
- **Future fix:** Replace the legacy drive gate with destination-specific
  validation and explicit copy status after a compatibility decision.
- **Validation:** Temporary local destinations, unavailable destination,
  collision/failure recovery, and user confirmation on the lab mapping.

## Two compatibility behaviors are intentionally deferred

- **Current behavior:** Enabled VISA widgets retain deferred automatic resource
  discovery, and syntactically valid unknown profile channel names are silently
  omitted from exposed allowlists.
- **Impact:** Construction can initiate discovery after the event loop starts,
  and a channel typo may produce an absent channel instead of profile failure.
- **Safe workaround:** Use disabled entries for dependency-safe configuration,
  inspect device panels/catalogs, and validate local channel names manually.
- **Future fix:** Treat explicit-only discovery and strict/warning channel
  validation as separate approved migrations with operator guidance.
- **Validation:** Device/UI compatibility tests and migration tests for existing
  local profiles.

## Array-valued getters are a separate project

- **Current behavior:** Scan storage, plotting, persistence, and loaders support
  the maintained scalar getter contract. No partial 1D/2D schema was added by
  the reconstruction.
- **Impact:** Spectra, frames, and object-shaped getter payloads are unsupported.
- **Safe workaround:** Keep array-producing instruments outside the scalar scan
  path or provide an independently maintained export workflow.
- **Future fix:** Design array shape metadata, storage, plotting, persistence,
  loader compatibility, and migration together.
- **Validation:** New schema decision, round trips, old-loader compatibility,
  plotting tests, and dedicated hardware-independent array fixtures.
