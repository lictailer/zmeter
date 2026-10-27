"""Connect snapshots to the running application.

The scan builds a :class:`SnapshotRun` on the UI thread when it starts.  The
scan thread then calls :meth:`SnapshotRun.take` at scan start and scan end.
Device calls go through the device manager's generation lease, so a device
that was reconnected or removed during the scan is reported as an error
instead of being called on a stale instance.

Two kinds of device are listed but not read:

* a device that is not part of this scan and has a live monitor running,
  because its own monitor thread may be talking to it at the same moment;
* a device that another running scan is using.
"""

from __future__ import annotations

import os
import threading
from typing import Iterable, Mapping

from .profile import lab_context_dir, lab_context_version, lab_context_text
from .snapshot import (
    DEFAULT_TOTAL_TIMEOUT_S,
    SNAPSHOT_CHANNELS_FILE,
    SnapshotTarget,
    load_snapshot_overrides,
    now_text,
    resolve_getter_names,
    scan_setter_channels,
    take_snapshot,
)

SKIP_LIVE_MONITOR = "live monitor running (not part of this scan)"
SKIP_OTHER_SCAN = "in use by another running scan"
SKIP_NO_GETTERS = "no snapshot getters defined"

_busy_lock = threading.Lock()
_busy_devices: dict[object, frozenset[str]] = {}


def register_scan_devices(scan_key: object, device_ids: Iterable[str]) -> None:
    with _busy_lock:
        _busy_devices[scan_key] = frozenset(str(item) for item in device_ids)


def release_scan_devices(scan_key: object) -> None:
    with _busy_lock:
        _busy_devices.pop(scan_key, None)


def devices_used_by_other_scans(scan_key: object) -> frozenset[str]:
    with _busy_lock:
        used: set[str] = set()
        for key, device_ids in _busy_devices.items():
            if key != scan_key:
                used.update(device_ids)
    return frozenset(used)


def has_live_monitor(equipment: object) -> bool:
    """Best-effort check for a device widget whose monitor is polling."""

    if getattr(equipment, "monitor_enabled", False) is True:
        return True
    if getattr(equipment, "monitor_mode", None):
        return True
    for name in ("timer", "monitor_timer", "read_timer"):
        timer = getattr(equipment, name, None)
        is_active = getattr(timer, "isActive", None)
        if callable(is_active):
            try:
                if is_active():
                    return True
            except Exception:  # noqa: BLE001 - deleted Qt object
                continue
    return False


def _connected_devices(main_window) -> list[tuple[str, str, object, int | None]]:
    """Return ``(device_id, driver_id, equipment, generation)`` for each
    connected device, in catalog order."""

    snapshot = getattr(main_window, "_applied_device_snapshot", None)
    equipment = dict(getattr(main_window, "equips", {}) or {})
    records = tuple(getattr(snapshot, "records", ()) or ())
    devices = []
    if records:
        for record in records:
            state = getattr(record, "state", None)
            if str(getattr(state, "value", state)) != "connected":
                continue
            device_id = str(record.device_id)
            instance = equipment.get(device_id, getattr(record, "instance", None))
            if instance is None:
                continue
            devices.append(
                (
                    device_id,
                    str(getattr(record, "driver_id", "") or ""),
                    instance,
                    int(getattr(record, "generation", 0)),
                )
            )
        return devices
    # Legacy start-up without a device manager: every loaded widget counts.
    for device_id, instance in equipment.items():
        devices.append((str(device_id), type(instance).__name__.lower(), instance, None))
    return devices


def _missing_getter(name: str):
    def reader():
        raise AttributeError(f"device has no get_{name}")

    return reader


class SnapshotRun:
    """Everything one scan needs to take its start and end snapshots."""

    def __init__(
        self,
        main_window,
        participating_ids: Iterable[str],
        levels: Mapping | None,
        *,
        scan_key: object,
        lab_folder=None,
        total_timeout_s: float = DEFAULT_TOTAL_TIMEOUT_S,
    ):
        self.main_window = main_window
        self.participating_ids = frozenset(str(item) for item in participating_ids)
        self.scan_key = scan_key
        self.total_timeout_s = total_timeout_s
        self.skip_channels = frozenset(scan_setter_channels(levels))
        folder = lab_folder or lab_context_dir()
        self.overrides = load_snapshot_overrides(folder / SNAPSHOT_CHANNELS_FILE)
        self.config_note = self.overrides.get("_error") if self.overrides else None
        self.lab_context_version = lab_context_version(lab_context_text(folder))
        self._devices = []
        for device_id, driver_id, equipment, generation in _connected_devices(
            main_window
        ):
            logic = getattr(equipment, "logic", None)
            defaults = getattr(type(logic), "SNAPSHOT_GETTERS", ()) if logic else ()
            names = resolve_getter_names(driver_id, device_id, defaults, self.overrides)
            readers = {}
            for name in names:
                method = getattr(logic, f"get_{name}", None) if logic else None
                if not callable(method):
                    readers[name] = _missing_getter(name)
                    continue
                bind = getattr(main_window, "_bind_manager_device_call", None)
                readers[name] = (
                    bind(device_id, generation, method) if callable(bind) else method
                )
            self._devices.append((device_id, driver_id, equipment, readers))

    def targets(self) -> list[SnapshotTarget]:
        """Build targets now; monitor and busy state is checked at call time."""

        busy = devices_used_by_other_scans(self.scan_key)
        targets = []
        for device_id, driver_id, equipment, readers in self._devices:
            skip_reason = None
            if not readers:
                skip_reason = SKIP_NO_GETTERS
            elif device_id not in self.participating_ids:
                if device_id in busy:
                    skip_reason = SKIP_OTHER_SCAN
                elif has_live_monitor(equipment):
                    skip_reason = SKIP_LIVE_MONITOR
            targets.append(
                SnapshotTarget(device_id, driver_id, readers, skip_reason)
            )
        return targets

    def take(self) -> dict:
        try:
            return take_snapshot(
                self.targets(),
                skip_channels=self.skip_channels,
                total_timeout_s=self.total_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - a snapshot never stops a scan
            return {
                "time": now_text(),
                "devices": {},
                "error": f"{type(exc).__name__}: {exc}",
            }


def data_folder(main_window) -> str:
    """The folder scans save into (same rule as the scan autosave)."""

    path_box = getattr(main_window, "save_info_path", None)
    text = path_box.toPlainText().strip() if path_box is not None else ""
    if text:
        return os.path.normpath(text.strip('"'))
    if hasattr(main_window, "save_path"):
        return os.path.normpath(str(main_window.save_path))
    return os.getcwd()
