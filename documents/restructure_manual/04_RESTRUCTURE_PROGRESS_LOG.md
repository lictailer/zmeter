# Restructure Progress Log

## Rules

This is the inspection ledger for the restructure. The implementation agent must update it after baseline inspection and after every phase, maintenance integration, scope decision, test gate, and user review.

- Append new entries; do not rewrite prior evidence to make later results look cleaner.
- Correct mistakes with a dated correction entry.
- Record exact commands and results; never write “tests pass” without identifying them.
- Record files changed, behavior impact, risks, and remaining work.
- Do not include credentials, instrument responses containing sensitive information, or private endpoints.
- Before implementation, copy the complete manual to `documents/restructure_manual/` in the authorized source worktree. All implementation entries must be written to that in-repository copy; the external staged copy remains the manual-creation record only.

## Manual-creation baseline

| Field | Value |
| --- | --- |
| Date | 2026-08-18 |
| Author | Codex documentation task |
| Source repository inspected | `C:\Users\Taylo\Documents\GitHub\zmeter` |
| Observed source branch | `codex/structural_update_vibeeee` |
| Observed source status | Clean |
| Source files changed by manual creation | None |
| Manual workspace | `C:\Users\Taylo\Documents\ChatGPT\zmeter\restructure_manual` |
| Hardware tests | Not run; prohibited for agent |
| Product tests | Not run; documentation-only task |

## Baseline implementation entry — required before code changes

Copy and complete:

```markdown
## YYYY-MM-DD — Phase 0 baseline

- Agent/operator:
- Authorized repository root:
- Current branch:
- Current commit:
- Upstream:
- Approved `main` baseline commit:
- Recovery tag and commit:
- Initial `git status --short --branch`:
- Python environment/version/executable:
- Checked-in startup profile/devices:
- Relevant pre-existing changes or failures:
- Hardware-impact assessment:
- Persistence-impact assessment:

### Commands and evidence

| Command/check | Evidence level | Result | Files/output created |
| --- | --- | --- | --- |
| | | | |

### Baseline decision

- Safe to begin Phase 1: Yes/No
- Blockers or user decisions:
```

## Phase entry template

```markdown
## YYYY-MM-DD — Phase N: <name>

### Intended outcome

- Acceptance criteria:
- Explicit non-goals:
- Base commit:
- Related maintenance commits integrated:

### Changes

- Files added:
- Files modified:
- Files moved:
- Files removed:
- API/config impact:
- Existing behavior impact: None / explain and cite approval
- Scan/data/schema impact: None / explain and cite approval
- Hardware/lifecycle impact:
- Documentation updated:

### Validation

| Exact command/check | Environment | Evidence level | Result | Duration/output |
| --- | --- | --- | --- | --- |
| | | | | |

- Tests not run and reason:
- User-executed hardware test status:

### Inspection

- `git diff --check`:
- `git status --short --branch`:
- Unexpected/unrelated changes:
- Generated artifacts removed:
- Security/configuration review:

### Decision

- Gate passed: Yes/No
- Commit(s):
- Rollback method:
- Remaining risks:
- Next authorized phase:
- User input required:
```

## Maintenance integration template

```markdown
## YYYY-MM-DD — Integrated maintenance update

- Production issue/feature:
- `main` commit integrated:
- Structure-branch commit before integration:
- Integration method:
- Conflicts and resolutions:
- Why resolution preserves production behavior:
- Focused tests:
- Broader regressions:
- Final status:
```

## Scope decision template

```markdown
## YYYY-MM-DD — Scope/architecture decision

- Question:
- Current verified behavior:
- Options considered:
- Safety/data/maintenance tradeoffs:
- Decision:
- User approval reference, if scope changed:
- Files/tests/documentation affected:
```

## User hardware result template

```markdown
## YYYY-MM-DD — User-executed hardware result

- Executed by:
- Commit/profile/environment:
- Device model/firmware/interface:
- Approved limits/units/initial state:
- Procedure:
- Expected result:
- Observed result:
- Logs/data supplied:
- Final physical/device state independently checked:
- Pass/fail:
- Limitations and follow-up:
```

## Final completion entry — required

