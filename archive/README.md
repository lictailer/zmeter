# Documentation Archive

This directory contains material retained for project history and recovery. It is not the source of truth for current ZMeter behavior.

## 2026-08-21 reconstruction consolidation

Completed reconstruction manuals, implementation plans, registration reviews,
and investigation records are indexed in
[archive/reconstruction-2026-08-21/README.md](reconstruction-2026-08-21/README.md).
They were removed from the active `documents/` surface after their current
outcomes, readiness state, known issues, and durable decisions were consolidated
into canonical documentation.

## 2026-08-13 documentation snapshot

All documentation that existed before the new agent-instruction system was moved to:

```text
archive/documentation-2026-08-13/
```

The snapshot preserves every file's former repository-relative path:

| Former location | Archived location |
| --- | --- |
| `agent.md` | `archive/documentation-2026-08-13/agent.md` |
| `README.md` | `archive/documentation-2026-08-13/README.md` |
| `CODEX_CONTRIBUTION_WORKFLOW_TUTORIAL.md` | `archive/documentation-2026-08-13/CODEX_CONTRIBUTION_WORKFLOW_TUTORIAL.md` |
| `documents/README_scan_overview.md` | `archive/documentation-2026-08-13/documents/README_scan_overview.md` |
| `documents/README_scan_logic.md` | `archive/documentation-2026-08-13/documents/README_scan_logic.md` |
| `documents/device_command_bus_guide.md` | `archive/documentation-2026-08-13/documents/device_command_bus_guide.md` |
| `autofocus_xuguo/README.md` | `archive/documentation-2026-08-13/autofocus_xuguo/README.md` |
| `autofocus_xuguo/autofocusXZ.md` | `archive/documentation-2026-08-13/autofocus_xuguo/autofocusXZ.md` |
| `demoDevice/README.md` | `archive/documentation-2026-08-13/demoDevice/README.md` |
| `mockDevice/README.md` | `archive/documentation-2026-08-13/mockDevice/README.md` |
| `ni6423/ai_refactor_v1.md` | `archive/documentation-2026-08-13/ni6423/ai_refactor_v1.md` |
| `ni6423/cI_channel_structure.md` | `archive/documentation-2026-08-13/ni6423/cI_channel_structure.md` |
| `ni6423/counter_refactor_v1.md` | `archive/documentation-2026-08-13/ni6423/counter_refactor_v1.md` |
| `sr860/sr860_readme.md` | `archive/documentation-2026-08-13/sr860/sr860_readme.md` |
| `tlpm/readme.md` | `archive/documentation-2026-08-13/tlpm/readme.md` |

These files include useful design history, device notes, known-risk observations, and the workflow tutorial used to begin the documentation rebuild. They also contain stale, contradictory, lab-specific, or unverified statements. Consult them only as historical evidence and confirm all behavior in current code and tests.

At the time of this snapshot, the only active documentation introduced by that
first rebuild step was the repository-root `AGENTS.md`. Later canonical
documentation is indexed by `documents/README.md`.
