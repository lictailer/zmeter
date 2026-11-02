"""Fixed scan levels for array getters.

Choosing an array getter (see ``core.array_getters``) on the innermost user
level inserts one locked "fixed" level per array axis below the user's levels.
The last array axis becomes level0, the one before it level1, and so on; the
user's levels shift up by the number of axes.  The array getters themselves
are moved onto fixed level0, so ``level_data_arrays[0]`` holds every array
with the same nested layout as an ordinary scan.

A fixed level is an ordinary level dictionary with one extra key::

    "fixed_axis": {"channel": "andor_0_spectrum", "axis": 0, "name": "pixel",
                   "units": "counts"}

``axis`` is the array axis index (0 = first axis of the array).  Its setter is
``none`` with the axis coordinates as explicit destinations, so plots can use
``L0S0_none`` for the calibrated axis and ``level0`` for the point index.

``sync_fixed_levels`` is the only place that adds, removes or rebuilds fixed
levels.  It is idempotent and returns the old-to-new level mapping so plot
tokens and averaged-getter tokens can be renumbered with ``remap_plots`` and
``remap_level_getters``.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import re

import numpy as np

FIXED_AXIS_KEY = "fixed_axis"

_AVERAGE_TOKEN = re.compile(r"^level(\d+)_average_(.+)$")
_LEVEL_TOKEN = re.compile(r"^level(\d+)$")
_PLOT_CHANNEL_TOKEN = re.compile(r"^L(\d+)([SG])(\d+)_(.*)$")


@dataclass
class SyncResult:
    levels: dict
    mapping: dict = field(default_factory=dict)  # old index -> new index or None
    changed: bool = False
    warnings: list = field(default_factory=list)

    @property
    def renumbered(self) -> bool:
        return any(old != new for old, new in self.mapping.items())


def is_fixed_level(level_info) -> bool:
    return isinstance(level_info, dict) and isinstance(
        level_info.get(FIXED_AXIS_KEY), dict
    )


def ordered_levels(levels) -> list:
    """Level dictionaries sorted by their ``levelN`` index."""
    items = []
    for key, info in (levels or {}).items():
        match = _LEVEL_TOKEN.match(str(key))
        index = int(match.group(1)) if match else len(items)
        items.append((index, info))
    items.sort(key=lambda item: item[0])
    return [info for _, info in items]


def fixed_level_count(levels) -> int:
    """Number of fixed levels at the bottom of ``levels``."""
    count = 0
    for info in ordered_levels(levels):
        if not is_fixed_level(info):
            break
        count += 1
    return count


def innermost_user_level(levels):
    """Index of the innermost user level, or ``None``."""
    for index, info in enumerate(ordered_levels(levels)):
        if not is_fixed_level(info):
            return index
    return None


def _real_getters(info):
    return [g for g in info.get("getters", []) if isinstance(g, str) and g != "none"]


def array_channels(levels) -> list:
    """Array getter channels of a synced scan (the getters on fixed level0)."""
    ordered = ordered_levels(levels)
    if not ordered or not is_fixed_level(ordered[0]):
        return []
    return _real_getters(ordered[0])


def build_fixed_level(channel, axis_index, axis_name, values, units="", template=None):
    values = [float(v) for v in values]
    count = len(values)
    level = copy.deepcopy(template) if isinstance(template, dict) else {}
    level.update(
        {
            "setters": {
                "setter0": {
                    "channel": "none",
                    "explicit": True,
                    "linear_setting": {
                        "start": 0,
                        "end": max(count - 1, 0),
                        "step": 1,
                        "mid": max(count - 1, 0) / 2,
                        "span": max(count - 1, 0),
                        "points": count,
                        "destinations": list(range(count)),
                    },
                    "explicit_setting": list(values),
                    "destinations": list(values),
                }
            },
            "setting_method": "",
            "getters": ["none"],
            "settle_time": 0.0,
            "start_wait_time": 0.0,
            "manual_set_before": [],
            "manual_set_after": [],
            "setting_array": np.array([values], dtype=float),
            FIXED_AXIS_KEY: {
                "channel": str(channel),
                "axis": int(axis_index),
                "name": str(axis_name),
                "units": str(units or ""),
            },
        }
    )
    return level


def _fixed_values(info):
    setter = info.get("setters", {}).get("setter0", {})
    values = setter.get("destinations", setter.get("explicit_setting", []))
    return [float(v) for v in np.asarray(values, dtype=float).ravel()]


def _matches(existing_fixed, array_info):
    """Whether existing fixed levels already describe ``array_info``'s axes."""
    if len(existing_fixed) != array_info.ndim:
        return False
    for level_index, info in enumerate(existing_fixed):
        axis_index = array_info.ndim - 1 - level_index
        marker = info.get(FIXED_AXIS_KEY, {})
        if marker.get("axis") != axis_index:
            return False
        if marker.get("name") != array_info.axes[axis_index]:
            return False
        if len(_fixed_values(info)) != array_info.shape[axis_index]:
            return False
    return True


