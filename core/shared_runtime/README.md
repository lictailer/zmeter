# Shared hardware runtimes

`core.shared_runtime` owns process-wide vendor runtimes and managers. Typed
services stay independent: replacing or reverting VISA must not change Kinesis,
and replacing or reverting Kinesis must not change VISA.

The durable ownership decision is recorded in
`documents/decisions/001-shared-runtime-services.md`; current driver readiness
and pending hardware evidence are indexed in `documents/device_status.md`.

The standard local vendor layout is:

```text
core/shared_runtime/vendor/<runtime-name>/
```

The reviewed Kinesis DLLs, vendor XML files, setup instructions, and manifest
are tracked together. The contents of `vendor/thorlabs_kinesis/` must come from
one complete, matching 64-bit release and verify against `manifest.json` before
connecting. Do not mix files from device packages or installed releases.

Constructing `RuntimeServices`, `VisaRuntime`, or `KinesisRuntime` is side-effect
free. A widget with a shared VISA address selector schedules background
enumeration for the next Qt event-loop turn and retains its manual refresh
button; creating the runtime alone does not enumerate. The selector and its
popup expand to show the longest discovered address. Kinesis is validated and
loaded only when a device explicitly asks for native or managed bindings.
Each Kinesis API component builds its DeviceManager list once after a
successful initialization. Known-serial reconnects use the cached initialized
state; device integrations may request one serialized refresh after a direct
connection failure.

Device sessions own leases. Device disconnect closes/releases only its lease.
The startup/profile boundary terminates devices first, then calls provider
shutdown. Kinesis modules remain process-resident because native DLLs and
default-context .NET assemblies cannot be safely unloaded.

Diagnostics contain backend/path, loaded components, state, owners, and active
canonical VISA address reservations. They never contain credentials or
instrument responses; treat addresses and runtime paths as local diagnostics.

## Updating and restoring

1. Close every ZMeter/Python process.
2. Replace the tracked files in `vendor/thorlabs_kinesis/` from one complete
   reviewed release.
3. Update the manifest version, sizes, and SHA-256 hashes in the same change.
4. Run fake/static validation before any bench test.
5. Perform the device README's **User-executed hardware test**.

Deploy the complete `vendor/thorlabs_kinesis/` directory, including its
manifest, rather than copying an individual DLL named by the first load error.
For example, refresh the entire directory in
`D:\Xuguo\2026.08.14_sharedruntimes_test` before bench validation.

To restore a runtime family after a failed bench test, revert only that typed
service and its device migrations from Git history. Do not add hidden legacy
switches or make the other service depend on the restoration.
