# Zurich Instruments MFLI

Maintained driver ID: **`mfli`**. The user has reported successful standalone
hardware operation. Integrated ZMeter scans still need the user-executed bench
acceptance below. Automated validation uses injected fake APIs only.

## Configuration and launch

The maintained implementation uses three layers: `MFLI_hardware.py` owns address
validation, connection/interface handling, and instrument I/O; `MFLI_logic.py`
owns worker and scan coordination; `MFLI_main.py` owns the panel and standalone
entry point. There is no separate connection module. Hardware-layer imports
remain free of instrument access and defer the Zurich API import until connecting.

The existing workbook address cell contains plain text, with no Python evaluation:

| Address | Connection |
| --- | --- |
| `DEV30037, 192.168.141.54` | Explicit serial and IP, port 8004 |
| `DEV30037` | Host `mf-dev30037`, port 8004 |

Whitespace and serial case are ignored. An explicit second value must be a valid
IP address. Brackets, URLs, extra fields, and missing serials are rejected
before I/O. Invalid addresses appear in the MFLI panel log without blocking other
devices. The panel's existing serial/host/port fields remain editable.

`device_config.xlsx` includes `mfli_0`, enabled with manual connection
(`connect_on_start=FALSE`). Blank scan filters expose all 25 channels. The registry
also supports optional asynchronous startup connection. Driver imports are lazy;
Zurich Core is imported only when connecting. Runtime addition/removal is disabled.

Use the existing `zmeter-v1.0-beta.1` environment, from the repository root:

```powershell
python -B start_zmeter.py
```

Open **mfli_0** and click **Connect**. Connection reads settings without applying
defaults. To launch only the maintained device window:

```powershell
python -B devices/mfli/MFLI_main.py
```

This standalone entry starts with blank serial/host fields and connects only on
an explicit button press. Closing the standalone window performs cleanup; closing a managed
device panel hides it and retains its connection, plots, and log.

### Dependencies and LabOne prerequisites

`zhinst-core==26.7.1.4` is pinned in `zmeter_Sept2026_environment.yml` and the local
requirements file. Toolkit and Utils are unnecessary. No packages were installed
during integration. Tested installed versions: Python 3.12.12, PyQt6 6.9.1,
pyqtgraph 0.13.7, NumPy 2.4.1, Core 26.7.1.4.

USB requires the Windows LabOne RNDIS virtual Ethernet driver and a reachable
instrument Data Server. API level 6 and port 8004 are used. Attachment reuses an
existing device connection or chooses the server-reported interface (typically
PCIe for the embedded server). The API interface is not the PC's USB cable type.
Version mismatch is allowed as requested; client/server versions are logged.

LabOne owns oscillator frequencies/assignments, input routing, output enables,
output range/load, filters, triggers, and streaming. Configure all four tone
nodes (MF-MD), and enable demodulator streaming at a positive rate in continuous
mode for channels being read. The rate is instrument samples per second, separate
from the UI refresh interval. No acquisition setup is written by this driver.

## Scan channels

Exactly nine setters and sixteen getters are discovered from explicit methods.
Setters take one value and return an acknowledged scalar; getters take no arguments
and return numeric scalars. The instance prefix defaults to `mfli_0_`.

| Channels, x = 1–4 | Node or calculation | Units |
| --- | --- | --- |
| `OSC{x}_amplitude` | `sigouts/0/amplitudes/x-1` | Signed V peak |
| `OSC{x}_phase` | `demods/x-1/phaseshift` | Degrees, -180 to +180 |
| `output_DCoffset` | `sigouts/0/offset` | V |
| `DEMOD{x}_X`, `DEMOD{x}_Y` | `demods/x-1/sample` | Selected input units |
| `DEMOD{x}_R` | `hypot(X, Y)` from one sample | Selected input units |
| `DEMOD{x}_theta` | `degrees(atan2(Y, X))`; NaN at zero magnitude | Degrees |

OSC rows represent fixed tone/demodulator pairs, all contributing to the same
physical Signal Output. Actual oscillator assignment/frequency is displayed.
Phase writes affect both the generated tone and its demodulation reference.
Amplitude/DC writes re-read all four amplitudes, offset, and range and require
`sum(abs(amplitudes)) + abs(offset) <= range`, including disabled tones. Existing
ZMeter global scan limits are also enforced. No write is automatically retried.

