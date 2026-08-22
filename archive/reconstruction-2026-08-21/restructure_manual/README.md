# ZMeter Behavior-Preserving Restructure Manual

> **Archived 2026-08-21 — Eight-phase reconstruction completed.** This manual
> and its append-only progress log are implementation evidence, not current
> instructions. See `documents/reconstruction_status.md` and ADR 002 for the
> maintained outcome and remaining work.

## Purpose

This manual is the execution contract for restructuring ZMeter while preserving all existing behavior. It is written so the work can be delegated to an implementation agent and inspected later.

The restructure may add only the two capabilities already approved for this project:

1. device instances and lab settings are selected through validated configuration instead of editing `start_zmeter.py`;
2. devices can be added, disconnected, or removed at runtime through a lifecycle-aware manager, initially only while the scan system is idle.

All other observable behavior must remain unchanged.

Array-valued getters, including 1D spectra and 2D frames, are explicitly deferred to the next project. See the existing array update brief outside this manual. This restructure must preserve the current scalar getter contract.

## Manual contents

Read and follow these files in order:

1. [01_AGENT_TASK_CONTRACT.md](01_AGENT_TASK_CONTRACT.md) — authority, immutable behavior, workspace and Git limits, safety rules, stop conditions, and completion criteria.
2. [02_TARGET_STRUCTURE_AND_STEPS.md](02_TARGET_STRUCTURE_AND_STEPS.md) — target layout, component responsibilities, configuration rules, and phased implementation procedure.
3. [03_VALIDATION_AND_INSPECTION.md](03_VALIDATION_AND_INSPECTION.md) — baseline characterization, test gates, review method, rollback, and evidence requirements.
4. [04_RESTRUCTURE_PROGRESS_LOG.md](04_RESTRUCTURE_PROGRESS_LOG.md) — append-only record that must be updated throughout implementation.

The repository's root `AGENTS.md`, executable code, tests, `project_structure.md`, and canonical documents remain authoritative. If this manual conflicts with a higher-priority instruction or verified current behavior, stop, record the conflict, and ask the user before proceeding.

## Before delegating implementation

This copy of the manual is staged in the review workspace because the documentation task was not authorized to modify the source repository. Before implementation begins, copy this complete directory into:

```text
C:\Users\Taylo\Documents\GitHub\zmeter\documents\restructure_manual
```

That documentation-only copy should be the first recorded change on the structure branch. From then on, the implementation agent must use and update only the in-repository copy, especially the progress log. Do not maintain two active versions of the manual.

## Selected strategy

- Modify the existing project incrementally on the structure branch.
- Do not copy the runnable application into a `legacy/` folder.
- Keep `main` stable and usable.
- Use a tested baseline tag and Git history for recovery.
- Make each phase independently testable and revertible.
- Separate mechanical moves from behavior-bearing changes.
- Do not rewrite the scan engine, persistence system, plotting system, or device implementations during this restructure.

## High-level completion state

At completion:

```text
profile JSON
    -> validated configuration
    -> reviewed driver registry
    -> device manager
    -> MainWindow / channel catalog / existing scan system
```

`start_zmeter.py` is a small stable launcher. Existing devices retain their current logic, hardware commands, channels, widgets, limits, and lifecycle behavior. The application can update the device catalog while idle without leaving stale scan/router/UI references.

## Document status

- Manual created: 2026-08-18
- Source repository inspected: `C:\Users\Taylo\Documents\GitHub\zmeter`
- Structure branch observed when this manual was created: `codex/structural_update_vibeeee`
- Source worktree was clean at inspection time.
- No ZMeter source code was changed while creating this manual.
