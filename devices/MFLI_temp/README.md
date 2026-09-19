# MFLI development demos and compatibility launcher

The maintained hardware, logic, and UI now live in [devices/mfli](../mfli/README.md).
This folder retains the original demos, offline tests, notes, and scratch files.
`MFLI_main.py` is a thin launcher using the existing demo defaults.
The user reported successful standalone hardware operation; integrated ZMeter
scan acceptance is still pending.

## Standalone device UI

Run **`MFLI_main.py`** directly in `zmeter-v1.0-beta.1`. Opening the window does
not discover or connect to instruments. Click Connect explicitly. This direct launch opens only the device window. The same implementation is
also registered with ZMeter as `mfli`; see the maintained package README.

**User-executed hardware test — launch:**

```powershell
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -B 'C:\Users\Taylo\Documents\ChatGPT\zmeter\zmeter-release-beta-phase1\devices\MFLI_temp\MFLI_main.py'
```

The connection fields initially reuse `DEVICE_ID`, `SERVER_HOST`, and
`SERVER_PORT` from the existing connection demo (currently DEV30037,
192.168.141.54, 8004). Edit the fields before connecting if necessary. Blank host
uses `mf-<serial>`. Core 26.7.1.4, PyQt6 6.9.1, pyqtgraph 0.13.7, and NumPy 2.4.1
are already present in the selected environment; this update installs nothing.
The requirements file intentionally pins only the additional Zurich dependency.

### Operator workflow

1. Configure the four channels in LabOne: oscillator assignments/frequencies,
   input sources, filters, **Enable Streaming**, positive **Rate (Sa/s)**, and
   **Continuous** trigger. Configure output range, load, and tone/output enables
   for the experiment. The UI does not write any of those settings.
2. Connect and compare amplitude, phase, offset, oscillator assignments, and
   actual frequencies with LabOne. All four tone nodes must be available
   (MF-MD option). Disabled demodulators do not prevent connection or writes.
3. Edit amplitude/phase in any OSC row, then click that value's **Set** button.
   Edit DC offset and click **Set DC**. Readback fields show acknowledged values;
   typing and **Refresh settings** never write. Refresh replaces editor contents
   with the current instrument values, including changes made in LabOne.
4. Click **Start graphs**. Each plot independently selects demodulator 1–4 and
   X/Y/R/theta. Defaults are demodulator 1's four quantities. **Pause** stops GUI
   monitoring, not LabOne streaming. **Clear graphs** clears history and restarts
   elapsed time. Each plot keeps 600 points; changing its selection clears only
   that plot. The default GUI refresh interval is 100 ms, independent of the
   instrument sample rate.
5. Disconnect/reconnect to test client lifecycle. Close while monitoring and
   confirm the window finishes cleanup. Applied output settings remain applied.

### Channel meanings and units

| Logic methods (`x` is 1, 2, 3, or 4) | Meaning |
| --- | --- |
| `set_OSC{x}_amplitude(value)` | Signed peak volts at `sigouts/0/amplitudes/x-1`; returns acknowledged value |
| `set_OSC{x}_phase(value)` | Degrees, -180 through +180, at `demods/x-1/phaseshift`; returns acknowledged value |
| `set_output_DCoffset(value)` | Volts at `sigouts/0/offset`; returns acknowledged value |
| `get_DEMOD{x}_X()` / `get_DEMOD{x}_Y()` | Fresh scalar demodulator components |
| `get_DEMOD{x}_R()` / `get_DEMOD{x}_theta()` | Magnitude and angle calculated from one fresh X/Y sample |

These are exactly nine setters and sixteen getters with future ZMeter-compatible
signatures. They are registered as driver `mfli` in ZMeter. OSC1–OSC4 name **tone rows** tied to
demodulators 1–4; they do not force oscillator assignments. All tones contribute
to the same Signal Output. The read-only assignment/frequency fields identify
the current mapping. X/Y/R use V for voltage input, A for current input, or
explicitly labelled native units for other sources. Theta uses degrees and is
undefined (`nan`) at zero magnitude. No phase unwrapping is applied.

