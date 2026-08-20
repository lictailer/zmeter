# Phase 1 Device Registration Review

## Outcome and policy

Phase 1 of [DEVICE_REGISTRATION_ROADMAP.md](DEVICE_REGISTRATION_ROADMAP.md) is
implemented. The reviewed registry now recognizes the NI, maintained VISA, and
Thorlabs driver IDs below. The checked default profile remains mock-only; no
real address, serial, or device name is checked in, and no physical instrument
has been tested by a coding agent.

Every real driver remains startup-only with `runtime_mutation_allowed=False`.
For first commissioning use `connect_on_start=false` and enable exactly one real
device in an ignored `*.local.json` profile. Connect from its device panel when
the retained widget exposes that control. PEM100 and SP150 do not expose a
connection control in their retained widgets: inspect their disconnected panels
first, then use a separate reviewed run with `connect_on_start=true` to connect
to the exact profile address. Runtime add, manager disconnect, and removal
remain mock-only.

The compatibility decision is intentionally narrow: normal-condition widget,
logic, hardware, commands, ranges, timing, monitor, and discovery behavior are
preserved. The known special-condition gaps below remain visible future work.
They must not be interpreted as hardware validation.

## Registry and configuration matrix

| Driver ID | Widget import | Runtime | Required connection fields | Startup auto-connect |
| --- | --- | --- | --- | --- |
| `ni6423` | `devices.ni6423.ni6423_main.NI6423` | NI-DAQmx | `device_name: str` | No; use the panel |
| `nidaq` | `devices.nidaq.nidaq_main.NIDAQ` | legacy PyDAQmx | `device_name: str` | No; use the panel |
| `pem100` | `devices.pem100.pem100_main.PEM100` | shared VISA | `address: str`; optional `timeout_ms: int` | Supported, but false for commissioning |
| `sp150` | `devices.sp150.sp150_main.SP150` | shared VISA | `address: str`; optional `timeout_ms: int`, `query_delay_s: int/float` | Supported, but false for commissioning |
| `hp34401a` | `devices.hp34401a.hp34401a_main.HP34401A` | shared VISA | `address: str` | Supported, but false for commissioning |
| `keithley24xx` | `devices.keithley24xx.keithley24xx_main.Keithley24xx` | shared VISA | `address: str` | No; use the panel |
| `sr860` | `devices.sr860.sr860_main.SR860` | shared VISA | `address: str` | Supported, but false for commissioning |
| `sr830` | `devices.sr830.sr830_main.SR830` | shared VISA | `address: str` | Supported, but false for commissioning |
| `demo_device` | `devices.demoDevice.demoDevice_main.DemoDevice` | private dummy VISA | `address: str` | Supported; simulator only |
| `bbd30x` | `devices.BBD30X.BBD30X_main.BBD30X` | shared Kinesis | `serial: str` | No; use the panel |
| `k10cr1` | `devices.k10cr1.k10cr1_main.K10CR1` | shared Kinesis | `serial: str` | No; use the panel |

The factory for every entry is lazy. Merely loading or validating a profile
does not import a device package, create a VISA manager, import NI libraries,
import CLR/pythonnet, validate Kinesis files, enumerate devices, or connect.
An enabled legacy VISA widget still schedules its established deferred VISA
resource discovery for the next Qt event-loop turn. That approved behavior is
unchanged.

The `demo_device` registration deliberately does not receive the application's
shared real VISA runtime. It keeps its private `DummyResourceManager`, so this
template cannot accidentally become a real VISA driver.

## Scan interfaces retained

| Driver | Set channels | Get channels / notes |
| --- | --- | --- |
| `ni6423` | `AO0`–`AO3` | `AI0`–`AI31`, feedback `AO0`–`AO3`, `counter0` |
| `nidaq` | `AO0`, `AO1` | `AI0`–`AI6`, `sample_count` |
| `pem100` | `wavelength`, `retardance` | same two channels |
| `sp150` | `wavelength` | `wavelength` |
| `hp34401a` | none | `idn`, `dc_voltage`, `all`; filter nonnumeric/control getters |
| `keithley24xx` | `direct_source_voltage`, `ramp_source_voltage`, `source_current` | `voltage`, `current` |
| `sr860` | `amplitude` | measurement, configuration, status, auxiliary, and `all` getters; use an explicit measurement filter |
| `sr830` | none | X/Y/R/Theta, auxiliary, configuration/status, and `all` getters; use an explicit measurement filter |
| `demo_device` | none | template getters include text/control values; not a numeric production scan driver |
| `bbd30x` | `pos_mm`, `pos_um`, `delay_ps` | same three channels |
| `k10cr1` | `angle` | `angle` |