All four amplitude setters and the DC offset setter **always ramp**, including
panel Set buttons, standalone use, routed commands, and scans. The hardcoded
settings in `MFLI_hardware.py` are **10 V/s** and **100 updates/s**: steps are at
most 0.1 V, with a 10 ms cancellable wait before each step. The starting value is
read from the instrument; the final step lands on the requested target and returns
its acknowledged value. An unchanged target requires no write. There is no
separate direct-set channel or ramp setting. Phase setters remain direct.

The final target is checked before starting and the current combined output
range is checked before every intermediate write. Cancellation stops further
steps and raises an error, leaving the last applied value in place; **Refresh
settings** shows it after interruption. A failed step is not retried. API and
range-read overhead can make the ramp slower than the nominal rate; it never
speeds up to catch up. Native calls must finish before cancellation can take
effect. Monitoring shares the worker and pauses its updates during each ramp.

Each scalar getter waits for a newer timestamp than its own baseline. Separate
quantities can have different timestamps; there is no averaging or shared scan
sample cache. The default freshness timeout is 5 seconds, editable through
`READ_TIMEOUT_SECONDS` in the maintained `MFLI_main.py`, or `MFLIHardware(read_timeout=...)`.
Filter settling remains the scan author's responsibility. Storage uses existing
ZMeter measurement channels and formats without schema changes.

## Monitoring and lifecycle

The panel retains four selectable plots, 600 points per plot, a 100 ms initial
refresh interval, and a 500-entry log. Monitoring reads each demodulator once per
update, derives all quantities from that sample, and skips repeated timestamps.
Disabled/invalid/stale channels are reported separately; healthy channels continue.

One worker owns all API calls. Panel requests are asynchronous. Synchronous scan
methods run outside the GUI thread. MFLI opts into background command routing;
routed manual requests use the panel gate, while scans use the scan gate.

- Manager `stop_scan()` is called **before** scanning. It immediately gates panel
  jobs, cancels queued work, and inserts a worker barrier before subsequent scan
  calls. An active native call finishes first. Monitoring stops.
- Manager `start_scan()` is called **after** scanning. It releases the gate and
  resumes monitoring only if previously requested and still connected.
- `force_stop()` cancels queued jobs and cooperative sample waits. It never resets
  or zeros outputs. Transport failure stops monitoring and requires reconnection.
- Manager connect/disconnect/termination waits have a 10-second budget. State
  probes read locked worker state, without waiting for GUI signals. Timed-out
  connections are discarded and their eventual client is closed.
- Shutdown cancels pending work and closes only this API client. Applied settings
  remain in the instrument. Cleanup errors propagate to the manager, and unfinished
  clients/workers are retained. Native API calls cannot be interrupted by the
  Python budget; cleanup may finish later. No running worker is force-killed.

Passive monitor reads do not count as a manager busy veto: shutdown may cancel
and drain them. Active control operations still report busy.

The existing manager may refuse shutdown while a routed request or device call
is active; finish/abort the operation and retry. Other LabOne clients can alter
settings between calls, so coordinate simultaneous use.

## Validation history

Before release cleanup, the development branch passed 24 fake/offscreen ramp and
integration tests and 60 device/demo regressions. The development demos, tests,
and detailed notes are retained on `MFLI_dev2.0` and excluded from this release
branch. This cleanup does not alter the hardware, logic, or main implementation.
Integrated hardware and ramp timing acceptance remain user-executed below.

## User-executed hardware acceptance

1. Review enabled workbook rows and output values; launch ZMeter using the command
   above. Open `mfli_0`, connect manually, and compare settings with LabOne.
2. Start monitoring. Run a small reviewed amplitude/phase/DC scan, selecting the
   desired demodulator getters and suitable settling delay/global limits.
3. Confirm monitoring pauses and panel writes/connection changes are disabled
   during the scan, then resumes only when it was previously running.
4. Exercise abort, pause, panel hide/reopen, and disconnect/reconnect. Check failure
   messages for a disabled demodulator, then restore its LabOne setup.
5. Close ZMeter while monitoring. Confirm client cleanup and that output settings
   remain applied. Integrated hardware acceptance is pending this user test.

**User-executed ramp acceptance:** review safe targets and output range in LabOne,
then exercise DC offset and all four amplitudes upward and downward using the
panel and a small scan. Confirm intermediate steps and final readbacks, abort an
active ramp and refresh its last applied value, and verify phase remains direct.
Use suitable acquisition or external measurement to assess actual ramp timing;
the 100 ms plot refresh cannot resolve every 10 ms step. This ramp change has
only fake/offscreen validation so far.
