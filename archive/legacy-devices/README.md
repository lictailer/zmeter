# Legacy devices

Device packages retired from `devices/` in v2 phase 0 (PR 9). They are kept for
project history only, are not imported by any code under `core/` or `devices/`,
and are excluded from release ZIPs (`archive/` is `export-ignore`). Their
internal imports still name the former `devices.*` paths, so they do not run
from here.

| Former location | Archived location | Notes |
| --- | --- | --- |
| `devices/demoDevice/` | `archive/legacy-devices/demoDevice/` | Simulated VISA template. Its fake VISA manager moved to `tests/fixtures/dummy_visa.py` and is used by the shared VISA runtime tests. The `demo_device` driver ID stays registered as an unavailable driver until the end of v2 phase 5 (ADR 003) so older workbooks that still contain the row keep loading. Use `mock_device` for new integration work. |
| `devices/ANC300/` | `archive/legacy-devices/ANC300/` | Unregistered Attocube ANC300 source fragment. It was never selectable by a workbook. |
