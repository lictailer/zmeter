# Quantum Design OptiCool

## Purpose and status

This package controls a Quantum Design OptiCool through the vendor .NET `QDInstrument.dll`. It provides temperature and magnetic-field set/read operations plus optional waits for stable/holding status. It is a startup-only registered real-hardware integration with no production simulator or fake .NET backend.

Importing or constructing the panel does not load the vendor runtime. Each Connect attempt loads the DLL from the retained fixed path `C:\QdOptiCool\LabVIEW\QDInstrument.dll`, waits the established one second, and then creates the vendor objects. A failed attempt clears partial state, remains disconnected, and can be retried from the panel. The Python environment must supply pythonnet/.NET modules (`clr`, `System`, and `QuantumDesign`); these are not fully represented by the maintained Conda file.

## Scan channels

| Channel | Direction | Unit |
| --- | --- | --- |
| `temperature` | get/set | kelvin |
| `temperature_stable` | set | kelvin; set then wait |
| `field` | get/set | tesla at the logic boundary |
| `field_stable` | set | tesla; set then wait |

The vendor field interface uses gauss, and logic converts to/from tesla with a factor of 10,000. Temperature hardware defaults to a rate of 20 in vendor units; field defaults to 150 in vendor units.

The hardware prints a warning for temperatures outside 1.5–350 K but still sends the command. Therefore this check is not a safety limit. Enforce approved temperature, field, and ramp-rate bounds in validated configuration before use.

## Stable waits and lifecycle

Temperature wait exits on vendor `Stable`, a 50-sample standard-deviation threshold below 0.0001 K, or a user abort. Field wait exits on vendor `Holding` or abort. Neither loop has an overall timeout in current logic.

The widget runs jobs in a `QThread` and exposes an abort button for stable waits; the manager maps that abort request to force-stop. There are no `start_scan` or `stop_scan` hooks. `terminate_dev` waits up to two seconds and then disconnects; it does not guarantee a long wait has stopped. These are accepted registration limitations.

Agents must not load/use the vendor API to connect, set temperature/field, wait, read, abort, or disconnect. Before enabling, the user must review limits, units, approach modes, timeout/abort behavior, and shutdown. See [hardware_safety.md](../../documents/hardware_safety.md).

## Validation

Hardware-independent syntax check: `python -B -m py_compile devices/opticool/opticool_hardware.py devices/opticool/opticool_logic.py devices/opticool/opticool_main.py`. It does not prove that pythonnet or the vendor DLL can load.

**User-executed hardware test:** with the OptiCool in a known safe state, confirm the vendor application and emergency procedures; connect and read temperature/field without changing them; set each target equal to its current readback; exercise and abort both stable-wait paths; make only lab-approved small temperature and field changes inside configured rate/limit bounds; terminate; and verify the instrument remains in the intended holding state. Do not use the current software warning as a temperature interlock.
