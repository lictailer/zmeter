# 001: Shared process runtime services for hardware integrations

- Status: Implemented locally; hardware validation pending
- Date: 2026-08-14
- Owners: ZMeter maintainers
- Supersedes: none

The shared implementation is under `core/shared_runtime/`. Current device code,
the runtime manifest, and tests remain authoritative for exact behavior.

## Context

Several ZMeter devices depend on process-wide vendor runtimes or managers, but
the application does not currently coordinate their selection, ownership, or
shutdown.

K10CR1 and BBD30X both depend on the Thorlabs Kinesis runtime. K10CR1 loads a
package-local native Kinesis library at module import, while BBD30X lazily loads
managed Kinesis CLI assemblies from a separately selected directory. Their
device-specific libraries depend on common Kinesis components such as
`Thorlabs.MotionControl.DeviceManager.dll`. If different releases or directories
are mixed in one process, the first loaded dependency can determine what the
later device receives. Import or connection order can therefore cause
order-dependent load failures.

The maintained environment currently contains PyVISA 1.16.1. For one canonical
VISA backend/library, repeated `pyvisa.ResourceManager()` calls reuse the same
manager. Closing that manager also closes resources opened through its other
references. Current VISA devices create managers independently and have
inconsistent ownership: PEM100, SP150, and HP34401A close a manager during
device disconnect, while several older drivers retain only their instrument
session. Disconnecting one device can consequently invalidate other active VISA
sessions that use the same backend.

These cases share a lifecycle problem but not a vendor API. The architecture
must distinguish:

- a **runtime**, such as one Kinesis DLL set, one VISA backend, or the hosted
  .NET CLR;
- a **manager**, such as a VISA resource manager or Kinesis device manager;
- a **device session**, such as one VISA instrument, controller, channel, DAQ
  task, or serial port.

Process runtimes and compatible managers may be shared. A physical device
session remains owned by one device integration unless an explicit, tested
exception is designed.

## Decision

ZMeter will introduce a small, typed runtime-service layer rather than allowing
device packages to select and close process-wide runtimes independently.

The implementation uses `core/shared_runtime/` so the application-owned service
layer remains visibly separate from device packages.
The startup/profile boundary will create one `RuntimeServices` provider, inject
the required typed service into enabled devices, and arrange for provider
shutdown only after device sessions have been terminated. Constructing the
provider or a device widget must not import optional vendor runtimes, enumerate
hardware, or connect to a device.

The common layer will provide:

- lazy initialization;
- canonical configuration keys and conflict detection;
- ownership leases and physical-resource reservations;
- thread-safe runtime initialization and shared-manager operations;
- diagnostics for selected paths, versions/backends, owners, and open leases;
- deterministic process shutdown;
- injectable fake factories for hardware-independent tests.

Vendor behavior will remain in typed adapters. The first adapters will be
`KinesisRuntime` and `VisaRuntime`; there will not be one untyped universal
hardware manager.

### KinesisRuntime

`KinesisRuntime` will:

- select one canonical Kinesis directory and compatible release/bitness for the
  process;
- validate the complete native and managed dependency set needed by enabled
  Kinesis devices before loading;
- retain Windows DLL-directory handles for the process lifetime;
- load K10CR1 native bindings lazily instead of during Python import;
- load BBD30X managed bindings from the same canonical directory;
- serialize shared initialization such as `BuildDeviceList()`;
- reject any later request for a different path or incompatible version with a
  clear error;
- avoid falling through to another directory after a managed assembly has been
  partially loaded, because default-context .NET assemblies cannot be reliably
  unloaded or replaced;
- remain loaded until process shutdown.

The service does not distribute proprietary Kinesis binaries. The laboratory
populates the ignored repo-relative
`core/shared_runtime/vendor/thorlabs_kinesis/` directory from one reviewed
release. The tracked manifest validates the required local files before load.

### VisaRuntime

`VisaRuntime` will:

- own one PyVISA `ResourceManager` for each canonical backend specification,
  such as the configured IVI library or `@py`;
- open a separate instrument session for each device address;
- make device disconnect close only that instrument session and release its
  lease;
- close the shared resource manager only at application shutdown after all
  instrument sessions have been closed;
- reject duplicate ownership of one VISA address by default, with any exception
  requiring an explicit device contract and serialization policy;
- keep resource enumeration an explicit user/profile operation rather than an
  import or construction side effect;
- support injected fake managers without globally monkey-patching `pyvisa`.

Sharing the VISA manager does not imply sharing instrument sessions or assuming
that concurrent calls are safe. Each session will retain device-specific
terminations, timeout, serial configuration, protocol validation, and locking.

### Migration boundary

Migration will be incremental:

1. Add the common lifecycle, lease, diagnostics, and fake-service tests without
   activating hardware.
2. Migrate K10CR1 and BBD30X to `KinesisRuntime` and remove their independent
   runtime selection.
