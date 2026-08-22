# Agent Task Contract

> **Archived 2026-08-21 — Reconstruction contract completed.** Preserved as
> historical implementation evidence. See `documents/reconstruction_status.md`
> and ADR 002 for the maintained outcome and remaining work.

## Objective

Restructure ZMeter so device code is organized under one parent directory, startup device selection is profile-driven, and a centralized device manager safely owns device instances and runtime catalog updates. Preserve every existing behavior except the two explicitly approved device-configuration/runtime-management capabilities.

Priorities, in order:

1. hardware and measurement safety;
2. preservation and recoverability of data;
3. unchanged existing behavior;
4. a clean, minimal diff;
5. maintainability and documentation;
6. speed.

## Authorized implementation workspace

The only authorized source workspace is the current local ZMeter Git worktree. The expected canonical root is:

```text
C:\Users\Taylo\Documents\GitHub\zmeter
```

Before any edit, the agent must run read-only checks equivalent to:

```powershell
git rev-parse --show-toplevel
git status --short --branch
git branch --show-current
```

The resolved root must equal the user-selected ZMeter worktree. If it resolves to this documentation/archive folder, another clone, or an unexpected path, stop before editing.

### Write boundary

- Write only inside the authorized ZMeter worktree.
- At the beginning of Phase 0, copy the staged manual into `documents/restructure_manual/` inside that worktree if it is not already present. Afterward, treat the in-repository manual as authoritative and do not update the external staged copy.
- Use a repository-local ignored temporary directory such as `.restructure_tmp/` for generated test artifacts.
- Never write tests into configured measurement, autosave, PowerPoint, or backup folders.
- Do not modify another clone, worktree, home configuration, global Git configuration, installed SDK, environment, registry, network drive, or external data-tool repository.
- Do not access or mutate GitHub remote state unless the user separately authorizes pushing or PR operations.

## Git authorization and limits

The agent may:

- work on the user-selected local structure branch;
- create focused local commits when requested or when the delegated workflow explicitly includes commits;
- create local sub-branches or worktrees for dependent subtasks if necessary;
- inspect and integrate new `main` changes into the structure branch after confirming the working tree is clean.

The agent must not, without separate explicit approval:

- commit directly to `main`;
- merge the structure branch into `main`;
- push branches or tags;
- open, merge, or close a pull request;
- rewrite published history, force-push, delete branches/tags, or use destructive reset/checkout operations;
- modify or discard pre-existing user changes.

Before structural work begins, `main` must contain the finished, approved baseline work. Record its commit hash and create or request a recovery tag such as `pre-structure-v2`. If the structure branch does not descend from the chosen baseline, stop and reconcile the branch with the user.

Urgent or independent production fixes must be developed from `main`, merged into `main`, and then integrated into the structure branch at a clean phase boundary. Do not implement the same fix independently in both code lines.

## Unchangeable behavior

The following are immutable during this project unless the user explicitly expands scope in writing.

### Scan and channel contracts

- Getter methods remain scalar-valued for scan storage.
- Existing `get_<channel>()` and `set_<channel>(value)` discovery/signature rules remain unchanged.
- Full channel names remain `<device_label>_<channel>` and continue to support labels containing underscores.
- Nested scan order, setter order, grouped I/O, timing, settle time, start wait, pause/resume, stop, queue behavior, progress, and autosave triggers remain unchanged.
- Artificial-channel equations, skip semantics, range behavior, and router behavior remain unchanged.
- Average getters retain current scalar semantics.
- Scan signal payloads and thread ownership remain unchanged unless a minimal catalog-change signal is required for runtime device management.

### Hardware and lifecycle contracts

- Device commands, addresses, units, physical limits, experiment limits, ramp behavior, timeouts, polling, monitoring, force-stop flags, and cleanup behavior remain unchanged.
- No driver may silently select, enumerate, connect to, reset, home, configure, read, write, move, ramp, disconnect, or otherwise affect hardware as a result of import, configuration parsing, widget construction, or automated tests.
- Existing shared VISA/Kinesis ownership and lease behavior remain unchanged.
- Device logic/hardware separation and cross-device router boundaries remain unchanged.
- Runtime removal is allowed only while all scans and the queue are idle in the first implementation.

