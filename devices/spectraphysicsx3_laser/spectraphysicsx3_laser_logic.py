"""Scan-facing wavelength move and background panel jobs for InSight X3."""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import Any

from PyQt6 import QtCore

from .spectraphysicsx3_laser_hardware import (
    SpectraPhysicsX3Hardware,
    X3ConnectionError,
    X3ProtocolError,
    X3Status,
)


class X3MoveTimeout(TimeoutError):
    """A commanded state was not confirmed in time."""


class X3OperationCancelled(RuntimeError):
    """A ZMeter stop interrupted confirmation, without a shutdown command."""


class SpectraPhysicsX3Logic(QtCore.QThread):
    sig_connected = QtCore.pyqtSignal(bool)
    sig_target_wavelength = QtCore.pyqtSignal(object)
    sig_actual_wavelength = QtCore.pyqtSignal(object)
    sig_status_word = QtCore.pyqtSignal(object)
    sig_power_w = QtCore.pyqtSignal(object)
    sig_mode = QtCore.pyqtSignal(object)
    sig_diode_temperature_c = QtCore.pyqtSignal(object)
    sig_diode_current_a = QtCore.pyqtSignal(object)
    sig_diode_hours = QtCore.pyqtSignal(object)
    sig_warmup_percent = QtCore.pyqtSignal(object)
    sig_humidity_percent = QtCore.pyqtSignal(object)
    sig_motor_position_percent = QtCore.pyqtSignal(object)
    sig_identity = QtCore.pyqtSignal(object)
    sig_message = QtCore.pyqtSignal(str)
    sig_error = QtCore.pyqtSignal(str)

    def __init__(
        self,
        hardware: SpectraPhysicsX3Hardware | None = None,
        move_timeout_s: float = 120.0,
        poll_interval_s: float = 0.25,
        stable_reads: int = 2,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        self.hardware = hardware or SpectraPhysicsX3Hardware()
        self.move_timeout_s = self._positive_finite(move_timeout_s, "move timeout")
        self.poll_interval_s = self._positive_finite(
            poll_interval_s, "poll interval"
        )
        if type(stable_reads) is not int or stable_reads < 1:
            raise ValueError("X3 stable read count must be a positive integer")
        self.stable_reads = stable_reads
        self._monotonic = monotonic
        self._operation_lock = threading.RLock()
        self._job_lock = threading.Lock()
        self._cancel_event = threading.Event()
        self._job: tuple[Callable[..., Any], tuple[Any, ...]] | None = None

    @property
    def connected(self) -> bool:
        return self.hardware.connected

    def connect(self, address: str) -> bool:
        with self._operation_lock:
            result = self.hardware.connect(address)
            try:
                actual = self.hardware.read_actual_wavelength()
                status = self.hardware.read_status()
            except Exception:
                self.hardware.disconnect()
                raise
        self.sig_connected.emit(True)
        self.sig_actual_wavelength.emit(actual)
        self.sig_status_word.emit(status)
        self.sig_message.emit(f"connected to {address}; laser and shutter unchanged")
        return result

    def disconnect(self) -> None:
        with self._operation_lock:
            self.hardware.disconnect()
        self.sig_connected.emit(False)
        self.sig_target_wavelength.emit(None)
        self.sig_actual_wavelength.emit(None)
        self.sig_status_word.emit(None)
        self.sig_power_w.emit(None)
        self.sig_message.emit("disconnected; laser and shutter unchanged")

    def set_wavelength_stable(self, wavelength_nm):
        """Set a scan point and wait for confirmed actual wavelength in nm."""
        target = self.hardware.validate_wavelength(wavelength_nm)
        with self._operation_lock:
            self._require_connected()
            self._raise_if_cancelled()
            status = self.hardware.read_status()
            self.sig_status_word.emit(status)
            self._require_no_fault(status)
            current = self.hardware.read_actual_wavelength()
            self.sig_actual_wavelength.emit(current)
            deadline = self._monotonic() + self.move_timeout_s
            self.hardware.command_wavelength(target)
            self.sig_message.emit(f"waiting for {target} nm actual wavelength")

            # A successful serial write is not proof that the controller
            # accepted the requested target. Do not retry an uncertain write.
            while True:
                self._raise_if_cancelled()
                reported_target = self.hardware.read_target_wavelength()
                self.sig_target_wavelength.emit(reported_target)
                if reported_target == target:
                    break
                self._check_deadline(deadline, target, current, "accept target")
                self._wait_or_cancel()

            consecutive = 0
            while True:
                self._raise_if_cancelled()
                status = self.hardware.read_status()
                self.sig_status_word.emit(status)
                self._require_no_fault(status)
                actual = self.hardware.read_actual_wavelength()
                self.sig_actual_wavelength.emit(actual)
                current = actual
                consecutive = consecutive + 1 if actual == target else 0
                if consecutive >= self.stable_reads:
                    self.sig_message.emit(f"actual wavelength settled at {actual} nm")
                    return actual
                self._check_deadline(deadline, target, current, "reach target")
                self._wait_or_cancel()

    def get_wavelength_stable(self):
        """Scan getter: actual, not merely requested, wavelength (nm)."""
        with self._operation_lock:
            self._require_connected()
            actual = self.hardware.read_actual_wavelength()
        self.sig_actual_wavelength.emit(actual)
        return actual

    def set_shutter(self, state):
        """Scan setter: 0 closes, 1 opens; confirm the sensed status bit."""
        target = self.hardware.validate_shutter(state)
        with self._operation_lock:
            self._require_connected()
            if target == 1:
                self._raise_if_cancelled("shutter opening")
            status = self.hardware.read_status()
            self.sig_status_word.emit(status)
            if target == 1:
                self._require_no_fault(status)
                if not status.emission:
                    raise RuntimeError(
                        "X3 diode is off; shutter-open command was not sent"
                    )
            deadline = self._monotonic() + 10.0
            self.hardware.command_shutter(target)
            try:
                reported = self.hardware.read_commanded_shutter()
            except Exception as exc:
                raise X3ProtocolError(
                    f"X3 shutter {target} command was sent, but its acceptance "
                    "and actual state are uncertain"
                ) from exc
            if reported != target:
                raise X3ProtocolError(
                    f"X3 did not accept shutter target {target}; "
                    f"controller reported {reported}; actual state is uncertain"
                )
            consecutive = 0
            while True:
                if target == 1:
                    self._raise_if_cancelled("shutter opening")
                status = self.hardware.read_status()
                self.sig_status_word.emit(status)
                if target == 1:
                    self._require_no_fault(status)
                consecutive = consecutive + 1 if int(status.shutter_open) == target else 0
                if consecutive >= 2:
                    self.sig_message.emit(
                        "tunable shutter confirmed " + ("open" if target else "closed")
                    )
                    return target
                if self._monotonic() >= deadline:
                    raise X3MoveTimeout(
                        f"X3 shutter did not confirm {target} within 10 s; "
                        "actual shutter state is uncertain"
                    )
                if target == 1:
                    self._wait_or_cancel("shutter opening")
                else:
                    time.sleep(self.poll_interval_s)

    def panel_set_shutter(self, state):
        """A new explicit panel action may follow a cancelled scan."""
        with self._operation_lock:
            self._cancel_event.clear()
            return self.set_shutter(state)

    def get_shutter(self):
        """Scan getter: sensed tunable shutter position, not last command."""
        status = self.read_status()
        return int(status.shutter_open)

    def turn_diode_on(self) -> bool:
        """Panel-only action; GUI hold confirmation is handled by the widget."""
        with self._operation_lock:
            self._cancel_event.clear()
            self._require_connected()
            status = self.hardware.read_status()
            self.sig_status_word.emit(status)
            self._require_no_fault(status)
            if status.emission:
                return True
            warmup = self.hardware.read_warmup_percent()
            self.sig_warmup_percent.emit(warmup)
            if warmup < 100:
                raise RuntimeError(
                    f"X3 warm-up is {warmup:g}%; diode ON was not sent"
                )
            self.hardware.command_diode_on()
            self._wait_for_emission(True, 120.0)
        self.sig_message.emit("diode energized; shutter was not opened by ZMeter")
        return True

    def turn_diode_off(self) -> bool:
        with self._operation_lock:
            self._require_connected()
            self.hardware.command_diode_off()
            self._wait_for_emission(False, 30.0)
        self.sig_message.emit(
            "diode off; the controller closes the shutter when OFF is issued"
        )
        return True

    def select_mode(self, mode: str) -> str:
        """Panel-only Run/Align selection; never a scan setter."""
        selected = self.hardware.validate_mode(mode)
        with self._operation_lock:
            self._cancel_event.clear()
            self._require_connected()
            status = self.hardware.read_status()
            self.sig_status_word.emit(status)
            self._require_no_fault(status)
            self.hardware.command_mode(selected)
            deadline = self._monotonic() + 30.0
            while True:
                self._raise_if_cancelled("mode selection")
                reported = self.hardware.read_mode()
                self.sig_mode.emit(reported)
                if reported == selected:
                    self.sig_message.emit(f"controller mode confirmed {selected}")
                    return reported
                if self._monotonic() >= deadline:
                    raise X3MoveTimeout(
                        f"X3 did not confirm {selected} mode within 30 s"
                    )
                self._wait_or_cancel("mode selection")

    def read_mode(self) -> str:
        with self._operation_lock:
            self._require_connected()
            mode = self.hardware.read_mode()
        self.sig_mode.emit(mode)
        return mode

    def get_target_wavelength(self):
        with self._operation_lock:
            self._require_connected()
            target = self.hardware.read_target_wavelength()
        self.sig_target_wavelength.emit(target)
        return target

    def get_output_power_w(self):
        """Read-only scan/panel channel; the hardware serial lock owns I/O.

        This query may run during a wavelength wait so the panel can show
        changing power without issuing another wavelength command.
        """
        power = self.hardware.read_power_w()
        self.sig_power_w.emit(power)
        return power

    def read_status(self) -> X3Status:
        with self._operation_lock:
            self._require_connected()
            status = self.hardware.read_status()
        self.sig_status_word.emit(status)
        return status

    def read_diagnostics(self) -> None:
        with self._operation_lock:
            self._require_connected()
            status = self.hardware.read_status()
            humidity = self.hardware.read_humidity_percent()
            motor = self.hardware.read_motor_position_percent()
            temperature = self.hardware.read_diode_temperature_c()
            current = self.hardware.read_diode_current_a()
            hours = self.hardware.read_diode_hours()
            warmup = self.hardware.read_warmup_percent()
            mode = self.hardware.read_mode()
        self.sig_status_word.emit(status)
        self.sig_humidity_percent.emit(humidity)
        self.sig_motor_position_percent.emit(motor)
        self.sig_diode_temperature_c.emit(temperature)
        self.sig_diode_current_a.emit(current)
        self.sig_diode_hours.emit(hours)
        self.sig_warmup_percent.emit(warmup)
        self.sig_mode.emit(mode)

    def read_identity(self) -> str | None:
        with self._operation_lock:
            self._require_connected()
            identity = self.hardware.read_identity()
        self.sig_identity.emit(identity)
        return identity

    def submit_ui_job(self, operation: Callable[..., Any], *args: Any) -> bool:
        with self._job_lock:
            if self.isRunning() or self._job is not None:
                self.sig_error.emit("X3 panel is busy")
                return False
            self._job = (operation, args)
            self.start()
            return True

    def stop_scan(self) -> None:
        """No monitor or laser/shutter action is needed at scan start."""

    def start_scan(self) -> None:
        """Clear a previous ZMeter stop after scan cleanup."""
        self._cancel_event.clear()

    def force_stop(self) -> bool:
        """Interrupt wavelength waiting; never issue a laser/shutter command."""
        self._cancel_event.set()
        self.sig_message.emit(
            "ZMeter stop requested; laser emission and shutter were not changed"
        )
        return True

    def terminate_dev(self, wait_ms: int = 3_000) -> bool:
        self._cancel_event.set()
        if self.isRunning() and not self.wait(wait_ms):
            return False
        if not self._operation_lock.acquire(timeout=wait_ms / 1_000):
            return False
        try:
            self.hardware.disconnect()
        finally:
            self._operation_lock.release()
        self.sig_connected.emit(False)
        return True

    def run(self) -> None:
        with self._job_lock:
            job = self._job
        if job is None:
            return
        try:
            operation, args = job
            operation(*args)
        except Exception as exc:
            self.sig_error.emit(str(exc))
        finally:
            with self._job_lock:
                self._job = None

    def _check_deadline(
        self,
        deadline: float,
        target: int,
        last_actual: int,
        action: str,
    ) -> None:
        if self._monotonic() >= deadline:
            raise X3MoveTimeout(
                f"X3 did not {action} {target} nm within "
                f"{self.move_timeout_s:g} s; last actual wavelength was "
                f"{last_actual} nm. Laser and shutter were not changed by ZMeter."
            )

    def _wait_or_cancel(self, operation: str = "wavelength tuning") -> None:
        if self._cancel_event.wait(self.poll_interval_s):
            self._raise_if_cancelled(operation)

    def _wait_for_emission(self, expected: bool, timeout_s: float) -> None:
        deadline = self._monotonic() + timeout_s
        while True:
            if expected:
                self._raise_if_cancelled("diode ON confirmation")
            status = self.hardware.read_status()
            self.sig_status_word.emit(status)
            if status.emission == expected and (expected or not status.shutter_open):
                return
            if self._monotonic() >= deadline:
                raise X3MoveTimeout(
                    f"X3 did not confirm diode {'on' if expected else 'off'} "
                    f"within {timeout_s:g} s; actual state is uncertain"
                )
            if expected:
                self._wait_or_cancel("diode ON confirmation")
            else:
                time.sleep(self.poll_interval_s)

    def _raise_if_cancelled(self, operation: str = "wavelength tuning") -> None:
        if self._cancel_event.is_set():
            raise X3OperationCancelled(
                f"X3 {operation} confirmation cancelled; commanded state may "
                "already have changed; read the controller status. "
                "ZMeter stop does not send laser OFF or shutter CLOSE"
            )

    @staticmethod
    def _require_no_fault(status: X3Status) -> None:
        if status.fault or status.interlock_open:
            raise RuntimeError(
                f"X3 fault/interlock reported by status word {status.word}; "
                "wavelength operation stopped"
            )

    def _require_connected(self) -> None:
        if not self.connected:
            raise X3ConnectionError(
                "X3 is not connected; enter a COM port and connect first"
            )

    @staticmethod
    def _positive_finite(value: object, label: str) -> float:
        try:
            converted = float(value)
        except (TypeError, ValueError) as exc:
            raise TypeError(f"X3 {label} must be numeric") from exc
        if not math.isfinite(converted) or converted <= 0:
            raise ValueError(f"X3 {label} must be positive and finite")
        return converted
