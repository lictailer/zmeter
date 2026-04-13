"""Four9 PID temperature stability sweep test.

This script performs a multi-setpoint stability test for Four9 temperature control
and saves summary results to CSV files.

Default setpoint schedule:
- 3 to 18 K, step 5 K
- 18 to 90 K, step 8 K
- 90 to 210 K, step 12 K
"""

from __future__ import annotations

import argparse
import csv
import math
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Deque, Dict, List, Optional


SUMMARY_COLUMNS = [
    "start_time",
    "target_temperature_k",
    "status",
    "time_to_stable_with_post_wait_s",
    "deviation_60s_at_stable_k",
    "avg_temperature_60s_at_stable_k",
    "max_temp_before_first_in_range_k",
    "max_temp_ramp_rate_start_to_first_cross_k_per_s",
    "avg_heater_power_during_post_wait_w",
    "deviation_60s_before_next_setpoint_k",
    "avg_temperature_60s_before_next_setpoint_k",
    "last_temperature_k",
]


@dataclass
class TestConfig:
    base_url: str = "http://localhost"
    port: int = 4949

    target_channel: int = 2
    read_channel: int = 2
    heater_channel: int = 2

    poll_interval_s: float = 1.0
    stability_window_s: float = 60.0
    stable_deviation_threshold_k: float = 0.4
    target_tolerance_k: float = 0.2

    post_stable_wait_s: float = 60.0
    stable_timeout_s: float = 20 * 60.0

    dwell_after_stable_s: float = 5 * 60.0
    pre_next_eval_delay_s: float = 4 * 60.0
    pre_next_eval_window_s: float = 60.0

    output_csv: str = ""
    setpoints_k: List[float] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.setpoints_k is None:
            self.setpoints_k = build_default_setpoints()

    @property
    def stability_window_points(self) -> int:
        return max(1, int(round(self.stability_window_s / self.poll_interval_s)))



def build_default_setpoints() -> List[float]:
    setpoints: List[float] = []

    t = 3.0
    while t <= 18.0 + 1e-9:
        setpoints.append(round(t, 6))
        t += 5.0

    t = 18.0
    while t <= 90.0 + 1e-9:
        setpoints.append(round(t, 6))
        t += 8.0

    t = 90.0
    while t <= 210.0 + 1e-9:
        setpoints.append(round(t, 6))
        t += 12.0

    # Keep order, remove duplicates.
    uniq: List[float] = []
    seen = set()
    for s in setpoints:
        if s not in seen:
            uniq.append(s)
            seen.add(s)
    return uniq


def parse_setpoints(text: str) -> List[float]:
    if not text.strip():
        raise ValueError("Empty setpoint list.")
    out = []
    for token in text.split(","):
        out.append(float(token.strip()))
    return out


def finite_values(values: List[float]) -> List[float]:
    return [x for x in values if math.isfinite(x)]


def calc_deviation(values: List[float]) -> float:
    vals = finite_values(values)
    if not vals:
        return float("nan")
    return max(vals) - min(vals)


def calc_mean(values: List[float]) -> float:
    vals = finite_values(values)
    if not vals:
        return float("nan")
    return sum(vals) / len(vals)


def crossed_target(prev_temp: float, curr_temp: float, target_k: float) -> bool:
    prev_diff = prev_temp - target_k
    curr_diff = curr_temp - target_k
    if prev_diff == 0.0 or curr_diff == 0.0:
        return True
    return (prev_diff < 0.0 < curr_diff) or (prev_diff > 0.0 > curr_diff)


