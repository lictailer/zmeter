"""Queue setting folders: one numbered JSON file per queue item.

The number at the start of each file name is the queue order, for example::

    scan_queue_20261031_0930/
        01_scan_setting_gate_sweep.json
        02_manual_set_k10cr1_0_angle.json
        03_scan_setting_reflection.json

Scan files are ordinary scan setting files, so each one can also be opened
with the scan window's Load button.
"""

import json
import math
import os
import re

from .scan import SCAN_SETTING_PREFIX, read_scan_json, write_json_atomic

QUEUE_FOLDER_PREFIX = "scan_queue_"
MANUAL_SET_PREFIX = "manual_set_"

_NUMBERED_FILE = re.compile(r"^(\d+)_(.+)\.json$", re.IGNORECASE)
_UNSAFE_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def safe_file_part(text):
    """Make a scan or channel name usable inside a Windows file name."""
    return _UNSAFE_CHARACTERS.sub("_", str(text)).strip(" .") or "unnamed"


def scan_entry(name, payload):
    return (f"{SCAN_SETTING_PREFIX}{safe_file_part(name)}", payload)


def manual_set_entry(channel, value):
    payload = {"manual_set": {"channel": channel, "value": float(value)}}
    return (f"{MANUAL_SET_PREFIX}{safe_file_part(channel)}", payload)


def write_queue_folder(folder, entries):
    """Write ``(file label, payload)`` entries in order into a new or empty folder."""
    os.makedirs(folder, exist_ok=True)
    if os.listdir(folder):
        raise FileExistsError(f"{folder} is not empty; choose a new folder name.")
    width = max(2, len(str(len(entries))))
    paths = []
    for number, (label, payload) in enumerate(entries, start=1):
        path = os.path.join(folder, f"{number:0{width}d}_{label}.json")
        write_json_atomic(path, payload)
        paths.append(path)
    return paths


def _read_manual_set(path):
    with open(path, "r", encoding="utf-8") as file:
        content = json.load(file)
    manual_set = content.get("manual_set") if isinstance(content, dict) else None
    if not isinstance(manual_set, dict):
        raise ValueError(f"{os.path.basename(path)} has no manual_set entry.")
    channel = str(manual_set.get("channel", "")).strip()
    value = float(manual_set.get("value"))
    if not channel or not math.isfinite(value):
        raise ValueError(f"{os.path.basename(path)} needs a channel and a finite value.")
    return channel, value


def read_queue_folder(folder):
    """Read every numbered file in order as ``(kind, path, content)``.

    ``kind`` is ``"scan"`` (content: scan info) or ``"manual_set"`` (content:
    ``(channel, value)``).  Raises on the first bad file, so a queue is loaded
    completely or not at all.
    """
    numbered = []
    for name in os.listdir(folder):
        match = _NUMBERED_FILE.match(name)
        if match:
            numbered.append((int(match.group(1)), name, match.group(2)))
    entries = []
    for _number, name, label in sorted(numbered):
        path = os.path.join(folder, name)
        if label.startswith(MANUAL_SET_PREFIX):
            entries.append(("manual_set", path, _read_manual_set(path)))
        else:
            entries.append(("scan", path, read_scan_json(path)))
    return entries
