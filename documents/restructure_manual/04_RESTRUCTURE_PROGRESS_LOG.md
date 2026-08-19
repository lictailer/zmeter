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

## 2026-08-18 — Phase 4: validated profile-driven launcher

### Intended outcome

- Acceptance criteria: `start_zmeter.py` is a device-agnostic launcher; the checked-in mock JSON profile is the default; an explicit `--profile` selects repository-relative or absolute profiles without fallback; profile paths feed `MainWindow`; labels, filters, disconnected state, title, and shutdown order remain unchanged; startup validation remains free of device/vendor effects.
- Explicit non-goals: registering real devices, connecting hardware, runtime device mutation, rebuildable catalogs, device-package moves, explicit-only VISA discovery, or strict unknown-channel rejection.
- Base commit: `3b6c87b`.
- Related maintenance commits integrated: None.

### Changes

- Files added: None.
- Files modified: `start_zmeter.py`, `tests/test_device_manager_integration.py`, `tests/test_startup_shared_runtimes.py`, `config/README.md`, `README.md`, `project_structure.md`, `documents/architecture.md`, `documents/environment_windows.md`, `ANC300/README.md`, `auto_position/README.md`, `BBD30X/README.md`.
- Files moved: None.
- Files removed: None.
- API/config impact: the launcher now accepts `--profile PATH`, lets Qt consume its recognized general options first, then strictly rejects unknown launcher options. It validates the selected profile against reviewed registry metadata, constructs one manager, and passes the profile's save/backup paths to `MainWindow`. Missing or invalid explicit profiles print and display the aggregate error, exit nonzero, and never fall back or construct a manager/device.
- Existing behavior impact: the checked-in default still creates `mock_device_1` then `mock_device_2`, leaves both disconnected, disables backup, saves under `<repository>/data`, preserves exact channel/menu/catalog ordering and the `Main Window` title, and retains Phase 3 shutdown ordering. A new end-to-end test proves that known channels survive while unknown configured channel names are silently skipped.
- Scan/data/schema impact: None. Measurement/persistence schemas and scan execution are unchanged.
- Hardware/lifecycle impact: `start_zmeter.py` imports no device or vendor module and contains no device address, serial, channel list, or connection command. Disabled reviewed entries are validated but never reach their lazy factory. The default path uses only the in-process mock and leaves VISA/Kinesis services uninitialized.
- Documentation updated: launcher/profile selection, local-profile policy, architecture/ownership, Windows setup, maintained structure, and stale device-local `create_equipment()` guidance.

### Implementation scope resolution

- Phase 4's thin-launcher rule conflicts with its sequencing note to retain commented real-device examples until reviewed registry/profile replacements exist. Those examples were inactive, untested, included lab-specific addresses/serials, and were not part of the executable startup contract.
- Resolution used for this phase: remove the inactive comments from the launcher to enforce the component rule forbidding device-specific imports/values, retain their recovery history in the baseline and recovery tag, and do not register, enable, or claim profile support for any corresponding real driver. Future real-driver enablement still requires its own reviewed registry entry, schema, lifecycle/busy adapter, local ignored profile, and user-executed hardware validation.
- This resolution changes no runtime behavior and does not copy the retired lab values into shared profiles or documentation.

### Validation

| Exact command/check | Environment | Evidence level | Result | Duration/output |
| --- | --- | --- | --- | --- |
| `python -X pycache_prefix=C:\Users\Taylo\Documents\ChatGPT\zmeter\.restructure_phase4_pycache -m py_compile start_zmeter.py tests/test_device_manager_integration.py tests/test_startup_shared_runtimes.py` | `zmeter_May2026` Python 3.12.12 | Static | Passed; redirected bytecode directory verified and removed | Exit 0 |
| `python -B -m unittest discover -s tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen where requested by tests | Hardware-independent unit/mock/offscreen GUI | Fresh complete rerun passed 133 tests | 9.009 s |
| `python -B -m unittest discover -s mockDevice/tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen | Mock/simulation/offscreen GUI | 18 tests passed | 0.307 s |
| `python -B start_zmeter.py -platform offscreen --help` | `zmeter_May2026`, offscreen | CLI/Qt boundary | Help exited 0; Qt consumed `-platform` before strict launcher parsing | 1.355 s |
| Parse every `config/profiles/*.json` with Python `json` | `zmeter_May2026` | Static | 2 profile JSON files parsed | Exit 0 |
| Permanent fresh-process launcher import sentinel | `zmeter_May2026` | Import-safety unit | No `mockDevice`, `devices`, PyVISA, pythonnet, NI, Kinesis, or other watched device/vendor module imported | Passed |
| Independent Phase 4 audit | `zmeter_May2026`, offscreen/fake runtimes | CLI/config/lifecycle review | Clean after fixes; 46 focused tests passed, including deferred VISA and actual Qt argument consumption | Passed |
| `git diff --check`, active `create_equipment` search, direct launcher device/vendor import search, and credential/secret scan | Repository root | Static/security inspection | Passed; no active references/imports/secret matches, with expected LF/CRLF conversion warnings only | None |

