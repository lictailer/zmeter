import math
import argparse
import threading
from statistics import fmean
from typing import Dict, Optional

import nidaqmx
from nidaqmx.constants import AcquisitionType, Edge, Level, TriggerType
from nidaqmx.system import System


class NI6432Hardware:
    """
    Minimal NI USB-6432 hardware layer using nidaqmx.

    Public API:
    1. connect(device_name)
    2. disconnect()
    3. write_analog_output(output_channel, value)
    4. read_analog_input(input_channel, integration_time)
    5. read_sample_counter(input_counter_channel, integration_time)
    """

    INTEGRATION_STEP_S = 100e-6
    MIN_INTEGRATION_S = 100e-6
    AI_SAMPLE_RATE_HZ = 100_000.0  # 10 us sample period
    COUNTER_TIMEBASE_HZ = 100_000_000.0  # 100 MHz internal timebase

    def __init__(
        self,
        device_name: str = "Dev1",
        ao_min_val: float = -10.0,
        ao_max_val: float = 10.0,
        ai_min_val: float = -10.0,
        ai_max_val: float = 10.0,
    ) -> None:
        self._device_name = device_name
        self._ao_min_val = ao_min_val
        self._ao_max_val = ao_max_val
        self._ai_min_val = ai_min_val
        self._ai_max_val = ai_max_val

        self._connected = False
        self._ao_tasks: Dict[str, nidaqmx.Task] = {}
        self._lock = threading.RLock()

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
                available_devices = [dev.name for dev in System.local().devices]
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

            self._connected = True

    def disconnect(self) -> None:
        with self._lock:
            for task in self._ao_tasks.values():
                try:
                    task.close()
                except Exception:
                    pass
            self._ao_tasks.clear()
            self._connected = False

    # --------------------- analog output ------------------------
    def write_analog_output(self, output_channel: str, value: float) -> None:
        with self._lock:
            self._ensure_connected()
            if not (self._ao_min_val <= value <= self._ao_max_val):
                raise ValueError(
                    f"AO value {value} V is outside limits "
                    f"[{self._ao_min_val}, {self._ao_max_val}] V."
                )

            terminal = self._normalize_channel(output_channel, expected_prefix="AO")
            task = self._ao_tasks.get(terminal)
            if task is None:
                task = nidaqmx.Task(new_task_name=f"AO_{terminal.replace('/', '_')}")
                task.ao_channels.add_ao_voltage_chan(
                    terminal,
                    min_val=self._ao_min_val,
                    max_val=self._ao_max_val,
                )
                self._ao_tasks[terminal] = task

            task.write(float(value), auto_start=True)

    # --------------------- analog input -------------------------
    def read_analog_input(self, input_channel: str, integration_time: float) -> float:
        with self._lock:
            self._ensure_connected()
            integration_time = self._validate_integration_time(integration_time)
            terminal = self._normalize_channel(input_channel, expected_prefix="AI")

            sample_count = max(
                1, int(round(integration_time * self.AI_SAMPLE_RATE_HZ))
            )
            timeout = max(1.0, integration_time * 5.0 + 1.0)

            with nidaqmx.Task(new_task_name=f"AI_{terminal.replace('/', '_')}") as task:
                task.ai_channels.add_ai_voltage_chan(
                    terminal,
                    min_val=self._ai_min_val,
                    max_val=self._ai_max_val,
                )
                task.timing.cfg_samp_clk_timing(
                    rate=self.AI_SAMPLE_RATE_HZ,
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=sample_count,
                )

                data = task.read(
                    number_of_samples_per_channel=sample_count,
                    timeout=timeout,
                )

            if isinstance(data, list):
                return float(fmean(data))
            return float(data)

    # --------------------- edge counter -------------------------
    def read_sample_counter(
        self, input_counter_channel: str, integration_time: float
    ) -> float:
        """
        Count rising edges during the integration window and return count rate (Hz).

        Hardware clocking is implemented using a second counter that generates a
        one-shot gate pulse. The count task is paused when the gate is LOW.
        """
        with self._lock:
            self._ensure_connected()
            integration_time = self._validate_integration_time(integration_time)

            count_counter = self._normalize_channel(
                input_counter_channel, expected_prefix="CTR"
            )
            gate_counter = self._select_gate_counter(count_counter)

            gate_high_ticks = int(
                round(integration_time * self.COUNTER_TIMEBASE_HZ)
            )
            gate_high_ticks = max(gate_high_ticks, 1)
            gate_low_ticks = 10

            gate_internal = self._counter_internal_output(gate_counter)
            timebase_100mhz = f"/{self._device_name}/100MHzTimebase"
            timeout = max(1.0, integration_time * 5.0 + 1.0)

            with nidaqmx.Task() as count_task, nidaqmx.Task() as gate_task:
                gate_channel = gate_task.co_channels.add_co_pulse_chan_ticks(
                    counter=gate_counter,
                    source_terminal=timebase_100mhz,
                    high_ticks=gate_high_ticks,
                    low_ticks=gate_low_ticks,
                )
                gate_channel.co_pulse_idle_state = Level.LOW
                gate_channel.co_pulse_ticks_initial_delay = 0
                gate_task.timing.cfg_implicit_timing(
                    sample_mode=AcquisitionType.FINITE,
                    samps_per_chan=1,
                )

                count_task.ci_channels.add_ci_count_edges_chan(
                    counter=count_counter,
                    edge=Edge.RISING,
                    initial_count=0,
                )

                count_task.triggers.pause_trigger.trig_type = TriggerType.DIGITAL_LEVEL
                count_task.triggers.pause_trigger.dig_lvl_src = gate_internal
                count_task.triggers.pause_trigger.dig_lvl_when = Level.LOW

                count_task.start()
                gate_task.start()
                gate_task.wait_until_done(timeout=timeout)

                count = int(count_task.read())

            return float(count) / integration_time

    # ------------------------ helpers ---------------------------
    def _ensure_connected(self) -> None:
        if not self._connected:
            raise RuntimeError("NI6432 is not connected. Call connect() first.")

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

    def _select_gate_counter(self, count_counter: str) -> str:
        counter_name = count_counter.split("/")[-1]  # e.g. ctr0
        suffix = counter_name.replace("ctr", "")
        if not suffix.isdigit():
            raise ValueError(f"Invalid counter channel: {count_counter}")

        index = int(suffix)
        gate_index = index + 1 if index % 2 == 0 else index - 1
        return f"{self._device_name}/ctr{gate_index}"

    def _counter_internal_output(self, counter_channel: str) -> str:
        # DAQmx internal route format uses CtrXInternalOutput.
        counter_name = counter_channel.split("/")[-1].capitalize()
        return f"/{self._device_name}/{counter_name}InternalOutput"

    # Optional aliases to keep naming short in logic layer.
    analog_output = write_analog_output
    analog_input = read_analog_input
    sample_counter = read_sample_counter


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Basic smoke test for NI6432Hardware methods."
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
        "--counter-channel", default="Ctr0", help="Counter input channel, e.g. Ctr0"
    )
    parser.add_argument(
        "--integration-time",
        type=float,
        default=3e-2,
        help="Integration time in seconds (>=100us, 100us steps).",
    )
    args = parser.parse_args()

    hw = NI6432Hardware(device_name=args.device)
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

        print(
            "[TEST] read_sample_counter("
            f"{args.counter_channel}, {args.integration_time:.6g} s) ..."
        )
        count_rate = hw.read_sample_counter(args.counter_channel, args.integration_time)
        print(f"[PASS] read_sample_counter() -> {count_rate:.3f} Hz")

    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            hw.disconnect()
            print("[PASS] disconnect()")
        except Exception as exc:
            print(f"[WARN] disconnect() raised {type(exc).__name__}: {exc}")