```markdown
## YYYY-MM-DD — Restructure completion

- Final branch/commit:
- Baseline tag/commit:
- High-level outcome:
- Final runtime path:
- Final directory layout verified:
- Existing behavior compatibility summary:
- Configuration/profile behavior:
- Runtime add/disconnect/remove behavior and guards:
- Full hardware-independent commands/results:
- Tests not run:
- User-executed hardware status:
- Persistence/schema impact:
- Safety impact:
- Documentation updated:
- Remaining risks/known issues:
- Deferred array-valued getter work confirmed absent:
- Final `git status --short --branch`:
- Ready for user review: Yes/No
- Remote/main merge actions performed: None unless separately authorized
```

## 2026-08-18 — Phase 0 baseline

- Agent/operator: Codex implementation task
- Authorized repository root: `C:\Users\Taylo\Documents\GitHub\zmeter`
- Current branch: `codex/structural_update_vibeeee`
- Current commit at inspection: `b98a1666aad2132316f535738457df928f3147ac`
- Upstream: None configured for the structure branch
- Approved `main` baseline commit: `b98a1666aad2132316f535738457df928f3147ac` (local `main` and `origin/main` matched at inspection)
- Recovery tag and commit: local annotated tag `pre-structure-v2` at `b98a1666aad2132316f535738457df928f3147ac`; not pushed
- Initial `git status --short --branch`: branch header plus only the expected untracked `documents/restructure_manual/` copy; the five files matched the staged manual by SHA-256
- Python environment/version/executable: `zmeter_May2026`; Python 3.12.12; `C:\Users\Taylo\anaconda3\envs\zmeter_May2026\python.exe`; PyQt6/Qt 6.9.1; NumPy 2.4.1
- Checked-in startup profile/devices: `start_zmeter.py` created `mock_device_1` then `mock_device_2`; backup disabled; default save path `<repository>\data` when launched from the repository root
- Relevant pre-existing changes or failures: the manual copy was expected user-supplied work and was preserved in commit `5092f94`; the PATH Python 3.12.10 lacked PyQt6 and NumPy, producing eight import errors before the maintained environment was selected
- Hardware-impact assessment: none; imports, fixtures, and setup were inspected before execution, all validation used fakes/simulators/offscreen Qt, and no real device profile, discovery backend, vendor loader, or hardware command was run
- Persistence-impact assessment: none; one representative scalar JSON was written only inside an OS temporary directory and removed afterward

### Commands and evidence

