# Mock Device

## Purpose and status

`mockDevice` is ZMeter's maintained, hardware-independent reference device. It implements the widget/logic/hardware/simulator separation, exact scan-channel signatures, lifecycle hooks, deterministic measurements, fault injection, bounded logging, and offscreen tests.

The checked-in startup profile creates two instances. Use this package for safe first launch, core scan development, and new-device contract examples.

## Scan channels

| Channel | Direction | Behavior |
| --- | --- | --- |
| `channel_A`, `channel_B` | get/set | Direct set and noisy read around stored value |
| `random_channel` | get | Deterministic pseudo-random scalar sequence |
| `ramp_channel_A`, `ramp_channel_B` | set | 0.01-unit steps at 0.001 seconds per step; returns the actual final value |

All setters reject non-finite values. Optional range rejection enforces `[-10, 10]`; when disabled, that simulated range is intentionally not enforced.

## Lifecycle and fault model

The widget provides `connect`, `disconnect`, `start_scan`, `stop_scan`, `force_stop`, and `terminate_dev`. Closing the device window hides it without disconnecting; final termination stops an active ramp and disconnects.

The simulator supports fail-after-N, random failure probability, and range-rejection faults. Its command log retains the most recent 500 entries. A stopped ramp preserves and returns the last completed step.

## Safe use and validation

Any non-empty mock address is accepted; the repository uses names such as `MOCK::TEST`. No vendor driver or instrument is involved.

Focused tests are in `devices/mockDevice/tests/test_mock_device.py` and cover discovery, lifecycle, direct/ramped values, stop behavior, injected faults, range rejection, reset, logging, and offscreen widget behavior. Run them only in a compatible PyQt6/NumPy environment:

```powershell
python -B -m unittest discover -s devices/mockDevice/tests -p "test_*.py" -v
```

See [device_contract.md](../../documents/device_contract.md) and [testing.md](../../documents/testing.md).