class Four9PidStabilitySweep:
    def __init__(
        self,
        cfg: TestConfig,
        status_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
        log_callback: Optional[Callable[[str], None]] = None,
        abort_event: Optional[threading.Event] = None,
    ):
        self.cfg = cfg
        self.hw = self._make_hardware()
        self._status_callback = status_callback
        self._log_callback = log_callback
        self._abort_event = abort_event
        self._last_status: Dict[str, Any] = {}

    def _is_aborted(self) -> bool:
        return self._abort_event is not None and self._abort_event.is_set()

    def _log(self, message: str) -> None:
        print(message)
        if self._log_callback is not None:
            self._log_callback(message)

    def _emit_status(self, **updates: Any) -> None:
        self._last_status.update(updates)
        if self._status_callback is not None:
            self._status_callback(dict(self._last_status))

    def run(self) -> None:
        output_csv = self._resolve_output_path()
        output_cfg_csv = output_csv.with_name(f"{output_csv.stem}_config.csv")

        self._write_config_csv(output_cfg_csv)

        self._emit_status(
            stage="connecting",
            message=f"Connecting to {self.cfg.base_url}:{self.cfg.port}",
        )
        self._log(f"Connecting to Four9 at {self.cfg.base_url}:{self.cfg.port} ...")
        if not self.hw.connect_hardware(self.cfg.base_url, self.cfg.port):
            raise RuntimeError("Failed to connect to Four9.")
        self._log("Connected.")
        self._emit_status(stage="connected", message="Connected")

        with output_csv.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=SUMMARY_COLUMNS)
            writer.writeheader()

            try:
                for index, setpoint in enumerate(self.cfg.setpoints_k):
                    if self._is_aborted():
                        self._emit_status(stage="aborted", message="Aborted by user")
                        self._log("Aborted by user.")
                        break

                    self._log(
                        f"[{index + 1}/{len(self.cfg.setpoints_k)}] "
                        f"Set target CH{self.cfg.target_channel:02d} -> {setpoint:.3f} K"
                    )
                    self._emit_status(
                        stage="set_target",
                        setpoint_index=index + 1,
                        setpoint_total=len(self.cfg.setpoints_k),
                        target_k=setpoint,
                        message=f"Setting target to {setpoint:.3f} K",
                    )

                    row = self._run_single_setpoint(setpoint)
                    status = str(row["status"])

                    if status == "stable" and index < len(self.cfg.setpoints_k) - 1:
                        pre_next_dev, pre_next_avg = self._inter_setpoint_wait()
                        row["deviation_60s_before_next_setpoint_k"] = pre_next_dev
                        row["avg_temperature_60s_before_next_setpoint_k"] = pre_next_avg

                    writer.writerow(row)
                    file.flush()

                    if status == "aborted":
                        self._log("  Status: aborted. Stopping sweep.")
                        break
                    if status == "timeout":
                        self._log("  Status: timeout. Continuing to next setpoint.")
                        continue
                    if status != "stable":
                        self._log(f"  Status: {status}. Stopping sweep.")
                        break
            finally:
                self.hw.disconnect()
                self._emit_status(
                    stage="finished",
                    message=f"Saved summary CSV: {output_csv}",
                )
                self._log(f"Saved summary CSV: {output_csv}")
                self._log(f"Saved config CSV: {output_cfg_csv}")

    def _run_single_setpoint(self, target_k: float) -> Dict[str, object]:
        self.hw.set_target_temperature(self.cfg.target_channel, target_k)

        start_ts = datetime.now()
        start_mono = time.monotonic()
        stable_since: Optional[float] = None

        temp_window: Deque[float] = deque(maxlen=self.cfg.stability_window_points)
        power_window_during_post_wait: Deque[float] = deque(
            maxlen=self.cfg.stability_window_points
        )

        max_temp_before_first_in_range = float("-inf")
        first_in_range_seen = False

        max_ramp_rate = float("-inf")
        first_cross_seen = False
        prev_temp = float("nan")
        prev_ts = time.monotonic()

        last_temp = float("nan")
        last_dev = float("nan")
        last_avg = float("nan")

        while True:
            if self._is_aborted():
                return self._make_row(
                    start_ts=start_ts,
                    target_k=target_k,
                    status="aborted",
                    elapsed_s=time.monotonic() - start_mono,
                    deviation_k=last_dev,
                    avg_temp_k=last_avg,
                    max_temp_before_first_in_range=max_temp_before_first_in_range,
                    max_ramp_rate=max_ramp_rate,
                    avg_heater_power=calc_mean(list(power_window_during_post_wait)),
                    last_temp=last_temp,
                )

            loop_start = time.monotonic()

            temps, powers = self.hw.read_all_temperatures_and_heater_powers()
            temp = temps[self.cfg.read_channel]
            power = powers[self.cfg.heater_channel]
            now_ts = time.monotonic()
            last_temp = temp

            if math.isfinite(temp):
                temp_window.append(temp)

                if not first_in_range_seen:
                    max_temp_before_first_in_range = max(
                        max_temp_before_first_in_range, temp
                    )

                if (
                    not first_cross_seen
                    and math.isfinite(prev_temp)
                    and now_ts > prev_ts
                ):
                    ramp = abs((temp - prev_temp) / (now_ts - prev_ts))
                    if math.isfinite(ramp):
                        max_ramp_rate = max(max_ramp_rate, ramp)
                    if crossed_target(prev_temp, temp, target_k):
                        first_cross_seen = True

            in_range = (
                math.isfinite(temp)
                and abs(temp - target_k) <= self.cfg.target_tolerance_k
            )
            if in_range:
                first_in_range_seen = True

            last_dev = calc_deviation(list(temp_window))
            last_avg = calc_mean(list(temp_window))
            dev_ok = math.isfinite(last_dev) and (last_dev < self.cfg.stable_deviation_threshold_k)
            stable_now = in_range and dev_ok

            stable_hold_s = 0.0
            if stable_now:
                if stable_since is None:
                    stable_since = now_ts
                    power_window_during_post_wait.clear()

                if math.isfinite(power):
                    power_window_during_post_wait.append(power)

                stable_hold_s = now_ts - stable_since
                if stable_hold_s >= self.cfg.post_stable_wait_s:
                    elapsed_s = now_ts - start_mono
                    self._log(
                        "  Stable. "
                        f"time={elapsed_s:.1f}s, dev60={last_dev:.3f}K, avg60={last_avg:.3f}K"
                    )
                    self._emit_status(
                        stage="stable",
                        target_k=target_k,
                        current_temp_k=temp,
                        delta_t_k=(temp - target_k) if math.isfinite(temp) else float("nan"),
                        deviation_k=last_dev,
                        avg_temp_k=last_avg,
                        heater_power_w=power,
                        stable_hold_s=stable_hold_s,
                        elapsed_s=elapsed_s,
                        timeout_s=self.cfg.stable_timeout_s,
                        max_ramp_rate_k_per_s=max_ramp_rate if max_ramp_rate != float("-inf") else float("nan"),
                        message="Stable",
                    )
                    return self._make_row(
                        start_ts=start_ts,
                        target_k=target_k,
                        status="stable",
                        elapsed_s=elapsed_s,
                        deviation_k=last_dev,
                        avg_temp_k=last_avg,
                        max_temp_before_first_in_range=max_temp_before_first_in_range,
                        max_ramp_rate=max_ramp_rate,
                        avg_heater_power=calc_mean(list(power_window_during_post_wait)),
                        last_temp=last_temp,
                    )
            else:
                stable_since = None
                power_window_during_post_wait.clear()

            elapsed_s = now_ts - start_mono
            stage = "post_stable_wait" if stable_now else "stabilizing"
            self._emit_status(
                stage=stage,
                target_k=target_k,
                current_temp_k=temp,
                delta_t_k=(temp - target_k) if math.isfinite(temp) else float("nan"),
                deviation_k=last_dev,
                avg_temp_k=last_avg,
                heater_power_w=power,
                stable_hold_s=stable_hold_s,
                elapsed_s=elapsed_s,
                timeout_s=self.cfg.stable_timeout_s,
                max_ramp_rate_k_per_s=max_ramp_rate if max_ramp_rate != float("-inf") else float("nan"),
                message=stage,
            )

            if (now_ts - start_mono) >= self.cfg.stable_timeout_s:
                elapsed_s = now_ts - start_mono
                self._log(
                    "  Timeout. "
                    f"time={elapsed_s:.1f}s, dev60={last_dev:.3f}K, avg60={last_avg:.3f}K"
                )
                self._emit_status(stage="timeout", message="Timeout")
                return self._make_row(
                    start_ts=start_ts,
                    target_k=target_k,
                    status="timeout",
                    elapsed_s=elapsed_s,
                    deviation_k=last_dev,
                    avg_temp_k=last_avg,
                    max_temp_before_first_in_range=max_temp_before_first_in_range,
                    max_ramp_rate=max_ramp_rate,
                    avg_heater_power=calc_mean(list(power_window_during_post_wait)),
                    last_temp=last_temp,
                )

            prev_temp = temp
            prev_ts = now_ts
            self._sleep_to_next_poll(loop_start)

    def _inter_setpoint_wait(self) -> tuple[float, float]:
        if self.cfg.pre_next_eval_delay_s > 0:
            self._log(
                f"  Waiting {self.cfg.pre_next_eval_delay_s:.0f}s before "
                f"final pre-next stability check ..."
            )
            self._hold_for_seconds(self.cfg.pre_next_eval_delay_s, stage="inter_wait")

        self._log(
            f"  Measuring pre-next 60s stability window "
            f"({self.cfg.pre_next_eval_window_s:.0f}s) ..."
        )
        window_temps = self._collect_temperature_window(self.cfg.pre_next_eval_window_s)
        pre_next_dev = calc_deviation(window_temps)
        pre_next_avg = calc_mean(window_temps)

        already_waited = self.cfg.pre_next_eval_delay_s + self.cfg.pre_next_eval_window_s
        remaining = self.cfg.dwell_after_stable_s - already_waited
        if remaining > 0:
            self._log(f"  Extra dwell before next setpoint: {remaining:.0f}s")
            self._hold_for_seconds(remaining, stage="dwell")

        return pre_next_dev, pre_next_avg

    def _collect_temperature_window(self, duration_s: float) -> List[float]:
        temps_out: List[float] = []
        start = time.monotonic()
        while (time.monotonic() - start) < duration_s:
            if self._is_aborted():
                break
            loop_start = time.monotonic()
            temps, _ = self.hw.read_all_temperatures_and_heater_powers()
            temp = temps[self.cfg.read_channel]
            if math.isfinite(temp):
                temps_out.append(temp)
            self._emit_status(
                stage="pre_next_eval",
                current_temp_k=temp,
                elapsed_s=(time.monotonic() - start),
                timeout_s=duration_s,
                deviation_k=calc_deviation(temps_out),
                avg_temp_k=calc_mean(temps_out),
                message="pre-next evaluation",
            )
            self._sleep_to_next_poll(loop_start)
        return temps_out

    def _hold_for_seconds(self, duration_s: float, stage: str) -> None:
        start = time.monotonic()
        while (time.monotonic() - start) < duration_s:
            if self._is_aborted():
                break
            loop_start = time.monotonic()
            # Keep polling during hold, so communication issues surface early.
            temps, _ = self.hw.read_all_temperatures_and_heater_powers()
            temp = temps[self.cfg.read_channel]
            self._emit_status(
                stage=stage,
                current_temp_k=temp,
                elapsed_s=(time.monotonic() - start),
                timeout_s=duration_s,
                message=stage,
            )
            self._sleep_to_next_poll(loop_start)

    def _sleep_to_next_poll(self, loop_start_mono: float) -> None:
        elapsed = time.monotonic() - loop_start_mono
        remain = self.cfg.poll_interval_s - elapsed
        if remain > 0:
            time.sleep(remain)

    def _resolve_output_path(self) -> Path:
        if self.cfg.output_csv:
            out = Path(self.cfg.output_csv)
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            out = Path(f"four9_pid_stability_sweep_{stamp}.csv")
        if out.suffix.lower() != ".csv":
            out = out.with_suffix(".csv")
        out = out.resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        return out

    def _write_config_csv(self, path: Path) -> None:
        cfg_items: Dict[str, object] = {
            "base_url": self.cfg.base_url,
            "port": self.cfg.port,
            "target_channel": self.cfg.target_channel,
            "read_channel": self.cfg.read_channel,
            "heater_channel": self.cfg.heater_channel,
            "poll_interval_s": self.cfg.poll_interval_s,
            "stability_window_s": self.cfg.stability_window_s,
            "stability_window_points": self.cfg.stability_window_points,
            "stable_deviation_threshold_k": self.cfg.stable_deviation_threshold_k,
            "target_tolerance_k": self.cfg.target_tolerance_k,
            "post_stable_wait_s": self.cfg.post_stable_wait_s,
            "stable_timeout_s": self.cfg.stable_timeout_s,
            "dwell_after_stable_s": self.cfg.dwell_after_stable_s,
            "pre_next_eval_delay_s": self.cfg.pre_next_eval_delay_s,
            "pre_next_eval_window_s": self.cfg.pre_next_eval_window_s,
            "setpoints_k": ", ".join(f"{x:g}" for x in self.cfg.setpoints_k),
        }
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["key", "value"])
            for key, value in cfg_items.items():
                writer.writerow([key, value])

    def _make_row(
        self,
        *,
        start_ts: datetime,
        target_k: float,
        status: str,
        elapsed_s: float,
        deviation_k: float,
        avg_temp_k: float,
        max_temp_before_first_in_range: float,
        max_ramp_rate: float,
        avg_heater_power: float,
        last_temp: float,
    ) -> Dict[str, object]:
        return {
            "start_time": start_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "target_temperature_k": target_k,
            "status": status,
            "time_to_stable_with_post_wait_s": elapsed_s,
            "deviation_60s_at_stable_k": deviation_k,
            "avg_temperature_60s_at_stable_k": avg_temp_k,
            "max_temp_before_first_in_range_k": (
                max_temp_before_first_in_range
                if max_temp_before_first_in_range != float("-inf")
                else float("nan")
            ),
            "max_temp_ramp_rate_start_to_first_cross_k_per_s": (
                max_ramp_rate if max_ramp_rate != float("-inf") else float("nan")
            ),
            "avg_heater_power_during_post_wait_w": avg_heater_power,
            "deviation_60s_before_next_setpoint_k": "",
            "avg_temperature_60s_before_next_setpoint_k": "",
            "last_temperature_k": last_temp,
        }

    @staticmethod
    def _make_hardware() -> Any:
        try:
            try:
                from .four9_hardware import Four9Hardware
            except ImportError:
                from four9_hardware import Four9Hardware
            return Four9Hardware()
        except ModuleNotFoundError as exc:
            if exc.name == "requests":
                raise RuntimeError(
                    "requests is required for Four9 communication. "
                    "Install with: pip install requests"
                ) from exc
            raise


