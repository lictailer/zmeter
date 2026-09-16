"""Manual MFLI demo: connect, write four tone amplitudes/phases, read four demods.

Run this file directly in the same environment as connection_demo.py.
Configure four demodulators and their frequencies in LabOne first (MF-MD option).
Only amplitude and phase nodes are written. Written values remain in place.
"""

import math
import sys
import time

import connection_demo as connection


# Reuse the working connection settings; these can also be overridden here.
DEVICE_ID = connection.DEVICE_ID
SERVER_HOST = connection.SERVER_HOST
SERVER_PORT = connection.SERVER_PORT

# LabOne channels 1, 2, 3, 4 (API indices 0, 1, 2, 3).
AMPLITUDES_VPK = [0.001, 0.001, 0.001, 0.001]
PHASES_DEG = [0.0, 45.0, 90.0, 135.0]
SETTLE_SECONDS = 1.0  # Increase for long demodulator filter time constants.


def validate_settings(amplitudes, phases, settle_seconds):
    if len(amplitudes) != 4 or len(phases) != 4:
        raise ValueError("Provide exactly four amplitudes and four phases.")
    if not all(math.isfinite(value) for value in (*amplitudes, *phases)):
        raise ValueError("Amplitudes and phases must be finite numbers.")
    if any(not -180 <= phase <= 180 for phase in phases):
        raise ValueError("Phases must be between -180 and 180 degrees.")
    if not math.isfinite(settle_seconds) or settle_seconds <= 0:
        raise ValueError("SETTLE_SECONDS must be finite and positive.")


def sample_value(sample, field):
    values = sample.get(field, [])
    if len(values) == 0:
        raise ValueError(f"Demodulator sample has no {field} data.")
    value = float(values[-1])
    if not math.isfinite(value):
        raise ValueError(f"Demodulator sample contains invalid {field} data.")
    return value


def sample_timestamp(sample):
    values = sample.get("timestamp", [])
    if len(values) == 0:
        raise ValueError("Demodulator sample has no timestamp.")
    return int(values[-1])  # Keep integer precision for freshness comparison.


def run_demo(device, host, port, amplitudes, phases, settle_seconds,
             *, server_factory=None, sleep=time.sleep):
    device, host, port = connection.validate_config(device, host, port)
    validate_settings(amplitudes, phases, settle_seconds)
    if server_factory is None:
        import zhinst.core

        server_factory = zhinst.core.ziDAQServer

    daq = server_factory(host, port, connection.API_LEVEL, allow_version_mismatch=True)
    writes_started = False
    try:
        connection.ensure_device_connected(daq, device)
        if daq.getString(f"/{device}/features/devtype").strip().upper() != "MFLI":
            raise ValueError("This demo requires an MFLI.")
        root = f"/{device}"
        # Check all four channels before any write. Missing nodes also fail here.
        for index in range(4):
            daq.getDouble(f"{root}/sigouts/0/amplitudes/{index}")
            daq.getDouble(f"{root}/demods/{index}/phaseshift")
            rate = daq.getDouble(f"{root}/demods/{index}/rate")
            if not daq.getInt(f"{root}/demods/{index}/enable") or not math.isfinite(rate) or rate <= 0:
                raise ValueError(f"Enable demodulator {index + 1} with a positive rate in LabOne first.")
        output_range = daq.getDouble(f"{root}/sigouts/0/range")
        offset = daq.getDouble(f"{root}/sigouts/0/offset")
        if not math.isfinite(output_range) or output_range <= 0 or not math.isfinite(offset):
            raise ValueError("Invalid output range or offset readback.")
        if sum(abs(value) for value in amplitudes) + abs(offset) > output_range:
            raise ValueError("Combined peak amplitudes plus DC offset exceed the current output range. "
                             "Reduce AMPLITUDES_VPK or review the range in LabOne.")

        applied = []
        for index, (amplitude, phase) in enumerate(zip(amplitudes, phases)):
            writes_started = True
            actual_amp = daq.syncSetDouble(f"{root}/sigouts/0/amplitudes/{index}", amplitude)
            actual_phase = daq.syncSetDouble(f"{root}/demods/{index}/phaseshift", phase)
            if not math.isfinite(actual_amp) or not math.isfinite(actual_phase):
                raise ValueError(f"Invalid write acknowledgement for tone {index + 1}.")
            applied.append((actual_amp, actual_phase))
            print(f"Tone {index + 1}: requested {amplitude:g} Vpk / {phase:g} deg; "
                  f"acknowledged {actual_amp:g} Vpk / {actual_phase:g} deg")

        paths = [f"{root}/demods/{index}/sample" for index in range(4)]
        # A later timestamp than these post-write baselines rules out stale readback.
        baseline = [sample_timestamp(daq.getSample(path)) for path in paths]
        sleep(settle_seconds)
        rows = []
        for index, path in enumerate(paths):
            sample = daq.getSample(path)
            if sample_timestamp(sample) <= baseline[index]:
                raise ValueError(f"No fresh sample from demodulator {index + 1}. "
                                 "Check its rate/trigger or increase SETTLE_SECONDS.")
            x = sample_value(sample, "x")
            y = sample_value(sample, "y")
            rows.append({
                "channel": index + 1,
                "frequency_hz": sample_value(sample, "frequency"),
                "amplitude_vpk": applied[index][0],
                "phase_deg": applied[index][1],
                "x": x, "y": y, "r": math.hypot(x, y),
                "theta_deg": math.degrees(math.atan2(y, x)) if x or y else math.nan,
            })
    except BaseException:
        if writes_started:
            print("Some amplitude/phase writes may remain applied; review them in LabOne.", file=sys.stderr)
        raise
    finally:
        pending_error = sys.exception()
        try:
            daq.disconnect()
        except Exception as cleanup_error:
            if pending_error is None:
                raise
            print(f"Cleanup also failed: {cleanup_error}", file=sys.stderr)
    return rows


def main():
    try:
        rows = run_demo(DEVICE_ID, SERVER_HOST, SERVER_PORT,
                        AMPLITUDES_VPK, PHASES_DEG, SETTLE_SECONDS)
    except KeyboardInterrupt:
        print("Write/read demo interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print("\nDemod   Frequency (Hz)             X             Y             R   Theta (deg)")
    for row in rows:
        print(f"{row['channel']:5d} {row['frequency_hz']:16.7g} "
              f"{row['x']:13.6g} {row['y']:13.6g} {row['r']:13.6g} {row['theta_deg']:13.6g}")
    print("X/Y/R use the selected input's native units; theta is undefined (nan) at X=Y=0.")
    print("SUCCESS: four amplitude/phase pairs written and four demodulators read; client closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