Profile channel allowlists retain the established behavior: syntactically valid
unknown names are silently skipped. Registration does not tighten that policy.

## Official SR830 consolidation

The maintained former `sr830_v2` implementation is now the only official SR830:

- stable registry ID: `sr830`;
- package: `devices/sr830`;
- widget: `devices.sr830.sr830_main.SR830`;
- shared `VisaRuntime` ownership and deferred discovery retained;
- legacy direct-PyVISA implementation removed;
- no `sr830_v2` registry ID or executable package remains.

Local profiles and imports must use `sr830`, not `sr830_v2`.

## Confirmed limitations and future improvements

### NI DAQ

- `ni6423` and `nidaq` are separate drivers, not aliases or interchangeable
  hardware descriptions.
- NI6423 still assumes AO0–AO3, AI0–AI31, feedback AI28–AI31, Ctr0/Ctr1/Ctr3,
  a 100 MHz timebase, and PFI8/PFI12 routing. Verify every route in NI MAX.
- Legacy `nidaq` remains on PyDAQmx with its original two-AO/task behavior.
- Neither NI driver has a complete reviewed busy/force-stop/partial-task cleanup
  contract. Future work is migration of legacy `nidaq` to `nidaqmx`, explicit
  routing configuration, bounded rollback, and a complete fake NI backend.

### VISA

- Deferred VISA enumeration remains distinct from connection, but discovery and
  monitor workers are not yet complete runtime-removal busy probes.
- HP34401A, Keithley24xx, SR860, and SR830 preserve legacy lifecycle details;
  timeout, malformed-response, partial-connect, and failed-close paths need
  stronger fake fault coverage. HP34401A currently logs cleanup failures rather
  than proving the resource close, so the final physical/session state must be
  checked after any error.
- Keithley24xx manager teardown uses its existing two-second ramp stop window and
  direct shared-lease close, while normal panel connection remains asynchronous.
- SR860 and SR830 expose configuration/status helpers through scan discovery;
  local profiles should allow only intended numeric measurement getters.
- Future work is standardized bounded connect/disconnect/terminate behavior,
  explicit connection-state reporting, fault matrices, and model-specific
  command/unit/limit documentation.

### Thorlabs

- BBD30X retains the DDS220 fallback, 0–220 mm software range, connection-time
  velocity/acceleration writes, blocking home behavior, and controlled Kinesis
  stop behavior documented in its README.
- K10CR1 retains its empty widget `force_stop`, blocking motion/home operations,
  modulo-one-turn completion, and absence of software angular limits.
- Neither driver is eligible for runtime removal. Future work is a real bounded
  K10CR1 stop, last-confirmed-position reporting after interruption, complete
  device-owned busy probes, and fake timeout/partial-connect/shutdown coverage.

## Local profile example: NI6423

Use an ignored profile, preserve the rest of your local `paths` and devices,
and add an entry like this:

```json
{
  "id": "ni6423_1",
  "driver": "ni6423",
  "enabled": true,
  "connect_on_start": false,
  "connection": {
    "device_name": "Dev1"
  },
  "scan_channels": {
    "set": null,
    "get": null
  }
}
```

For `nidaq`, use driver `nidaq` with the same `device_name` key. The key is not
`address`. For these manual-connect registrations, enter the same reviewed NI
MAX name in the device panel before connecting.

## Commissioning sequence

Use [hardware_safety.md](hardware_safety.md) and the target device README. For
each driver:

1. record the exact Git commit, ignored profile hash, interpreter/environment,
   vendor runtime/driver, model/firmware, connection identifier, limits, wiring,
   and initial physical state;
2. enable exactly one real driver with `connect_on_start=false`;
3. launch ZMeter and confirm unrelated NI/VISA/Kinesis stacks stay dormant;
4. connect from the panel to the exact reviewed resource; for PEM100 and SP150,
   close the disconnected inspection run and explicitly change only
   `connect_on_start` to `true` for a reviewed connection run;
5. perform one read-only status/readback check;
6. perform only the smallest independently approved operation inside both the
   device and experiment limits;
7. exercise only the stop behavior already documented as safe for that exact
   device; mark incomplete force-stop checks pending rather than improvising;
8. disconnect or close the full application, then independently verify the
   final physical state and released session/task/handle;
9. return logs, observations, pass/fail, and limitations for that exact setup.

Do not enable runtime mutation for these drivers during commissioning.
