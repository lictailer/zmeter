#!/usr/bin/env python3
"""
Hardware helpers for the combined autofocus / reposition feature.

This file keeps two layers separate:
1. `stepperMotorHardware`: raw blocking serial communication with the Arduino.
2. `AutofocusXZHardware`: a thin wrapper that adds
   - angle <-> height conversion
   - reference-value reads through the device command router

`HOME` is a software home at 0 degrees because the current hardware description
does not include a physical home switch.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from typing import Any, Optional

import serial
from PyQt6 import QtCore

try:
    from core.device_command_router import DeviceCommandClient
except ImportError:
    _repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    from core.device_command_router import DeviceCommandClient



class stepperMotorHardware:
    """Minimal blocking serial driver for the Arduino-based stepper controller."""

    def __init__(
        self,
        com_port: str = "COM7",
        baud_rate: int = 115200,
        read_poll_timeout_s: float = 0.2,
        command_timeout_s: float = 120.0,
        startup_delay_s: float = 2.0,
    ) -> None:
        self.com_port = com_port
        self.baud_rate = int(baud_rate)
        self.read_poll_timeout_s = float(read_poll_timeout_s)
        self.command_timeout_s = float(command_timeout_s)
        self.startup_delay_s = float(startup_delay_s)

        self._serial: Optional[serial.Serial] = None
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(
        self,
        com_port: Optional[str] = None,
        baud_rate: Optional[int] = None,
    ) -> None:
        """Open the serial port and verify communication with the Arduino."""
        with self._lock:
            if self.is_connected:
                return

            if com_port is not None:
                self.com_port = com_port
            if baud_rate is not None:
                self.baud_rate = int(baud_rate)

            try:
                self._serial = serial.Serial(
                    port=self.com_port,
                    baudrate=self.baud_rate,
                    timeout=self.read_poll_timeout_s,
                    write_timeout=2.0,
                )
                time.sleep(self.startup_delay_s)
                self._serial.reset_input_buffer()
                self._serial.reset_output_buffer()
                response = self._send_command("PING", expected_prefixes=("OK",))
                if response != "OK PONG":
                    raise RuntimeError(
                        f"Unexpected Arduino handshake response: {response!r}"
                    )
            except Exception:
                self.disconnect()
                raise

    def disconnect(self) -> None:
        """Close the serial connection."""
        with self._lock:
            if self._serial is None:
                return
            try:
                if self._serial.is_open:
                    self._serial.close()
            finally:
                self._serial = None

    def motor_move_absolute_to(self, position_deg: float) -> float:
        """Move the motor to an absolute angle in degrees."""
        return self._send_move_command(f"MOVE_ABS {float(position_deg):.6f}")

    def motor_move_relative_to(self, delta_deg: float) -> float:
        """Move the motor by a relative angle in degrees."""
        return self._send_move_command(f"MOVE_REL {float(delta_deg):.6f}")

    def motor_current_position(self) -> float:
        """Return the current motor angle in degrees."""
        response = self._send_command("GET_POS", expected_prefixes=("POS",))
        return self._parse_position_response(response, expected_prefix="POS")

    def set_motor_current_position_to_zero(self) -> float:
        """Set the current motor position to 0 degrees without moving."""
        return self._send_move_command("ZERO")

    def motor_position_to_home(self) -> float:
        """Move the motor to the software home position at 0 degrees."""
        return self._send_move_command("HOME")

    def _send_move_command(self, command: str) -> float:
        response = self._send_command(command, expected_prefixes=("OK",))
        return self._parse_position_response(response, expected_prefix="OK")

    def _send_command(self, command: str, expected_prefixes: tuple[str, ...]) -> str:
        with self._lock:
            self._ensure_connected()
            assert self._serial is not None

            self._serial.reset_input_buffer()
            self._serial.write(f"{command}\n".encode("ascii"))
            self._serial.flush()

            deadline = time.monotonic() + self.command_timeout_s
            while time.monotonic() < deadline:
                raw_line = self._serial.readline()
                if not raw_line:
                    continue

                line = raw_line.decode("ascii", errors="replace").strip()
                if not line or line == "READY":
                    continue
                if line.startswith("ERR "):
                    raise RuntimeError(line[4:].strip())
                if line.startswith(expected_prefixes):
                    return line

            raise TimeoutError(f"No response for command {command!r}.")

    @staticmethod
    def _parse_position_response(response: str, expected_prefix: str) -> float:
        prefix = f"{expected_prefix} "
        if not response.startswith(prefix):
            raise RuntimeError(f"Unexpected response: {response!r}")

        try:
            return float(response[len(prefix) :].strip())
        except ValueError as exc:
            raise RuntimeError(f"Could not parse position from {response!r}") from exc

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            raise RuntimeError("Stepper motor is not connected. Call connect() first.")


class _CommandBusHardware:
    """Small blocking helper around the injected DeviceCommandClient."""

    def __init__(
        self,
        command_router: Any = None,
        source_device: str = "unknown_device",
        request_timeout_s: float = 5.0,
    ) -> None:
        self.command_router = command_router
        self.source_device = str(source_device)
        self.request_timeout_s = float(request_timeout_s)

        self._client: Optional[DeviceCommandClient] = None
        self._qt_app: Optional[QtCore.QCoreApplication] = None

    @property
    def device_label(self) -> str:
        return self.source_device

    @device_label.setter
    def device_label(self, value: str) -> None:
        self.source_device = str(value)
        self._client = None

    def configure_command_router(
        self,
        command_router: Any,
        source_device: Optional[str] = None,
    ) -> None:
        self.command_router = command_router
        if source_device is not None:
            self.source_device = str(source_device)
        self._client = None

    def list_available_channels(self) -> dict[str, Any]:
        response = self._request_via_client(
            send=lambda request_id: self._ensure_client().request_catalog(
                request_id=request_id
            )
        )
        catalog = response.get("catalog")
        if not isinstance(catalog, dict):
            raise RuntimeError(f"Invalid catalog response: {catalog!r}")
        return catalog

    def read_channel(self, target_device: str, channel: str) -> float:
        self._validate_channel_target(target_device, channel, name="read")
        response = self._request_via_client(
            send=lambda request_id: self._ensure_client().request_read(
                target_device=target_device,
                channel=channel,
                request_id=request_id,
            )
        )
        return float(response["value"])

    def write_channel(self, target_device: str, channel: str, value: Any) -> Any:
        self._validate_channel_target(target_device, channel, name="write")
        response = self._request_via_client(
            send=lambda request_id: self._ensure_client().request_write(
                target_device=target_device,
                channel=channel,
                value=value,
                request_id=request_id,
            )
        )
        return response["value"]

    def _disconnect_command_client(self) -> None:
        self._client = None

    def _request_via_client(self, send) -> dict[str, Any]:
        client = self._ensure_client()
        app = self._ensure_qt_app()

        holder: dict[str, Any] = {"response": None}

        def on_response(response: object) -> None:
            if isinstance(response, dict):
                holder["response"] = response

        client.sig_response.connect(on_response)
        try:
            request_id = str(uuid.uuid4())
            send(request_id)

            deadline = time.monotonic() + self.request_timeout_s
            while holder["response"] is None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(0.005)

            response = holder["response"]
            if response is None:
                raise TimeoutError(f"No command bus response for request {request_id}.")
            if not response.get("ok", False):
                raise RuntimeError(
                    f"{response.get('error_code')}: {response.get('error_message')}"
                )
            return response
        finally:
            client.sig_response.disconnect(on_response)

    def _ensure_client(self) -> DeviceCommandClient:
        if self.command_router is None:
            raise RuntimeError("command_router is not set.")
        if self._client is None:
            self._client = DeviceCommandClient(
                self.command_router,
                self.source_device,
            )
        return self._client

    def _ensure_qt_app(self) -> QtCore.QCoreApplication:
        app = QtCore.QCoreApplication.instance()
        if app is None:
            if self._qt_app is None:
                self._qt_app = QtCore.QCoreApplication([])
            app = self._qt_app
        return app

    @staticmethod
    def _validate_channel_target(target_device: str, channel: str, name: str) -> None:
        if not target_device:
            raise ValueError(f"{name} target_device must not be empty.")
        if not channel:
            raise ValueError(f"{name} channel must not be empty.")


class AutofocusXZHardware(_CommandBusHardware):
    """
    Z autofocus hardware wrapper.

    Logic-side usage:
    1. `list_available_channels()`
    2. `set_reference_channel(device, channel)`
    3. move in height and call `read_reference_value()`
    """

    def __init__(
        self,
        translator_height_per_rev: float = 500.0,
        gear_ratio: float = 100.0 / 30.0,
        command_router: Any = None,
        source_device: str = "autofocus_xz",
        stepper_motor: Optional[stepperMotorHardware] = None,
        request_timeout_s: float = 5.0,
    ) -> None:
        super().__init__(
            command_router=command_router,
            source_device=source_device,
            request_timeout_s=request_timeout_s,
        )
        self.stepper_motor = stepper_motor or stepperMotorHardware()
        self.reference_target_device: Optional[str] = None
        self.reference_channel: Optional[str] = None

        self.translator_height_per_rev = 500.0
        self.gear_ratio = 100.0 / 30.0
        self.set_height_conversion(
            translator_height_per_rev=translator_height_per_rev,
            gear_ratio=gear_ratio,
        )

    @property
    def is_connected(self) -> bool:
        return self.stepper_motor.is_connected

    def connect(self) -> None:
        self.stepper_motor.connect()

    def disconnect(self) -> None:
        self.stepper_motor.disconnect()
        self._disconnect_command_client()

    # ---------------- angle / height conversion ----------------
    def set_height_conversion(
        self,
        translator_height_per_rev: Optional[float] = None,
        gear_ratio: Optional[float] = None,
    ) -> None:
        """
        Configure the translator conversion.

        translator_height_per_rev:
            translator travel in micrometers for one translator revolution
        gear_ratio:
            motor_angle / translator_angle
        """
        if translator_height_per_rev is not None:
            if translator_height_per_rev <= 0:
                raise ValueError("translator_height_per_rev must be positive.")
            self.translator_height_per_rev = float(translator_height_per_rev)

        if gear_ratio is not None:
            if gear_ratio <= 0:
                raise ValueError("gear_ratio must be positive.")
            self.gear_ratio = float(gear_ratio)

    def angle_to_height(self, angle_deg: float) -> float:
        return (
            float(angle_deg)
            * self.translator_height_per_rev
            / (360.0 * self.gear_ratio)
        )

    def height_to_angle(self, height_um: float) -> float:
        return (
            float(height_um)
            * 360.0
            * self.gear_ratio
            / self.translator_height_per_rev
        )

    def move_absolute_height(self, height_um: float) -> float:
        final_angle = self.stepper_motor.motor_move_absolute_to(
            self.height_to_angle(height_um)
        )
        return self.angle_to_height(final_angle)

    def move_absoulte_height(self, height_um: float) -> float:
        return self.move_absolute_height(height_um)

    def move_relative_height(self, delta_height_um: float) -> float:
        final_angle = self.stepper_motor.motor_move_relative_to(
            self.height_to_angle(delta_height_um)
        )
        return self.angle_to_height(final_angle)

    def current_height(self) -> float:
        return self.angle_to_height(self.stepper_motor.motor_current_position())

    def zero(self) -> float:
        final_angle = self.stepper_motor.set_motor_current_position_to_zero()
        return self.angle_to_height(final_angle)

    def home(self) -> float:
        final_angle = self.stepper_motor.motor_position_to_home()
        return self.angle_to_height(final_angle)

    def set_reference_channel(
        self,
        target_device: str,
        channel: str,
    ) -> None:
        self._validate_channel_target(target_device, channel, name="reference")
        self.reference_target_device = str(target_device)
        self.reference_channel = str(channel)

    def read_reference_value(self) -> float:
        if self.reference_target_device is None or self.reference_channel is None:
            raise RuntimeError("Reference channel is not configured.")
        return self.read_channel(
            target_device=self.reference_target_device,
            channel=self.reference_channel,
        )


class AutoPositionXZHardware(_CommandBusHardware):
    """
    X/Y auto-position hardware wrapper.

    Logic-side usage:
    1. `list_available_channels()`
    2. `set_position_channels(...)` and `set_reference_channel(...)`
    3. move X/Y with absolute writes and call `read_reference_value()`
    """

    def __init__(
        self,
        command_router: Any = None,
        source_device: str = "autoposition_xz",
        request_timeout_s: float = 5.0,
    ) -> None:
        super().__init__(
            command_router=command_router,
            source_device=source_device,
            request_timeout_s=request_timeout_s,
        )

        self.x_target_device: Optional[str] = None
        self.x_channel: Optional[str] = None
        self.y_target_device: Optional[str] = None
        self.y_channel: Optional[str] = None
        self.reference_target_device: Optional[str] = None
        self.reference_channel: Optional[str] = None

    def connect(self) -> None:
        self._ensure_client()

    def disconnect(self) -> None:
        self._disconnect_command_client()

    def set_position_channels(
        self,
        x_target_device: str,
        x_channel: str,
        y_target_device: str,
        y_channel: str,
    ) -> None:
        self._validate_channel_target(x_target_device, x_channel, name="X")
        self._validate_channel_target(y_target_device, y_channel, name="Y")

        self.x_target_device = str(x_target_device)
        self.x_channel = str(x_channel)
        self.y_target_device = str(y_target_device)
        self.y_channel = str(y_channel)

    def set_reference_channel(
        self,
        target_device: str,
        channel: str,
    ) -> None:
        self._validate_channel_target(target_device, channel, name="reference")
        self.reference_target_device = str(target_device)
        self.reference_channel = str(channel)

    def move_absoluteX(self, value: float) -> float:
        target_device, channel = self._require_x_channel()
        self.write_channel(target_device, channel, float(value))
        return float(value)

    def move_absoluteY(self, value: float) -> float:
        target_device, channel = self._require_y_channel()
        self.write_channel(target_device, channel, float(value))
        return float(value)

    def read_reference_value(self) -> float:
        if self.reference_target_device is None or self.reference_channel is None:
            raise RuntimeError("Reference channel is not configured.")
        return self.read_channel(
            target_device=self.reference_target_device,
            channel=self.reference_channel,
        )

    def _require_x_channel(self) -> tuple[str, str]:
        if self.x_target_device is None or self.x_channel is None:
            raise RuntimeError("X position channel is not configured.")
        return self.x_target_device, self.x_channel

    def _require_y_channel(self) -> tuple[str, str]:
        if self.y_target_device is None or self.y_channel is None:
            raise RuntimeError("Y position channel is not configured.")
        return self.y_target_device, self.y_channel
