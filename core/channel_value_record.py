"""Last-value record of channels written or read through the main window.

The main window records every successful ``write_info`` and ``read_info``
call and the start/end scan snapshots.  Values set from a device's own panel
are not seen, so the record is a reference, not a guarantee.

Every entry carries a sequence number from one shared counter, so callers
can tell whether a channel was read after another one was written.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

ORIGIN_WRITE = "write"
ORIGIN_READ = "read"
ORIGIN_SNAPSHOT = "snapshot"


@dataclass(frozen=True, slots=True)
class ChannelValue:
    channel: str
    value: Any
    time: float
    origin: str
    seq: int


def _plain_number(value):
    """Return a float for numeric values, the value itself otherwise.

    An array read (a spectrum or camera frame) is recorded as NaN: the record
    keeps scalars only, and holding every frame would keep it in memory.
    """

    if isinstance(value, bool):
        return value
    if isinstance(value, (list, tuple)) or getattr(value, "ndim", 0) > 0:
        if len(value) != 1 or getattr(value, "size", 1) != 1:
            return float("nan")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    return number


class ChannelValueRecord:
    """Thread-safe ``{channel: newest value}`` record with ordering."""

    def __init__(self):
        self._lock = threading.Lock()
        self._seq = 0
        self._latest: dict[str, ChannelValue] = {}
        self._latest_write: dict[str, ChannelValue] = {}
        self._latest_reading: dict[str, ChannelValue] = {}
        self._invalidated: dict[str, int] = {}

    def _next_seq_locked(self) -> int:
        self._seq += 1
        return self._seq

    def record(self, channel: str, value, origin: str) -> ChannelValue:
        channel = str(channel)
        with self._lock:
            entry = ChannelValue(
                channel=channel,
                value=_plain_number(value),
                time=time.time(),
                origin=str(origin),
                seq=self._next_seq_locked(),
            )
            self._latest[channel] = entry
            if origin == ORIGIN_WRITE:
                self._latest_write[channel] = entry
            else:
                self._latest_reading[channel] = entry
            return entry

    def record_write(self, channel: str, value) -> ChannelValue:
        return self.record(channel, value, ORIGIN_WRITE)

    def record_read(self, channel: str, value) -> ChannelValue:
        return self.record(channel, value, ORIGIN_READ)

    def record_snapshot(self, snapshot: Mapping | None) -> int:
        """Record numeric fields of a setup-capture snapshot.

        ``snapshot`` is ``{"devices": {device_id: {"fields": {name: value}}}}``;
        each field becomes channel ``<device_id>_<name>``.  Returns the number
        of values recorded.
        """

        if not isinstance(snapshot, Mapping):
            return 0
        devices = snapshot.get("devices") or {}
        count = 0
        if not isinstance(devices, Mapping):
            return 0
        for device_id, entry in devices.items():
            if not isinstance(entry, Mapping):
                continue
            fields = entry.get("fields") or {}
            if not isinstance(fields, Mapping):
                continue
            for name, value in fields.items():
                if isinstance(value, Mapping):
                    continue  # read error
                number = _plain_number(value)
                if not isinstance(number, float) or not math.isfinite(number):
                    continue
                self.record(f"{device_id}_{name}", number, ORIGIN_SNAPSHOT)
                count += 1
        return count

    def latest(self, channel: str) -> ChannelValue | None:
        with self._lock:
            return self._latest.get(str(channel))

    def latest_write(self, channel: str) -> ChannelValue | None:
        with self._lock:
            return self._latest_write.get(str(channel))

    def latest_reading(self, channel: str) -> ChannelValue | None:
        """Newest read or snapshot value of ``channel``."""

        with self._lock:
            return self._latest_reading.get(str(channel))

    def invalidate(self, channels: Iterable[str]) -> None:
        """Make current readings of ``channels`` count as stale."""

        with self._lock:
            mark = self._next_seq_locked()
            for channel in channels:
                self._invalidated[str(channel)] = mark

    def fresh_reading(self, read_channel: str, set_channel: str | None = None):
        """Newest reading of ``read_channel`` if it is still trustworthy.

        A reading is stale when ``read_channel`` was invalidated after it,
        or when ``set_channel`` was written after it.  Returns ``None`` when
        no trustworthy reading exists.
        """

        with self._lock:
            reading = self._latest_reading.get(str(read_channel))
            if reading is None:
                return None
            if reading.seq <= self._invalidated.get(str(read_channel), 0):
                return None
            if set_channel is not None:
                write = self._latest_write.get(str(set_channel))
                if write is not None and write.seq > reading.seq:
                    return None
            return reading

    def entries(self) -> list[ChannelValue]:
        with self._lock:
            return sorted(self._latest.values(), key=lambda entry: entry.channel)

    def clear(self) -> None:
        with self._lock:
            self._latest.clear()
            self._latest_write.clear()
            self._latest_reading.clear()
            self._invalidated.clear()