class SweepStatusWindow:
    def __init__(self, cfg: TestConfig):
        try:
            from PyQt6 import QtCore, QtWidgets
        except ImportError as exc:
            raise RuntimeError("PyQt6 is required for --ui mode.") from exc

        self.QtCore = QtCore
        self.QtWidgets = QtWidgets
        self.cfg = cfg
        self.abort_event = threading.Event()
        self.queue: "queue.Queue[tuple[str, Any]]" = queue.Queue()
        self.running = False

        app = QtWidgets.QApplication.instance()
        self._owns_app = app is None
        self.app = app or QtWidgets.QApplication([])

        self.window = QtWidgets.QWidget()
        self.window.setWindowTitle("Four9 Sweep Status")
        self.window.resize(700, 520)

        self.values: Dict[str, str] = {
            "stage": "idle",
            "setpoint": "-/-",
            "target": "nan",
            "current": "nan",
            "delta_t": "nan",
            "deviation": "nan",
            "avg_temp": "nan",
            "heater": "nan",
            "ramp": "nan",
            "elapsed": "0 / 0",
            "message": "ready",
        }
        self.value_labels: Dict[str, Any] = {}

        self._build_ui()
        self.window.destroyed.connect(lambda: self.abort_event.set())

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self._consume_queue)

    def _build_ui(self) -> None:
        QtWidgets = self.QtWidgets
        QtCore = self.QtCore
        root_layout = QtWidgets.QVBoxLayout(self.window)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        root_layout.addLayout(grid)

        rows = [
            ("Stage", "stage"),
            ("Setpoint", "setpoint"),
            ("Target (K)", "target"),
            ("Current (K)", "current"),
            ("Delta T (K)", "delta_t"),
            ("Deviation (K)", "deviation"),
            ("Avg Temp (K)", "avg_temp"),
            ("Heater Power (W)", "heater"),
            ("Max Ramp (K/s)", "ramp"),
            ("Elapsed / Timeout (s)", "elapsed"),
            ("Message", "message"),
        ]
        for idx, (label, key) in enumerate(rows):
            label_widget = QtWidgets.QLabel(label)
            value_widget = QtWidgets.QLabel(self.values[key])
            value_widget.setTextInteractionFlags(
                QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
            )
            grid.addWidget(label_widget, idx, 0)
            grid.addWidget(value_widget, idx, 1)
            self.value_labels[key] = value_widget

        button_row = QtWidgets.QHBoxLayout()
        root_layout.addLayout(button_row)
        abort_button = QtWidgets.QPushButton("Abort")
        abort_button.clicked.connect(self._on_abort)
        button_row.addWidget(abort_button)
        button_row.addStretch(1)

        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        root_layout.addWidget(self.log)

    def _status_callback(self, status: Dict[str, Any]) -> None:
        self.queue.put(("status", status))

    def _log_callback(self, message: str) -> None:
        self.queue.put(("log", message))

    def _worker(self) -> None:
        try:
            runner = Four9PidStabilitySweep(
                self.cfg,
                status_callback=self._status_callback,
                log_callback=self._log_callback,
                abort_event=self.abort_event,
            )
            runner.run()
            self.queue.put(("done", "finished"))
        except Exception as exc:
            self.queue.put(("error", str(exc)))

    def _on_abort(self) -> None:
        self.abort_event.set()
        self.value_labels["message"].setText("abort requested")

    def _append_log(self, text: str) -> None:
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{timestamp}] {text}")

    @staticmethod
    def _fmt(value: Any, digits: int = 3) -> str:
        try:
            v = float(value)
            if math.isfinite(v):
                return f"{v:.{digits}f}"
        except Exception:
            pass
        return "nan"

    def _consume_queue(self) -> None:
        while True:
            try:
                kind, payload = self.queue.get_nowait()
            except queue.Empty:
                break

            if kind == "status":
                data: Dict[str, Any] = payload
                self.value_labels["stage"].setText(str(data.get("stage", "idle")))
                idx = data.get("setpoint_index")
                total = data.get("setpoint_total")
                if idx is not None and total is not None:
                    self.value_labels["setpoint"].setText(f"{idx}/{total}")
                self.value_labels["target"].setText(self._fmt(data.get("target_k")))
                self.value_labels["current"].setText(self._fmt(data.get("current_temp_k")))
                self.value_labels["delta_t"].setText(self._fmt(data.get("delta_t_k")))
                self.value_labels["deviation"].setText(self._fmt(data.get("deviation_k")))
                self.value_labels["avg_temp"].setText(self._fmt(data.get("avg_temp_k")))
                self.value_labels["heater"].setText(self._fmt(data.get("heater_power_w")))
                self.value_labels["ramp"].setText(
                    self._fmt(data.get("max_ramp_rate_k_per_s"), 4)
                )
                elapsed = self._fmt(data.get("elapsed_s"), 1)
                timeout = self._fmt(data.get("timeout_s"), 1)
                self.value_labels["elapsed"].setText(f"{elapsed} / {timeout}")
                if "message" in data:
                    self.value_labels["message"].setText(str(data["message"]))
            elif kind == "log":
                self._append_log(str(payload))
            elif kind == "error":
                self._append_log(f"ERROR: {payload}")
                self.value_labels["stage"].setText("error")
                self.value_labels["message"].setText(str(payload))
                self.running = False
            elif kind == "done":
                self._append_log("Sweep finished.")
                self.value_labels["stage"].setText("finished")
                self.value_labels["message"].setText("finished")
                self.running = False

        if not self.running:
            self.timer.stop()

    def run(self) -> None:
        self.running = True
        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()
        self.timer.start(200)
        self.window.show()
        if self._owns_app:
            self.app.exec()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Four9 PID temperature stability sweep (UI mode) to CSV"
    )
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--port", type=int, default=4949)

    parser.add_argument("--target-channel", type=int, default=2)
    parser.add_argument("--read-channel", type=int, default=2)
    parser.add_argument(
        "--heater-channel",
        type=int,
        default=-1,
        help="Heater channel for power averaging. -1 means use target-channel.",
    )

    parser.add_argument("--poll-interval-s", type=float, default=1.0)
    parser.add_argument("--stability-window-s", type=float, default=60.0)
    parser.add_argument("--stable-deviation-threshold-k", type=float, default=0.4)
    parser.add_argument("--target-tolerance-k", type=float, default=0.2)
    parser.add_argument("--post-stable-wait-s", type=float, default=60.0)
    parser.add_argument("--stable-timeout-s", type=float, default=20 * 60.0)

    parser.add_argument("--dwell-after-stable-s", type=float, default=5 * 60.0)
    parser.add_argument("--pre-next-eval-delay-s", type=float, default=4 * 60.0)
    parser.add_argument("--pre-next-eval-window-s", type=float, default=60.0)

    parser.add_argument(
        "--setpoints-k",
        type=str,
        default="",
        help="Comma-separated setpoints in K. If omitted, use default schedule.",
    )
    parser.add_argument("--output-csv", type=str, default="")
    return parser.parse_args()


