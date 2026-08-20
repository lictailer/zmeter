# Tutorial: Build a Reliable Codex Contribution Workflow for ZMeter

## Purpose of this tutorial

This document is an operating guide for upgrading how Codex contributes to ZMeter.
It describes what should be created later, what each document should contain, how the
documents relate to one another, and what workflow Codex should follow for every
implementation task.

This tutorial is the only workflow file being created at this stage. It does **not**
create `AGENTS.md`, nested instruction files, new technical references, CI files, or
test tooling. Use it as the plan for introducing those pieces deliberately.

The intended source repository is:

```text
C:\Users\Taylo\Documents\GitHub\zmeter
```

The current project-context/archive folder is useful historical evidence, but it
should not become the source of truth for active implementation behavior.

## 1. Design principles

Build the system around five rules:

1. **Codex instructions must be short and durable.** Put rules and required commands
   in `AGENTS.md`; do not put rapidly changing branch, device, or feature status there.
2. **Technical documentation must have one canonical home.** Use `documents/` for
   repository-wide technical references and keep device-specific documentation next
   to the device module.
3. **Code and tests are the final authority.** When documentation and implementation
   disagree, Codex must verify the implementation and report or repair the drift.
4. **Hardware claims require hardware evidence.** Compilation, unit tests, simulated
   devices, and real-instrument validation are separate evidence levels.
5. **Documentation maintenance is part of implementation.** A behavior change is not
   complete until its affected contracts and tests are synchronized.

## 2. Target information hierarchy

Use the following hierarchy when the workflow is implemented:

```text
zmeter/
|-- AGENTS.md                         # Short, mandatory repository rules
|-- README.md                         # Human setup and first-launch guide
|-- start_zmeter.py                   # Active startup/profile entry point
|-- documents/
|   |-- README.md                     # Documentation index and reading routes
|   |-- architecture.md               # Stable system architecture
|   |-- scan_engine.md                # Scan schema and runtime contract
|   |-- device_contract.md            # Rules for adding/integrating devices
|   |-- testing.md                    # Validation commands and evidence levels
|   |-- environment_windows.md        # Reproducible Windows environment
|   |-- data_format.md                # JSON/PPT/autosave/backup contracts
|   |-- hardware_safety.md            # Limits, stop, abort, and bench rules
|   |-- known_issues.md                # Confirmed unresolved issues
|   `-- decisions/
|       |-- README.md                 # Architecture-decision index/template
|       `-- NNN-short-decision.md     # One important decision per record
|-- core/
|   `-- AGENTS.md                     # Optional core-only rules
|-- tests/
|   `-- AGENTS.md                     # Optional test isolation rules
`-- devices/
    `-- <device>/
        `-- README.md                 # Device-specific setup and behavior
