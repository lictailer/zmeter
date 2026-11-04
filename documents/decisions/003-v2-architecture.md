# 003: v2 architecture by incremental replacement on release/beta

- Status: Accepted
- Date: 2026-11-03
- Owners: ZMeter maintainers
- Supersedes: none

## Context

The current code works in the lab, but several properties make further growth
expensive and risky:

- `MainWindow` is both the application window and the channel hub. Scans,
  panels, the router, and queues reach devices through it, so the scan engine
  cannot run or be tested without Qt.
- Device writes are checked against `scan_range_limits.json` only on the scan
  path. Device panels call device logic directly, and a channel without a scan
  limit (for example a nidaq AO) is silently unlimited.
- A device needs a widget, a logic class, a hardware class, a registration, and
  reflected `get_`/`set_` methods. Declaring a new instrument is mostly
  boilerplate.
- Many names only make sense after reading the code (`setter`, `getter`,
  `setting_array`, `equips`, `write_info`, `Brakets`).
- Persisted scan files carry no format version, so a later format change could
  not tell old files from new ones.

A previous attempt (the Mfork) developed a replacement on a separate branch.
After a few months its core could no longer be merged and features had to be
ported by hand. This decision avoids that failure mode.

The full plan, with phases and acceptance gates, is the "zmeter long-term
upgrade plan" maintained by the owner. This ADR records the decisions that
other repository documents and agents must follow.

## Decision

1. **Strangler approach on one branch.** There is no long-lived "v2" branch.
   New code is added on `release/beta` in new packages and ships next to the old
   code. Old and new code are tested together on every change.
2. **Off by default, switch, then delete.** Each phase ships new code switched
   off, switches the default after a bench check by the user, and deletes the old
   code only after at least one stable tag. Switching and deleting are separate
   pull requests. A phase is not done until its old code and the matching legacy
   documentation paragraphs are deleted.
3. **New packages and import rules.**
   - `zcore/` holds code with no Qt and no hardware dependency. Data and file
     format code lives in `zcore/data/`. `zcore` never imports `PyQt6`, `core`,
     `devices`, or `zui`.
   - `zui/` holds the Qt user interface of the new architecture. It may import
     `zcore`.
   - New declarative devices import only the device SDK in `zcore` and their own
     vendor libraries.
   - Optional vendor libraries are never imported at module top level in `core/`
     or `zcore/`.
   - `tests/test_layering.py` enforces these rules from the first commit of the
     packages.
4. **Two-tier output limits.** A *device limit* (in the device declaration,
   changed only through code review) applies to every write from every source. A
   *scan limit* (`scan_range_limits.json`, edited by the user) applies to scan,
   queue, and router writes and must lie inside the device limit. During
   migration a missing limit produces a warning; after all devices are migrated a
   device without device limits refuses to connect and a scan that writes a
   channel without a scan limit refuses to start.
5. **Persisted formats carry `format_version`.** Scan JSON gets
   `format_version` and `software` in phase 0. A missing value is read as 1.
   The phase 0 value is 2, not 1: v1.0-beta.5 already writes
   `format_version: 2` into scans that ran (setup capture), so lab files with
   2 exist. Key renames in files happen once, together with
   `format_version: 3`; readers accept every older version and old files stay
   readable.
6. **Naming.** `documents/naming.md` is the naming reference. New code uses the
   new names; old names are replaced in stages and persisted keys change last.
7. **English only.** Everything committed to the repository (code, comments,
   docstrings, documents, commit messages) is in English.
8. **Explicit decision for a second scan engine.** The rule in
   `documents/architecture.md` against a second scan engine or persistence path
   is lifted only for the transition described here: a v2 scan engine and
   storage may exist next to the legacy ones, selected by a setting
   (`scan_engine = legacy | v2`, default `legacy`) until the removal conditions
   below are met.

### Transition interfaces

`AGENTS.md` forbids shims, adapters, fallbacks, and duplicate implementations
without a concrete current need. The following transition interfaces are
approved by this ADR. Each has a removal condition. Anything not listed here is
still forbidden.

| Transition interface | Purpose | Removal condition |
| --- | --- | --- |
| Re-exports left at old module locations when a module moves into `zcore`/`zui` | Keep imports and tests working while callers are updated | Removed one stable tag after the move |
| `zui` bridge adapter and `LegacyProvider` | Let the new channel layer reach devices that are still written in the old style | Removed at the end of phase 5 (all devices migrated) |
| `scan_engine = legacy \| v2` setting and the legacy scan engine | Roll back the phase 3 switch without a code change | Removed one stable tag after the phase 3 default switch |
| `demo_device` unavailable registration | Old workbooks that still contain the `demo_device` row keep loading (an unregistered driver in any row fails the whole profile) | Removed at the end of phase 5 |

Adding a transition interface requires amending this ADR with its removal
condition in the same pull request that introduces it.

## Consequences

- Operators see nothing new until a phase switches its default. Phase 0 adds one
  warning line (scan channel without a scan limit) and two fields in scan JSON
  (`format_version`, `software`).
- Reviewers can reject any compatibility code that is not listed above or lacks
  a removal condition.
- Old and new code coexist for months, so the test suite and documentation carry
  both until each phase deletes the old side. Documents use a "current" section
  and a "v2 (transition)" section during that time instead of a parallel set of
  documents.
- Version `v2.0-beta` starts when phase 3 makes the new scan engine the default;
  until then the version stays `v1.x`.
- Lab workbooks and queue files keep working throughout. Channel ids stay
  `<device label>_<channel name>`.

## Alternatives considered

- **Rewrite on a separate branch (as the Mfork).** Rejected: the branches
  diverge, features must be ported twice, and the new core is never exercised
  with the lab's real workflow until late.
- **Stay with the current structure.** Rejected: write safety, testability
  without Qt, and device boilerplate stay unsolved and get worse with every
  device.
- **Big-bang refactor inside `core/`.** Rejected: no switch to roll back a
  phase, and every step risks the scan path the lab depends on.

## Validation implications

- Static and unit: `tests/test_layering.py` runs in every PR; each phase adds
  unit tests for the new packages that need neither Qt nor hardware.
- Differential tests (phase 3): the same scan plan through the legacy and v2
  engines on mock devices must produce the same writes, reads, and saved data.
  Simulation cannot prove hardware timing.
- Persistence: round trips on old files for every format change; old files stay
  readable.
- User-executed hardware bench: required before each phase switches its default.
  An agent bench test on the test PC ("Agent bench tests on the test PC" in
  `documents/hardware_safety.md`) never replaces it.
