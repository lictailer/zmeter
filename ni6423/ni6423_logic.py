import argparse
import math
import threading
from collections import deque
from typing import Deque, Dict, Optional, Set

from PyQt6 import QtCore

try:
    from .ni6423_hardware import NI6423Hardware
except ImportError:
    from ni6423_hardware import NI6423Hardware



class NI6423Logic(QtCore.QThread):
    """
    Logic layer for NI USB-6423.

    Scan-facing methods:
    - set_AO0..set_AO3(val)
    - get_AI0..get_AI31()
    - get_counter0()
    - get_AO0..get_AO3()  # AO readback from AI28..AI31
    """

    sig_new_write = QtCore.pyqtSignal(object)          # [channel_name, value]
    sig_new_read = QtCore.pyqtSignal(object)           # [channel_name, value]
    sig_name = QtCore.pyqtSignal(object)               # active device name or "None"
    sig_connected = QtCore.pyqtSignal(object)          # bool
    sig_integrating_time = QtCore.pyqtSignal(object)   # compatibility signal
    sig_ao_integrating_time = QtCore.pyqtSignal(object)
    sig_counter_integrating_time = QtCore.pyqtSignal(object)
    sig_error = QtCore.pyqtSignal(object)              # string

    AO_CHANNELS = [f"AO{i}" for i in range(4)]
    AI_CHANNELS = [f"AI{i}" for i in range(32)]
    COUNTER_CHANNELS = ["Ctr0"]
    AO_FEEDBACK_MAP = {
        "AO0": "AI28",
        "AO1": "AI29",
        "AO2": "AI30",
        "AO3": "AI31",
    }

    def __init__(self):
        super().__init__()
        self._lock = threading.RLock()
        self._feedback_lock = threading.Lock()
        self._feedback_stop = threading.Event()

        self._feedback_queue: Deque[str] = deque()
        self._feedback_queued: Set[str] = set()
        self._feedback_worker: Optional[threading.Thread] = None

        self.dev_name = ""
        self.daq: Optional[NI6423Hardware] = None
        self.is_initialized = False

        self.ao_integrating_time = 1e-3
        self.counter_integrating_time = 1e-3
        self.integrating_time = 1e-3  # backward compatibility

        self.job = ""
        self.next_ao_channel = "AO0"
        self.next_ai_channel = "AI0"
        self.next_counter_channel = "Ctr0"
        self.next_feedback_ao_channel = "AO0"

        self.target_AO: Dict[str, float] = {
            channel: 0.0 for channel in self.AO_CHANNELS
        }
        self.ao_feedback_cache: Dict[str, Optional[float]] = {
            channel: None for channel in self.AO_CHANNELS
        }

    # ------------------------ lifecycle -------------------------
    def initialize(self, dev_name: str) -> None:
        with self._lock:
            if self.is_initialized:
                self.close()

            self.dev_name = dev_name
            self.daq = NI6423Hardware(device_name=dev_name)
            try:
                self.daq.connect()
            except Exception as exc:
                self.daq = None
                self.sig_error.emit(f"Failed to connect NI6423 ({dev_name}): {exc}")
                raise

            self.is_initialized = True
            self._feedback_stop.clear()
            self._clear_feedback_queue_locked()

        self.sig_name.emit(dev_name)
        self.sig_connected.emit(True)
        self.sig_ao_integrating_time.emit(self.ao_integrating_time)
        self.sig_counter_integrating_time.emit(self.counter_integrating_time)
        self.sig_integrating_time.emit(self.integrating_time)

    def close(self) -> None:
        with self._lock:
            if not self.is_initialized:
                self.sig_name.emit("None")
                self.sig_connected.emit(False)
                return

            self._feedback_stop.set()

        worker = self._feedback_worker
        if worker is not None and worker.is_alive():
            worker.join(timeout=1.0)

        with self._lock:
            try:
                if self.daq is not None:
                    self.daq.disconnect()
            finally:
                self.daq = None
                self.is_initialized = False
                self._clear_feedback_queue_locked()
                self._feedback_worker = None

        self.sig_name.emit("None")
        self.sig_connected.emit(False)

    def stop(self):
        if self.isRunning():
            self.wait()

    # --------------------- integration helpers ------------------
    def update_integrating_time(self, time_s: float) -> float:
        validated = self._validate_integrating_time(time_s)
        with self._lock:
            self.ao_integrating_time = validated
            self.counter_integrating_time = validated
            self.integrating_time = validated
        self.sig_ao_integrating_time.emit(validated)
        self.sig_counter_integrating_time.emit(validated)
        self.sig_integrating_time.emit(validated)
        return validated

    def update_ao_integrating_time(self, time_s: float) -> float:
        validated = self._validate_integrating_time(time_s)
        with self._lock:
            self.ao_integrating_time = validated
            self.integrating_time = validated
        self.sig_ao_integrating_time.emit(validated)
        self.sig_integrating_time.emit(validated)
        return validated

    def update_counter_integrating_time(self, time_s: float) -> float:
        validated = self._validate_integrating_time(time_s)
        with self._lock:
            self.counter_integrating_time = validated
        self.sig_counter_integrating_time.emit(validated)
        return validated

    # ---------------------- selector helpers --------------------
    def update_ao_target(self, channel: str, value: float) -> None:
        channel = channel.upper()
        if channel not in self.AO_CHANNELS:
            raise ValueError(f"Unknown AO channel '{channel}'.")
        with self._lock:
            self.target_AO[channel] = float(value)

    def update_next_ao_channel(self, channel: str) -> None:
        channel = channel.upper()
        if channel not in self.AO_CHANNELS:
            raise ValueError(f"Unknown AO channel '{channel}'.")
        self.next_ao_channel = channel

    def update_next_feedback_ao_channel(self, channel: str) -> None:
        channel = channel.upper()
        if channel not in self.AO_CHANNELS:
            raise ValueError(f"Unknown AO channel '{channel}'.")
        self.next_feedback_ao_channel = channel

    def update_next_ai_channel(self, channel: str) -> None:
        channel = channel.upper()
        if channel not in self.AI_CHANNELS:
            raise ValueError(f"Unknown AI channel '{channel}'.")
        self.next_ai_channel = channel

    def update_next_counter_channel(self, channel: str) -> None:
        normalized = channel.capitalize()
        if normalized not in self.COUNTER_CHANNELS:
            raise ValueError(f"Unknown counter channel '{channel}'.")
        self.next_counter_channel = normalized

    # --------------------- async feedback API -------------------
    def request_ao_feedback_async(self, ao_channel: str) -> None:
        ao_channel = ao_channel.upper()
        if ao_channel not in self.AO_CHANNELS:
            raise ValueError(f"Unknown AO channel '{ao_channel}'.")
        self._enqueue_feedback_channel(ao_channel)

    def request_all_ao_feedback_async(self) -> None:
        for ao_channel in self.AO_CHANNELS:
            self._enqueue_feedback_channel(ao_channel)

    # --------------------- internal I/O ------------------------
    def write_ao_channel(self, ao_channel: str, value: float) -> float:
        ao_channel = ao_channel.upper()
        if ao_channel not in self.AO_CHANNELS:
            raise ValueError(f"Unknown AO channel '{ao_channel}'.")

        try:
            with self._lock:
                daq = self._require_daq()
                daq.write_analog_output(ao_channel, float(value))
                self.target_AO[ao_channel] = float(value)
        except Exception as exc:
            self.sig_error.emit(f"AO write failed ({ao_channel}): {exc}")
            raise

        self.sig_new_write.emit([ao_channel, float(value)])
        self._enqueue_feedback_channel(ao_channel)
        return float(value)

    def read_ai_channel(
        self,
        ai_channel: str,
        emit_name: Optional[str] = None,
        integration_time: Optional[float] = None,
    ) -> float:
        ai_channel = ai_channel.upper()
        if ai_channel not in self.AI_CHANNELS:
            raise ValueError(f"Unknown AI channel '{ai_channel}'.")

        with self._lock:
            if integration_time is None:
                integration_time = self.ao_integrating_time

        try:
            with self._lock:
                daq = self._require_daq()
                value = daq.read_analog_input(ai_channel, integration_time)
        except Exception as exc:
            self.sig_error.emit(f"AI read failed ({ai_channel}): {exc}")
            raise

        key = emit_name or ai_channel
        if key in self.AO_CHANNELS:
            with self._lock:
                self.ao_feedback_cache[key] = value

        self.sig_new_read.emit([key, value])
        return value

    def read_counter_channel(
        self,
        counter_channel: str,
        emit_name: Optional[str] = None,
        integration_time: Optional[float] = None,
    ) -> float:
        counter_channel = counter_channel.capitalize()
        if counter_channel not in self.COUNTER_CHANNELS:
            raise ValueError(f"Unknown counter channel '{counter_channel}'.")

        with self._lock:
            if integration_time is None:
                integration_time = self.counter_integrating_time

        try:
            with self._lock:
                daq = self._require_daq()
                value = daq.read_sample_counter(integration_time)
        except Exception as exc:
            self.sig_error.emit(f"Counter read failed ({counter_channel}): {exc}")
            raise

        self.sig_new_read.emit([emit_name or counter_channel, value])
        return value

    def read_ao_feedback_channel(self, ao_channel: str) -> float:
        ao_channel = ao_channel.upper()
        if ao_channel not in self.AO_CHANNELS:
            raise ValueError(f"Unknown AO channel '{ao_channel}'.")

        with self._lock:
            integration_time = self.ao_integrating_time
        ai_channel = self.AO_FEEDBACK_MAP[ao_channel]
        value = self.read_ai_channel(
            ai_channel, emit_name=ao_channel, integration_time=integration_time
        )
        with self._lock:
            self.ao_feedback_cache[ao_channel] = value
        return value

    # ----------------------- thread job ------------------------
    def run(self):
        if not self.is_initialized:
            return

        try:
            if self.job == "write_AO":
                self.write_ao_channel(
                    self.next_ao_channel, self.target_AO[self.next_ao_channel]
                )
            elif self.job == "read_AI":
                self.read_ai_channel(self.next_ai_channel)
            elif self.job == "read_counter":
                counter_name = self.next_counter_channel.replace("Ctr", "counter")
                self.read_counter_channel(
                    self.next_counter_channel,
                    emit_name=counter_name,
                )
            elif self.job == "read_AO_feedback":
                self.read_ao_feedback_channel(self.next_feedback_ao_channel)
            elif self.job == "refresh_all_AO_feedback":
                for ao_channel in self.AO_CHANNELS:
                    self.read_ao_feedback_channel(ao_channel)
        finally:
            self.job = ""

    # ----------------- async feedback worker -------------------
    def _enqueue_feedback_channel(self, ao_channel: str) -> None:
        with self._feedback_lock:
            if not self.is_initialized:
                return
            if ao_channel not in self._feedback_queued:
                self._feedback_queue.append(ao_channel)
                self._feedback_queued.add(ao_channel)
            worker_running = (
                self._feedback_worker is not None and self._feedback_worker.is_alive()
            )
            if worker_running:
                return

            self._feedback_worker = threading.Thread(
                target=self._feedback_worker_loop,
                name="ni6423-feedback-worker",
                daemon=True,
            )
            self._feedback_worker.start()

    def _feedback_worker_loop(self) -> None:
        while not self._feedback_stop.is_set():
            with self._feedback_lock:
                if not self._feedback_queue:
                    break
                ao_channel = self._feedback_queue.popleft()
                self._feedback_queued.discard(ao_channel)

            try:
                self.read_ao_feedback_channel(ao_channel)
            except Exception as exc:
                self.sig_error.emit(
                    f"AO feedback read failed ({ao_channel}): {exc}"
                )

        with self._feedback_lock:
            self._feedback_worker = None

    def _clear_feedback_queue_locked(self) -> None:
        with self._feedback_lock:
            self._feedback_queue.clear()
            self._feedback_queued.clear()

    # ------------------------ utilities ------------------------
    def _require_daq(self) -> NI6423Hardware:
        if self.daq is None or not self.is_initialized:
            raise RuntimeError("NI6423 is not initialized. Call initialize() first.")
        return self.daq

    def _validate_integrating_time(self, time_s: float) -> float:
        minimum = NI6423Hardware.MIN_INTEGRATION_S
        step = NI6423Hardware.INTEGRATION_STEP_S

        if time_s < minimum:
            raise ValueError(f"Integrating time must be >= {minimum} s.")

        steps = round(time_s / step)
        expected = steps * step
        if not math.isclose(time_s, expected, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError("Integrating time must use 100 us steps.")
        return float(expected)


def _make_set_ao(index: int):
    channel = f"AO{index}"

    def setter(self: NI6423Logic, value: float) -> float:
        return self.write_ao_channel(channel, value)

    setter.__name__ = f"set_AO{index}"
    return setter


def _make_get_ai(index: int):
    channel = f"AI{index}"

    def getter(self: NI6423Logic) -> float:
        return self.read_ai_channel(channel)

    getter.__name__ = f"get_AI{index}"
    return getter


def _make_get_counter(index: int):
    channel = f"Ctr{index}"
    emit_name = f"counter{index}"

    def getter(self: NI6423Logic) -> float:
        return self.read_counter_channel(channel, emit_name=emit_name)

    getter.__name__ = f"get_counter{index}"
    return getter


def _make_get_ao_feedback(index: int):
    ao_name = f"AO{index}"

    def getter(self: NI6423Logic) -> float:
        return self.read_ao_feedback_channel(ao_name)

    getter.__name__ = f"get_AO{index}"
    return getter


for _i in range(4):
    setattr(NI6423Logic, f"set_AO{_i}", _make_set_ao(_i))

for _i in range(32):
    setattr(NI6423Logic, f"get_AI{_i}", _make_get_ai(_i))

setattr(NI6423Logic, "get_counter0", _make_get_counter(0))

for _i in range(4):
    setattr(NI6423Logic, f"get_AO{_i}", _make_get_ao_feedback(_i))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Brief smoke test for NI6423Logic: connection, AO, AI, counter."
    )
    parser.add_argument("--device", default="Dev1", help="NI device name, e.g. Dev1")
    parser.add_argument("--ao-channel", default="AO0", help="AO channel, e.g. AO0")
    parser.add_argument("--ao-value", type=float, default=0.1, help="AO value in volts")
    parser.add_argument("--ai-channel", default="AI0", help="AI channel, e.g. AI0")
    parser.add_argument(
        "--counter-channel", default="Ctr0", help="Counter channel, e.g. Ctr0"
    )
    parser.add_argument(
        "--ao-integration-time",
        type=float,
        default=1e-3,
        help="AO/AI integration time in seconds (>=100us and 100us step).",
    )
    parser.add_argument(
        "--counter-integration-time",
        type=float,
        default=1e-3,
        help="Counter integration time in seconds (>=100us and 100us step).",
    )
    args = parser.parse_args()

    logic = NI6423Logic()
    logic.sig_error.connect(lambda msg: print(f"[SIG_ERROR] {msg}"))
    logic.sig_name.connect(lambda msg: print(f"[SIG_NAME] {msg}"))
    logic.sig_connected.connect(lambda state: print(f"[SIG_CONNECTED] {state}"))
    logic.sig_new_write.connect(lambda evt: print(f"[SIG_WRITE] {evt}"))
    logic.sig_new_read.connect(lambda evt: print(f"[SIG_READ] {evt}"))
    logic.sig_ao_integrating_time.connect(
        lambda t: print(f"[SIG_AO_INTEGRATING_TIME] {t:.6g} s")
    )
    logic.sig_counter_integrating_time.connect(
        lambda t: print(f"[SIG_COUNTER_INTEGRATING_TIME] {t:.6g} s")
    )

    try:
        print(f"[TEST] initialize({args.device})")
        logic.initialize(args.device)
        print("[PASS] connection")

        print(f"[TEST] update_ao_integrating_time({args.ao_integration_time})")
        logic.update_ao_integrating_time(args.ao_integration_time)
        print(
            f"[TEST] update_counter_integrating_time({args.counter_integration_time})"
        )
        logic.update_counter_integrating_time(args.counter_integration_time)

        ao_setter = getattr(logic, f"set_{args.ao_channel.upper()}")
        print(f"[TEST] set_{args.ao_channel.upper()}({args.ao_value})")
        ao_setter(args.ao_value)
        print("[PASS] AO write")

        ai_getter = getattr(logic, f"get_{args.ai_channel.upper()}")
        print(f"[TEST] get_{args.ai_channel.upper()}()")
        ai_val = ai_getter()
        print(f"[PASS] AI read -> {ai_val:+.6f} V")

        counter_name = args.counter_channel.capitalize()
        if counter_name != "Ctr0":
            raise ValueError(
                "Only Ctr0 is supported in the current counter hardware mode."
            )
        print("[TEST] get_counter0()")
        count_rate = logic.get_counter0()
        print(f"[PASS] counter read -> {count_rate:.3f} Hz")

        print("[TEST] request_all_ao_feedback_async()")
        logic.request_all_ao_feedback_async()

    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}")
        raise
    finally:
        print("[TEST] close()")
        logic.close()
        print("[PASS] disconnected")