`R = hypot(X, Y)` and `theta = degrees(atan2(Y, X))`; the sample's reference
`phase` field is not the measured theta. Phase changes shift both the tone and
its demodulator reference, so a same-channel loopback can retain the same theta.
[MFLI phase and output documentation](https://docs.zhinst.com/mfli_user_manual/functional_description/lock_in_mf.html)

Amplitude and DC writes re-read all four amplitudes, offset, and output range.
The conservative sum of absolute peaks (including disabled tones) plus absolute
offset must fit the current range. The maintained UI and scan channels always
ramp amplitude/DC targets at a hardcoded 10 V/s and 100 updates/s; see the
[maintained ramp contract](../mfli/README.md). Phase writes remain direct.
The UI does not auto-range, enable outputs, or restore settings.
Another LabOne client can still change settings
between API calls; coordinate edits between clients. A failed write can already
have applied and is never automatically retried.

### Acquisition and lifecycle

- Monitoring reads each demodulator once per update, derives its four quantities
  together, and skips duplicate timestamps. Reads across demodulators are
  sequential and are not guaranteed simultaneous. This is a latest-value display,
  not an acquisition recorder; intermediate instrument samples may be skipped.
- Disabled streaming, invalid rate, and non-continuous trigger produce separate
  channel messages. Other demodulators continue plotting. Stale data is reported
  after `max(READ_TIMEOUT_SECONDS, 3 / rate)` seconds without a new timestamp.
  Error messages are deduplicated, and fresh-data recovery is logged.
- Each synchronous getter requests a sample newer than its own post-request
  baseline. Separate scalar getters can therefore return different timestamps.
  Set `READ_TIMEOUT_SECONDS` in `devices/mfli/MFLI_main.py` (default 5 s) for very slow rates.
  Programmatic callers can pass `read_timeout` to `MFLIHardware`.
  Freshness does not guarantee filter settling; callers choose settling delays.
- One worker owns the client and serializes every API call. UI jobs use
  `logic.request(...)` and completion signals. Synchronous scan methods reject
  GUI-thread use; call them from an external worker. The standalone launch does not run the ZMeter scan engine.
- Disconnect/close cancels pending jobs, signals a waiting fresh read to stop,
  lets the active API call finish, and closes only this client. No global
  `disconnectDevice`, reset, or output-disable command is sent.
- Native API calls use the vendor's timeouts. The freshness timeout does not
  interrupt a blocked native call, and cleanup waits responsively for it. Failed
  cleanup leaves the window open for retry; the worker is never force-killed.
  Transport errors stop monitoring and require an explicit reconnect.
- The resizable log is in memory only, limited to 500 entries. Routine samples
  and successful writes update dedicated readbacks instead of filling the log.

**User-executed hardware acceptance:** compare all settings against LabOne;
apply reviewed low amplitude/phase/DC values and compare acknowledged readbacks;
exercise the 16 demodulator/quantity selections, pause/resume, and refresh;
disable one demodulator in LabOne and verify other plots continue; re-enable it
and observe recovery; disconnect/reconnect; close while monitoring. Inspect
the final settings in LabOne. Real-instrument validation remains user-performed.

## Original connection demo

`connection_demo.py` is a directly runnable connection check for a
Zurich Instruments MFLI. It reads identity, software versions, installed options,
and the internal clock frequency. It does not configure outputs, inputs,
demodulators, or acquisition. It is not registered with ZMeter.

## Four-tone write/read demo

Run **`write_read_demo.py`** directly for the second demo. Its scope is connection,
four sine-tone amplitude/phase writes, and X/Y/R/theta readout at the four current
demodulator frequencies. It reuses the connection settings and interface logic
from `connection_demo.py`, including the version-mismatch bypass. No additional
packages are needed.

Editable settings at the top of the new file:

```python
AMPLITUDES_VPK = [0.001, 0.001, 0.001, 0.001]
PHASES_DEG = [0.0, 45.0, 90.0, 135.0]
SETTLE_SECONDS = 1.0
```

List positions correspond to LabOne channels 1-4 (API indices 0-3). These four
tones share Signal Output 1. Amplitudes use **peak volts** at the API; phase uses
degrees. The MFLI needs the MF-MD option for all four channels.

**User-executed hardware test:** first configure the four frequencies/oscillator
assignments, input sources, enabled demodulators with positive sample rates, and
desired output/tone enables in LabOne. The demo leaves that setup unchanged.
Adjust the two lists above, then run:

```powershell
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -B 'C:\Users\Taylo\Documents\ChatGPT\zmeter\zmeter-release-beta-phase1\devices\MFLI_temp\write_read_demo.py'
```

The only written nodes are `sigouts/0/amplitudes/0..3` and
`demods/0..3/phaseshift`. Their acknowledged values are printed. **The written
settings remain applied**, including any completed writes before an error; this
is not an automatic restore test. Frequencies, ranges, output enables, input
settings, and demodulator enables/rates are not written. Requested amplitudes
plus DC offset must fit the current range before any write occurs.

The result table reports the actual frequency, X, Y, `R = hypot(X, Y)`, and
`theta = degrees(atan2(Y, X))` for each channel. X/Y/R use the selected input's
native units (volts for voltage input, amperes for current input). Theta is
undefined and printed as `nan` at zero magnitude. Samples are sequential, not
guaranteed simultaneous. Timestamp checks reject stale data; increase
`SETTLE_SECONDS` for slow sample rates or long filters. This delay is a user-chosen
settling interval, not an automatic determination of steady state.

On MFLI the channel phase shift affects both its generated tone and its
demodulation reference. Changing it may leave measured theta unchanged in a
same-channel loopback. The measured angle is calculated from X/Y, not copied from
the sample's reference `phase` field.
[Zurich's phase description](https://docs.zhinst.com/mfli_user_manual/functional_description/lock_in_mf.html)

Offline validation for this demo uses the test-discovery command below plus
`python -B -m py_compile devices/MFLI_temp/write_read_demo.py devices/MFLI_temp/tests/test_write_read_demo.py`
with the selected environment's Python. No hardware run has been performed by
the agent.

## Environment

The requested environment is `zmeter-v1.0-beta.1` (64-bit Python 3.12).
Only `zhinst-core==26.7.1.4` is added; its NumPy and typing-extensions dependencies
are already installed. The user-reported instrument server is LabOne 26.4.1;
the installed client reports 26.7.1. The demo allows this release mismatch.
Neither Toolkit nor Utils is required.

From the repository root, installation can be reproduced in PowerShell with:

```powershell
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -m pip install -r devices/MFLI_temp/requirements.txt
```

Choose that same Python executable as your IDE interpreter. Do not rely on the
system `python`, which may point to a different environment.

## USB setup

1. Connect the MFLI's device USB connection to the Windows PC and allow it to boot.
2. Ensure its USB RNDIS driver is installed. The instrument's `MF-DRIVER` drive
   provides `MF-Device-Finder64.msi` for 64-bit Windows; the manual's section
   2.4.2 describes installation. Driver installation, if needed, is a separate
   user-performed Windows setup step, not a Python package installation.
3. Use MF Device Finder or the instrument's LabOne browser interface to identify
   its actual `dev...` serial, hostname/IP, and Data Server version.
4. Note the Data Server version for troubleshooting. The demo passes
   `allow_version_mismatch=True`, so a different server release does not prevent
   the connection solely because of its version. API/read errors still surface.

MFLI USB is a virtual Ethernet connection between the PC and the instrument.
The API's device interface describes the separate link between the Data Server
and measurement hardware: it is `PCIe` when the server runs inside the MFLI,
even with USB or Ethernet from the PC. The demo reads `/zi/devices/connected`
and reuses an existing attachment. Otherwise it selects the interface reported
by `/zi/devices`, using the active interface or an advertised available interface.
It does not assume an interface from the cable type or attempt successive guesses.
See the manual's [Available Devices section](https://docs.zhinst.com/mfli_user_manual/getting_started/labone_software_startup.html#available-devices).

By default it contacts the embedded Data Server at `mf-<device serial>:8004`. The browser interface's
HTTP port is not the API port. A separate Data Server on the PC is not needed
for this embedded-server workflow. Use `--host` to supply the instrument's
actual IP if hostname resolution fails.

## User-executed hardware test

The repository's `AGENTS.md` reserves all real-hardware discovery, connection,
and testing for the user. The commands below are for manual execution.

### Run directly in your IDE

Open `connection_demo.py`, set `DEVICE_ID` to your actual serial, select the
interpreter above, and run the file. Leave `SERVER_HOST` blank to use the default
instrument hostname, or set it to the instrument's IP. No ZMeter launcher is used.

### Run directly in PowerShell

Replace `dev12345` with your actual serial. This absolute-path command works
independently of your current directory:

```powershell
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -B 'C:\Users\Taylo\Documents\ChatGPT\zmeter\zmeter-release-beta-phase1\devices\MFLI_temp\connection_demo.py' --device dev12345
```

Optional IP override (replace this example IP too):

```powershell
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -B 'C:\Users\Taylo\Documents\ChatGPT\zmeter\zmeter-release-beta-phase1\devices\MFLI_temp\connection_demo.py' --device dev12345 --host 169.254.1.2 --port 8004
```

Expected output includes:

- The requested serial, server address, port, and API level.
- Device type `MFLI`, its serial and installed options (possibly none).
- Python API and Data Server versions, with the server revision.
- Clock frequency, normally `60000000 Hz (60 MHz)` for the MFLI.
- `SUCCESS: MFLI identity and clock read; client connection closed.`

Output values above are illustrative, not a recorded bench result. Verify them
against your instrument. Repeat the command once to check that a new client can
connect after the previous run finishes. Record the results in
`DEVELOPMENT_NOTES.md`.

Exit codes: `0` for success, `1` for configuration/API/read/cleanup failure,
`2` for invalid command-line syntax, and `130` for a handled keyboard interrupt.
No success message is printed until reads and client cleanup finish.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Missing Python dependency | Use the selected environment's executable and install this folder's requirements. |
| Missing or invalid serial | Set `DEVICE_ID` or use `--device dev...`; do not leave the example serial in place. |
| Host cannot be resolved | Check USB RNDIS/Device Finder and try the actual instrument IP with `--host`. |
| Server connection refused/unavailable | Check the instrument is ready, the address is correct, and port 8004 is reachable under your network/firewall policy. |
| Version-mismatch rejection | Ensure you are running this updated script, which passes `allow_version_mismatch=True`. |
| Interface unavailable | Run the updated script, which reuses an existing attachment or selects the server-reported interface. Embedded MFLI servers use PCIe, regardless of the PC cable. |
| Wrong instrument type | Verify the serial and server address; this demo accepts MFLI only. |
| Read or cleanup failure | Keep the full error text and verify the USB connection and LabOne session. The script preserves the original failure if cleanup also fails. |

The Core API controls blocking connection/read timeouts; the demo does not add
automatic retries or a separate hard deadline. Ctrl+C handling depends on when
the vendor call returns control to Python.

Cleanup calls `disconnect()` on this client only. It never calls
`disconnectDevice()`, which would disconnect the device from the shared server.
The demo performs no broad device discovery, measurement-setting writes, or
subscriptions. It reads the chosen server's device metadata without creating a
discovery object or scanning other servers. Connecting may attach the device to the Data Server; no automatic
device detachment is performed afterward.

## Hardware-independent checks

From the repository root:

```powershell
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -B -m unittest discover -s devices/MFLI_temp/tests -p 'test_*.py' -v
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -B -m py_compile devices/MFLI_temp/connection_demo.py devices/MFLI_temp/tests/test_connection_demo.py
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -B -m py_compile devices/mfli/MFLI_hardware.py devices/mfli/MFLI_logic.py devices/MFLI_temp/MFLI_main.py devices/MFLI_temp/tests/test_mfli_layers.py
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -B devices/MFLI_temp/connection_demo.py --help
& 'C:\Users\Taylo\anaconda3\envs\zmeter-v1.0-beta.1\python.exe' -B -m pip check
```

Tests inject a fake server and reject any attempt to import the real vendor API.
Importing the demo, requesting `--help`, or supplying an empty serial
does not load the vendor API or contact hardware. Generated development files
belong in `.scratch/`, `.cache/`, or this folder's ignored `__pycache__/` folders.

See `DEVELOPMENT_NOTES.md` for the evidence, implementation decisions, and
remaining bench validation.
