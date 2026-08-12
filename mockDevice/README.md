# Mock Device

`mockDevice` is a fully simulated ZMeter instrument for exercising scan logic
without physical hardware. It is intentionally self-contained and does not
patch PyVISA or modify ZMeter core behavior.

## Architecture

```text
MockDevice (Qt widget)
    -> MockDeviceLogic (QThread and scan API)
        -> MockDeviceHardware (thin adapter)
            -> MockDeviceSimulator (state, noise, ramps, faults, log)
```

The simulator owns the authoritative A/B values. The hardware and logic layers
do not maintain duplicate device state.

## Scan channels

The logic layer exposes exactly these channels:

- Setters: `channel_A`, `channel_B`, `ramp_channel_A`, `ramp_channel_B`
- Getters: `channel_A`, `channel_B`, `random_channel`

Direct setters update immediately. A/B getters return the stored value plus
Gaussian noise with a default standard deviation of `0.001`. The random getter
returns a standard Gaussian value.

Ramps use a fixed `0.01` step at `1000 Hz`. The final step lands exactly on the
target, and emergency stop preserves the last completed step.

## Lifecycle

The widget provides the lifecycle methods expected by `MainWindow`:

```python
connect(address="MOCK::INSTR")
disconnect()
start_scan()
stop_scan()
force_stop()
terminate_dev()
```

The logic layer provides the corresponding `connect_device`,
`disconnect_device`, `start_scan`, `stop_scan`, `force_stop`, and `close`
methods.

## Faults

The UI can enable three deterministic test conditions:

- Fail once on the Nth subsequent scan operation.
- Fail each scan operation with a selected probability.
- Reject setter targets outside `[-10, 10]`.

NaN and infinite setter targets are always rejected. Fault checks occur once
per external scan operation; internal ramp steps do not increment the command
counter.

## Optional application setup

Registration is intentionally outside this package. A future setup can import
and instantiate it in a selected startup profile:

```python
from mockDevice.mock_device_main import MockDevice

equips["mock_0"] = MockDevice()
equips["mock_0"].connect("MOCK::INSTR")
```

## Tests

From the repository root in the ZMeter environment:

```powershell
python -B -m unittest discover -s mockDevice/tests -p "test_*.py" -v
```
