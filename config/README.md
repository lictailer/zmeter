# ZMeter Profiles

ZMeter profiles select session paths and registered device instances without
putting device imports, addresses, or connection calls in the launcher.

`profiles/mock.json` is the checked-in hardware-safe default. It reproduces the
two mock-device labels and disabled-backup behavior of the previous launcher.
The stored mock address is not opened at startup because `connect_on_start` is
false.

Launch that default from the repository root with:

```powershell
python start_zmeter.py
```

Select another validated profile without editing the launcher with:

```powershell
python start_zmeter.py --profile config/profiles/example.local.json
```

An explicitly selected profile is never replaced with a fallback profile. A
missing, unreadable, or invalid profile prints its complete validation report,
shows the same report in a startup dialog, exits with a nonzero status, and does
not construct a device manager or device widget.

After validation, a small stage-only window remains visible while ZMeter loads
devices and issues requested startup connections. An enabled device whose
package, dependency, runtime, configuration, or widget construction fails is
reported and skipped; later devices still load, and the Main Window can open
with an empty or partial catalog. A requested connection failure is also
nonfatal. The session-only read-only System Log in the Main Window shows one
sanitized status line per enabled device and a compact total for disabled
devices. Recoverable application-level warnings are recorded there instead of
being duplicated in the console; device-specific details remain in the device
panel.

Relative profile filenames and `paths.save`/`paths.backup` values resolve from
the repository root, not the process's current directory. Absolute paths remain
absolute. Profile loading validates structure and registered connection fields
without importing drivers, constructing widgets, enumerating resources, or
opening connections.

Disabled entries are still schema-checked against their reviewed registry ID,
but they do not import a device package, construct a widget, enumerate a
resource, or connect. Enabled VISA widgets retain their established exception:
after construction they may schedule automatic resource discovery for the next
Qt event-loop turn. Changing that behavior to operator-only discovery is
deferred to a future approved update.

Channel filters accept `null` for all discovered channels or a list of names.
For compatibility with the existing application, syntactically valid names
that the constructed device does not expose are silently skipped. Strict
unknown-channel rejection or warnings are deferred to a separately approved
future update.

Runtime add, disconnect, and remove operations are separate from profile
configuration. They affect only the current process and never edit this JSON.
Only a code-reviewed registration with runtime mutation enabled and an explicit
busy probe is eligible; the checked-in registry currently permits only the mock
driver. The manager admits a change only while scan, queue, manual, router,
device-call, and device-owned activity is idle. Removal is also refused while a
stored session definition references the target label or one of its channels.
Restarting ZMeter reconstructs the selected profile exactly as written here.

Keep laboratory profiles local. Files named `*.local.json` and the
`profiles/local/` directory are ignored by Git. Do not commit instrument
addresses, serial numbers, credentials, private endpoints, or laboratory data
paths. Copy `profiles/example_lab.json` to a local ignored filename and add only
reviewed registry IDs and connection fields.

## Phase 1 registered driver fields

The default profile remains mock-only. These additional IDs are available for
one-device-at-a-time user commissioning in an ignored local profile:

| Driver | Connection object |
| --- | --- |
| `ni6423`, `nidaq` | `{"device_name": "Dev1"}` |
| `pem100` | `{"address": "...", "timeout_ms": 20000}` |
| `sp150` | `{"address": "...", "timeout_ms": 10000, "query_delay_s": 1.0}` |
| `hp34401a`, `keithley24xx`, `sr860`, `sr830` | `{"address": "..."}` |
| `demo_device` | `{"address": "DUMMY::INSTR"}` |
| `bbd30x`, `k10cr1` | `{"serial": "..."}` |

Keep `connect_on_start` false for first commissioning. Every registered Phase 1
driver now supports a best-effort startup request through the same public path
as its device panel. NI6423, NIDAQ, PEM100, SP150, HP34401A, SR860, SR830, demo,
and mock connections report immediate success or failure. Keithley24xx,
BBD30X, and K10CR1 report that their existing asynchronous request was accepted;
their panels remain authoritative for the final result and manual retry. For NI
drivers, the field name is `device_name`, not `address`. All real Phase 1
drivers remain ineligible for runtime add, manager disconnect, and removal.

The tracked `profiles/phase1_lab.json` intentionally keeps every
`connect_on_start` value false. Copy it to an ignored local profile before
inserting real identifiers or enabling reviewed connection requests.

See `documents/device_status.md`, `documents/hardware_safety.md`, and the target
device README before enabling a driver.

## Phase 2 registered driver fields

Phase 2 admits four environment-specific startup-only drivers:

| Driver | Connection object |
| --- | --- |
| `four9` | `{"host": "...", "port": 5050, "socket_timeout_s": 10.0}` |
| `montana2` | `{"address": "..."}` |
| `opticool` | `{}` |
| `tlpm` | `{}` |

All four use the same ordered best-effort startup behavior as Phase 1. Their
connection requests schedule the existing panel workers and are reported as
pending; inspect the device panel for final success, failure, and manual retry.
Montana2 requires an explicit profile address even though its standalone panel
retains the existing quick-connect default. OptiCool retains the fixed vendor
DLL path and TLPM retains first-discovered-resource selection and reset. The
tracked `profiles/phase2_lab.json` keeps all entries disabled and all startup
flags false. Copy it to an ignored local profile for commissioning.

`autofocus_xz`, `auto_focus`, `auto_position`, and `anc300` remain deliberately
unregistered. See `documents/device_status.md` for the current blockers and
future work; registration is not hardware approval.