- Validation incidents: the first final full-suite invocation had one timeout in the pre-existing deferred VISA refresh timing test. The test passed immediately in isolation in 0.083 s, and the unchanged complete suite then passed all 133 tests. The independent audit found a `parse_known_args` typo/fallback risk, stale device-local `create_equipment()` instructions, and missing end-to-end silent-skip evidence; each was fixed before acceptance.
- Tests not run and reason: no interactive GUI session and no physical-device/vendor integration tests were run. The agent did not enumerate resources, validate a vendor runtime, or connect hardware.
- User-executed hardware test status: Not applicable to the checked-in mock-only profile; not run.

### Inspection

- `git diff --check`: Passed before commit.
- `git status --short --branch`: Clean immediately after the Phase 4 source/documentation commit; this log entry is the only subsequent change.
- Unexpected/unrelated changes: None.
- Generated artifacts removed: the external redirected Phase 4 bytecode directory was resolved, verified, and removed. Temporary test profiles used OS temporary directories and were removed by their contexts.
- Security/configuration review: the launcher contains no device-specific import, address, serial, connection command, or channel list. No checked profile contains credentials, private endpoints, real instrument identifiers, or lab paths. Explicit invalid profiles do not fall back.

### Decision

- Gate passed: Yes.
- Commit(s): `a67a8d5` (`Switch launcher to validated profiles`); this evidence entry follows in a documentation commit.
- Rollback method: revert the Phase 4 source/documentation commit and its evidence commit; recovery tag remains `pre-structure-v2`.
- Remaining risks: only `mock_device` has a reviewed active registry entry; source presence does not imply profile support. Runtime catalog rebuilding and mutation remain disabled. The known cooperative GUI-finalizer shutdown deadline from Phase 3 remains unchanged.
- Next authorized phase: Phase 5 — make every catalog consumer rebuild from one authoritative manager snapshot and define safe reference reconciliation.
- User input required: None.

## 2026-08-18 — Phase 5: rebuildable transactional device catalogs

### Intended outcome

- Acceptance criteria: one immutable catalog snapshot is rebuilt from a manager snapshot; callable/display/router/UI consumers refresh together; repeated refresh does not duplicate controls or signals; synthetic add/remove and rollback are deterministic; a stored reference to a removed label or channel refuses the change without rewriting a scan definition.
- Explicit non-goals: manager-owned runtime add/disconnect/remove, persistence of session mutations, registration or activation of a real driver, mechanical package moves, array-valued getters, or physical-device validation.
- Base commit: `bd9aac9`.
- Related maintenance commits integrated: None.

### Changes

- Files added: `core/device_catalog.py`, `tests/test_mainwindow_catalog_refresh.py`, `tests/test_scan_catalog_consumers.py`.
- Files modified: `core/mainWindow.py`, `core/scanlist.py`, `core/scan.py`, `core/all_level.py`, `core/nested_menu.py`, `core/artificial_channel_2d_main.py`, `core/artificial_channel_logic.py`, `core/device_command_router.py`, `autofocus_xuguo/autofocusXZ_main.py`, `autofocus_xuguo/autofocusXZ_logic.py`, `autofocus_xuguo/autofocusXZ_hardware.py`, `documents/architecture.md`, `documents/device_contract.md`, `documents/testing.md`, `project_structure.md`.
- Files moved: None.
- Files removed: None.
- API/config impact: `MainWindow.apply_device_snapshot()` now builds and publishes an immutable `DeviceCatalogSnapshot`; `ScanList.refresh_catalog()`, reference inventory, and idle-blocker APIs cover the available, queue, past, manual, active, detached-worker, and New Scan template surfaces. Device-specific stored cross-device choices may participate through the reviewed reference-provider hook. Configuration/profile schemas are unchanged.
- Existing behavior impact: startup still presents the two disconnected mocks in profile order. Device button show/restore/focus behavior, exact underscore-label routing, artificial-channel operation, range enforcement, scan definitions, and silent skipping of unknown configured channel names are preserved. Deferred automatic VISA discovery is unchanged.
- Scan/data/schema impact: scan execution and scalar storage/persistence formats are unchanged. Catalog refresh updates menu choices without emitting definition changes, clearing averaged getters, defaulting plots, or rewriting unresolved selections.
- Hardware/lifecycle impact: none. Phase 5 applies synthetic snapshots only; runtime manager mutation remains disabled. Reversible router attach/detach and closed-client behavior were added so a future failed add/remove cannot retain hidden signal subscribers.
- Documentation updated: architecture, device/router contract, hardware-independent catalog testing, and maintained module inventory.

