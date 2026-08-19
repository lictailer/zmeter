# ANC300 Source

## Status

This directory contains a single vendored pyLabLib-derived ANC300 controller source file. It is not currently a ZMeter device package: there is no package initializer, widget, scan-facing logic layer, UI, or startup registration, and `ANC300_pyLabLib` has no `.py` extension. Its relative imports expect the surrounding pyLabLib package and do not resolve from this directory alone.

Treat it as implementation reference only. Do not add a registry entry or select it in a profile without first building a normal three-layer integration and validating the dependency and licensing decisions.

## Represented hardware

The source targets an Attocube ANC300 multi-axis controller over a pyLabLib communication backend. It includes controller/axis identity, mode, voltage, offset, frequency, capacitance, trigger, jog, step, wait, and stop operations. Construction opens the transport and probes available axes, so importing or instantiating a completed integration could affect hardware.

## Dependencies and configuration

- pyLabLib package internals matching the copied source's relative imports;
- NumPy;
- a serial or Ethernet controller address and controller password;
- axis/module-specific voltage, frequency, mode, correction, and motion limits.

No lab-safe limits or ZMeter channel mapping are defined here. Keep the address, password, axes, units, and limits in lab configuration rather than shared core code.

## ZMeter contract and safety

There are no scan-visible ZMeter channels or lifecycle methods in the current tree. A future integration must separate transport from logic and UI, validate every motion/output command, provide bounded stop and cleanup behavior, and document which controller/module combinations are supported.

Agents must not run this source or any ANC300 discovery, connection, axis probe, motion, voltage, frequency, mode, or stop command. See [device_contract.md](../../documents/device_contract.md) and [hardware_safety.md](../../documents/hardware_safety.md).

## Validation

There is no standalone ZMeter test command or sanctioned bench checklist for this incomplete integration. Static parsing can target the extensionless file explicitly, but it does not resolve the missing pyLabLib package context. Build the package/transport boundary, limits, lifecycle, simulator, and tests before proposing a **User-executed hardware test**.
