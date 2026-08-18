"""Thorlabs BBD30X/DDS220 hardware adapter.

The optional pythonnet and Kinesis runtime are loaded only when ``connect`` is
called. Importing this module therefore does not enumerate or connect hardware.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable

from core.shared_runtime.kinesis import KinesisRuntime, KinesisRuntimeLease


class BBD30x_hardware:
    MIN_POSITION_MM = 0.0
    MAX_POSITION_MM = 220.0
    DEFAULT_VELOCITY_MM_S = 100.0
    DEFAULT_ACCELERATION_MM_S2 = 2000.0
    MOVE_TOLERANCE_MM = 0.0001

    def __init__(
        self,
        kinesis_runtime: KinesisRuntime | None = None,
        completion_callback_factory: Callable[[Callable[[object], None]], object]
        | None = None,
        move_timeout_seconds: float = 50.0,
        poll_interval_seconds: float = 0.1,
    ):
        self.device = None
        self.channel = None
        self.kinesis_runtime = kinesis_runtime or KinesisRuntime()
        self._kinesis_lease: KinesisRuntimeLease | None = None
        self._dm = None
        self._gm = None
        self._bm = None
        self._convert = None
        self._decimal = None
        self._completion_callback_factory = (
            completion_callback_factory or self._make_completion_callback
        )
        self.move_timeout_seconds = float(move_timeout_seconds)
        self.poll_interval_seconds = float(poll_interval_seconds)

    @staticmethod
    def _make_completion_callback(callback: Callable[[object], None]):
        # Imported lazily so constructing the widget remains pythonnet-free.
        from System import Action, UInt64

        return Action[UInt64](callback)

    def _ensure_bindings(self):
        if self._dm is not None:
            if self._kinesis_lease is None:
                self._kinesis_lease = self.kinesis_runtime.acquire(
                    f"BBD30X:{id(self):x}"
                )
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

    def _require_channel(self):
        if self.channel is None:
            raise RuntimeError("BBD30X is not connected")
        return self.channel

    def connect(self, serial_no: str) -> tuple[float, float]:
        try:
            self._ensure_bindings()
            print("trying to find BBD ...")
            self.serial_no = str(serial_no)

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
            self.channel.WaitForSettingsInitialized(5000)

            try:
                self.channel.LoadMotorConfiguration(self.channel.DeviceID)
            except Exception as exc:
                print("Load from device failed, applying file settings for DDS220...", exc)
                cfg = self.channel.LoadMotorConfiguration(
                    self.channel.DeviceID,
                    self._gm.DeviceConfiguration.DeviceSettingsUseOptionType.UseFileSettings,
                )
                cfg.DeviceSettingsName = "DDS220"
                cfg.UpdateCurrentConfiguration()
                self.channel.SetSettings(self.channel.MotorDeviceSettings, True, False)

            self.channel.StartPolling(50)
            time.sleep(0.3)
            self.channel.EnableDevice()
            time.sleep(0.3)
            velocity_params = self.set_velocity_params(
                self.DEFAULT_VELOCITY_MM_S,
                self.DEFAULT_ACCELERATION_MM_S2,
            )
            print("BBD connected")
            return velocity_params
        except Exception:
            self.disconnect()
            raise

    def connect3(self, serial_no: str):
        """Preserved alternate connection path; not used by the ZMeter widget."""
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
        self.set_velocity_params(
            self.DEFAULT_VELOCITY_MM_S,
            self.DEFAULT_ACCELERATION_MM_S2,
        )
        self.channel.StartPolling(10)
        time.sleep(0.25)
        self.channel.EnableDevice()
        time.sleep(0.25)

    def set_homing_velocity(self, vel=10.0):
        channel = self._require_channel()
        home_params = channel.GetHomingParams()
        print(
            f"Homing Velocity: {home_params.Velocity}\n",
            f"Homing Direction: {home_params.Direction}",
        )
        home_params.Velocity = self._convert.ToDecimal(vel)
        home_params.Direction = self._gm.Settings.HomeSettings.HomeDirection.CounterClockwise
        channel.SetHomingParams(home_params)

    @staticmethod
    def _validate_positive_finite(value: object, name: str) -> float:
        numeric = float(value)
        if not math.isfinite(numeric) or numeric <= 0:
            raise ValueError(f"{name} must be a finite value greater than zero")
        return numeric

    @classmethod
    def validate_position_mm(cls, value: object) -> float:
        numeric = float(value)
        if not math.isfinite(numeric):
            raise ValueError("BBD30X position must be finite")
        if numeric < cls.MIN_POSITION_MM or numeric > cls.MAX_POSITION_MM:
            raise ValueError(
                f"BBD30X position {numeric} mm is outside "
                f"[{cls.MIN_POSITION_MM}, {cls.MAX_POSITION_MM}] mm"
            )
        return numeric

    def get_velocity_params(self) -> tuple[float, float]:
        params = self._require_channel().GetVelocityParams()
        velocity = float(self._decimal.ToDouble(params.MaxVelocity))
        acceleration = float(self._decimal.ToDouble(params.Acceleration))
        return velocity, acceleration

    def set_velocity_params(
        self, velocity: object | None = None, acceleration: object | None = None
    ) -> tuple[float, float]:
        channel = self._require_channel()
        if velocity is None and acceleration is None:
            return self.get_velocity_params()

        params = channel.GetVelocityParams()
        if velocity is not None:
            velocity = self._validate_positive_finite(velocity, "Velocity")
            params.MaxVelocity = self._convert.ToDecimal(velocity)
        if acceleration is not None:
            acceleration = self._validate_positive_finite(acceleration, "Acceleration")
            params.Acceleration = self._convert.ToDecimal(acceleration)
        channel.SetVelocityParams(params)
        return self.get_velocity_params()

    def home(self):
        self._require_channel().Home(60000)

    def move(
        self,
        position_mm: object,
        position_callback: Callable[[float], None] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> float:
        target_mm = self.validate_position_mm(position_mm)
        channel = self._require_channel()
        completed = threading.Event()

        def on_completed(_task_id):
            completed.set()

        callback = self._completion_callback_factory(on_completed)
        channel.MoveTo(self._decimal(target_mm), callback)
        deadline = time.monotonic() + self.move_timeout_seconds

        while True:
            current_mm = self.get_cached_position_mm()
            if position_callback is not None:
                position_callback(current_mm)

            if completed.is_set() and abs(current_mm - target_mm) <= self.MOVE_TOLERANCE_MM:
                return current_mm
            if cancel_event is not None and cancel_event.is_set():
                self.stop_motion()
                raise RuntimeError("BBD30X move cancelled")
            if time.monotonic() >= deadline:
                self.stop_motion()
                raise TimeoutError(f"BBD30X did not reach {target_mm} mm within timeout.")
            time.sleep(self.poll_interval_seconds)

    def get_cached_position_mm(self) -> float:
        return float(self._decimal.ToDouble(self._require_channel().Position))

    def get_position_mm(self) -> float:
        time.sleep(0.5)
        return self.get_cached_position_mm()

    def get_target_position_mm(self) -> float:
        channel = self._require_channel()
        target = (
            channel.TargetPosition
            if hasattr(channel, "TargetPosition")
            else channel.Position
        )
        return float(self._decimal.ToDouble(target))

    def stop_motion(self) -> bool:
        if self.channel is None:
            return False
        self.channel.Stop(5000)
        return True

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
