"""Scan-facing and asynchronous UI logic for the Four9 device."""

from __future__ import annotations

import math
import threading
import time
from typing import Any

from PyQt6 import QtCore

from .four9_hardware import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_SOCKET_TIMEOUT_S,
    Four9ConnectionError,
    Four9Hardware,
    Four9ProtocolError,
    Four9ServerError,
)


DEFAULT_STABLE_WAIT_TIMEOUT_S = 2 * 60 * 60
DEFAULT_STABLE_POLL_INTERVAL_S = 1.0


class Four9Logic(QtCore.QThread):
    """Expose Four9 scan channels while keeping GUI requests asynchronous."""

    sig_temperature = QtCore.pyqtSignal(object)
    sig_target_temperature = QtCore.pyqtSignal(object)
    sig_temperature_stable = QtCore.pyqtSignal(bool, str)
    sig_log = QtCore.pyqtSignal(object)
    sig_is_connected = QtCore.pyqtSignal(bool)

    def __init__(
        self,
        hardware: Four9Hardware | None = None,
        *,
        stable_wait_timeout_s: float = DEFAULT_STABLE_WAIT_TIMEOUT_S,
        stable_poll_interval_s: float = DEFAULT_STABLE_POLL_INTERVAL_S,
    ) -> None:
        super().__init__()
        self.hardware = hardware or Four9Hardware()

        self.host = getattr(self.hardware, "host", DEFAULT_HOST)
        self.port = int(getattr(self.hardware, "port", DEFAULT_PORT))
        self.socket_timeout_s = float(
            getattr(self.hardware, "socket_timeout_s", DEFAULT_SOCKET_TIMEOUT_S)
        )
        self.stable_wait_timeout_s = float(stable_wait_timeout_s)
        self.stable_poll_interval_s = float(stable_poll_interval_s)

        self.job = ""
        self.setpoint_temperature = 0.0
        self.is_connected = bool(getattr(self.hardware, "is_connected", False))

        self._abort_stable_wait = threading.Event()
        self._stable_wait_lock = threading.Lock()
        self._stable_wait_active = False
        self._last_server_error = ""
        self._latest_temperature: float | None = None
        self._latest_target: float | None = None
        self._latest_stable = False
        self._latest_stable_reason = "unknown"

    def _emit_log(self, message: object, level: str = "INFO") -> None:
        self.sig_log.emit((str(level).upper(), str(message)))

    def connect(self) -> bool:
        if self.is_connected and bool(getattr(self.hardware, "is_connected", False)):
            self.sig_is_connected.emit(True)
            self._emit_log(
                f"Already connected to Four9 at {self.host}:{self.port}."
            )
            return True

        self._emit_log(
            f"Connecting to Four9 at {self.host}:{self.port} "
            f"(socket timeout {self.socket_timeout_s:g} s)."
        )
        try:
            connected = bool(self.hardware.connect_hardware(self.host, self.port))
        except Exception as exc:
            self._mark_disconnected()
            self._emit_log(f"Four9 connection failed: {exc}", "ERROR")
            return False

        self.is_connected = connected
        self.sig_is_connected.emit(connected)
        if connected:
            self._emit_log(
                f"Connected to Four9 at {self.host}:{self.port}. "
                f"Stable-wait timeout is {self.stable_wait_timeout_s:g} s."
            )
        else:
            self._emit_log(
                f"Four9 connection failed at {self.host}:{self.port}.",
                "ERROR",
            )
        return connected

    def disconnect(self) -> None:
        self.request_abort_stable_wait(log_if_idle=False)
        if not self.is_connected and not bool(
            getattr(self.hardware, "is_connected", False)
        ):
            self._mark_disconnected()
            self._emit_log("Four9 is already disconnected.")
            return

        try:
            self.hardware.disconnect()
        except Exception as exc:
            self._emit_log(f"Four9 disconnect error: {exc}", "ERROR")
        finally:
            self._mark_disconnected()
            self._emit_log("Four9 disconnected.")

    # These are the only scan-discoverable get_/set_ methods in this class.
    def get_temperature(self) -> float:
        """Return cached server temperature and emit the full status snapshot."""

        status = self._request_status()
        temperature = self._apply_status(status)
        if temperature is None:
            error = Four9ProtocolError(
                "Four9 has not cached a temperature sample yet."
            )
            self._emit_log(error, "ERROR")
            raise error
        return temperature

    def set_temperature(self, target_k: float) -> float:
        """Set a 0-300 K target and passively refresh all UI status fields."""

        self._ensure_connected()
        target = Four9Hardware.validate_temperature(target_k)
        try:
            returned_target = float(self.hardware.set_temperature(target))
        except Exception as exc:
            self._handle_request_error(exc)
            raise

        self._mark_connected()
        self._latest_target = returned_target
        self.sig_target_temperature.emit(returned_target)

        status = self._request_status()
        self._apply_status(status)
        return returned_target

    def set_temperature_stable(self, target_k: float) -> bool:
        """Set temperature, then wait for the server's authoritative stable flag."""

        if not self._stable_wait_lock.acquire(blocking=False):
            raise RuntimeError("A Four9 stable wait is already active.")

        self._abort_stable_wait.clear()
        self._stable_wait_active = True
        start_time = time.monotonic()
        try:
            target = self.set_temperature(target_k)
            self._emit_log(
                f"Waiting for Four9 server stability at {target:.5f} K; "
                f"client timeout is {self.stable_wait_timeout_s:g} s."
            )

            while True:
                elapsed_s = time.monotonic() - start_time
                if self._latest_stable:
                    self._emit_log(
                        f"Four9 reported stable at {target:.5f} K after "
                        f"{elapsed_s:.1f} s ({self._latest_stable_reason})."
                    )
                    return True

                if elapsed_s >= self.stable_wait_timeout_s:
                    self._emit_log(
                        f"Four9 stable wait timed out after {elapsed_s:.1f} s "
                        f"at target {target:.5f} K; scan will continue.",
                        "WARNING",
                    )
                    return False

                wait_s = min(
                    self.stable_poll_interval_s,
                    max(0.0, self.stable_wait_timeout_s - elapsed_s),
                )
                if self._abort_stable_wait.wait(wait_s):
                    elapsed_s = time.monotonic() - start_time
                    self._emit_log(
                        f"Four9 stable wait stopped after {elapsed_s:.1f} s; "
                        f"target remains {target:.5f} K.",
                        "WARNING",
                    )
                    return False

                # Poll before checking the deadline again so the final server
                # state at the two-hour boundary is not discarded.
                status = self._request_status()
                self._apply_status(status)
        finally:
            self._stable_wait_active = False
            self._abort_stable_wait.clear()
            self._stable_wait_lock.release()

    def request_abort_stable_wait(self, *, log_if_idle: bool = True) -> None:
        if self._stable_wait_active:
            self._abort_stable_wait.set()
            self._emit_log("Stop requested for Four9 stable wait.", "WARNING")
        elif log_if_idle:
            self._emit_log("No Four9 stable wait is active.")

    def run(self) -> None:
        job = self.job
        self.job = ""
        try:
            if job == "connect":
                self.connect()
            elif job == "disconnect":
                self.disconnect()
            elif job == "set_temperature":
                self.set_temperature(self.setpoint_temperature)
            elif job == "get_temperature":
                self.get_temperature()
            elif job:
                raise ValueError(f"Unknown Four9 job: {job}")
        except Exception as exc:
            if not isinstance(
                exc, (Four9ConnectionError, Four9ProtocolError, Four9ServerError)
            ):
                self._emit_log(f"Four9 {job or 'job'} failed: {exc}", "ERROR")

    def _request_status(self) -> dict[str, Any]:
        self._ensure_connected()
        try:
            status = self.hardware.get_status()
        except Exception as exc:
            self._handle_request_error(exc)
            raise
        self._mark_connected()
        if not isinstance(status, dict):
            error = Four9ProtocolError("Four9 GET_STATUS data must be an object.")
            self._handle_request_error(error)
            raise error
        return status

    def _apply_status(self, status: dict[str, Any]) -> float | None:
        try:
            target = self._finite_number(status.get("target"), "target")
            stable_value = status.get("stable")
            if type(stable_value) is not bool:
                raise Four9ProtocolError(
                    "Four9 GET_STATUS is missing a boolean stable value."
                )

            raw_temperature = status.get("latest_temperature")
            temperature = (
                None
                if raw_temperature is None
                else self._finite_number(raw_temperature, "latest_temperature")
            )
            metrics = status.get("stability_metrics")
            if metrics is not None and not isinstance(metrics, dict):
                raise Four9ProtocolError(
                    "Four9 stability_metrics must be an object."
                )
            reason = "unknown"
            if isinstance(metrics, dict):
                reason = str(metrics.get("stable_reason") or "unknown")

            last_error = status.get("last_error", "")
            if last_error is None:
                last_error = ""
            if not isinstance(last_error, str):
                raise Four9ProtocolError("Four9 last_error must be text.")
        except Four9ProtocolError as exc:
            self._handle_request_error(exc)
            raise

        self._latest_target = target
        self._latest_temperature = temperature
        self._latest_stable = stable_value
        self._latest_stable_reason = reason

        self.sig_target_temperature.emit(target)
        if temperature is not None:
            self.sig_temperature.emit(temperature)
        self.sig_temperature_stable.emit(stable_value, reason)

        if last_error and last_error != self._last_server_error:
            self._emit_log(f"Four9 server last_error: {last_error}", "ERROR")
        self._last_server_error = last_error
        return temperature

    @staticmethod
    def _finite_number(value: Any, field_name: str) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise Four9ProtocolError(
                f"Four9 {field_name} must be numeric."
            ) from exc
        if not math.isfinite(number):
            raise Four9ProtocolError(f"Four9 {field_name} must be finite.")
        return number

    def _ensure_connected(self) -> None:
        if not self.is_connected or not bool(
            getattr(self.hardware, "is_connected", False)
        ):
            self._mark_disconnected()
            raise Four9ConnectionError("Four9 is not connected.")

    def _handle_request_error(self, exc: Exception) -> None:
        if isinstance(exc, Four9ServerError):
            self._emit_log(f"Four9 server rejected request: {exc}", "ERROR")
            return
        if isinstance(exc, (Four9ConnectionError, Four9ProtocolError)):
            try:
                self.hardware.disconnect()
            except Exception:
                pass
            self._mark_disconnected()
            self._emit_log(f"Four9 connection/protocol error: {exc}", "ERROR")
            return
        self._emit_log(f"Four9 request error: {exc}", "ERROR")

    def _mark_connected(self) -> None:
        if not self.is_connected:
            self.is_connected = True
            self.sig_is_connected.emit(True)

    def _mark_disconnected(self) -> None:
        self.is_connected = False
        self.sig_is_connected.emit(False)
