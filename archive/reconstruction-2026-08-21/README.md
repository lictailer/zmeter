# Reconstruction Documentation Archive

This directory preserves completed plans, reviews, and investigation evidence
removed from the active `documents/` surface on 2026-08-21. These files are
historical and may describe intermediate states, superseded paths, or decisions
that were later narrowed. Current code, tests, canonical documents, and
device-local READMEs remain authoritative.

| Former path | Final status | Current successor |
| --- | --- | --- |
| `documents/restructure_manual/` | Eight-phase reconstruction completed | `documents/reconstruction_status.md`, ADR 002 |
| `documents/ZMETER_OFFLINE_BRANCH_COMPARISON_2026-08-13.md` | Historical comparison completed | `documents/device_status.md`, `documents/known_issues.md` |
| `documents/SHARED_RUNTIME_IMPLEMENTATION_PLAN_2026-08-14.md` | Implemented; hardware validation pending | `core/shared_runtime/README.md`, ADR 001 |
| `documents/DEVICE_LOGGING_AND_KINESIS_CONNECTION_PLAN_2026-08-18.md` | Implemented with approved reduced scope | `documents/architecture.md`, device READMEs |
| `documents/DEVICE_REGISTRATION_ROADMAP.md` | Both phases completed | `documents/device_status.md` |
| `documents/DEVICE_REGISTRATION_PHASE1_REVIEW.md` | Completed and consolidated | `documents/device_status.md`, Phase 1 device READMEs |
| `documents/DEVICE_REGISTRATION_PHASE2_REVIEW.md` | Completed and consolidated | `documents/device_status.md`, Phase 2 device READMEs |
| `documents/ZMETER_DEPLOYMENT_CLI_PLAN_2026-08-20.md` | Implemented in the standalone installer repository | `documents/release_deployment.md` |

The archive preserves unique evidence rather than deleting it. Do not copy
historical instructions back into active documentation without verifying them
against current behavior.