| Command/check | Evidence level | Result | Files/output created |
| --- | --- | --- | --- |
| `git rev-parse --show-toplevel`; `git status --short --branch`; `git branch --show-current`; `git rev-parse HEAD`; `git rev-parse main`; `git merge-base --is-ancestor main HEAD` | Static inspection | Correct root and branch; HEAD equaled `main`; ancestor exit 0 | None |
| `git remote -v`; `git branch -vv`; `git tag --list 'pre-structure*'` | Static inspection | `origin/main` matched baseline; structure branch had no upstream; no recovery tag initially | None |
| `python -c "import sys; print(sys.version); print(sys.executable)"` | Environment inspection | PATH Python 3.12.10 at `C:\Users\Taylo\AppData\Local\Programs\Python\Python312\python.exe` | None |
| `python -B -m unittest discover -s tests -p "test_*.py" -v` | Environment failure; not product evidence | 23 tests passed and 8 modules failed import because PATH Python lacked PyQt6/NumPy | None |
| `C:\Users\Taylo\anaconda3\envs\zmeter_May2026\python.exe -B -m unittest discover -s tests -p "test_*.py" -v` | Hardware-independent unit/mock/offscreen GUI | 61 tests passed in 1.465 s | OS temporary Kinesis fixtures only; removed by tests |
| `C:\Users\Taylo\anaconda3\envs\zmeter_May2026\python.exe -B -m unittest discover -s mockDevice/tests -p "test_*.py" -v` | Mock/simulation/offscreen GUI | 18 tests passed in 0.293 s | None |
| Offscreen startup/catalog characterization using `RuntimeServices`, `create_equipment()`, and `MainWindow` with an OS temporary save path | Hardware-independent integration | Labels/buttons were `mock_device_1`, `mock_device_2`; each exposed setters `channel_A`, `channel_B`, `ramp_channel_A`, `ramp_channel_B` and getters `channel_A`, `channel_B`, `random_channel`; default and artificial catalogs also matched | OS temporary directory only; removed |
| Offscreen `Scan.when_save_clicked()` characterization with mock devices, a patched-false `Z:\` existence check, and OS temporary output | Persistence simulation | One JSON written and parsed; top-level keys were `levels`, `data`, `plots`, `name`, `plots_per_page`, `comments`, `scan_log`; scalar sample encoded as `[1.25, NaN]`; comments and list-valued log preserved | One temporary JSON; removed |
| `git tag -a pre-structure-v2 b98a1666aad2132316f535738457df928f3147ac -m "Recovery point before device-management restructure"` | Local recovery control | Local annotated recovery tag created | Local Git tag only; no remote action |
| `git diff --check`; `git status --short --branch` before recording this entry | Static inspection | No whitespace errors; only expected manual files present before their first commit | None |

### Baseline decision

- Safe to begin Phase 1: No, pending the two verified contract/current-behavior conflicts recorded below.
- Blockers or user decisions: decide automatic VISA discovery behavior and unknown configured-channel handling before configuration/registry implementation.

## 2026-08-18 — Scope/architecture decision (pending): automatic VISA discovery

- Question: Must enabled VISA widgets retain their current automatic deferred resource discovery, or must discovery become an explicit operator action?
- Current verified behavior: `documents/architecture.md` and `tests/test_visa_widget_construction.py` require dropdown VISA widgets to schedule worker-thread resource enumeration on the next Qt event-loop turn after construction. The injected test manager is enumerated but no resource is opened.
- Options considered: (1) preserve automatic deferred enumeration for enabled VISA widgets while making configuration parsing, disabled entries, registry lookup, and manager construction side-effect free; (2) change all VISA widgets to enumerate only after an explicit operator refresh action.
- Safety/data/maintenance tradeoffs: option 1 preserves operator behavior but requires a narrow exception to the manual's absolute construction-triggered-enumeration ban; option 2 follows that ban literally but changes established startup behavior across maintained VISA devices.
- Decision: Pending user approval; no Phase 1 source edits made.
- User approval reference, if scope changed: Pending.
- Files/tests/documentation affected: future registry/manager tests, `tests/test_visa_widget_construction.py`, `documents/architecture.md`, and possibly VISA widget implementations.

## 2026-08-18 — Scope/architecture decision (pending): unknown profile channels

- Question: Must an explicit profile channel allowlist containing an unknown channel fail validation, or retain the current silent-skip behavior?
- Current verified behavior: `MainWindow.filter_scan_channels()` and `documents/device_contract.md` silently ignore unknown requested names. The restructure manual's profile rules and Gate B require unknown explicit channels to be reported/rejected.
- Options considered: (1) reject the entire profile before device construction and report all unknown channels; (2) preserve silent skipping; (3) accept the profile with warnings.
- Safety/data/maintenance tradeoffs: option 1 implements deterministic validated configuration and prevents a typo from silently omitting a measurement channel, but changes current startup-filter behavior; option 2 preserves behavior but weakens the approved validated-profile capability; option 3 leaves partially accepted safety-relevant configuration, which the manual otherwise forbids.
- Decision: Pending user approval; no Phase 1 source edits made.
- User approval reference, if scope changed: Pending.
- Files/tests/documentation affected: future configuration models/loader tests, `MainWindow` integration, `documents/device_contract.md`, startup/profile documentation.

## 2026-08-18 — Scope/architecture decision resolved: automatic VISA discovery

- Question: Resolve the pending conflict between established deferred VISA discovery and the manual's construction-side-effect prohibition.
- Current verified behavior: Enabled maintained VISA widgets schedule resource enumeration on the next Qt event-loop turn after widget construction; they do not open an instrument session during discovery.
- Decision: Preserve the established deferred automatic VISA discovery behavior for enabled VISA widgets. Configuration parsing, disabled profile entries, registry lookup, and manager construction must remain free of vendor import, enumeration, connection, and other hardware effects. Constructing an enabled VISA widget may continue to schedule its existing deferred discovery behavior.
- User approval reference: User response on 2026-08-18: "Preserve deferred automatic VISA discovery."
- Future-update note: Converting enabled VISA widgets to explicit operator-only discovery is deferred and requires a separately approved behavior change with device/UI regression review.
- Files/tests/documentation affected: Preserve `tests/test_visa_widget_construction.py`; document the narrow enabled-widget exception in configuration/architecture documentation and manager tests.

## 2026-08-18 — Scope/architecture decision resolved: unknown profile channels

- Question: Resolve the pending conflict between current silent channel-filter skipping and the manual's proposed rejection of unknown configured channels.
- Current verified behavior: `MainWindow.filter_scan_channels()` ignores unknown names in explicit getter/setter allowlists while retaining all recognized names.
- Decision: Preserve silent skipping of unknown profile channel names. Validate the allowlist container and entry types, but do not reject a profile, warn, or fail device construction solely because a syntactically valid channel name is not exposed by the device. The corresponding Gate B unknown-channel rejection requirement is superseded for this restructure.
- User approval reference: User response on 2026-08-18: "keep the current silent-skip behavior, write it down for future update."
- Future-update note: Strict rejection or warnings for unknown configured channels are explicitly deferred. Either behavior would alter the current profile/device-filter contract and requires separate approval plus migration guidance for existing lab profiles.
- Files/tests/documentation affected: Configuration/manager tests must assert silent skipping; retain and later update `documents/device_contract.md`, profile documentation, and `MainWindow` integration to state this compatibility rule.

## 2026-08-18 — Phase 0 blocker resolution

- The two mandatory-stop decisions recorded during Phase 0 were answered by the user.
- Safe to begin Phase 1: Yes, subject to the resolved compatibility exceptions above.
- No source behavior changed while resolving the decisions.

## 2026-08-18 — Phase 1: configuration models and validation

### Intended outcome

- Acceptance criteria: immutable profile models; deterministic, aggregated validation; repository-root-relative paths; checked-in hardware-safe mock profile matching the two current startup labels; no active startup switch; no driver/vendor import, enumeration, construction, or connection during loading.
- Explicit non-goals: registry/factory construction, manager ownership, launcher changes, runtime mutation, real-device profiles, and strict unknown-channel rejection.
- Base commit: `6e89226`
- Related maintenance commits integrated: None.

### Changes

- Files added: `core/device_management/__init__.py`, `core/device_management/models.py`, `core/device_management/config.py`, `config/README.md`, `config/profiles/mock.json`, `config/profiles/example_lab.json`, `tests/test_device_config.py`.
- Files modified: `.gitignore` for local profiles and `.restructure_tmp/` validation artifacts.
- Files moved: None.
- Files removed: None.
- API/config impact: added schema version 1 profile loading and immutable `ProfileConfig`/`DeviceConfig` models. Added optional `connect_on_start` (default false). Relative profile and configured data paths resolve from the repository root without probing configured output/network paths.
- Existing behavior impact: None. `start_zmeter.py` still owns the active startup path. Per the user-approved compatibility decision, syntactically valid unknown channel names remain in the model and are silently skipped later by existing channel filtering.
- Scan/data/schema impact: None. Measurement JSON and scan behavior were not changed.
- Hardware/lifecycle impact: None. The loader accepts only reviewed registry metadata and imports or constructs no device.
- Documentation updated: added `config/README.md` with path, local-profile, safety, and deferred unknown-channel policy.

### Validation

| Exact command/check | Environment | Evidence level | Result | Duration/output |
| --- | --- | --- | --- | --- |
| `python -B -m py_compile core/device_management/__init__.py core/device_management/models.py core/device_management/config.py tests/test_device_config.py` | `zmeter_May2026` Python 3.12.12 with `PYTHONPYCACHEPREFIX=.restructure_tmp/pycache` | Static | Passed after redirecting bytecode to the ignored validation directory | Exit 0 |
| `python -B -m unittest discover -s tests -p 'test_device_config.py' -v` | `zmeter_May2026` | Hardware-independent unit/subprocess | 13 tests passed, including duplicate-key rejection, aggregate errors, deep immutability, original JSON indices, checked profile values, silent unknown-channel retention, and fresh-process import safety | 0.193 s |
| `python -B -m unittest discover -s tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen where requested by tests | Hardware-independent unit/mock/offscreen GUI | 74 tests passed | 1.616 s |
| `python -B -m unittest discover -s mockDevice/tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen | Mock/simulation/offscreen GUI | 18 tests passed | 0.312 s |
| Parse every `config/profiles/*.json` with Python `json` | `zmeter_May2026` | Static | 2 profile JSON files parsed | Exit 0 |
| Fresh-process profile-load sentinel in `test_device_config.py` | `zmeter_May2026` | Import-safety unit | No `mockDevice`, `devices`, `pyvisa`, or `clr` module imported | Passed |
| `rg` scan for credentials/private endpoints/real addresses in Phase 1 files | Repository root | Security/config inspection | No matches | None |

- Validation incidents: the first compile attempt was blocked by sandbox denial when `py_compile` tried to create source-tree bytecode; it was rerun successfully with bytecode confined to `.restructure_tmp/`. One combined quiet regression invocation emitted no output and was interrupted after approximately 50 seconds; the same core and mock commands were then run separately with verbose output and both passed.
- Tests not run and reason: no manual GUI launch and no real-device/vendor tests; Phase 1 is a pure configuration layer and agent hardware execution is prohibited.
- User-executed hardware test status: Not applicable to this phase; not run.

### Inspection

- `git diff --check`: Passed before commit.
- `git status --short --branch`: Clean immediately after Phase 1 source commit; this log entry is the only subsequent change.
- Unexpected/unrelated changes: None.
- Generated artifacts removed: no generated artifact is tracked; ignored `.restructure_tmp/pycache` is retained for later phase compilation and must be removed before final handoff.
- Security/configuration review: checked-in profiles are mock/empty only; no credentials, private endpoints, real instrument addresses, serials, or lab backup paths were added. Local profile patterns are ignored.

### Decision

- Gate passed: Yes.
- Commit(s): `25c4767` (`Add validated device profiles`); this evidence entry follows in a documentation commit.
- Rollback method: revert the Phase 1 source commit and its evidence commit; recovery tag remains `pre-structure-v2`.
- Remaining risks: connection-field availability and factory argument enforcement depend on the Phase 2 reviewed registry; active startup has not yet consumed the profile.
- Next authorized phase: Phase 2 — reviewed lazy driver registry, starting with `mock_device` only.
- User input required: None.

## 2026-08-18 — Phase 2: reviewed lazy driver registry

### Intended outcome

- Acceptance criteria: a code-reviewed registry maps stable driver IDs to explicit factories, configuration schemas, runtime-service dependencies, lifecycle callbacks, and state probes; lookup remains free of device/vendor imports and hardware effects; disabled entries are never constructed; the initial registry contains only the hardware-safe `mock_device` driver.
- Explicit non-goals: active launcher integration, dynamic device mutation, real-device registrations, hardware connection, device package moves, or changing deferred VISA discovery.
- Base commit: `bd784fa`.
- Related maintenance commits integrated: None.

### Changes

- Files added: `core/device_management/registry.py`, `tests/test_device_registry.py`.
- Files modified: `core/device_management/__init__.py`, `mockDevice/mock_device_logic.py`.
- Files moved: None.
- Files removed: None.
- API/config impact: added `DriverRegistry`, immutable `DriverRegistration`, guarded `DriverAdapter`, typed registry errors, and `build_default_registry()`. The default registry exposes only `mock_device`, with an explicit `address` schema and no runtime-service dependency.
- Existing behavior impact: no active startup path changed. `MockDeviceLogic.is_busy()` adds a synchronized public state probe over existing worker/ramp state without changing discovery, reads, writes, or lifecycle behavior.
- Scan/data/schema impact: None.
- Hardware/lifecycle impact: registry lookup performs no device/vendor import. Construction is lazy and allowed only for enabled, registered, schema-valid entries. Adapter termination and widget closing are serialized, one-attempt, and idempotent after success or partial failure; later lifecycle calls are rejected after termination.
- Documentation updated: this append-only evidence entry.

### Validation

| Exact command/check | Environment | Evidence level | Result | Duration/output |
| --- | --- | --- | --- | --- |
| `python -B -m py_compile core/device_management/__init__.py core/device_management/registry.py mockDevice/mock_device_logic.py tests/test_device_registry.py` | `zmeter_May2026` Python 3.12.12 with `PYTHONPYCACHEPREFIX=.restructure_tmp/pycache` | Static | Passed | Exit 0 |
| `python -B -m unittest discover -s tests -p 'test_device_registry.py' -v` | `zmeter_May2026`, offscreen | Hardware-independent unit/subprocess/mock GUI | 11 tests passed, including fresh-process lazy lookup, optional-driver isolation, schema revalidation, runtime-service allowlisting, concurrent partial teardown, failed-close idempotence, terminated-state guards, and disconnected mock construction | 0.252 s |
| `python -B -m unittest discover -s tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen where requested by tests | Hardware-independent unit/mock/offscreen GUI | 85 tests passed | 1.817 s |
| `python -B -m unittest discover -s mockDevice/tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen | Mock/simulation/offscreen GUI | 18 tests passed | 0.322 s |
| Fresh-process default-registry sentinel in `test_device_registry.py` | `zmeter_May2026` | Import-safety unit | No `mockDevice`, PyVISA, pythonnet, NI, Kinesis, or other watched device/vendor module imported during registry build/lookup | Passed |
| `rg` scan for credentials/secrets in Phase 2 files | Repository root | Security/config inspection | No matches | None |
| `rg` scan for top-level device/vendor imports in `registry.py` | Repository root | Static import inspection | No matches; the mock widget import is scoped inside its factory | None |

- Validation incidents: the first validation invocation used `pytest`, which is not installed in the maintained environment, and was therefore an environment/tool-selection failure rather than product evidence. The first compile invocation was sandbox-blocked while writing ignored bytecode under the source repository; it was rerun with the established temporary-output approval and passed. All documented `unittest` commands then passed.
- Tests not run and reason: no manual GUI launch and no real-device/vendor tests; only the in-process mock was constructed, and agent hardware execution is prohibited.
- User-executed hardware test status: Not applicable to this phase; not run.

### Inspection

- `git diff --check`: Passed before commit.
- `git status --short --branch`: Clean immediately after the Phase 2 source commit; this log entry is the only subsequent change.
- Unexpected/unrelated changes: None.
- Generated artifacts removed: no generated artifact is tracked; ignored `.restructure_tmp/pycache` remains temporary and must be removed before final handoff.
- Security/configuration review: no credentials, private endpoints, real instrument addresses, serials, or vendor paths were introduced. Disabled/unavailable drivers cannot invoke a factory, and one unavailable factory does not prevent a separately registered healthy driver from being used.

### Decision

- Gate passed: Yes.
- Commit(s): `82b0639` (`Add lazy mock device registry`); this evidence entry follows in a documentation commit.
- Rollback method: revert the Phase 2 source commit and its evidence commit; recovery tag remains `pre-structure-v2`.
- Remaining risks: only `mock_device` is registered; real drivers require individual lifecycle, dependency, connection-schema, and busy-state review. Active startup still uses the legacy direct construction path until the manager/profile integration phases.
- Next authorized phase: Phase 3 — static `DeviceManager` ownership and unified teardown while preserving startup behavior.
- User input required: None.

## 2026-08-18 — Phase 3: static manager ownership and safe unified teardown

### Intended outcome

- Acceptance criteria: one manager transactionally owns the unchanged two-mock startup set; `MainWindow` consumes one immutable ordered snapshot; scan lifecycle calls delegate without changing driver behavior; application shutdown proves scan/queue/output quiescence before ordered device teardown and releases shared runtimes only after successful device cleanup.
- Explicit non-goals: activating the checked JSON profile, runtime add/remove, rebuildable catalogs, real-driver registration, device-package moves, explicit-only VISA discovery, or strict unknown-channel rejection.
- Base commit: `fb86fd6`.
- Related maintenance commits integrated: None.

### Changes

- Files added: `core/device_management/manager.py`, `tests/test_device_manager.py`, `tests/test_device_manager_integration.py`, `tests/test_scanlist_shutdown.py`.
- Files modified: `core/device_management/__init__.py`, `core/mainWindow.py`, `core/scan.py`, `core/scan_logic.py`, `core/scanlist.py`, `start_zmeter.py`, `tests/test_device_registry.py`.
- Files moved: None.
- Files removed: None.
- API/config impact: added immutable device snapshots/record views, explicit manager states, transactional one-profile loading, typed lifecycle/startup/thread errors, aggregated lifecycle reports, and idempotent ordered teardown. `MainWindow` accepts a manager while retaining its legacy constructor path for this focused transition. The active launcher uses a temporary in-memory two-mock `ProfileConfig`; switching to `config/profiles/mock.json` remains Phase 4.
- Existing behavior impact: startup labels, button order, window titles, disconnected mock state, channel order, router labels, menus, close confirmation, and driver start/stop exception behavior remain unchanged. Deferred automatic VISA discovery and silent skipping of unknown configured channels remain intact and covered by regression tests.
- Scan/data/schema impact: measurement schema, scan signals, queue semantics, save/autosave behavior, and serial numbering are unchanged. A shutdown-only barrier now seals new scan/manual/queue starts, requests stop, waits for direct/queued scan threads and deferred output finalizers, and closes scan widgets only after quiescence.
- Hardware/lifecycle impact: manager load is atomic and disabled devices are not constructed. Final teardown preserves the existing global order: force-stop every device, stop every applicable device, then terminate and close each device in profile order. Construction and final QWidget teardown are restricted to the manager owner/UI thread. Failures are aggregated without skipping later devices; failed teardown prevents shared-runtime release.
- Documentation updated: this append-only evidence entry.

### Validation

| Exact command/check | Environment | Evidence level | Result | Duration/output |
| --- | --- | --- | --- | --- |
| `python -X pycache_prefix=C:\Users\Taylo\Documents\ChatGPT\zmeter\.restructure_phase3_pycache -m py_compile core/device_management/__init__.py core/device_management/manager.py core/mainWindow.py core/scan.py core/scan_logic.py core/scanlist.py start_zmeter.py tests/test_device_manager.py tests/test_device_manager_integration.py tests/test_device_registry.py tests/test_scanlist_shutdown.py` | `zmeter_May2026` Python 3.12.12 | Static | Passed; redirected bytecode directory removed immediately after validation | Exit 0 |
| `python -B -m unittest tests.test_device_manager tests.test_device_manager_integration -v` | `zmeter_May2026`, offscreen | Hardware-independent unit/mock/offscreen GUI | 28 tests passed, including transactional rollback, teardown order/error aggregation, real-QWidget owner-thread rejection, exact catalog compatibility, and launcher failure policy | 2.994 s |
| `python -B -m unittest discover -s tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen where requested by tests | Hardware-independent unit/mock/offscreen GUI | 125 tests passed | 5.255 s |
| `python -B -m unittest discover -s mockDevice/tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen | Mock/simulation/offscreen GUI | 18 tests passed | 0.313 s |
| Independent adversarial shutdown/manager audit | `zmeter_May2026`, offscreen | Safety/race review | No confirmed defects after fixes; independent rerun passed 125 core and 18 mock tests | 5.436 s / 0.307 s |
| Fresh-process manager/registry sentinels | `zmeter_May2026` | Import-safety unit | No mock, VISA, pythonnet, NI, Kinesis, or other watched device/vendor import during manager/default-registry lookup | Passed |
| `git diff --check` plus focused credential/secret scan | Repository root | Static/security inspection | Passed; only expected LF/CRLF conversion warnings and no secret matches | None |

- Validation incidents: an early full-suite run in an independent workstream observed one timing race in the existing VISA refresh test; its isolated retry passed, and two later complete maintained-environment runs passed without failure. Adversarial review identified and drove fixes for late scan creation during event pumping, incomplete finalizer tracking, lifecycle-error propagation, manager state sealing, disconnected-driver fidelity, startup rollback/runtime ordering, abnormal-exit status, and UI-thread final teardown before the phase was accepted.
- Tests not run and reason: no interactive GUI session and no physical-device/vendor integration tests were run; agent hardware execution is prohibited and this phase registers only the in-process mock.
- User-executed hardware test status: Not applicable to this mock-only phase; not run.

### Inspection

- `git diff --check`: Passed before commit.
- `git status --short --branch`: Clean immediately after the Phase 3 source commit; this log entry is the only subsequent change.
- Unexpected/unrelated changes: None.
- Generated artifacts removed: the external redirected Phase 3 bytecode directory was verified and removed. No generated source-repository artifact is tracked.
- Security/configuration review: no credentials, private endpoints, real instrument addresses, serials, vendor paths, or hardware-enabling values were added. The active manager creates only the two disconnected mock widgets and does not touch shared VISA/Kinesis runtimes.

### Decision

- Gate passed: Yes.
- Commit(s): `14128f6` (`Add static device manager ownership`); this evidence entry follows in a documentation commit.
- Rollback method: revert the Phase 3 source commit and its evidence commit; recovery tag remains `pre-structure-v2`.
- Remaining risks: the shutdown deadline is cooperative for a synchronous GUI callback already executing; an over-budget callback is detected before scan widgets, devices, or runtimes are torn down. Runtime mutation and safe catalog reconciliation are not yet enabled. Active startup still uses the temporary static profile source until Phase 4.
- Next authorized phase: Phase 4 — activate the validated checked-in profile loader in the launcher.
- User input required: None.
