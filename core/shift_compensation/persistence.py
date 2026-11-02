"""Save and load a Shift Compensation mapping set (one JSON file).

A set file holds every mapping of the window: CSV points, the four
channels, fit model, options, fit result, reference value and Active flag.
Loading keeps the saved Active flags; ``ShiftCompensationLogic.load_mappings``
re-checks them against the current catalog before anything is published.
"""

from __future__ import annotations

import json
import os
import tempfile
from typing import Iterable

from .logic import Mapping, now_text

SET_FORMAT = "zmeter.shift_compensation_set"
SET_VERSION = 1
SET_FILE_FILTER = "Shift compensation set (*.json);;All files (*)"


class MappingSetError(ValueError):
    """The file is not a usable Shift Compensation set."""


def build_set_payload(mappings: Iterable[Mapping]) -> dict:
    return {
        "format": SET_FORMAT,
        "version": SET_VERSION,
        "saved_at": now_text(),
        "mappings": [mapping.to_dict() for mapping in mappings],
    }


def save_set(path: str | os.PathLike, mappings: Iterable[Mapping]) -> dict:
    """Write the set atomically (temporary file, then replace)."""

    payload = build_set_payload(mappings)
    path = os.fspath(path)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(
        prefix=".shift_compensation_", suffix=".json", dir=folder
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temp_path, path)
    except BaseException:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise
    return payload


def mappings_from_set_payload(payload) -> list[Mapping]:
    if not isinstance(payload, dict):
        raise MappingSetError("the file does not hold a JSON object")
    if payload.get("format") != SET_FORMAT:
        raise MappingSetError(
            f"not a shift compensation set (format {payload.get('format')!r})"
        )
    try:
        version = int(payload.get("version", 0))
    except (TypeError, ValueError):
        version = 0
    if version != SET_VERSION:
        raise MappingSetError(f"unsupported set version {payload.get('version')!r}")
    items = payload.get("mappings")
    if not isinstance(items, list):
        raise MappingSetError("'mappings' must be a list")
    mappings = []
    seen_ids = set()
    for index, item in enumerate(items):
        try:
            mapping = Mapping.from_dict(item)
        except Exception as exc:  # noqa: BLE001 - report which entry failed
            raise MappingSetError(f"mapping {index + 1}: {exc}") from exc
        if mapping.mapping_id in seen_ids:
            mapping.mapping_id = Mapping().mapping_id
        seen_ids.add(mapping.mapping_id)
        mappings.append(mapping)
    return mappings


def load_set(path: str | os.PathLike) -> list[Mapping]:
    try:
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise MappingSetError(f"cannot read '{path}': {exc}") from exc
    return mappings_from_set_payload(payload)
