"""MFLI node access. Construction/import performs no hardware operations.

One logic worker owns this object and its client for their entire lifetime.
OSC numbers identify demodulator-associated tones, not oscillator assignments.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
import math
import re
import threading
import time
from typing import Callable

SERVER_PORT = 8004
RAMP_RATE_V_PER_SECOND = 10.0
RAMP_UPDATES_PER_SECOND = 100.0


def parse_address(address: str) -> tuple[str, str, int]:
    """Accept plain DEV12345 or DEV12345, IP without enclosing brackets."""
    if not isinstance(address, str):
        raise ValueError("MFLI address must be text: DEV12345, 192.168.1.2")
    text = address.strip()
    parts = [part.strip() for part in text.split(",")]
    if len(parts) not in (1, 2) or any(not part for part in parts):
        raise ValueError("Use DEV12345 or DEV12345, IP in the address cell.")
    device, host, port = validate_config(parts[0], "", SERVER_PORT)
    if len(parts) == 2:
        try:
            host = str(ipaddress.ip_address(parts[1]))
        except ValueError as exc:
            raise ValueError(f"Invalid MFLI IP address: {parts[1]!r}") from exc
    return device, host, port


def validate_config(device: str, host: str, port: int) -> tuple[str, str, int]:
    device = device.strip().lower()
    if not re.fullmatch(r"dev[0-9]+", device):
        raise ValueError("Set an explicit MFLI serial, for example DEV30037.")
    host = host.strip() or f"mf-{device}"
    if any(char.isspace() for char in host) or "://" in host or "/" in host:
        raise ValueError("Use a server hostname or IP address, without a URL or path.")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("Server port must be an integer between 1 and 65535.")
    return device, host, port


def ensure_device_connected(daq, device: str) -> None:
    connected = {item.strip().lower() for item in daq.getString("/zi/devices/connected").split(",")}
    if device in connected:
        return
    devices = json.loads(daq.getString("/zi/devices"))
    info = next((value for key, value in devices.items() if key.lower() == device), None)
    if info is None:
        raise ValueError(f"{device} is not visible to this Data Server. Check serial and host.")
    undefined = {"", "none", "unknown"}
    interface = info.get("INTERFACE", "").strip()
    if interface.lower() in undefined:
        available = [item.strip() for item in info.get("INTERFACES", "").split(",")
                     if item.strip().lower() not in undefined]
        if not available:
            raise ValueError(f"No available server interface for {device}.")
        interface = next((item for item in available if item.lower() == "1gbe"), available[0])
    daq.connectDevice(device, interface)


class TransportError(RuntimeError):
    """An API operation failed; require explicit reconnect before further work."""


class SampleError(ValueError):
    """One demodulator is unavailable or returned unusable data."""


@dataclass(frozen=True)
class ToneSettings:
    channel: int
    amplitude: float
    phase: float
    oscillator: int
    frequency: float


@dataclass(frozen=True)
class Settings:
    tones: tuple[ToneSettings, ...]
    offset: float
    output_range: float


@dataclass(frozen=True)
class DemodSample:
    channel: int
    timestamp: int
    X: float
    Y: float
    R: float
    theta: float
    unit: str
    frequency: float


@dataclass(frozen=True)
class MonitorBatch:
    samples: dict[int, DemodSample]
    problems: dict[int, str]


def finite(value: float, label: str) -> float:
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite.")
    return value


def channel_index(channel: int) -> int:
    if type(channel) is not int or not 1 <= channel <= 4:
        raise ValueError("Channel must be an integer from 1 to 4.")
    return channel - 1


class MFLIHardware:
    def __init__(self, server_factory: Callable | None = None,
                 *, read_timeout: float = 5.0):
        self._factory = server_factory
        self.read_timeout = finite(read_timeout, "Read timeout")
        if self.read_timeout <= 0:
            raise ValueError("Read timeout must be positive.")
        self._daq = None
        self.device = ""
        self.cancel = threading.Event()
        self._last_seen: dict[int, tuple[int, float]] = {}

    @property
    def connected(self) -> bool:
        return self._daq is not None

    def _call(self, method: str, *args):
        if self._daq is None:
            raise RuntimeError("MFLI is disconnected.")
        try:
            return getattr(self._daq, method)(*args)
        except Exception as exc:
            node = str(args[0]) if args else "client"
            raise TransportError(f"{method} {node}: {exc}") from exc

    def _path(self, node: str) -> str:
        return f"/{self.device}/{node}"

    def _double(self, node: str) -> float:
        return finite(self._call("getDouble", self._path(node)), node)

    def _integer(self, node: str) -> int:
        return int(self._call("getInt", self._path(node)))

    def connect(self, device: str, host: str, port: int) -> tuple[dict, Settings]:
        device, host, port = validate_config(device, host, port)
        if self.connected:
            raise RuntimeError("Disconnect the existing client before connecting again.")
        factory = self._factory
        if factory is None:
            try:
                import zhinst.core
            except ImportError as exc:
                raise RuntimeError(
                    "Zurich Core is unavailable. Use the ZMeter environment with "
                    "zhinst-core==26.7.1.4 installed."
                ) from exc
            factory = zhinst.core.ziDAQServer
        self.cancel.clear()
        self.device = device
        try:
            self._daq = factory(host, port, 6, allow_version_mismatch=True)
            ensure_device_connected(self._daq, device)
            kind = self._call("getString", self._path("features/devtype")).strip()
            if kind.upper() != "MFLI":
                raise ValueError(f"Expected MFLI, received {kind!r}.")
            identity = {
                "device": device, "host": host, "port": port,
                "type": kind,
                "serial": self._call("getString", self._path("features/serial")),
                "options": self._call("getString", self._path("features/options")),
                "api": self._call("version"),
                "server": self._call("getString", "/zi/about/version"),
            }
            if not identity["serial"].strip():
                raise ValueError("Instrument returned an empty serial.")
            settings = self.refresh_settings()  # Also verifies all four tone nodes.
            self._last_seen.clear()
            return identity, settings
        except Exception as exc:
            try:
                self.disconnect()
            except Exception as cleanup:
                raise RuntimeError(f"Connection failed: {exc}; cleanup also failed: {cleanup}") from exc
            raise

    def disconnect(self) -> None:
        """Release only our API client. Retain a failed handle for a cleanup retry."""
        if self._daq is not None:
            self._call("disconnect")
            self._daq = None
        self._last_seen.clear()

    def refresh_settings(self) -> Settings:
        tones = []
        for i in range(4):
            tones.append(ToneSettings(
                i + 1, self._double(f"sigouts/0/amplitudes/{i}"),
                self._double(f"demods/{i}/phaseshift"),
                self._integer(f"demods/{i}/oscselect") + 1,
                self._double(f"demods/{i}/freq"),
            ))
        output_range = self._double("sigouts/0/range")
        if output_range <= 0:
            raise ValueError("Instrument output range must be positive.")
        return Settings(tuple(tones), self._double("sigouts/0/offset"), output_range)

    def _check_headroom(self, channel: int | None, value: float) -> None:
        # Read every contribution even if its output enable is currently off.
        # This conservative check also covers LabOne changes since UI refresh.
        amplitudes = [self._double(f"sigouts/0/amplitudes/{i}") for i in range(4)]
        offset = self._double("sigouts/0/offset")
        output_range = self._double("sigouts/0/range")
        if output_range <= 0:
            raise ValueError("Instrument output range must be positive.")
        if channel is None:
            offset = value
        else:
            amplitudes[channel_index(channel)] = value
        if sum(abs(a) for a in amplitudes) + abs(offset) > output_range:
            raise ValueError(
                f"Combined peak amplitudes plus DC offset exceed {output_range:g} V range. "
                "Reduce the requested value or review settings in LabOne."
            )

    def write_amplitude(self, channel: int, value: float) -> float:
        i = channel_index(channel)
        value = finite(value, "Amplitude")
        return self._ramp_voltage(f"sigouts/0/amplitudes/{i}", channel, value)

    def write_phase(self, channel: int, value: float) -> float:
        i = channel_index(channel)
        value = finite(value, "Phase")
        if not -180 <= value <= 180:
            raise ValueError("Phase must be between -180 and 180 degrees.")
        return self._write(f"demods/{i}/phaseshift", value)

    def write_offset(self, value: float) -> float:
        value = finite(value, "DC offset")
        return self._ramp_voltage("sigouts/0/offset", None, value)

    def _ramp_voltage(self, node: str, channel: int | None, target: float) -> float:
        """Ramp every amplitude/DC write on the owning worker, without catch-up bursts."""
        if self.cancel.is_set():
            raise InterruptedError(f"MFLI ramp cancelled before starting: {node}.")
        start = self._double(node)  # Never assume zero or use an old UI value.
        self._check_headroom(channel, target)  # Reject invalid targets before any write.
        last_ack = start

        def check_cancelled():
            if self.cancel.is_set():
                raise InterruptedError(
                    f"MFLI ramp cancelled: {node}; last acknowledged value {last_ack:g} V. "
                    "Refresh settings before continuing."
                )

        check_cancelled()
        interval = 1.0 / RAMP_UPDATES_PER_SECOND
        step = RAMP_RATE_V_PER_SECOND * interval
        distance = abs(target - start)
        direction = 1 if target > start else -1
        count = math.ceil(distance / step)
        for index in range(1, count + 1):
            # Wait before every step, including the first and the final partial
            # step. API overhead may slow the ramp; never compensate by jumping.
            self.cancel.wait(interval)
            check_cancelled()
            next_value = target if index == count else start + direction * index * step
            self._check_headroom(channel, next_value)
            check_cancelled()  # Stop requests may arrive during the settings reads.
            last_ack = self._write(node, next_value)
            check_cancelled()  # A native write may finish after an abort request.
        return last_ack

    def _write(self, node: str, value: float) -> float:
        try:
            result = self._call("syncSetDouble", self._path(node), value)
        except TransportError as exc:
            raise TransportError(f"Write may have applied; {exc}") from exc
        try:
            return finite(result, f"Acknowledgement for {node}")
        except (TypeError, ValueError, OverflowError) as exc:
            raise TransportError(f"Write may have applied; invalid acknowledgement: {node}") from exc

    def _stream_info(self, channel: int) -> tuple[float, str]:
        i = channel_index(channel)
        if not self._integer(f"demods/{i}/enable"):
            raise SampleError(f"Demodulator {channel}: streaming is disabled in LabOne.")
        rate = self._call("getDouble", self._path(f"demods/{i}/rate"))
        if not math.isfinite(rate) or rate <= 0:
            raise SampleError(f"Demodulator {channel}: sample rate must be finite and positive.")
        if self._integer(f"demods/{i}/trigger") != 0:
            raise SampleError(f"Demodulator {channel}: select Continuous trigger in LabOne.")
        source = self._integer(f"demods/{i}/adcselect")
        return rate, {0: "V", 1: "A"}.get(source, "native units")

    def _sample(self, channel: int, unit: str) -> DemodSample:
        i = channel_index(channel)
        raw = self._call("getSample", self._path(f"demods/{i}/sample"))
        try:
            stamp = int(raw["timestamp"][-1])  # Preserve full 64-bit precision.
            x = finite(raw["x"][-1], "X")
            y = finite(raw["y"][-1], "Y")
            frequency = finite(raw["frequency"][-1], "Frequency")
            r = finite(math.hypot(x, y), "R")
        except (KeyError, IndexError, TypeError, ValueError, OverflowError) as exc:
            raise SampleError(f"Demodulator {channel}: invalid sample ({exc}).") from exc
        return DemodSample(channel, stamp, x, y, r,
                           math.degrees(math.atan2(y, x)) if x or y else math.nan,
                           unit, frequency)

    def monitor(self) -> MonitorBatch:
        samples, problems = {}, {}
        for channel in range(1, 5):
            if self.cancel.is_set():
                break
            try:
                rate, unit = self._stream_info(channel)
                sample = self._sample(channel, unit)
                now = time.monotonic()
                previous = self._last_seen.get(channel)
                if previous and sample.timestamp <= previous[0]:
                    if sample.timestamp < previous[0]:
                        raise SampleError(f"Demodulator {channel}: timestamp moved backwards; reconnect.")
                    if now - previous[1] >= max(self.read_timeout, 3 / rate):
                        raise SampleError(f"Demodulator {channel}: stale data; check rate/trigger in LabOne.")
                    continue  # Repeated sample is not a new plot point.
                self._last_seen[channel] = sample.timestamp, now
                samples[channel] = sample
            except SampleError as exc:
                problems[channel] = str(exc)
        return MonitorBatch(samples, problems)

    def read_fresh(self, channel: int) -> DemodSample:
        _, unit = self._stream_info(channel)
        baseline = self._sample(channel, unit).timestamp
        deadline = time.monotonic() + self.read_timeout
        while not self.cancel.wait(0.01):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Demodulator {channel}: no fresh sample within {self.read_timeout:g} s.")
            sample = self._sample(channel, unit)
            if sample.timestamp > baseline:
                return sample
        raise InterruptedError("MFLI read cancelled for disconnect/shutdown.")
