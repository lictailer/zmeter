"""System information export for AI scan planning.

The Setup capture window writes one Markdown file that an AI agent using the
``zmeter-scan-planner`` skill (``skills/zmeter-scan-planner``) reads instead of
the zmeter folder: the devices, the exact channel names a scan can set and
read, the active scan range limits, the data folder, the experiment
description, the remembered questionnaire answers and ``lab_context.md``.  A
JSON block at the end repeats the machine-readable part for the skill's build
script.

Everything comes from what ZMeter already holds in memory; no device is called.
"""

from __future__ import annotations

import datetime as _dt
import json
import math
import os
import re
from typing import Iterable, Mapping

from ..channel_check import catalog_leaf_names
from .profile import DESCRIPTION_FIELDS
from .runtime import data_folder

EXPORT_FORMAT = "zmeter_system"
EXPORT_VERSION = 1
DEFAULT_FILE_NAME = "zmeter_system.md"

# Catalog entries that are not workbook devices.
_BUILT_IN_DEVICES = {
    "default": (
        "built-in channels (default_wait = wait N seconds, default_count = step "
        "counter, default_slack_notification = Slack ping to the operator)"
    ),
    "artificial_channel": "derived channels defined in the artificial-channel window",
    "compensated_source": (
        "Shift Compensation: moves the raw source channel and corrects its coupled "
        "targets by fitted mappings set up by the operator"
    ),
    "compensated_target": (
        "Shift Compensation: sets the raw target channel to the requested value plus "
        "the fitted correction for the current source value"
    ),
}


def _channel_names(catalog: Mapping | None) -> dict[str, list[str]]:
    """Full channel names per device, in catalog order, as scans spell them."""

    return {
        str(device): [f"{device}_{leaf}" for leaf in catalog_leaf_names(choices)]
        for device, choices in (catalog or {}).items()
    }


def _limit(value: float) -> float | None:
    """A finite bound, or None for an open (infinite) side."""

    value = float(value)
    return value if math.isfinite(value) else None


def system_info(main_window) -> dict:
    """The machine-readable part of the export."""

    snapshot = getattr(main_window, "_applied_device_snapshot", None)
    devices = []
    for record in getattr(snapshot, "records", ()) or ():
        state = getattr(record, "state", "")
        devices.append(
            {
                "id": str(record.device_id),
                "driver": str(getattr(record, "driver_id", "") or ""),
                "state": str(getattr(state, "value", state)),
            }
        )
    limits = []
    for (device, channel), bounds in (getattr(main_window, "active_scan_range_limits", None) or {}).items():
        low, high = _limit(bounds[0]), _limit(bounds[1])
        if low is None and high is None:
            continue
        limits.append({"channel": f"{device}_{channel}", "low": low, "high": high})
    return {
        "format": EXPORT_FORMAT,
        "version": EXPORT_VERSION,
        "exported_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "profile": str(getattr(snapshot, "profile_name", "") or ""),
        "data_folder": data_folder(main_window),
        "devices": devices,
        "setter_channels": _channel_names(getattr(main_window, "setter_equipment_info", None)),
        "getter_channels": _channel_names(getattr(main_window, "getter_equipment_info", None)),
        "limits": limits,
    }


def _bound_text(value: float | None) -> str:
    return "none" if value is None else f"{value:g}"


def export_markdown(
    info: Mapping,
    description: Mapping,
    answers: Iterable[Mapping],
    lab_context: str,
) -> str:
    """The export file: readable sections, then the JSON block."""

    lines = [
        "# ZMeter system export",
        "",
        "Written by ZMeter's Setup capture window for AI scan planning "
        "(zmeter-scan-planner skill). It lists what this ZMeter could set and read "
        "at export time. Use only the channel names below, spelled exactly.",
        "",
        f"- Exported: {info['exported_at']}",
        f"- Device profile: {info['profile'] or '-'}",
        f"- Data folder: {info['data_folder']}",
        "",
        "## Devices",
        "",
        "| Device id | Driver | State |",
        "| --- | --- | --- |",
    ]
    for device in info["devices"]:
        lines.append(f"| {device['id']} | {device['driver']} | {device['state']} |")
    for device, note in _BUILT_IN_DEVICES.items():
        if device in info["setter_channels"] or device in info["getter_channels"]:
            lines.append(f"| {device} | {note} | built in |")
    lines += [
        "",
        "Only connected devices have channels. A device that is not connected "
        "cannot be used until it is connected and the system is exported again.",
        "",
    ]
    for title, key in (
        ("Setter channels (scan setters and manual sets)", "setter_channels"),
        ("Getter channels (recorded by scans)", "getter_channels"),
    ):
        lines += [f"## {title}", ""]
        channels = {device: names for device, names in info[key].items() if names}
        if not channels:
            lines.append("(none)")
        for device, names in channels.items():
            lines.append(f"- {device}: " + ", ".join(f"`{name}`" for name in names))
        lines.append("")
    lines += [
        "## Scan range limits",
        "",
        "ZMeter refuses to write a setter value outside these limits and records "
        "that point as NaN. Channels not listed have no limit.",
        "",
    ]
    if info["limits"]:
        lines += ["| Channel | Low | High |", "| --- | --- | --- |"]
        for limit in info["limits"]:
            lines.append(
                f"| `{limit['channel']}` | {_bound_text(limit['low'])} | {_bound_text(limit['high'])} |"
            )
    else:
        lines.append("(none)")
    lines += ["", "## Experiment description", "", "Typed in Setup capture; may be incomplete.", ""]
    for key, label in DESCRIPTION_FIELDS:
        value = str(description.get(key, "") or "").strip()
        lines.append(f"- {label}: {value or '(empty)'}")
    lines += [
        "",
        "## Remembered questionnaire answers",
        "",
        "From earlier scans, newest first. They may be outdated: confirm before relying on them.",
        "",
    ]
    answered = [item for item in answers if str(item.get("answer") or "").strip()]
    for item in answered:
        lines.append(f"- {item.get('text') or item.get('id')}: {item.get('answer')}")
    if not answered:
        lines.append("(none)")
    lines += [
        "",
        "## Lab context (lab_context/lab_context.md)",
        "",
        # One heading level down, so its sections sit inside this one.
        re.sub(r"(?m)^(#+ )", r"##\1", lab_context.strip()) or "(empty)",
        "",
        "## Machine-readable system information",
        "",
        "```json",
        json.dumps(info, indent=1),
        "```",
        "",
    ]
    return "\n".join(lines)


def write_export(path: str, text: str) -> str:
    """Write the export atomically; returns the path."""

    temporary = f"{path}.{os.getpid()}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        if os.path.exists(temporary):
            os.remove(temporary)
        raise
    return path
