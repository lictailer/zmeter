# ZMeter Profiles

ZMeter profiles select session paths and registered device instances without
putting device imports, addresses, or connection calls in the launcher.

`profiles/mock.json` is the checked-in hardware-safe default. It reproduces the
two mock-device labels and disabled-backup behavior of the previous launcher.
The stored mock address is not opened at startup because `connect_on_start` is
false.

Relative profile filenames and `paths.save`/`paths.backup` values resolve from
the repository root, not the process's current directory. Absolute paths remain
absolute. Profile loading validates structure and registered connection fields
without importing drivers, constructing widgets, enumerating resources, or
opening connections.

Channel filters accept `null` for all discovered channels or a list of names.
For compatibility with the existing application, syntactically valid names
that the constructed device does not expose are silently skipped. Strict
unknown-channel rejection or warnings are deferred to a separately approved
future update.

Keep laboratory profiles local. Files named `*.local.json` and the
`profiles/local/` directory are ignored by Git. Do not commit instrument
addresses, serial numbers, credentials, private endpoints, or laboratory data
paths. Copy `profiles/example_lab.json` to a local ignored filename and add only
reviewed registry IDs and connection fields.
