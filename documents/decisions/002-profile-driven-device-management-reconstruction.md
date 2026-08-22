# 002: Profile-driven device management and behavior-preserving reconstruction

- Status: Implemented in `release/beta`; stable promotion and hardware commissioning pending
- Date: 2026-08-21
- Owners: ZMeter maintainers
- Supersedes: none

## Context

ZMeter previously selected devices and laboratory settings through launcher
edits, kept device packages at repository root, and distributed ownership of
device construction, channel catalogs, shared runtimes, and shutdown. Adding or
removing a device risked stale bound callables in scans, menus, the router, and
artificial-channel configuration. A copied legacy application would have
created another runnable source of truth.

The reconstruction had to preserve established scalar scan traversal,
persistence, device behavior, deferred VISA discovery, and local laboratory
configuration while making startup and ownership reviewable.

## Decision

ZMeter uses validated JSON profiles, a lazy code-reviewed driver registry, one
`DeviceManager`, and typed shared runtime services. `start_zmeter.py` remains a
thin composition boundary. Checked profiles stay mock-only or contain disabled
placeholders; addresses, serials, endpoints, paths, and enabled real-device
sets remain local configuration.

Profile startup constructs enabled devices independently in order and issues a
separate best-effort startup connection request. A device-local construction or
connection failure is visible but does not prevent unrelated devices or the
Main Window from opening. Invalid profile syntax, duplicate IDs, and unknown
drivers remain fatal validation errors.

The manager owns device lifecycle and publishes generation-bound snapshots.
MainWindow rebuilds device buttons, callable maps, router catalog, scan/manual
menus, artificial-channel choices, and active range views as one UI-thread
transaction. Runtime add, disconnect, and remove are session-only, idle-gated,
reference-aware, and do not rewrite profiles. Only the mock registration is
currently eligible; real drivers remain startup-only until separately reviewed.

All device/source packages live under the flat `devices/` namespace. The
maintained former SR830 v2 implementation is the sole `devices/sr830` package.
Application-level events use the session-only Main Window System Log, while
device, scan, queue, and output details remain in their owning logs.

The reconstruction deliberately preserves deferred automatic VISA discovery
for enabled legacy widgets and silent omission of unknown configured channel
names. It preserves the scalar persistence schema and does not introduce
array-valued getters.

## Consequences

- Startup is deterministic, configurable, lazy, and mock-safe by default.
- Device teardown and shared-runtime release have one owner and tested ordering.
- Catalog mutation can fail closed without leaving stale device callables.
- Real-device registration no longer implies runtime mutation or hardware
  approval; per-driver lifecycle work and user commissioning remain necessary.
- Runtime changes disappear at restart because the selected profile remains the
  durable source of configuration.
- Compatibility decisions around discovery, unknown channels, and scalar data
  remain visible future migrations rather than hidden behavioral changes.
- The manager/catalog implementation is more complex than static startup and
  therefore requires deterministic lifecycle, generation, and reconciliation
  tests.

## Alternatives considered

- Continue editing `start_zmeter.py`: rejected because it mixes code with lab
  configuration and cannot provide validated, recoverable composition.
- Keep a runnable legacy copy: rejected because duplicate active paths drift and
  weaken recovery; Git history and the recovery tag provide rollback.
- Rewrite all device drivers during registration: rejected because it expands
  hardware risk and obscures behavior-preserving structural changes.
- Enable runtime mutation for every registered driver: rejected because most
  real drivers lack complete busy, bounded lifecycle, reference, and bench
  evidence.
- Change VISA discovery or unknown-channel behavior during reconstruction:
  rejected as an unapproved operator/profile compatibility change.

## Validation implications

Static, unit, fake-runtime, mock, offscreen GUI, scalar regression, persistence,
catalog, lifecycle, and shutdown checks are required for structural changes.
Hardware validation is always user-executed, one device and installation at a
time. Any future real-driver runtime mutation requires its own reviewed busy,
worker, stop, cleanup, router-detach, reference-provider, and bench evidence.
Array-valued data requires a separate schema decision and migration plan.
