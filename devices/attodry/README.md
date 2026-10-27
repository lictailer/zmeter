# attocube attoDRY2100

## Purpose and readiness

This package integrates the laboratory attoDRY2100/2100e controller with ZMeter. It controls the sample-temperature loop and the single Z-axis superconducting magnet through attocube's `atto_device` 1.12.0 Python API. The driver is registered for startup profiles, disabled by default, and not approved for runtime add/remove. Automated evidence uses an injected fake API only. Real hardware validation remains pending.

The defaults target the laboratory's attoDRY2100 with a 9 T single-axis magnet and persistent switch. Review the system-specific certificate and controller configuration before using them on another installation. The maintained software limits are sample setpoints 1.8-300 K and field setpoints -9 to +9 T. ZMeter does not change PID zones, field ramp tables, driven/persistent mode, or quench state.

## Dependency and connection

The device panel imports no vendor package and performs no network operation until Connect is requested. Keep the supplied `api_atto-device-python_1.0.12.whl` beside `deploy_zmeter.py`, or retain the supplied `Attocube/u drive/Software/API/` tree beside the deployer. Companion installer branch `MS/optional-attodry-installation` offers the optional API when a selected published ZMeter release contains this driver. Answer yes to install it, or no to continue without attoDRY. The installer discovers the local wheel or asks for its path, verifies its SHA-256, stages the standards-compliant name `atto_device-1.12.0-py3-none-any.whl`, and installs it into the exact release environment after Conda finishes. Missing/corrupt wheels fail before Conda changes when installation is requested. The wheel is not republished because redistribution permission has not been established. An unpublished development checkout uses the manual fallback below; it is not a verified release package.

For a deliberate manual fallback, first copy or rename the wheel, because `pip` rejects the historical vendor filename:

```powershell
Copy-Item "<USB drive>\Software\API\api_atto-device-python_1.0.12.whl" ".\atto_device-1.12.0-py3-none-any.whl"
python -m pip install ".\atto_device-1.12.0-py3-none-any.whl"
```

The wheel contains `atto_device` 1.12.0 despite the historical archive filename. Configure only the controller host name or IP address in the workbook `address` column. For the laboratory controller whose browser is `http://192.168.1.1/`, enter only `192.168.1.1`. The vendor API uses TCP port 9090. Do not include `http://`, a path, or a port suffix. Never run network discovery from ZMeter.

## Scan channels

| Channel | Direction | Unit and behavior |
| --- | --- | --- |
| `T` | get/set | Sample temperature in kelvin; `set_T` starts controller temperature control and returns immediately |
| `T_stable` | set | Starts the same control, then uses the panel's temperature tolerance, consecutive-reading count, and reading interval; 4 h timeout |
| `B` | get/set | Z-axis magnetic field in tesla; `set_B` checks quench state, applies the target, starts field control, and returns immediately |
| `B_stable` | set | Starts the same control, then waits for the vendor field-control sequence to finish and applies the panel's field tolerance, consecutive-reading count, and reading interval; 2 h timeout |

The exact scan-visible method names are `get_T`, `get_B`, `set_T`, `set_T_stable`, `set_B`, and `set_B_stable`. Live panel polling reads `T`, `B`, and the vendor field-state string once per second when the worker is idle. All API calls share one lock so panel polling and scan calls cannot use the socket concurrently. Scan start disables live polling and scan cleanup may re-enable it through the panel.

The panel provides separate **T stability** and **B stability** rows. Each row configures the absolute tolerance, required consecutive **Readings**, and **Interval** in seconds between those readings. Temperature defaults to ±0.05 K, five readings, every 2 s; field defaults to ±0.001 T, five readings, every 2 s. Temperature tolerance accepts 0.001-5 K, field tolerance accepts 0.00001-0.1 T, the reading count accepts 2-100, and the interval accepts 0.5-60 s. The lower bounds retain an actual consecutive-reading check and avoid aggressive controller polling.

Both manual and scan stable calls use these values. A wait atomically snapshots all three settings before issuing its controller command, and its row is disabled until that wait ends, so editing cannot weaken an active wait. All settings are deliberately session-only and return to their defaults on every ZMeter launch; this prevents unusually loose criteria from silently carrying into another measurement session. Field stability additionally requires the controller's field-control sequence to finish, regardless of the selected numerical criteria.

`force_stop` and the panel's Stop stable wait button interrupt only ZMeter's wait loop. They deliberately do not call `stopFieldControl`, change persistent mode, or cancel the controller's active temperature/field target. The last confirmed readback is reported. This preserves controller ownership of the superconducting-magnet sequence.

## Startup profile

Use a disabled row for first commissioning:

| id | driver | enabled | connect_on_start | address | scan set | scan get |
| --- | --- | --- | --- | --- | --- | --- |
| `attodry` | `attodry` | `FALSE` | `FALSE` | controller host/IP | `T, T_stable, B, B_stable` | `T, B` |

For the first run, enter the reviewed controller address, keep `enabled=FALSE`, close Excel, and review the workbook. Then set `enabled=TRUE` while keeping `connect_on_start=FALSE`. Open the panel, compare its disconnected display with the native controller UI, and connect manually.

## User-executed hardware test

Only a trained operator may perform this procedure.

1. Record the exact ZMeter revision, workbook hash, Python environment, `atto_device` version, controller firmware, cryostat state, magnet state, configured ramp tables, quench indication, and approved temperature/field limits.
2. Keep the workbook row startup-only with `connect_on_start=FALSE`. Start ZMeter, open the attoDRY panel, and confirm that no connection occurs before pressing Connect.
3. Connect with the approved controller address. Compare temperature, field, and field-state readbacks with the native attoDRY interface. Do not change a target yet.
4. Set `T` and `B` equal to their current native-interface setpoints. Confirm that the controller accepts them without an unexpected ramp or mode change.
5. With lab-approved small changes, test `set_T` and `set_B`, watching the native controller throughout. Confirm units, direction, configured ramp rates, persistent-switch sequence, and final readbacks.
6. Test `set_T_stable` and `set_B_stable` first with their defaults, then with one lab-approved alternate tolerance/count/interval combination for each. Confirm the logged criteria, consecutive-read behavior, controller-completion requirement for field, and restart reset. Press Stop stable wait during each and confirm that ZMeter exits its wait while the controller retains the commanded target.
7. Run a two-point temperature-only scan, then a two-point field-only scan inside approved limits. Verify scan data, live-poll suspension, cleanup, and final controller state.
8. Test an out-of-range target, simulated connection loss if an approved network isolation method exists, Queue Stop during a stable wait, panel disconnect, and full application shutdown. Confirm no unintended setpoint, persistent-mode, quench-reset, or ramp-table change.
9. Leave the cryostat in the lab's approved final state and record all discrepancies before enabling `connect_on_start`.

Do not perform the magnet portion if the native controller reports a quench, unexpected temperature, unknown persistent-switch state, or a mismatch with the system-specific magnet documentation.
