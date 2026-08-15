# Local Thorlabs Kinesis runtime

This tracked directory contains the reviewed 64-bit Kinesis release files used
by both K10CR1 and BBD30X. The tracked `manifest.json` defines and verifies the
exact required set.

Current approved source on the laboratory workstation:

```text
C:\Users\Taylo\Documents\GitHub\Kinesis
```

The BBD30X managed assemblies are explicitly loaded in dependency order:

1. `Thorlabs.MotionControl.Tools.Logging.dll`
2. `Thorlabs.MotionControl.Tools.Common.dll`
3. `Thorlabs.MotionControl.Tools.WPF.dll`
4. `Thorlabs.MotionControl.PrivateInternal.dll`
5. `Thorlabs.MotionControl.DeviceManagerCLI.dll`
6. `Thorlabs.MotionControl.GenericMotorCLI.dll`
7. `Thorlabs.MotionControl.Benchtop.BrushlessMotorCLI.dll`

When updating Kinesis, replace only the manifest-listed files from that one
source directory and update their manifest identities in the same change. Do
not combine them with older device-package DLLs, another installation, or
another release. Deploy this entire directory, including `manifest.json`; do
not copy only the DLL named by the first assembly-load exception.