3. Migrate PEM100, SP150, HP34401A, Keithley24xx, SR830 v2, and SR860 to
   `VisaRuntime`, then route UI resource listing through the same service.
4. Replace `demoDevice`'s global PyVISA monkey-patch with injected fake services.
5. Leave legacy `sr830/` unchanged and unsupported in shared-VISA profiles.
6. Evaluate additional typed adapters or reservation policies only when their
   device packages are actively maintained.

The initial change will not alter scan channels, device units, hardware limits,
protocol commands, startup-profile activation, or persisted scan formats.

Shared operation is the only maintained path for migrated packages. Old
device-local loaders, manager factories, constructor enumeration, and hidden
legacy switches are not retained. Each vendor family can be restored
independently from Git history if user bench validation fails.

### Later candidates

The same lifecycle framework may later cover:

- OptiCool's process-wide pythonnet/CLR selection, using a separate managed
  assembly family from Kinesis;
- TLPM native-library path, version, bitness, and lazy loading while preserving
  independent TLPM sessions;
- NI-DAQ/PyDAQmx physical-channel, counter, and task-name reservations rather
  than sharing DAQ tasks;
- `auto_focus` and `autofocus_xuguo` exclusive serial-port reservations rather
  than sharing serial sessions;
- future spectrometer/Andor SDK runtime selection and exclusive camera handles;
- duplicate endpoint protection for network instruments where demonstrated to
  be necessary.

These candidates share provider lifecycle and diagnostics, not a common vendor
API. They are not part of the first implementation phase.

## Consequences

Positive consequences:

- Kinesis load behavior no longer depends on device import or connection order.
- All enabled Kinesis devices use one verified runtime release and directory.
- Disconnecting one VISA instrument cannot close unrelated VISA instruments.
- Runtime ownership, failure state, and shutdown order become inspectable.
- Optional runtimes remain lazy and disabled profiles remain hardware-free.
- Fake injection becomes consistent, reducing global monkey-patching and making
  multi-device lifecycle tests practical.
- Duplicate physical-resource ownership and shared initialization races can be
  rejected early with actionable errors.

Negative consequences:

- A new shared subsystem must be designed, documented, and maintained.
- Existing drivers have different constructor, connection, and cleanup
  contracts and require careful migration.
- Reference/lease handling and thread-safe shutdown introduce failure modes that
  need focused tests.
- The runtime provider becomes shared infrastructure, so an error can affect
  several devices.
- Vendor-specific behavior cannot be hidden completely; typed adapters and
  device-specific cleanup remain necessary.
- A runtime that has partially failed to load may require restarting the Python
  process rather than attempting recovery in place.

The primary benefit is correctness and predictable ownership, not a significant
performance improvement.

## Alternatives considered

### Keep each device independent and document import order

Rejected. Import order is not a stable dependency-resolution mechanism and does
not solve PyVISA manager ownership.

### Implement unrelated Kinesis and VISA fixes only

Rejected as the complete design. Their vendor adapters must remain separate, but
they need the same lifecycle, ownership, injection, diagnostics, and shutdown
principles. Duplicating that infrastructure would invite inconsistent behavior.

### Use one universal hardware manager

Rejected. Kinesis DLL binding, VISA manager ownership, serial exclusivity, and
DAQ channel reservations have different semantics. A universal untyped API
would obscure safety-relevant behavior.

### Share every device session

Rejected. Sharing a runtime or manager is different from sharing a physical
instrument handle. Device sessions remain exclusive by default.

### Run every vendor stack in a separate process

Deferred as a fallback. Process isolation is appropriate if two required vendor
runtimes cannot coexist at compatible versions, but it adds IPC, process
supervision, error propagation, and shutdown complexity that is unnecessary for
the first implementation.

## Validation implications

All automated validation must remain hardware-independent. It must not load real
Kinesis DLLs, instantiate a real PyVISA resource manager, enumerate devices, or
open laboratory sessions.

Required implementation evidence includes:

- static tests for canonical path/backend normalization and version conflicts;
- fake-runtime tests proving imports and widget construction have no hardware
  side effects;
- Kinesis tests covering both device load orders, one-time loading, conflicting
  path rejection, retained DLL-directory handles, partial-load errors, and
  serialized shared initialization;
- PyVISA tests with at least two simultaneous fake instruments proving that one
  device disconnect closes only its session and manager shutdown occurs once,
  after all sessions are released;
- duplicate-address and lease cleanup tests, including partial connection
  failures and repeated disconnect/shutdown;
- offscreen widget tests with injected services;
- existing core, mock-device, K10CR1, BBD30X, PEM100, SP150, and migrated-device
  regression suites;
- documentation of selected runtime paths/backends and shutdown ownership.

Real-runtime and bench validation remains a **User-executed hardware test**. It
must be reviewed separately and include compatible Kinesis version/bitness,
multiple simultaneous VISA instruments, disconnect isolation, device-specific
limits, stop behavior, and final shutdown cleanup.
