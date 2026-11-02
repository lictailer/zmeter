"""Mappings and compensated scan channels for Shift Compensation.

No Qt widgets and no direct device access: every device write and read goes
through the ``write_channel(value, channel)`` and ``read_channel(channel)``
callables, which are ``MainWindow.write_info`` / ``read_info`` in the app.

Compensated channels (``<group>_<raw channel>``):

``compensated_source_<S>``
    Set: read S, read every coupled target, set S, then set each target to
    its old value + sum of f(new) - f(old) over the mappings S -> target.
    Get: S's readback.

``compensated_target_<T>``
    Set: get every coupled source (from the main-window value record when
    it is still valid, else a fresh read), then set T to the requested value
    + sum of f(x_now) - f(x_ref) over the mappings onto T.
    Get: T's readback (the physical value).
"""

from __future__ import annotations

import copy
import datetime as _dt
import math
import threading
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping as MappingType, Sequence

import numpy as np
from PyQt6 import QtCore

from .fitting import (
    MODEL_COSINE,
    MODELS,
    FitResult,
    MappingFitError,
    fit_mapping,
)

SOURCE_GROUP = "compensated_source"
TARGET_GROUP = "compensated_target"
GROUPS = (SOURCE_GROUP, TARGET_GROUP)

DEFAULT_OPTIONS = {"period": 360.0, "free_period": False, "order": 1}

READBACK_CACHE_RULE = (
    "Source readbacks come from the main-window value record unless the "
    "source was set through the main window after the reading, or the "
    "reading predates scan start; then the source is read again."
)


class ShiftCompensationError(RuntimeError):
    """A compensated channel cannot be used as requested."""


def now_text() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


@dataclass
class Mapping:
    """One source -> target coupling with its points and fit."""

    mapping_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    name: str = ""
    csv_name: str = ""
    source_values: list = field(default_factory=list)
    shift_values: list = field(default_factory=list)
    source_set: str = ""
    source_read: str = ""
    target_set: str = ""
    target_read: str = ""
    model: str = MODEL_COSINE
    options: dict = field(default_factory=lambda: dict(DEFAULT_OPTIONS))
    fit: FitResult | None = None
    x_ref: float | None = None
    active: bool = False
    note: str = ""

    @property
    def display_name(self) -> str:
        if self.name.strip():
            return self.name.strip()
        if self.source_set and self.target_set:
            return f"{self.source_set} → {self.target_set}"
        return f"mapping {self.mapping_id}"

    @property
    def channels(self) -> tuple[str, str, str, str]:
        return (self.source_set, self.source_read, self.target_set, self.target_read)

    def reference_value(self) -> float:
        if self.x_ref is not None:
            return float(self.x_ref)
        if self.source_values:
            return float(self.source_values[0])
        raise ShiftCompensationError(f"{self.display_name}: no reference value")

    def correction(self, x_from: float, x_to: float) -> float:
        """Target shift caused by moving the source from x_from to x_to."""

        if self.fit is None:
            raise ShiftCompensationError(f"{self.display_name}: not fitted")
        return float(self.fit.evaluate(float(x_to)) - self.fit.evaluate(float(x_from)))

    def to_dict(self) -> dict:
        return {
            "id": self.mapping_id,
            "name": self.name,
            "csv_name": self.csv_name,
            "points": {
                "source": [float(v) for v in self.source_values],
                "shift": [float(v) for v in self.shift_values],
            },
            "channels": {
                "source_set": self.source_set,
                "source_read": self.source_read,
                "target_set": self.target_set,
                "target_read": self.target_read,
            },
            "model": self.model,
            "options": dict(self.options),
            "fit": None if self.fit is None else self.fit.to_dict(),
            "x_ref": None if self.x_ref is None else float(self.x_ref),
            "active": bool(self.active),
        }

    @classmethod
    def from_dict(cls, payload: MappingType[str, Any]) -> "Mapping":
        points = payload.get("points") or {}
        channels = payload.get("channels") or {}
        model = str(payload.get("model", MODEL_COSINE))
        if model not in MODELS:
            raise ValueError(f"unknown fit model '{model}'")
        fit_payload = payload.get("fit")
        options = dict(DEFAULT_OPTIONS)
        options.update(payload.get("options") or {})
        x_ref = payload.get("x_ref")
        source_values = [float(v) for v in points.get("source", [])]
        shift_values = [float(v) for v in points.get("shift", [])]
        if len(source_values) != len(shift_values):
            raise ValueError("mapping points have different lengths")
        return cls(
            mapping_id=str(payload.get("id") or uuid.uuid4().hex[:8]),
            name=str(payload.get("name", "")),
            csv_name=str(payload.get("csv_name", "")),
            source_values=source_values,
            shift_values=shift_values,
            source_set=str(channels.get("source_set", "")),
            source_read=str(channels.get("source_read", "")),
            target_set=str(channels.get("target_set", "")),
            target_read=str(channels.get("target_read", "")),
            model=model,
            options=options,
            fit=None if not fit_payload else FitResult.from_dict(fit_payload),
            x_ref=None if x_ref is None else float(x_ref),
            active=bool(payload.get("active", False)),
        )