```

Do not create every file simply because it appears in this tree. Introduce them in
the rollout order in Section 10 and merge overlapping existing documents instead of
creating duplicate sources of truth.

## 3. Root `AGENTS.md`

### Why it is required

Codex automatically looks for `AGENTS.md` and `AGENTS.override.md`. The existing
`agent.md` is not the standard filename and should not be assumed to load unless an
explicit fallback is configured.

Create a fresh `AGENTS.md` rather than blindly renaming the existing file. The current
file contains useful knowledge, but it also contains stale and contradictory details.

### Recommended size

Aim for roughly 3-5 KB. It should be fast to read at the beginning of every task.

### Required sections

#### Project purpose

Describe ZMeter in two or three sentences:

- Windows/PyQt6 laboratory measurement application.
- Configurable nested scans over multiple instruments.
- Hardware control, live plotting, JSON persistence, PPT logs, and backups.

#### Source-of-truth order

State the precedence explicitly:

1. Current code and test behavior.
2. Repository `AGENTS.md` instructions.
3. Canonical documents linked from `documents/README.md`.
4. Device-local README files.
5. Historical audits, old branches, and Codex transcripts.

#### Required task-start checks

Require Codex to:

- inspect `git status --short --branch`;
- preserve all pre-existing changes;
- identify the active call path before editing;
- read only the documents relevant to the requested subsystem;
- state whether the task touches real hardware, persistence, or safety behavior.

#### Architectural invariants

Keep only stable rules, for example:

- Active scan engine is imported by `core/scan.py`; verify the import before editing.
- Normal scan channels use validated `.logic.get_*()` and `.logic.set_*(value)` methods.
- Cross-device operations go through the injected command router.
- Device-specific I/O belongs in the hardware layer.
- GUI, logic, and hardware lifecycle behavior must remain coherent.
- Saved scan-schema changes require save/load and compatibility verification.

Do not list currently enabled instruments or addresses here.

#### Hardware safety rules

Require Codex to:

- use mock/simulated paths before real hardware where possible;
- never assume a compile or unit test proves hardware behavior;
- preserve configured limits and emergency-stop behavior;
- avoid connecting to, homing, ramping, or writing real devices unless authorized;
- report any test that requires a human bench procedure.

#### Validation requirements

List the canonical commands after they have been verified in the supported environment.
Keep the root file concise and link to `documents/testing.md` for the complete matrix.

#### Documentation update contract

Require updates when implementation changes affect:

- channel names or signatures;
- scan schema or execution order;
- UI-visible workflow;
- JSON, PPT, autosave, or backup behavior;
- dependencies or launch commands;
- hardware requirements, limits, stop, or abort behavior.

#### Completion report

Require every Codex handoff to include:

- behavior changed;
- files changed;
- tests run and results;
- tests not run and reasons;
- hardware-validation status;
- remaining risks;
- final Git working-tree state.

### Information that must not be in `AGENTS.md`

Avoid:

- current branch, commit, or dirty-file lists;
- hardcoded VISA addresses, serial numbers, or lab backup paths;
- long historical summaries;
- unfinished feature inventories;
- duplicate explanations already maintained in technical documentation;
- speculative roadmap items.

## 4. Root `README.md`

The root README is for a new human operator or developer, not primarily for Codex.

It should contain:

1. What ZMeter does.
2. Supported operating system.
3. One canonical Python/Conda environment and its exact filename.
4. Required NI, VISA, GPIB, and vendor runtimes.
5. Clone, environment creation, activation, and launch commands.
6. A mock-device or no-hardware first-launch procedure.
7. Where laboratory profiles and device addresses are configured.
8. Links to the documentation index and testing guide.
9. A short troubleshooting section.

Before writing it, decide whether `zmeter_Mar2026_environment.yml` or
`zmeter_May2026_environment.yml` is canonical, or create a consolidated environment
as a separate implementation task. Do not document `environment.yml` unless that file
actually exists.

## 5. Documentation index: `documents/README.md`

This should be the routing page for both humans and Codex. It should answer, "What do
I read for this task?"

Use a table like:

| Task | Read first | Then inspect |
| --- | --- | --- |
| Change scan traversal | `scan_engine.md` | `core/scan.py`, `core/scan_logic.py` |
| Add a device | `device_contract.md` | `devices/demoDevice/`, target module |
| Change save/load | `data_format.md` | `core/scan.py`, loaders/tests |
| Change hardware limits | `hardware_safety.md` | device logic/hardware, range config |
| Change environment | `environment_windows.md` | environment YAML files |
| Run validation | `testing.md` | affected tests and mock device |

Each entry should say whether the document is canonical, module-specific, historical,
or planned for retirement.

## 6. Canonical technical documents

### `documents/architecture.md`

Include stable relationships, not line-by-line code narration:

- boot flow: `start_zmeter.py -> MainWindow -> ScanList -> Scan -> ScanLogic`;
- ownership responsibilities for each major component;
- UI-thread versus worker-thread boundaries;
- device discovery and command routing;
- scan configuration and data flow;
- plot and persistence flow;
- extension points and forbidden coupling.

End with a short "Where to edit" table.

### `documents/scan_engine.md`

Consolidate the useful content from the existing scan overview and scan-logic files.
Document:

- active engine and exact import path;
- `ScanInfo` schema and required/default fields;
- level ordering and recursion direction;
- setting-array construction and `NaN` semantics;
- duplicate-channel write resolution;
- manual before/after actions;
- settle time and start-wait time;
- direct and averaged getters;
- grouped parallel device I/O;
- artificial-channel and global-range skip behavior;
- pause, resume, stop, abort, and cleanup;
- progress, logging, autosave, and finish-time output;
- save/load compatibility expectations;
- focused test cases for every invariant.

Prefer function names over fragile line numbers.

### `documents/device_contract.md`

Describe the contract for a device module:

- package and import layout;
- widget/main, logic, and hardware responsibilities;
- valid getter and setter signatures;
- signal and thread expectations;
- connect/disconnect lifecycle;
- `start_scan`, `stop_scan`, `force_stop`, `terminate_dev`, and `close` behavior;
- command-router injection and cross-device operations;
- optional dependencies and guarded imports;
- channel filtering;
- configuration versus hardcoded values;
- minimum mock/unit/GUI/hardware tests;
- checklist for registering a device in a lab profile.

Use `devices/mockDevice` as the preferred executable reference. Treat
`devices/demoDevice` as a historical/template reference until its instructions
are reconciled with current code.

### `documents/testing.md`

Create a validation matrix with four evidence levels:

1. **Static:** imports, syntax compilation, UI XML parsing.
2. **Hardware-independent:** unit tests for scan logic, schemas, and utilities.
3. **Simulation/GUI:** mock-device and offscreen widget integration.
4. **Hardware bench:** real connection, read/write, timeout, abort, and shutdown.

For every command, document:

- required environment;
- whether hardware is needed;
- expected runtime;
- files or caches it may create;
- what a pass does and does not prove.

Candidate commands to verify and then standardize are:

```powershell
python -B -m py_compile <changed Python files>
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m unittest discover -s devices/mockDevice/tests -p "test_*.py" -v
```

Do not place an unverified command in `AGENTS.md` as mandatory.

### `documents/environment_windows.md`

Include:

- canonical environment file and Python version;
- environment creation and update commands;
- required system drivers;
- device-specific optional runtimes;
- environment variables and path configuration;
- PowerPoint/COM requirements;
- mock-only setup;
- common import/driver failures and diagnostics.

Separate Python packages from system-installed drivers.

### `documents/data_format.md`

Document:

- top-level scan JSON fields;
- per-level, setter, getter, plot, comments, and log fields;
- array encoding and `NaN` handling;
- filename/serial rules;
- save, load, autosave, and backup lifecycle;
- PPT slide organization;
- backward-compatibility policy;
- downstream consumers such as ZMeter JSON loaders;
- round-trip tests required when the schema changes.

### `documents/hardware_safety.md`

Include repository-wide rules for:

- permitted ranges and units;
- safe ramp planning;
- emergency stop and force-stop flag lifecycle;
- pause/resume behavior;
- shutdown and disconnection;
- scan-range rejection and skipped measurements;
- behavior after partial hardware failure;
- simulated validation before bench validation;
- minimum human bench checklist.

Device-specific limits should remain in device documentation or configuration and be
linked from this document.

### `documents/known_issues.md`

Keep this evidence-based and short. For each issue record:

- title and affected subsystem;
- observed behavior;
- reproduction conditions;
- safety/data impact;
- current workaround;
- test or evidence needed to close it;
- related issue/branch/decision link.

Remove resolved issues rather than leaving ambiguous "future update" lists.

### `documents/decisions/`

Use an architecture decision record only for durable choices with meaningful tradeoffs,
such as:

- the single active scan engine;
- named laboratory profiles instead of editing one hardcoded startup file;
- channel signature rules;
- array-valued scan data representation;
- command-router ownership;
- vendor DLL distribution policy.

Each record should contain status, context, decision, consequences, alternatives, and
validation implications.

## 7. Device-local README files

Each active device should eventually have a consistent README containing:

1. Supported model(s).
2. Required Python and vendor dependencies.
3. Connection/address configuration.
4. Exposed getter and setter channels, units, and limits.
5. UI behavior.
6. Scan lifecycle behavior.
7. Stop/abort/shutdown behavior.
8. Standalone or mock test commands.
9. Hardware bench checklist.
10. Known limitations.

Do not duplicate the general three-layer device contract in every module. Link to
`documents/device_contract.md` and record only device-specific behavior.

## 8. Optional nested `AGENTS.md` files

Add nested instruction files only when a subtree needs mandatory rules that differ
from the root.

### Possible `core/AGENTS.md`

Use for rules such as:

- preserve scan recursion and data-index invariants;
- add regression tests for scan behavior;
- verify save/load when schema changes;
- avoid blocking UI-thread operations;
- synchronize scan and plot update payloads.

### Possible `tests/AGENTS.md`

Use for rules such as:

- tests must not connect to real instruments by default;
- use deterministic seeds for simulated noise/fault tests;
- isolate filesystem output in temporary directories;
- label hardware-only procedures clearly;
- do not weaken assertions to make a regression pass.

Do not create an `AGENTS.md` inside every device folder unless it adds real mandatory
constraints. Ordinary knowledge belongs in the device README.

## 9. Workflow for every future Codex task

### Step 1: Establish context

Codex should:

1. Confirm the repository root.
2. Read the active `AGENTS.md` chain.
3. Inspect branch and working-tree state.
4. Identify pre-existing changes.
5. Read the documentation index route for the subsystem.

### Step 2: Write a task contract

Before editing, define:

- requested outcome;
- acceptance criteria;
- non-goals;
- files/subsystems likely affected;
- persistence compatibility;
- hardware and safety exposure;
- validation level expected.

For a small, clear task this can be a concise commentary update. For a high-risk task,
record a fuller plan before implementation.

### Step 3: Trace the implementation

Follow the real call path. For example:

```text
UI action
  -> widget/main layer
  -> logic method or scan controller
  -> hardware/router operation
  -> returned data and signals
  -> persistence/plot/log consumers
