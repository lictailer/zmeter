"""Instrument snapshots recorded at scan start and scan end.

A snapshot reads a short, reviewed list of getters on every connected
device.  The list comes from ``SNAPSHOT_GETTERS`` on the device's logic
class and can be changed per lab with ``snapshot_channels.json`` in the
lab-context folder.  Reads never stop a scan: a failed or slow read is
recorded as an error entry instead of a value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import datetime as _dt
import json
import math
from pathlib import Path
import threading
import time
from typing import Callable, Iterable, Mapping

SNAPSHOT_CHANNELS_FILE = "snapshot_channels.json"
DEFAULT_TOTAL_TIMEOUT_S = 15.0


@dataclass(frozen=True)
class SnapshotTarget:
    """One connected device and the getters a snapshot may call on it."""

    device_id: str
    driver_id: str
    readers: Mapping[str, Callable[[], object]] = field(default_factory=dict)
    skip_reason: str | None = None


def now_text() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def load_snapshot_overrides(path: Path | None) -> dict:
    """Return the optional per-lab override mapping, or ``{}``.

    Format: ``{"<driver or device id>": {"add": [...], "remove": [...]}}``.
    A device-id entry is applied after its driver entry.  A broken file is
    reported through the ``"_error"`` key and otherwise ignored.
    """

    if path is None or not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - a broken file must not stop a scan
        return {"_error": f"{path.name}: {type(exc).__name__}: {exc}"}
    if not isinstance(raw, dict):
        return {"_error": f"{path.name}: top level must be an object"}
    return raw


def resolve_getter_names(
    driver_id: str,
    device_id: str,
    default_getters: Iterable[str],
    overrides: Mapping[str, object],
) -> list[str]:
    names = list(dict.fromkeys(str(name) for name in default_getters))
    for key in (driver_id, device_id):
        entry = overrides.get(key)
        if not isinstance(entry, Mapping):
            continue
        for name in entry.get("add", ()) or ():
            if str(name) not in names:
                names.append(str(name))
        removed = {str(name) for name in (entry.get("remove", ()) or ())}
        names = [name for name in names if name not in removed]
    return names


def json_safe(value: object) -> object:
    """Convert instrument replies to plain JSON values."""

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    item = getattr(value, "item", None)  # numpy scalars
    if callable(item):
        try:
            return json_safe(item())
        except Exception:  # noqa: BLE001
            pass
    tolist = getattr(value, "tolist", None)  # numpy arrays
    if callable(tolist):
        try:
            return json_safe(tolist())
        except Exception:  # noqa: BLE001
            pass
    return str(value)


def _read_device(target: SnapshotTarget, skip_channels: frozenset[str]) -> dict:
    entry: dict = {"driver": target.driver_id, "fields": {}}
    if target.skip_reason:
        entry["skipped"] = target.skip_reason
        return entry
    for name, reader in target.readers.items():
        if f"{target.device_id}_{name}" in skip_channels:
            continue
        try:
            entry["fields"][name] = json_safe(reader())
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            entry["fields"][name] = {"error": f"{type(exc).__name__}: {exc}"}
    return entry


def take_snapshot(
    targets: Iterable[SnapshotTarget],
    *,
    skip_channels: Iterable[str] = (),
    total_timeout_s: float = DEFAULT_TOTAL_TIMEOUT_S,
) -> dict:
    """Read every target in parallel (one daemon thread per device).

    ``skip_channels`` holds full channel names (``<device>_<getter>``) that
    this scan already records as setters.  Devices still reading when the
    time budget ends are recorded as timed out; their threads finish in the
    background, their late results are discarded, and they never keep the
    application from closing.
    """

    targets = list(targets)
    skip = frozenset(skip_channels)
    snapshot: dict = {"time": now_text(), "devices": {}}
    if not targets:
        return snapshot

    results: dict[str, dict] = {}
    lock = threading.Lock()

    def worker(target: SnapshotTarget) -> None:
        try:
            entry = _read_device(target, skip)
        except Exception as exc:  # noqa: BLE001
            entry = {
                "driver": target.driver_id,
                "fields": {},
                "skipped": f"{type(exc).__name__}: {exc}",
            }
        with lock:
            results[target.device_id] = entry

    threads = []
    for target in targets:
        thread = threading.Thread(
            target=worker,
            args=(target,),
            name=f"SetupSnapshot-{target.device_id}",
            daemon=True,
        )
        thread.start()
        threads.append(thread)

    deadline = time.monotonic() + max(0.1, float(total_timeout_s))
    for thread in threads:
        thread.join(max(0.0, deadline - time.monotonic()))

    with lock:
        finished = dict(results)
    for target in targets:
        snapshot["devices"][target.device_id] = finished.get(
            target.device_id,
            {
                "driver": target.driver_id,
                "fields": {},
                "skipped": f"timeout after {total_timeout_s:g} s",
            },
        )
    return snapshot


def changed_fields(start: Mapping | None, end: Mapping | None) -> list[str]:
    """List ``device.field`` names whose value differs between snapshots.

    Fields that failed in either snapshot are not compared.
    """

    if not isinstance(start, Mapping) or not isinstance(end, Mapping):
        return []
    changed = []
    start_devices = start.get("devices", {}) or {}
    end_devices = end.get("devices", {}) or {}
    for device_id, start_entry in start_devices.items():
        end_entry = end_devices.get(device_id)
        if not isinstance(end_entry, Mapping):
            continue
        start_fields = start_entry.get("fields", {}) or {}
        end_fields = end_entry.get("fields", {}) or {}
        for name, start_value in start_fields.items():
            if name not in end_fields:
                continue
            end_value = end_fields[name]
            if _is_error(start_value) or _is_error(end_value):
                continue
            if start_value != end_value:
                changed.append(f"{device_id}.{name}")
    return changed


def _is_error(value: object) -> bool:
    return isinstance(value, Mapping) and "error" in value


def scan_setter_channels(levels: Mapping | None) -> set[str]:
    """Every channel a scan writes: swept setters and manual sets."""

    channels: set[str] = set()
    if not isinstance(levels, Mapping):
        return channels
    for level in levels.values():
        if not isinstance(level, Mapping):
            continue
        setters = level.get("setters", {})
        if isinstance(setters, Mapping):
            for setter in setters.values():
                if isinstance(setter, Mapping) and setter.get("channel"):
                    channels.add(str(setter["channel"]))
        for key in ("manual_set_before", "manual_set_after"):
            for item in level.get(key, ()) or ():
                if isinstance(item, Mapping):
                    channels.update(str(name) for name in item)
    return channels


def scan_channels(levels: Mapping | None) -> set[str]:
    """Every channel a scan touches (setters, manual sets and getters)."""

    channels = scan_setter_channels(levels)
    if isinstance(levels, Mapping):
        for level in levels.values():
            if isinstance(level, Mapping):
                for getter in level.get("getters", ()) or ():
                    if getter and str(getter).lower() not in {"none", "void"}:
                        channels.add(str(getter))
    return channels
