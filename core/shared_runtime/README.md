# Shared hardware runtimes

`core.shared_runtime` owns process-wide vendor runtimes and managers. Typed
services stay independent: replacing or reverting VISA must not change Kinesis,
and replacing or reverting Kinesis must not change VISA.

The standard local vendor layout is:

```text
core/shared_runtime/vendor/<runtime-name>/
```

Instructions and manifests are tracked. Proprietary DLLs and vendor XML files
are local and ignored. For Kinesis, populate `vendor/thorlabs_kinesis/` from one
complete, matching 64-bit release and verify it against `manifest.json` before
connecting. Do not mix files from device packages or installed releases.

Constructing `RuntimeServices`, `VisaRuntime`, or `KinesisRuntime` is side-effect
free. A widget with a shared VISA address selector schedules background
enumeration for the next Qt event-loop turn and retains its manual refresh
button; creating the runtime alone does not enumerate. The selector and its
popup expand to show the longest discovered address. Kinesis is validated and
loaded only when a device explicitly asks for native or managed bindings.

Device sessions own leases. Device disconnect closes/releases only its lease.
The startup/profile boundary terminates devices first, then calls provider
shutdown. Kinesis modules remain process-resident because native DLLs and
default-context .NET assemblies cannot be safely unloaded.

Diagnostics contain backend/path, loaded components, state, owners, and active
canonical VISA address reservations. They never contain credentials or
instrument responses; treat addresses and runtime paths as local diagnostics.

## Updating and restoring

1. Close every ZMeter/Python process.
2. Copy one complete reviewed release into `vendor/thorlabs_kinesis/`.
3. Update the tracked manifest version, sizes, and SHA-256 hashes together.
4. Run fake/static validation before any bench test.
5. Perform the device README's **User-executed hardware test**.

To restore a runtime family after a failed bench test, revert only that typed
service and its device migrations from Git history. Do not add hidden legacy
switches or make the other service depend on the restoration.