def _is_number(value) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


class ShiftCompensationLogic(QtCore.QObject):
    """Owns the mappings and implements the compensated channels."""

    sig_changed = QtCore.pyqtSignal()
    sig_log = QtCore.pyqtSignal(str, str)

    def __init__(
        self,
        write_channel: Callable[[float, str], Any],
        read_channel: Callable[[str], Any],
        value_record=None,
        parent: QtCore.QObject | None = None,
    ):
        super().__init__(parent)
        self._write_channel = write_channel
        self._read_channel = read_channel
        self._value_record = value_record
        self._lock = threading.RLock()
        self._target_locks: dict[str, threading.Lock] = {}
        self._mappings: list[Mapping] = []
        self._available_setters: frozenset[str] | None = None
        self._available_getters: frozenset[str] | None = None

    # ------------------------------------------------------------ logging
    def _log(self, level: str, message: str) -> None:
        self.sig_log.emit(str(level).upper(), str(message))

    # ------------------------------------------------------------ state
    def mappings(self) -> list[Mapping]:
        with self._lock:
            return list(self._mappings)

    def get(self, mapping_id: str) -> Mapping:
        with self._lock:
            for mapping in self._mappings:
                if mapping.mapping_id == mapping_id:
                    return mapping
        raise KeyError(f"unknown mapping '{mapping_id}'")

    def capture_state(self) -> list[Mapping]:
        with self._lock:
            return copy.deepcopy(self._mappings)

    def restore_state(self, state: Sequence[Mapping], *, emit=True) -> None:
        with self._lock:
            self._mappings = copy.deepcopy(list(state))
        if emit:
            self.sig_changed.emit()

    def add_mapping(self, **values) -> Mapping:
        mapping = Mapping(**values)
        mapping.active = False
        with self._lock:
            self._mappings.append(mapping)
        self.sig_changed.emit()
        return mapping

    def remove_mapping(self, mapping_id: str) -> None:
        with self._lock:
            self._mappings = [m for m in self._mappings if m.mapping_id != mapping_id]
        self.sig_changed.emit()

    def replace_mappings(self, mappings: Iterable[Mapping]) -> None:
        with self._lock:
            self._mappings = list(mappings)
        self.sig_changed.emit()

    def _editable(self, mapping_id: str) -> Mapping:
        mapping = self.get(mapping_id)
        if mapping.active:
            raise ShiftCompensationError(
                f"{mapping.display_name} is active; deactivate it before editing"
            )
        return mapping

    def update_mapping(self, mapping_id: str, **values) -> Mapping:
        allowed = {
            "name",
            "source_set",
            "source_read",
            "target_set",
            "target_read",
            "model",
            "options",
            "x_ref",
        }
        unknown = set(values) - allowed
        if unknown:
            raise TypeError(f"cannot update {sorted(unknown)}")
        with self._lock:
            mapping = self._editable(mapping_id)
            for key, value in values.items():
                if key == "options":
                    merged = dict(mapping.options)
                    merged.update(value)
                    value = merged
                setattr(mapping, key, value)
            mapping.note = ""
        self.sig_changed.emit()
        return mapping

    def set_points(self, mapping_id: str, source_values, shift_values, csv_name="") -> Mapping:
        source_values = [float(v) for v in source_values]
        shift_values = [float(v) for v in shift_values]
        if len(source_values) != len(shift_values) or len(source_values) < 2:
            raise ValueError("a mapping needs at least two (source, shift) points")
        with self._lock:
            mapping = self._editable(mapping_id)
            mapping.source_values = source_values
            mapping.shift_values = shift_values
            mapping.csv_name = str(csv_name)
            mapping.fit = None
            mapping.note = ""
        self.sig_changed.emit()
        return mapping

    def fit(self, mapping_id: str, model: str | None = None, options=None) -> FitResult:
        with self._lock:
            mapping = self._editable(mapping_id)
            if model is not None:
                mapping.model = model
            if options is not None:
                merged = dict(mapping.options)
                merged.update(options)
                mapping.options = merged
            if len(mapping.source_values) < 2:
                raise MappingFitError("load a CSV before fitting")
            result = fit_mapping(
                mapping.source_values,
                mapping.shift_values,
                mapping.model,
                mapping.options,
            )
            mapping.fit = result
            mapping.note = ""
        self.sig_changed.emit()
        return result

    # ------------------------------------------------------------ activation
    def set_active_flag(self, mapping_id: str, active: bool) -> None:
        with self._lock:
            mapping = self.get(mapping_id)
            mapping.active = bool(active)
            if active:
                mapping.note = ""
        self.sig_changed.emit()

    def activation_problems(
        self,
        mapping: Mapping,
        setter_channels: Iterable[str],
        getter_channels: Iterable[str],
        others: Iterable[Mapping] | None = None,
    ) -> list[str]:
        """Reasons why ``mapping`` cannot be active together with ``others``."""

        setters = set(setter_channels)
        getters = set(getter_channels)
        problems = []
        if mapping.fit is None:
            problems.append("no fit yet")
        labels = ("source set", "source read", "target set", "target read")
        for label, channel in zip(labels, mapping.channels):
            if not channel:
                problems.append(f"{label} channel not chosen")
        for label, channel in (
            ("source set", mapping.source_set),
            ("target set", mapping.target_set),
        ):
            if channel and channel not in setters:
                problems.append(f"{label} channel '{channel}' is not available")
        for label, channel in (
            ("source read", mapping.source_read),
            ("target read", mapping.target_read),
        ):
            if channel and channel not in getters:
                problems.append(f"{label} channel '{channel}' is not available")
        for channel in mapping.channels:
            if channel.startswith(tuple(f"{group}_" for group in GROUPS)):
                problems.append(f"'{channel}' is a compensated channel")
        if mapping.source_set and mapping.source_set == mapping.target_set:
            problems.append("source and target set channels are the same")
        if others is None:
            others = [
                m for m in self.mappings()
                if m.active and m.mapping_id != mapping.mapping_id
            ]
        for other in others:
            if other.mapping_id == mapping.mapping_id:
                continue
            if mapping.target_set and mapping.target_set == other.source_set:
                problems.append(
                    f"chaining: '{mapping.target_set}' is the source of "
                    f"{other.display_name}"
                )
            if mapping.source_set and mapping.source_set == other.target_set:
                problems.append(
                    f"chaining: '{mapping.source_set}' is the target of "
                    f"{other.display_name}"
                )
            if (
                mapping.source_set == other.source_set
                and mapping.source_read != other.source_read
            ):
                problems.append(
                    f"source '{mapping.source_set}' is read through "
                    f"'{other.source_read}' in {other.display_name}"
                )
            if (
                mapping.target_set == other.target_set
                and mapping.target_read != other.target_read
            ):
                problems.append(
                    f"target '{mapping.target_set}' is read through "
                    f"'{other.target_read}' in {other.display_name}"
                )
        return problems

    def deactivate_invalid(self, setter_channels, getter_channels) -> list[str]:
        """Deactivate active mappings that break the rules; return messages."""

        setters = frozenset(setter_channels)
        getters = frozenset(getter_channels)
        messages = []
        with self._lock:
            kept: list[Mapping] = []
            for mapping in self._mappings:
                if not mapping.active:
                    continue
                problems = self.activation_problems(mapping, setters, getters, kept)
                if problems:
                    mapping.active = False
                    mapping.note = "; ".join(problems)
                    messages.append(f"{mapping.display_name} deactivated: {mapping.note}")
                else:
                    kept.append(mapping)
        if messages:
            for message in messages:
                self._log("WARNING", f"[ShiftCompensation] {message}")
            self.sig_changed.emit()
        return messages

    def available_channels(self) -> tuple[frozenset[str], frozenset[str]]:
        """Raw ``(setters, getters)`` of the installed catalog."""

        with self._lock:
            return (
                self._available_setters or frozenset(),
                self._available_getters or frozenset(),
            )

    def activate(self, mapping_id: str) -> Mapping:
        """Set a mapping active, or raise with the reasons it cannot be."""

        setters, getters = self.available_channels()
        with self._lock:
            mapping = self.get(mapping_id)
            problems = self.activation_problems(mapping, setters, getters)
            if problems:
                raise ShiftCompensationError(
                    f"{mapping.display_name} cannot be activated: "
                    + "; ".join(problems)
                )
            mapping.active = True
            mapping.note = ""
        self.sig_changed.emit()
        return mapping

    def load_mappings(self, mappings: Iterable[Mapping]) -> list[str]:
        """Replace every mapping with ``mappings`` (e.g. from a set file).

        A mapping saved as active is activated again when it passes the
        normal activation checks against the installed catalog; otherwise
        it loads inactive with the reasons in its note.  Returns one
        message per mapping that could not be activated.
        """

        setters, getters = self.available_channels()
        messages = []
        loaded = copy.deepcopy(list(mappings))
        with self._lock:
            kept: list[Mapping] = []
            for mapping in loaded:
                wanted = bool(mapping.active)
                mapping.active = False
                mapping.note = ""
                if not wanted:
                    continue
                problems = self.activation_problems(mapping, setters, getters, kept)
                if problems:
                    mapping.note = "loaded inactive: " + "; ".join(problems)
                    messages.append(f"{mapping.display_name} {mapping.note}")
                else:
                    mapping.active = True
                    kept.append(mapping)
            self._mappings = loaded
        self.sig_changed.emit()
        return messages

    def deactivate(self, mapping_id: str) -> Mapping:
        with self._lock:
            mapping = self.get(mapping_id)
            mapping.active = False
        self.sig_changed.emit()
        return mapping

    def set_available_channels(self, setter_channels, getter_channels) -> list[str]:
        """Record the raw catalog after a catalog install; drop broken mappings."""

        with self._lock:
            self._available_setters = frozenset(setter_channels)
            self._available_getters = frozenset(getter_channels)
        return self.deactivate_invalid(setter_channels, getter_channels)

    def _published_mappings(self, setter_channels=None, getter_channels=None) -> list[Mapping]:
        with self._lock:
            setters = (
                self._available_setters
                if setter_channels is None
                else frozenset(setter_channels)
            )
            getters = (
                self._available_getters
                if getter_channels is None
                else frozenset(getter_channels)
            )
            result = []
            for mapping in self._mappings:
                if not mapping.active or mapping.fit is None:
                    continue
                if setters is not None and (
                    mapping.source_set not in setters
                    or mapping.target_set not in setters
                ):
                    continue
                if getters is not None and (
                    mapping.source_read not in getters
                    or mapping.target_read not in getters
                ):
                    continue
                result.append(mapping)
            return result

    def published_channels(self, setter_channels=None, getter_channels=None):
        """``(sources, targets)`` raw channel names for the compensated groups."""

        mappings = self._published_mappings(setter_channels, getter_channels)
        sources = tuple(sorted({m.source_set for m in mappings}))
        targets = tuple(sorted({m.target_set for m in mappings}))
        return sources, targets

    def physical_channels(self, channel: str) -> tuple[str, ...]:
        """Raw channels touched by one full compensated channel name."""

        channel = str(channel)
        mappings = self._published_mappings()
        if channel.startswith(f"{SOURCE_GROUP}_"):
            raw = channel[len(SOURCE_GROUP) + 1:]
            related = [m for m in mappings if m.source_set == raw]
        elif channel.startswith(f"{TARGET_GROUP}_"):
            raw = channel[len(TARGET_GROUP) + 1:]
            related = [m for m in mappings if m.target_set == raw]
        else:
            return ()
        channels = []
        for mapping in related:
            channels.extend(mapping.channels)
        return tuple(dict.fromkeys(c for c in channels if c))

    # ------------------------------------------------------------ scan I/O
    def _lock_for_target(self, target: str) -> threading.Lock:
        with self._lock:
            lock = self._target_locks.get(target)
            if lock is None:
                lock = threading.Lock()
                self._target_locks[target] = lock
            return lock

    def _read_number(self, channel: str) -> float:
        value = self._read_channel(channel)
        if not _is_number(value):
            raise ShiftCompensationError(
                f"readback '{channel}' returned a non-numeric value {value!r}"
            )
        return float(value)

    def _write(self, value: float, channel: str) -> bool:
        result = self._write_channel(float(value), channel)
        return result is not False

    def source_value(self, mapping: Mapping) -> float:
        """Current source value: recorded reading if still valid, else a read."""

        record = self._value_record
        if record is not None:
            reading = record.fresh_reading(mapping.source_read, mapping.source_set)
            if reading is not None and _is_number(reading.value):
                return float(reading.value)
        return self._read_number(mapping.source_read)

    def write_source(self, source_set: str, value: float) -> bool:
        """Setter of ``compensated_source_<source_set>``."""

        value = float(value)
        if not math.isfinite(value):
            return False
        mappings = [m for m in self._published_mappings() if m.source_set == source_set]
        if not mappings:
            raise ShiftCompensationError(
                f"no active mapping uses '{source_set}' as its source"
            )
        target_reads: dict[str, str] = {}
        for mapping in mappings:
            target_reads.setdefault(mapping.target_set, mapping.target_read)
        locks = [self._lock_for_target(t) for t in sorted(target_reads)]
        for lock in locks:
            lock.acquire()
        try:
            x_old = self._read_number(mappings[0].source_read)
            y_old = {t: self._read_number(r) for t, r in target_reads.items()}
            if not self._write(value, source_set):
                self._log(
                    "WARNING",
                    f"[ShiftCompensation] '{source_set}'={value} was not written; "
                    "targets left unchanged.",
                )
                return False
            all_written = True
            for target, old in y_old.items():
                delta = sum(
                    m.correction(x_old, value)
                    for m in mappings
                    if m.target_set == target
                )
                if not self._write(old + delta, target):
                    all_written = False
                    self._log(
                        "WARNING",
                        f"[ShiftCompensation] correction of '{target}' to "
                        f"{old + delta} was not written.",
                    )
            return all_written
        finally:
            for lock in reversed(locks):
                lock.release()

    def write_target(self, target_set: str, value: float) -> bool:
        """Setter of ``compensated_target_<target_set>``."""

        value = float(value)
        if not math.isfinite(value):
            return False
        mappings = [m for m in self._published_mappings() if m.target_set == target_set]
        if not mappings:
            raise ShiftCompensationError(
                f"no active mapping uses '{target_set}' as its target"
            )
        with self._lock_for_target(target_set):
            total = 0.0
            for mapping in mappings:
                x_now = self.source_value(mapping)
                total += mapping.correction(mapping.reference_value(), x_now)
            written = self._write(value + total, target_set)
            if not written:
                names = ", ".join(m.display_name for m in mappings)
                self._log(
                    "WARNING",
                    f"[ShiftCompensation] '{target_set}'={value + total} "
                    f"(requested {value} + correction {total}) was not written "
                    f"({names}).",
                )
            return written

    def read_source(self, source_set: str) -> float:
        for mapping in self._published_mappings():
            if mapping.source_set == source_set:
                return self._read_channel(mapping.source_read)
        raise ShiftCompensationError(f"no active mapping uses '{source_set}' as its source")

    def read_target(self, target_set: str) -> float:
        for mapping in self._published_mappings():
            if mapping.target_set == target_set:
                return self._read_channel(mapping.target_read)
        raise ShiftCompensationError(f"no active mapping uses '{target_set}' as its target")

    # ------------------------------------------------------------ scan record
    def mark_sources_stale(self) -> None:
        record = self._value_record
        if record is None:
            return
        record.invalidate({m.source_read for m in self._published_mappings()})

    def begin_scan(self, scan_name: str = "", serial: str = "") -> dict:
        """Mark sources stale and return the record stored in the scan JSON."""

        self.mark_sources_stale()
        mappings = self._published_mappings()
        sources, targets = self.published_channels()
        return {
            "recorded_at": now_text(),
            "scan": {"name": str(scan_name), "serial": str(serial)},
            "channels": {
                "source": [f"{SOURCE_GROUP}_{c}" for c in sources],
                "target": [f"{TARGET_GROUP}_{c}" for c in targets],
            },
            "readback_cache": READBACK_CACHE_RULE,
            "active": [mapping.to_dict() for mapping in mappings],
        }

    def summary_lines(self) -> list[str]:
        lines = []
        for mapping in self._published_mappings():
            fit = mapping.fit
            lines.append(
                f"Shift compensation active: {mapping.display_name} "
                f"({mapping.source_set} -> {mapping.target_set}), "
                f"{fit.describe()}, x_ref={mapping.reference_value():g}, "
                f"rms={fit.rms:.3g}"
            )
        return lines

    # ------------------------------------------------------------ set file
    def to_set_payload(self) -> list[dict]:
        return [mapping.to_dict() for mapping in self.mappings()]

    @staticmethod
    def mappings_from_payload(items: Iterable[MappingType[str, Any]]) -> list[Mapping]:
        return [Mapping.from_dict(item) for item in items]


def evaluate_points(mapping: Mapping, count: int = 400):
    """Dense ``(x, y)`` of the fit across the CSV range, for plotting."""

    if mapping.fit is None or not mapping.source_values:
        return np.array([]), np.array([])
    x = np.asarray(mapping.source_values, dtype=float)
    grid = np.linspace(float(x.min()), float(x.max()), count)
    return grid, np.asarray(mapping.fit.evaluate(grid), dtype=float)
