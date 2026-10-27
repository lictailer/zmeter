import math
from threading import Event, Lock
import time

from PyQt6 import QtCore

from .sr860_hardware import SR860_Hardware
from core.shared_runtime.visa import VisaRuntime


class SR860RampAbortedError(RuntimeError):
    """Raised after a ramp stops at its last successfully written waypoint."""


class SR860_Logic(QtCore.QThread):
    """Qt thread-wrapper that exposes **all** SR860_Hardware methods via signals.

    Naming rules (enforced project-wide):
    1. get_xxx   – purely read access; proxies <hardware>.xxx(read=True) or <hardware>.get_xxx().
    2. set_xxx  – write / set access; proxies <hardware>.xxx(write=True) or <hardware>.set_xxx().
    3. setup_xxx  – boolean two-state helpers (ON / OFF like auto_range, sync_filter …).
    4. get_xxx    - get_X, get_Y, get_R, get_Theta and get_aux_in to be used as getters in scan control.

    The QThread processes queued jobs.  The *job* string **must exactly match** the wrapper
    method name so the dispatcher can automatically call it.
    """

    # Read-only getters recorded by setup capture at scan start and end.
    # Labs can add or remove names in lab_context/snapshot_channels.json.
    SNAPSHOT_GETTERS = (
        "frequency",
        "amplitude",
        "time_constant",
        "sensitivity",
        "phase",
        "ref_mode",
        "ext_trigger",
        "ref_input",
        "sync_filter",
        "harmonic",
        "input_config",
        "voltage_input_coupling",
        "voltage_input_range",
        "current_input_range",
        "input_shield",
        "notch_filter",
        "dc_level",
        "dc_level_mode",
        "filter_slope",
    )

    # ---------- value update signals ----------
    sig_frequency = QtCore.pyqtSignal(object)
    sig_amplitude = QtCore.pyqtSignal(object)
    sig_time_constant = QtCore.pyqtSignal(object)
    sig_sensitivity = QtCore.pyqtSignal(object)
    sig_phase = QtCore.pyqtSignal(object)
    sig_ref_mode = QtCore.pyqtSignal(object)
    sig_ext_trigger = QtCore.pyqtSignal(object)
    sig_ref_input = QtCore.pyqtSignal(object)
    sig_sync_filter = QtCore.pyqtSignal(object)
    sig_harmonic = QtCore.pyqtSignal(object)
    sig_signal_input_type = QtCore.pyqtSignal(object)
    sig_signal_input_mode = QtCore.pyqtSignal(object)
    sig_input_config = QtCore.pyqtSignal(object)
    sig_voltage_input_coupling = QtCore.pyqtSignal(object)
    sig_voltage_input_range = QtCore.pyqtSignal(object)
    sig_current_input_range = QtCore.pyqtSignal(object)
    sig_input_shield = QtCore.pyqtSignal(object)
    sig_dc_level = QtCore.pyqtSignal(object)
    sig_dc_level_mode = QtCore.pyqtSignal(object)
    sig_filter_slope = QtCore.pyqtSignal(object)

    sig_X = QtCore.pyqtSignal(object)
    sig_Y = QtCore.pyqtSignal(object)
    sig_R = QtCore.pyqtSignal(object)
    sig_Theta = QtCore.pyqtSignal(object)

    sig_display = QtCore.pyqtSignal(object)
    sig_aux_out = QtCore.pyqtSignal(object)        # (chan, value)
    sig_aux_in = QtCore.pyqtSignal(object)         # (chan, value)
    sig_unlocked = QtCore.pyqtSignal(object)
    sig_input_overload = QtCore.pyqtSignal(object)
    sig_sensitivity_overload = QtCore.pyqtSignal(object)
    sig_multiple_outputs = QtCore.pyqtSignal(object)

    # ---------- generic state signals ----------
    sig_is_changing = QtCore.pyqtSignal(object)
    sig_connected = QtCore.pyqtSignal(object)
    sig_log = QtCore.pyqtSignal(object)

    AMPLITUDE_MIN_V = 0.0
    AMPLITUDE_MAX_V = 2.0
    DC_LEVEL_MIN_MV = -5000.0
    DC_LEVEL_MAX_MV = 5000.0
    COMBINED_OUTPUT_LIMIT_V = 6.0
    AMPLITUDE_RAMP_RATE_MIN_V_PER_S = 0.001
    AMPLITUDE_RAMP_RATE_MAX_V_PER_S = 2.0
    DC_RAMP_RATE_MIN_MV_PER_S = 5.0
    DC_RAMP_RATE_MAX_MV_PER_S = 5000.0
    RAMP_UPDATE_HZ = 20.0
    MAX_RAMP_DURATION_S = 3600.0
    RAMP_TIMEOUT_MIN_MARGIN_S = 30.0
    ENDPOINT_CONFIRM_TIMEOUT_S = 1.0
    ENDPOINT_CONFIRM_POLL_S = 0.05

    # -------------------------------------------
    def __init__(self, visa_runtime: VisaRuntime | None = None):
        super().__init__()

        # queued instruction executed in run()
        self.job: str = ""  # name of the next action

        # -------- set-points (set_*) --------
        self.setpoint_frequency = 0.0
        self.setpoint_amplitude = 0.0
        self.setpoint_time_constant = 0
        self.setpoint_sensitivity = 0
        self.setpoint_phase = 0.0
        self.setpoint_ref_mode = "internal"
        self.setpoint_ext_trigger = "sine"
        self.setpoint_ref_input = 0
        self.setpoint_sync_filter = False
        self.setpoint_harmonic = 1
        self.setpoint_input_config = "Voltage: A"
        self.setpoint_signal_input_type = "voltage"
        self.setpoint_signal_input_mode = "A"
        self.setpoint_voltage_input_coupling = "AC"
        self.setpoint_voltage_input_range = "1 V"
        self.setpoint_current_input_range = "1 uA"
        self.setpoint_input_shield = "Float"
        self.setpoint_dc_level = 0.0
        self.setpoint_dc_level_mode = "common"
        self.setpoint_filter_slope = "6 dB/oct"
        self.setpoint_aux_channel = 1
        self.setpoint_aux_voltage = 0.0

        self.setpoint_auto_range = False
        self.setpoint_auto_scale = False
        self.setpoint_auto_phase = False

        # for bulk get_multiple_outputs
        self.setpoint_outputs = ("X", "Y", "R")

        self.monitor_count = 10

        # Session-only ramp configuration. The amplitude channel uses V while
        # the DC-level channel follows the panel convention and uses mV.
        self.amplitude_ramp_rate_v_per_s = 0.1
        self.dc_level_ramp_rate_mv_per_s = 100.0
        self._ramp_stop_event = Event()
        self._ramp_lock = Lock()
        self._ramp_active = False
        self._active_ramp_channel: str | None = None
        self._ramp_stop_reason: str | None = None
        self._monotonic = time.monotonic

        # runtime state
        self.connected = False
        self.reject_signal = False

        self.hardware: SR860_Hardware | None = None
        self.visa_runtime = visa_runtime or VisaRuntime()

    def _emit_log(self, message: str, level: str = "INFO"):
        self.sig_log.emit((level, str(message)))

    @staticmethod
    def _validated_finite_value(name, value, low, high):
        if isinstance(value, bool):
            raise ValueError(f"{name} must be numeric")
        try:
            numeric_value = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not math.isfinite(numeric_value):
            raise ValueError(f"{name} must be finite")
        if not low <= numeric_value <= high:
            raise ValueError(f"{name} must be between {low} and {high}")
        return numeric_value

    def configure_amplitude_ramp_rate(self, value):
        self.amplitude_ramp_rate_v_per_s = self._validated_finite_value(
            "amplitude ramp rate (V/s)",
            value,
            self.AMPLITUDE_RAMP_RATE_MIN_V_PER_S,
            self.AMPLITUDE_RAMP_RATE_MAX_V_PER_S,
        )
        return self.amplitude_ramp_rate_v_per_s

    def configure_dc_ramp_rate(self, value):
        self.dc_level_ramp_rate_mv_per_s = self._validated_finite_value(
            "DC ramp rate (mV/s)",
            value,
            self.DC_RAMP_RATE_MIN_MV_PER_S,
            self.DC_RAMP_RATE_MAX_MV_PER_S,
        )
        return self.dc_level_ramp_rate_mv_per_s

    def _validate_combined_output(self, amplitude_v, dc_level_mv):
        amplitude = self._validated_finite_value(
            "amplitude", amplitude_v, self.AMPLITUDE_MIN_V, self.AMPLITUDE_MAX_V
        )
        dc_level = self._validated_finite_value(
            "DC level", dc_level_mv, self.DC_LEVEL_MIN_MV, self.DC_LEVEL_MAX_MV
        )
        combined_peak_v = abs(dc_level) / 1000.0 + math.sqrt(2.0) * amplitude
        if combined_peak_v > self.COMBINED_OUTPUT_LIMIT_V:
            raise ValueError(
                "SR860 output limit exceeded: |DC offset| + sqrt(2) * "
                f"amplitude is {combined_peak_v:g} V; maximum is "
                f"{self.COMBINED_OUTPUT_LIMIT_V:g} V"
            )

    @staticmethod
    def _readback_matches_programmed_value(
        requested_value,
        actual_value,
        minimum_resolution,
    ):
        """Match the SR860's documented three-significant-digit rounding."""
        magnitude = abs(requested_value)
        significant_resolution = 0.0
        if magnitude > 0.0:
            significant_resolution = 10.0 ** (
                math.floor(math.log10(magnitude)) - 2
            )
        resolution = max(minimum_resolution, significant_resolution)
        tolerance = resolution / 2.0 + 1e-12 * max(
            1.0, magnitude, abs(actual_value)
        )
        return abs(actual_value - requested_value) <= tolerance

    @property
    def ramp_active(self):
        return self._ramp_active

    @property
    def active_ramp_channel(self):
        return self._active_ramp_channel

    def request_force_stop(self, reason="external force-stop"):
        self._ramp_stop_reason = str(reason)
        self._ramp_stop_event.set()
        if self._ramp_lock.locked() or self._ramp_active:
            self._emit_log(
                f"Stop requested for SR860 "
                f"{self._active_ramp_channel or 'output'} ramp "
                f"({self._ramp_stop_reason}).",
                level="WARN",
            )

    def _ramp_abort_message(self, channel, current_value, unit):
        reason = self._ramp_stop_reason or "unknown source"
        return (
            f"{channel} ramp stopped at {current_value:g} {unit} "
            f"(requested by {reason})"
        )

    def prepare_for_scan(self):
        if self._ramp_lock.locked() or self._ramp_active:
            raise RuntimeError(
                f"SR860 {self._active_ramp_channel or 'output'} ramp is already active"
            )
        self._ramp_stop_event.clear()
        self._ramp_stop_reason = None

    def prepare_for_manual_ramp(self):
        self.prepare_for_scan()

    def _ramp_output(
        self,
        *,
        channel,
        target,
        rate,
        rate_low,
        rate_high,
        low,
        high,
        unit,
        minimum_readback_resolution,
        read_current,
        program_and_readback,
        state_attribute,
        signal,
    ):
        target_value = self._validated_finite_value(channel, target, low, high)
        rate_value = self._validated_finite_value(
            f"{channel} ramp rate ({unit}/s)",
            rate,
            rate_low,
            rate_high,
        )

        with self._ramp_lock:
            if self._ramp_stop_event.is_set():
                raise SR860RampAbortedError(
                    f"{channel} ramp refused because force-stop is set "
                    f"({self._ramp_stop_reason or 'unknown source'})"
                )

            start_value = self._validated_finite_value(
                f"current {channel}", read_current(), low, high
            )
            setattr(self, state_attribute, start_value)
            signal.emit(start_value)

            delta = target_value - start_value
            if math.isclose(delta, 0.0, abs_tol=1e-12):
                return start_value

            planned_duration = abs(delta) / rate_value
            if planned_duration > self.MAX_RAMP_DURATION_S:
                raise ValueError(
                    f"{channel} ramp would take {planned_duration:.1f} s; "
                    f"maximum is {self.MAX_RAMP_DURATION_S:.0f} s"
                )

            direction = 1.0 if delta > 0.0 else -1.0
            update_interval = 1.0 / self.RAMP_UPDATE_HZ
            ramp_started_at = self._monotonic()
            planned_end_at = ramp_started_at + planned_duration
            timeout_margin = max(
                self.RAMP_TIMEOUT_MIN_MARGIN_S, planned_duration
            )
            deadline = planned_end_at + timeout_margin
            next_update_at = min(
                ramp_started_at + update_interval, planned_end_at
            )
            current_value = start_value
            last_known_output = start_value
            last_programmed_readback = None
            self._ramp_active = True
            self._active_ramp_channel = channel
            self._emit_log(
                f"Starting {channel} ramp from {start_value:g} to "
                f"{target_value:g} {unit} at {rate_value:g} {unit}/s.",
                level="INFO",
            )

            try:
                while not math.isclose(
                    current_value, target_value, abs_tol=1e-12
                ):
                    if self._ramp_stop_event.is_set():
                        raise SR860RampAbortedError(
                            self._ramp_abort_message(
                                channel, last_known_output, unit
                            )
                        )
                    now = self._monotonic()
                    if now >= deadline:
                        raise TimeoutError(
                            f"{channel} ramp timed out at "
                            f"{current_value:g} {unit}"
                        )

                    wait_time = max(0.0, next_update_at - now)
                    if self._ramp_stop_event.wait(wait_time):
                        raise SR860RampAbortedError(
                            self._ramp_abort_message(
                                channel, last_known_output, unit
                            )
                        )
                    now = self._monotonic()
                    if now >= deadline:
                        raise TimeoutError(
                            f"{channel} ramp timed out at "
                            f"{current_value:g} {unit}"
                        )

                    elapsed = min(
                        max(0.0, now - ramp_started_at), planned_duration
                    )
                    travelled = min(abs(delta), rate_value * elapsed)
                    next_value = start_value + direction * travelled
                    if math.isclose(
                        elapsed, planned_duration, abs_tol=1e-12
                    ):
                        next_value = target_value

                    programmed_readback = self._validated_finite_value(
                        f"programmed {channel}",
                        program_and_readback(next_value),
                        low,
                        high,
                    )
                    current_value = next_value
                    last_known_output = programmed_readback
                    last_programmed_readback = programmed_readback
                    setattr(self, state_attribute, programmed_readback)
                    signal.emit(programmed_readback)

                    is_final_waypoint = math.isclose(
                        current_value, target_value, abs_tol=1e-12
                    )
                    if (
                        not is_final_waypoint
                        and not self._readback_matches_programmed_value(
                            next_value,
                            programmed_readback,
                            minimum_readback_resolution,
                        )
                    ):
                        raise RuntimeError(
                            f"{channel} waypoint mismatch: requested "
                            f"{next_value:g} {unit}, read back "
                            f"{programmed_readback:g} {unit}"
                        )

                    if is_final_waypoint:
                        break
                    next_update_at = min(
                        self._monotonic() + update_interval,
                        planned_end_at,
                    )

                confirmation_deadline = (
                    self._monotonic() + self.ENDPOINT_CONFIRM_TIMEOUT_S
                )
                confirmed_value = last_programmed_readback
                while True:
                    if confirmed_value is None:
                        confirmed_value = self._validated_finite_value(
                            f"confirmed {channel}", read_current(), low, high
                        )
                        last_known_output = confirmed_value
                        setattr(self, state_attribute, confirmed_value)
                        signal.emit(confirmed_value)
                    if self._readback_matches_programmed_value(
                        target_value,
                        confirmed_value,
                        minimum_readback_resolution,
                    ):
                        break

                    confirmation_remaining = (
                        confirmation_deadline - self._monotonic()
                    )
                    if confirmation_remaining <= 0.0:
                        raise RuntimeError(
                            f"{channel} endpoint mismatch after "
                            f"{self.ENDPOINT_CONFIRM_TIMEOUT_S:g} s: requested "
                            f"{target_value:g} {unit}, last readback "
                            f"{confirmed_value:g} {unit}"
                        )
                    if self._ramp_stop_event.wait(
                        min(
                            self.ENDPOINT_CONFIRM_POLL_S,
                            confirmation_remaining,
                        )
                    ):
                        raise SR860RampAbortedError(
                            self._ramp_abort_message(
                                channel, last_known_output, unit
                            )
                        )
                    confirmed_value = None

                self._emit_log(
                    f"Completed {channel} ramp at confirmed readback "
                    f"{confirmed_value:g} {unit}.",
                    level="INFO",
                )
                return confirmed_value
            except Exception as exc:
                self._emit_log(
                    f"{channel} ramp ended with last known output "
                    f"{last_known_output:g} {unit}: {exc}",
                    level=(
                        "WARN"
                        if isinstance(exc, SR860RampAbortedError)
                        else "ERROR"
                    ),
                )
                raise
            finally:
                self._ramp_active = False
                self._active_ramp_channel = None

    def _cleanup_connection(self):
        if self.hardware is None:
            return
        try:
            self.hardware.disconnect()
        except Exception as exc:
            self._emit_log(f"Error during hardware.disconnect(): {exc}", level="WARN")
        finally:
            self.hardware = None

    # -------------- connection helpers ----------------
    def connect_visa(self, address: str):
        """Instantiate SR860_Hardware, validate IDN, and mark connected."""
        self.reject_signal = True
        self.job = ""
        if self.isRunning():
            self.wait()
        self.reject_signal = False

        self.connected = False
        self._cleanup_connection()

        temp_hardware: SR860_Hardware | None = None
        try:
            temp_hardware = SR860_Hardware(
                address, visa_runtime=self.visa_runtime
            )
            idn = temp_hardware.idn()
            if not idn:
                raise RuntimeError("No response to *IDN? query.")
            if "SR860" not in idn.upper():
                raise ValueError(f"Unexpected instrument identity: {idn}")

            self.hardware = temp_hardware
            self.connected = True
            self._ramp_stop_event.clear()
            self._ramp_stop_reason = None
            self.sig_connected.emit(f"connected to {address}")
            self._emit_log(f"Connected to {address}: {idn}", level="INFO")
            return True
        except Exception as exc:
            if temp_hardware is not None:
                try:
                    temp_hardware.disconnect()
                except Exception:
                    pass
            self.hardware = None
            self.connected = False
            self.sig_connected.emit("connection failed")
            self._emit_log(f"Connection failed for {address}: {exc}", level="ERROR")
            return False

    # -------------- get wrappers ---------------------
    def get_frequency(self):
        assert self.hardware is not None
        val = self.hardware.get_frequency()
        self.sig_frequency.emit(val)
        return val

    def get_amplitude(self):
        assert self.hardware is not None
        val = self.hardware.get_amplitude()
        self.sig_amplitude.emit(val)
        return val

    def get_time_constant(self):
        assert self.hardware is not None
        val = self.hardware.time_constant(read=True)
        self.sig_time_constant.emit(val)
        return val

    def get_sensitivity(self):
        assert self.hardware is not None
        val = self.hardware.sensitivity(read=True)
        self.sig_sensitivity.emit(val)
        return val

    def get_phase(self):
        assert self.hardware is not None
        val = self.hardware.phase(read=True)
        self.sig_phase.emit(val)
        return val

    def get_ref_mode(self):
        assert self.hardware is not None
        val = self.hardware.ref_mode(read=True)
        self.sig_ref_mode.emit(val)
        return val

    def get_ext_trigger(self):
        assert self.hardware is not None
        val = self.hardware.ext_trigger(read=True)
        self.sig_ext_trigger.emit(val)
        return val

    def get_ref_input(self):
        assert self.hardware is not None
        val = self.hardware.ref_input(read=True)
        self.sig_ref_input.emit(val)
        return val

    def get_sync_filter(self):
        assert self.hardware is not None
        val = self.hardware.sync_filter(read=True)
        self.sig_sync_filter.emit(val)
        return val

    def get_harmonic(self):
        assert self.hardware is not None
        val = self.hardware.harmonic(read=True)
        self.sig_harmonic.emit(val)
        return val

    def get_signal_input_type(self):
        assert self.hardware is not None
        val = self.hardware.signal_input_type(read=True)
        self.sig_signal_input_type.emit(val)
        return val

    def get_signal_input_mode(self):
        assert self.hardware is not None
        val = self.hardware.signal_input_mode(read=True)
        self.sig_signal_input_mode.emit(val)
        return val

    def get_input_config(self):
        assert self.hardware is not None
        input_type = self.hardware.signal_input_type(read=True)
        input_mode = self.hardware.signal_input_mode(read=True)
        if input_type == "voltage":
            val = f"Voltage: {input_mode}"
        elif input_type == "current":
            val = f"Current"
        else:
            raise ValueError(f"Invalid signal input type: {input_type}")
        self.sig_input_config.emit(val)
        return val

    def get_voltage_input_coupling(self):
        assert self.hardware is not None
        val = self.hardware.voltage_input_coupling(read=True)
        self.sig_voltage_input_coupling.emit(val)
        return val

    def get_voltage_input_range(self):
        assert self.hardware is not None
        val = self.hardware.voltage_input_range(read=True)
        self.sig_voltage_input_range.emit(val)
        return val

    def get_current_input_range(self):
        assert self.hardware is not None
        val = self.hardware.current_input_range(read=True)
        self.sig_current_input_range.emit(val)
        return val

    def get_multiple_outputs(self):
        assert self.hardware is not None
        val = self.hardware.get_multiple_outputs(*self.setpoint_outputs)
        self.sig_multiple_outputs.emit(val)
        return val

    def get_display(self):
        assert self.hardware is not None
        val = self.hardware.get_display()
        self.sig_display.emit(val)
        return val

    def get_aux_out(self):
        assert self.hardware is not None
        val = self.hardware.get_aux_out(self.setpoint_aux_channel)
        self.sig_aux_out.emit((self.setpoint_aux_channel, val))
        return val

    def get_unlocked(self):
        assert self.hardware is not None
        val = self.hardware.unlocked()
        self.sig_unlocked.emit(val)
        return val

    def get_input_overload(self):
        assert self.hardware is not None
        val = self.hardware.input_overload()
        self.sig_input_overload.emit(val)
        return val

    def get_sensitivity_overload(self):
        assert self.hardware is not None
        val = self.hardware.sensitivity_overload()
        self.sig_sensitivity_overload.emit(val)
        return val

    def get_input_shield(self):
        assert self.hardware is not None
        val = self.hardware.input_shield(read=True)
        self.sig_input_shield.emit(val)
        return val

    def get_notch_filter(self):
        assert self.hardware is not None
        val = self.hardware.notch_filter(read=True)
        self.sig_notch_filter.emit(val)
        return val
    
    def get_dc_level(self):
        assert self.hardware is not None
        # The SR860 query reports volts; ZMeter's DC-level channel and panel
        # deliberately use millivolts for both reads and writes.
        val = self.hardware.dc_level(read=True) * 1000.0
        self.sig_dc_level.emit(val)
        return val

    def refresh_output_levels(self):
        """Read both source outputs without exposing a compound scan channel."""
        return self.get_amplitude(), self.get_dc_level()
    
    def get_dc_level_mode(self):   
        assert self.hardware is not None
        val = self.hardware.dc_level_mode(read=True)
        self.sig_dc_level_mode.emit(val)
        return val

    def get_filter_slope(self):
        assert self.hardware is not None
        val = self.hardware.filter_slope(read=True)
        self.sig_filter_slope.emit(val)
        return val

    # ----- special getters that keep original names -----
    def get_X(self):
        assert self.hardware is not None
        val = self.hardware.get_X()
        self.sig_X.emit(val)
        return val

    def get_Y(self):
        assert self.hardware is not None
        val = self.hardware.get_Y()
        self.sig_Y.emit(val)
        return val

    def get_R(self):
        assert self.hardware is not None
        val = self.hardware.get_R()
        self.sig_R.emit(val)
        return val

    def get_Theta(self):
        assert self.hardware is not None
        val = self.hardware.get_Theta()
        self.sig_Theta.emit(val)
        return val

    def get_aux_in(self):
        assert self.hardware is not None
        val = self.hardware.get_aux_in(self.setpoint_aux_channel)
        self.sig_aux_in.emit((self.setpoint_aux_channel, val))
        return val

    # -------------- setters ---------------------
    def set_amplitude(self, val=None):
        assert self.hardware is not None
        target = self.setpoint_amplitude if val is None else val
        target = self._validated_finite_value(
            "amplitude", target, self.AMPLITUDE_MIN_V, self.AMPLITUDE_MAX_V
        )
        dc_level_mv = self.hardware.dc_level(read=True) * 1000.0
        self._validate_combined_output(target, dc_level_mv)
        completed_value = self._ramp_output(
            channel="amplitude",
            target=target,
            rate=self.amplitude_ramp_rate_v_per_s,
            rate_low=self.AMPLITUDE_RAMP_RATE_MIN_V_PER_S,
            rate_high=self.AMPLITUDE_RAMP_RATE_MAX_V_PER_S,
            low=self.AMPLITUDE_MIN_V,
            high=self.AMPLITUDE_MAX_V,
            unit="V",
            minimum_readback_resolution=1e-9,
            read_current=self.hardware.get_amplitude,
            program_and_readback=self.hardware.program_amplitude_and_readback,
            state_attribute="setpoint_amplitude",
            signal=self.sig_amplitude,
        )
        self.sig_is_changing.emit(f"amplitude set to {completed_value}")
        return completed_value


    # -------------- set wrappers ---------------------
    def set_frequency(self):
        assert self.hardware is not None
        self.hardware.set_frequency(self.setpoint_frequency)
        self.sig_is_changing.emit(f"frequency set to {self.setpoint_frequency}")
        self.sig_frequency.emit(self.setpoint_frequency)

    def set_time_constant(self):
        assert self.hardware is not None
        self.hardware.time_constant(self.setpoint_time_constant, write=True)
        self.sig_is_changing.emit(f"time_constant set to {self.setpoint_time_constant}")
        self.sig_time_constant.emit(self.setpoint_time_constant)

    def set_sensitivity(self):
        assert self.hardware is not None
        self.hardware.sensitivity(self.setpoint_sensitivity, write=True)
        self.sig_is_changing.emit(f"sensitivity set to {self.setpoint_sensitivity}")
        self.sig_sensitivity.emit(self.setpoint_sensitivity)

    def set_phase(self):
        assert self.hardware is not None
        self.hardware.phase(self.setpoint_phase, write=True)
        self.sig_is_changing.emit(f"phase set to {self.setpoint_phase}")
        self.sig_phase.emit(self.setpoint_phase)

    def set_ref_mode(self):
        assert self.hardware is not None
        self.hardware.ref_mode(self.setpoint_ref_mode, write=True)
        self.sig_is_changing.emit(f"ref_mode set to {self.setpoint_ref_mode}")
        self.sig_ref_mode.emit(self.setpoint_ref_mode)

    def set_ext_trigger(self):
        assert self.hardware is not None
        self.hardware.ext_trigger(self.setpoint_ext_trigger, write=True)
        self.sig_is_changing.emit(f"ext_trigger set to {self.setpoint_ext_trigger}")
        self.sig_ext_trigger.emit(self.setpoint_ext_trigger)

    def set_harmonic(self):
        assert self.hardware is not None
        self.hardware.harmonic(self.setpoint_harmonic, write=True)
        self.sig_is_changing.emit(f"harmonic set to {self.setpoint_harmonic}")
        self.sig_harmonic.emit(self.setpoint_harmonic)

    def set_signal_input_type(self):
        assert self.hardware is not None
        self.hardware.signal_input_type(self.setpoint_signal_input_type, write=True)
        self.sig_is_changing.emit(f"signal_input_type set to {self.setpoint_signal_input_type}")
        self.sig_signal_input_type.emit(self.setpoint_signal_input_type)

    def set_signal_input_mode(self):
        assert self.hardware is not None
        self.hardware.signal_input_mode(self.setpoint_signal_input_mode, write=True)
        self.sig_is_changing.emit(f"signal_input_mode set to {self.setpoint_signal_input_mode}")
        self.sig_signal_input_mode.emit(self.setpoint_signal_input_mode)

    def set_signal_input_config(self):
        assert self.hardware is not None
        if self.setpoint_input_config == "Current" or self.setpoint_input_config == 0:
            self.setpoint_signal_input_type = "current"
            self.hardware.signal_input_type(self.setpoint_signal_input_type, write=True)
        elif self.setpoint_input_config == "Voltage: A" or self.setpoint_input_config == 1:
            self.setpoint_signal_input_type = "voltage"
            self.setpoint_signal_input_mode = "A"
            self.hardware.signal_input_type(self.setpoint_signal_input_type, write=True)
            self.hardware.signal_input_mode(self.setpoint_signal_input_mode, write=True)
        elif self.setpoint_input_config == "Voltage: A-B" or self.setpoint_input_config == 2:
            self.setpoint_signal_input_type = "voltage"
            self.setpoint_signal_input_mode = "A-B"
            self.hardware.signal_input_type(self.setpoint_signal_input_type, write=True)
            self.hardware.signal_input_mode(self.setpoint_signal_input_mode, write=True)
        else:
            raise ValueError(f"Invalid signal input config: {self.setpoint_input_config}")

        self.hardware.current_input_range(self.setpoint_current_input_range, write=True)
        self.hardware.voltage_input_range(self.setpoint_voltage_input_range, write=True)

        self.sig_is_changing.emit(f"input_config set to {self.setpoint_input_config}")
        self.sig_input_config.emit(self.setpoint_input_config)
        self.sig_voltage_input_range.emit(self.setpoint_voltage_input_range)
        self.sig_current_input_range.emit(self.setpoint_current_input_range)

    def set_voltage_input_coupling(self):
        assert self.hardware is not None
        self.hardware.voltage_input_coupling(self.setpoint_voltage_input_coupling, write=True)
        self.sig_is_changing.emit(f"voltage_input_coupling set to {self.setpoint_voltage_input_coupling}")
        self.sig_voltage_input_coupling.emit(self.setpoint_voltage_input_coupling)

    def set_voltage_input_range(self):
        assert self.hardware is not None
        self.hardware.voltage_input_range(self.setpoint_voltage_input_range, write=True)
        self.sig_is_changing.emit(f"voltage_input_range set to {self.setpoint_voltage_input_range}")
        self.sig_voltage_input_range.emit(self.setpoint_voltage_input_range)

    def set_aux_out(self):
        assert self.hardware is not None
        self.hardware.set_aux_out(self.setpoint_aux_channel, self.setpoint_aux_voltage)
        self.sig_is_changing.emit(
            f"aux_out[{self.setpoint_aux_channel}] set to {self.setpoint_aux_voltage}")
        self.sig_aux_out.emit((self.setpoint_aux_channel, self.setpoint_aux_voltage))

    def set_input_shield(self):
        assert self.hardware is not None
        self.hardware.input_shield(self.setpoint_input_shield, write=True)
        self.sig_is_changing.emit(f"input_shield set to {self.setpoint_input_shield}")
        self.sig_input_shield.emit(self.setpoint_input_shield)

    def set_dc_level(self, val=None):
        assert self.hardware is not None
        target = self.setpoint_dc_level if val is None else val
        target = self._validated_finite_value(
            "DC level", target, self.DC_LEVEL_MIN_MV, self.DC_LEVEL_MAX_MV
        )
        amplitude_v = self.hardware.get_amplitude()
        self._validate_combined_output(amplitude_v, target)
        completed_value = self._ramp_output(
            channel="dc_level",
            target=target,
            rate=self.dc_level_ramp_rate_mv_per_s,
            rate_low=self.DC_RAMP_RATE_MIN_MV_PER_S,
            rate_high=self.DC_RAMP_RATE_MAX_MV_PER_S,
            low=self.DC_LEVEL_MIN_MV,
            high=self.DC_LEVEL_MAX_MV,
            unit="mV",
            minimum_readback_resolution=0.1,
            read_current=lambda: self.hardware.dc_level(read=True) * 1000.0,
            program_and_readback=self.hardware.program_dc_level_and_readback,
            state_attribute="setpoint_dc_level",
            signal=self.sig_dc_level,
        )
        self.sig_is_changing.emit(f"dc_level set to {completed_value}")
        return completed_value
    
    def set_dc_level_mode(self):
        assert self.hardware is not None
        self.hardware.dc_level_mode(self.setpoint_dc_level_mode, write=True)
        self.sig_is_changing.emit(f"dc_level_mode set to {self.setpoint_dc_level_mode}")
        self.sig_dc_level_mode.emit(self.setpoint_dc_level_mode)

    def set_filter_slope(self):
        assert self.hardware is not None
        self.hardware.filter_slope(self.setpoint_filter_slope, write=True)
        self.sig_is_changing.emit(f"filter_slope set to {self.setpoint_filter_slope}")
        self.sig_filter_slope.emit(self.setpoint_filter_slope)

    def set_ref_input(self):
        assert self.hardware is not None
        self.hardware.ref_input(self.setpoint_ref_input, write=True)
        self.sig_is_changing.emit(f"ref_input set to {self.setpoint_ref_input}")
        self.sig_ref_input.emit(self.setpoint_ref_input)

    def set_sync_filter(self):
        assert self.hardware is not None
        self.hardware.sync_filter(self.setpoint_sync_filter, write=True)
        self.sig_is_changing.emit(f"sync_filter set to {self.setpoint_sync_filter}")
        self.sig_sync_filter.emit(self.setpoint_sync_filter)

    # -------------- auto setting ------------------------
    def set_auto_scale(self):
        assert self.hardware is not None
        self.hardware.set_auto_scale()
        self.sig_is_changing.emit(f"auto_scale set to {self.setpoint_sensitivity}")

    def set_auto_phase(self):
        assert self.hardware is not None
        self.hardware.set_auto_phase()
        self.sig_is_changing.emit(f"auto_phase set to {self.setpoint_phase}")

    def set_auto_range(self):
        assert self.hardware is not None
        self.hardware.set_auto_range()
        self.sig_is_changing.emit(f"auto_range set to {self.setpoint_time_constant}")

    def set_notch_filter(self):
        assert self.hardware is not None
        self.hardware.notch_filter(self.setpoint_notch_filter, write=True)
        self.sig_is_changing.emit(f"notch_filter set to {self.setpoint_notch_filter}")
        self.sig_notch_filter.emit(self.setpoint_notch_filter)

    # -------------- bulk helper ------------------------
    def get_all(self):
        """Read a representative subset of parameters at once."""

        self.get_input_overload()
        self.get_sensitivity_overload()
        self.get_X()
        self.get_Y()
        self.get_R()
        self.get_Theta()

        # --- always refresh current input configuration and ranges ---

        # self.get_display()
        # self.get_unlocked()

        self.monitor_count += 1
        if self.monitor_count >= 10:
            self.get_frequency()
            self.get_amplitude()
            self.get_dc_level()
            self.get_time_constant()
            self.get_sensitivity()
            self.get_phase()
            self.get_ref_mode()
            self.get_ext_trigger()
            self.get_ref_input()
            self.get_sync_filter()
            self.get_harmonic()
            self.get_voltage_input_coupling()
            self.get_input_config()
            self.get_voltage_input_range()
            self.get_current_input_range()
            self.get_input_shield()
            self.monitor_count = 0
        time.sleep(0.05)

    # -------------- disconnect helper ------------------
    def disconnect(self):
        """Safely stop the thread and close the VISA link."""
        self.request_force_stop("device disconnect")
        self.reject_signal = True
        self.job = ""

        if self.isRunning() and not self.wait(5_000):
            raise RuntimeError("SR860 operation did not stop within 5000 ms")

        self._cleanup_connection()

        if self.connected:
            self.connected = False
            self.sig_connected.emit("disconnected")
            self._emit_log("Disconnected SR860.", level="INFO")

        # allow new jobs after a future reconnect
        self.reject_signal = False

    # -------------- thread main ------------------------
    def run(self):
        if self.reject_signal or not self.connected or self.hardware is None:
            return

        # generic dispatcher: call method named in self.job (no args)
        if self.job:
            fn = getattr(self, self.job, None)
            if callable(fn):
                try:
                    fn()
                except SR860RampAbortedError:
                    pass
                except Exception as exc:
                    self._emit_log(f"SR860_Logic job '{self.job}' error: {exc}", level="ERROR")
            else:
                self._emit_log(f"SR860_Logic has no job '{self.job}'", level="WARN")

            # reset marker
            self.job = ""

    # -------------- stop helper ------------------------
    def stop(self):
        self.reject_signal = True
        self.quit()
        self.wait()
        self.reject_signal = False
