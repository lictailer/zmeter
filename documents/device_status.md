# Device Registration and Readiness Status

This document is the current repository-wide readiness index. Source and tests
remain authoritative for behavior; connection details, channels, limits, and
device-specific bench procedures belong in each device README. Registration is
not hardware approval.

## Maintained registry

All real registrations are lazy, startup-only, and disabled from runtime
mutation. Startup connection is best-effort: a failure does not prevent the
Main Window or later devices from loading. `Pending` means an existing device
worker accepted the request and the device panel remains authoritative for its
final result.

| Driver ID | Package | Startup connection | Runtime mutation | Evidence and readiness | Primary future improvement |
| --- | --- | --- | --- | --- | --- |
| `mock_device` | [mockDevice](../devices/mockDevice/README.md) | Confirmed synchronous simulator | Approved | Unit, simulation, offscreen GUI; user reports successful manual mock operation | Add an operator device-management UI only if a maintained workflow requires it |
| `ni6423` | [ni6423](../devices/ni6423/README.md) | Best-effort synchronous | Disabled | Stub/fake and offscreen registration only; hardware pending | Configurable routing, bounded task cleanup, complete busy/force-stop contract, fake NI backend |
| `nidaq` | [nidaq](../devices/nidaq/README.md) | Best-effort synchronous | Disabled | Legacy fake coverage only; hardware pending | Migrate from PyDAQmx to NI-DAQmx and standardize lifecycle/task rollback |
| `pem100` | [pem100](../devices/pem100/README.md) | Best-effort synchronous | Disabled | Fake VISA coverage; hardware pending | Fault matrix, explicit state reporting, bounded cleanup, busy probe |
| `sp150` | [sp150](../devices/sp150/README.md) | Best-effort synchronous | Disabled | Fake VISA coverage; hardware pending | Fault matrix, interruption reporting, bounded cleanup, busy probe |
| `hp34401a` | [hp34401a](../devices/hp34401a/README.md) | Best-effort synchronous | Disabled | Fake/shared-runtime coverage; hardware pending | Prove failed-close cleanup and standardize lifecycle/state reporting |
| `keithley24xx` | [keithley24xx](../devices/keithley24xx/README.md) | Asynchronous pending | Disabled | Fake/shared-runtime coverage; hardware pending | Bounded ramp/teardown, complete busy reporting, partial-connect faults |
| `sr860` | [sr860](../devices/sr860/README.md) | Best-effort synchronous | Disabled | Fake/shared-runtime coverage; hardware pending | Restrict reviewed numeric scan filters and standardize lifecycle/fault handling |
| `sr830` | [sr830](../devices/sr830/README.md) | Best-effort synchronous | Disabled | Maintained former v2 implementation; fake/shared-runtime coverage; hardware pending | Restrict reviewed numeric scan filters and standardize lifecycle/fault handling |
| `demo_device` | [demoDevice](../devices/demoDevice/README.md) | Confirmed synchronous simulator | Disabled | Dummy-runtime automated coverage | Keep as a legacy template; use `mock_device` for new integration work |
| `bbd30x` | [BBD30X](../devices/BBD30X/README.md) | Asynchronous pending | Disabled | Fake Kinesis coverage; hardware pending | Complete motion busy/timeout/partial-connect and interrupted-position evidence |
| `k10cr1` | [k10cr1](../devices/k10cr1/README.md) | Asynchronous pending | Disabled | Fake Kinesis coverage; hardware pending | Implement a bounded real force-stop path and software motion limits |
| `four9` | [four9](../devices/four9/README.md) | Asynchronous pending | Disabled | Loopback/fake TCP coverage; environment bench pending | Connection-loss/shutdown races and installation/service manifest |
| `montana2` | [montana2](../devices/montana2/README.md) | Asynchronous pending | Disabled | Intercepted registration behavior; no production REST fake; bench pending | REST timeouts, explicit signals/limits, proven shutdown, configurable remaining endpoint assumptions |
| `opticool` | [opticool](../devices/opticool/README.md) | Asynchronous pending and retryable | Disabled | Intercepted vendor boundary; bench pending | Configurable DLL location, hard limits, bounded stability/termination, fake .NET backend |
| `tlpm` | [tlpm](../devices/tlpm/readme.md) | Asynchronous pending and retryable | Disabled | Intercepted native boundary; bench pending | Explicit resource selection, bounded native calls, reviewed scan channels, production fake backend |

The tracked templates are [phase1_lab.json](../config/profiles/phase1_lab.json)
and [phase2_lab.json](../config/profiles/phase2_lab.json). Copy a template to an
ignored local profile, enable exactly one real driver, and retain
`connect_on_start=false` for first commissioning.

## Ongoing, unregistered packages

| Package | Current availability | Blocking work before registration |
| --- | --- | --- |
| [autofocus_xuguo](../devices/autofocus_xuguo/README.md) | Source retained; not selectable by profile | Remove constructor COM discovery, move long work off the UI thread, stop active work before termination, define router/reference/busy contracts |
| [auto_focus](../devices/auto_focus/README.md) | Prototype retained; not selectable by profile | Complete object wiring, remove direct NI coupling and embedded identifiers, define explicit resources and coherent lifecycle |
| [auto_position](../devices/auto_position/README.md) | Prototype retained; not selectable by profile | Port to PyQt6, remove direct task construction, add logic boundary, explicit profile schema, limits, stop, and final cleanup |
| [ANC300](../devices/ANC300/README.md) | Source fragment retained; not an importable ZMeter device | Build widget/logic/hardware package, explicit transport/axes/units/limits/channels, bounded lifecycle, and simulator |

Selecting an unregistered ID must continue to produce a visible profile
validation error rather than constructing an uncertain integration.

## Commissioning and promotion

Follow [hardware_safety.md](hardware_safety.md) and the target device README.
Hardware evidence applies only to the exact commit, profile hash, interpreter,
vendor runtime, model, wiring, limits, operation, and final state observed. Do
not enable runtime mutation for a real driver merely to test it.
