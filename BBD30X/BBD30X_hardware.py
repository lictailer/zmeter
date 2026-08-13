"""Thorlabs BBD30X/DDS220 hardware adapter.

The optional pythonnet and Kinesis runtime are loaded only when ``connect`` is
called. Importing this module therefore does not enumerate or connect hardware.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

import numpy


KINESIS_DIR_ENV = "THORLABS_KINESIS_DIR"
KINESIS_DIR_LOCAL = os.path.join(os.path.dirname(__file__), "Kinesis")
KINESIS_DIR_PROGRAM_FILES = r"C:\Program Files\Thorlabs\Kinesis"
DM = None
GM = None
BM = None
Convert = None
Decimal = None
_KINESIS_LOADED = False
_DLL_DIRECTORY_HANDLES = []


def _candidate_kinesis_directories():
    configured_dir = os.environ.get(KINESIS_DIR_ENV, "").strip()
    candidates = [configured_dir, KINESIS_DIR_PROGRAM_FILES, KINESIS_DIR_LOCAL]
    unique_candidates = []
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = os.path.normcase(os.path.abspath(candidate))
        if normalized in seen:
            continue
        seen.add(normalized)
        unique_candidates.append(candidate)
    return unique_candidates


def _prepare_dll_directory(base_dir):
    if hasattr(os, "add_dll_directory"):
        _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(base_dir))

    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    normalized_entries = {os.path.normcase(os.path.abspath(path)) for path in path_entries if path}
    normalized_base = os.path.normcase(os.path.abspath(base_dir))
    if normalized_base not in normalized_entries:
        os.environ["PATH"] = base_dir + os.pathsep + os.environ.get("PATH", "")


def _add_reference_from(clr_module, base_dir, dll_name):
    dll_path = os.path.join(base_dir, dll_name)
    clr_module.AddReference(dll_path)


def _load_kinesis_cli():
    global DM, GM, BM, Convert, Decimal, _KINESIS_LOADED
    if _KINESIS_LOADED:
        return DM, GM, BM, Convert, Decimal

    dlls = [
        "Thorlabs.MotionControl.DeviceManagerCLI.dll",
        "Thorlabs.MotionControl.GenericMotorCLI.dll",
        "Thorlabs.MotionControl.Benchtop.BrushlessMotorCLI.dll",
    ]
    candidates = _candidate_kinesis_directories()
    complete_directories = [
        base_dir
        for base_dir in candidates
        if os.path.isdir(base_dir)
        and all(os.path.isfile(os.path.join(base_dir, dll)) for dll in dlls)
    ]
    if not complete_directories:
        searched = ", ".join(candidates)
        raise FileNotFoundError(
            "Could not find the required Thorlabs Kinesis CLI DLLs. "
            f"Set {KINESIS_DIR_ENV} or install Kinesis. Searched: {searched}"
        )

    try:
        import clr
        from System import Convert as system_convert, Decimal as system_decimal
    except ImportError as exc:
        raise ImportError(
            "BBD30X requires the optional 'pythonnet' package to load Thorlabs Kinesis."
        ) from exc

    last_error = None
    for base_dir in complete_directories:
        try:
            _prepare_dll_directory(base_dir)
            for dll in dlls:
                _add_reference_from(clr, base_dir, dll)

            import Thorlabs.MotionControl.DeviceManagerCLI as device_manager
            import Thorlabs.MotionControl.GenericMotorCLI as generic_motor
            import Thorlabs.MotionControl.Benchtop.BrushlessMotorCLI as brushless_motor

            DM = device_manager
            GM = generic_motor
            BM = brushless_motor
            Convert = system_convert
            Decimal = system_decimal
            _KINESIS_LOADED = True
            return DM, GM, BM, Convert, Decimal
        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        "Found Kinesis CLI DLLs but could not load them. Check Kinesis, pythonnet, "
        f".NET, and process bitness. Last error: {last_error}"
    ) from last_error


class BBD30x_hardware:

    def __init__(self, kinesis_loader: Callable | None = None):
        self.device = None
        self.channel = None
        self._kinesis_loader = kinesis_loader or _load_kinesis_cli
        self._dm = None
        self._gm = None
        self._bm = None
        self._convert = None
        self._decimal = None

    def _ensure_bindings(self):
        if self._dm is not None:
            return
        bindings = self._kinesis_loader()
        if bindings is None:
            bindings = (DM, GM, BM, Convert, Decimal)
        if len(bindings) != 5 or any(binding is None for binding in bindings):
            raise RuntimeError("The Kinesis loader did not provide complete bindings.")
        self._dm, self._gm, self._bm, self._convert, self._decimal = bindings

    def connect(self, serial_no: str):
        self._ensure_bindings()
        print("trying to find BBD ...")
        self.serial_no = str(serial_no)

        # 1) connect
        self._dm.DeviceManagerCLI.BuildDeviceList()
        for serial in self._dm.DeviceManagerCLI.GetDeviceList():
            print("Found BBD:", serial)

        self.device = self._bm.BenchtopBrushlessMotor.CreateBenchtopBrushlessMotor(
            self.serial_no
        )
        self.device.Connect(self.serial_no)
        self.channel = self.device.GetChannel(1)

        # 2) wait for internal init BEFORE loading config -- important
        self.channel.WaitForSettingsInitialized(5000)

        # 3) try device settings; fallback to file settings and apply DDS220
        try:
            _ = self.channel.LoadMotorConfiguration(self.channel.DeviceID)
        except Exception as exc:
            print("Load from device failed, applying file settings for DDS220...", exc)
            cfg = self.channel.LoadMotorConfiguration(
                self.channel.DeviceID,
                self._gm.DeviceConfiguration.DeviceSettingsUseOptionType.UseFileSettings,
            )
            cfg.DeviceSettingsName = "DDS220"
            cfg.UpdateCurrentConfiguration()
            # True = initialize device with these settings; False = don't persist ranges
            self.channel.SetSettings(self.channel.MotorDeviceSettings, True, False)

        # 4) start polling and enable after configuration
        self.channel.StartPolling(50)
        time.sleep(0.3)
        self.channel.EnableDevice()
        time.sleep(0.3)
        print("BBD connected")

    def connect3(self, serial_no: str):
        self._ensure_bindings()
        print("trying to find BBD ...")
        self.serial_no = serial_no
        self._dm.DeviceManagerCLI.BuildDeviceList()

        for serial in self._dm.DeviceManagerCLI.GetDeviceList():
            print("Found BBD: ", serial)

        self.device = self._bm.BenchtopBrushlessMotor.CreateBenchtopBrushlessMotor(
            self.serial_no
        )
        self.device.Connect(self.serial_no)
        self.channel = self.device.GetChannel(1)

        self.channel.WaitForSettingsInitialized(5000)

        device_info = self.channel.GetDeviceInfo()
        print(device_info.Description)

        motor_config = self.channel.LoadMotorConfiguration(self.channel.DeviceID)
        device_settings = self.channel.MotorDeviceSettings
        motor_config.UpdateCurrentConfiguration()
        self.channel.SetSettings(device_settings, False)
        if not self.channel.IsSettingsInitialized():
            self.channel.WaitForSettingsInitialized(10000)
            assert self.channel.IsSettingsInitialized() is True

        self.set_homing_velocity()
        self.set_velocity_params(30, 100)

        self.channel.StartPolling(10)
        time.sleep(0.25)
        self.channel.EnableDevice()
        time.sleep(0.25)

    def set_homing_velocity(self, vel=10.0):
        home_params = self.channel.GetHomingParams()
        print(
            f"Homing Velocity: {home_params.Velocity}\n",
            f"Homing Direction: {home_params.Direction}",
        )
        home_params.Velocity = self._convert.ToDecimal(vel)
        home_params.Direction = self._gm.Settings.HomeSettings.HomeDirection.CounterClockwise
        self.channel.SetHomingParams(home_params)
        home_params = self.channel.GetHomingParams()
        print(
            f"Homing Velocity: {home_params.Velocity}\n",
            f"Homing Direction: {home_params.Direction}",
        )

    def set_velocity_params(self, vel=100.0, acceleration=1000.0):
        print("here")
        vel_params = self.channel.GetVelocityParams()
        print(
            f"Move Maximum Velocity: {vel_params.MaxVelocity}\n",
            f"Move Acceleration: {vel_params.Acceleration}",
        )
        vel_params.MaxVelocity = self._convert.ToDecimal(vel)
        vel_params.Acceleration = self._convert.ToDecimal(acceleration)
        self.channel.SetVelocityParams(vel_params)
        vel_params = self.channel.GetVelocityParams()
        print(
            f"Move Maximum Velocity: {vel_params.MaxVelocity}\n",
            f"Move Acceleration: {vel_params.Acceleration}",
        )

    def home(self):
        self.channel.Home(60000)

    def move_abs(self, pos: float):
        new_pos = self._decimal(pos)  # real units: mm
        self.channel.MoveTo(new_pos, 50000)

    def move(self, pos: float):
        self.move_abs(pos)

        tolerance_mm = 0.1e-3
        max_checks = 100
        for _ in range(max_checks):
            if numpy.abs(self.get_position_mm() - pos) <= tolerance_mm:
                return
            time.sleep(0.05)

        raise TimeoutError(f"BBD30X did not reach {pos} mm within timeout.")

    def get_position_mm(self) -> float:
        time.sleep(0.5)
        return self._decimal.ToDouble(self.channel.Position)

    def disconnect(self):
        if self.channel is not None:
            try:
                self.channel.StopPolling()
            except Exception as exc:
                print(f"BBD30X StopPolling failed: {exc}")

        if self.device is not None:
            try:
                self.device.Disconnect()
            except Exception as exc:
                print(f"BBD30X disconnect failed: {exc}")

        self.channel = None
        self.device = None
