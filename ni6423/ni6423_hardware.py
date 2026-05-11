import argparse
import math
import threading
from statistics import fmean
from typing import Dict, Optional

import nidaqmx
from nidaqmx.constants import (
    AcquisitionType,
    CountDirection,
    Edge,
    Level,
    TaskMode,
    TriggerType,
)
from nidaqmx.system import System

class NI6423Hardware:
    """
    Minimal NI USB-6423 hardware layer using nidaqmx.

    Public API:
    1. connect(device_name)
    2. disconnect()
    3. write_analog_output(output_channel, value)
    4. read_analog_input(input_channel, integration_time)
    5. read_sample_counter(integration_time)  # fixed to Ctr0
    6. start_pulse_train(frequency_hz, duty_time_s)  # fixed to Ctr3
    7. stop_pulse_train()
    """

    INTEGRATION_STEP_S = 100e-6
    MIN_INTEGRATION_S = 100e-6
    AO_CHANNEL_COUNT = 4
    AI_SAMPLE_RATE_HZ = 250_000.0  # 10 us sample period
    AI_CHANNEL_COUNT = 32
    COUNTER_TIMEBASE_HZ = 100_000_000.0  # 100 MHz internal timebase
    GATE_LOW_TICKS = 10
    GATE_MIN_HIGH_TICKS = 2

    def __init__(
        self,
        device_name: str = "Dev1",
        ao_min_val: float = -10.0,
        ao_max_val: float = 10.0,
        ai_min_val: float = -10.0,
        ai_max_val: float = 10.0,
        ctr0_input_pfi: str = "PFI8",
        ctr1_gate_counter: str = "ctr1",
        ctr2_input_pfi: str = "PFI10",
        ctr3_pulse_counter: str = "ctr3",
        ctr3_output_pfi: str = "PFI12",
    ) -> None:
        self._device_name = device_name
        self._ao_min_val = ao_min_val
        self._ao_max_val = ao_max_val
        self._ai_min_val = ai_min_val
        self._ai_max_val = ai_max_val

        # Counter routing config (V1: only Ctr0 read path is active).
        self._ctr0_counter = "ctr0"
        self._ctr0_input_pfi = ctr0_input_pfi
        self._ctr1_gate_counter = ctr1_gate_counter
        self._ctr2_input_pfi = ctr2_input_pfi  # placeholder for future extension
        self._ctr3_pulse_counter = ctr3_pulse_counter
        self._ctr3_output_pfi = ctr3_output_pfi

        self._connected = False
        self._ao_tasks: Dict[str, nidaqmx.Task] = {}
        self._lock = threading.RLock()

        self._counter_count_task: Optional[nidaqmx.Task] = None
        self._counter_gate_task: Optional[nidaqmx.Task] = None
        self._counter_gate_channel = None
        self._counter_previous_total: Optional[int] = None
        self._counter_gate_high_ticks: int = 1

        self._counter_count_terminal: Optional[str] = None
        self._counter_gate_terminal: Optional[str] = None
        self._counter_input_terminal: Optional[str] = None

        self._pulse_task: Optional[nidaqmx.Task] = None
        self._pulse_frequency_hz: Optional[float] = None
        self._pulse_duty_time_s: Optional[float] = None

        self._ai_task: Optional[nidaqmx.Task] = None
        self._ai_sample_count: int = 1
        self._ai_channel_index_map: Dict[str, int] = {}
        self._ai_effective_rate_hz: float = self.AI_SAMPLE_RATE_HZ

    # ------------------------- lifecycle -------------------------
    def connect(self, device_name: Optional[str] = None) -> None:
        with self._lock:
            if self._connected and device_name in (None, self._device_name):
                return

            if self._connected and device_name not in (None, self._device_name):
                self.disconnect()

            if device_name is not None:
                self._device_name = device_name

            try:
                devices = list(System.local().devices)
                available_devices = [dev.name for dev in devices]
            except Exception as exc:
                raise RuntimeError(
                    "Unable to query local NI-DAQ devices. "
                    "Confirm NI-DAQmx runtime is installed."
                ) from exc

            if self._device_name not in available_devices:
                raise RuntimeError(
                    f"Device '{self._device_name}' not found. "
                    f"Available devices: {available_devices}"
                )
            selected_device = next(
                (dev for dev in devices if dev.name == self._device_name),
                None,
            )

            self._connected = True
            try:
                self._setup_ao_tasks()
                self._setup_ai_task(selected_device)
                self._setup_counter_tasks()
            except Exception:
                self._stop_and_close_all_ao_tasks()
                self._teardown_ai_task()
                self._teardown_counter_tasks()
                self._connected = False
                raise

    def disconnect(self) -> None:
        with self._lock:
            self._stop_and_close_all_ao_tasks()
            self._teardown_ai_task()
            self._teardown_counter_tasks()
            self._connected = False

    # --------------------- analog output ------------------------
    def write_analog_output(self, output_channel: str, value: float) -> None:
        with self._lock:
            self._ensure_connected()
            self._ensure_ao_tasks_ready()
            if not (self._ao_min_val <= value <= self._ao_max_val):
                raise ValueError(
                    f"AO value {value} V is outside limits "
                    f"[{self._ao_min_val}, {self._ao_max_val}] V."
                )

            terminal = self._normalize_channel(output_channel, expected_prefix="AO")
            task = self._ao_tasks.get(terminal)
            if task is None:
                raise RuntimeError(
                    f"AO task for channel '{terminal}' is not initialized. "
                    "Reconnect the hardware."
                )

            task.write(float(value), auto_start=False)

    # --------------------- analog input -------------------------
    def read_analog_input(self, input_channel: str, integration_time: float) -> float:
        with self._lock:
            self._ensure_connected()
            self._ensure_ai_task_ready()
            integration_time = self._validate_integration_time(integration_time)
            terminal = self._normalize_channel(input_channel, expected_prefix="AI")
            channel_index = self._ai_channel_index_map.get(terminal)
            if channel_index is None:
                raise ValueError(
                    f"Channel '{input_channel}' is outside configured AI range AI0..AI31."
                )

            sample_count = max(2, self._integration_time_to_sample_count(integration_time))
            actual_integration_time = sample_count / self._ai_effective_rate_hz
            timeout = max(1.0, actual_integration_time * 5.0 + 1.0)
            if sample_count != self._ai_sample_count:
                self._ai_task.control(TaskMode.TASK_UNRESERVE)
                self._ai_task.timing.cfg_samp_clk_timing(
                    rate=self._ai_effective_rate_hz,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=sample_count,
                )
                self._ai_task.control(TaskMode.TASK_COMMIT)
                self._ai_sample_count = sample_count

            self._ai_task.start()
            try:
                data = self._ai_task.read(
                    number_of_samples_per_channel=sample_count,
                    timeout=timeout,
                )
            finally:
                try:
                    self._ai_task.stop()
                except Exception:
                    pass
            
            return self._extract_ai_channel_mean(data, channel_index)

    # --------------------- edge counter -------------------------
    def read_sample_counter(self, integration_time: float) -> float:
        """
        Count rising edges on Ctr0 during a hardware-timed gate window and
        return count rate (Hz). Tasks are created once in connect().
        """
        with self._lock:
            self._ensure_connected()
            integration_time = self._validate_integration_time(integration_time)
            self._ensure_counter_tasks_ready()

            gate_high_ticks = max(
                self.GATE_MIN_HIGH_TICKS,
                int(round(integration_time * self.COUNTER_TIMEBASE_HZ)),
            )
            actual_integration_time = gate_high_ticks / self.COUNTER_TIMEBASE_HZ
            timeout = max(1.0, actual_integration_time * 5.0 + 1.0)

            if gate_high_ticks != self._counter_gate_high_ticks:
                # Reconfigure finite gate width without recreating the task.
                self._counter_gate_task.control(TaskMode.TASK_UNRESERVE)
                self._counter_gate_channel.co_pulse_high_ticks = gate_high_ticks
                self._counter_gate_channel.co_pulse_low_ticks = self.GATE_LOW_TICKS
                self._counter_gate_task.control(TaskMode.TASK_COMMIT)
                self._counter_gate_high_ticks = gate_high_ticks
            self._counter_gate_task.start()
            try:
                self._counter_gate_task.wait_until_done(timeout=timeout)
            finally:
                try:
                    self._counter_gate_task.stop()
                except Exception:
                    pass
            current_total = int(self._counter_count_task.read())
            previous_total = self._counter_previous_total
            if previous_total is None:
                previous_total = current_total
            window_count = (current_total - previous_total) % 2**32
            self._counter_previous_total = current_total
            
            return float(window_count) / actual_integration_time

    # --------------------- pulse output -------------------------
    def start_pulse_train(self, frequency_hz: float, duty_time_s: float) -> None:
        with self._lock:
            self._ensure_connected()
            self._validate_pulse_config(frequency_hz, duty_time_s)

            self.stop_pulse_train()
            duty_cycle = duty_time_s * frequency_hz

            pulse_counter = self._normalize_channel(
                self._ctr3_pulse_counter, expected_prefix="CTR"
            )
            pulse_terminal = self._normalize_terminal(self._ctr3_output_pfi)
            if pulse_counter.lower() in {
                (self._counter_count_terminal or "").lower(),
                (self._counter_gate_terminal or "").lower(),
            }:
                raise ValueError(
                    "Pulse counter must be different from Ctr0 (count) and gate counter."
                )

            task = nidaqmx.Task(new_task_name=f"CO_{pulse_counter.replace('/', '_')}")
            co_channel = task.co_channels.add_co_pulse_chan_freq(
                counter=pulse_counter,
                idle_state=Level.LOW,
                initial_delay=0.0,
                freq=frequency_hz,
                duty_cycle=duty_cycle,
            )
            co_channel.co_pulse_term = pulse_terminal
            task.timing.cfg_implicit_timing(sample_mode=AcquisitionType.CONTINUOUS)
            task.control(TaskMode.TASK_COMMIT)
            task.start()

            self._pulse_task = task
            self._pulse_frequency_hz = float(frequency_hz)
            self._pulse_duty_time_s = float(duty_time_s)

    def stop_pulse_train(self) -> None:
        with self._lock:
            if self._pulse_task is None:
                return
            try:
                self._pulse_task.stop()
            except Exception:
                pass
            try:
                self._pulse_task.close()
            except Exception:
                pass

            self._pulse_task = None
            self._pulse_frequency_hz = None
            self._pulse_duty_time_s = None

    # ------------------------ helpers ---------------------------
    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("NI6423 is not connected. Call connect() first.")

    def _validate_integration_time(self, integration_time: float) -> float:
        if integration_time < self.MIN_INTEGRATION_S:
            raise ValueError(
                f"integration_time must be >= {self.MIN_INTEGRATION_S} s."
            )

        steps = round(integration_time / self.INTEGRATION_STEP_S)
        expected = steps * self.INTEGRATION_STEP_S
        if not math.isclose(integration_time, expected, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(
                "integration_time must use 100 us steps "
                f"(e.g. {self.MIN_INTEGRATION_S}, 2e-4, 3e-4, ...)."
            )
        return float(expected)

    def _validate_pulse_config(self, frequency_hz: float, duty_time_s: float) -> None:
        if frequency_hz <= 0:
            raise ValueError("frequency_hz must be > 0.")
        if duty_time_s <= 0:
            raise ValueError("duty_time_s must be > 0.")

        period_s = 1.0 / frequency_hz
        if duty_time_s >= period_s:
            raise ValueError(
                "duty_time_s must be smaller than one period (1 / frequency_hz)."
            )

    def _integration_time_to_sample_count(self, integration_time: float) -> int:
        return max(1, int(round(integration_time * self._ai_effective_rate_hz)))

    def _extract_ai_channel_mean(self, data, channel_index: int) -> float:
        if isinstance(data, list):
            if not data:
                raise RuntimeError("AI read returned empty data.")

            channel_data = data[channel_index]
            if isinstance(channel_data, list):
                if not channel_data:
                    raise RuntimeError("AI read returned empty channel data.")
                return float(fmean(channel_data))
            return float(channel_data)

        return float(data)

    def _normalize_channel(self, channel: str, expected_prefix: str) -> str:
        token = channel.strip().lstrip("/")
        if not token:
            raise ValueError("Empty channel name.")

        if "/" not in token:
            token = f"{self._device_name}/{token}"

        dev, chan = token.split("/", 1)
        if dev != self._device_name:
            raise ValueError(
                f"Channel '{channel}' belongs to '{dev}', but connected device is "
                f"'{self._device_name}'."
            )

        chan = chan.upper()
        if not chan.startswith(expected_prefix):
            raise ValueError(
                f"Channel '{channel}' must start with '{expected_prefix}'."
            )

        return f"{dev}/{chan.lower()}"

    def _normalize_terminal(self, terminal: str) -> str:
        token = terminal.strip().lstrip("/")
        if not token:
            raise ValueError("Empty terminal name.")

        if "/" not in token:
            token = f"{self._device_name}/{token}"

        dev, term = token.split("/", 1)
        if dev != self._device_name:
            raise ValueError(
                f"Terminal '{terminal}' belongs to '{dev}', but connected device is "
                f"'{self._device_name}'."
            )

        return f"/{dev}/{term.upper()}"

    def _counter_internal_output(self, counter_channel: str) -> str:
        # DAQmx internal route format uses CtrXInternalOutput.
        counter_name = counter_channel.split("/")[-1].capitalize()
        return f"/{self._device_name}/{counter_name}InternalOutput"

    def _ensure_ai_task_ready(self) -> None:
        if self._ai_task is None:
            raise RuntimeError("AI task is not initialized. Reconnect the hardware.")

    def _ensure_ao_tasks_ready(self) -> None:
        if len(self._ao_tasks) != self.AO_CHANNEL_COUNT:
            raise RuntimeError("AO tasks are not initialized. Reconnect the hardware.")

    def _ensure_counter_tasks_ready(self) -> None:
        if self._counter_count_task is None or self._counter_gate_task is None:
            raise RuntimeError(
                "Counter tasks are not initialized. Reconnect the hardware."
            )

    def _setup_ao_tasks(self) -> None:
        self._stop_and_close_all_ao_tasks()

        created_tasks: Dict[str, nidaqmx.Task] = {}
        try:
            for index in range(self.AO_CHANNEL_COUNT):
                terminal = self._normalize_channel(f"AO{index}", expected_prefix="AO")
                task = nidaqmx.Task(new_task_name=f"AO_{terminal.replace('/', '_')}")
                task.ao_channels.add_ao_voltage_chan(
                    terminal,
                    min_val=self._ao_min_val,
                    max_val=self._ao_max_val,
                )
                task.control(TaskMode.TASK_COMMIT)
                task.start()
                created_tasks[terminal] = task

            self._ao_tasks = created_tasks
        except Exception:
            for task in created_tasks.values():
                try:
                    task.stop()
                except Exception:
                    pass
                try:
                    task.close()
                except Exception:
                    pass
            self._ao_tasks.clear()
            raise

    def _setup_ai_task(self, device) -> None:
        self._teardown_ai_task()

        ai_task = nidaqmx.Task(new_task_name=f"AI_{self._device_name}_all")
        ai_range = f"{self._device_name}/ai0:{self.AI_CHANNEL_COUNT - 1}"
        ai_rate = self._compute_safe_ai_rate(device)
        initial_sample_count = max(2, int(round(self.MIN_INTEGRATION_S * ai_rate)))

        try:
            ai_task.ai_channels.add_ai_voltage_chan(
                ai_range,
                min_val=self._ai_min_val,
                max_val=self._ai_max_val,
            )
            ai_task.timing.cfg_samp_clk_timing(
                rate=ai_rate,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=initial_sample_count,
            )
            ai_task.control(TaskMode.TASK_COMMIT)

            self._ai_task = ai_task
            self._ai_effective_rate_hz = ai_rate
            self._ai_sample_count = initial_sample_count
            self._ai_channel_index_map = {
                f"{self._device_name}/ai{index}": index
                for index in range(self.AI_CHANNEL_COUNT)
            }
        except Exception:
            try:
                ai_task.close()
            except Exception:
                pass
            raise

    def _teardown_ai_task(self) -> None:
        if self._ai_task is not None:
            try:
                self._ai_task.stop()
            except Exception:
                pass
            try:
                self._ai_task.close()
            except Exception:
                pass

        self._ai_task = None
        self._ai_sample_count = 1
        self._ai_effective_rate_hz = self.AI_SAMPLE_RATE_HZ
        self._ai_channel_index_map.clear()

    def _compute_safe_ai_rate(self, device) -> float:
        target_rate = float(self.AI_SAMPLE_RATE_HZ)
        min_fallback = max(1.0, target_rate / self.AI_CHANNEL_COUNT)

        if device is None:
            return min_fallback

        try:
            max_single = float(device.ai_max_single_chan_rate)
            max_multi_total = float(device.ai_max_multi_chan_rate)
            per_chan_from_multi = max_multi_total / float(self.AI_CHANNEL_COUNT)
            return max(
                min_fallback,
                min(target_rate, max_single, per_chan_from_multi),
            )
        except Exception:
            return min_fallback

    def _setup_counter_tasks(self) -> None:
        self._teardown_counter_tasks()

        count_counter = self._normalize_channel(self._ctr0_counter, expected_prefix="CTR")
        gate_counter = self._normalize_channel(
            self._ctr1_gate_counter, expected_prefix="CTR"
        )
        input_terminal = self._normalize_terminal(self._ctr0_input_pfi)

        if count_counter.lower() == gate_counter.lower():
            raise ValueError("Ctr0 and gate counter must be different resources.")

        timebase_100mhz = f"/{self._device_name}/100MHzTimebase"
        gate_internal = self._counter_internal_output(gate_counter)

        count_task = nidaqmx.Task(new_task_name=f"CI_{count_counter.replace('/', '_')}")
        gate_task = nidaqmx.Task(new_task_name=f"Gate_{gate_counter.replace('/', '_')}")

        try:
            ci_channel = count_task.ci_channels.add_ci_count_edges_chan(
                counter=count_counter,
                edge=Edge.RISING,
                initial_count=0,
                count_direction=CountDirection.COUNT_UP,
            )
            ci_channel.ci_count_edges_term = input_terminal

            count_task.triggers.pause_trigger.trig_type = TriggerType.DIGITAL_LEVEL
            count_task.triggers.pause_trigger.dig_lvl_src = gate_internal
            count_task.triggers.pause_trigger.dig_lvl_when = Level.LOW

            gate_channel = gate_task.co_channels.add_co_pulse_chan_ticks(
                counter=gate_counter,
                source_terminal=timebase_100mhz,
                high_ticks=self.GATE_MIN_HIGH_TICKS,
                low_ticks=self.GATE_LOW_TICKS,
            )
            gate_channel.co_pulse_idle_state = Level.LOW
            gate_channel.co_pulse_ticks_initial_delay = 0
            gate_task.timing.cfg_implicit_timing(
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=1,
            )

            count_task.control(TaskMode.TASK_COMMIT)
            gate_task.control(TaskMode.TASK_COMMIT)
            count_task.start()

            self._counter_count_task = count_task
            self._counter_gate_task = gate_task
            self._counter_gate_channel = gate_channel
            self._counter_previous_total = int(count_task.read())
            self._counter_gate_high_ticks = self.GATE_MIN_HIGH_TICKS

            self._counter_count_terminal = count_counter
            self._counter_gate_terminal = gate_counter
            self._counter_input_terminal = input_terminal
        except Exception:
            try:
                gate_task.close()
            except Exception:
                pass
            try:
                count_task.close()
            except Exception:
                pass
            raise

    def _teardown_counter_tasks(self) -> None:
        self.stop_pulse_train()

        if self._counter_gate_task is not None:
            try:
                self._counter_gate_task.stop()
            except Exception:
                pass
            try:
                self._counter_gate_task.close()
            except Exception:
                pass

        if self._counter_count_task is not None:
            try:
                self._counter_count_task.stop()
            except Exception:
                pass
            try:
                self._counter_count_task.close()
            except Exception:
                pass

        self._counter_count_task = None
        self._counter_gate_task = None
        self._counter_gate_channel = None
        self._counter_previous_total = None
        self._counter_gate_high_ticks = self.GATE_MIN_HIGH_TICKS
        self._counter_count_terminal = None
        self._counter_gate_terminal = None
        self._counter_input_terminal = None

    def _stop_and_close_all_ao_tasks(self) -> None:
        for task in self._ao_tasks.values():
            try:
                task.stop()
            except Exception:
                pass
            try:
                task.close()
            except Exception:
                pass
        self._ao_tasks.clear()

    # Optional aliases to keep naming short in logic layer.
    analog_output = write_analog_output
    analog_input = read_analog_input
    sample_counter = read_sample_counter


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Basic smoke test for NI6423Hardware methods."
    )
    parser.add_argument("--device", default="Dev7", help="NI device name, e.g. Dev1")
    parser.add_argument(
        "--ao-channel", default="AO0", help="Analog output channel, e.g. AO0"
    )
    parser.add_argument(
        "--ao-value", type=float, default=0.0, help="Analog output value in volts"
    )
    parser.add_argument(
        "--ai-channel", default="AI0", help="Analog input channel, e.g. AI0"
    )
    parser.add_argument(
        "--integration-time",
        type=float,
        default=3e-2,
        help="Integration time in seconds (>=100us, 100us steps).",
    )
    parser.add_argument(
        "--pulse-freq",
        type=float,
        default=0.0,
        help="If >0, start Ctr3 pulse output before reading counter.",
    )
    parser.add_argument(
        "--duty-time",
        type=float,
        default=1e-6,
        help="Pulse high time in seconds for Ctr3 output.",
    )
    args = parser.parse_args()

    hw = NI6423Hardware(device_name=args.device)
    try:
        print(f"[TEST] Connecting to {args.device} ...")
        hw.connect()
        print("[PASS] connect()")

        print(
            f"[TEST] write_analog_output({args.ao_channel}, {args.ao_value:.6f} V) ..."
        )
        hw.write_analog_output(args.ao_channel, args.ao_value)
        print("[PASS] write_analog_output()")

        print(
            f"[TEST] read_analog_input({args.ai_channel}, {args.integration_time:.6g} s) ..."
        )
        ai_val = hw.read_analog_input(args.ai_channel, args.integration_time)
        print(f"[PASS] read_analog_input() -> {ai_val:+.6f} V")

        if args.pulse_freq > 0:
            print(
                "[TEST] start_pulse_train("
                f"freq={args.pulse_freq:.6f} Hz, duty_time={args.duty_time:.9f} s) ..."
            )
            hw.start_pulse_train(args.pulse_freq, args.duty_time)
            print("[PASS] start_pulse_train()")

        print(f"[TEST] read_sample_counter({args.integration_time:.6g} s) ...")
        count_rate = hw.read_sample_counter(args.integration_time)
        print(f"[PASS] read_sample_counter() -> {count_rate:.3f} Hz")

    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            hw.stop_pulse_train()
        except Exception:
            pass
        try:
            hw.disconnect()
            print("[PASS] disconnect()")
        except Exception as exc:
            print(f"[WARN] disconnect() raised {type(exc).__name__}: {exc}")