def build_config(args: argparse.Namespace) -> TestConfig:
    setpoints = build_default_setpoints()
    if args.setpoints_k.strip():
        setpoints = parse_setpoints(args.setpoints_k)

    heater_channel = args.heater_channel
    if heater_channel < 0:
        heater_channel = args.target_channel

    cfg = TestConfig(
        base_url=args.base_url,
        port=args.port,
        target_channel=args.target_channel,
        read_channel=args.read_channel,
        heater_channel=heater_channel,
        poll_interval_s=args.poll_interval_s,
        stability_window_s=args.stability_window_s,
        stable_deviation_threshold_k=args.stable_deviation_threshold_k,
        target_tolerance_k=args.target_tolerance_k,
        post_stable_wait_s=args.post_stable_wait_s,
        stable_timeout_s=args.stable_timeout_s,
        dwell_after_stable_s=args.dwell_after_stable_s,
        pre_next_eval_delay_s=args.pre_next_eval_delay_s,
        pre_next_eval_window_s=args.pre_next_eval_window_s,
        output_csv=args.output_csv,
        setpoints_k=setpoints,
    )
    _validate_config(cfg)
    return cfg


def _validate_config(cfg: TestConfig) -> None:
    for ch in (cfg.target_channel, cfg.read_channel, cfg.heater_channel):
        if ch < 0 or ch > 5:
            raise ValueError(f"Channel must be 0..5, got {ch}")
    if cfg.poll_interval_s <= 0:
        raise ValueError("poll_interval_s must be > 0")
    if cfg.stability_window_s <= 0:
        raise ValueError("stability_window_s must be > 0")
    if cfg.post_stable_wait_s < 0:
        raise ValueError("post_stable_wait_s must be >= 0")
    if cfg.stable_timeout_s <= 0:
        raise ValueError("stable_timeout_s must be > 0")
    if cfg.dwell_after_stable_s < 0:
        raise ValueError("dwell_after_stable_s must be >= 0")
    if cfg.pre_next_eval_delay_s < 0 or cfg.pre_next_eval_window_s < 0:
        raise ValueError("pre-next evaluation durations must be >= 0")


def main() -> int:
    args = parse_args()
    cfg = build_config(args)

    print("Setpoints (K):", ", ".join(f"{x:g}" for x in cfg.setpoints_k))
    print(
        f"Stability criteria: |T-target| <= {cfg.target_tolerance_k} K, "
        f"dev({cfg.stability_window_s:.0f}s) < {cfg.stable_deviation_threshold_k} K, "
        f"post-wait {cfg.post_stable_wait_s:.0f}s, timeout {cfg.stable_timeout_s:.0f}s, "
        f"poll={cfg.poll_interval_s:.1f}s"
    )

    try:
        SweepStatusWindow(cfg).run()
    except KeyboardInterrupt:
        print("Interrupted by user.")
        return 130
    except Exception as exc:
        print(f"Failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
