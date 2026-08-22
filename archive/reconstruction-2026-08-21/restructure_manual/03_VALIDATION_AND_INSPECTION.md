# Validation, Safety, and Inspection Plan

> **Archived 2026-08-21 — Reconstruction validation completed.** Preserved as
> historical implementation evidence. See `documents/reconstruction_status.md`
> and ADR 002 for the maintained outcome and remaining work.

## Validation principle

This is a behavior-preserving refactor. Passing new tests is insufficient; the agent must show that existing observable behavior did not change. Validate the smallest affected surface first, then run the broader hardware-independent suite.

No test may access real hardware. Hardware validation is always labeled **User-executed hardware test** and remains pending until the user supplies evidence.

## Baseline evidence required before editing

Record in the progress log:

- repository root, branch, base commit, upstream, and clean/dirty status;
- `main` commit used as the baseline and recovery tag status;
- Python version and executable;
- checked-in startup profile behavior and device labels;
- initial device/channel catalog produced by mock devices;
- exact hardware-independent commands inspected and run;
- results and known pre-existing failures;
- representative scalar JSON structure using temporary output, if a safe existing fixture/path is available;
- `git status --short --branch` after baseline checks.

Do not create baseline artifacts in `data/`, a lab save path, `Z:\`, or an existing PowerPoint log.

## Test layers and gates

### Gate A — Static and import safety

For every changed Python file:

- compile with Python 3.12 using `python -B -m py_compile`;
- inspect imports for vendor SDK, PyVISA manager, `clr`, DLL load, enumeration, or connection side effects;
- parse changed JSON profiles and UI XML without hardware access;
- test optional-driver imports with the dependency absent or replaced by a fake;
- verify resource paths from the repository root and after package moves.

Passing Gate A proves syntax/import structure only.

### Gate B — Configuration and registry unit tests

Test at least:

- valid mock profile;
- missing schema version, unknown version, wrong field type;
- duplicate/empty/invalid device IDs;
- unknown or disabled driver;
- unsupported connection keys;
- invalid channel-filter type and unknown channel;
- relative and invalid paths without writing output;
- missing optional SDK for disabled and enabled devices;
- registry factory receives only declared runtime services/arguments;
- parser and registry lookup do not enumerate or connect.

### Gate C — Manager lifecycle tests with mocks/fakes

Test at least:

- add one and multiple instances of one driver;
- duplicate add rejection;
- disconnected/connected/error state reporting;
- partial construction and partial connection cleanup;
- disconnect versus remove semantics;
- force-stop/stop/terminate/close ordering;
- idempotent repeated removal and application shutdown;
- shared runtime lease release using fakes;
- no UI blocking during simulated slow lifecycle operations;
- refusal during active scan, active queue, manual operation, or in-flight call;
- no call accepted after removal begins;
- rollback/catalog consistency when teardown fails.

Use deterministic events/barriers and bounded waits rather than real timing or long sleeps.

### Gate D — Catalog, router, and UI integration

Test at least:

- initial catalog exactly matches the baseline labels/channels/order;
- add refreshes getter/setter lists, device buttons, router, manual-set menus, scan menus, artificial-channel choices, and range-limit visibility;
- remove deletes every corresponding reference;
- repeated refresh does not duplicate buttons/actions/signals;
- labels containing underscores resolve correctly;
- channel allowlists behave exactly as before;
- router read/write requests use mock devices and fail clearly for removed devices;
- open scan definitions referencing a removed device follow the documented unresolved/refusal policy;
- widget show/focus/minimize behavior remains unchanged;
- close confirmation and final shutdown remain unchanged.

Run relevant GUI tests offscreen with mock devices only.

### Gate E — Existing scan regression

The restructure must not change:

- scalar getter storage shape/dtype/order;
- nested traversal and grouped reads/writes;
- skip/range/artificial-channel behavior;
- scalar averaged getters;
- pause/resume/stop/force-stop behavior;
- scan queue ordering and cleanup;
- signal payloads and plot update selection;
- autosave triggers and scan logging.

Run the canonical suites only after inspecting that they remain hardware-independent:

```powershell
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B -m unittest discover -s devices/mockDevice/tests -p "test_*.py" -v
```

During early phases, use the current pre-move mock test path. After the mechanical move, update the path once; do not keep duplicate test trees.

### Gate F — Persistence and output compatibility

Even though persistence code should not change, startup/catalog refactoring can indirectly affect scan definitions. With mocks and isolated temporary paths, verify:

- empty and populated scalar save/load round trip;
- top-level fields, levels, setters, getters, plots, comments, and log remain unchanged;
- NumPy array ordering and current `NaN` encodings remain unchanged;
- filename uniqueness and serial discovery remain unchanged;
- autosave still targets `autosave.json` at the same time/path semantics;
- backup-disabled behavior remains unchanged;
- no test attempts to access `Z:\` or a real PowerPoint log;
- representative downstream scalar loader still accepts output, when a safe fixture-based test exists.

PPT/COM checks must use a disposable presentation and do not imply hardware validation.

### Gate G — Final repository inspection

Before handoff:

1. Review `git diff --check`.
2. Review `git status --short --branch`.
3. Review changed file list and diff statistics.
4. Inspect every behavioral diff separately from moves.
5. Search for old root-level device imports and stale package paths.
6. Search for duplicate runnable packages, duplicate registries/managers, and dead startup paths.
7. Search for addresses, serials, credentials, private endpoints, generated data, `.pyc`, caches, DLLs, screenshots, PPT, and local profiles.
8. Confirm canonical documents match the executable path.
9. Confirm no 1D/2D getter, object-array storage, spectrum plotting, or persistence-schema work entered the diff.
10. Record exact tests not run and why.

## PR/commit inspection rules

Use reviewable units:

| Change type | Keep separate from |
| --- | --- |
| Configuration models | Active startup switch |
| Registry entries | Device behavior changes |
| Manager ownership | Runtime add/remove UI |
| Runtime catalog refresh | Mechanical package moves |
| Package move | Logic/style cleanup |
| Documentation | May accompany the behavior it documents, but not hide code changes |

Each phase commit/PR description must include:

- outcome and acceptance criteria;
- files and components affected;
- statement of behavior/API/schema/persistence/hardware impact;
- exact tests and results by evidence level;
- unrun tests and reason;
- user-executed hardware status;
- rollback method;
- remaining risks and dependent next phase.

## Handling maintenance changes during restructure

1. Independent or urgent change branches from current `main`.
2. It is reviewed, tested, and merged into `main` first.
3. At the next clean boundary, update the structure branch from `main`.
4. Re-run the affected phase tests plus scalar regression tests.
5. Record the integrated commit and conflict decisions in the progress log.
6. Never duplicate the fix manually in both histories.

If a new function depends on unfinished structural work, branch it from the smallest structure commit that provides the dependency and keep it as a clearly dependent draft. Do not merge incomplete structure into production merely to unblock it.

## Rollback strategy

- Recovery is through the tested baseline tag, `main`, and focused Git commits—not a copied legacy application.
- Each phase must be revertible without requiring later phases.
- Do not combine irreversible data migration with this project.
- On a failed phase, preserve logs/diffs, revert only with user authorization, and return to the last passing phase.
- On a failed user bench test, stop enabling the affected real driver/profile, preserve the mock-tested structure, and document the exact observed failure.

## User-executed hardware validation

After all software gates pass, prepare but do not execute a minimal bench procedure for each enabled real-device family:

1. exact deployed commit/profile/environment/SDK and initial physical state;
2. start with one device enabled;
3. verify connection and existing read-only status behavior;
4. verify one previously established safe operation within documented units/limits;
5. stop/force-stop and confirm current behavior;
6. disconnect/remove while the scan system is idle;
7. verify removal is rejected during a dependent active scan using a safe controlled setup;
8. close the application and independently verify final physical/device state;
9. record logs, observed results, pass/fail, and limitations.

The user must review and execute this procedure. Success applies only to the exact observed model, configuration, and operation.

## Final handoff checklist

- [ ] Objective achieved without out-of-scope behavior.
- [ ] Existing scalar behavior is unchanged.
- [ ] Default startup remains mock-only and hardware-safe.
- [ ] All required software gates pass.
- [ ] No real hardware test was executed by the agent.
- [ ] No measurement/persistence schema changed.
- [ ] No legacy runnable copy or duplicate active path remains.
- [ ] Documentation and progress log are complete.
- [ ] Final diff contains no unrelated changes or generated artifacts.
- [ ] Source branch is ready for user review but not merged/pushed without authorization.
- [ ] Array-valued getter work remains deferred.