```

Confirm every documentation claim against code before relying on it.

### Step 4: Assess risk

Classify the change:

- **Low:** documentation, pure helper, isolated UI text.
- **Medium:** schema, scan configuration, simulated device, plotting.
- **High:** scan traversal, concurrency, save/backup, force stop, hardware writes.

Higher-risk work requires more explicit invariants and regression coverage.

### Step 5: Implement minimally

- Preserve user changes.
- Modify the smallest coherent set of files.
- Keep UI/model/runtime/persistence changes synchronized.
- Avoid unrelated cleanup.
- Prefer configuration to new machine-specific hardcoding.
- Preserve backward compatibility unless the task explicitly changes the policy.

### Step 6: Validate in layers

Run the narrowest relevant test first, then broader hardware-independent coverage.
Record commands and results exactly. If a test cannot run, report the concrete reason.

Never use these statements interchangeably:

- "Python compilation passed."
- "Unit tests passed."
- "Mock-device integration passed."
- "GUI behavior was manually verified."
- "Real hardware bench test passed."

### Step 7: Synchronize documentation

Use this mapping:

| Change | Required documentation review |
| --- | --- |
| Scan runtime/schema | `scan_engine.md`, `data_format.md`, tests |
| Device API/lifecycle | Device README, `device_contract.md`, tests |
| Dependencies/setup | Root README, `environment_windows.md` |
| Stop/range/ramp behavior | `hardware_safety.md`, device README, tests |
| Major design choice | New or updated decision record |
| Confirmed unresolved defect | `known_issues.md` |

Do not update documentation merely to repeat implementation details that are easy to
discover and likely to drift.

### Step 8: Final handoff

Use this completion structure:

```text
Outcome:
Files changed:
Behavioral/API/schema impact:
Validation performed:
Validation not performed:
Hardware status:
Remaining risks:
Final Git state:
```

## 10. Recommended rollout sequence

### Phase 0: Preserve and classify

1. Ensure active source, branches, stashes, and unique local modules are backed up.
2. Inventory every current Markdown file.
3. Label each as canonical, device-specific, historical, duplicate, or obsolete.
4. Do not delete historical material during the first documentation pass.

### Phase 1: Make instructions load reliably

1. Draft a fresh root `AGENTS.md` using Section 3.
2. Verify Codex reports it as an active instruction source.
3. Keep the old `agent.md` temporarily for comparison.
4. After all useful content is routed elsewhere, retire or rename the old file.

### Phase 2: Establish navigation and setup

1. Create `documents/README.md`.
2. Correct the root README.
3. Select or build the canonical environment.
4. Create `environment_windows.md` and `testing.md`.

### Phase 3: Consolidate technical truth

1. Create `architecture.md`.
2. Merge the existing scan overview and logic documentation into `scan_engine.md`.
3. Create `device_contract.md`, using current code and `devices/mockDevice` as evidence.
4. Create `data_format.md` and `hardware_safety.md`.
5. Convert confirmed open problems into `known_issues.md`.

### Phase 4: Improve reproducibility

1. Add missing hardware-independent regression tests.
2. Standardize exact validation commands.
3. Introduce named laboratory profiles instead of repeatedly editing hardcoded startup
   equipment, addresses, and backup paths.
4. Add continuous integration for compilation and hardware-independent tests.

### Phase 5: Add reusable automation only after stabilization

When the device contract and tests have stabilized, consider a repository skill for
the repeated "add a ZMeter device" workflow. The skill could contain:

- a module template;
- channel and lifecycle checklists;
- a mock-test scaffold;
- a documentation template;
- a validation script.

Do not build the skill while the underlying contract is still changing rapidly.

## 11. Documentation maintenance process

### Ownership rule

The person or Codex task that changes behavior owns the associated documentation and
tests in the same change.

### Review cadence

- Review affected documentation during every behavioral change.
- Perform a small quarterly drift audit of commands, file paths, and public contracts.
- Generate branch/commit/dirty state on demand instead of storing it in durable docs.
- Check all "current," "active," and "default" statements especially carefully.

### Drift audit procedure

1. Verify every referenced file exists.
2. Verify named classes/functions still exist.
3. Compare documented schemas with current defaults and loaders.
4. Compare documented commands with the canonical environment.
5. Compare channel tables with discovered getter/setter methods.
6. Confirm known issues are still reproducible.
7. Remove duplicated or historical claims from canonical documents.

## 12. Definition of done for the workflow upgrade

The documentation/contribution system is ready when:

- Codex reliably loads the root `AGENTS.md`.
- The root instructions are concise and contain no volatile repository status.
- `documents/README.md` routes common tasks to one canonical document.
- Installation commands work from a clean Windows checkout.
- Scan and device contracts match current code and tests.
- Test commands clearly distinguish static, simulated, GUI, and hardware evidence.
- Hardware safety and stop/abort expectations are explicit.
- Every active device has sufficient module-specific documentation.
- Historical audits and transcripts are clearly separated from current truth.
- A future Codex task can identify what to read, what to change, how to validate, and
  what to report without reconstructing the entire project history.

## 13. Official Codex reference

The structure in this tutorial follows the official Codex guidance that repository
conventions belong in `AGENTS.md`, with more specific nested instructions applying to
their subtrees. See:

- https://learn.chatgpt.com/docs/agent-configuration/agents-md.md

