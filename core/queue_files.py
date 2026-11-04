"""Saved queues: one folder with a scan setting JSON per scan and queue.json.

queue.json lists the queue in order. A scan entry names its JSON file in the
folder; a manual set is stored inline, since it has no settings of its own:

    {
        "format": "zmeter_queue",
        "version": 1,
        "items": [
            {"scan": "01_gate_sweep.json"},
            {"manual_set": {"channel": "nidaq_0_AO0", "value": 0.5}},
            {"scan": "03_field_sweep.json"}
        ]
    }

Each scan file is an ordinary scan setting file, so it can also be opened alone
with Load in a scan window. The number in its name is its queue position.
"""

import json
import os
import re
import shutil

from .scan import _write_json_payload, read_scan_file
from .scan_file_info import stamp_scan_payload

QUEUE_FILE = "queue.json"
QUEUE_FORMAT = "zmeter_queue"
QUEUE_VERSION = 1

_UNSAFE_FILE_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _file_stem(name):
    stem = _UNSAFE_FILE_CHARACTERS.sub("_", str(name or "")).strip(" .")
    return stem or "scan"


def save_queue(folder, items):
    """Write items, in queue order, to a new folder.

    Each item is {"scan": setting_payload} or
    {"manual_set": {"channel": name, "value": number}}. The folder must not
    exist. Files are written to a temporary folder that is renamed at the end,
    so a failed save leaves nothing behind.
    """
    folder = os.path.abspath(folder)
    if os.path.exists(folder):
        raise FileExistsError(f"{folder} already exists")

    width = max(2, len(str(len(items))))
    temporary = f"{folder}.{os.getpid()}.tmp"
    os.makedirs(temporary)
    try:
        entries = []
        for position, item in enumerate(items, start=1):
            if "scan" in item:
                payload = stamp_scan_payload(item["scan"])
                file_name = f"{position:0{width}d}_{_file_stem(payload.get('name'))}.json"
                _write_json_payload(os.path.join(temporary, file_name), payload)
                entries.append({"scan": file_name})
            else:
                entries.append({"manual_set": dict(item["manual_set"])})
        _write_json_payload(
            os.path.join(temporary, QUEUE_FILE),
            {"format": QUEUE_FORMAT, "version": QUEUE_VERSION, "items": entries},
        )
        os.replace(temporary, folder)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return folder


def read_queue(folder):
    """Read a saved queue in its saved order.

    Returns {"scan": info, "path": file} and {"manual_set": {...}} items.
    Raises if queue.json or any scan file is missing or malformed.
    """
    with open(os.path.join(folder, QUEUE_FILE), "r", encoding="utf-8") as file:
        queue = json.load(file)
    if (
        not isinstance(queue, dict)
        or queue.get("format") != QUEUE_FORMAT
        or queue.get("version") != QUEUE_VERSION
    ):
        raise ValueError(f"{QUEUE_FILE} is not a version {QUEUE_VERSION} ZMeter queue")

    items = []
    for entry in queue.get("items", []):
        if "scan" in entry:
            path = os.path.join(folder, entry["scan"])
            items.append({"scan": read_scan_file(path), "path": path})
        elif "manual_set" in entry:
            manual_set = entry["manual_set"]
            items.append(
                {
                    "manual_set": {
                        "channel": str(manual_set["channel"]),
                        "value": float(manual_set["value"]),
                    }
                }
            )
        else:
            raise ValueError(f"unknown queue item: {entry}")
    return items