def _values_equal(existing_fixed, array_info):
    for level_index, info in enumerate(existing_fixed):
        axis_index = array_info.ndim - 1 - level_index
        if not np.allclose(
            _fixed_values(info), array_info.axis_values[axis_index], equal_nan=True
        ):
            return False
    return True


def remap_average_token(token, mapping):
    """Renumber ``levelN_average_ch``; ``None`` when level N was removed."""
    if not isinstance(token, str):
        return token
    match = _AVERAGE_TOKEN.match(token)
    if match is None:
        return token
    new_level = mapping.get(int(match.group(1)), int(match.group(1)))
    if new_level is None:
        return None
    return f"level{new_level}_average_{match.group(2)}"


def remap_level_getters(levels_list, mapping):
    """Renumber averaged getters of every user level in place."""
    changed = False
    for info in levels_list:
        if is_fixed_level(info):
            continue
        getters = info.get("getters", [])
        output = []
        for getter in getters:
            new_getter = remap_average_token(getter, mapping)
            if new_getter is None:
                changed = True
                continue
            if new_getter != getter:
                changed = True
            output.append(new_getter)
        if not output:
            output = ["none"]
        if output != getters:
            info["getters"] = output
    return changed


def remap_plot_token(token, mapping, levels=None):
    """Renumber one plot token after a level remap.

    ``levelN`` and ``LxSy_ch`` follow the level mapping.  ``LxGy_ch`` also
    follows its channel: getter positions can move when array getters leave a
    level, so the index is looked up again in ``levels`` (the new levels).
    Returns ``""`` when the token no longer points anywhere.
    """
    if not isinstance(token, str) or token in ("", "None"):
        return token
    level_match = _LEVEL_TOKEN.match(token)
    if level_match is not None:
        new_level = mapping.get(int(level_match.group(1)), int(level_match.group(1)))
        return "" if new_level is None else f"level{new_level}"
    plot_match = _PLOT_CHANNEL_TOKEN.match(token)
    if plot_match is None:
        return token
    old_level, kind, index, channel = plot_match.groups()
    new_level = mapping.get(int(old_level), int(old_level))
    if kind == "G":
        channel = remap_average_token(channel, mapping)
        if channel is None:
            return ""
    if new_level is None:
        if kind == "S":
            return ""
        new_level = None
    if kind == "S":
        return f"L{new_level}S{index}_{channel}"
    if levels is None:
        return "" if new_level is None else f"L{new_level}G{index}_{channel}"
    ordered = ordered_levels(levels)
    search = []
    if new_level is not None and new_level < len(ordered):
        search.append(new_level)
    search.extend(i for i in range(len(ordered)) if i not in search)
    for level_index in search:
        getters = ordered[level_index].get("getters", [])
        if channel in getters:
            return f"L{level_index}G{getters.index(channel)}_{channel}"
    return ""


def remap_plots(plots, mapping, levels=None):
    """Return a renumbered copy of a scan's ``plots`` dictionary."""
    output = copy.deepcopy(plots) if isinstance(plots, dict) else {}
    for kind in ("line_plots", "image_plots"):
        group = output.get(kind)
        if not isinstance(group, dict):
            continue
        for plot in group.values():
            if not isinstance(plot, dict):
                continue
            for field_name, token in list(plot.items()):
                plot[field_name] = remap_plot_token(token, mapping, levels)
    return output