### Reference and removal policy

- A catalog change is refused when its old-minus-new full setter/getter channels or exact removed labels intersect any open/template/queued/past/active/detached scan reference, manual-set item, artificial active/draft selection, or registered device-owned reference provider.
- Unknown stored channel names continue to be silently absent from exported allowlisted channels, but they still count as an exact device-label reference for removal safety.
- Artificial-channel rename is treated as channel removal. Preflight occurs before mutation, and target/state signals are emitted only after the logic and catalog transaction commits.
- Stable device IDs cannot be rekeyed by reusing the same instance under a new label. Removal and later construction of a new generation belongs to Phase 6.

### Validation

| Exact command/check | Environment | Evidence level | Result | Duration/output |
| --- | --- | --- | --- | --- |
| `python -X pycache_prefix=C:\Users\Taylo\Documents\ChatGPT\zmeter\.restructure_phase5_pycache -B -m py_compile <all changed Python files>` | `zmeter_May2026` Python 3.12.12 | Static | Passed; redirected bytecode directory verified and removed | Exit 0 |
| `python -B -m unittest tests.test_mainwindow_catalog_refresh tests.test_scan_catalog_consumers -v` | `zmeter_May2026`, offscreen | Hardware-independent unit/mock/offscreen GUI | Final focused catalog/consumer matrix passed 24 tests | 11.096 s |
| Broader relevant config/registry/manager/startup/catalog/VISA suite | `zmeter_May2026`, offscreen/fake runtimes | Hardware-independent integration | 60 tests passed | 16.823 s |
| `python -B -m unittest discover -s tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen where requested by tests | Hardware-independent unit/mock/offscreen GUI | Complete core suite passed 157 tests | 21.369 s |
| `python -B -m unittest discover -s mockDevice/tests -p 'test_*.py' -v` | `zmeter_May2026`, offscreen | Mock/simulation/offscreen GUI | 18 tests passed | 0.293 s |
| Independent Phase 5 adversarial audit | Read-only code review plus focused offscreen tests | Catalog/router/UI safety review | Clean after failed-removal, router-after-removal, rollback aggregation, reentrancy, queue-completion, and stale-action coverage | Passed |
| `git diff --check`, changed-file/status review, generated-artifact cleanup, and secret/address scan | Repository root | Static/security inspection | Passed; only expected LF/CRLF conversion warnings; no new address, credential, profile, cache, or data artifact | None |

- Validation incidents: an intermediate test expected a channel-named property to be evaluated during discovery. Discovery was deliberately hardened to inspect only static callable descriptors, and the test was corrected to separately prove both property non-evaluation and genuine staging failure rollback. The final focused, broader, and complete suites passed.
- Tests not run and reason: no interactive GUI workflow, physical-device test, real VISA enumeration, vendor SDK/DLL load, network instrument action, or PowerPoint/COM hardware workflow was run. None is authorized or required for the mock-only Phase 5 gate.
- User-executed hardware test status: Pending for any future real-driver enablement; not applicable to the checked-in mock profile.

### Inspection

- `git diff --check`: Passed before commit, with line-ending notices only.
- `git status --short --branch`: clean after the Phase 5 source/documentation commit; this progress entry is the only subsequent change.
- Unexpected/unrelated changes: None.
- Generated artifacts removed: the explicitly resolved external `.restructure_phase5_pycache` directory was removed after validation.
- Security/configuration review: no profile, address, serial, credential, private endpoint, DLL, measurement output, persistence schema, or array-getter work entered the phase.

### Decision

- Gate passed: Yes.
- Commit(s): `e663318` (`Make device catalogs rebuildable`); this evidence entry follows in a documentation commit.
- Rollback method: revert the Phase 5 source/documentation commit and its evidence commit; recovery tag remains `pre-structure-v2`.
- Remaining risks: manager-owned session mutation and generation-aware/in-flight call gating are not yet enabled. `MainWindow.apply_device_snapshot()` is a tested UI-thread transaction, but Phase 6 must split side-effect-free proposal/preflight from post-lifecycle commit, reject stale generations, and keep profile persistence separate. A real driver with additional stored references or router clients remains ineligible for runtime mutation until its provider/detach contract is reviewed.
- Next authorized phase: Phase 6 — add mock-only idle-guarded runtime add/disconnect/remove and manager call gating, then integrate the transactional catalog acknowledgement.
- User input required: None.

## 2026-08-18 — Phase 6: idle-only runtime device management

### Intended outcome

- Acceptance criteria: add, disconnect, and remove reviewed mock devices without blocking the UI; refuse mutation while scans, the queue, manual operations, router/device calls, or device-owned work are active; prevent any call after removal starts; publish exactly one acknowledged catalog generation per successful change; preserve ownership-order teardown and allow a failed pre-teardown boundary to retry without reopening the half-shutdown session.
- Explicit non-goals: persisting session mutations, enabling a real driver for runtime mutation, changing scalar scan or persistence behavior, moving device packages, array-valued getters, or physical-device validation.
- Base commit: `127068c`.
- Related maintenance commits integrated: None.

### Changes

- Files added: `tests/test_device_manager_runtime_mutation.py`, `tests/test_runtime_device_ui.py`.
- Files modified: `core/device_management/manager.py`, `core/device_management/models.py`, `core/device_management/registry.py`, `core/device_management/__init__.py`, `core/mainWindow.py`, `core/device_command_router.py`, `core/scan.py`, `core/scanlist.py`, focused integration/catalog tests, root/config READMEs, architecture, device contract, testing guidance, and `project_structure.md`.
- Files moved: None.
- Files removed: None.
- API/config impact: `DeviceManager` now exposes generation-bound snapshots, call/session leases, activity reservations, mock-only asynchronous add/disconnect/remove operations, guarded reconciliation, and asynchronous final teardown. Runtime registrations require an explicitly reviewed fast `is_busy` probe. `ChannelFilters` defensively normalizes caller iterables to detached tuples. Profile bytes and schema are unchanged; runtime changes remain session-only.
- Existing behavior impact: the checked-in profile still starts the same two disconnected mocks in the same order. Deferred automatic VISA discovery and silent skipping of unknown configured channel names remain unchanged and covered end to end. Device-window show/restore/focus behavior and catalog/menu/router publication remain unchanged on successful operations.
- Scan/data/schema impact: no scalar scan, output, autosave, or persistence schema changed. Scan, queue, manual-set, output-finalization, router, and direct device activity now reserve a shared manager gate so removal cannot race a bound call.
- Hardware/lifecycle impact: slow construct/connect/disconnect/force-stop/stop/terminate callbacks execute on lifecycle workers; QWidget construction, catalog acknowledgement, close, and delete scheduling remain on the Qt owner thread. Failed termination, close, deletion, or catalog acknowledgement is retained as explicit ERROR/quarantine state and retried or reported rather than silently discarded.
- Documentation updated: runtime ownership, mutation eligibility, worker/thread-affinity rules, shutdown retry behavior, session-only configuration semantics, and focused Gate C/D commands.

### Runtime mutation and shutdown policy

- Runtime mutation is enabled only for the reviewed `mock_device` registration. Source presence or a lazy registry candidate does not imply runtime eligibility for any real driver.
- The manager seals admission before construction or lifecycle dispatch, performs side-effect-free UI preflight with an exact manager-issued proposal identity, then commits and publishes only after synchronous UI acknowledgement. Retained records keep their creation generation; removing and re-adding the same label invalidates old proxies.
- Removal is refused when the target is busy or when a stored session reference would become unavailable. Disconnect keeps the record and its generation; remove terminates and deletes it only after preflight and drain succeed.
- Application shutdown preserves the established global order: force-stop all devices, stop-scan all devices, then terminate/close/delete each device in ownership order. If the teardown worker cannot start or another pre-commit boundary fails after `ScanList.shutdown()`, the exact shutdown reservation and UI seal remain active; new calls and mutations stay rejected while an explicit retry is allowed.

### Validation

| Exact command/check | Environment | Evidence level | Result | Duration/output |
| --- | --- | --- | --- | --- |
| `python -B -m py_compile core/device_management/{models,manager,registry,__init__}.py core/device_command_router.py core/mainWindow.py core/scan.py core/scanlist.py tests/test_device_manager_runtime_mutation.py tests/test_runtime_device_ui.py` | `zmeter_May2026` Python 3.12.12 | Static | Passed | Exit 0 |
| `python -B -m unittest -q tests.test_device_config tests.test_device_manager tests.test_device_registry tests.test_device_manager_runtime_mutation` | `zmeter_May2026`, fake runtimes | Hardware-independent unit/mock | 56 tests passed | Passed |
| `python -B -m unittest -q tests.test_device_manager_integration tests.test_runtime_device_ui tests.test_mainwindow_catalog_refresh` | `zmeter_May2026`, offscreen | Hardware-independent integration/GUI | 55 tests passed | Passed |
| `python -B -m unittest discover -s tests -p 'test_*.py' -q` | `zmeter_May2026`, offscreen where requested by tests | Hardware-independent unit/mock/offscreen GUI | Complete core suite passed 193 tests | 26.496 s on final primary-agent rerun |
| `python -B -m unittest discover -s mockDevice/tests -p 'test_*.py' -q` | `zmeter_May2026`, offscreen | Mock/simulation/offscreen GUI | 18 tests passed | 0.314 s |
| Independent adversarial Gate C/D audits | Read-only code review plus deterministic fake/offscreen reproducers | Lifecycle/catalog/router/UI safety review | Clean after generation, proposal capability, mutable-input, worker-dispatch, quarantine/reconcile, call-lease, teardown-order, and synchronous/asynchronous shutdown-retry coverage | Independent selections passed 111 tests and 36 tests |
| `git diff --check`, staged-file/status review, and changed-file statistics | Repository root | Static/inspection | Passed; only expected LF/CRLF conversion notices | None |

- Validation incidents: adversarial review found and fixed intermediate races involving worker start/delete failures, post-commit reconciliation, target busy probing, mutable caller filter lists, malformed runtime configs, and a half-shutdown session reopening after teardown dispatch failure. Each reproducer became or strengthened a deterministic regression, and the final focused and complete suites passed.
- Tests not run and reason: no interactive hardware workflow, physical-device test, real VISA enumeration, vendor SDK/DLL load, network instrument action, or PowerPoint/COM hardware workflow was run. Runtime mutation remains deliberately mock-only, so no real-driver bench validation is authorized for this phase.
- User-executed hardware test status: Pending for any future real-driver eligibility review; not applicable to the checked-in mock profile.

### Inspection

- `git diff --check`: Passed before commit, with line-ending notices only.
- `git status --short --branch`: clean after the Phase 6 source/documentation commit; this progress entry is the only subsequent change.
- Unexpected/unrelated changes: None.
- Generated artifacts removed: None were tracked or staged; test bytecode remained ignored.
- Security/configuration review: no profile, address, serial, credential, private endpoint, DLL, measurement output, persistence schema, or array-getter work entered the phase.

### Decision

- Gate passed: Yes.
- Commit(s): `c9aa520` (`Add idle-only runtime device management`); this evidence entry follows in a documentation commit.
- Rollback method: revert the Phase 6 source/documentation commit and its evidence commit; recovery tag remains `pre-structure-v2`.
- Remaining risks: runtime mutation is approved only for the mock driver. A real registration remains ineligible until its busy probe, lifecycle worker safety, router detach/reference-provider contract, optional dependencies, and user-executed bench plan are reviewed. Router source-device authentication is future hardening and does not change the current trusted in-process command path. The cooperative deadline limitation for an already-running GUI callback remains unchanged.
- Next authorized phase: Phase 7 — move packages under `devices/` mechanically, repairing imports and file-relative resources without enabling additional drivers.
- User input required: None.

## 2026-08-19 — Phase 7: device packages consolidated under `devices/`

### Intended outcome

- Acceptance criteria: every root-level device/source directory moves exactly once into an import-free `devices/` namespace; registry, tests, package imports, UI/resource paths, commands, and links resolve from the new location; no duplicate runnable package or compatibility shim remains; binary/source artifacts preserve identity; mock startup and scalar behavior remain unchanged.
- Explicit non-goals: enabling an additional registry driver, changing device protocols or safety limits, normalizing legacy device behavior, loading optional vendor dependencies, persisting session mutations, array-valued getters, or physical-device validation.
- Base commit: `20546d8`.
- Related maintenance commits integrated: None.

### Changes

- Files added: import-free `devices/__init__.py`.
- Files moved: 152 tracked files across 21 directories — `ANC300`, `auto_focus`, `auto_position`, `autofocus_xuguo`, `BBD30X`, `demoDevice`, `four9`, `hp34401a`, `k10cr1`, `keithley24xx`, `mockDevice`, `montana2`, `ni6423`, `nidaq`, `opticool`, `pem100`, `sp150`, `sr830`, `sr830_v2`, `sr860`, and `tlpm` — from the repository root to flat `devices/<package>/` subpackages.
- Files modified: reviewed registry lazy import; affected package-relative imports and test imports; 13 CWD-sensitive UI paths; TLPM DLL resolution; fallback repository-root calculations; Montana nested import/path depth; focused tests; central/current documentation and 20 device READMEs.
- Files removed: no source content was deleted; the former root package locations disappeared as part of detected renames.
- API/config impact: import paths are now `devices.<package>...`. The default registry remains exactly `('mock_device',)` and imports `devices.mockDevice` only inside its lazy factory. Configuration/profile schema and checked profile bytes are unchanged.
- Existing behavior impact: package moves are mechanical except for path/import resolution required to preserve construction from any working directory. Deferred automatic VISA discovery still schedules on the next Qt event-loop turn, and unknown configured channel names are still silently absent from exported allowlists. No compatibility shim or duplicate package was introduced.
- Scan/data/schema impact: none. Scalar traversal, storage, plotting, output, autosave, JSON/PPT behavior, and scan definitions are unchanged.
- Hardware/lifecycle impact: none. No device was discovered, connected, opened, configured, moved, read, written, stopped, or disconnected. Optional vendor imports and DLL loads remained dormant.
- Documentation updated: root/agent commands, maintained structure and architecture, device contract/testing/tutorial/index, all affected device links/commands/import examples, corrected `auto_position` move-era status, and the previously omitted Four9 inventory.

### Move and preservation details

- All package moves were committed as reviewable namespace, mock, VISA, Four9, Kinesis, autofocus, NI, and high-risk legacy checkpoints. No root-level device directory remains.
- UI resources are file-relative after the move. Direct-script local-import fallbacks were preserved where they remain part of a legacy package's standalone behavior; active package imports use relative or `devices.*` paths.
- The extensionless ANC300 source remains 15,564 bytes, SHA-256 `20F39EB43BEEAC2FB445B02E59FDBFD3C78385EE51A0EEB9005A40C7F38DDF19`, Git blob `467dfa2084a56ad68a4dc4e4bee28f49c99dab83`.
- `devices/tlpm/TLPM_64.dll` remains 712,632 bytes, SHA-256 `948920D2EDEA4B4ABADEBF4FA644740C880228A46E01629146F50E0A3951AA0C`, Git blob `2b9fadee64b8ccb0ee738070c800ff49f75be9ab`. It was hashed only and never loaded.
- Dated investigation/implementation-plan documents, ADR historical context, archived material, earlier progress entries, and the preserved SR830 traceback were not retroactively rewritten.

### Validation

| Exact command/check | Environment | Evidence level | Result | Duration/output |
| --- | --- | --- | --- | --- |
| `python -X pycache_prefix=<external Phase 7 cache> -B -m py_compile <all devices/**/*.py>` | `zmeter_May2026` Python 3.12.12 | Static | 107 Python files compiled; one pre-existing Montana invalid-escape `SyntaxWarning`; redirected cache verified and removed | Exit 0 |
| PowerShell XML parse of every `devices/**/*.ui` | Repository root | Static/resource | 20 UI files parsed | Passed |
| `python -B -m unittest discover -s tests -p 'test_*.py' -q` | `zmeter_May2026`, offscreen where requested by tests | Hardware-independent unit/mock/offscreen GUI | Complete core suite passed 194 tests | 26.342 s |
| `python -B -m unittest discover -s devices/mockDevice/tests -p 'test_*.py' -q` | `zmeter_May2026`, offscreen | Mock/simulation/offscreen GUI | 18 tests passed | 0.298 s |
| Moved package suites for `four9`, `pem100`, `sp150`, `BBD30X`, and K10CR1 | `zmeter_May2026`, injected fakes/offscreen/local fake loopback only | Hardware-independent package integration | 20 + 10 + 12 + 20 + 10 = 72 tests passed | Passed |
| `tests.test_nidaq_two_ao` and `tests.test_mainwindow_catalog_refresh` | `zmeter_May2026`, stubbed PyDAQmx/offscreen | Safe legacy-path and catalog regression | 22 tests passed | Passed |
| Explicit deferred-VISA and silent-unknown-filter selectors | `zmeter_May2026`, fake VISA/offscreen | User-approved compatibility decisions | 4 tests passed | 0.995 s on the completed rerun |
| Fresh-process default-registry import sentinel | `zmeter_May2026` | Import safety | Driver IDs exactly `('mock_device',)`; no `devices`, PyVISA, CLR, NI, or PyDAQmx module imported before factory use | Passed |
| Directory/tracked-file/profile/binary inspection | Repository root | Structure/integrity | 21 exact child directories, 153 tracked `devices/` files including namespace, zero root duplicates; checked profile names, lengths, and SHA-256 unchanged; ANC/TLPM identities unchanged | Passed |
| Markdown relative-link and current-path/import checks | Non-archive/current documentation | Documentation | Zero broken links and zero active stale root-package paths; Four9 present in all central inventories | Passed |
| `git diff --check`, rename summaries, status, and staged-file review | Repository root | Static/inspection | Passed; only expected LF/CRLF conversion notices | None |

- Validation incidents: the first verbose four-test compatibility selector stalled after starting the VISA-widget construction test and left one maintained-environment test process. That process was explicitly stopped; an immediate identical quiet selector completed 4/4 in 0.995 seconds, and the same test also passed inside the 194-test full suite. No hardware call occurred. This is consistent with the previously documented intermittent Qt test-timing race rather than a package-path failure.
- Tests not run and reason: no physical-device test, real VISA enumeration, vendor SDK/DLL load, serial-port enumeration, NI device/task access, Kinesis/CLR load, cryostat/network action, or PowerPoint/COM hardware workflow was run. High-risk legacy packages received static/XML inspection only unless an existing injected-fake test was known safe.
- User-executed hardware test status: Pending for any future real-driver eligibility review; no real driver is newly registered or enabled by this phase.

### Inspection

- `git diff --check`: Passed before each move/documentation commit, with line-ending notices only.
- `git status --short --branch`: clean after the Phase 7 move and documentation commits; this progress entry is the only subsequent change.
- Unexpected/unrelated changes: None.
- Generated artifacts: the explicitly redirected Phase 7 compile cache was removed. Ignored pre-existing May-2026 `__pycache__` content moved with `ni6423` and `montana2`; it is not tracked or staged and was left intact rather than deleting user-local files.
- Security/configuration review: checked profile files are byte-identical. No new address, serial, credential, private endpoint, measurement output, persistence schema, or array-getter work entered the phase. Existing device-local defaults and the tracked TLPM DLL were preserved, not executed.

### Decision

- Gate passed: Yes.
- Commit(s): `42bcdd0` (namespace), `123c9e4` (VISA family), `3abe733` (mock), `0a3253c` (Four9), `4a0d569` (Kinesis family), `86f0ce0` (autofocus XZ), `0130d1b` (legacy NI/autofocus), `dea8ae7` (NI6423), `9a82785` (ANC300), `262ea14` (Montana), `14d707b` (legacy SR830), `f2bb6ad` (OptiCool), `91082c3` (TLPM), and `c797acc` (documentation).
- Rollback method: revert the Phase 7 documentation and family move commits in reverse order, then the namespace commit; recovery tag remains `pre-structure-v2`.
- Remaining risks: package presence still does not imply registry eligibility or hardware validation. Legacy direct-execution fallbacks and optional dependency behavior remain as documented. Six definitively dead root-device import comments and one redundant root-specific ignore rule remain for Phase 8 consolidation. The intermittent Qt VISA construction-test timing race is unchanged and passed on rerun/full-suite execution.
- Next authorized phase: Phase 8 — remove only definitively dead restructure remnants, complete final documentation/inspection, run the full hardware-independent validation matrix, and prepare the user-executed hardware plan.
- User input required: None.

## 2026-08-19 — Restructure completion

- Final branch/commit: `codex/structural_update_vibeeee`; final implementation commit `0a3d5e1` (`Complete restructure consolidation`); this entry is committed as the final documentation checkpoint.
- Baseline tag/commit: `pre-structure-v2` at `b98a1666aad2132316f535738457df928f3147ac`, identical to local and remote `main` when the restructure began.
- High-level outcome: the manual's eight phases are complete. Startup is profile-driven and hardware-safe by default; the lazy registry and manager own device construction/lifecycle; runtime add/disconnect/remove is guarded and mock-only; catalogs rebuild transactionally; and all 21 former root device/source directories live under the import-free `devices/` namespace without runnable duplicates.
- Final runtime path: `start_zmeter.py` strictly selects `config/profiles/mock.json` or an explicit reviewed profile, validates it relative to the repository root, builds the lazy registry and shared runtime services, loads a manager-owned ordered snapshot, and gives that manager to `MainWindow`; scan, queue, manual, router, mutation, reconciliation, and shutdown paths share the manager's generation/activity gates.
- Final directory layout verified: exactly 21 flat `devices/<package>/` directories and 153 tracked files including `devices/__init__.py`; no former root package directory or compatibility shim remains. `core/`, `config/`, `tests/`, `documents/`, and historical `archive/` retain their documented roles.
- Existing behavior compatibility summary: the default two labels and exact mock channel catalogs remain unchanged; deferred automatic VISA discovery is preserved; unknown configured channel names remain silently absent from exported allowlists; device-button focus/show behavior, scalar scan traversal/storage/order, range/skip/artificial behavior, averaged getters, queue order, signals, autosave timing, logging, close confirmation, and ordered teardown remain regression-covered.
- Configuration/profile behavior: checked profiles remain the disconnected mock profile and empty example profile, byte-identical to their activation state. Relative paths resolve from the repository root; an invalid explicitly selected profile fails without fallback; disabled entries remain import/factory/lifecycle inert; real addresses, serials, credentials, and lab paths remain excluded from checked configuration. Runtime mutations are session-only and do not rewrite profiles.
- Runtime add/disconnect/remove behavior and guards: only the reviewed `mock_device` registration is eligible. Operations require an idle, unreferenced session; scan/queue/manual/router/direct calls hold shared leases; generation-bound proxies reject stale/removed records; QWidget construction/close/delete stays on the owner thread while slow lifecycle work runs off-thread; catalog prepare/commit/reconciliation is capability-bound; cleanup failures remain quarantined/reportable; and failed shutdown keeps the session sealed for an exact guarded retry.
- Full hardware-independent commands/results: maintained `zmeter_May2026` Python 3.12.12 with offscreen Qt and bytecode disabled. Final core discovery passed 202/202 in 27.115 s; moved mock discovery passed 18/18 in 0.299 s; the exact Gate E/F selection passed 46/46 in 4.113 s; the new scalar/persistence modules passed 8/8 in 0.568 s; final Four9/BBD30X/PEM100/SP150 package runs passed 20 + 20 + 10 + 12 tests; shared-runtime/VISA/K10CR1 fake selection passed 37/37; Phase 8 `py_compile` passed 3/3 with its OS-temporary cache removed; 36 tracked/current UI resources XML-parsed; all 41 current non-archive Markdown files had valid relative links; JSON/profile, directory, registry-import, binary/hash, secret/address, generated-artifact, old-import, duplicate-manager, changed-file, status, and `git diff --check` inspections passed.
- Tests not run: no physical-device workflow; real VISA/resource or serial-port enumeration; NI task/device access; CLR/Kinesis or other vendor-runtime/DLL loading; cryostat/network action; real PowerPoint/COM output; or interactive lab GUI procedure. High-risk optional packages were limited to static checks or existing injected-fake suites.
- User-executed hardware status: pending and not applicable to the checked mock-only registry. `documents/hardware_safety.md` now supplies the required future plan: separately approve one real registration/profile first, record exact commit/profile hash/environment/SDK/device/limits/state, perform only established safe checks, conditionally test runtime mutation, close the full application, independently verify final physical state, and return exact evidence using the user-hardware-result template.
- Persistence/schema impact: none. Twenty-one relevant `Scan`, `ScanLogic`, and `MainWindow` persistence/traversal selectors plus `core/append_to_ppt.py` are structurally identical to `pre-structure-v2`. New temporary-path tests preserve top-level JSON order `levels`, `data`, `plots`, `name`, `plots_per_page`, `comments`, `scan_log`; scalar `float64` shapes/order; current unquoted `NaN`; empty/populated round trips; filename collision and serial discovery; canonical `autosave.json`; backup-disabled behavior; and downstream load acceptance.
- Safety impact: checked startup remains disconnected mock-only. No hardware, vendor runtime, DLL, network endpoint, PowerPoint, or COM operation was executed. `Z:\`, backup, presentation, slide, dialog, and COM paths in persistence tests were intercepted and asserted unused. All generated `__pycache__`, bytecode, and `.restructure_tmp` artifacts were removed after verified in-repository containment; no source, profile, data, or vendor binary was deleted.
- Documentation updated: root README; maintained structure/architecture/device/runtime/testing/environment/hardware-safety documents; configuration guide; tutorial/indexes; all relevant device READMEs; and the complete append-only phase/decision evidence in this log. Historical archive, dated investigations, ADR context, and earlier phase evidence were not retroactively rewritten.
- Remaining risks/known issues: package presence does not imply registry eligibility, optional-dependency support, or hardware validation; only `mock_device` is registered and runtime-mutable. Real-driver schemas, busy/lifecycle adapters, physical limits, SDK compatibility, and user bench evidence remain future per-driver work. Actual Office/PPT integration remains unexecuted. An already-running GUI finalizer can exceed the cooperative shutdown deadline, and the pre-existing intermittent deferred-VISA Qt timing race remains unchanged; the VISA test passed on immediate rerun and in final complete discovery.
- Deferred array-valued getter work confirmed absent: Yes. No 1D/2D getter representation, object-array storage, shape inference, array persistence, spectrum/image plotting, or related schema work entered this branch.
- Final `git status --short --branch`: `## codex/structural_update_vibeeee` (clean; this completion entry is the final documentation checkpoint).
- Ready for user review: Yes.
- Remote/main merge actions performed: None. Nothing was pushed or merged.
