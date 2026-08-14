"""Thorlabs BBD30X/DDS220 hardware adapter.

The optional pythonnet and Kinesis runtime are loaded only when ``connect`` is
called. Importing this module therefore does not enumerate or connect hardware.
"""

from __future__ import annotations

import time

import numpy

from core.shared_runtime.kinesis import KinesisRuntime, KinesisRuntimeLease


class BBD30x_hardware:

    def __init__(self, kinesis_runtime: KinesisRuntime | None = None):
        self.device = None
        self.channel = None
        self.kinesis_runtime = kinesis_runtime or KinesisRuntime()
        self._kinesis_lease: KinesisRuntimeLease | None = None
        self._dm = None
        self._gm = None
        self._bm = None
        self._convert = None
        self._decimal = None

    def _ensure_bindings(self):
        if self._dm is not None:
            return
        lease = self.kinesis_runtime.acquire(f"BBD30X:{id(self):x}")
        try:
            bindings = self.kinesis_runtime.load_managed("bbd30x")
            if len(bindings) != 5 or any(binding is None for binding in bindings):
                raise RuntimeError("The Kinesis runtime did not provide complete bindings.")
            self._dm, self._gm, self._bm, self._convert, self._decimal = bindings
            self._kinesis_lease = lease
        except Exception:
            lease.close()
            raise

    def connect(self, serial_no: str):
        try:
            self._ensure_bindings()
            print("trying to find BBD ...")
            self.serial_no = str(serial_no)

            # 1) connect
            self.kinesis_runtime.initialize_device_manager(
                self._dm.DeviceManagerCLI.BuildDeviceList
            )
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
        except Exception:
            self.disconnect()
            raise

    def connect3(self, serial_no: str):
        self._ensure_bindings()
        print("trying to find BBD ...")
        self.serial_no = serial_no
        self.kinesis_runtime.initialize_device_manager(
            self._dm.DeviceManagerCLI.BuildDeviceList
        )

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
        if self._kinesis_lease is not None:
            self._kinesis_lease.close()
            self._kinesis_lease = None