def sync_fixed_levels(levels, catalog, *, refresh=False):
    """Add, keep, rebuild or remove fixed levels so they match the getters.

    ``levels`` is the scan's ``levels`` dictionary (not modified).  ``catalog``
    provides ``is_array(channel)`` and ``info(channel)`` (an
    ``ArrayCatalog``).  With ``refresh`` the axis values are re-read from the
    device even when the shape is unchanged (done at scan start).

    Rules:
    * array getters are taken only from the innermost user level and moved
      to fixed level0; on outer user levels they are dropped with a warning;
    * all array getters of one scan must share one shape; a getter with a
      different shape is dropped with a warning;
    * an array getter whose device is offline keeps its existing fixed levels;
    * with no array getter left, every fixed level is removed.
    """
    ordered = ordered_levels(levels)
    levels_copy = copy.deepcopy(ordered)
    old_count = len(levels_copy)
    old_fixed = [info for info in levels_copy if is_fixed_level(info)]
    user = [info for info in levels_copy if not is_fixed_level(info)]
    old_user_positions = [i for i, info in enumerate(levels_copy) if not is_fixed_level(info)]
    old_fixed_positions = [i for i, info in enumerate(levels_copy) if is_fixed_level(info)]
    warnings = []

    # Fixed levels must sit at the bottom; anything else is rebuilt below.
    misplaced = old_fixed_positions != list(range(len(old_fixed)))

    existing_tokens = []
    for info in old_fixed:
        for token in _real_getters(info):
            if token not in existing_tokens:
                existing_tokens.append(token)

    # Pull array getters off user levels.
    original_first = list(user[0].get("getters", [])) if user else []
    moved_tokens = []
    for position, info in enumerate(user):
        getters = list(info.get("getters", []))
        kept = []
        for getter in getters:
            if isinstance(getter, str) and getter != "none" and catalog.is_array(getter):
                if position == 0:
                    if getter not in moved_tokens and getter not in existing_tokens:
                        moved_tokens.append(getter)
                else:
                    warnings.append(
                        f"{getter} is an array getter; it can only be recorded on the "
                        "innermost level and was removed from an outer level."
                    )
                continue
            kept.append(getter)
        if kept != getters:
            info["getters"] = kept or ["none"]

    tokens = existing_tokens + moved_tokens

    # Resolve shapes.  Existing tokens come first so they set the shape.
    reference = None
    accepted = []
    unresolved = []
    for token in tokens:
        info = catalog.info(token)
        if info is None:
            unresolved.append(token)
            accepted.append(token)
            continue
        if reference is None:
            reference = info
            accepted.append(token)
            continue
        if info.axes == reference.axes and info.shape == reference.shape:
            accepted.append(token)
        else:
            warnings.append(
                f"{info.label()} does not match {reference.label()}; all array "
                "getters of one scan must have the same shape, so it was not added."
            )
    tokens = accepted

    if not tokens:
        new_fixed = []
    elif reference is None:
        # Device offline: keep what the file says.
        new_fixed = list(old_fixed)
        if new_fixed:
            new_fixed[0]["getters"] = list(tokens)
        elif user:
            # Nothing describes the shape yet: leave the getters on the user
            # level until the device is available.
            user[0]["getters"] = original_first
            tokens = []
    elif (not misplaced) and _matches(old_fixed, reference) and not (
        refresh and not _values_equal(old_fixed, reference)
    ):
        new_fixed = list(old_fixed)
        if _real_getters(new_fixed[0]) != tokens:
            new_fixed[0]["getters"] = list(tokens)
    else:
        new_fixed = []
        for level_index in range(reference.ndim):
            axis_index = reference.ndim - 1 - level_index
            template = old_fixed[level_index] if level_index < len(old_fixed) else None
            new_fixed.append(
                build_fixed_level(
                    reference.channel,
                    axis_index,
                    reference.axes[axis_index],
                    reference.axis_values[axis_index],
                    reference.units,
                    template=template,
                )
            )
        new_fixed[0]["getters"] = list(tokens)

    for level_index, info in enumerate(new_fixed):
        if level_index > 0 and _real_getters(info):
            info["getters"] = ["none"]

    new_list = new_fixed + user
    new_fixed_count = len(new_fixed)

    mapping = {}
    for rank, old_index in enumerate(old_user_positions):
        mapping[old_index] = new_fixed_count + rank
    for rank, old_index in enumerate(old_fixed_positions):
        mapping[old_index] = rank if rank < new_fixed_count else None

    if any(old != new for old, new in mapping.items()):
        remap_level_getters(user, mapping)

    changed = (
        misplaced
        or len(new_list) != old_count
        or any(old != new for old, new in mapping.items())
        or not _levels_equal(ordered, new_list)
    )
    new_levels = {f"level{i}": info for i, info in enumerate(new_list)}
    return SyncResult(new_levels, mapping, changed, warnings)


def _values_same(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_values_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple, np.ndarray)) or isinstance(b, (list, tuple, np.ndarray)):
        try:
            a_arr = np.asarray(a, dtype=float)
            b_arr = np.asarray(b, dtype=float)
        except (TypeError, ValueError):
            if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
                return len(a) == len(b) and all(_values_same(x, y) for x, y in zip(a, b))
            return False
        return a_arr.shape == b_arr.shape and bool(np.array_equal(a_arr, b_arr, equal_nan=True))
    try:
        return bool(a == b)
    except Exception:  # noqa: BLE001
        return False


def _levels_equal(old_list, new_list):
    if len(old_list) != len(new_list):
        return False
    return all(_values_same(a, b) for a, b in zip(old_list, new_list))


def fixed_block_shape(levels):
    """Expected array shape of the scan's array getters (array axis order)."""
    ordered = ordered_levels(levels)
    count = fixed_level_count(levels)
    return tuple(len(_fixed_values(ordered[k])) for k in range(count - 1, -1, -1))


def user_point_count(levels) -> int:
    """Points of the user levels only (fixed levels are one read)."""
    total = 1
    for info in ordered_levels(levels):
        if is_fixed_level(info):
            continue
        array = info.get("setting_array")
        if array is None:
            continue
        total *= int(np.asarray(array).shape[-1])
    return total