### UI and operator workflow

- Existing windows, controls, labels, channel selections, scan editing, queue workflow, save paths, serial numbering, and close confirmation remain unchanged.
- Device buttons may become dynamically generated from the manager, but existing startup devices must appear and open as before.
- Configuration errors must be visible and must fail before hardware connection. They must not silently choose a fallback real device.

### Persistence and external interfaces

- Scan JSON structure, field meanings, level ordering, array ordering, `NaN` behavior, plot selector tokens, filename rules, serial discovery, comments, and logs remain unchanged.
- PPT slide organization, titles, screenshots, and failure handling remain unchanged.
- Autosave filename/location/timing and backup behavior remain unchanged.
- Existing downstream loaders must continue to accept newly produced scalar files.
- No schema version or migration is needed because this project is not authorized to change measurement data format.

### Dependencies and packaging

- Do not add or upgrade Python packages, SDKs, DLLs, system drivers, or environment files merely to perform the restructure.
- Optional device dependencies must remain optional and lazy.
- Keep the current Python/PyQt environment and Windows behavior.

## Explicitly out of scope

- 1D or 2D array-valued scan getter support;
- spectrometer/camera integration that depends on array storage;
- scan-engine rewrite or restoration of an older scan engine;
- plotting redesign;
- JSON/PPT/autosave/backup format changes;
- device behavior cleanup unrelated to moves or manager registration;
- new hardware limits, ramps, retries, auto-connect, or auto-reconnect;
- broad renaming or style cleanup;
- a full `src/` packaging conversion;
- splitting the existing `core` modules into new scan/plot/persistence packages;
- copying the old project into a runnable `legacy/` folder.

When implementation reveals that one of these changes appears necessary, stop and report why. Do not absorb it into the restructure.

## Safety rules

1. Never operate or test real laboratory hardware. Hardware tests are written for and executed by the user only.
2. Before running a test, inspect its imports, fixtures, discovery, configuration, and setup for hardware side effects.
3. Use mock devices, fake runtime adapters, temporary profiles, temporary paths, and offscreen Qt only.
4. Never launch an enabled real-device profile for validation.
5. Never weaken limits or stop behavior to make a test pass.
6. Never delete or overwrite measurement data, backup data, branches, tags, or user changes.
7. Never hide a baseline failure or classify an unrun test as passing.
8. Keep runtime device mutation serialized on the appropriate Qt ownership boundary; do not mutate catalogs while worker threads may still hold device callables.

## Mandatory stop conditions

Stop the task, update the progress log, preserve the working state, and ask the user when:

- the workspace root or base branch is unexpected;
- the initial worktree contains unexplained changes overlapping this project;
- baseline tests fail for reasons not already documented;
- a step may access real hardware or a vendor runtime without an injected fake;
- an existing behavior or persistence contract cannot be determined confidently;
- a required change enters an out-of-scope area;
- runtime removal cannot prove the scan and queue are idle;
- a device cannot be terminated safely using its current lifecycle contract;
- a configuration change would guess an address, channel, unit, dependency, or fallback;
- completion would require new packages, remote writes, destructive Git operations, or changes outside the authorized workspace;
- an urgent `main` change conflicts semantically with structural work.

## Definition of done

The project is complete only when:

- the final layout and runtime path match `02_TARGET_STRUCTURE_AND_STEPS.md`;
- startup behavior for the checked-in mock profile is unchanged;
- existing devices are moved/registered without device behavior changes;
- configuration validation is deterministic and side-effect free;
- the manager owns add/disconnect/remove/teardown and publishes one rebuilt catalog snapshot;
- runtime mutation is refused while scans or the queue are active;
- no stale buttons, router entries, bound methods, artificial-channel choices, or scan menus remain after removal;
- all required hardware-independent validation passes;
- all canonical documentation is updated to match verified code;
- the progress log contains a complete phase-by-phase record;
- final Git status and diff are reviewed, with no unrelated files or generated artifacts;
- real-hardware validation remains explicitly pending unless the user supplies results.
